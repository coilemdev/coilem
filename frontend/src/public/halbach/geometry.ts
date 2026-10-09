import type { HalbachArrayConfig } from './types';

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
