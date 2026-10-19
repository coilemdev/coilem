import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The Layout view's ring: slots in the cross-section's orientation, end turns
// outside the stator the short way round, two-layer slots split as the geometry does.
const {
  WINDING_RING,
  WINDING_RING_EXTENT,
  coilSpanSlots,
  endTurnPath,
  polar,
  previewSlotAngles,
  slotAngle,
  slotMarkerRadius,
  slotSideCentre,
} = await importTypeScriptModule(new URL('../src/public/windingRing.ts', import.meta.url));

const close = (actual, expected, label, tolerance = 1e-9) => assert.ok(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} != ${expected}`);
const points = (path) => [...path.matchAll(/(-?\d+\.\d+) (-?\d+\.\d+)/g)].map((match) => [Number(match[1]), Number(match[2])]);
const radius = ([x, y]) => Math.hypot(x, y);
const angleOf = ([x, y]) => Math.atan2(-y, x);

// Slot 1 at three o'clock, numbering counter-clockwise (y up on screen).
const [x0, y0] = polar(100, slotAngle(0, 36));
close(x0, 100, 'slot 1 x'); close(y0, 0, 'slot 1 y');
const [x9, y9] = polar(100, slotAngle(9, 36));
close(x9, 0, 'slot 10 x', 1e-9); close(y9, -100, 'slot 10 is at twelve o\'clock (screen y up)', 1e-9);

// Spans the short way round, across slot 1 as well.
assert.equal(coilSpanSlots(0, 6, 36), 6);
assert.equal(coilSpanSlots(33, 3, 36), 6);
assert.equal(coilSpanSlots(3, 33, 36), 6);

for (const [label, slotIn, slotOut, slotCount] of [
  ['distributed 6p/36s coil', 0, 6, 36],
  ['coil across slot 1', 33, 3, 36],
  ['tooth coil', 4, 5, 12],
  ['half the ring (2-pole full pitch)', 0, 6, 12],
]) {
  const path = points(endTurnPath(slotIn, slotOut, slotCount));
  // Starts and ends at the end-turn radius in its two slots...
  close(radius(path[0]), WINDING_RING.endTurn, `${label}: starts at the end-turn radius`, 0.02);
  close(radius(path.at(-1)), WINDING_RING.endTurn, `${label}: ends at the end-turn radius`, 0.02);
  close(angleOf(path[0]), Math.atan2(Math.sin(slotAngle(slotIn, slotCount)), Math.cos(slotAngle(slotIn, slotCount))), `${label}: leaves its first slot`, 1e-4);
  close(angleOf(path.at(-1)), Math.atan2(Math.sin(slotAngle(slotOut, slotCount)), Math.cos(slotAngle(slotOut, slotCount))), `${label}: reaches its second slot`, 1e-4);
  // ...stays outside the stator, even for half the ring, and inside the drawing.
  assert.ok(path.every((p) => radius(p) >= WINDING_RING.endTurn - 0.02), `${label}: stays outside the stator`);
  assert.ok(path.every((p) => Math.abs(p[0]) <= WINDING_RING_EXTENT && Math.abs(p[1]) <= WINDING_RING_EXTENT), `${label}: fits the viewBox`);
}

// A coil across slot 1 goes the short way, through three o'clock, not round the back.
const across = points(endTurnPath(33, 3, 36));
assert.ok(across.every(([x]) => x > 0), 'coil 34→4 stays on the right of the ring');

// A wider coil bulges further than a tooth coil.
const peak = (path) => Math.max(...points(path).map(radius));
assert.ok(peak(endTurnPath(0, 6, 36)) > peak(endTurnPath(0, 1, 36)), 'a distributed coil bulges further than a tooth coil');

// Two-layer slots: radial puts layer 1 at the bore; tangential puts layer 1 on the
// side of the tooth before the slot (lower angle).
const inner = radius(slotSideCentre(2, 36, 1, 2, 'radial'));
const outer = radius(slotSideCentre(2, 36, 2, 2, 'radial'));
assert.ok(inner < outer, 'radial: layer 1 is nearer the bore');
const before = angleOf(slotSideCentre(2, 12, 1, 2, 'tangential'));
const after = angleOf(slotSideCentre(2, 12, 2, 2, 'tangential'));
assert.ok(before < slotAngle(2, 12) && after > slotAngle(2, 12), 'tangential: layer 1 on the side of the tooth before the slot');

// The ⊙ / ⊗ marker fills most of the narrowest coil side but stays inside every
// side it marks: clear of both radial edges and of the side's inner and outer arcs.
for (const slotCount of [6, 9, 12, 18, 24, 36, 48, 72]) {
  for (const [layers, split] of [[1, null], [2, 'radial'], [2, 'tangential']]) {
    const label = `${slotCount} slots, ${layers} layer${layers > 1 ? `s ${split}` : ''}`;
    const marker = slotMarkerRadius(slotCount, layers, split);
    const half = (Math.PI / slotCount) * 0.62;
    const depth = (WINDING_RING.outer - WINDING_RING.inner) / (split === 'radial' ? layers : 1);
    const width = (2 * half) / (split === 'tangential' ? layers : 1);
    for (let layer = 1; layer <= layers; layer += 1) {
      const slotIndex = 3;
      const centre = slotSideCentre(slotIndex, slotCount, layer, layers, split);
      const r = radius(centre);
      const angle = angleOf(centre);
      // The side's own edges, as slotSidePath draws them.
      const a0 = slotAngle(slotIndex, slotCount) - half + (split === 'tangential' ? (layer - 1) * width : 0);
      const a1 = a0 + width;
      const r0 = WINDING_RING.inner + (split === 'radial' ? (layer - 1) * depth : 0);
      const r1 = r0 + depth;
      assert.ok(r * Math.sin(angle - a0) >= marker - 1e-9 && r * Math.sin(a1 - angle) >= marker - 1e-9, `${label} layer ${layer}: marker clear of the slot's sides`);
      assert.ok(r - marker >= r0 && r + marker <= r1, `${label} layer ${layer}: marker clear of the slot's ends`);
    }
    // Most of the narrower dimension, so it reads at Fit; capped for few, wide slots.
    const centreRadius = WINDING_RING.inner + depth / 2;
    const narrowHalf = Math.min(centreRadius * Math.sin(width / 2), depth / 2);
    assert.ok(marker >= Math.min(26, 0.75 * narrowHalf), `${label}: marker fills its side (${marker.toFixed(1)} of ${narrowHalf.toFixed(1)})`);
  }
}
// SPM 6p/36s: about 14.5 units, against a typed glyph of about 8 before.
assert.ok(slotMarkerRadius(36, 1, null) > 14, '6p/36s marker');

