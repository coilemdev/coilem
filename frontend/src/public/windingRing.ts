/**
 * Geometry for the Layout view's winding ring: the slots around the bore and each
 * coil's end turn, in SVG units centred on 0,0.
 *
 * Slot positions come from the preview geometry, including imported references
 * whose numbering runs clockwise. Y is flipped to match the cross-section.
 */

/** Radii of the bore, the slot band and the end turns. */
export const WINDING_RING = {
  numbers: 262,
  inner: 290,
  outer: 380,
  endTurn: 386,
} as const;

/** Share of a slot pitch the drawn slot covers; the rest is tooth. */
const SLOT_FILL = 0.62;
/** End-turn bulge: a hop between neighbours, up to a large arc across half the ring. */
const MIN_BULGE = 26;
const MAX_BULGE = 150;

export type SlotLayerSplit = 'radial' | 'tangential' | null;

export function slotAngle(slotIndex: number, slotCount: number, angles?: readonly number[]): number {
  if (angles && Number.isFinite(angles[slotIndex])) return angles[slotIndex];
  return (slotIndex * 2 * Math.PI) / Math.max(1, slotCount);
}

/** Area centroids of the actual slot polygons, combining both layers by area. */
export function previewSlotAngles(
  regions: ReadonlyArray<{ region_type: string; points: Array<[number, number]> }>,
  slotCount: number,
): number[] {
  const slots = Array.from({ length: slotCount }, () => ({ x: 0, y: 0, area: 0 }));
  for (const region of regions) {
    const match = /^slot_(\d+)(?:_|$)/i.exec(region.region_type);
    const index = match ? Number(match[1]) - 1 : -1;
    if (index < 0 || index >= slotCount || region.points.length < 3) continue;
    let area2 = 0; let x = 0; let y = 0;
    region.points.forEach(([x0, y0], i) => {
      const [x1, y1] = region.points[(i + 1) % region.points.length];
      const cross = x0 * y1 - x1 * y0;
      area2 += cross; x += (x0 + x1) * cross; y += (y0 + y1) * cross;
    });
    if (Math.abs(area2) < 1e-12) continue;
    const weight = Math.abs(area2);
    slots[index].x += weight * x / (3 * area2);
    slots[index].y += weight * y / (3 * area2);
    slots[index].area += weight;
  }
  return slots.map((slot, index) => slot.area > 0 ? Math.atan2(slot.y, slot.x) : slotAngle(index, slotCount));
}

export function polar(radius: number, angle: number): [number, number] {
  return [radius * Math.cos(angle), -radius * Math.sin(angle)];
}

const point = ([x, y]: [number, number]) => `${x.toFixed(2)} ${y.toFixed(2)}`;

/** An annular sector from angle a0 to a1 (a1 > a0, counter-clockwise on screen). */
function sector(inner: number, outer: number, a0: number, a1: number): string {
  return [
    `M ${point(polar(outer, a0))}`,
    `A ${outer} ${outer} 0 0 0 ${point(polar(outer, a1))}`,
    `L ${point(polar(inner, a1))}`,
    `A ${inner} ${inner} 0 0 1 ${point(polar(inner, a0))}`,
    'Z',
  ].join(' ');
}

/**
 * The part of a slot one coil side fills. A distributed double layer stacks
 * radially with layer 1 at the bore; tooth coils sit side by side with layer 1
 * next to the tooth before the slot (backend geometry_ir.slot_layer_split).
 */
export function slotSidePath(
  slotIndex: number,
  slotCount: number,
  layer: number,
  layers: number,
  split: SlotLayerSplit,
  angles?: readonly number[],
): string {
  const centre = slotAngle(slotIndex, slotCount, angles);
  const half = (Math.PI / Math.max(1, slotCount)) * SLOT_FILL;
  const { inner, outer } = WINDING_RING;
  const count = Math.max(1, layers);
  const index = Math.min(Math.max(1, layer), count) - 1;
  if (split === 'radial' && count > 1) {
    const depth = (outer - inner) / count;
    return sector(inner + index * depth, inner + (index + 1) * depth, centre - half, centre + half);
  }
  if (split === 'tangential' && count > 1) {
    const width = (2 * half) / count;
    return sector(inner, outer, centre - half + index * width, centre - half + (index + 1) * width);
  }
  return sector(inner, outer, centre - half, centre + half);
}

