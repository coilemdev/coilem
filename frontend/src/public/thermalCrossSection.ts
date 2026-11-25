import type { PublicFieldLinePlot } from './model';

// Match only regions represented by a thermal node. Pocket air, flux barriers,
// the shaft and unknown regions must never acquire a neighbouring temperature.
export function thermalNodeForRegion(region: string): string | null {
  if (/^stator_yoke(?:_\d+)?$/.test(region)) return 'yoke';
  if (/^stator_tooth(?:_\d+)?$/.test(region)) return 'teeth';
  if (/^slot_winding(?:_\d+)?(?:_layer\d+)?$/.test(region) || region === 'winding') return 'winding';
  if (/^rotor_core(?:_\d+)?$/.test(region)) return 'rotor';
  if (/^magnet(?:_\d+)?$/.test(region)) return 'magnets';
  if (region === 'airgap') return 'airgap';
  return null;
}

export interface ThermalCrossSection {
  parts: Array<{ region: string; node: string | null; fillPath: string; outlinePath: string }>;
  anchors: Record<string, [number, number]>;
  /** Drawing units per millimetre. */
  scale: number;
  /** Radius of the solved section's central hole and of its outside, in drawing units. */
  innerRadius: number;
  outerRadius: number;
}

/** A part the thermal model has but the solved cross-section does not: drawn as a ring, not from geometry. */
export interface SchematicThermalPart { key: string; node: string | null; label: string; inner: number; outer: number }

/**
 * Rings for the thermal parts that lie outside the electromagnetic section, so
 * the picture shows every part the table lists. An outer-rotor motor has its
 * hub, bearings and shaft inside the stator; an inner-rotor motor has a housing
 * around the stator and bearings on the shaft. Their sizes are not part of the
 * design, so the proportions are a drawing convention, never a dimension.
 */
export function schematicThermalParts(section: Pick<ThermalCrossSection, 'scale' | 'innerRadius' | 'outerRadius'>,
  nodes: Record<string, unknown>, housingThicknessMm?: number | null): SchematicThermalPart[] {
  const parts: SchematicThermalPart[] = [];
  const hole = section.innerRadius;
  const hasHole = hole > 6;
  if ('mount' in nodes && hasHole) {
    parts.push({ key: 'mount', node: 'mount', label: 'Stator mount (hub)', inner: hole * 0.5, outer: hole });
    if ('bearings' in nodes) parts.push({ key: 'bearings', node: 'bearings', label: 'Bearings', inner: hole * 0.26, outer: hole * 0.5 });
    parts.push({ key: 'shaft', node: null, label: 'Shaft: inside the rotor-to-bearings path, not a part of its own', inner: 0, outer: hole * 0.26 });
    return parts;
  }
  if ('housing' in nodes) {
    const thickness = Number.isFinite(housingThicknessMm) && (housingThicknessMm as number) > 0 ? (housingThicknessMm as number) * section.scale : 8;
    parts.push({ key: 'housing', node: 'housing', label: 'Housing', inner: section.outerRadius, outer: section.outerRadius + Math.max(4, Math.min(14, thickness)) });
  }
  if ('bearings' in nodes && hasHole) {
    parts.push({ key: 'bearings', node: 'bearings', label: 'Bearings', inner: hole * 0.6, outer: hole });
    parts.push({ key: 'shaft', node: null, label: 'Shaft: inside the rotor-to-bearings path, not a part of its own', inner: 0, outer: hole * 0.6 });
  }
  return parts;
}

/** An SVG path for a ring (or a disc when `inner` is 0), to be filled with the even-odd rule. */
export function ringPath(inner: number, outer: number): string {
  const circle = (r: number) => `M${(-r).toFixed(2)} 0a${r.toFixed(2)} ${r.toFixed(2)} 0 1 0 ${(2 * r).toFixed(2)} 0a${r.toFixed(2)} ${r.toFixed(2)} 0 1 0 ${(-2 * r).toFixed(2)} 0Z`;
  return inner > 0 ? circle(outer) + circle(inner) : circle(outer);
}

