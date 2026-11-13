import type { GeometryPreview, PreviewRegion } from './model';
import { pointInContours, previewContours, type Contour } from './previewContours';
import { previewSlotAngles } from './windingRing';

type Point = [number, number];
export interface WindingTurnDots {
  points: Point[];
  radius: number;
  marker: { point: Point; radius: number };
}

function edgeClearance(point: Point, contours: Contour[]): number {
  if (!pointInContours(point, contours)) return 0;
  let distance = Infinity;
  for (const loop of contours) for (let i = 0; i < loop.length; i += 1) {
    const a = loop[i]; const b = loop[(i + 1) % loop.length];
    const dx = b[0] - a[0]; const dy = b[1] - a[1];
    const length2 = dx * dx + dy * dy;
    const t = length2 ? Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2)) : 0;
    distance = Math.min(distance, Math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy));
  }
  return distance;
}

/** Widest inside interval at a radial station, including concave shoes and holes. */
function sectionAt(v: number, contours: Contour[]): [number, number] | null {
  const crossings: number[] = [];
  for (const loop of contours) for (let i = 0; i < loop.length; i += 1) {
    const [u0, v0] = loop[i]; const [u1, v1] = loop[(i + 1) % loop.length];
    if ((v0 > v) !== (v1 > v)) crossings.push(u0 + (u1 - u0) * (v - v0) / (v1 - v0));
  }
  crossings.sort((a, b) => a - b);
  let widest: [number, number] | null = null;
  for (let i = 0; i + 1 < crossings.length; i += 2) {
    if (!widest || crossings[i + 1] - crossings[i] > widest[1] - widest[0]) widest = [crossings[i], crossings[i + 1]];
  }
  return widest;
}

/**
 * One schematic dot per turn in one coil side, not per strand in hand. Sizes
 * adapt to the polygon, not wire gauge. Work in a shared slot frame so paired
 * sides mirror each other and their direction markers sit at the same depth.
 */
export function windingTurnDots(region: PreviewRegion, turns: number, angle: number, outer = false): WindingTurnDots | null {
  if (!Number.isInteger(turns) || turns < 1 || turns > 500) return null;
  const c = Math.cos(angle); const s = Math.sin(angle);
  const local = ([x, y]: Point): Point => [-x * s + y * c, x * c + y * s];
  const world = ([u, v]: Point): Point => [v * c - u * s, v * s + u * c];
  const contours = previewContours(region).map((loop) => loop.map(local));
  const points = contours.flat();
  if (points.length < 3) return null;
  const lo = Math.min(...points.map((p) => p[1])); const hi = Math.max(...points.map((p) => p[1]));
  const depth = hi - lo;
  if (depth < 1e-8) return null;
  // Reserve the airgap end for the direction glyph, clear of every turn dot.
  const markerV = outer ? hi - depth * 0.22 : lo + depth * 0.22;
  const markerSpan = sectionAt(markerV, contours);
  if (!markerSpan) return null;
  const markerPoint: Point = [(markerSpan[0] + markerSpan[1]) / 2, markerV];
  const markerRadius = Math.min(depth * 0.095, edgeClearance(markerPoint, contours) * 0.72);
  const start = outer ? lo + depth * 0.055 : lo + depth * 0.38;
  const end = outer ? hi - depth * 0.38 : hi - depth * 0.055;
  const midSpan = sectionAt((start + end) / 2, contours);
  if (!midSpan || markerRadius <= 0) return null;
  const idealColumns = Math.sqrt(turns * (midSpan[1] - midSpan[0]) / (end - start));
  const columns = new Set([1, turns]);
  for (const factor of [0.5, 0.7, 0.85, 1, 1.2, 1.5, 2]) {
    const n = Math.round(idealColumns * factor);
    for (const offset of [-1, 0, 1]) columns.add(Math.max(1, Math.min(turns, n + offset)));
  }
  let best: Point[] = []; let radius = 0;
  for (const count of columns) {
    const rows = Math.ceil(turns / count);
    const rowPitch = (end - start) / rows;
    let candidateRadius = rowPitch * 0.36;
    const candidate: Point[] = [];
    for (let row = 0; row < rows; row += 1) {
      const v = start + (row + 0.5) * rowPitch;
      const span = sectionAt(v, contours);
      if (!span) { candidateRadius = 0; break; }
      const rowCount = Math.floor(turns / rows) + (row < turns % rows ? 1 : 0);
      const pitch = (span[1] - span[0]) / (rowCount + 0.5);
      candidateRadius = Math.min(candidateRadius, pitch * 0.36);
      for (let col = 0; col < rowCount; col += 1) {
        const point: Point = [(span[0] + span[1]) / 2 + (col - (rowCount - 1) / 2) * pitch, v];
        candidateRadius = Math.min(candidateRadius, edgeClearance(point, contours) * 0.75,
          Math.hypot(point[0] - markerPoint[0], point[1] - markerPoint[1]) - markerRadius * 1.35);
        candidate.push(point);
      }
    }
    if (candidate.length === turns && candidateRadius > radius) { best = candidate; radius = candidateRadius; }
  }
  return radius > 0 ? { points: best.map(world), radius, marker: { point: world(markerPoint), radius: markerRadius } } : null;
}

export function buildWindingTurnDots(geometry: GeometryPreview | null, turns: number): ReadonlyMap<PreviewRegion, WindingTurnDots> {
  const result = new Map<PreviewRegion, WindingTurnDots>();
  if (!geometry) return result;
  const angles = previewSlotAngles(geometry.regions, Number(geometry.metadata.slot_count || 0));
  for (const region of geometry.regions) {
    const match = /^slot_(\d+).*\([abc][+\-−]\)/i.exec(region.region_type);
    if (!match) continue;
    const angle = angles[Number(match[1]) - 1];
    if (!Number.isFinite(angle)) continue;
    const layout = windingTurnDots(region, turns, angle, geometry.metadata.rotor_layout === 'outer');
    if (layout) result.set(region, layout);
  }
  return result;
}