console.log('winding ring checks passed');

// The imported Prius is reflected: all 48 slots and both ends of every coil
// must follow its actual cross-section, including slot 13 at six o'clock.
const prius = JSON.parse(await readFile(new URL('../../tests/fixtures/prius_winding_ring.json', import.meta.url), 'utf8'));
const priusAngles = previewSlotAngles(prius.regions, 48);
const angleClose = (actual, expected, label) => close(Math.atan2(Math.sin(actual - expected), Math.cos(actual - expected)), 0, label, 1e-4);
for (let index = 0; index < 48; index += 1) {
  angleClose(slotAngle(index, 48, priusAngles), -index * 2 * Math.PI / 48, `Prius slot ${index + 1}`);
  angleClose(angleOf(slotSideCentre(index, 48, 1, 1, null, priusAngles)), priusAngles[index], `Prius marker ${index + 1}`);
}
for (const coil of prius.coils) {
  const path = points(endTurnPath(coil.slot_in, coil.slot_out, 48, priusAngles));
  angleClose(angleOf(path[0]), priusAngles[coil.slot_in], 'Prius end turn start');
  angleClose(angleOf(path.at(-1)), priusAngles[coil.slot_out], 'Prius end turn end');
  assert.ok(path.every(p => radius(p) >= WINDING_RING.endTurn - 0.02));
}
// Reversing polygon vertex order cannot change its centroid; neither can
// splitting a slot into two layers. Missing geometry keeps the generic fallback.
const box = (points) => ({region_type: 'slot_1_layer_1', points});
const a = box([[2, 1], [4, 1], [4, 3], [2, 3]]);
const b = box([[4, 1], [8, 1], [8, 3], [4, 3]]);
close(previewSlotAngles([a, b], 1)[0], Math.atan2(2, 5), 'area-weighted layers');
close(previewSlotAngles([{...a, points: [...a.points].reverse()}, b], 1)[0], Math.atan2(2, 5), 'vertex order');
assert.deepEqual(previewSlotAngles([], 12), Array.from({length: 12}, (_, i) => slotAngle(i, 12)));
console.log('actual Prius slot geometry checks passed');
