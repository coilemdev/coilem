import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  backEmfReadings,
  electricalFrequencyHz,
  formatVolts,
  waveformMeasure,
  electromagneticPower,
  formatFrequencyHz,
  loadingScaleMaxT,
  saturationKneeRangeT,
  sparklinePath,
  sharedSparklinePaths,
  torqueRange,
  torqueRippleView,
  solvedPhaseCurrent,
} = await importTypeScriptModule(new URL('../src/public/resultMetrics.ts', import.meta.url));

const currentConfig = { solve_params: { current_amplitude_A: 30, current_amplitude_convention: 'rms' } };
assert.equal(solvedPhaseCurrent(currentConfig, { solve_metadata: { current_amplitude_A: 0 } }), 0);
assert.equal(solvedPhaseCurrent(currentConfig, { solve_metadata: { current_amplitude_A: 30 * Math.SQRT2 } }), 30);
assert.equal(solvedPhaseCurrent(currentConfig, { solve_metadata: {} }), 30, 'old results retain their recorded requested current');
assert.equal(solvedPhaseCurrent(currentConfig, { solve_metadata: { current_amplitude_A: 20, current_amplitude_convention: 'rms' } }), 20);
assert.equal(solvedPhaseCurrent({ solve_params: { current_amplitude_A: 30, current_amplitude_convention: 'plateau' } }, { solve_metadata: { current_amplitude_A: 18 } }), 18);

// The default example: 8 poles at 2,400 rpm is 160 Hz electrical.
assert.equal(electricalFrequencyHz(2400, 8), 160);
assert.equal(formatFrequencyHz(160), '160');
assert.equal(formatFrequencyHz(electricalFrequencyHz(1000, 14)), '116.7');

// Electromagnetic power is torque × mechanical speed: 10.59 N·m at 2,400 rpm is 2.66 kW.
assert.deepEqual(electromagneticPower(10.59, 2400), { text: '2.66', unit: 'kW' });
assert.deepEqual(electromagneticPower(0.5, 1000), { text: '52.4', unit: 'W' });
assert.deepEqual(electromagneticPower(-10.59, 2400), { text: '−2.66', unit: 'kW' }, 'generating keeps its sign');
assert.equal(electromagneticPower(Number.NaN, 2400), null);

// Back EMF readings: rms is the fundamental's, peak and pk-pk come from the solved
// waveform. A phase of 10 sin θ − sin 3θ reaches 11 V, not the fundamental's 10 V,
// so its peak is not √2 × rms; a − b cancels the third harmonic and peaks at √3·10 V.
const cycle = Array.from({ length: 48 }, (_, index) => index * 7.5);
const phase = (shiftDeg) => cycle.map((angle) => {
  const theta = ((angle - shiftDeg) * Math.PI) / 180;
  return 10 * Math.sin(theta) - Math.sin(3 * theta);
});
const emf = { electrical_angle_deg: cycle, phase_a_V: phase(0), phase_b_V: phase(120), phase_c_V: phase(240) };
const close = (actual, expected, label) => assert.ok(Math.abs(actual - expected) < 1e-9, `${label}: ${actual} vs ${expected}`);
close(waveformMeasure(cycle, emf.phase_a_V, 'rms'), 10 / Math.SQRT2, 'fundamental rms ignores the third harmonic');
close(waveformMeasure(cycle, emf.phase_a_V, 'peak'), 11, 'peak includes it: 10 sin θ − sin 3θ peaks at 11 V on θ = 90°');
close(waveformMeasure(cycle, emf.phase_a_V, 'pk-pk'), 22, 'pk-pk');
assert.equal(waveformMeasure(cycle.slice(0, 7), emf.phase_a_V.slice(0, 7), 'peak'), null, 'a Preview window is not a whole cycle');
assert.equal(waveformMeasure(cycle, emf.phase_a_V.slice(1), 'rms'), null, 'mismatched lengths');
const readings = backEmfReadings(emf, 10 / Math.SQRT2);
assert.deepEqual(readings.map((row) => row.label), ['Phase', 'Line (wye)']);
close(readings[0].peakV, 11, 'phase peak');
close(readings[1].rmsV, Math.sqrt(3) * 10 / Math.SQRT2, 'line rms is √3 × phase');
close(readings[1].peakV, 10 * Math.sqrt(3), 'line a − b: the third harmonic cancels');
close(readings[1].peakToPeakV, 20 * Math.sqrt(3), 'line pk-pk');
assert.equal(backEmfReadings({ ...emf, line_ab_V: emf.phase_a_V.map((value) => 2 * value) }, 1)[1].peakV, 22, 'a solver line waveform is used as given');
assert.equal(backEmfReadings(emf, null), null);
assert.deepEqual(backEmfReadings({ ...emf, electrical_angle_deg: cycle.map((angle) => angle / 8) }, 5).map((row) => row.peakV), [null, null]);
assert.deepEqual([formatVolts(6.358), formatVolts(17.4), formatVolts(31.62), formatVolts(230.6), formatVolts(null)], ['6.36', '17.4', '31.6', '231', '—']);

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
// With a cogging sweep (#185) the 0 A row is the sweep's own peak-to-peak, so two cogging numbers never disagree.
const withSweep = run(0.005, 329698.82, [0.1, 6.2, 8.3, 2.0, -8.4, -3.1], 0);
withSweep.summary.cogging = { peak_to_peak_Nm: 0.412, positions_per_period: 24 };
const sweepRow = torqueRippleView(withSweep);
assert.equal(sweepRow.peakToPeakNm, 0.412);
assert.equal(sweepRow.peakToPeakLabel, 'Cogging torque p-p');
assert.match(sweepRow.note, /cogging sweep's: one cogging period at 24 positions/);
assert.match(noLoad.note, /not sized to the cogging period; turn on Cogging torque/);
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