/** Preserve the solved mesh, including holes and IPM pockets, in a 400px square. */
export function thermalCrossSection(plot: PublicFieldLinePlot | null | undefined): ThermalCrossSection | null {
  if (!plot?.triangles.length || plot.regions.length !== plot.triangles.length) return null;
  if (!plot.nodes_mm.length || plot.nodes_mm.some((p) => p.length < 2 || !Number.isFinite(p[0]) || !Number.isFinite(p[1]))) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of plot.nodes_mm) { minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y); }
  const span = Math.max(maxX - minX, maxY - minY);
  if (!(span > 0)) return null;
  const scale = 380 / span;
  const points = plot.nodes_mm.map(([x, y]) => [(x - (minX + maxX) / 2) * scale, -(y - (minY + maxY) / 2) * scale]);
  // The section's hole and outside are taken from the parts the estimate knows,
  // so surrounding air or a meshed shaft does not move them.
  let innerRadius = Infinity, outerRadius = 0;
  const xy = (index: number) => points[index].map((v) => Number(v.toFixed(3))).join(' ');
  const buckets = new Map<string, { node: string | null; fills: string[]; edges: Map<string, [number, number]> }>();
  const candidates: Record<string, Array<[number, number]>> = {};
  for (let i = 0; i < plot.triangles.length; i++) {
    const triangle = plot.triangles[i];
    if (triangle.length !== 3 || triangle.some((index) => !Number.isInteger(index) || !points[index])) return null;
    const region = plot.regions[i];
    const node = thermalNodeForRegion(region);
    const bucket = buckets.get(region) ?? {node, fills: [], edges: new Map<string, [number, number]>()};
    buckets.set(region, bucket);
    bucket.fills.push(`M${xy(triangle[0])}L${xy(triangle[1])}L${xy(triangle[2])}Z`);
    for (let j = 0; j < 3; j++) {
      const a = triangle[j], b = triangle[(j + 1) % 3];
      const key = a < b ? `${a}:${b}` : `${b}:${a}`;
      if (bucket.edges.has(key)) bucket.edges.delete(key); else bucket.edges.set(key, [a, b]);
    }
    if (node) for (const index of triangle) { const r = Math.hypot(points[index][0], points[index][1]); innerRadius = Math.min(innerRadius, r); outerRadius = Math.max(outerRadius, r); }
    if (node) (candidates[node] ??= []).push([
      triangle.reduce((sum, index) => sum + points[index][0], 0) / 3,
      triangle.reduce((sum, index) => sum + points[index][1], 0) / 3,
    ]);
  }
  const anchors: ThermalCrossSection['anchors'] = {};
  // Pick an actual element centroid near each callout, never a fabricated point.
  const angles: Record<string, number> = {yoke: -145, teeth: 180, winding: 145, magnets: -40, rotor: 0, airgap: 45};
  for (const [node, centres] of Object.entries(candidates)) {
    const radius = centres.reduce((sum, [x, y]) => sum + Math.hypot(x, y), 0) / centres.length;
    const angle = angles[node] * Math.PI / 180;
    const target = [radius * Math.cos(angle), radius * Math.sin(angle)];
    anchors[node] = centres.reduce((best, point) => Math.hypot(point[0] - target[0], point[1] - target[1]) < Math.hypot(best[0] - target[0], best[1] - target[1]) ? point : best);
  }
  if (!Number.isFinite(innerRadius)) { innerRadius = 0; outerRadius = 190; }
  return {anchors, scale, innerRadius, outerRadius, parts: [...buckets].map(([region, b]) => ({region, node: b.node, fillPath: b.fills.join(''), outlinePath: [...b.edges.values()].map(([a, z]) => `M${xy(a)}L${xy(z)}`).join('')}))};
}
