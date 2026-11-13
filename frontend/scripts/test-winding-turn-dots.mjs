import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { windingTurnDots } = await importTypeScriptModule(new URL('../src/public/windingTurnDots.ts', import.meta.url));
const { pointInContours } = await importTypeScriptModule(new URL('../src/public/previewContours.ts', import.meta.url));
// A coil side with a narrow shoe neck. The paired side mirrors it about the slot.
const points = [[0, 30], [0.45, 30], [0.45, 31], [3, 31], [4, 42], [0, 42]];
const side = (points) => ({ region_type: 'slot_1_(a+)', points });
for (const outer of [false, true]) for (const turns of [1, 2, 14, 21, 100, 500]) {
  const layout = windingTurnDots(side(points), turns, Math.PI / 2, outer);
  assert.ok(layout && layout.radius > 0, `${turns} turns has a layout`);
  assert.equal(layout.points.length, turns, 'one dot per turn, without truncation');
  const marker = layout.marker;
  for (const [x, y] of layout.points) {
    // The entire disk stays inside the copper polygon, clear of the marker.
    for (let i = 0; i < 24; i += 1) {
      const a = i * Math.PI / 12;
      assert.ok(pointInContours([x + layout.radius * Math.cos(a), y + layout.radius * Math.sin(a)], [points]));
    }
    assert.ok(Math.hypot(x - marker.point[0], y - marker.point[1]) > layout.radius + marker.radius);
  }
  for (let i = 0; i < layout.points.length; i += 1) for (let j = i + 1; j < layout.points.length; j += 1) {
    assert.ok(Math.hypot(layout.points[i][0] - layout.points[j][0], layout.points[i][1] - layout.points[j][1]) >= 2 * layout.radius - 1e-8);
  }
  const mirrored = windingTurnDots(side(points.map(([x, y]) => [-x, y])), turns, Math.PI / 2, outer);
  assert.ok(Math.abs(marker.point[0] + mirrored.marker.point[0]) < 1e-8);
  assert.ok(Math.abs(marker.point[1] - mirrored.marker.point[1]) < 1e-8, 'paired markers share their radial station');
  assert.ok(Math.abs(layout.radius - mirrored.radius) < 1e-8);
  const rounded = (points) => points.map((point) => point.map((n) => Number(n.toFixed(8)))).sort();
  assert.deepEqual(rounded(layout.points.map(([x, y]) => [-x, y])), rounded(mirrored.points));
}
// Rotating the same side preserves its layout and count.
const angle = 1.2;
const rotate = ([x, y]) => [x * Math.cos(angle) - y * Math.sin(angle), x * Math.sin(angle) + y * Math.cos(angle)];
const original = windingTurnDots(side(points), 14, Math.PI / 2);
const rotated = windingTurnDots(side(points.map(rotate)), 14, Math.PI / 2 + angle);
assert.equal(rotated.points.length, 14);
assert.ok(Math.abs(original.radius - rotated.radius) < 1e-8);
assert.equal(windingTurnDots(side([[0, 0], [1, 1]]), 14, 0), null);
assert.equal(windingTurnDots(side(points), 0, 0), null);
console.log('Winding turn dots: exact counts, containment, separation, paired symmetry and rotation passed.');
