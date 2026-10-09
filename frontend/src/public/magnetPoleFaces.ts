export type MagnetPoint = [number, number];

export interface MagnetPoleFaces {
  /** Long edge nearest the airgap. */
  airgapFace: [MagnetPoint, MagnetPoint];
  /** Opposing long edge toward the shaft. */
  backFace: [MagnetPoint, MagnetPoint];
  /** Center of the complete magnet body. */
  center: MagnetPoint;
  /** Unit normal from the back face toward the airgap-facing face. */
  airgapNormal: MagnetPoint;
  /** Physical distance between the two pole faces. */
  thickness: number;
}

export interface MagnetPolarityHalves {
  /** Half nearest the stator bore / airgap. */
  airgapHalf: MagnetPoint[];
  /** Opposite half against the rotor back iron. */
  backHalf: MagnetPoint[];
}

interface PolygonEdge {
  from: MagnetPoint;
  to: MagnetPoint;
  midpoint: MagnetPoint;
  direction: MagnetPoint;
  length: number;
}

function withoutClosingPoint(points: MagnetPoint[]): MagnetPoint[] {
  if (points.length < 2) return points;
  const first = points[0];
  const last = points[points.length - 1];
  return Math.hypot(first[0] - last[0], first[1] - last[1]) < 1e-7
    ? points.slice(0, -1)
    : points;
}

function polygonCentroid(points: MagnetPoint[]): MagnetPoint {
  let areaTwice = 0;
  let x = 0;
  let y = 0;
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index];
    const next = points[(index + 1) % points.length];
    const cross = current[0] * next[1] - next[0] * current[1];
    areaTwice += cross;
    x += (current[0] + next[0]) * cross;
    y += (current[1] + next[1]) * cross;
  }
  if (Math.abs(areaTwice) < 1e-9) {
    return points.reduce<MagnetPoint>(
      (sum, point) => [sum[0] + point[0] / points.length, sum[1] + point[1] / points.length],
      [0, 0],
    );
  }
  return [x / (3 * areaTwice), y / (3 * areaTwice)];
}

function signedArea(points: MagnetPoint[]): number {
  return points.reduce((areaTwice, current, index) => {
    const next = points[(index + 1) % points.length];
    return areaTwice + current[0] * next[1] - next[0] * current[1];
  }, 0) / 2;
}

function normalizeSignedAngle(angle: number): number {
  let normalized = angle;
  while (normalized <= -Math.PI) normalized += Math.PI * 2;
  while (normalized > Math.PI) normalized -= Math.PI * 2;
  return normalized;
}

function samplePolarArc(
  radius: number,
  startAngle: number,
  endAngle: number,
  segments: number,
): MagnetPoint[] {
  return Array.from({ length: segments + 1 }, (_, index) => {
    const angle = startAngle + ((endAngle - startAngle) * index) / segments;
    return [radius * Math.cos(angle), radius * Math.sin(angle)];
  });
}

/**
 * Split a surface-magnet arc at its radial mid-thickness.
 *
 * A circular boundary is required here: a Cartesian half-plane would trim
 * the tangential ends of wider SPM magnets instead of following the curved
 * airgap- and rotor-facing pole surfaces.
 */
