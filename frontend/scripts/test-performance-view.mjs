import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  SVPWM_MODULATION, curveAt, defaultDriveLimits, efficiencyBands, efficiencyColor, formatDuration, inductanceTable, mapCsv, niceTicks,
} = await importTypeScriptModule(new URL('../src/public/performanceView.ts', import.meta.url));

// Defaults from a run at 10 A rms, 7.5 V rms back EMF, 3,000 rpm.
const limits = defaultDriveLimits({ ratedSpeedRpm: 3000, phaseCurrentRmsA: 10, backEmfRmsV: 7.5 });
assert.equal(limits.peak_current_A, 29, 'twice the solved peak, 28.3 A, rounded up');
assert.equal(limits.continuous_current_A, 14.5);
assert.equal(limits.dc_bus_V, 30, '√3 × 10.6 V × 1.3 = 23.9 V, up to the next 10 V');
assert.equal(limits.max_speed_rpm, 9000);
assert.equal(limits.modulation_index_max, SVPWM_MODULATION);
assert.equal(defaultDriveLimits({ ratedSpeedRpm: 3000, phaseCurrentRmsA: 10, backEmfRmsV: 7.5, dcBusV: 48 }).dc_bus_V, 48, 'a design bus wins');

assert.deepEqual(niceTicks(23), [0, 5, 10, 15, 20, 25]);
assert.deepEqual(niceTicks(0.9), [0, 0.2, 0.4, 0.6, 0.8, 1]);
assert.deepEqual(niceTicks(0), [0]);

const effMap = { efficiency_pct: [[null, 80.4, 91.2], [70.1, 88.8, 96.6]] };
const bands = efficiencyBands(effMap);
assert.deepEqual(bands, { floor: 81, top: 97, step: 2 }, 'the floor stays within 16 points of the peak');
assert.equal(efficiencyColor(82.9, bands), efficiencyColor(81.0, bands), 'one band, one colour');
assert.notEqual(efficiencyColor(83.0, bands), efficiencyColor(81.0, bands));
assert.equal(efficiencyColor(70.1, bands), efficiencyColor(81.0, bands), 'lower values share the darkest band');
assert.equal(efficiencyBands({ efficiency_pct: [[90, 92, 96]] }).floor, 86, 'a narrow map keeps ten points of range');

const curve = {
  speed_rpm: [0, 1000, 2000], torque_Nm: [10, 10, 6], power_W: [0, 1047, 1257], region: ['mtpa', 'mtpa', 'field_weakening'],
  i_d_A: [0, 0, -30], i_q_A: [40, 40, 30],
};
const at1500 = curveAt(curve, 1500);
assert.deepEqual({ torque: at1500.torque, power: at1500.power, region: at1500.region }, { torque: 8, power: 1152, region: 'field_weakening' });
assert.ok(Math.abs(at1500.currentPeakA - Math.hypot(-15, 35)) < 1e-9, 'current magnitude from the interpolated id and iq');
assert.ok(Math.abs(at1500.gammaDeg - Math.atan2(15, 35) * 180 / Math.PI) < 1e-9);
assert.equal(curveAt(curve, 2500), null);

const point = (current, gamma, ld, lq) => {
  const rad = gamma * Math.PI / 180;
  return { current_peak_A: current, gamma_deg: gamma, i_d_A: -current * Math.sin(rad), i_q_A: current * Math.cos(rad), status: 'ok', avg_torque_Nm: 1, lambda_d_Wb: ld, lambda_q_Wb: lq };
};
const fluxMap = {
  scope_key: 'abc123', pole_pairs: 2, current_peak_A: [0, 10], gamma_deg: [0, 90], reference_speed_rpm: 3000, rotor_positions: 17, mesh_density: 'normal',
  points: [point(0, 0, 0.011, 0), point(0, 90, 0.011, 0), point(10, 0, 0.011, 0.0005), point(10, 90, 0.0105, 0)],
};
const [row] = inductanceTable(fluxMap);
assert.equal(row.currentA, 10);
assert.ok(Math.abs(row.ldH - 0.00005) < 1e-12, 'Ld = (10.5 − 11) mWb / −10 A');
assert.ok(Math.abs(row.lqH - 0.00005) < 1e-12);

