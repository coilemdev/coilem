import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { getPublicFieldFrame, type PublicSolveProgress } from './api';
import {
  FieldResultPlot,
  warmFieldResultPlot,
  type FieldColorRangeMode,
  type FieldLineDensity,
  type FieldLineOverlay,
  type FieldProbe,
  type FieldProbeDescription,
  type FieldResultRaster,
} from './FieldResultPlot';
import { normalizeFieldPlaybackManifest } from './fieldPlaybackContract';
import { statorSteelSaturationTicks } from './fluxColorScale';
import {
  FieldPlaybackRasterizer,
  type FieldRasterSource,
} from './fieldPlaybackRasterizer';
import {
  advancePlaybackElectricalAngle,
  advanceWindowPlaybackAngle,
  normalizePlaybackElectricalAngle,
  playbackCycleSpanDeg,
  playbackFrameStride,
  playbackLookaheadFrameIndices,
  playbackSpanOf,
  playbackStrideFrameIndex,
  positionSliderFrameIndex,
  positionSliderRange,
  positionSliderValue,
  PUBLIC_FIELD_PLAYBACK_DEFAULT_RPM,
  PUBLIC_FIELD_PLAYBACK_MAX_RPM,
  PUBLIC_FIELD_PLAYBACK_MIN_RPM,
  publicFieldPlaybackBufferFrames,
  publicFieldPlaybackCacheFrames,
  scrubNeighbourIndices,
  windowLookaheadFrameIndices,
  windowPlaybackFrameIndex,
} from './fieldPlaybackTiming';
import { LatestFrameLoader } from './latestFrameLoader';
import { RpmField } from './RpmField';
import { rotorAirgapBoundaryRadiusMm } from './motorAirgap';
import type {
  GeometryPreview,
  MaterialCatalog,
  MotorConfig,
  PublicAirgapProfileDescriptor,
  PublicArmatureFieldComposition,
  PublicFieldFrameDescriptor,
  PublicFieldLinePlot,
  PublicFieldPlaybackManifest,
  SolveResult,
} from './model';

type FieldSource = 'resultant' | 'pm' | 'armature';
// Stator + PM draws the PM-only field's lines over the stator-only field (#120).
type FieldView = FieldSource | 'stator_pm';
// A stator frame pairs with the PM frame at the same rotor position.
const OVERLAY_ANGLE_TOLERANCE_DEG = 1e-3;
// Public playback turns clockwise (the solve angle convention).
const CLOCKWISE_FIELD_AXES = { rotation: 'clockwise' } as const;
const IDLE_BUFFER_FRAMES = 4;
const DETAIL_VIEWPORT_SCALE = 1.08;
const MAX_PLAYBACK_CATCHUP_MS = 250;
// While the position slider moves, each position shows its fast playback
// raster. The exact ~11 MB solver frame loads only once the slider rests.
const EXACT_FRAME_SETTLE_MS = 200;
const FIELD_LINE_DENSITY_STOPS: readonly FieldLineDensity[] = ['low', 'medium', 'high'];

function prepareFrameForPlayback(
  frame: PublicFieldLinePlot,
  source: FieldSource,
): Promise<PublicFieldLinePlot> {
  return new Promise((resolve) => {
    const prepare = () => {
      // Warm only the composition on screen; the other prepares on demand.
      warmFieldResultPlot(source === 'pm' ? frame.noload_plot ?? frame : frame);
      resolve(frame);
    };
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(prepare, { timeout: 180 });
    } else {
      window.setTimeout(prepare, 0);
    }
  });
}

function rasterCacheKey(artifactId: string, source: FieldRasterSource, withMesh = false): string {
  return `${source}:${withMesh ? 'mesh:' : ''}${artifactId}`;
}

// Playback rasters skip the mesh layer while it is hidden. One decoded with
// its mesh also serves a view without it.
function cachedRaster(
  cache: Record<string, FieldResultRaster>,
  artifactId: string,
  source: FieldRasterSource,
  withMesh: boolean,
): FieldResultRaster | undefined {
  return cache[rasterCacheKey(artifactId, source, true)]
    ?? (withMesh ? undefined : cache[rasterCacheKey(artifactId, source)]);
}

function closeRaster(raster: FieldResultRaster): void {
  raster.base.close();
  raster.heat.close();
  raster.mesh?.close();
  raster.lines.close();
}

// Drop the oldest rasters beyond the limit, keeping the ones on screen or about
// to play. Kept rasters may briefly hold the cache above its limit.
function evictRasters(
  cache: Record<string, FieldResultRaster>,
  limit: number,
  keep: ReadonlySet<string>,
  retire: (raster: FieldResultRaster) => void,
): void {
  let excess = Object.keys(cache).length - limit;
  for (const key of Object.keys(cache)) {
    if (excess <= 0) return;
    if (keep.has(key)) continue;
    retire(cache[key]);
    delete cache[key];
    excess -= 1;
  }
}

function readableFieldRegion(region: string): string {
  const normalized = region.replace(/[_-]+/g, ' ').trim();
  if (/stator.*tooth|tooth.*stator/i.test(normalized)) return 'Stator tooth';
  if (/stator.*yoke|yoke.*stator/i.test(normalized)) return 'Stator yoke';
  if (/stator/i.test(normalized)) return 'Stator steel';
  if (/rotor/i.test(normalized)) return 'Rotor steel';
  if (/magnet/i.test(normalized)) return 'Permanent magnet';
  if (/slot|winding|coil|copper/i.test(normalized)) return 'Winding region';
  if (/air.?gap/i.test(normalized)) return 'Air gap';
  if (/air/i.test(normalized)) return 'Air';
  return normalized || 'Unclassified region';
}

function describeFieldProbe(probe: FieldProbe, config: MotorConfig): FieldProbeDescription {
  const regionLabel = readableFieldRegion(probe.region);
  const isStatorSteel = /stator|tooth|yoke/i.test(probe.region);
  const isRotorSteel = /rotor/i.test(probe.region) && !/magnet/i.test(probe.region);
  if (isStatorSteel || isRotorSteel) {
    const materialLabel = isStatorSteel
      ? config.materials.stator_steel
      : config.materials.rotor_steel;
    if (probe.bMagT >= 1.6) {
      return {
        regionLabel,
        materialLabel,
        saturationLabel: 'Above the 1.4–1.6 T reference knee',
        saturationTone: 'warning',
      };
    }
    if (probe.bMagT >= 1.4) {
      return {
        regionLabel,
        materialLabel,
        saturationLabel: 'Within the 1.4–1.6 T reference knee',
        saturationTone: 'warning',
      };
    }
    return {
      regionLabel,
      materialLabel,
      saturationLabel: 'Below the 1.4–1.6 T reference knee',
      saturationTone: 'good',
    };
  }
  if (/magnet/i.test(probe.region)) {
    return {
      regionLabel,
      materialLabel: config.materials.magnet_grade,
      saturationLabel: 'Steel saturation does not apply',
      saturationTone: 'neutral',
    };
  }
  if (/slot|winding|coil|copper/i.test(probe.region)) {
    return {
      regionLabel,
      materialLabel: config.materials.conductor,
      saturationLabel: 'Approximately nonmagnetic · μr ≈ 1',
      saturationTone: 'neutral',
    };
  }
  return {
    regionLabel,
    materialLabel: /air/i.test(probe.region) ? 'Air' : 'Solver region',
    saturationLabel: 'No steel saturation assessment',
    saturationTone: 'neutral',
  };
}

