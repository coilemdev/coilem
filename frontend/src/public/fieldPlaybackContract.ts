import type {
  PublicFieldPlaybackComposition,
  PublicFieldPlaybackCompositionDefinition,
  PublicFieldPlaybackFrame,
  PublicFieldPlaybackLayerDefinition,
  PublicFieldPlaybackManifest,
  PublicFieldPlaybackTimeline,
  PublicFieldPlaybackVisualV2,
} from './model';

export interface NormalizedFieldPlaybackSequence {
  timeline: PublicFieldPlaybackTimeline;
  layers: PublicFieldPlaybackLayerDefinition[];
  compositions: PublicFieldPlaybackCompositionDefinition[];
  frames: PublicFieldPlaybackFrame[];
}

export function fieldPlaybackSweepMaxT(
  frames: readonly PublicFieldPlaybackFrame[],
  compositionId: string,
): number | null {
  let maximum = Number.NEGATIVE_INFINITY;
  frames.forEach((frame) => {
    const value = frame.compositions[compositionId]?.max_b_t;
    if (Number.isFinite(value)) maximum = Math.max(maximum, value);
  });
  return Number.isFinite(maximum) ? maximum : null;
}

const LEGACY_LAYERS: PublicFieldPlaybackLayerDefinition[] = [
  {
    id: 'geometry',
    label: 'Geometry',
    role: 'geometry',
    media_type: 'image/webp',
    default_visible: true,
  },
  {
    id: 'flux_density',
    label: 'Flux density',
    role: 'scalar',
    media_type: 'image/webp',
    default_visible: true,
    quantity: 'magnetic_flux_density',
    unit: 'T',
  },
  {
    id: 'field_lines',
    label: 'Field lines',
    role: 'contours',
    media_type: 'image/webp',
    default_visible: true,
  },
];

function statistic(
  values: Record<string, string | number | boolean | null> | undefined,
  key: string,
): number {
  const value = values?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function layerIdForRole(
  layers: PublicFieldPlaybackLayerDefinition[],
  role: PublicFieldPlaybackLayerDefinition['role'],
): string | null {
  return layers.find((layer) => layer.role === role)?.id ?? null;
}

function normalizeV2Visual(
  visual: PublicFieldPlaybackVisualV2,
  layers: PublicFieldPlaybackLayerDefinition[],
): PublicFieldPlaybackComposition | null {
  const geometryId = layerIdForRole(layers, 'geometry');
  const scalarId = layerIdForRole(layers, 'scalar');
  const contoursId = layerIdForRole(layers, 'contours');
  const meshId = layers.find((layer) => layer.id === 'mesh')?.id ?? null;
  const base = geometryId ? visual.layers[geometryId] : null;
  const fluxDensity = scalarId ? visual.layers[scalarId] : null;
  const fieldLines = contoursId ? visual.layers[contoursId] : null;
  const mesh = meshId ? visual.layers[meshId] : null;
  const detailBase = geometryId ? visual.detail_layers?.[geometryId] : null;
  const detailFluxDensity = scalarId ? visual.detail_layers?.[scalarId] : null;
  const detailFieldLines = contoursId ? visual.detail_layers?.[contoursId] : null;
  const detailMesh = meshId ? visual.detail_layers?.[meshId] : null;
  if (!base || !fluxDensity || !fieldLines) return null;
  return {
    base,
    flux_density: fluxDensity,
    ...(mesh ? { mesh } : {}),
    field_lines: fieldLines,
    ...(detailBase && detailFluxDensity && detailFieldLines
      ? {
        detail: {
          base: detailBase,
          flux_density: detailFluxDensity,
          ...(detailMesh ? { mesh: detailMesh } : {}),
          field_lines: detailFieldLines,
        },
      }
      : {}),
    view_box: visual.view_box,
    min_b_t: visual.legend?.min ?? 0,
    max_b_t: visual.legend?.max ?? 0,
    triangle_count: statistic(visual.statistics, 'triangle_count'),
    contour_level_count: statistic(visual.statistics, 'contour_level_count'),
    contour_segment_count: statistic(visual.statistics, 'contour_segment_count'),
    vector_cues: visual.vector_cues,
  };
}

export function normalizeFieldPlaybackManifest(
  manifest: PublicFieldPlaybackManifest | null | undefined,
): NormalizedFieldPlaybackSequence | null {
  if (
    !manifest
    || !['layered-raster-v1', 'layered-webp-v1'].includes(manifest.encoding)
    || manifest.frames.length === 0
  ) {
    return null;
  }
  const numericalSnapshots = manifest.numerical_snapshots.length === manifest.frames.length
    ? manifest.numerical_snapshots
    : [];
  if (manifest.schema_version === 'coilem.field_playback.v1') {
    const compositionIds = Array.from(new Set(
      manifest.frames.flatMap((frame) => Object.keys(frame.compositions)),
    ));
    return {
      timeline: {
        kind: 'angle',
        unit: 'deg_electrical',
        loop: true,
        direction: 'increasing',
      },
      layers: LEGACY_LAYERS,
      compositions: compositionIds.map((id) => ({ id, label: id })),
      frames: manifest.frames.map((frame, index) => ({
        ...frame,
        numerical_artifact: numericalSnapshots[index],
      })),
    };
  }
  if (manifest.schema_version !== 'coilem.field_playback.v2') return null;
  return {
    timeline: manifest.timeline,
    layers: manifest.layers,
    compositions: manifest.compositions,
    frames: manifest.frames.map((frame, index) => ({
      index: frame.index,
      angle_deg: frame.coordinate,
      numerical_artifact: numericalSnapshots[index],
      compositions: Object.fromEntries(
        Object.entries(frame.compositions).flatMap(([id, visual]) => {
          const composition = normalizeV2Visual(visual, manifest.layers);
          return composition ? [[id, composition]] : [];
        }),
      ),
    })),
  };
}