const csv = mapCsv({ ...fluxMap, points: [...fluxMap.points, { ...point(10, 45, 0.0108, 0.0004), status: 'failed', error: 'mesh, "bad"' }] });
const lines = csv.trim().split('\n');
assert.match(lines[0], /^# coilEM flux-linkage map, scope abc123/);
assert.equal(lines[3].split(',')[0], 'current_peak_A');
assert.equal(lines.length, 3 + 1 + 5);
assert.match(lines[lines.length - 1], /,"mesh, ""bad"""$/);

assert.equal(formatDuration(42), 'about 40 s');
assert.equal(formatDuration(400), 'about 7 min');
assert.equal(formatDuration(null), '');

console.log('performance view: ok');

const { estimateMapSeconds } = await importTypeScriptModule(new URL('../src/public/performanceView.ts', import.meta.url));
// The 8p12s example: a 25.5 s run of 48 positions; 12 positions per point cost about 1.25 × 6.4 s ≈ 8 s.
const perPoint = 1.25 * 25.5 * 12 / 48;
const fresh = estimateMapSeconds({ runSolveSeconds: 25.5, runPositions: 48, pointPositions: 12, solves: 29, zeroPointPending: true });
assert.ok(Math.abs(fresh - perPoint * 31) < 1e-9, 'the zero-current point counts three times');
const resumed = estimateMapSeconds({ runSolveSeconds: 25.5, runPositions: 48, pointPositions: 12, solves: 10, zeroPointPending: false });
assert.ok(Math.abs(resumed - perPoint * 10) < 1e-9);
assert.equal(estimateMapSeconds({ runSolveSeconds: null, runPositions: 48, pointPositions: 12, solves: 29, zeroPointPending: true }), null);
assert.equal(estimateMapSeconds({ runSolveSeconds: 25.5, runPositions: 48, pointPositions: 12, solves: 0, zeroPointPending: true }), null);
console.log('performance view: map estimate ok');

const { currentUnits, efficiencyAt } = await importTypeScriptModule(new URL('../src/public/performanceView.ts', import.meta.url));
// The Solve page's units: rms unless the design is set to peak.
const rms = currentUnits('rms');
assert.equal(rms.unit, 'A rms');
assert.ok(Math.abs(rms.toPeak(35) - 49.497) < 1e-3);
assert.ok(Math.abs(rms.fromPeak(rms.toPeak(35)) - 35) < 1e-12);
assert.equal(currentUnits('plateau').unit, 'A rms');
assert.equal(currentUnits('peak').toPeak(40), 40);
// Defaults round in the shown unit: 35 A rms solved → continuous 35 A rms, peak 70 A rms.
const shown = defaultDriveLimits({ ratedSpeedRpm: 2400, phaseCurrentRmsA: 35, backEmfRmsV: 31.2, shownUnitPeakA: Math.SQRT2 });
assert.ok(Math.abs(rms.fromPeak(shown.continuous_current_A) - 35) < 1e-9);
assert.ok(Math.abs(rms.fromPeak(shown.peak_current_A) - 70) < 1e-9);
// The solved point's cell, and nothing off the map or above the envelope.
const grid = { speed_rpm: [1000, 2000, 3000], torque_Nm: [5, 10, 15], efficiency_pct: [[90, 92, 93], [91, 95, 94], [null, 94, null]] };
assert.equal(efficiencyAt(grid, 2100, 10.4), 95);
assert.equal(efficiencyAt(grid, 3000, 15), null);
assert.equal(efficiencyAt(grid, 5000, 10), null);
console.log('performance view: current units, defaults and solved point ok');

const { currentAt } = await importTypeScriptModule(new URL('../src/public/performanceView.ts', import.meta.url));
const currents = { ...grid, phase_current_rms_A: [[10, 9, 8], [20, 18, 17], [null, 27, null]], current_angle_deg: [[0, 0, 5], [0, 3, 12], [null, 20, null]] };
assert.deepEqual(currentAt(currents, 2100, 10.4), { rmsA: 18, gammaDeg: 3 });
assert.equal(currentAt(currents, 1000, 15), null);
assert.equal(currentAt(grid, 2000, 10), null, 'maps without currents show none');
console.log('performance view: current at a point ok');
