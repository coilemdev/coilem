/**
 * Small arrows along B for the solved-field view, in place of flux lines.
 *
 * The arrows sit on rings about the motor axis, one spacing apart, with about
 * one spacing between neighbours along each ring, so every pole reads alike.
 * Each arrow points along the B of the element under it (a first-order
 * triangle's B is constant) and fades where |B| is weak for that field: the
 * stator's field alone is a few tenths of a tesla, the resultant over one, and
 * both should read. The flux-density colours give |B| itself. The server draws the
 * same arrows into the playback images (backend/public_field_playback.py), so
 * a paused frame matches the moving one: the constants below are mirrored
 * there and a test holds them equal.
 */

import { buildTriangleGrid, triangleGridCell, type GridRect, type TriangleGrid } from './triangleGrid';

export type FieldArrowDensity = 'low' | 'medium' | 'high';

/** Ring spacing as a share of the view's larger side (the motor plus 2.5% padding per side). */
export const FIELD_ARROW_SPACING_FRACTION: Readonly<Record<FieldArrowDensity, number>> = {
  low: 1 / 24,
  medium: 1 / 34,
  high: 1 / 48,
};
/** Arrow length as a share of the spacing. */
export const FIELD_ARROW_LENGTH_FRACTION = 0.64;
/**
 * Rings sit at (k + offset) spacings from the axis. The PM field's sit halfway
 * between the others, so in the Stator + PM view the two sets interleave.
 */
export const FIELD_ARROW_RING_OFFSET = { primary: 0.5, pm: 1.0 } as const;
/** A field's strong |B|: the element at this share of them, by |B| (its 95th percentile). */
export const FIELD_ARROW_REFERENCE_PERCENTILE = 0.95;
/** No arrow below this share of the field's strong |B|, nor below FIELD_ARROW_MIN_T. */
export const FIELD_ARROW_HIDE_BELOW_SHARE = 0.015;
/** No arrow below this |B| (T) in any field: a field with no current or magnets shows none. */
export const FIELD_ARROW_MIN_T = 1e-4;
/** [upper share of the strong |B|, opacity]: weak-field arrows fade so the strong paths stand out. */
export const FIELD_ARROW_OPACITY_STEPS: ReadonlyArray<readonly [number, number]> = [
  [0.07, 0.35],
  [0.2, 0.65],
  [Number.POSITIVE_INFINITY, 1],
];

export type FieldArrowTone = 'field' | 'pm' | 'stator';
/** Light arrows with a dark rim read over every flux-density colour and the dark base. */
export const FIELD_ARROW_COLORS: Readonly<Record<FieldArrowTone, string>> = {
  field: '#f8fafc',
  pm: '#5ed3f3',
  stator: '#ffd166',
};
export const FIELD_ARROW_HALO = 'rgba(3,7,15,.82)';

/** A solved mesh indexed for finding the element under a point. */
export interface FieldArrowMesh {
  xs: Float64Array;
  ys: Float64Array;
  /** Node indices, three per usable element. */
  corners: Int32Array;
  bx: Float64Array;
  by: Float64Array;
  /** The usable elements by bounding box (triangleGrid.ts). */
  grid: TriangleGrid;
  /** The farthest node from the axis, mm. */
  maxRadius: number;
  /** The field's strong |B| (T), which the fading is a share of. */
  referenceT: number;
}

export interface FieldArrowSample {
  x: number;
  y: number;
  /** Unit direction of B. */
  ux: number;
  uy: number;
  /** |B|, T. */
  magnitude: number;
  /** 0.35, 0.65 or 1 by how strong |B| is for this field. */
  opacity: number;
}

/** A model-space rectangle, mm (y up). */
export type FieldArrowRect = GridRect;

