import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// One flux-density colour scale (0–2.0 T, magenta above) and the stator steel's
// knee and saturation ticks, read from its B–H curve.
const {
  FIXED_FLUX_SCALE,
  FLUX_OVER_RANGE_INDEX,
  fittedFluxScale,
  fluxColorIndex,
  statorSteelSaturationTicks,
  steelSaturationTicks,
} = await importTypeScriptModule(new URL('../src/public/fluxColorScale.ts', import.meta.url));

const close = (actual, expected, label, tolerance = 0.01) => {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} != ${expected}`);
};

// Fixed scale: eight colours over 0–2.0 T, then the over-range colour.
assert.equal(fluxColorIndex(0, FIXED_FLUX_SCALE), 0);
assert.equal(fluxColorIndex(0.24, FIXED_FLUX_SCALE), 0);
assert.equal(fluxColorIndex(1.39, FIXED_FLUX_SCALE), 5);
assert.equal(fluxColorIndex(2.0, FIXED_FLUX_SCALE), 7);
assert.equal(fluxColorIndex(2.64, FIXED_FLUX_SCALE), FLUX_OVER_RANGE_INDEX);

// Fit view never stretches past 2.0 T, so one hot element cannot set the top.
const fitted = fittedFluxScale(0.2, 2.64);
assert.equal(fitted.maxB, 2.0);
assert.equal(fitted.fixed, false);
assert.equal(fluxColorIndex(2.64, fitted), FLUX_OVER_RANGE_INDEX);
const lowFlux = fittedFluxScale(0.1, 0.9);
assert.deepEqual([lowFlux.minB, lowFlux.maxB], [0.1, 0.9]);
assert.equal(fluxColorIndex(0.9, lowFlux), 7);

// M350-50A, the bundled steel: its permeability falls to 1000 at 1.47 T and
// to 100 at 1.78 T.
const csv = await readFile(new URL('../../materials/electrical-steel/M350-50A.csv', import.meta.url), 'utf8');
const points = csv.split('\n')
  .filter((line) => line && !line.startsWith('#') && !line.startsWith('B_T'))
  .map((line) => line.split(',').map(Number))
  .map(([b, h]) => [h, b]);
const [knee, saturation] = steelSaturationTicks(points, 'M350-50A');
assert.equal(knee.label, 'knee');
close(knee.bT, 1.473, 'M350-50A knee');
assert.equal(saturation.label, 'saturation');
close(saturation.bT, 1.776, 'M350-50A saturation');

// A curve that never falls that far, or none at all, gives 1.5 T and 1.8 T.
assert.deepEqual(steelSaturationTicks(null, 'unknown').map((tick) => tick.bT), [1.5, 1.8]);

// A custom stator steel's ticks come from its own curve.
const custom = {
  id: 'custom:0123456789abcdef', name: 'Lab sample', source: 'Lab measurement',
  lamination_thickness_mm: null, curve_sha256: '0'.repeat(64),
  bh_curve: [[0, 0], [1.0, 100], [1.5, 10000]],
};
const config = { materials: { stator_steel: custom.id, custom_steels: { [custom.id]: custom } } };
const catalog = { steels: ['M350-50A'], magnet_grades: [], conductors: [], models: {} };
const customTicks = statorSteelSaturationTicks(config, catalog);
close(customTicks[0].bT, 1.444, 'custom knee');
assert.equal(customTicks[0].steelName, 'Lab sample');
assert.equal(customTicks[1].bT, 1.8);

console.log('flux colour scale and steel saturation ticks passed');
