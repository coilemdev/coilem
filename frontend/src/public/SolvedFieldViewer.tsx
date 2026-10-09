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
  type FieldProbe,
  type FieldProbeDescription,
  type FieldResultRaster,
} from './FieldResultPlot';
import {
  fieldPlaybackSweepMaxT,
  normalizeFieldPlaybackManifest,
} from './fieldPlaybackContract';
import {
  FieldPlaybackRasterizer,
  type FieldRasterSource,
} from './fieldPlaybackRasterizer';
import {
  advancePlaybackElectricalAngle,
  nearestPlaybackFrameIndex,
  normalizePlaybackElectricalAngle,
  playbackCycleSpanDeg,
  playbackLookaheadFrameIndices,
  PUBLIC_FIELD_PLAYBACK_DEFAULT_RPM,
  PUBLIC_FIELD_PLAYBACK_MAX_RPM,
  PUBLIC_FIELD_PLAYBACK_MIN_RPM,
  publicFieldPlaybackBufferFrames,
  publicFieldPlaybackCacheFrames,
} from './fieldPlaybackTiming';
import { rotorAirgapBoundaryRadiusMm } from './motorAirgap';
import type {
  GeometryPreview,
  MotorConfig,
  PublicAirgapProfileDescriptor,
  PublicArmatureFieldComposition,
  PublicFieldFrameDescriptor,
  PublicFieldLinePlot,
  PublicFieldPlaybackManifest,
  SolveResult,
} from './model';

type FieldSource = 'resultant' | 'pm' | 'armature';
const IDLE_BUFFER_FRAMES = 4;
const DETAIL_VIEWPORT_SCALE = 1.08;
const MAX_PLAYBACK_CATCHUP_MS = 250;
const FIELD_LINE_DENSITY_STOPS: readonly FieldLineDensity[] = ['low', 'medium', 'high'];

function prepareFrameForPlayback(frame: PublicFieldLinePlot): Promise<PublicFieldLinePlot> {
  return new Promise((resolve) => {
    const prepare = () => {
      warmFieldResultPlot(frame);
      resolve(frame);
    };
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(prepare, { timeout: 180 });
    } else {
      window.setTimeout(prepare, 0);
    }
  });
}

function rasterCacheKey(artifactId: string, source: FieldRasterSource): string {
  return `${source}:${artifactId}`;
}