/** Index a solved plot's elements; null when it has no usable element with B. */
export function buildFieldArrowMesh(
  nodes: readonly (readonly number[])[],
  triangles: readonly (readonly number[])[],
  elementBx: readonly number[] | null | undefined,
  elementBy: readonly number[] | null | undefined,
): FieldArrowMesh | null {
  if (!elementBx || !elementBy || nodes.length === 0) return null;
  const xs = new Float64Array(nodes.length);
  const ys = new Float64Array(nodes.length);
  let maxRadius = 0;
  nodes.forEach((node, index) => {
    const x = Number(node?.[0]);
    const y = Number(node?.[1]);
    xs[index] = x;
    ys[index] = y;
    if (Number.isFinite(x) && Number.isFinite(y)) maxRadius = Math.max(maxRadius, Math.hypot(x, y));
  });
  const corners: number[] = [];
  const bxValues: number[] = [];
  const byValues: number[] = [];
  const boxes: number[] = [];
  triangles.forEach((triangle, index) => {
    const bx = elementBx[index];
    const by = elementBy[index];
    if (!triangle || triangle.length !== 3 || !Number.isFinite(bx) || !Number.isFinite(by)) return;
    const [a, b, c] = triangle;
    if (![a, b, c].every((node) => Number.isInteger(node) && node >= 0 && node < nodes.length)) return;
    if (![a, b, c].every((node) => Number.isFinite(xs[node]) && Number.isFinite(ys[node]))) return;
    corners.push(a, b, c);
    bxValues.push(bx);
    byValues.push(by);
    boxes.push(
      Math.min(xs[a], xs[b], xs[c]),
      Math.min(ys[a], ys[b], ys[c]),
      Math.max(xs[a], xs[b], xs[c]),
      Math.max(ys[a], ys[b], ys[c]),
    );
  });
  const count = bxValues.length;
  const grid = buildTriangleGrid(Float64Array.from(boxes), count);
  if (!grid) return null;
  const magnitudes = Float64Array.from(bxValues, (bx, index) => Math.hypot(bx, byValues[index])).sort();
  return {
    xs,
    ys,
    corners: Int32Array.from(corners),
    bx: Float64Array.from(bxValues),
    by: Float64Array.from(byValues),
    grid,
    maxRadius,
    referenceT: magnitudes[Math.floor(FIELD_ARROW_REFERENCE_PERCENTILE * (count - 1))],
  };
}

/** The usable element under a point, or -1 outside the mesh. */
export function locateFieldArrowElement(mesh: FieldArrowMesh, x: number, y: number): number {
  const { grid, xs, ys, corners } = mesh;
  const cell = triangleGridCell(grid, x, y);
  if (cell < 0) return -1;
  for (let item = grid.cellStart[cell]; item < grid.cellStart[cell + 1]; item += 1) {
    const element = grid.cellItems[item];
    const a = corners[element * 3];
    const b = corners[element * 3 + 1];
    const c = corners[element * 3 + 2];
    const denominator = (ys[b] - ys[c]) * (xs[a] - xs[c]) + (xs[c] - xs[b]) * (ys[a] - ys[c]);
    if (Math.abs(denominator) <= 1e-18) continue;
    const first = ((ys[b] - ys[c]) * (x - xs[c]) + (xs[c] - xs[b]) * (y - ys[c])) / denominator;
    const second = ((ys[c] - ys[a]) * (x - xs[c]) + (xs[a] - xs[c]) * (y - ys[c])) / denominator;
    const tolerance = -1e-9;
    if (first >= tolerance && second >= tolerance && 1 - first - second >= tolerance) return element;
  }
  return -1;
}

/** The view's zoom rounded down to a half-octave, so arrows stay put while zooming within one. */
export function fieldArrowZoomStep(zoom: number): number {
  if (!Number.isFinite(zoom) || zoom <= 1) return 1;
  return 2 ** (Math.floor(2 * Math.log2(zoom) + 1e-9) / 2);
}

/** Ring spacing in model mm for a view of this size (mm), at this density and zoom. */
export function fieldArrowSpacingMm(viewSizeMm: number, density: FieldArrowDensity, zoom = 1): number {
  return (viewSizeMm * FIELD_ARROW_SPACING_FRACTION[density]) / fieldArrowZoomStep(zoom);
}

/** Opacity for an arrow of this |B| in a field whose strong |B| is `referenceT`, or 0 to leave it out. */
export function fieldArrowOpacity(magnitude: number, referenceT: number): number {
  if (!(magnitude >= Math.max(FIELD_ARROW_MIN_T, FIELD_ARROW_HIDE_BELOW_SHARE * referenceT))) return 0;
  const share = magnitude / referenceT;
  return FIELD_ARROW_OPACITY_STEPS.find(([upper]) => share < upper)?.[1] ?? 1;
}

