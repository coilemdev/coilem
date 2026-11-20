import { solveViewMemory, type FieldView } from './solveViewMemory';
import { useLayerMenu } from './useLayerMenu';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { outerRotorRing } from './sectorFraming';

import { getPublicFieldFrame, getPublicPlaybackStatus } from './api';
import {
  FIELD_FIT_LIKE_MOTOR_CANVAS,
  FieldResultPlot,
  warmFieldResultPlot,
  type FieldColorRangeMode,
  type FieldLineDensity,
  type FieldLineOverlay,
  type FieldProbe,
  type FieldResultRaster,
} from './FieldResultPlot';
import { normalizeFieldPlaybackManifest } from './fieldPlaybackContract';
import { statorSteelSaturationTicks } from './fluxColorScale';
import {
  FieldPlaybackRasterizer,
  FieldRasterLayer,
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
  PUBLIC_FIELD_PLAYBACK_DEFAULT_RPM,
  PUBLIC_FIELD_PLAYBACK_MAX_RPM,
  PUBLIC_FIELD_PLAYBACK_MIN_RPM,
  PUBLIC_FIELD_PLAYBACK_PM_ARROW_FPS,
  publicFieldPlaybackBufferFrames,
  publicFieldPlaybackCacheFrames,
  scrubNeighbourIndices,
  windowLookaheadFrameIndices,
  windowPlaybackFrameIndex,
} from './fieldPlaybackTiming';
import { LatestFrameLoader } from './latestFrameLoader';
import { RpmField } from './RpmField';
import { describeFieldProbe } from './fieldProbeRegion';
import { isSteppedCycle, phaseCurrentsAt, phaseCycleFromFrames, type FieldPhaseView } from './fieldPhases';
import { slotCurrents, toothPoles, type PhaseDrive } from './phaseDrive';
import type { FieldPositionLink } from './fieldPositionLink';
import { magneticAirgapMm, rotorAirgapBoundaryRadiusMm } from './motorAirgap';
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

// Stator + PM draws the PM-only field's arrows over the stator-only field's (#120).
type FieldSource = Exclude<FieldView, 'stator_pm'>;
// A stator frame pairs with the PM frame at the same rotor position.
const OVERLAY_ANGLE_TOLERANCE_DEG = 1e-3;
// Public playback turns clockwise (the solve angle convention).
const CLOCKWISE_FIELD_AXES = { rotation: 'clockwise' } as const;
const IDLE_BUFFER_FRAMES = 4;
const DETAIL_VIEWPORT_SCALE = 1.08;
const MAX_PLAYBACK_CATCHUP_MS = 250;
// How often to ask whether a saved run's playback images are all drawn.
const PLAYBACK_STATUS_POLL_MS = 1000;
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

function rasterCacheKey(artifactId: string, source: FieldRasterSource, layers: number = FieldRasterLayer.All): string {
  return `${source}:${layers}:${artifactId}`;
}

// Turning off a layer can reuse a frame that already contains it.
function availableRasterKey(
  cache: Record<string, FieldResultRaster>,
  artifactId: string,
  source: FieldRasterSource,
  requestedLayers: number,
): string {
  const requestedKey = rasterCacheKey(artifactId, source, requestedLayers);
  if (cache[requestedKey]) return requestedKey;
  for (let layers = requestedLayers + 1; layers <= FieldRasterLayer.All; layers += 1) {
    if ((layers & requestedLayers) !== requestedLayers) continue;
    const key = rasterCacheKey(artifactId, source, layers);
    if (cache[key]) return key;
  }
  return requestedKey;
}

function cachedRaster(
  cache: Record<string, FieldResultRaster>,
  artifactId: string,
  source: FieldRasterSource,
  layers: number,
): FieldResultRaster | undefined {
  return cache[availableRasterKey(cache, artifactId, source, layers)];
}