interface SolvedFieldViewerProps {
  viewControls: ReactNode;
  expandControl?: ReactNode;
  config: MotorConfig;
  /** The material catalog, for the stator steel's knee and saturation ticks. */
  materials?: MaterialCatalog | null;
  geometry: GeometryPreview | null;
  result: SolveResult;
  armature: PublicArmatureFieldComposition | null;
  armatureBusy: boolean;
  armatureError: string | null;
  armatureProgress: PublicSolveProgress | null;
  magnetoCompositionAvailable: boolean;
  onRequestArmature: () => void;
  onCancelArmature: () => void;
}

function nearestFrame(
  frames: PublicFieldFrameDescriptor[],
  electricalAngleDeg: number,
): PublicFieldFrameDescriptor | null {
  return frames.reduce<PublicFieldFrameDescriptor | null>((nearest, frame) => (
    nearest === null
      || Math.abs(frame.angle_deg - electricalAngleDeg) < Math.abs(nearest.angle_deg - electricalAngleDeg)
      ? frame
      : nearest
  ), null);
}

function nearestAirgapProfile(
  profiles: PublicAirgapProfileDescriptor[],
  electricalAngleDeg: number,
): PublicAirgapProfileDescriptor | null {
  return profiles.reduce<PublicAirgapProfileDescriptor | null>((nearest, profile) => (
    nearest === null
      || Math.abs(profile.angle_deg - electricalAngleDeg) < Math.abs(nearest.angle_deg - electricalAngleDeg)
      ? profile
      : nearest
  ), null);
}

function playbackDescriptors(
  manifest: PublicFieldPlaybackManifest | null | undefined,
  fallback: PublicFieldFrameDescriptor[],
  airgapProfiles: PublicAirgapProfileDescriptor[] = [],
): PublicFieldFrameDescriptor[] {
  const sequence = normalizeFieldPlaybackManifest(manifest);
  if (!sequence || sequence.timeline.kind !== 'angle') return fallback;
  return sequence.frames.flatMap((frame) => {
    const composition = frame.compositions.resultant
      ?? frame.compositions.armature
      ?? frame.compositions.pm;
    if (!composition) return [];
    const solvedFrame = nearestFrame(fallback, frame.angle_deg);
    const airgapProfile = nearestAirgapProfile(airgapProfiles, frame.angle_deg);
    return [{
      angle_deg: frame.angle_deg,
      field_frame_artifact: {
        artifact_id: frame.numerical_artifact?.artifact_id ?? composition.base.artifact_id,
      },
      has_pm_only: Boolean(frame.compositions.pm),
      airgap_brbt: airgapProfile?.airgap_brbt ?? solvedFrame?.airgap_brbt ?? null,
      playback_frame: frame,
    }];
  });
}