function angularWindow(rect: FieldArrowRect): [number, number] | null {
  if (rect.minX <= 0 && rect.maxX >= 0 && rect.minY <= 0 && rect.maxY >= 0) return null;
  const centre = Math.atan2((rect.minY + rect.maxY) / 2, (rect.minX + rect.maxX) / 2);
  let low = 0;
  let high = 0;
  for (const [x, y] of [[rect.minX, rect.minY], [rect.maxX, rect.minY], [rect.minX, rect.maxY], [rect.maxX, rect.maxY]]) {
    let delta = Math.atan2(y, x) - centre;
    delta -= 2 * Math.PI * Math.round(delta / (2 * Math.PI));
    low = Math.min(low, delta);
    high = Math.max(high, delta);
  }
  return [centre + low, centre + high];
}

/**
 * Arrows on rings at (k + ringOffset) * spacing from the axis, inside the mesh
 * and, when given, the rectangle. Each ring holds round(2πr / spacing) arrows,
 * every other ring turned half a step so neighbouring rings do not line up.
 */
export function sampleFieldArrows(
  mesh: FieldArrowMesh,
  spacing: number,
  ringOffset: number,
  rect: FieldArrowRect | null = null,
): FieldArrowSample[] {
  if (!(spacing > 0)) return [];
  let innerRadius = 0;
  let outerRadius = mesh.maxRadius;
  let window: [number, number] | null = null;
  if (rect) {
    const nearestX = Math.min(Math.max(0, rect.minX), rect.maxX);
    const nearestY = Math.min(Math.max(0, rect.minY), rect.maxY);
    innerRadius = Math.hypot(nearestX, nearestY);
    outerRadius = Math.min(outerRadius, Math.max(
      Math.hypot(rect.minX, rect.minY),
      Math.hypot(rect.maxX, rect.minY),
      Math.hypot(rect.minX, rect.maxY),
      Math.hypot(rect.maxX, rect.maxY),
    ));
    window = angularWindow(rect);
  }
  const arrows: FieldArrowSample[] = [];
  const firstRing = Math.max(0, Math.ceil(innerRadius / spacing - ringOffset));
  const lastRing = Math.floor(outerRadius / spacing - ringOffset);
  for (let ring = firstRing; ring <= lastRing; ring += 1) {
    const radius = (ring + ringOffset) * spacing;
    if (radius <= 0) continue;
    const count = Math.max(1, Math.round((2 * Math.PI * radius) / spacing));
    const step = (2 * Math.PI) / count;
    const phase = (ring % 2) * step / 2;
    let first = 0;
    let last = count - 1;
    if (window) {
      first = Math.ceil((window[0] - phase) / step);
      last = Math.min(first + count - 1, Math.floor((window[1] - phase) / step));
    }
    for (let index = first; index <= last; index += 1) {
      const angle = phase + index * step;
      const x = radius * Math.cos(angle);
      const y = radius * Math.sin(angle);
      if (rect && (x < rect.minX || x > rect.maxX || y < rect.minY || y > rect.maxY)) continue;
      const element = locateFieldArrowElement(mesh, x, y);
      if (element < 0) continue;
      const bx = mesh.bx[element];
      const by = mesh.by[element];
      const magnitude = Math.hypot(bx, by);
      const opacity = fieldArrowOpacity(magnitude, mesh.referenceT);
      if (opacity <= 0) continue;
      arrows.push({ x, y, ux: bx / magnitude, uy: by / magnitude, magnitude, opacity });
    }
  }
  return arrows;
}

/**
 * The outline of one arrow, centred on its sample point, in the plot's drawing
 * space (x right, y down: model y negated). `shaftHalfWidth` widens the shaft
 * so it stays at least a pixel across when the arrows are small.
 */
export function fieldArrowOutline(
  arrow: Pick<FieldArrowSample, 'x' | 'y' | 'ux' | 'uy'>,
  length: number,
  shaftHalfWidth = length * 0.06,
): Array<[number, number]> {
  const ux = arrow.ux;
  const uy = -arrow.uy;
  const nx = -uy;
  const ny = ux;
  const cx = arrow.x;
  const cy = -arrow.y;
  const tail = -length / 2;
  const tip = length / 2;
  const headBase = tip - length * 0.4;
  const headHalfWidth = Math.max(length * 0.22, shaftHalfWidth * 2.2);
  const point = (along: number, across: number): [number, number] => [
    cx + ux * along + nx * across,
    cy + uy * along + ny * across,
  ];
  return [
    point(tail, -shaftHalfWidth),
    point(headBase, -shaftHalfWidth),
    point(headBase, -headHalfWidth),
    point(tip, 0),
    point(headBase, headHalfWidth),
    point(headBase, shaftHalfWidth),
    point(tail, shaftHalfWidth),
  ];
}

