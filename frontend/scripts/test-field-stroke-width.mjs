import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// Field lines and mesh edges are drawn in model millimetres. The 200 mm example
// and anything larger keep the tuned widths; smaller motors (outrunners, small
// inrunners) thin them in proportion so they look the same on screen.
const { fieldStrokeScale, FIELD_STROKE_REFERENCE_VIEW_MM } = await importTypeScriptModule(
  new URL('../src/public/fieldStrokeWidth.ts', import.meta.url),
);

// The 200 mm example's view (2.5 % padding each side) is the reference.
assert.equal(FIELD_STROKE_REFERENCE_VIEW_MM, 210);
assert.equal(fieldStrokeScale(210, 210), 1);
// Larger motors (the Prius stator is 269.24 mm) keep the tuned widths.
assert.equal(fieldStrokeScale(269.24 * 1.05, 269.24 * 1.05), 1);
// The LRK outrunner (30.78 mm rotor OD) thins to about a seventh.
const lrk = fieldStrokeScale(30.78 * 1.05, 30.78 * 1.05);
assert.ok(Math.abs(lrk - (30.78 * 1.05) / 210) < 1e-12);
assert.ok(lrk > 0.15 && lrk < 0.16);
// The larger side sets the raster scale, so it sets the factor too.
assert.equal(fieldStrokeScale(105, 42), 0.5);
// A degenerate view keeps the tuned widths.
assert.equal(fieldStrokeScale(Number.NaN, 10), 1);
assert.equal(fieldStrokeScale(0, 0), 1);

console.log('field stroke width tests passed');
