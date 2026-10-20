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

const curve = { speed_rpm: [0, 1000, 2000], torque_Nm: [10, 10, 6], power_W: [0, 1047, 1257], region: ['mtpa', 'mtpa', 'field_weakening'] };
assert.deepEqual(curveAt(curve, 1500), { torque: 8, power: 1152, region: 'field_weakening' });
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