/**
 * The outline moved outward by `distance` (each corner along its mitre), for
 * the dark rim drawn under an arrow. Filling this and then the arrow gives the
 * same rim here and in the server's images, where a stroke would not.
 */
export function offsetFieldArrowOutline(outline: ReadonlyArray<readonly [number, number]>, distance: number): Array<[number, number]> {
  const count = outline.length;
  let twiceArea = 0;
  outline.forEach(([x, y], index) => {
    const [nextX, nextY] = outline[(index + 1) % count];
    twiceArea += x * nextY - nextX * y;
  });
  const sign = twiceArea >= 0 ? 1 : -1;
  const normal = (from: readonly [number, number], to: readonly [number, number]): [number, number] => {
    const dx = to[0] - from[0];
    const dy = to[1] - from[1];
    const length = Math.hypot(dx, dy) || 1;
    return [(sign * dy) / length, (-sign * dx) / length];
  };
  return outline.map((point, index) => {
    const [ax, ay] = normal(outline[(index - 1 + count) % count], point);
    const [bx, by] = normal(point, outline[(index + 1) % count]);
    // A mitre at most three times the distance, for the sharp tip.
    const factor = distance / Math.max(1 + ax * bx + ay * by, 2 / 9);
    return [point[0] + (ax + bx) * factor, point[1] + (ay + by) * factor];
  });
}

type ArrowContext = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

/** The model-space rectangle a context's canvas shows through its current transform (y up). */
export function visibleFieldArrowRect(context: ArrowContext): FieldArrowRect | null {
  const transform = context.getTransform();
  if (!transform.is2D || Math.abs(transform.a * transform.d - transform.b * transform.c) < 1e-18) return null;
  const inverse = transform.inverse();
  const { width, height } = context.canvas;
  const corners = [[0, 0], [width, 0], [0, height], [width, height]].map(([x, y]) => {
    const point = inverse.transformPoint({ x, y });
    return [point.x, -point.y];
  });
  return {
    minX: Math.min(...corners.map(([x]) => x)),
    maxX: Math.max(...corners.map(([x]) => x)),
    minY: Math.min(...corners.map(([, y]) => y)),
    maxY: Math.max(...corners.map(([, y]) => y)),
  };
}

/** Shaft half-width and rim width for arrows of this length, at least a pixel across at any size. */
export function fieldArrowWidths(length: number, pixel: number): { shaftHalfWidth: number; rim: number } {
  return {
    shaftHalfWidth: Math.max(length * 0.06, pixel * 0.55),
    rim: Math.max(length * 0.07, pixel * 0.8),
  };
}

/**
 * Draw arrows through the context's current transform (model mm to pixels,
 * y flipped as in the plot): a dark rim, then the light body, faded by |B|.
 */
export function drawFieldArrows(
  context: ArrowContext,
  arrows: readonly FieldArrowSample[],
  length: number,
  color: string,
): void {
  if (arrows.length === 0 || !(length > 0)) return;
  const transform = context.getTransform();
  const pixel = 1 / Math.max(Math.hypot(transform.a, transform.b), 1e-12);
  const { shaftHalfWidth, rim } = fieldArrowWidths(length, pixel);
  const groups = new Map<number, FieldArrowSample[]>();
  arrows.forEach((arrow) => {
    const group = groups.get(arrow.opacity);
    if (group) group.push(arrow);
    else groups.set(arrow.opacity, [arrow]);
  });
  const trace = (outline: ReadonlyArray<readonly [number, number]>) => {
    context.moveTo(outline[0][0], outline[0][1]);
    for (let index = 1; index < outline.length; index += 1) context.lineTo(outline[index][0], outline[index][1]);
    context.lineTo(outline[0][0], outline[0][1]);
  };
  context.save();
  context.shadowBlur = 0;
  context.shadowColor = 'transparent';
  [...groups.entries()].sort(([first], [second]) => first - second).forEach(([opacity, group]) => {
    const outlines = group.map((arrow) => fieldArrowOutline(arrow, length, shaftHalfWidth));
    context.globalAlpha = opacity;
    context.beginPath();
    outlines.forEach((outline) => trace(offsetFieldArrowOutline(outline, rim)));
    context.fillStyle = FIELD_ARROW_HALO;
    context.fill();
    context.beginPath();
    outlines.forEach(trace);
    context.fillStyle = color;
    context.fill();
  });
  context.restore();
}
