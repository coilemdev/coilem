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
  torqueRippleView,
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

// Ripple % only where it means something. No current: the torque is cogging,
// averaging about zero, so the swing replaces a 329,698 % ripple (the 2005
// Honda Accord at 0 A, Preview).
const run = (avg, ripple, torque, current) => ({
  summary: { avg_torque_Nm: avg, torque_ripple_pct: ripple },
  torque_waveform: { electrical_angle_deg: torque.map((_, index) => index * 3.75), torque_Nm: torque },
  solve_metadata: { current_amplitude_A: current },
});
const noLoad = torqueRippleView(run(0.005, 329698.82, [0.1, 6.2, 8.3, 2.0, -8.4, -3.1], 0));
assert.equal(noLoad.ripplePct, null);
assert.ok(Math.abs(noLoad.peakToPeakNm - 16.7) < 1e-9);
assert.equal(noLoad.peakToPeakLabel, 'Cogging torque p-p');
assert.match(noLoad.note, /^No current, so this torque is cogging/);
// A loaded run keeps the solver's percentage and shows no swing row.
assert.deepEqual(torqueRippleView(run(10.66, 14.27, [11.66, 10.4, 9.24, 10.9], 42.4)),
  { ripplePct: 14.27, peakToPeakNm: null, peakToPeakLabel: 'Torque p-p', note: null });
// Current but a near-zero average (all d-axis): the swing, not cogging.
const dAxis = torqueRippleView(run(0.01, 40000, [-2, 0, 2], 10));
assert.equal(dAxis.ripplePct, null);
assert.equal(dAxis.peakToPeakNm, 4);
assert.equal(dAxis.peakToPeakLabel, 'Torque p-p');
assert.match(dAxis.note, /^The average torque is close to zero/);
// Without the requested current the average alone decides.
assert.equal(torqueRippleView({ ...run(0.002, 1e5, [-1, 1], 0), solve_metadata: {} }).ripplePct, null);
assert.equal(torqueRippleView({ ...run(5, 12, [4.7, 5.3], 0), solve_metadata: {} }).ripplePct, 12);

console.log('result summary: frequency, power, torque range, ripple view, sparkline, loading scale and knee pass');
