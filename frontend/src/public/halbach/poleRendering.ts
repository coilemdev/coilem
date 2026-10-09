export type HalbachPolePoint = [number, number];

export const HALBACH_POLE_NORTH_FALLBACK = '#cf4d51';
export const HALBACH_POLE_SOUTH_FALLBACK = '#3978ad';

export function halbachWedgeCentroid(
  innerRadius: number,
  outerRadius: number,
  startDeg: number,
  endDeg: number,
): HalbachPolePoint {
  const centerRad = (startDeg + endDeg) * Math.PI / 360;
  const halfSpanRad = Math.abs(endDeg - startDeg) * Math.PI / 360;
  const radialRatio = (
    outerRadius ** 3 - innerRadius ** 3
  ) / Math.max(Number.EPSILON, outerRadius ** 2 - innerRadius ** 2);
  const centroidRadius = halfSpanRad <= 1e-9
    ? (innerRadius + outerRadius) / 2
    : 2 * Math.sin(halfSpanRad) * radialRatio / (3 * halfSpanRad);
  return [
    Math.cos(centerRad) * centroidRadius,
    Math.sin(centerRad) * centroidRadius,
  ];
}

export function halbachWedgePolygon(
  innerRadius: number,
  outerRadius: number,
  startDeg: number,
  endDeg: number,
): HalbachPolePoint[] {
  const steps = Math.max(2, Math.ceil(Math.abs(endDeg - startDeg) / 4));
  const points: HalbachPolePoint[] = [];
  for (let step = 0; step <= steps; step += 1) {
    const angle = (startDeg + (endDeg - startDeg) * step / steps) * Math.PI / 180;
    points.push([outerRadius * Math.cos(angle), outerRadius * Math.sin(angle)]);
  }
  for (let step = steps; step >= 0; step -= 1) {
    const angle = (startDeg + (endDeg - startDeg) * step / steps) * Math.PI / 180;
    points.push([innerRadius * Math.cos(angle), innerRadius * Math.sin(angle)]);
  }
  return points;
}

export function clipHalbachPoleHalf(
  points: HalbachPolePoint[],
  normal: HalbachPolePoint,
  origin: HalbachPolePoint,
): HalbachPolePoint[] {
  const signedSide = (point: HalbachPolePoint) => (
    normal[0] * (point[0] - origin[0]) + normal[1] * (point[1] - origin[1])
  );
  const clipped: HalbachPolePoint[] = [];
  for (let index = 0; index < points.length; index += 1) {
    const previous = points[(index + points.length - 1) % points.length];
    const current = points[index];
    const previousSide = signedSide(previous);
    const currentSide = signedSide(current);
    if ((previousSide >= 0) !== (currentSide >= 0)) {
      const fraction = previousSide / (previousSide - currentSide);
      clipped.push([
        previous[0] + (current[0] - previous[0]) * fraction,
        previous[1] + (current[1] - previous[1]) * fraction,
      ]);
    }
    if (currentSide >= 0) clipped.push(current);
  }
  return clipped;
}
