import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { fitTransform, viewportTransformOrigin, anchoredZoomPan } = await importTypeScriptModule(
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
console.log('shifted and full viewport zoom checks passed');