/** Where a coil side's direction glyph goes: the middle of its part of the slot. */
export function slotSideCentre(
  slotIndex: number,
  slotCount: number,
  layer: number,
  layers: number,
  split: SlotLayerSplit,
  angles?: readonly number[],
): [number, number] {
  const centre = slotAngle(slotIndex, slotCount, angles);
  const half = (Math.PI / Math.max(1, slotCount)) * SLOT_FILL;
  const { inner, outer } = WINDING_RING;
  const count = Math.max(1, layers);
  const index = Math.min(Math.max(1, layer), count) - 1;
  if (split === 'radial' && count > 1) {
    const depth = (outer - inner) / count;
    return polar(inner + (index + 0.5) * depth, centre);
  }
  if (split === 'tangential' && count > 1) {
    const width = (2 * half) / count;
    return polar((inner + outer) / 2, centre - half + (index + 0.5) * width);
  }
  return polar((inner + outer) / 2, centre);
}

/** Share of a coil side's narrower dimension the ⊙ / ⊗ marker spans, and its cap. */
const MARKER_FILL = 0.8;
const MAX_MARKER_RADIUS = 26;

/**
 * Outer radius of the current-direction marker, the same in every slot: as big as
 * fits the narrowest coil side (the innermost layer of a radial split), so the
 * direction still reads when the ring is zoomed out to fit.
 */
export function slotMarkerRadius(slotCount: number, layers: number, split: SlotLayerSplit): number {
  const count = Math.max(1, layers);
  const { inner, outer } = WINDING_RING;
  let angularWidth = 2 * (Math.PI / Math.max(1, slotCount)) * SLOT_FILL;
  let depth = outer - inner;
  if (split === 'radial' && count > 1) depth /= count;
  if (split === 'tangential' && count > 1) angularWidth /= count;
  // Half the side's width at its centre: the distance from there to either edge.
  const halfWidth = (inner + depth / 2) * Math.sin(angularWidth / 2);
  return Math.min(MAX_MARKER_RADIUS, MARKER_FILL * Math.min(halfWidth, depth / 2));
}

/** Slots between a coil's two sides the short way round the ring. */
export function coilSpanSlots(slotIn: number, slotOut: number, slotCount: number): number {
  const forward = (((slotOut - slotIn) % slotCount) + slotCount) % slotCount;
  return Math.min(forward, slotCount - forward);
}

/**
 * A coil's end turn: a curve outside the stator from one side's slot to the other,
 * the short way round, bulging further the wider the coil spans.
 */
export function endTurnPath(slotIn: number, slotOut: number, slotCount: number, angles?: readonly number[]): string {
  const span = coilSpanSlots(slotIn, slotOut, slotCount);
  const a0 = slotAngle(slotIn, slotCount, angles);
  const target = slotAngle(slotOut, slotCount, angles);
  const a1 = a0 + Math.atan2(Math.sin(target - a0), Math.cos(target - a0));
  const bulge = MIN_BULGE + (MAX_BULGE - MIN_BULGE) * Math.min(1, (2 * span) / Math.max(1, slotCount));
  const radius = WINDING_RING.endTurn;
  // Out from the slot, round at the bulge and back in, sampled so a span of
  // half the ring still goes round rather than through the middle.
  const samples = 32;
  const points = Array.from({ length: samples + 1 }, (_, step) => {
    const t = step / samples;
    return point(polar(radius + bulge * Math.sin(Math.PI * t) ** 0.6, a0 + (a1 - a0) * t));
  });
  return `M ${points[0]} ${points.slice(1).map((value) => `L ${value}`).join(' ')}`;
}

/** Half the side of a square viewBox that holds the ring and its widest end turn. */
export const WINDING_RING_EXTENT = WINDING_RING.endTurn + MAX_BULGE + 12;
