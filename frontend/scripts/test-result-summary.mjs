import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  electricalFrequencyHz,
  electromagneticPower,
  formatFrequencyHz,
  loadingScaleMaxT,
  saturationKneeRangeT,
  sparklinePath,
  sharedSparklinePaths,
  torqueRange,
} = await importTypeScriptModule(new URL('../src/public/resultMetrics.ts', import.meta.url));

// The default example: 8 poles at 2,400 rpm is 160 Hz electrical.
assert.equal(electricalFrequencyHz(2400, 8), 160);
assert.equal(formatFrequencyHz(160), '160');
assert.equal(formatFrequencyHz(electricalFrequencyHz(1000, 14)), '116.7');

// Electromagnetic power is torque × mechanical speed: 10.59 N·m at 2,400 rpm is 2.66 kW.
assert.deepEqual(electromagneticPower(10.59, 2400), { text: '2.66', unit: 'kW' });
assert.deepEqual(electromagneticPower(0.5, 1000), { text: '52.4', unit: 'W' });
assert.deepEqual(electromagneticPower(-10.59, 2400), { text: '−2.66', unit: 'kW' }, 'generating keeps its sign');
assert.equal(electromagneticPower(Number.NaN, 2400), null);

// The torque range ignores non-finite samples and needs two.
assert.deepEqual(torqueRange([11.2, 9.8, Number.NaN, 11.6]), { min: 9.8, max: 11.6 });
assert.equal(torqueRange([10]), null);

// The sparkline spans the box inside its margin, lowest sample at the bottom.
const path = sparklinePath([1, 3, 2], 100, 20);
assert.equal(path, 'M2.0 18.0 L50.0 2.0 L98.0 10.0');
assert.equal(sparklinePath([5, 5, 5], 100, 20), 'M2.0 18.0 L50.0 18.0 L98.0 18.0', 'a flat waveform draws a flat line');
assert.equal(sparklinePath([7], 100, 20), null);

// The back-EMF sparkline draws all phases on one scale: a flat phase at the
// midpoint of another's swing sits mid-height, not at the bottom (#110).
const [phaseA, phaseB] = sharedSparklinePaths([[0, 2, 0], [1, 1, 1]], 100, 20);
assert.equal(phaseA, 'M2.0 18.0 L50.0 2.0 L98.0 18.0');
assert.equal(phaseB, 'M2.0 10.0 L50.0 10.0 L98.0 10.0');
assert.deepEqual(sharedSparklinePaths([[1], []], 100, 20), [null, null], 'without two finite samples, no phase draws');

// The flux-density scale is 0–2 T unless a peak exceeds it.
assert.equal(loadingScaleMaxT([1.5, 1.25]), 2);
assert.equal(loadingScaleMaxT([2.1, 1.25]), 2.5);
assert.equal(loadingScaleMaxT([Number.NaN]), 2);

// The knee comes from the steel's own model; custom steels declare none.
const catalog = {
  steels: ['M350-50A'], magnet_grades: [], conductors: [],
  models: {
    'M350-50A': { properties: { saturation_knee_range_T: [1.4, 1.6] } },
    'custom:abc': { properties: { curve_max_T: 2 } },
    broken: { properties: { saturation_knee_range_T: [1.6, 1.4] } },
  },
};
assert.deepEqual(saturationKneeRangeT(catalog, 'M350-50A'), [1.4, 1.6]);
assert.equal(saturationKneeRangeT(catalog, 'custom:abc'), null);
assert.equal(saturationKneeRangeT(catalog, 'broken'), null, 'an inverted range is ignored');
assert.equal(saturationKneeRangeT({ steels: [], magnet_grades: [], conductors: [] }, 'M350-50A'), null);

console.log('result summary: frequency, power, torque range, sparkline, loading scale and knee pass');