export function computeSpmMagnetPolarityHalves(inputPoints: MagnetPoint[]): MagnetPolarityHalves | null {
  const points = withoutClosingPoint(inputPoints);
  if (points.length < 3) return null;

  const radii = points.map(([x, y]) => Math.hypot(x, y));
  const innerRadius = Math.min(...radii);
  const outerRadius = Math.max(...radii);
  if (!Number.isFinite(innerRadius) || !Number.isFinite(outerRadius) || outerRadius - innerRadius < 1e-6) {
    return null;
  }

  const center = polygonCentroid(points);
  const centerAngle = Math.atan2(center[1], center[0]);
  const relativeAngles = points.map(([x, y]) => (
    normalizeSignedAngle(Math.atan2(y, x) - centerAngle)
  ));
  const startAngle = Math.min(...relativeAngles);
  const endAngle = Math.max(...relativeAngles);
  const span = endAngle - startAngle;
  if (!Number.isFinite(span) || span < 1e-6 || span > Math.PI + 1e-6) return null;

  const splitRadius = (innerRadius + outerRadius) / 2;
  const segments = Math.max(4, Math.ceil((span * 180) / Math.PI));
  const absoluteStart = centerAngle + startAngle;
  const absoluteEnd = centerAngle + endAngle;
  const buildBand = (bandInnerRadius: number, bandOuterRadius: number): MagnetPoint[] => [
    ...samplePolarArc(bandOuterRadius, absoluteStart, absoluteEnd, segments),
    ...samplePolarArc(bandInnerRadius, absoluteEnd, absoluteStart, segments),
  ];

  let airgapHalf = buildBand(splitRadius, outerRadius);
  let backHalf = buildBand(innerRadius, splitRadius);
  if (signedArea(points) < 0) {
    airgapHalf = airgapHalf.reverse();
    backHalf = backHalf.reverse();
  }

  const fullArea = Math.abs(signedArea(points));
  const airgapArea = Math.abs(signedArea(airgapHalf));
  const backArea = Math.abs(signedArea(backHalf));
  if (fullArea < 1e-6 || airgapArea < fullArea * 0.15 || backArea < fullArea * 0.15) {
    return null;
  }
  return { airgapHalf, backHalf };
}

/**
 * Find the two opposing long faces of a rectangular buried magnet.
 *
 * The magnet remains one complete polygon. These segments are presentation
 * cues for its surface polarity; they do not create or alter solver geometry.
 */
export function computeMagnetPoleFaces(inputPoints: MagnetPoint[]): MagnetPoleFaces | null {
  const points = withoutClosingPoint(inputPoints);
  if (points.length < 4) return null;

  const edges: PolygonEdge[] = points.map((from, index) => {
    const to = points[(index + 1) % points.length];
    const dx = to[0] - from[0];
    const dy = to[1] - from[1];
    const length = Math.hypot(dx, dy);
    return {
      from,
      to,
      midpoint: [(from[0] + to[0]) / 2, (from[1] + to[1]) / 2] as MagnetPoint,
      direction: (length > 1e-9 ? [dx / length, dy / length] : [0, 0]) as MagnetPoint,
      length,
    };
  }).sort((left, right) => right.length - left.length);

  const firstFace = edges[0];
  if (!firstFace || firstFace.length < 1e-6) return null;
  const secondFace = edges.find((edge) => (
    edge !== firstFace
    && edge.length >= firstFace.length * 0.72
    && Math.abs(
      edge.direction[0] * firstFace.direction[0]
      + edge.direction[1] * firstFace.direction[1],
    ) > 0.94
  ));
  if (!secondFace) return null;

  const center = polygonCentroid(points);
  let normal: MagnetPoint = [-firstFace.direction[1], firstFace.direction[0]];
  if (normal[0] * center[0] + normal[1] * center[1] < 0) {
    normal = [-normal[0], -normal[1]];
  }

  const firstProjection = firstFace.midpoint[0] * normal[0] + firstFace.midpoint[1] * normal[1];
  const secondProjection = secondFace.midpoint[0] * normal[0] + secondFace.midpoint[1] * normal[1];
  const airgapEdge = firstProjection >= secondProjection ? firstFace : secondFace;
  const backEdge = airgapEdge === firstFace ? secondFace : firstFace;
  const thickness = Math.abs(firstProjection - secondProjection);
  if (!Number.isFinite(thickness) || thickness < 1e-6) return null;

  return {
    airgapFace: [airgapEdge.from, airgapEdge.to],
    backFace: [backEdge.from, backEdge.to],
    center,
    airgapNormal: normal,
    thickness,
  };
}
