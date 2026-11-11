import type { HalbachArrayConfig, LinearHalbachArrayConfig } from './types';

export interface HalbachDisplaySegment {
  index: number;
  startDeg: number;
  endDeg: number;
  centerDeg: number;
  magnetizationDeg: number;
}

export function halbachMagnetizationAngleDeg(
  segmentCenterDeg: number,
  fieldDirectionDeg: number,
): number {
  return 2 * segmentCenterDeg - fieldDirectionDeg;
}

/** Shared exact planar segment contract consumed by both 2D and 3D views. */
export function halbachDisplaySegments(config: HalbachArrayConfig): HalbachDisplaySegment[] {
  // A ring that cannot be drawn has no segments. Both viewers iterate this
  // list, so a bad radius or count simply leaves the magnet ring out instead of
  // reaching a canvas arc or a mesh build with values they cannot take.
  if (!halbachRingIsDrawable(config)) return [];
  const pitch = 360 / config.geometry.segment_count;
  const span = pitch - config.geometry.segment_gap_angle;
  return Array.from({ length: config.geometry.segment_count }, (_, index) => {
    const centerDeg = config.geometry.segment_start_angle + (index + 0.5) * pitch;
    return {
      index,
      startDeg: centerDeg - span / 2,
      endDeg: centerDeg + span / 2,
      centerDeg,
      magnetizationDeg: halbachMagnetizationAngleDeg(
        centerDeg,
        config.array.field_direction,
      ),
    };
  });
}

const MAX_DRAWN_SEGMENTS = 512;
const MAX_DRAWN_LINEAR_MAGNETS = 256;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isPositiveNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** True for a radius, length or scale a canvas or mesh can be drawn with. */
export function isDrawableLength(value: unknown): value is number {
  return isPositiveNumber(value);
}

/** True when the magnet ring can be drawn: real radii, outer beyond inner. */
export function halbachRingIsDrawable(config: HalbachArrayConfig): boolean {
  const geometry = config.geometry;
  return isPositiveNumber(geometry.inner_radius)
    && isPositiveNumber(geometry.outer_radius)
    && geometry.outer_radius > geometry.inner_radius
    && Number.isInteger(geometry.segment_count)
    && geometry.segment_count >= 1
    && geometry.segment_count <= MAX_DRAWN_SEGMENTS
    && isFiniteNumber(geometry.segment_gap_angle)
    && isFiniteNumber(geometry.segment_start_angle);
}

/**
 * Radius the 2D view is fitted to. Only usable radii take part, so one bad
 * field cannot turn the view scale negative, zero or NaN.
 */
export function halbachViewRadius(config: HalbachArrayConfig): number {
  const candidates = [
    config.geometry.outer_radius * 1.25,
    config.sample_region.leakage_probe_radius * 1.08,
    config.geometry.inner_radius * 1.25,
    config.sample_region.radius * 1.25,
  ].filter(isPositiveNumber);
  return candidates.length > 0 ? Math.max(...candidates) : 1;
}

/** Magnets the linear viewers draw; zero when the row cannot be drawn. */
export function linearHalbachDrawableMagnetCount(
  config: LinearHalbachArrayConfig,
): number {
  const geometry = config.geometry;
  if (
    !isPositiveNumber(geometry.block_width)
    || !isPositiveNumber(geometry.magnet_height)
    || !isFiniteNumber(geometry.block_gap)
    || !isPositiveNumber(geometry.period_count)
  ) return 0;
  return Math.min(MAX_DRAWN_LINEAR_MAGNETS, 4 * Math.round(geometry.period_count));
}

function hasSharedConfigShape(value: Record<string, unknown>): boolean {
  if (
    !isRecord(value.geometry)
    || !isRecord(value.array)
    || !isRecord(value.magnet)
    || !isRecord(value.sample_region)
    || !isRecord(value.solve)
    || !isRecord(value.solve.mesh)
    || !isRecord(value.solve.linear)
  ) return false;
  const magnet = value.magnet;
  if (magnet.source === 'catalog') return typeof magnet.grade === 'string';
  return magnet.source === 'custom' && typeof magnet.name === 'string';
}

/**
 * True when a stored or opened cylindrical design has every section the
 * workspace reads. Values are not judged here.
 */
export function hasHalbachConfigShape(value: unknown): value is HalbachArrayConfig {
  return isRecord(value)
    && value.kind === 'halbach_array_config'
    && hasSharedConfigShape(value);
}

/** Linear counterpart of hasHalbachConfigShape. */
export function hasLinearHalbachConfigShape(
  value: unknown,
): value is LinearHalbachArrayConfig {
  return isRecord(value)
    && value.kind === 'linear_halbach_array_config'
    && hasSharedConfigShape(value);
}

/**
 * Gate for a cylindrical autosave. A draft that fails it is dropped and the
 * example design is used, so a stored bad value can never lock the workspace.
 * Softer problems (ROI too large, probe outside the boundary) are kept: they
 * draw fine and Design Health reports them.
 */
export function isRestorableHalbachConfig(value: unknown): value is HalbachArrayConfig {
  if (!hasHalbachConfigShape(value)) return false;
  return halbachRingIsDrawable(value)
    && isPositiveNumber(value.geometry.axial_length)
    && isPositiveNumber(value.sample_region.radius)
    && isPositiveNumber(value.sample_region.leakage_probe_radius)
    && isPositiveNumber(value.solve.mesh.outer_boundary_radius_factor);
}

/** Gate for a linear autosave, with the same intent as the cylindrical one. */
export function isRestorableLinearHalbachConfig(
  value: unknown,
): value is LinearHalbachArrayConfig {
  if (!hasLinearHalbachConfigShape(value)) return false;
  const { geometry, sample_region: sample } = value;
  return isPositiveNumber(geometry.block_width)
    && isPositiveNumber(geometry.magnet_height)
    && isPositiveNumber(geometry.out_of_plane_depth)
    && Number.isInteger(geometry.period_count)
    && geometry.period_count >= 1
    && 4 * geometry.period_count <= MAX_DRAWN_LINEAR_MAGNETS
    && isFiniteNumber(geometry.block_gap)
    && geometry.block_gap >= 0
    && isPositiveNumber(sample.probe_offset)
    && isFiniteNumber(sample.edge_exclusion_periods)
    && isFiniteNumber(sample.samples_per_period)
    && isFiniteNumber(value.array.phase_deg)
    && (value.array.strong_side === 'positive_y' || value.array.strong_side === 'negative_y')
    && isPositiveNumber(value.solve.mesh.outer_padding_factor);
}