function closeRaster(raster: FieldResultRaster): void {
  raster.base?.close();
  raster.heat?.close();
  raster.mesh?.close();
  raster.lines?.close();
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

interface SolvedFieldViewerProps {
  magnifierSlot?: HTMLElement | null;
  probeSlot?: HTMLElement | null;
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
  magnetoCompositionAvailable: boolean;
  /** Why this run has no stator-only field (for example a cogging-only run), or null. */
  statorFieldUnavailableReason?: string | null;
  onRequestArmature: () => void;
  /** The Solve tab's waveform plots: they set the field's position and show it. */
  positionLink?: FieldPositionLink;
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
  magnifierSlot = null,
  probeSlot = null,
  viewControls,
  expandControl,
  config,
  materials = null,
  geometry,
  result,
  armature,
  armatureBusy,
  armatureError,
  magnetoCompositionAvailable: solverSupportsComposition,
  statorFieldUnavailableReason = null,
  onRequestArmature,
  positionLink,
}: SolvedFieldViewerProps) {
  const playbackUnavailableReason = result.field_playback_unavailable_reason;
  const resultantFrames = useMemo(
    () => playbackUnavailableReason ? [] : playbackDescriptors(result.field_playback, result.field_line_frames ?? []),
    [result.field_line_frames, result.field_playback, playbackUnavailableReason],
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
  const fieldAxes = useMemo(() => ({
    ...CLOCKWISE_FIELD_AXES,
    currentAngleDeg: config.solve_params.excitation_mode === 'sinusoidal' ? config.solve_params.current_angle_deg : null,
  }), [config.solve_params.excitation_mode, config.solve_params.current_angle_deg]);
  // Stator + PM loads, caches and plays the stator field as Stator only does;
  // the PM frame at the same position loads beside it.
  const source: FieldSource = overlayActive ? 'armature' : view;
  const [frameIndex, setFrameIndex] = useState(0);
  // The layer choices start from where the field view was last left.
  const [showHeatmap, setShowHeatmap] = useState(solveViewMemory.field.showHeatmap);
  const [showMesh, setShowMesh] = useState(solveViewMemory.field.showMesh);
  const [showFieldLines, setShowFieldLines] = useState(solveViewMemory.field.showFieldLines);
  const primaryLayers = FieldRasterLayer.Base
    | (showHeatmap && !overlayActive ? FieldRasterLayer.Heat : 0)
    | (showMesh ? FieldRasterLayer.Mesh : 0)
    | (showFieldLines ? FieldRasterLayer.Lines : 0);
  const overlayLayers = showFieldLines ? FieldRasterLayer.Lines : 0;
  const [showMagnets, setShowMagnets] = useState(solveViewMemory.field.showMagnets);
  const [magnifier, setMagnifier] = useState(solveViewMemory.field.magnifier);
  const fieldLayerMenu = useLayerMenu();
  const [showAirgap, setShowAirgap] = useState(solveViewMemory.field.showAirgap);
  const [showPoleLabels, setShowPoleLabels] = useState(solveViewMemory.field.showPoleLabels);
  const [showToothPoles, setShowToothPoles] = useState(solveViewMemory.field.showToothPoles);
  const [showPhases, setShowPhases] = useState(solveViewMemory.field.showPhases);
  const [showCoilColors, setShowCoilColors] = useState(solveViewMemory.field.showCoilColors);
  const [fieldLineDensity, setFieldLineDensity] = useState(solveViewMemory.field.fieldLineDensity);
  const [colorRangeMode, setColorRangeMode] = useState<FieldColorRangeMode>('fixed');
  const saturationTicks = useMemo(() => statorSteelSaturationTicks(config, materials), [config, materials]);
  const [playing, setPlaying] = useState(false);
  const [pmPlaybackLimited, setPmPlaybackLimited] = useState(false);
  const [playbackRpm, setPlaybackRpm] = useState(solveViewMemory.field.playbackRpm ?? PUBLIC_FIELD_PLAYBACK_DEFAULT_RPM);
  const playbackRpmRef = useRef(playbackRpm);
  playbackRpmRef.current = playbackRpm;
  useEffect(() => {
    solveViewMemory.field = { showHeatmap, showMesh, magnifier, showFieldLines, showMagnets, showAirgap, showPoleLabels, showToothPoles, showPhases, showCoilColors, fieldLineDensity, playbackRpm };
  }, [showHeatmap, showMesh, magnifier, showFieldLines, showMagnets, showAirgap, showPoleLabels, showToothPoles, showPhases, showCoilColors, fieldLineDensity, playbackRpm]);
  const playbackElectricalAngleRef = useRef(0);
  const [playbackWaiting, setPlaybackWaiting] = useState(false);
  const [frameCache, setFrameCache] = useState<Record<string, PublicFieldLinePlot>>({});
  const [rasterCache, setRasterCache] = useState<Record<string, FieldResultRaster>>({});
  const frameCacheRef = useRef<Record<string, PublicFieldLinePlot>>({});
  const rasterCacheRef = useRef<Record<string, FieldResultRaster>>({});
  const frameRequestsRef = useRef<Map<string, Promise<PublicFieldLinePlot>>>(new Map());
  const rasterRequestsRef = useRef<Map<string, Promise<FieldResultRaster | null>>>(new Map());
  const failedRasterKeysRef = useRef(new Set<string>());
  const rasterizerRef = useRef<FieldPlaybackRasterizer | null>(null);
  const activeRasterKeyRef = useRef<string | null>(null);
  const frameGenerationRef = useRef(0);
  const frameIndexRef = useRef(0);
  const [retainedPlot, setRetainedPlot] = useState<{ source: FieldSource; plot: PublicFieldLinePlot; angleDeg: number } | null>(null);
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
  const playbackSpanDeg = useMemo(() => playbackCycleSpanDeg(angleFrames), [angleFrames]);
  // A Preview run solves only a window of the cycle; the slider covers it once.
  const playbackSpan = useMemo(() => playbackSpanOf(angleFrames), [angleFrames]);
  const playbackSpanRef = useRef(playbackSpan);
  playbackSpanRef.current = playbackSpan;
  const streamingArmatureFrame = source === 'armature' && armatureBusy
    ? armatureFrames[armatureFrames.length - 1] ?? null
    : null;
  const electricalAngleDeg = streamingArmatureFrame?.angle_deg
    ?? angleFrames[boundedIndex]?.angle_deg
    ?? 0;
  const sourceFrames = source === 'armature' ? armatureFrames : resultantFrames;
  // A solve's playback images are drawn after its result is saved. Hold Play
  // until every position it shows is drawn, so playback never stalls on drawing:
  // one status check per composition played (the PM overlay too).
  const playbackStatusChecks = useMemo(() => {
    const checks: { artifactId: string; composition: string }[] = [];
    const addIfPending = (frames: PublicFieldFrameDescriptor[], composition: string) => {
      const layers = frames.map((frame) => frame.playback_frame?.compositions[composition]).filter((layer) => layer !== undefined);
      const pending = layers.some((layer) => (
        [layer.base, layer.flux_density, layer.field_lines].some((ref) => ref.byte_count === null)
      ));
      if (pending && layers[0]) checks.push({ artifactId: layers[0].base.artifact_id, composition });
    };
    addIfPending(sourceFrames, source);
    if (overlayActive) addIfPending(resultantFrames, 'pm');
    return checks;
  }, [overlayActive, resultantFrames, source, sourceFrames]);
  const playbackStatusKey = playbackStatusChecks.map((check) => `${check.composition}:${check.artifactId}`).join('|');
  const playbackStatusChecksRef = useRef(playbackStatusChecks);
  playbackStatusChecksRef.current = playbackStatusChecks;
  const [playbackReadiness, setPlaybackReadiness] = useState<{
    key: string;
    drawn: number;
    total: number;
    ready: boolean;
  } | null>(null);
  useEffect(() => {
    if (!playbackStatusKey) return undefined;
    let cancelled = false;
    let timer = 0;
    const poll = async () => {
      try {
        const statuses = await Promise.all(playbackStatusChecksRef.current.map(
          (check) => getPublicPlaybackStatus(check.artifactId, check.composition),
        ));
        if (cancelled) return;
        // A drawing job that has stopped with positions missing no longer holds
        // Play: those frames are drawn on request, as before.
        const ready = statuses.every((status) => status.ready || !status.drawing);
        setPlaybackReadiness({
          key: playbackStatusKey,
          drawn: statuses.reduce((sum, status) => sum + (status.frames_drawn ?? 0), 0),
          total: statuses.reduce((sum, status) => sum + (status.frames_total ?? 0), 0),
          ready,
        });
        if (!ready) timer = window.setTimeout(() => { void poll(); }, PLAYBACK_STATUS_POLL_MS);
      } catch {
        // Without a status, Play falls back to drawing frames on request.
        if (!cancelled) setPlaybackReadiness({ key: playbackStatusKey, drawn: 0, total: 0, ready: true });
      }
    };
    void poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [playbackStatusKey]);
  const playbackPreparing = playbackStatusKey !== ''
    && !(playbackReadiness?.key === playbackStatusKey && playbackReadiness.ready);
  const playbackPreparingLabel = playbackReadiness?.key === playbackStatusKey && playbackReadiness.total > 0
    ? `Preparing playback ${playbackReadiness.drawn}/${playbackReadiness.total}`
    : 'Preparing playback…';
  const descriptor = streamingArmatureFrame ?? nearestFrame(sourceFrames, electricalAngleDeg);
  const descriptorAngleDeg = descriptor?.angle_deg ?? electricalAngleDeg;
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
  overlayRasterKeyRef.current = overlayArtifactId ? availableRasterKey(rasterCache, overlayArtifactId, 'pm', overlayLayers) : null;
  const overlayRaster = overlayRasterKeyRef.current ? rasterCache[overlayRasterKeyRef.current] ?? null : null;
  const overlayPlot = overlayArtifactId ? frameCache[overlayArtifactId]?.noload_plot ?? null : null;
  const visibleOverlayRaster = overlayActive ? overlayRaster ?? (overlayPlot ? null : heldOverlayRaster) : null;
  const fieldLineOverlay = useMemo<FieldLineOverlay | null>(
    () => (overlayActive && (visibleOverlayRaster || overlayPlot)
      ? { raster: visibleOverlayRaster, plot: playing && visibleOverlayRaster ? null : overlayPlot }
      : null),
    [overlayActive, overlayPlot, playing, visibleOverlayRaster],
  );
  const activeRasterKey = artifactId ? availableRasterKey(rasterCache, artifactId, source, primaryLayers) : null;
  activeRasterKeyRef.current = activeRasterKey;
  const activeRaster = activeRasterKey ? rasterCache[activeRasterKey] ?? null : null;
  // Keep the same frame under the overlays while a newly enabled layer loads.
  const partialRaster = artifactId && !activeRaster ? cachedRaster(rasterCache, artifactId, source, FieldRasterLayer.Base) ?? null : null;
  const detailRasterKey = artifactId ? rasterCacheKey(artifactId, source) : null;
  const activeDetailRaster = !playing && detailRaster?.key === detailRasterKey
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
  const exactVectorAngleDeg = exactVectorPlot?.angle_deg ?? (selectedPlot || activeDetailPlot ? descriptorAngleDeg : 0);
  const heldVector = retainedPlot?.source === source || (source === 'armature' && armatureBusy)
    ? retainedPlot
    : null;
  const armatureReferencePlot = source === 'armature' && armatureBusy
    ? result.field_line_plot ?? null
    : null;
  // Keep the last raster visible while the next position decodes.
  const heldFrame = !activeRaster && !partialRaster && !exactVectorPlot && heldRaster?.source === source
    ? heldRaster
    : null;
  const drawnRaster = activeRaster ?? (exactVectorPlot ? null : partialRaster);
  const visibleRaster = activeDetailRaster ?? drawnRaster ?? heldFrame?.raster ?? null;
  // Zoom, arrows and the magnifier use the displayed playback image. Pausing restores
  // exact field detail once available. A run without an image still draws its vectors.
  const highResolutionPlot = playing ? null : exactVectorPlot;
  const visiblePlot = visibleRaster ? highResolutionPlot : exactVectorPlot ?? heldVector?.plot ?? armatureReferencePlot;
  // Keep overlays at the position of whichever raster or numerical plot is on screen.
  const vectorAngleDeg = exactVectorPlot ? exactVectorAngleDeg : heldVector?.angleDeg ?? armatureReferencePlot?.angle_deg ?? 0;
  const shownElectricalAngleDeg = activeDetailRaster || drawnRaster
    ? descriptorAngleDeg
    : heldFrame?.angleDeg ?? (visiblePlot ? vectorAngleDeg : descriptorAngleDeg);
  // Both winding overlays use the recorded currents for the frame on screen.
  const phaseCycle = useMemo(() => phaseCycleFromFrames(
    result.slot_excitation_frames, result.solve_metadata?.loaded_cycle_complete, result.solve_metadata?.rotor_positions,
    result.torque_waveform?.electrical_angle_deg,
  ), [result.slot_excitation_frames, result.solve_metadata?.loaded_cycle_complete, result.solve_metadata?.rotor_positions, result.torque_waveform]);
  const shownCurrents = useMemo(() => phaseCycle && source !== 'pm' && (showPhases || showToothPoles)
    ? phaseCurrentsAt(phaseCycle, shownElectricalAngleDeg)
    : null, [phaseCycle, source, showPhases, showToothPoles, shownElectricalAngleDeg]);
  const slotCount = Number(geometry?.metadata.slot_count);
  const hasToothGeometry = useMemo(() => Boolean(
    geometry?.winding_layout?.length && Number.isInteger(slotCount) && slotCount > 0
    && geometry.regions.some((region) => /stator_tooth/i.test(region.region_type) && region.points.length >= 3)
  ), [geometry, slotCount]);
  const toothPolesAvailable = source !== 'pm' && Boolean(phaseCycle?.peakA) && hasToothGeometry;
  const toothPoleStrengths = useMemo(() => {
    if (!showToothPoles || !toothPolesAvailable || !shownCurrents || !geometry?.winding_layout) return null;
    const currents = slotCurrents(geometry.winding_layout, slotCount, shownCurrents);
    return toothPoles(currents, geometry.metadata.rotor_layout === 'outer' ? 'outward' : 'inward');
  }, [geometry, slotCount, showToothPoles, toothPolesAvailable, shownCurrents]);
  // The drive panel's caption and frequency: six-step when the recorded currents
  // are, and the motor's poles. Its waveforms are the recorded currents.
  const phaseDrive = useMemo<PhaseDrive | null>(() => (phaseCycle
    ? {
      mode: (phaseCycle.peakA > 0 ? isSteppedCycle(phaseCycle) : config.solve_params.excitation_mode === 'ideal_six_step_120')
        ? 'ideal_six_step_120'
        : 'sinusoidal',
      currentAngleDeg: config.solve_params.current_angle_deg,
      currentAngleReference: 'q_axis',
      currentAmplitudeA: phaseCycle.peakA,
      commutationAdvanceDeg: config.solve_params.commutation_advance_deg,
      axisOffsetDeg: 0,
      poleCount: config.rotor.pole_count,
    }
    : null), [config.rotor.pole_count, config.solve_params.commutation_advance_deg, config.solve_params.current_angle_deg, config.solve_params.excitation_mode, phaseCycle]);
  const phaseView = useMemo<FieldPhaseView | null>(() => (showPhases && phaseCycle && phaseDrive
    ? {
      angleDeg: shownElectricalAngleDeg,
      currentsA: shownCurrents,
      pmOnly: source === 'pm',
      coilColors: showCoilColors,
      cycle: phaseCycle,
      drive: phaseDrive,
      rpm: playbackRpm,
    }
    : null), [phaseCycle, phaseDrive, playbackRpm, shownElectricalAngleDeg, showPhases, showCoilColors, shownCurrents, source]);
  const currentPeakBT = useMemo(() => {
    const rasterPeak = visibleRaster?.maxB;
    if (Number.isFinite(rasterPeak)) return rasterPeak ?? 0;
    const values = visiblePlot?.element_b_mag_t.filter(Number.isFinite) ?? [];
    return values.reduce((peak, value) => Math.max(peak, value), 0);
  }, [visiblePlot, visibleRaster?.maxB]);
  const describeProbe = useCallback(
    (probe: FieldProbe) => describeFieldProbe(probe, config, materials),
    [config, materials],
  );
  const polePairs = Math.max(1, config.rotor.pole_count / 2);
  const mechanicalAngleDeg = shownElectricalAngleDeg / polePairs;
  const statorPolarityRotationDeg = source === 'armature'
    && armature?.field_playback
    && (armature.airgap_profiles?.length ?? 0) < 2
    && armature.frames.length <= 1
    // Magneto2D advances the displayed sweep with a negative mechanical
    // rotation. Match that convention when an older cached playback has only
    // the frame-zero polarity profile.
    ? -mechanicalAngleDeg
    : 0;
  const magnetoCompositionAvailable = solverSupportsComposition && !statorFieldUnavailableReason;
  const pmAvailable = resultantFrames.some((frame) => frame.has_pm_only);
  const hasMagnets = Boolean(geometry?.regions.some((region) => /magnet/i.test(region.region_type)));
  const desiredBufferFrames = Math.max(
    IDLE_BUFFER_FRAMES,
    publicFieldPlaybackBufferFrames(playbackRpm),
  );
  const fastPmArrows = view === 'pm' && showFieldLines && !showHeatmap && !showMesh
    && !playbackSpan.windowed && Boolean(descriptor?.playback_frame?.compositions.pm)
    && !pmPlaybackLimited;
  const playbackStride = playbackFrameStride(
    angleFrames.length,
    playbackSpanDeg,
    playbackRpm,
    polePairs,
    fastPmArrows ? PUBLIC_FIELD_PLAYBACK_PM_ARROW_FPS : undefined,
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
      playbackSpanDeg,
      playbackStride,
      desiredBufferFrames,
    ),
    [
      angleFrames,
      desiredBufferFrames,
      electricalAngleDeg,
      playbackSpanDeg,
      playbackStride,
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
  const visualFrameReady = useCallback((frame: PublicFieldFrameDescriptor | null, frameSource: FieldRasterSource, layers: number) => {
    if (!frame) return false;
    const id = frame.field_frame_artifact.artifact_id;
    if (cachedRaster(rasterCacheRef.current, id, frameSource, layers)) return true;
    // A numerical frame cached during inspection is expensive to redraw during
    // Play. Also finish loading newly enabled layers on a paused playback image.
    if (frame.playback_frame?.compositions[frameSource]
      && !failedRasterKeysRef.current.has(rasterCacheKey(id, frameSource, layers))) {
      if (playing || cachedRaster(rasterCacheRef.current, id, frameSource, layers & FieldRasterLayer.Base)) return false;
    }
    const exact = frameCacheRef.current[id];
    return Boolean(frameSource === 'pm' ? exact?.noload_plot : exact);
  }, [playing]);
  const bufferedAhead = useMemo(() => {
    let ready = 0;
    for (const preloadIndex of preloadIndices) {
      const preloadAngle = angleFrames[preloadIndex]?.angle_deg ?? 0;
      if (!visualFrameReady(nearestFrame(sourceFrames, preloadAngle), source, primaryLayers)) break;
      if (overlayActive && !visualFrameReady(nearestFrame(resultantFrames, preloadAngle), 'pm', overlayLayers)) break;
      ready += 1;
    }
    return ready;
  }, [
    angleFrames,
    frameCache,
    preloadIndices,
    rasterCache,
    primaryLayers,
    overlayActive,
    overlayLayers,
    resultantFrames,
    visualFrameReady,
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
          ? [availableRasterKey(rasterCache, preloadArtifactId, source, primaryLayers)]
          : []),
        ...(overlayArtifactIdAhead
          ? [availableRasterKey(rasterCache, overlayArtifactIdAhead, 'pm', overlayLayers)]
          : []),
      ];
    }),
  ), [angleFrames, overlayActive, overlayLayers, preloadIndices, primaryLayers, rasterCache, resultantFrames, source, sourceFrames]);
  const upcomingRasterKeysRef = useRef(upcomingRasterKeys);
  upcomingRasterKeysRef.current = upcomingRasterKeys;
  const keptRasterKeys = useCallback((loadedKey?: string): Set<string> => {
    const keep = new Set(upcomingRasterKeysRef.current);
    if (loadedKey) keep.add(loadedKey);
    if (activeRasterKeyRef.current) keep.add(activeRasterKeyRef.current);
    if (overlayRasterKeyRef.current) keep.add(overlayRasterKeyRef.current);
    return keep;
  }, []);

  const loadFrame = useCallback((requestedArtifactId: string, warmSource?: FieldSource): Promise<PublicFieldLinePlot> => {
    const cached = frameCacheRef.current[requestedArtifactId];
    if (cached) return Promise.resolve(cached);

    const pending = frameRequestsRef.current.get(requestedArtifactId);
    if (pending) return pending;

    const generation = frameGenerationRef.current;
    const request = getPublicFieldFrame(requestedArtifactId)
      .then(async (payload) => {
        const frame = payload.field_line_frame as unknown as PublicFieldLinePlot;
        // A numerical-only fallback needs drawable layers. Inspecting a saved
        // image only needs the numerical values and exact geometry on demand.
        if (warmSource) await prepareFrameForPlayback(frame, warmSource);
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
    requestedLayers = primaryLayers,
  ): Promise<FieldResultRaster | null> => {
    const requestedArtifactId = requestedDescriptor.field_frame_artifact.artifact_id;
    const key = rasterCacheKey(requestedArtifactId, requestedSource, requestedLayers);
    const cached = cachedRaster(rasterCacheRef.current, requestedArtifactId, requestedSource, requestedLayers);
    if (cached) return Promise.resolve(cached);
    // A scrub request may have queued before a previous request recovered from
    // a missing image. Recheck its fallback when the queued request starts.
    if (failedRasterKeysRef.current.has(key)) {
      const exact = frameCacheRef.current[requestedArtifactId];
      if (requestedSource === 'pm' ? exact?.noload_plot : exact) return Promise.resolve(null);
    }
    const pending = rasterRequestsRef.current.get(key);
    if (pending) return pending;
    const generation = frameGenerationRef.current;
    const request = (rasterizerRef.current
      ? rasterizerRef.current.render(
        requestedArtifactId,
        requestedSource,
        requestedDescriptor.playback_frame,
        requestedLayers,
      )
      : Promise.reject(new Error('Field playback workers are unavailable.')))
      .then((raster) => {
        if (frameGenerationRef.current !== generation) {
          closeRaster(raster);
          return null;
        }
        failedRasterKeysRef.current.delete(key);
        const nextCache = {
          ...rasterCacheRef.current,
          [key]: raster,
        };
        evictRasters(nextCache, rasterCacheLimitRef.current, keptRasterKeys(key), retireRaster);
        rasterCacheRef.current = nextCache;
        setRasterCache(nextCache);
        return raster;
      })
      .catch(async () => {
        if (frameGenerationRef.current !== generation) return null;
        const frame = await loadFrame(requestedArtifactId, requestedSource);
        if (requestedSource === 'pm' && !frame.noload_plot) throw new Error('The PM field is unavailable for this position.');
        if (frameGenerationRef.current === generation && requestedDescriptor.playback_frame) {
          failedRasterKeysRef.current.add(key);
        }
        return null;
      })
      .finally(() => {
        if (rasterRequestsRef.current.get(key) === request) {
          rasterRequestsRef.current.delete(key);
        }
      });
    rasterRequestsRef.current.set(key, request);
    return request;
  }, [keptRasterKeys, loadFrame, primaryLayers, retireRaster]);

  useEffect(() => {
    const rasterizer = new FieldPlaybackRasterizer();
    rasterizerRef.current = rasterizer;
    return () => {
      frameLoaderRef.current.clear();
      frameGenerationRef.current += 1;
      detailRequestRef.current += 1;
      if (rasterizerRef.current === rasterizer) rasterizerRef.current = null;
      rasterizer.dispose();
      const departingRasters = new Set([...Object.values(rasterCacheRef.current), ...retiredRastersRef.current]);
      if (detailRasterRef.current) departingRasters.add(detailRasterRef.current.raster);
      departingRasters.forEach(closeRaster);
      retiredRastersRef.current.clear();
      rasterCacheRef.current = {};
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

  useEffect(() => {
    if (drawnRaster) setHeldRaster({ source, raster: drawnRaster, angleDeg: descriptorAngleDeg });
  }, [drawnRaster, descriptorAngleDeg, source]);

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
    failedRasterKeysRef.current.clear();
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
    let sampleWindowMs = 0;
    let waitingMs = 0;
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
        const nextReady = visualFrameReady(nextDescriptor, source, primaryLayers);
        const nextOverlay = overlayActive ? nearestFrame(resultantFrames, nextAngle) : null;
        const nextOverlayId = nextOverlay?.field_frame_artifact.artifact_id;
        const nextOverlayReady = !nextOverlayId
          || visualFrameReady(nextOverlay, 'pm', overlayLayers);
        // A slow decode or a tab resuming should not set the rate for a whole
        // session. Use the normal stride if loading stalls a fifth of a second
        // or more over one second of active playback.
        if (fastPmArrows && elapsedMs < MAX_PLAYBACK_CATCHUP_MS) {
          sampleWindowMs += elapsedMs;
          if (!nextReady) waitingMs += elapsedMs;
          if (sampleWindowMs >= 1000) {
            if (waitingMs >= 200) setPmPlaybackLimited(true);
            sampleWindowMs = 0;
            waitingMs = 0;
          }
        }
        if (nextDescriptor && nextArtifactId && !nextReady) {
          void loadVisualFrame(nextDescriptor, source).catch(() => {
            setPlaybackWaiting(false);
            setPlaying(false);
          });
          setPlaybackWaiting(true);
        } else if (nextOverlay && !nextOverlayReady) {
          void loadVisualFrame(nextOverlay, 'pm', overlayLayers).catch(() => {
            setPlaybackWaiting(false);
            setPlaying(false);
          });
          setPlaybackWaiting(true);
        } else {
          playbackElectricalAngleRef.current = nextPlaybackAngleDeg;
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
    fastPmArrows,
    loadVisualFrame,
    overlayActive,
    overlayLayers,
    primaryLayers,
    visualFrameReady,
    playing,
    polePairs,
    playbackSpan,
    playbackSpanDeg,
    resultantFrames,
    source,
    sourceFrames,
  ]);

  useEffect(() => {
    if (exactVectorPlot) setRetainedPlot({ source, plot: exactVectorPlot, angleDeg: exactVectorAngleDeg });
  }, [exactVectorPlot, exactVectorAngleDeg, source]);

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
      if (preloadDescriptor && !visualFrameReady(preloadDescriptor, source, primaryLayers)) {
        void loadVisualFrame(preloadDescriptor, source).catch(() => undefined);
      }
      const preloadOverlay = overlayActive ? nearestFrame(resultantFrames, preloadAngle) : null;
      if (preloadOverlay && !visualFrameReady(preloadOverlay, 'pm', overlayLayers)) {
        void loadVisualFrame(preloadOverlay, 'pm', overlayLayers).catch(() => undefined);
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
    overlayLayers,
    primaryLayers,
    visualFrameReady,
    source,
    sourceFrames,
  ]);

  useEffect(() => {
    // The PM frame on screen in Stator + PM: its playback raster at once, and
    // its exact frame once the stator frame has settled.
    if (!overlayActive || !overlayDescriptor || !overlayArtifactId) return;
    if (!visualFrameReady(overlayDescriptor, 'pm', overlayLayers)) {
      void loadVisualFrame(overlayDescriptor, 'pm', overlayLayers).catch(() => undefined);
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
    overlayLayers,
    playing,
    visualFrameReady,
  ]);

  useEffect(() => {
    if (!artifactId) {
      setFrameLoading(false);
      return;
    }
    if (visualFrameReady(descriptor, source, primaryLayers)) {
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
  }, [artifactId, descriptor, frameCache, loadVisualFrame, playing, primaryLayers, rasterCache, source, visualFrameReady]);

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
      // Show each field's poles when comparing the stator and magnets.
      setShowPoleLabels(true);
      setShowToothPoles(true);
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

  // Switching to a view whose playback is still being drawn stops playback.
  useEffect(() => {
    if (!playbackPreparing) return;
    setPlaying(false);
    setPlaybackWaiting(false);
  }, [playbackPreparing]);

  // Play and pause from the shown position; stop goes back to the first, as
  // in the Geometry preview.
  const togglePlayback = () => {
    if (!playing) setPmPlaybackLimited(false);
    setPlaybackWaiting(false);
    setPlaying(!playing);
  };
  const stopPlayback = () => {
    setPlaying(false);
    setPlaybackWaiting(false);
    frameIndexRef.current = 0;
    playbackElectricalAngleRef.current = angleFrames[0]?.angle_deg ?? 0;
    setFrameIndex(0);
  };

  // A position picked on a torque or back-EMF curve: pause and show the nearest
  // solved position, preloading its neighbours in the direction of travel.
  const scrubToAngle = (angleDeg: number) => {
    if (angleFrames.length < 2) return;
    const nextIndex = positionSliderFrameIndex(angleFrames, angleDeg, playbackSpan);
    const direction = angleDeg >= playbackElectricalAngleRef.current ? 1 : -1;
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
    playbackElectricalAngleRef.current = angleFrames[nextIndex]?.angle_deg ?? angleDeg;
    setFrameIndex(nextIndex);
  };
  const scrubToAngleRef = useRef(scrubToAngle);
  scrubToAngleRef.current = scrubToAngle;
  useEffect(() => positionLink?.subscribeRequests((angleDeg) => scrubToAngleRef.current(angleDeg)), [positionLink]);
  // The curves mark the shown position.
  useEffect(() => {
    positionLink?.setPlayhead(angleFrames.length > 0 ? electricalAngleDeg : null);
  }, [angleFrames.length, electricalAngleDeg, positionLink]);
  useEffect(() => () => positionLink?.setPlayhead(null), [positionLink]);

  const sourceLabel = overlayActive
    ? 'Stator and PM field arrows'
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
      ? 'Preparing solved geometry, flux density, and field direction'
      : source === 'armature' && !armature
        ? armatureError ?? 'Select Stator to compute the cached Br = 0 sweep.'
        : frameError;
  // The plot portals its zoom controls into the dock, off the field (#120 follow-up).
  const [zoomSlot, setZoomSlot] = useState<HTMLSpanElement | null>(null);
  // Flux density and field arrows change what the picture means, so they stay
  // in view; the reference layers wait in More, which counts how many are on.
  const phasesOn = showPhases && Boolean(phaseCycle);
  const renderMoreLayerButtons = () => (
    <>
      <button type="button" aria-pressed={magnifier} title="Show an enlarged view of the area under the pointer" onClick={() => setMagnifier((value) => !value)}><i aria-hidden="true" />Magnifier</button>
      {hasMagnets && <button type="button" aria-pressed={showMagnets} onClick={() => setShowMagnets((value) => !value)}><i aria-hidden="true" />{source === 'armature' && !overlayActive ? 'PM reference' : 'Magnets'}</button>}
      <button type="button" aria-pressed={showMesh} onClick={() => setShowMesh((value) => !value)}><i aria-hidden="true" />Mesh</button>
      <button type="button" aria-pressed={showAirgap} onClick={() => setShowAirgap((value) => !value)}><i aria-hidden="true" />Airgap</button>
      {hasMagnets && <button type="button" aria-pressed={showMagnets && showPoleLabels} disabled={!showMagnets} title="Label the displayed rotor magnets N or S" onClick={() => setShowPoleLabels((value) => !value)}><i aria-hidden="true" />Magnet labels</button>}
      <button
        type="button"
        aria-pressed={toothPolesAvailable && showToothPoles}
        disabled={!toothPolesAvailable}
        title={toothPolesAvailable
          ? 'Color each stator tooth red for north or blue for south at this position'
          : source === 'pm' ? 'The PM-only field has zero stator current'
            : 'Tooth poles need stator tooth geometry and recorded winding currents with nonzero excitation'}
        onClick={() => setShowToothPoles((value) => !value)}
      ><i aria-hidden="true" />Tooth poles</button>
      {/* As in the Geometry view: Phases brings the coil colours with it, and they can be turned off again. */}
      <button
        type="button"
        aria-pressed={phasesOn && showCoilColors}
        disabled={!phasesOn}
        title={!phasesOn ? 'Turn on Phases to color the coils by phase'
          : showCoilColors ? 'Hide the phase colors on the coils; the current marks and the A / B / C traces stay'
            : 'Outline each coil in its phase color'}
        onClick={() => setShowCoilColors((value) => !value)}
      ><i aria-hidden="true" />Coil colors</button>
    </>
  );
  const moreLayersOn = [
    phasesOn && showCoilColors,
    magnifier,
    hasMagnets && showMagnets,
    showMesh,
    showAirgap,
    hasMagnets && showMagnets && showPoleLabels,
    toothPolesAvailable && showToothPoles,
  ].filter(Boolean).length;
  // Arrow density sits right after Field arrows as a three-way choice, and only
  // while the arrows are shown.
  const densityAdjustable = Boolean(highResolutionPlot);
  const displayedDensity = densityAdjustable ? fieldLineDensity[view] : 'medium';
  const renderDensityControl = () => {
    const densityTitle = playing
      ? 'Playback uses medium arrow density. Pause to adjust the exact frame.'
      : densityAdjustable
        ? 'Arrow density: how closely the field arrows are spaced'
        : 'Loading the exact frame before arrow density can be changed.';
    return (
      <span className="public-field-density-choice" role="group" aria-label="Field-arrow density" title={densityTitle}>
        {FIELD_LINE_DENSITY_STOPS.map((stop) => (
          <button
            type="button"
            aria-pressed={displayedDensity === stop}
            disabled={!densityAdjustable}
            onClick={() => setFieldLineDensity(previous => ({ ...previous, [view]: stop }))}
            aria-label={`${stop === 'low' ? 'Low' : stop === 'medium' ? 'Medium' : 'High'} arrow density`}
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
        {(visibleRaster || visiblePlot) && (
          <>
            <FieldResultPlot
              ring={outerRotorRing(config)}
              plot={visiblePlot}
              raster={visibleRaster}
              highResolutionPlot={highResolutionPlot}
              probeEnabled={Boolean(highResolutionPlot) && !overlayActive}
              geometry={geometry}
              magnetRotationDeg={mechanicalAngleDeg}
              showMagnets={showMagnets}
              showStatistics={false}
              magnifier={magnifier}
              magnifierSlot={magnifierSlot}
              probeSlot={probeSlot}
              fitScale={FIELD_FIT_LIKE_MOTOR_CANVAS}
              rotorMarkDeg={mechanicalAngleDeg}
              showAirgap={showAirgap}
              // The field axes assume an inner rotor.
              airgapInnerRadiusMm={config.rotor_layout === 'outer' ? undefined : rotorAirgapBoundaryRadiusMm(config)}
              // An outer rotor's gap runs from the stator's outside out to the magnets' inner face.
              airgapRingMm={config.rotor_layout === 'outer' ? [config.stator.OD_mm / 2, config.stator.OD_mm / 2 + magneticAirgapMm(config)] : undefined}
              showMagnetPolarityLabels={showPoleLabels}
              magnetReference={source === 'armature' && !overlayActive}
              toothPoleStrengths={toothPoleStrengths}
              statorPolarityProfile={descriptor?.airgap_brbt ?? exactVectorPlot?.airgap_brbt}
              statorPolarityRotationDeg={statorPolarityRotationDeg}
              statorInnerRadiusMm={config.rotor_layout === 'outer' ? undefined : config.stator.ID_mm / 2}
              poles={config.rotor.pole_count}
              showHeatmap={showHeatmap && !overlayActive}
              showMesh={showMesh}
              showFieldLines={showFieldLines}
              fieldLineDensity={displayedDensity}
              colorRangeMode={colorRangeMode}
              saturationTicks={saturationTicks}
              onColorRangeModeChange={setRangeMode}
              showControls={false}
              showHeading={false}
              title={sourceLabel}
              subtitle={sourceDetail}
              describeProbe={describeProbe}
              onViewportScaleSettled={setFieldViewportScale}
              overlay={fieldLineOverlay}
              pmLines={source === 'pm'}
              fieldAxes={overlayActive ? fieldAxes : null}
              navigationSlot={zoomSlot}
              phases={phaseView}
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
            {(visibleRaster || visiblePlot) && (
              <div className="viewport-cad-status">
                {playbackWaiting && <small className="public-field-playback-buffering" aria-live="polite">Buffering… </small>}
                {shownElectricalAngleDeg.toFixed(1)}° elec<span className="public-field-text-long"> · peak |B| {currentPeakBT.toFixed(2)} T</span>
              </div>
            )}
            <details className="public-field-physics-info">
              <summary aria-label="Field details" title="Field details">i</summary>
              <div className="public-field-summary-panel">
                <span>Field composition</span>
                <strong>{sourceLabel}</strong>
                <p>{sourceDetail}</p>
                {(visibleRaster || visiblePlot) && (
                  <dl>
                    <div><dt>Peak |B|</dt><dd>{currentPeakBT.toFixed(3)} T</dd></div>
                    <div><dt>Position</dt><dd>{shownElectricalAngleDeg.toFixed(1)}° elec</dd></div>
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
              <span className={`public-field-source-pair${overlayActive ? ' is-both' : ''}`} role="group" aria-label="Separate fields: PM, Stator, or both together" title="Pick PM, Stator, or both to draw their field arrows together">
                <button type="button" className="is-pm" aria-label="PM-only field, zero current" title="Exact zero-current Magneto2D field" aria-pressed={pmShown} disabled={!pmAvailable} onClick={() => toggleSeparateField('pm')}><strong>PM</strong></button>
                <button type="button" className="is-stator" aria-label="Stator-current-only field, permanent-magnet remanence disabled" title={magnetoCompositionAvailable ? 'Exact zero-remanence Magneto2D field' : statorFieldUnavailableReason ?? 'Stator-only composition is available for Magneto2D results'} aria-pressed={statorShown} disabled={!magnetoCompositionAvailable} onClick={() => toggleSeparateField('armature')}><strong>Stator</strong></button>
              </span>
            </div>
          </div>
          <div className="public-field-control-cluster public-field-overlay-cluster">
            <span>Show</span>
            <div className="public-field-layer-controls public-field-layer-controls-inline" role="group" aria-label="Field solution overlays">
              <button type="button" aria-pressed={showHeatmap && !overlayActive} disabled={overlayActive} title={overlayActive ? 'Off while PM and Stator are both shown: one |B| map cannot belong to both fields' : undefined} onClick={() => setShowHeatmap((value) => !value)} aria-label="Flux density"><i aria-hidden="true" /><span className="public-field-text-long">Flux density</span><span className="public-field-text-short" aria-hidden="true">Flux</span></button>
              <button type="button" aria-pressed={showFieldLines} onClick={() => setShowFieldLines((value) => !value)} aria-label="Field arrows" title="Small arrows along the magnetic field B"><i aria-hidden="true" /><span className="public-field-text-long">Field arrows</span><span className="public-field-text-short" aria-hidden="true">Arrows</span></button>
              {showFieldLines && renderDensityControl()}
              <button
                type="button"
                aria-pressed={showPhases && Boolean(phaseCycle)}
                disabled={!phaseCycle}
                title={phaseCycle
                  ? 'Coils by phase, which way their current flows at this position, and the A / B / C currents the solver applied'
                  : 'This run did not record the phase currents it applied: solve it again to show them'}
                onClick={() => setShowPhases((value) => !value)}
                aria-label="Phases"
              ><i aria-hidden="true" /><span className="public-field-text-long">Phases</span><span className="public-field-text-short" aria-hidden="true">Phases</span></button>
            </div>
            <details className="public-field-layer-menu" {...fieldLayerMenu}>
              <summary>More{moreLayersOn > 0 && <em>{moreLayersOn} on</em>}</summary>
              <div className="public-field-layer-controls" role="group" aria-label="More field layers">
                {renderMoreLayerButtons()}
              </div>
            </details>
          </div>
        </div>
        <div className="public-field-playback">
          <span className="public-field-playback-label" aria-hidden="true">Play</span>
          <button
            className="public-field-transport-play"
            type="button"
            aria-label={playing ? 'Pause clockwise field playback' : 'Play field clockwise'}
            title={playbackUnavailableReason || (playbackPreparing
              ? `${playbackPreparingLabel}: Play starts once every position is drawn.`
              : colorRangeMode === 'viewport'
                ? 'Switch the flux-density range to Fixed to animate.'
                : 'Clockwise — follows the public solve angle convention')}
            disabled={Boolean(playbackUnavailableReason) || angleFrames.length < 2 || colorRangeMode === 'viewport' || playbackPreparing}
            onClick={togglePlayback}
          >
            {playing ? 'Ⅱ' : '▶'}
          </button>
          <button
            className="public-field-transport-play"
            type="button"
            aria-label="Stop and go to the first position"
            title="Stop and go to the first position"
            disabled={angleFrames.length < 2}
            onClick={stopPlayback}
          >
            ■
          </button>
          <RpmField
            value={playbackRpm}
            min={PUBLIC_FIELD_PLAYBACK_MIN_RPM}
            max={PUBLIC_FIELD_PLAYBACK_MAX_RPM}
            label="Speed"
            ariaLabel="Playback speed (RPM)"
            title="Visual playback speed — not the solve operating point. Type 0.1 to 100 or use the arrows (tenths below 1 RPM); Shift+arrow steps by 10."
            onChange={setPlaybackRpm}
          />
          {playbackUnavailableReason && <span className="public-field-playback-preparing" role="status">{playbackUnavailableReason}</span>}
          {playbackPreparing && !playbackUnavailableReason && (
            <span className="public-field-playback-preparing" role="status" aria-live="polite">{playbackPreparingLabel}</span>
          )}
        </div>
      </div>
    </section>
  );
}
