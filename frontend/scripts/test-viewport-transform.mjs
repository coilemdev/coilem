import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { fitTransform, viewportTransformOrigin, anchoredZoomPan, viewportScaleBar } = await importTypeScriptModule(
  new URL('../src/public/viewportTransform.ts', import.meta.url),
);
const { phaseDriveFrame } = await importTypeScriptModule(new URL('../src/public/phaseDrive.ts', import.meta.url));
const points = [[-100, -100], [100, 100]];
for (const [width, height] of [[1000, 700], [760, 600], [400, 500]]) {
  for (const frame of [undefined, phaseDriveFrame(width, height)?.motor]) {
    const origin = viewportTransformOrigin(width, height, frame);
    for (const point of [[0, 0], [50, -35], [-60, 30]]) {
      for (const [scale, nextScale] of [[1, 2], [2, 1], [1.25, 3.5]]) {
        const pan = { x: 14, y: -8 };
        const before = fitTransform(points, width, height, scale, [pan.x, pan.y], frame).map(point);
        const anchor = { x: before[0] - origin.x, y: before[1] - origin.y };
        const next = anchoredZoomPan(pan, scale, nextScale, anchor);
        const after = fitTransform(points, width, height, nextScale, [next.x, next.y], frame).map(point);
        assert.ok(Math.hypot(after[0] - before[0], after[1] - before[1]) < 1e-9, 'point beneath the pointer must stay fixed');
        const restored = anchoredZoomPan(next, nextScale, scale, anchor);
        assert.ok(Math.hypot(restored.x - pan.x, restored.y - pan.y) < 1e-9, 'zoom roundtrip preserves pan');
      }
    }
  }
}
// The sector turntable turns the motor about its centre before zoom and pan: the
// centre stays put, distances from it are kept, and a quarter turn takes the top
// of the motor to its right-hand side (clockwise on screen).
{
  const motor = [[-40, -40], [40, -40], [40, 40], [-40, 40]];
  const still = fitTransform(motor, 600, 400, 2, [30, -20]);
  const turned = fitTransform(motor, 600, 400, 2, [30, -20], undefined, Math.PI / 2);
  const centre = still.map([0, 0]);
  assert.deepEqual(turned.map([0, 0]).map((v) => Math.round(v * 1e9) / 1e9), centre.map((v) => Math.round(v * 1e9) / 1e9));
  const top = still.map([0, 30]);
  const topTurned = turned.map([0, 30]);
  const radius = Math.hypot(top[0] - centre[0], top[1] - centre[1]);
  assert.ok(Math.abs(Math.hypot(topTurned[0] - centre[0], topTurned[1] - centre[1]) - radius) < 1e-9);
  assert.ok(Math.abs(topTurned[0] - (centre[0] + radius)) < 1e-9 && Math.abs(topTurned[1] - centre[1]) < 1e-9);
  assert.equal(turned.scale, still.scale);
}
// A scale bar measures the same physical distance as the fitted drawing,
// including small decimals at inspection zoom and a shifted/rotated frame.
for (const diameter of [10, 48, 100, 190, 500]) {
  for (const zoom of [0.5, 1, 1.25, 8, 256]) {
    for (const frame of [undefined, { x: 100, y: 30, width: 470, height: 550 }]) {
      const fit = fitTransform([[-diameter / 2, -diameter / 2], [diameter / 2, diameter / 2]], 900, 650, zoom, [37, -29], frame, 0.8);
      const bar = viewportScaleBar(fit.scale);
      assert.ok(bar && bar.mm > 0 && bar.pixels > 0 && bar.pixels <= 120 + 1e-9);
      const from = fit.map([0, 0]);
      const to = fit.map([bar.mm, 0]);
      assert.ok(Math.abs(Math.hypot(to[0] - from[0], to[1] - from[1]) - bar.pixels) < 1e-8);
      const mantissa = bar.mm / 10 ** Math.floor(Math.log10(bar.mm));
      assert.ok([1, 2, 5].some((n) => Math.abs(n - mantissa) < 1e-9));
    }
  }
}
for (const value of [0, -1, NaN, Infinity]) assert.equal(viewportScaleBar(value), null);
assert.equal(viewportScaleBar(3, 0), null);
console.log('shifted/full viewport zoom and physical scale-bar checks passed');
