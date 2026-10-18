import type { MaterialCatalog, MotorConfig } from './model';
import { projectMaterialCatalog } from './customSteel';

/**
 * One flux-density colour scale for every frame, rotor position and design.
 *
 * The eight colours span 0–2.0 T and anything above 2.0 T is magenta. The
 * scale used to run from each frame's minimum to its maximum, so a single
 * sharp-corner element (2.6 T in the example motor, where 99% of the steel is
 * below 1.4 T) set the top and squashed the steel into the lower colours.
 * The server's playback images use the same scale (backend/public_field_playback.py).
 */
export const HEAT_COLORS = ['#142a61', '#1855a7', '#1b8eb7', '#2ab673', '#a7c83a', '#f1c232', '#f58b24', '#dc3d3d'];
export const FLUX_SCALE_MAX_T = 2.0;
export const FLUX_OVER_RANGE_COLOR = '#f43cf5';
/** Index of the over-range colour, after the eight scale colours. */
export const FLUX_OVER_RANGE_INDEX = HEAT_COLORS.length;

export interface FluxColorScale {
  minB: number;
  maxB: number;
  /** Values above this are drawn in the over-range colour; null for a scale without one (older images). */
  overAboveT: number | null;
  /** The fixed 0–2.0 T scale, as opposed to one fitted to a view or an older image's own range. */
  fixed: boolean;
}

export const FIXED_FLUX_SCALE: FluxColorScale = {
  minB: 0,
  maxB: FLUX_SCALE_MAX_T,
  overAboveT: FLUX_SCALE_MAX_T,
  fixed: true,
};

/** A scale fitted to the visible values, never past 2.0 T, so one hot element cannot stretch it. */
export function fittedFluxScale(minB: number, maxB: number): FluxColorScale {
  const top = Math.min(maxB, FLUX_SCALE_MAX_T);
  const bottom = Math.min(Math.max(0, minB), top);
  return {
    minB: bottom,
    maxB: Math.max(top, bottom + Number.EPSILON),
    overAboveT: FLUX_SCALE_MAX_T,
    fixed: false,
  };
}

/** The colour index of one value: 0–7 on the scale, FLUX_OVER_RANGE_INDEX above it. */
export function fluxColorIndex(value: number, scale: FluxColorScale): number {
  if (scale.overAboveT !== null && value > scale.overAboveT) return FLUX_OVER_RANGE_INDEX;
  const span = Math.max(scale.maxB - scale.minB, Number.EPSILON);
  return Math.min(
    HEAT_COLORS.length - 1,
    Math.max(0, Math.floor(((value - scale.minB) / span) * HEAT_COLORS.length)),
  );
}

export function fluxColor(index: number): string {
  return index === FLUX_OVER_RANGE_INDEX ? FLUX_OVER_RANGE_COLOR : HEAT_COLORS[index];
}

export interface SaturationTick {
  bT: number;
  label: 'knee' | 'saturation';
  relativePermeability: number;
  steelName: string;
}

const MU_0 = 4e-7 * Math.PI;
// Where the steel's relative permeability falls to these values: about where its
// curve bends (the knee) and where it is heavily saturated. For M350-50A they
// fall at 1.47 T and 1.78 T.
const TICK_PERMEABILITIES: ReadonlyArray<[SaturationTick['label'], number, number]> = [
  ['knee', 1000, 1.5],
  ['saturation', 100, 1.8],
];

function fluxAtRelativePermeability(points: ReadonlyArray<readonly [number, number]>, target: number): number | null {
  let previous: { b: number; mur: number } | null = null;
  for (const [h, b] of points) {
    if (!(h > 0) || !Number.isFinite(b)) continue;
    const mur = b / (MU_0 * h);
    if (previous && previous.mur >= target && mur < target) {
      const fraction = (previous.mur - target) / (previous.mur - mur);
      return previous.b + fraction * (b - previous.b);
    }
    previous = { b, mur };
  }
  return null;
}

/**
 * The knee and saturation ticks for the stator steel, read from its B–H curve
 * (points are [H in A/m, B in T]). A curve that never falls that far gives the
 * usual silicon-steel values, 1.5 T and 1.8 T.
 */
export function steelSaturationTicks(
  points: ReadonlyArray<readonly [number, number]> | null | undefined,
  steelName: string,
): SaturationTick[] {
  return TICK_PERMEABILITIES.map(([label, relativePermeability, fallbackT]) => ({
    bT: (points && fluxAtRelativePermeability(points, relativePermeability)) ?? fallbackT,
    label,
    relativePermeability,
    steelName,
  }));
}

/** The ticks for a design's stator steel, bundled or custom. */
export function statorSteelSaturationTicks(config: MotorConfig, catalog: MaterialCatalog | null | undefined): SaturationTick[] {
  const steelId = config.materials.stator_steel;
  const model = catalog ? projectMaterialCatalog(catalog, config).models?.[steelId] : undefined;
  const name = config.materials.custom_steels?.[steelId]?.name ?? steelId;
  return steelSaturationTicks(model?.curve?.points ?? null, name);
}