function closeRaster(raster: FieldResultRaster): void {
  raster.base.close();
  raster.heat.close();
  raster.mesh?.close();
  raster.lines.close();
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
  geometry: GeometryPreview | null;
  result: SolveResult;
  armature: PublicArmatureFieldComposition | null;
  armatureBusy: boolean;
  armatureError: string | null;
  armatureProgress: PublicSolveProgress | null;
  magnetoCompositionAvailable: boolean;
  onRequestArmature: () => void;
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
  geometry,
  result,
  armature,
  armatureBusy,
  armatureError,
  armatureProgress,
  magnetoCompositionAvailable,
  onRequestArmature,
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
  const [source, setSource] = useState<FieldSource>('resultant');
  const [frameIndex, setFrameIndex] = useState(0);
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [showMesh, setShowMesh] = useState(false);
  const [showFieldLines, setShowFieldLines] = useState(true);
  const [showMagnets, setShowMagnets] = useState(true);
  const [showAirgap, setShowAirgap] = useState(false);
  const [showPoleLabels, setShowPoleLabels] = useState(false);
  const [fieldLineDensity, setFieldLineDensity] = useState<FieldLineDensity>('medium');
  const [colorRangeMode, setColorRangeMode] = useState<FieldColorRangeMode>('viewport');
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
  const replaceDetailRaster = useCallback((next: {
    key: string;
    raster: FieldResultRaster;
  } | null) => {
    const current = detailRasterRef.current;
    if (current && current.raster !== next?.raster) closeRaster(current.raster);
    detailRasterRef.current = next;
    setDetailRaster(next);
  }, []);

  // Public Magneto2D solves already map increasing UI angles to the solver's
  // negative (clockwise) native rotor positions. Preserve the stored,
  // increasing 0..360° electrical sequence here; reversing it would apply the
  // direction conversion twice and make the motor play counterclockwise.
  const angleFrames = resultantFrames.length > 0 ? resultantFrames : armatureFrames;
  const boundedIndex = Math.min(frameIndex, Math.max(0, angleFrames.length - 1));
  const playbackSpanDeg = playbackCycleSpanDeg(angleFrames);
  const streamingArmatureFrame = source === 'armature' && armatureBusy
    ? armatureFrames[armatureFrames.length - 1] ?? null
    : null;
  const electricalAngleDeg = streamingArmatureFrame?.angle_deg
    ?? angleFrames[boundedIndex]?.angle_deg
    ?? 0;
  const sourceFrames = source === 'armature' ? armatureFrames : resultantFrames;
  const descriptor = streamingArmatureFrame ?? nearestFrame(sourceFrames, electricalAngleDeg);
  const artifactId = descriptor?.field_frame_artifact.artifact_id ?? null;
  const activeRasterKey = artifactId ? rasterCacheKey(artifactId, source) : null;
  activeRasterKeyRef.current = activeRasterKey;
  const activeRaster = activeRasterKey ? rasterCache[activeRasterKey] : null;
  const activeDetailRaster = detailRaster?.key === activeRasterKey
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
  const visibleRaster = activeRaster;
  const currentPeakBT = useMemo(() => {
    const rasterPeak = activeDetailRaster?.maxB ?? visibleRaster?.maxB;
    if (Number.isFinite(rasterPeak)) return rasterPeak ?? 0;
    const values = visiblePlot?.element_b_mag_t.filter(Number.isFinite) ?? [];
    return values.reduce((peak, value) => Math.max(peak, value), 0);
  }, [activeDetailRaster?.maxB, visiblePlot, visibleRaster?.maxB]);
  const sweepScaleMaxT = useMemo(() => {
    const playbackFrames = sourceFrames.flatMap((frame) => (
      frame.playback_frame ? [frame.playback_frame] : []
    ));
    return Math.max(
      0.001,
      currentPeakBT,
      fieldPlaybackSweepMaxT(playbackFrames, source) ?? 0,
    );
  }, [currentPeakBT, source, sourceFrames]);
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
  const bufferTarget = playbackLookaheadIndices.length;
  const bufferedAhead = useMemo(() => {
    let ready = 0;
    for (const preloadIndex of playbackLookaheadIndices) {
      const preloadAngle = angleFrames[preloadIndex]?.angle_deg ?? 0;
      const preloadArtifactId = nearestFrame(sourceFrames, preloadAngle)?.field_frame_artifact.artifact_id;
      if (
        !preloadArtifactId
        || (
          !rasterCache[rasterCacheKey(preloadArtifactId, source)]
          && !frameCache[preloadArtifactId]
        )
      ) break;
      ready += 1;
    }
    return ready;
  }, [
    angleFrames,
    frameCache,
    playbackLookaheadIndices,
    rasterCache,
    source,
    sourceFrames,
  ]);

  const loadFrame = useCallback((requestedArtifactId: string): Promise<PublicFieldLinePlot> => {
    const cached = frameCacheRef.current[requestedArtifactId];
    if (cached) return Promise.resolve(cached);

    const pending = frameRequestsRef.current.get(requestedArtifactId);
    if (pending) return pending;

    const generation = frameGenerationRef.current;
    const request = getPublicFieldFrame(requestedArtifactId)
      .then(async (payload) => {
        const frame = payload.field_line_frame as unknown as PublicFieldLinePlot;
        await prepareFrameForPlayback(frame);
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
  ): Promise<FieldResultRaster | null> => {
    const requestedArtifactId = requestedDescriptor.field_frame_artifact.artifact_id;
    const key = rasterCacheKey(requestedArtifactId, requestedSource);
    const cached = rasterCacheRef.current[key];
    if (cached) return Promise.resolve(cached);
    const pending = rasterRequestsRef.current.get(key);
    if (pending) return pending;
    const generation = frameGenerationRef.current;
    const request = (rasterizerRef.current
      ? rasterizerRef.current.render(
        requestedArtifactId,
        requestedSource,
        requestedDescriptor.playback_frame,
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
        const cachedKeys = Object.keys(nextCache);
        while (
          cachedKeys.length
          > publicFieldPlaybackCacheFrames(playbackRpmRef.current)
        ) {
          const expiredKey = cachedKeys.shift();
          if (
            expiredKey
            && expiredKey !== key
            && expiredKey !== activeRasterKeyRef.current
          ) {
            closeRaster(nextCache[expiredKey]);
            delete nextCache[expiredKey];
          } else if (expiredKey) {
            cachedKeys.push(expiredKey);
          }
        }
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
  }, [loadFrame]);

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
    frameGenerationRef.current += 1;
    Object.values(rasterCacheRef.current).forEach(closeRaster);
    frameCacheRef.current = {};
    rasterCacheRef.current = {};
    frameRequestsRef.current.clear();
    rasterRequestsRef.current.clear();
    setSource('resultant');
    setFrameIndex(0);
    frameIndexRef.current = 0;
    playbackElectricalAngleRef.current = 0;
    setPlaying(false);
    setPlaybackWaiting(false);
    setFrameCache({});
    setRasterCache({});
    setRetainedPlot(null);
    setFieldViewportScale(1);
    setColorRangeMode('viewport');
    setDetailPlot(null);
    replaceDetailRaster(null);
    detailRequestRef.current += 1;
    setFrameError(null);
  }, [replaceDetailRaster, result]);

  useEffect(() => {
    frameIndexRef.current = boundedIndex;
  }, [boundedIndex]);

  const syncPlaybackSlider = useCallback((electricalAngle: number) => {
    if (!playbackSliderRef.current) return;
    playbackSliderRef.current.value = String(
      normalizePlaybackElectricalAngle(electricalAngle),
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

    const cachedRasterKeys = Object.keys(rasterCacheRef.current);
    if (cachedRasterKeys.length > cacheLimit) {
      const nextRasterCache = { ...rasterCacheRef.current };
      while (cachedRasterKeys.length > cacheLimit) {
        const expiredKey = cachedRasterKeys.shift();
        if (expiredKey === activeRasterKeyRef.current) {
          cachedRasterKeys.push(expiredKey);
          continue;
        }
        if (expiredKey) {
          closeRaster(nextRasterCache[expiredKey]);
          delete nextRasterCache[expiredKey];
        }
      }
      rasterCacheRef.current = nextRasterCache;
      setRasterCache(nextRasterCache);
    }
  }, [playbackRpm]);

  useEffect(() => {
    if (!playing || angleFrames.length < 2) return undefined;
    let lastSampleAt: number | null = null;
    let animationFrameId = 0;
    const animate = (timestamp: number) => {
      if (lastSampleAt !== null) {
        const elapsedMs = timestamp - lastSampleAt;
        const nextPlaybackAngleDeg = advancePlaybackElectricalAngle(
          playbackElectricalAngleRef.current,
          Math.min(elapsedMs, MAX_PLAYBACK_CATCHUP_MS),
          playbackRpmRef.current,
          polePairs,
        );
        const nextSolvedAngleDeg = normalizePlaybackElectricalAngle(
          nextPlaybackAngleDeg,
          playbackSpanDeg,
        );
        const nextIndex = nearestPlaybackFrameIndex(
          angleFrames,
          nextSolvedAngleDeg,
          playbackSpanDeg,
        );
        const nextAngle = angleFrames[nextIndex]?.angle_deg ?? 0;
        const nextDescriptor = nearestFrame(sourceFrames, nextAngle);
        const nextArtifactId = nextDescriptor?.field_frame_artifact.artifact_id;
        const nextReady = nextArtifactId
          && (
            rasterCacheRef.current[rasterCacheKey(nextArtifactId, source)]
            || frameCacheRef.current[nextArtifactId]
          );
        if (nextDescriptor && nextArtifactId && !nextReady) {
          void loadVisualFrame(nextDescriptor, source).catch(() => {
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
    playing,
    polePairs,
    playbackSpanDeg,
    source,
    sourceFrames,
    syncPlaybackSlider,
  ]);

  useEffect(() => {
    if (activePlot) setRetainedPlot({ source, plot: activePlot });
  }, [activePlot, source]);

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
    if (activeDetailPlot || activeDetailRaster) return;

    const requestId = ++detailRequestRef.current;
    // Prefer exact solver vectors for a stopped, zoomed frame. Playback WebPs
    // keep animation fast, while the numerical artifact has no raster ceiling.
    // Older caches retained only frame zero, so their detail WebP remains the
    // compatibility fallback when the numerical endpoint returns 404.
    const loadNumericalDetail = () => getPublicFieldFrame(artifactId)
      .then((payload) => {
        if (detailRequestRef.current !== requestId) return false;
        const outerPlot = payload.field_line_frame as unknown as PublicFieldLinePlot;
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
    fieldViewportScale,
    playing,
    replaceDetailRaster,
    source,
  ]);

  useEffect(() => {
    if (angleFrames.length < 2) return;
    for (const preloadIndex of playbackLookaheadIndices) {
      const preloadAngle = angleFrames[preloadIndex]?.angle_deg ?? 0;
      const preloadDescriptor = nearestFrame(sourceFrames, preloadAngle);
      const preloadArtifactId = preloadDescriptor?.field_frame_artifact.artifact_id;
      if (
        preloadDescriptor
        && preloadArtifactId
        && !rasterCacheRef.current[rasterCacheKey(preloadArtifactId, source)]
        && !frameCacheRef.current[preloadArtifactId]
      ) {
        void loadVisualFrame(preloadDescriptor, source).catch(() => undefined);
      }
    }
  }, [
    angleFrames,
    loadVisualFrame,
    playbackLookaheadIndices,
    source,
    sourceFrames,
  ]);

  useEffect(() => {
    if (!artifactId) {
      setFrameLoading(false);
      return;
    }
    if (
      rasterCacheRef.current[rasterCacheKey(artifactId, source)]
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
    void loadVisualFrame(descriptor, source)
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
  }, [artifactId, descriptor, frameCache, loadVisualFrame, rasterCache, source]);

  useEffect(() => {
    if (playing || !artifactId || activePlot) return;
    // A stopped frame keeps its compact playback raster for immediate display,
    // then loads the exact numerical mesh for probing, density control, and a
    // genuinely fixed color range.
    void loadFrame(artifactId).catch(() => undefined);
  }, [activePlot, artifactId, loadFrame, playing]);

  const selectSource = (nextSource: FieldSource) => {
    if (nextSource === 'armature' && !magnetoCompositionAvailable) return;
    setSource(nextSource);
    setPlaying(false);
    setPlaybackWaiting(false);
    if (nextSource !== 'armature') setRetainedPlot(null);
    setDetailPlot(null);
    replaceDetailRaster(null);
    detailRequestRef.current += 1;
    if (nextSource === 'armature' && !armature && !armatureBusy) onRequestArmature();
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

  const sourceLabel = source === 'resultant' ? 'Resultant field' : source === 'pm' ? 'PM-only field' : 'Stator-current field';
  const sourceDetail = source === 'resultant'
    ? 'Permanent magnets and stator current'
    : source === 'pm'
      ? 'Exact zero-current Magneto2D frames'
      : 'PM remanence off · exact stator field';
  const setRangeMode = (nextMode: FieldColorRangeMode) => {
    setColorRangeMode(nextMode);
    if (nextMode === 'sweep') {
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
        ? armatureError ?? 'Select Stator only to compute the cached Br = 0 sweep.'
        : frameError;
  const renderLayerButtons = () => (
    <>
      {hasMagnets && <button type="button" aria-pressed={showMagnets} onClick={() => setShowMagnets((value) => !value)}><i aria-hidden="true" />{source === 'armature' ? 'PM reference' : 'Magnets'}</button>}
      <button type="button" aria-pressed={showHeatmap} onClick={() => setShowHeatmap((value) => !value)}><i aria-hidden="true" />Flux density</button>
      <button type="button" aria-pressed={showMesh} onClick={() => setShowMesh((value) => !value)}><i aria-hidden="true" />Mesh</button>
      <button type="button" aria-pressed={showAirgap} onClick={() => setShowAirgap((value) => !value)}><i aria-hidden="true" />Airgap</button>
      <button type="button" aria-pressed={showFieldLines} onClick={() => setShowFieldLines((value) => !value)}><i aria-hidden="true" />Field lines</button>
      {(hasMagnets || source === 'armature') && <button type="button" aria-pressed={showPoleLabels} onClick={() => setShowPoleLabels((value) => !value)}><i aria-hidden="true" />Pole labels</button>}
    </>
  );
  const renderDensityControl = (inline = false) => {
    const densityAdjustable = !playing && Boolean(exactVectorPlot);
    const displayedDensity = exactVectorPlot ? fieldLineDensity : 'medium';
    const densityIndex = Math.max(0, FIELD_LINE_DENSITY_STOPS.indexOf(displayedDensity));
    const densityLabel = displayedDensity === 'medium'
      ? 'Medium'
      : `${displayedDensity.charAt(0).toUpperCase()}${displayedDensity.slice(1)}`;
    const densityTitle = playing
      ? 'Playback uses medium field-line density. Pause to adjust the exact frame.'
      : densityAdjustable
        ? `${densityLabel} field-line density`
        : 'Loading the exact frame before field-line density can be changed.';
    return (
      <label className={`public-field-density-control${inline ? ' public-field-density-control-inline' : ''}`}>
        <span>{inline ? 'Lines' : 'Line density'}</span>
        <input
          type="range"
          min="0"
          max="2"
          step="1"
          value={densityIndex}
          disabled={!densityAdjustable}
          aria-label="Field-line density"
          aria-valuetext={densityLabel}
          title={densityTitle}
          style={{ ['--public-field-density-progress' as never]: `${densityIndex * 50}%` }}
          onChange={(event) => {
            const nextDensity = FIELD_LINE_DENSITY_STOPS[Number(event.currentTarget.value)];
            if (nextDensity) setFieldLineDensity(nextDensity);
          }}
        />
        <small aria-hidden="true"><span>Low</span><span>Med</span><span>High</span></small>
      </label>
    );
  };

  return (
    <section className="public-solved-field-viewer" aria-label="Completed field solution">
      <div className="public-solved-field-toolbar">
        {viewControls}
        <div className="public-field-toolbar-groups">
          <div className="public-field-control-cluster">
            <span>Source</span>
            <div className="public-field-source-controls" role="group" aria-label="Field composition">
              <button type="button" aria-label="Resultant field, permanent magnets plus stator current" title="Permanent magnets plus stator current" aria-pressed={source === 'resultant'} onClick={() => selectSource('resultant')}><strong>Resultant</strong></button>
              <button type="button" aria-label="PM-only field, zero current" title="Exact zero-current Magneto2D field" aria-pressed={source === 'pm'} disabled={!pmAvailable} onClick={() => selectSource('pm')}><strong>PM only</strong></button>
              <button type="button" aria-label="Stator-current-only field, permanent-magnet remanence disabled" title={magnetoCompositionAvailable ? 'Exact zero-remanence Magneto2D field' : 'Stator-only composition is available for Magneto2D results'} aria-pressed={source === 'armature'} disabled={!magnetoCompositionAvailable} onClick={() => selectSource('armature')}><strong>Stator only</strong></button>
            </div>
          </div>
          <div className="public-field-control-cluster public-field-overlay-cluster">
            <span>Overlays</span>
            <div className="public-field-layer-controls public-field-layer-controls-inline" role="group" aria-label="Field solution overlays">
              {renderLayerButtons()}
            </div>
          </div>
        </div>
        <div className="public-field-toolbar-end">
          <details className="public-field-layer-menu">
            <summary>Overlays</summary>
            <div className="public-field-layer-controls" role="group" aria-label="Field solution overlays">
              {renderLayerButtons()}
              {showFieldLines && renderDensityControl()}
            </div>
          </details>
          {showFieldLines && renderDensityControl(true)}
          {expandControl}
        </div>
      </div>

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
            <progress
              max={Math.max(1, armatureProgress?.total ?? 1)}
              value={Math.max(0, armatureProgress?.position ?? 0)}
            />
          </div>
        )}
        {(activeDetailRaster || visibleRaster || visiblePlot) && (
          <>
            <details className="public-field-summary">
              <summary>Field details</summary>
              <div className="public-field-summary-panel">
                <span>Field composition</span>
                <strong>{sourceLabel}</strong>
                <p>{sourceDetail}</p>
                <dl>
                  <div><dt>Peak |B|</dt><dd>{currentPeakBT.toFixed(3)} T</dd></div>
                  <div><dt>Position</dt><dd>{electricalAngleDeg.toFixed(1)}° elec</dd></div>
                </dl>
              </div>
            </details>
            <FieldResultPlot
              plot={visiblePlot}
              raster={activeDetailRaster ?? visibleRaster}
              highResolutionPlot={exactVectorPlot}
              probeEnabled={!playing && Boolean(exactVectorPlot)}
              geometry={geometry}
              magnetRotationDeg={mechanicalAngleDeg}
              showMagnets={showMagnets}
              showAirgap={showAirgap}
              airgapInnerRadiusMm={rotorAirgapBoundaryRadiusMm(config)}
              showMagnetPolarityLabels={showPoleLabels}
              magnetReference={source === 'armature'}
              showStatorPolarity={source === 'armature' && showPoleLabels}
              showPolarityLegend={source === 'armature' && showPoleLabels}
              statorPolarityProfile={descriptor?.airgap_brbt ?? exactVectorPlot?.airgap_brbt}
              statorPolarityRotationDeg={statorPolarityRotationDeg}
              statorInnerRadiusMm={config.stator.ID_mm / 2}
              poles={config.rotor.pole_count}
              showHeatmap={showHeatmap}
              showMesh={showMesh}
              showFieldLines={showFieldLines}
              fieldLineDensity={exactVectorPlot ? fieldLineDensity : 'medium'}
              colorRangeMode={colorRangeMode}
              sweepScaleMaxT={sweepScaleMaxT}
              showRangeControl
              onColorRangeModeChange={setRangeMode}
              showControls={false}
              showHeading={false}
              title={sourceLabel}
              subtitle={sourceDetail}
              describeProbe={describeProbe}
              onViewportScaleSettled={setFieldViewportScale}
            />
          </>
        )}
        {!visibleRaster && !visiblePlot && <div className="public-field-loading" role="status">
          <strong>{loadingTitle}</strong>
          {loadingDetail && <span>{loadingDetail}</span>}
          {source === 'armature' && !armature && !armatureBusy && <button type="button" onClick={onRequestArmature}>{armatureError ? 'Retry stator field' : 'Compute stator field'}</button>}
        </div>}
      </div>

      <div className="public-field-playback">
        <button
          className="public-field-transport-play"
          type="button"
          aria-label={playing ? 'Pause clockwise field playback' : 'Play field clockwise'}
          title={colorRangeMode === 'sweep'
            ? 'Switch the flux-density range to View to animate.'
            : 'Clockwise — follows the public solve angle convention'}
          disabled={angleFrames.length < 2 || colorRangeMode === 'sweep'}
          onClick={togglePlayback}
        >
          {playing ? 'Ⅱ' : '▶'}
        </button>
        <label className="public-field-position-control">
          <span><strong>Position</strong><em>{boundedIndex + 1} / {Math.max(1, angleFrames.length)}</em></span>
          <input
            ref={playbackSliderRef}
            type="range"
            min={0}
            max={360}
            step="any"
            defaultValue={0}
            disabled={angleFrames.length < 2}
            aria-label="Solved rotor position"
            onChange={(event) => {
              const nextPlaybackAngleDeg = Number(event.target.value);
              const nextSolvedAngleDeg = normalizePlaybackElectricalAngle(
                nextPlaybackAngleDeg,
                playbackSpanDeg,
              );
              const nextIndex = nearestPlaybackFrameIndex(
                angleFrames,
                nextSolvedAngleDeg,
                playbackSpanDeg,
              );
              setPlaying(false);
              setPlaybackWaiting(false);
              frameIndexRef.current = nextIndex;
              playbackElectricalAngleRef.current = nextPlaybackAngleDeg;
              setFrameIndex(nextIndex);
            }}
          />
        </label>
        <label
          className="public-field-playback-rpm"
          title="Visual playback speed — not the solve operating point"
        >
          <span className="public-field-transport-label"><strong>Playback speed</strong><em>{Math.round(playbackRpm)} RPM</em></span>
          <input
            type="range"
            min={PUBLIC_FIELD_PLAYBACK_MIN_RPM}
            max={PUBLIC_FIELD_PLAYBACK_MAX_RPM}
            step={1}
            value={playbackRpm}
            aria-label="Playback speed (RPM)"
            onChange={(event) => setPlaybackRpm(Number(event.target.value))}
            style={{
              ['--playback-rpm-progress' as never]: (
                ((playbackRpm - PUBLIC_FIELD_PLAYBACK_MIN_RPM)
                  / (PUBLIC_FIELD_PLAYBACK_MAX_RPM - PUBLIC_FIELD_PLAYBACK_MIN_RPM))
                * 100
              ).toFixed(1),
            }}
          />
        </label>
        <span className="public-field-playback-meta" aria-live="polite">
          <span><small>Mechanical</small><strong>{mechanicalAngleDeg.toFixed(2)}°</strong></span>
          <span><small>Electrical</small><strong>{electricalAngleDeg.toFixed(1)}°</strong></span>
          <em className={playbackWaiting ? 'is-buffering' : ''}>CW · {bufferStatus}</em>
        </span>
        <details className="public-field-physics-info">
          <summary aria-label="About field composition" title="About field composition">i</summary>
          <p>PM-only and Stator-only are separate nonlinear solves; their arithmetic sum is not assumed to equal the Resultant field when steel is saturated.</p>
        </details>
      </div>
    </section>
  );
}
