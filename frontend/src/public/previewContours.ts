import type { PreviewRegion } from './model';

export type Contour = Array<[number, number]>;

export function previewContours(region: Pick<PreviewRegion, 'points' | 'loops'>): Contour[] {
  return region.loops?.length ? region.loops : [region.points];
}

/** Even/odd containment also excludes bores and magnet pockets from picks. */
export function pointInContours([x, y]: [number, number], contours: Contour[]): boolean {
  let inside = false;
  for (const contour of contours) {
    for (let i = 0, j = contour.length - 1; i < contour.length; j = i++) {
      const [xi, yi] = contour[i];
      const [xj, yj] = contour[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
  }
  return inside;
}

export function isMovingPreviewRegion(regionType: string): boolean {
  return /rotor|magnet|shaft|inter_pole_air|ipm_pocket|pocket_air/i.test(regionType) && !/stator/i.test(regionType);
}