export function SolvedFieldViewer({
  viewControls,
  expandControl,
  config,
  materials = null,
  geometry,
  result,
  armature,
  armatureBusy,
  armatureError,
  armatureProgress,
  magnetoCompositionAvailable,
  onRequestArmature,
  onCancelArmature,
}: SolvedFieldViewerProps) {
  const resultantFrames = useMemo(
    () => playbackDescriptors(result.field_playback, result.field_line_frames ?? []),
    [result.field_line_frames, result.field_playback],
  );
  const armatureFrames = useMemo(
    () => playbackDescriptors(
      armature?.field_playback,
      armature?.frames ?? [],
      armature?.airgap_profiles ?? [],
    ),
    [armature?.airgap_profiles, armature?.field_playback, armature?.frames],
  );
  const [view, setView] = useState<FieldView>('resultant');
  const overlayActive = view === 'stator_pm';
  // Stator + PM loads, caches and plays the stator field as Stator only does;
  // the PM frame at the same position loads beside it.
  const source: FieldSource = overlayActive ? 'armature' : view;
  const sourceRef = useRef<FieldSource>('resultant');
  sourceRef.current = source;
  const [frameIndex, setFrameIndex] = useState(0);
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [showMesh, setShowMesh] = useState(false);
  const showMeshRef = useRef(false);
  showMeshRef.current = showMesh;
  const [showFieldLines, setShowFieldLines] = useState(true);
  const [showMagnets, setShowMagnets] = useState(true);
  const [showAirgap, setShowAirgap] = useState(false);
  const [showPoleLabels, setShowPoleLabels] = useState(false);
  const [fieldLineDensity, setFieldLineDensity] = useState<FieldLineDensity>('medium');
  const [colorRangeMode, setColorRangeMode] = useState<FieldColorRangeMode>('fixed');
  const saturationTicks = useMemo(() => statorSteelSaturationTicks(config, materials), [config, materials]);
  const [playing, setPlaying] = useState(false);
  const [playbackRpm, setPlaybackRpm] = useState(PUBLIC_FIELD_PLAYBACK_DEFAULT_RPM);
  const playbackRpmRef = useRef(PUBLIC_FIELD_PLAYBACK_DEFAULT_RPM);
  playbackRpmRef.current = playbackRpm;
  const playbackElectricalAngleRef = useRef(0);
  const playbackSliderRef = useRef<HTMLInputElement>(null);
  const [playbackWaiting, setPlaybackWaiting] = useState(false);
  const [frameCache, setFrameCache] = useState<Record<string, PublicFieldLinePlot>>({});
  const [rasterCache, setRasterCache] = useState<Record<string, FieldResultRaster>>({});
  const frameCacheRef = useRef<Record<string, PublicFieldLinePlot>>({});
  const rasterCacheRef = useRef<Record<string, FieldResultRaster>>({});
  const frameRequestsRef = useRef<Map<string, Promise<PublicFieldLinePlot>>>(new Map());
  const rasterRequestsRef = useRef<Map<string, Promise<FieldResultRaster | null>>>(new Map());
  const rasterizerRef = useRef<FieldPlaybackRasterizer | null>(null);
  const activeRasterKeyRef = useRef<string | null>(null);
  const frameGenerationRef = useRef(0);
  const frameIndexRef = useRef(0);
  const [retainedPlot, setRetainedPlot] = useState<{ source: FieldSource; plot: PublicFieldLinePlot } | null>(null);
  const [frameLoading, setFrameLoading] = useState(false);
  const [frameError, setFrameError] = useState<string | null>(null);
  const [settledArtifactId, setSettledArtifactId] = useState<string | null>(null);
  // The last frame drawn, kept on screen while the slider's next one decodes.
  const [heldRaster, setHeldRaster] = useState<{
    source: FieldSource;
    raster: FieldResultRaster;
    angleDeg: number;
  } | null>(null);
  // The last PM overlay drawn, kept while the next position's decodes.
  const [heldOverlayRaster, setHeldOverlayRaster] = useState<FieldResultRaster | null>(null);
  // While the slider is dragged, only its newest position loads (#59).
  const [scrubbing, setScrubbing] = useState(false);
  const [scrubDirection, setScrubDirection] = useState<1 | -1>(1);
  const scrubIdleTimerRef = useRef<number | null>(null);
  const frameLoaderRef = useRef(new LatestFrameLoader<FieldResultRaster | null>());
  // Two loads can finish out of order; only a newer request replaces the frame shown.
  const frameRequestSeqRef = useRef(0);
  const shownRequestSeqRef = useRef(0);
  const [fieldViewportScale, setFieldViewportScale] = useState(1);
  const [detailPlot, setDetailPlot] = useState<{
    artifactId: string;
    source: FieldSource;
    plot: PublicFieldLinePlot;
  } | null>(null);
  const [detailRaster, setDetailRaster] = useState<{
    key: string;
    raster: FieldResultRaster;
  } | null>(null);
  const detailRasterRef = useRef<{
    key: string;
    raster: FieldResultRaster;
  } | null>(null);
  const detailRequestRef = useRef(0);
  // A slider update renders at a higher priority than a queued cache update,
  // so React can still render a raster that an eviction has already dropped.
  // Retired rasters are closed only once a committed render no longer shows
  // them; closing them sooner made drawImage throw on a detached bitmap.
  const retiredRastersRef = useRef<Set<FieldResultRaster>>(new Set());
  const retireRaster = useCallback((raster: FieldResultRaster) => {
    retiredRastersRef.current.add(raster);
  }, []);
  const replaceDetailRaster = useCallback((next: {
    key: string;
    raster: FieldResultRaster;
  } | null) => {
    const current = detailRasterRef.current;
    if (current && current.raster !== next?.raster) retireRaster(current.raster);
    detailRasterRef.current = next;
    setDetailRaster(next);
  }, [retireRaster]);

  // Public Magneto2D solves already map increasing UI angles to the solver's
  // negative (clockwise) native rotor positions. Preserve the stored,
  // increasing 0..360° electrical sequence here; reversing it would apply the
  // direction conversion twice and make the motor play counterclockwise.
  const angleFrames = resultantFrames.length > 0 ? resultantFrames : armatureFrames;
  const boundedIndex = Math.min(frameIndex, Math.max(0, angleFrames.length - 1));
  const playbackSpanDeg = playbackCycleSpanDeg(angleFrames);
  // A Preview run solves only a window of the cycle; the slider covers it once.
  const playbackSpan = useMemo(() => playbackSpanOf(angleFrames), [angleFrames]);
  const playbackSpanRef = useRef(playbackSpan);
  playbackSpanRef.current = playbackSpan;
  const sliderRange = positionSliderRange(playbackSpan);
  const streamingArmatureFrame = source === 'armature' && armatureBusy
    ? armatureFrames[armatureFrames.length - 1] ?? null
    : null;
  const electricalAngleDeg = streamingArmatureFrame?.angle_deg
    ?? angleFrames[boundedIndex]?.angle_deg
    ?? 0;
  const sourceFrames = source === 'armature' ? armatureFrames : resultantFrames;
  const descriptor = streamingArmatureFrame ?? nearestFrame(sourceFrames, electricalAngleDeg);
  const artifactId = descriptor?.field_frame_artifact.artifact_id ?? null;
  const exactFrameSettled = artifactId !== null && settledArtifactId === artifactId;
  const overlayDescriptor = overlayActive && descriptor
    ? nearestFrame(resultantFrames, descriptor.angle_deg)
    : null;
  const overlayArtifactId = overlayDescriptor && descriptor
    && Math.abs(overlayDescriptor.angle_deg - descriptor.angle_deg) <= OVERLAY_ANGLE_TOLERANCE_DEG
    ? overlayDescriptor.field_frame_artifact.artifact_id
    : null;
  const overlayRasterKeyRef = useRef<string | null>(null);
  overlayRasterKeyRef.current = overlayArtifactId ? rasterCacheKey(overlayArtifactId, 'pm') : null;
  const overlayRaster = overlayArtifactId ? cachedRaster(rasterCache, overlayArtifactId, 'pm', false) ?? null : null;
  const overlayPlot = overlayArtifactId ? frameCache[overlayArtifactId]?.noload_plot ?? null : null;
  const visibleOverlayRaster = overlayActive ? overlayRaster ?? heldOverlayRaster : null;
  const fieldLineOverlay = useMemo<FieldLineOverlay | null>(
    () => (overlayActive && (visibleOverlayRaster || overlayPlot)
      ? { raster: visibleOverlayRaster, plot: overlayPlot }
      : null),
    [overlayActive, overlayPlot, visibleOverlayRaster],
  );
  const activeRasterKey = artifactId ? rasterCacheKey(artifactId, source, showMesh) : null;
  activeRasterKeyRef.current = activeRasterKey;
  const activeRaster = artifactId ? cachedRaster(rasterCache, artifactId, source, showMesh) ?? null : null;
  // Turning the mesh on keeps the frame without it until its mesh layer loads.
  const meshlessRaster = artifactId && showMesh ? rasterCache[rasterCacheKey(artifactId, source)] ?? null : null;
  const detailRasterKey = artifactId ? rasterCacheKey(artifactId, source) : null;
  const activeDetailRaster = detailRaster?.key === detailRasterKey
    ? detailRaster.raster
    : null;
  const artifactFrame = artifactId ? frameCache[artifactId] : null;
  const selectedPlot = source === 'pm'
    ? artifactFrame?.noload_plot ?? null
    : artifactFrame;
  const fallbackPlot = source === 'resultant'
    && (resultantFrames.length === 0 || Math.abs(electricalAngleDeg) < 1e-9)
    ? result.field_line_plot ?? null
    : null;
  const activePlot = selectedPlot ?? fallbackPlot;
  const activeDetailPlot = detailPlot?.artifactId === artifactId && detailPlot.source === source
    ? detailPlot.plot
    : null;
  const exactVectorPlot = activePlot ?? activeDetailPlot;
  const armatureReferencePlot = source === 'armature' && armatureBusy
    ? retainedPlot?.plot ?? result.field_line_plot ?? null
    : null;
  const visiblePlot = exactVectorPlot
    ?? (retainedPlot?.source === source ? retainedPlot.plot : null)
    ?? armatureReferencePlot;
  // A frame still decoding keeps the last one drawn on screen, with the magnets
  // at its angle, instead of an older exact frame, so dragging the slider
  // never jumps backwards (#59).
  const heldFrame = !activeRaster && !meshlessRaster && !exactVectorPlot && heldRaster?.source === source
    ? heldRaster
    : null;
  const visibleRaster = activeRaster ?? meshlessRaster ?? heldFrame?.raster ?? null;
  const currentPeakBT = useMemo(() => {
    const rasterPeak = activeDetailRaster?.maxB ?? visibleRaster?.maxB;
    if (Number.isFinite(rasterPeak)) return rasterPeak ?? 0;
    const values = visiblePlot?.element_b_mag_t.filter(Number.isFinite) ?? [];
    return values.reduce((peak, value) => Math.max(peak, value), 0);
  }, [activeDetailRaster?.maxB, visiblePlot, visibleRaster?.maxB]);
  const describeProbe = useCallback(
    (probe: FieldProbe) => describeFieldProbe(probe, config),
    [config],
  );
  const polePairs = Math.max(1, config.rotor.pole_count / 2);
  const mechanicalAngleDeg = electricalAngleDeg / polePairs;
  const statorPolarityRotationDeg = source === 'armature'
    && armature?.field_playback
    && (armature.airgap_profiles?.length ?? 0) < 2
    && armature.frames.length <= 1
    // Magneto2D advances the displayed sweep with a negative mechanical
    // rotation. Match that convention when an older cached playback has only
    // the frame-zero polarity profile.
    ? -mechanicalAngleDeg
    : 0;
  const pmAvailable = resultantFrames.some((frame) => frame.has_pm_only);
  const hasMagnets = Boolean(geometry?.regions.some((region) => /magnet/i.test(region.region_type)));
  const desiredBufferFrames = Math.max(
    IDLE_BUFFER_FRAMES,
    publicFieldPlaybackBufferFrames(playbackRpm),
  );
  const playbackStride = playbackFrameStride(
    angleFrames.length,
    playbackSpanDeg,
    playbackRpm,
    polePairs,
  );
  const playbackStrideRef = useRef(playbackStride);
  playbackStrideRef.current = playbackStride;
  const rasterCacheLimit = publicFieldPlaybackCacheFrames(
    playbackRpm,
    Math.ceil(angleFrames.length / playbackStride),
  ) * (overlayActive ? 2 : 1);
  const rasterCacheLimitRef = useRef(rasterCacheLimit);
  rasterCacheLimitRef.current = rasterCacheLimit;
  const playbackLookaheadIndices = useMemo(
    () => playbackLookaheadFrameIndices(
      angleFrames,
      electricalAngleDeg,
      playbackRpm,
      polePairs,
      desiredBufferFrames,
    ),
    [
      angleFrames,
      desiredBufferFrames,
      electricalAngleDeg,
      playbackRpm,
      polePairs,
    ],
  );
  // Playing preloads the frames it shows next. Stopped, the slider preloads a
  // few positions in the direction it was last dragged, and nothing while it
  // is being dragged.
  const preloadIndices = useMemo(() => {
    if (playing) {
      return playbackSpan.windowed
        ? windowLookaheadFrameIndices(angleFrames.length, boundedIndex, desiredBufferFrames)
        : playbackLookaheadIndices;
    }
    return scrubNeighbourIndices(angleFrames.length, boundedIndex, scrubDirection, !playbackSpan.windowed);
  }, [
    angleFrames.length,
    boundedIndex,
    desiredBufferFrames,
    playbackLookaheadIndices,
    playbackSpan.windowed,
    playing,
    scrubDirection,
  ]);
  const bufferTarget = preloadIndices.length;
  const bufferedAhead = useMemo(() => {
    let ready = 0;
    for (const preloadIndex of preloadIndices) {
      const preloadAngle = angleFrames[preloadIndex]?.angle_deg ?? 0;
      const preloadArtifactId = nearestFrame(sourceFrames, preloadAngle)?.field_frame_artifact.artifact_id;
      if (
        !preloadArtifactId
        || (
          !cachedRaster(rasterCache, preloadArtifactId, source, showMesh)
          && !frameCache[preloadArtifactId]
        )
      ) break;
      ready += 1;
    }
    return ready;
  }, [
    angleFrames,
    frameCache,
    preloadIndices,
    rasterCache,
    showMesh,
    source,
    sourceFrames,
  ]);
  const upcomingRasterKeys = useMemo(() => new Set(
    preloadIndices.flatMap((preloadIndex) => {
      const preloadAngle = angleFrames[preloadIndex]?.angle_deg ?? 0;
      const preloadArtifactId = nearestFrame(sourceFrames, preloadAngle)?.field_frame_artifact.artifact_id;
      const overlayArtifactIdAhead = overlayActive
        ? nearestFrame(resultantFrames, preloadAngle)?.field_frame_artifact.artifact_id
        : null;
      return [
        ...(preloadArtifactId
          ? [rasterCacheKey(preloadArtifactId, source), rasterCacheKey(preloadArtifactId, source, true)]
          : []),
        ...(overlayArtifactIdAhead
          ? [rasterCacheKey(overlayArtifactIdAhead, 'pm'), rasterCacheKey(overlayArtifactIdAhead, 'pm', true)]
          : []),
      ];
    }),
  ), [angleFrames, overlayActive, preloadIndices, resultantFrames, source, sourceFrames]);
  const upcomingRasterKeysRef = useRef(upcomingRasterKeys);
  upcomingRasterKeysRef.current = upcomingRasterKeys;
  const keptRasterKeys = useCallback((loadedKey?: string): Set<string> => {
    const keep = new Set(upcomingRasterKeysRef.current);
    if (loadedKey) keep.add(loadedKey);
    if (activeRasterKeyRef.current) {
      keep.add(activeRasterKeyRef.current);
      keep.add(activeRasterKeyRef.current.replace(/^([^:]+):mesh:/, '$1:'));
    }
    if (overlayRasterKeyRef.current) {
      keep.add(overlayRasterKeyRef.current);
      keep.add(overlayRasterKeyRef.current.replace(/^([^:]+):/, '$1:mesh:'));
    }
    return keep;
  }, []);

  const loadFrame = useCallback((requestedArtifactId: string): Promise<PublicFieldLinePlot> => {
    const cached = frameCacheRef.current[requestedArtifactId];
    if (cached) return Promise.resolve(cached);

    const pending = frameRequestsRef.current.get(requestedArtifactId);
    if (pending) return pending;

    const generation = frameGenerationRef.current;
    const request = getPublicFieldFrame(requestedArtifactId)
      .then(async (payload) => {
        const frame = payload.field_line_frame as unknown as PublicFieldLinePlot;
        await prepareFrameForPlayback(frame, sourceRef.current);
        if (frameGenerationRef.current === generation) {
          const nextCache = {
            ...frameCacheRef.current,
            [requestedArtifactId]: frame,
          };
          const cachedIds = Object.keys(nextCache);
          while (
            cachedIds.length
            > publicFieldPlaybackCacheFrames(playbackRpmRef.current)
          ) {
            const expiredId = cachedIds.shift();
            if (expiredId && expiredId !== requestedArtifactId) delete nextCache[expiredId];
          }
          frameCacheRef.current = nextCache;
          setFrameCache(nextCache);
        }
        return frame;
      })
      .finally(() => {
        if (frameRequestsRef.current.get(requestedArtifactId) === request) {
          frameRequestsRef.current.delete(requestedArtifactId);
        }
      });
    frameRequestsRef.current.set(requestedArtifactId, request);
    return request;
  }, []);

  const loadVisualFrame = useCallback((
    requestedDescriptor: PublicFieldFrameDescriptor,
    requestedSource: FieldRasterSource,
    withMesh = showMeshRef.current,
  ): Promise<FieldResultRaster | null> => {
    const requestedArtifactId = requestedDescriptor.field_frame_artifact.artifact_id;
    const key = rasterCacheKey(requestedArtifactId, requestedSource, withMesh);
    const cached = cachedRaster(rasterCacheRef.current, requestedArtifactId, requestedSource, withMesh);
    if (cached) return Promise.resolve(cached);
    const pending = rasterRequestsRef.current.get(key);
    if (pending) return pending;
    const generation = frameGenerationRef.current;
    const request = (rasterizerRef.current
      ? rasterizerRef.current.render(
        requestedArtifactId,
        requestedSource,
        requestedDescriptor.playback_frame,
        withMesh,
      )
      : Promise.reject(new Error('Field playback workers are unavailable.')))
      .then((raster) => {
        if (frameGenerationRef.current !== generation) {
          closeRaster(raster);
          return null;
        }
        const nextCache = {
          ...rasterCacheRef.current,
          [key]: raster,
        };
        evictRasters(nextCache, rasterCacheLimitRef.current, keptRasterKeys(key), retireRaster);
        rasterCacheRef.current = nextCache;
        setRasterCache(nextCache);
        return raster;
      })
      .catch(async (error: unknown) => {
        if (requestedDescriptor.playback_frame) throw error;
        await loadFrame(requestedArtifactId);
        return null;
      })
      .finally(() => {
        if (rasterRequestsRef.current.get(key) === request) {
          rasterRequestsRef.current.delete(key);
        }
      });
    rasterRequestsRef.current.set(key, request);
    return request;
  }, [keptRasterKeys, loadFrame, retireRaster]);

  useEffect(() => {
    const rasterizer = new FieldPlaybackRasterizer();
    rasterizerRef.current = rasterizer;
    return () => {
      if (rasterizerRef.current === rasterizer) rasterizerRef.current = null;
      rasterizer.dispose();
      if (detailRasterRef.current) closeRaster(detailRasterRef.current.raster);
      detailRasterRef.current = null;
    };
  }, []);

  useEffect(() => {
    const shown = new Set(Object.values(rasterCache));
    if (detailRaster) shown.add(detailRaster.raster);
    if (heldRaster) shown.add(heldRaster.raster);
    if (heldOverlayRaster) shown.add(heldOverlayRaster);
    retiredRastersRef.current.forEach((raster) => {
      if (shown.has(raster)) return;
      closeRaster(raster);
      retiredRastersRef.current.delete(raster);
    });
  }, [detailRaster, heldOverlayRaster, heldRaster, rasterCache]);

  const drawnRaster = activeRaster ?? meshlessRaster;
  useEffect(() => {
    if (drawnRaster) setHeldRaster({ source, raster: drawnRaster, angleDeg: electricalAngleDeg });
  }, [drawnRaster, electricalAngleDeg, source]);

  useEffect(() => {
    if (overlayRaster) setHeldOverlayRaster(overlayRaster);
  }, [overlayRaster]);

  useEffect(() => {
    if (!overlayActive) setHeldOverlayRaster(null);
  }, [overlayActive]);

  useEffect(() => () => {
    if (scrubIdleTimerRef.current !== null) window.clearTimeout(scrubIdleTimerRef.current);
  }, []);

  useEffect(() => {
    frameGenerationRef.current += 1;
    Object.values(rasterCacheRef.current).forEach(retireRaster);
    frameCacheRef.current = {};
    rasterCacheRef.current = {};
    frameRequestsRef.current.clear();
    rasterRequestsRef.current.clear();
    setView('resultant');
    setHeldOverlayRaster(null);
    setFrameIndex(0);
    frameIndexRef.current = 0;
    playbackElectricalAngleRef.current = 0;
    setPlaying(false);
    setPlaybackWaiting(false);
    setFrameCache({});
    setRasterCache({});
    setHeldRaster(null);
    frameLoaderRef.current.clear();
    setRetainedPlot(null);
    setFieldViewportScale(1);
    setColorRangeMode('fixed');
    setDetailPlot(null);
    replaceDetailRaster(null);
    detailRequestRef.current += 1;
    setFrameError(null);
  }, [replaceDetailRaster, result, retireRaster]);

  useEffect(() => {
    frameIndexRef.current = boundedIndex;
  }, [boundedIndex]);

  const syncPlaybackSlider = useCallback((electricalAngle: number) => {
    if (!playbackSliderRef.current) return;
    playbackSliderRef.current.value = String(
      positionSliderValue(playbackSpanRef.current, electricalAngle),
    );
  }, []);

  useEffect(() => {
    if (!playing && playbackSliderRef.current) {
      syncPlaybackSlider(playbackElectricalAngleRef.current);
    }
  }, [boundedIndex, playing, syncPlaybackSlider]);

  useEffect(() => {
    const cacheLimit = publicFieldPlaybackCacheFrames(playbackRpm);
    const cachedFrameIds = Object.keys(frameCacheRef.current);
    if (cachedFrameIds.length > cacheLimit) {
      const nextFrameCache = { ...frameCacheRef.current };
      while (cachedFrameIds.length > cacheLimit) {
        const expiredId = cachedFrameIds.shift();
        if (expiredId) delete nextFrameCache[expiredId];
      }
      frameCacheRef.current = nextFrameCache;
      setFrameCache(nextFrameCache);
    }

    if (Object.keys(rasterCacheRef.current).length > rasterCacheLimit) {
      const nextRasterCache = { ...rasterCacheRef.current };
      evictRasters(nextRasterCache, rasterCacheLimit, keptRasterKeys(), retireRaster);
      rasterCacheRef.current = nextRasterCache;
      setRasterCache(nextRasterCache);
    }
  }, [keptRasterKeys, playbackRpm, rasterCacheLimit, retireRaster]);

  useEffect(() => {
    if (!playing || angleFrames.length < 2) return undefined;
    let lastSampleAt: number | null = null;
    let animationFrameId = 0;
    const animate = (timestamp: number) => {
      if (lastSampleAt !== null) {
        const elapsedMs = timestamp - lastSampleAt;
        // A solved window loops through its positions in order; a full cycle
        // turns at the playback RPM on its stride grid.
        const nextPlaybackAngleDeg = playbackSpan.windowed
          ? advanceWindowPlaybackAngle(
            playbackElectricalAngleRef.current,
            Math.min(elapsedMs, MAX_PLAYBACK_CATCHUP_MS),
            playbackRpmRef.current,
            polePairs,
            playbackSpan,
          )
          : advancePlaybackElectricalAngle(
            playbackElectricalAngleRef.current,
            Math.min(elapsedMs, MAX_PLAYBACK_CATCHUP_MS),
            playbackRpmRef.current,
            polePairs,
          );
        const nextIndex = playbackSpan.windowed
          ? windowPlaybackFrameIndex(angleFrames, nextPlaybackAngleDeg, playbackSpan)
          : playbackStrideFrameIndex(
            angleFrames,
            normalizePlaybackElectricalAngle(nextPlaybackAngleDeg, playbackSpanDeg),
            playbackSpanDeg,
            playbackStrideRef.current,
          );
        const nextAngle = angleFrames[nextIndex]?.angle_deg ?? 0;
        const nextDescriptor = nearestFrame(sourceFrames, nextAngle);
        const nextArtifactId = nextDescriptor?.field_frame_artifact.artifact_id;
        const nextReady = nextArtifactId
          && (
            cachedRaster(rasterCacheRef.current, nextArtifactId, source, showMeshRef.current)
            || frameCacheRef.current[nextArtifactId]
          );
        const nextOverlay = overlayActive ? nearestFrame(resultantFrames, nextAngle) : null;
        const nextOverlayId = nextOverlay?.field_frame_artifact.artifact_id;
        const nextOverlayReady = !nextOverlayId
          || cachedRaster(rasterCacheRef.current, nextOverlayId, 'pm', false)
          || frameCacheRef.current[nextOverlayId];
        if (nextDescriptor && nextArtifactId && !nextReady) {
          void loadVisualFrame(nextDescriptor, source).catch(() => {
            setPlaybackWaiting(false);
            setPlaying(false);
          });
          setPlaybackWaiting(true);
        } else if (nextOverlay && !nextOverlayReady) {
          void loadVisualFrame(nextOverlay, 'pm', false).catch(() => {
            setPlaybackWaiting(false);
            setPlaying(false);
          });
          setPlaybackWaiting(true);
        } else {
          playbackElectricalAngleRef.current = nextPlaybackAngleDeg;
          syncPlaybackSlider(nextPlaybackAngleDeg);
          if (nextIndex !== frameIndexRef.current) {
            frameIndexRef.current = nextIndex;
            setFrameIndex(nextIndex);
          }
          setPlaybackWaiting(false);
        }
      }
      lastSampleAt = timestamp;
      animationFrameId = window.requestAnimationFrame(animate);
    };
    animationFrameId = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(animationFrameId);
  }, [
    angleFrames,
    loadVisualFrame,
    overlayActive,
    playing,
    polePairs,
    playbackSpan,
    playbackSpanDeg,
    resultantFrames,
    source,
    sourceFrames,
    syncPlaybackSlider,
  ]);

  useEffect(() => {
    if (activePlot) setRetainedPlot({ source, plot: activePlot });
  }, [activePlot, source]);

  useEffect(() => {
    if (playing || !artifactId) return undefined;
    const timeout = window.setTimeout(
      () => setSettledArtifactId(artifactId),
      EXACT_FRAME_SETTLE_MS,
    );
    return () => window.clearTimeout(timeout);
  }, [artifactId, playing]);

  useEffect(() => {
    if (fieldViewportScale < DETAIL_VIEWPORT_SCALE || playing || !artifactId) {
      if (fieldViewportScale < DETAIL_VIEWPORT_SCALE || playing) {
        setDetailPlot(null);
        replaceDetailRaster(null);
        detailRequestRef.current += 1;
      }
      return;
    }
    if (activePlot) {
      replaceDetailRaster(null);
      return;
    }
    if (activeDetailPlot || activeDetailRaster || !exactFrameSettled) return;

    const requestId = ++detailRequestRef.current;
    // Prefer exact solver vectors for a stopped, zoomed frame. Playback WebPs
    // keep animation fast, while the numerical artifact has no raster ceiling.
    // Older caches retained only frame zero, so their detail WebP remains the
    // compatibility fallback when the numerical endpoint returns 404.
    // loadFrame shares the exact-frame request instead of downloading it twice.
    const loadNumericalDetail = () => loadFrame(artifactId)
      .then((outerPlot) => {
        if (detailRequestRef.current !== requestId) return false;
        if (!outerPlot) return false;
        const requestedPlot = source === 'pm' ? outerPlot.noload_plot : outerPlot;
        if (!requestedPlot) return false;
        setDetailPlot({ artifactId, source, plot: requestedPlot });
        return true;
      })
      .catch(() => false);
    void loadNumericalDetail().then((loadedNumericalDetail) => {
      if (loadedNumericalDetail || detailRequestRef.current !== requestId) return;
      const detailRequest = descriptor && rasterizerRef.current
        ? rasterizerRef.current.renderDetail(source, descriptor.playback_frame)
        : Promise.resolve(null);
      void detailRequest
        .then((raster) => {
          if (!raster) return;
          if (detailRequestRef.current !== requestId) {
            closeRaster(raster);
            return;
          }
          replaceDetailRaster({
            key: rasterCacheKey(artifactId, source),
            raster,
          });
        })
        .catch(() => undefined);
    });
  }, [
    activeDetailPlot,
    activeDetailRaster,
    activePlot,
    artifactId,
    descriptor,
    exactFrameSettled,
    fieldViewportScale,
    loadFrame,
    playing,
    replaceDetailRaster,
    source,
  ]);

  useEffect(() => {
    // Preloading while the slider is dragged would queue frames it has already
    // left; the slider's own position loads instead.
    if (angleFrames.length < 2 || (scrubbing && !playing)) return;
    for (const preloadIndex of preloadIndices) {
      const preloadAngle = angleFrames[preloadIndex]?.angle_deg ?? 0;
      const preloadDescriptor = nearestFrame(sourceFrames, preloadAngle);
      const preloadArtifactId = preloadDescriptor?.field_frame_artifact.artifact_id;
      if (
        preloadDescriptor
        && preloadArtifactId
        && !cachedRaster(rasterCacheRef.current, preloadArtifactId, source, showMeshRef.current)
        && !frameCacheRef.current[preloadArtifactId]
      ) {
        void loadVisualFrame(preloadDescriptor, source).catch(() => undefined);
      }
      const preloadOverlay = overlayActive ? nearestFrame(resultantFrames, preloadAngle) : null;
      const preloadOverlayId = preloadOverlay?.field_frame_artifact.artifact_id;
      if (
        preloadOverlay
        && preloadOverlayId
        && !cachedRaster(rasterCacheRef.current, preloadOverlayId, 'pm', false)
        && !frameCacheRef.current[preloadOverlayId]
      ) {
        void loadVisualFrame(preloadOverlay, 'pm', false).catch(() => undefined);
      }
    }
  }, [
    angleFrames,
    loadVisualFrame,
    overlayActive,
    playing,
    preloadIndices,
    resultantFrames,
    scrubbing,
    showMesh,
    source,
    sourceFrames,
  ]);

  useEffect(() => {
    // The PM frame on screen in Stator + PM: its playback raster at once, and
    // its exact frame once the stator frame has settled.
    if (!overlayActive || !overlayDescriptor || !overlayArtifactId) return;
    if (
      !cachedRaster(rasterCacheRef.current, overlayArtifactId, 'pm', false)
      && !frameCacheRef.current[overlayArtifactId]
    ) {
      void loadVisualFrame(overlayDescriptor, 'pm', false).catch(() => undefined);
    }
    if (!playing && exactFrameSettled && !frameCacheRef.current[overlayArtifactId]) {
      void loadFrame(overlayArtifactId).catch(() => undefined);
    }
  }, [
    exactFrameSettled,
    loadFrame,
    loadVisualFrame,
    overlayActive,
    overlayArtifactId,
    overlayDescriptor,
    playing,
  ]);

  useEffect(() => {
    if (!artifactId) {
      setFrameLoading(false);
      return;
    }
    if (
      cachedRaster(rasterCacheRef.current, artifactId, source, showMeshRef.current)
      || frameCacheRef.current[artifactId]
    ) {
      setFrameLoading(false);
      setFrameError(null);
      return;
    }
    let active = true;
    setFrameLoading(true);
    setFrameError(null);
    if (!descriptor) return;
    // Stopped, the newest slider position replaces any position still waiting
    // to load, so dragging never queues frames the slider has left (#59).
    // Each frame that finishes is shown straight away, even when the slider
    // has moved on, so the picture keeps following a fast drag.
    const frameAngleDeg = descriptor.angle_deg;
    const requestSeq = ++frameRequestSeqRef.current;
    void (playing
      ? loadVisualFrame(descriptor, source)
      : frameLoaderRef.current.request(() => loadVisualFrame(descriptor, source)).then((raster) => {
        if (raster && requestSeq > shownRequestSeqRef.current) {
          shownRequestSeqRef.current = requestSeq;
          setHeldRaster({ source, raster, angleDeg: frameAngleDeg });
        }
        return raster;
      }))
      .catch((error: unknown) => {
        if (!active) return;
        const message = error && typeof error === 'object' && 'message' in error
          ? String(error.message)
          : 'The solved field frame could not be loaded.';
        setFrameError(message);
      })
      .finally(() => {
        if (active) setFrameLoading(false);
      });
    return () => { active = false; };
  }, [artifactId, descriptor, frameCache, loadVisualFrame, playing, rasterCache, showMesh, source]);

  useEffect(() => {
    if (playing || !artifactId || activePlot || !exactFrameSettled) return;
    // A stopped frame keeps its compact playback raster for immediate display,
    // then loads the exact numerical mesh for probing, density control, and a
    // genuinely fixed color range.
    void loadFrame(artifactId).catch(() => undefined);
  }, [activePlot, artifactId, exactFrameSettled, loadFrame, playing]);

  const selectSource = (nextView: FieldView) => {
    const nextSource: FieldSource = nextView === 'stator_pm' ? 'armature' : nextView;
    if (nextSource === 'armature' && !magnetoCompositionAvailable) return;
    if (nextView === 'stator_pm' && !pmAvailable) return;
    setView(nextView);
    setPlaying(false);
    setPlaybackWaiting(false);
    if (nextSource !== 'armature') setRetainedPlot(null);
    if (nextView === 'stator_pm') {
      // Stator + PM shows no flux-density map, so it has no colour range to hold.
      setColorRangeMode('fixed');
      // Pole labels and fewer lines keep the two fields' poles readable.
      setShowPoleLabels(true);
      setFieldLineDensity('low');
    }
    setDetailPlot(null);
    replaceDetailRaster(null);
    detailRequestRef.current += 1;
    if (nextSource === 'armature' && !armature && !armatureBusy) onRequestArmature();
  };

  // PM and Stator are one group: either alone, or both to overlay their lines.
  // Turning the last one off falls back to Resultant.
  const pmShown = view === 'pm' || view === 'stator_pm';
  const statorShown = view === 'armature' || view === 'stator_pm';
  const toggleSeparateField = (part: 'pm' | 'armature') => {
    const nextPm = part === 'pm' ? !pmShown : pmShown;
    const nextStator = part === 'armature' ? !statorShown : statorShown;
    selectSource(nextPm && nextStator ? 'stator_pm' : nextPm ? 'pm' : nextStator ? 'armature' : 'resultant');
  };

  const togglePlayback = () => {
    if (playing) {
      setPlaying(false);
      setPlaybackWaiting(false);
      return;
    }
    frameIndexRef.current = 0;
    playbackElectricalAngleRef.current = angleFrames[0]?.angle_deg ?? 0;
    syncPlaybackSlider(playbackElectricalAngleRef.current);
    setFrameIndex(0);
    setPlaybackWaiting(false);
    setPlaying(true);
  };

  const sourceLabel = overlayActive
    ? 'Stator and PM field lines'
    : source === 'resultant' ? 'Resultant field' : source === 'pm' ? 'PM-only field' : 'Stator-current field';
  const sourceDetail = overlayActive
    ? 'Separate solves: in saturated steel the resultant is not their sum.'
    : source === 'resultant'
      ? 'Permanent magnets and stator current'
      : source === 'pm'
        ? 'Exact zero-current Magneto2D frames'
        : 'PM remanence off · exact stator field';
  const setRangeMode = (nextMode: FieldColorRangeMode) => {
    setColorRangeMode(nextMode);
    // Playback images use the fixed scale, so Fit view applies to a stopped frame.
    if (nextMode === 'viewport') {
      setPlaying(false);
      setPlaybackWaiting(false);
    }
  };
  const bufferStatus = playbackWaiting
    ? 'Buffering next frame…'
    : `${bufferedAhead}/${bufferTarget} frames ${playing ? 'buffered' : 'ready'}`;
  const loadingTitle = source === 'armature' && armatureBusy
    ? 'Computing exact stator field…'
    : frameLoading
      ? 'Loading solved field frame…'
      : 'Field frame unavailable';
  const loadingDetail = source === 'armature' && armatureBusy
    ? 'Solving the zero-remanence rotor sweep locally'
    : frameLoading
      ? 'Preparing solved geometry, flux density, and contours'
      : source === 'armature' && !armature
        ? armatureError ?? 'Select Stator to compute the cached Br = 0 sweep.'
        : frameError;
  // The plot portals its zoom controls into the dock, off the field (#120 follow-up).
  const [zoomSlot, setZoomSlot] = useState<HTMLSpanElement | null>(null);
  // Flux density and field lines change what the picture means, so they stay
  // in view; the reference layers wait in More, which counts how many are on.
  const renderMoreLayerButtons = () => (
    <>
      {hasMagnets && <button type="button" aria-pressed={showMagnets} onClick={() => setShowMagnets((value) => !value)}><i aria-hidden="true" />{source === 'armature' && !overlayActive ? 'PM reference' : 'Magnets'}</button>}
      <button type="button" aria-pressed={showMesh} onClick={() => setShowMesh((value) => !value)}><i aria-hidden="true" />Mesh</button>
      <button type="button" aria-pressed={showAirgap} onClick={() => setShowAirgap((value) => !value)}><i aria-hidden="true" />Airgap</button>
      {(hasMagnets || source === 'armature') && <button type="button" aria-pressed={showPoleLabels} onClick={() => setShowPoleLabels((value) => !value)}><i aria-hidden="true" />Pole labels</button>}
    </>
  );
  const moreLayersOn = [
    hasMagnets && showMagnets,
    showMesh,
    showAirgap,
    (hasMagnets || source === 'armature') && showPoleLabels,
  ].filter(Boolean).length;
  // Line density sits right after Field lines as a three-way choice, and only
  // while the lines are shown.
  const renderDensityControl = () => {
    const densityAdjustable = !playing && Boolean(exactVectorPlot);
    const displayedDensity = exactVectorPlot ? fieldLineDensity : 'medium';
    const densityTitle = playing
      ? 'Playback uses medium field-line density. Pause to adjust the exact frame.'
      : densityAdjustable
        ? 'Field-line density'
        : 'Loading the exact frame before field-line density can be changed.';
    return (
      <span className="public-field-density-choice" role="group" aria-label="Field-line density" title={densityTitle}>
        {FIELD_LINE_DENSITY_STOPS.map((stop) => (
          <button
            type="button"
            aria-pressed={displayedDensity === stop}
            disabled={!densityAdjustable}
            onClick={() => setFieldLineDensity(stop)}
            aria-label={`${stop === 'low' ? 'Low' : stop === 'medium' ? 'Medium' : 'High'} line density`}
            key={stop}
          >
            <span className="public-field-density-long">{stop === 'low' ? 'Low' : stop === 'medium' ? 'Med' : 'High'}</span>
            <span className="public-field-density-short" aria-hidden="true">{stop === 'low' ? 'L' : stop === 'medium' ? 'M' : 'H'}</span>
          </button>
        ))}
      </span>
    );
  };

  return (
    <section className="public-solved-field-viewer" aria-label="Completed field solution">
      <div className="public-solved-field-canvas">
        {source === 'armature' && armatureBusy && (
          <div
            className="public-field-stream-status"
            role="status"
            aria-label="Stator-current field solve progress"
          >
            <span>
              {armatureFrames.length > 0
                ? 'Live Magneto2D stator field'
                : 'Previous resultant field · waiting for first stator frame'}
            </span>
            <strong>
              {armatureProgress && armatureProgress.total > 0
                ? `Position ${Math.min(armatureProgress.position, armatureProgress.total)} / ${armatureProgress.total}`
                : 'Preparing exact field…'}
            </strong>
            <button type="button" aria-label="Cancel the stator-only field" onClick={onCancelArmature}>Cancel</button>
            <progress
              max={Math.max(1, armatureProgress?.total ?? 1)}
              value={Math.max(0, armatureProgress?.position ?? 0)}
            />
          </div>
        )}
        {(activeDetailRaster || visibleRaster || visiblePlot) && (
          <>
            <FieldResultPlot
              plot={visiblePlot}
              raster={activeDetailRaster ?? visibleRaster}
              highResolutionPlot={exactVectorPlot}
              probeEnabled={!playing && Boolean(exactVectorPlot) && !overlayActive}
              geometry={geometry}
              magnetRotationDeg={(heldFrame?.angleDeg ?? electricalAngleDeg) / polePairs}
              showMagnets={showMagnets}
              showAirgap={showAirgap}
              airgapInnerRadiusMm={rotorAirgapBoundaryRadiusMm(config)}
              showMagnetPolarityLabels={showPoleLabels}
              magnetReference={source === 'armature' && !overlayActive}
              showStatorPolarity={source === 'armature' && showPoleLabels}
              showPolarityLegend={source === 'armature' && showPoleLabels}
              statorPolarityProfile={descriptor?.airgap_brbt ?? exactVectorPlot?.airgap_brbt}
              statorPolarityRotationDeg={statorPolarityRotationDeg}
              statorInnerRadiusMm={config.stator.ID_mm / 2}
              poles={config.rotor.pole_count}
              showHeatmap={showHeatmap && !overlayActive}
              showMesh={showMesh}
              showFieldLines={showFieldLines}
              fieldLineDensity={exactVectorPlot ? fieldLineDensity : 'medium'}
              colorRangeMode={colorRangeMode}
              saturationTicks={saturationTicks}
              showRangeControl
              onColorRangeModeChange={setRangeMode}
              showControls={false}
              showHeading={false}
              title={sourceLabel}
              subtitle={sourceDetail}
              describeProbe={describeProbe}
              onViewportScaleSettled={setFieldViewportScale}
              overlay={fieldLineOverlay}
              fieldAxes={overlayActive ? CLOCKWISE_FIELD_AXES : null}
              navigationSlot={zoomSlot}
            />
          </>
        )}
        {!visibleRaster && !visiblePlot && <div className="public-field-loading" role="status">
          <strong>{loadingTitle}</strong>
          {loadingDetail && <span>{loadingDetail}</span>}
          {source === 'armature' && !armature && !armatureBusy && <button type="button" onClick={onRequestArmature}>{armatureError ? 'Retry stator field' : 'Compute stator field'}</button>}
        </div>}
      </div>

      {/* The dock reads in the order you work: the title bar, then what the
          field shows, then playback through the solved positions. */}
      <div className="public-field-dock">
        <div className="public-dock-strip">
          {viewControls}
          <div className="public-dock-strip-end">
            {(activeDetailRaster || visibleRaster || visiblePlot) && (
              <div className="viewport-cad-status"><span className="public-field-text-long">{angleFrames.length} positions · </span>peak |B| {currentPeakBT.toFixed(2)} T</div>
            )}
            <details className="public-field-physics-info">
              <summary aria-label="Field details" title="Field details">i</summary>
              <div className="public-field-summary-panel">
                <span>Field composition</span>
                <strong>{sourceLabel}</strong>
                <p>{sourceDetail}</p>
                {(activeDetailRaster || visibleRaster || visiblePlot) && (
                  <dl>
                    <div><dt>Peak |B|</dt><dd>{currentPeakBT.toFixed(3)} T</dd></div>
                    <div><dt>Position</dt><dd>{electricalAngleDeg.toFixed(1)}° elec</dd></div>
                    <div><dt>Mechanical</dt><dd>{mechanicalAngleDeg.toFixed(2)}°</dd></div>
                    <div><dt>Playback</dt><dd>Clockwise</dd></div>
                    <div><dt>Frames</dt><dd>{bufferStatus}</dd></div>
                  </dl>
                )}
                <p className="public-field-summary-note">PM-only and Stator-only are separate nonlinear solves; their arithmetic sum is not assumed to equal the Resultant field when steel is saturated.</p>
              </div>
            </details>
            <span className="public-field-zoom-slot" ref={setZoomSlot} />
            {expandControl}
          </div>
        </div>
        <div className="public-field-dock-controls" role="toolbar" aria-label="Field display">
          <div className="public-field-control-cluster">
            <span>Field</span>
            <div className="public-field-source-controls" role="group" aria-label="Field composition">
              <button type="button" aria-label="Resultant field, permanent magnets plus stator current" title="Permanent magnets plus stator current" aria-pressed={view === 'resultant'} onClick={() => selectSource('resultant')}><strong>Resultant</strong></button>
              <span className={`public-field-source-pair${overlayActive ? ' is-both' : ''}`} role="group" aria-label="Separate fields: PM, Stator, or both together" title="Pick PM, Stator, or both to draw their field lines together">
                <button type="button" className="is-pm" aria-label="PM-only field, zero current" title="Exact zero-current Magneto2D field" aria-pressed={pmShown} disabled={!pmAvailable} onClick={() => toggleSeparateField('pm')}><strong>PM</strong></button>
                <button type="button" className="is-stator" aria-label="Stator-current-only field, permanent-magnet remanence disabled" title={magnetoCompositionAvailable ? 'Exact zero-remanence Magneto2D field' : 'Stator-only composition is available for Magneto2D results'} aria-pressed={statorShown} disabled={!magnetoCompositionAvailable} onClick={() => toggleSeparateField('armature')}><strong>Stator</strong></button>
              </span>
            </div>
          </div>
          <div className="public-field-control-cluster public-field-overlay-cluster">
            <span>Show</span>
            <div className="public-field-layer-controls public-field-layer-controls-inline" role="group" aria-label="Field solution overlays">
              <button type="button" aria-pressed={showHeatmap && !overlayActive} disabled={overlayActive} title={overlayActive ? 'Off while PM and Stator are both shown: one |B| map cannot belong to both fields' : undefined} onClick={() => setShowHeatmap((value) => !value)} aria-label="Flux density"><i aria-hidden="true" /><span className="public-field-text-long">Flux density</span><span className="public-field-text-short" aria-hidden="true">Flux</span></button>
              <button type="button" aria-pressed={showFieldLines} onClick={() => setShowFieldLines((value) => !value)} aria-label="Field lines"><i aria-hidden="true" /><span className="public-field-text-long">Field lines</span><span className="public-field-text-short" aria-hidden="true">Lines</span></button>
              {showFieldLines && renderDensityControl()}
            </div>
            <details className="public-field-layer-menu">
              <summary>More{moreLayersOn > 0 && <em>{moreLayersOn} on</em>}</summary>
              <div className="public-field-layer-controls" role="group" aria-label="More field layers">
                {renderMoreLayerButtons()}
              </div>
            </details>
          </div>
        </div>
        <div className="public-field-playback">
          <button
            className="public-field-transport-play"
            type="button"
            aria-label={playing ? 'Pause clockwise field playback' : 'Play field clockwise'}
            title={colorRangeMode === 'viewport'
              ? 'Switch the flux-density range to Fixed to animate.'
              : 'Clockwise — follows the public solve angle convention'}
            disabled={angleFrames.length < 2 || colorRangeMode === 'viewport'}
            onClick={togglePlayback}
          >
            {playing ? 'Ⅱ' : '▶'}
          </button>
          <label className="public-field-position-control">
            {/* Nothing in this row changes size while playing: a stall shows
                inside the label, and the frame count is in the field details. */}
            <span>
              <strong>Position</strong>
              {playbackWaiting && <small className="public-field-playback-buffering" aria-live="polite">Buffering…</small>}
              <em>{boundedIndex + 1} / {Math.max(1, angleFrames.length)} · {electricalAngleDeg.toFixed(1)}° elec</em>
            </span>
            <input
              ref={playbackSliderRef}
              type="range"
              min={sliderRange.min}
              max={sliderRange.max}
              step="any"
              defaultValue={sliderRange.min}
              disabled={angleFrames.length < 2}
              aria-label="Solved rotor position"
              onChange={(event) => {
                const nextPlaybackAngleDeg = Number(event.target.value);
                const nextIndex = positionSliderFrameIndex(angleFrames, nextPlaybackAngleDeg, playbackSpan);
                const direction = nextPlaybackAngleDeg >= playbackElectricalAngleRef.current ? 1 : -1;
                if (direction !== scrubDirection) setScrubDirection(direction);
                setScrubbing(true);
                if (scrubIdleTimerRef.current !== null) window.clearTimeout(scrubIdleTimerRef.current);
                scrubIdleTimerRef.current = window.setTimeout(() => {
                  scrubIdleTimerRef.current = null;
                  setScrubbing(false);
                }, EXACT_FRAME_SETTLE_MS);
                setPlaying(false);
                setPlaybackWaiting(false);
                frameIndexRef.current = nextIndex;
                playbackElectricalAngleRef.current = nextPlaybackAngleDeg;
                setFrameIndex(nextIndex);
              }}
            />
          </label>
          <RpmField
            value={playbackRpm}
            min={PUBLIC_FIELD_PLAYBACK_MIN_RPM}
            max={PUBLIC_FIELD_PLAYBACK_MAX_RPM}
            label="Speed"
            ariaLabel="Playback speed (RPM)"
            title="Visual playback speed — not the solve operating point. Type a number or use the arrows; Shift+arrow steps by 10."
            onChange={setPlaybackRpm}
          />
        </div>
      </div>
    </section>
  );
}
