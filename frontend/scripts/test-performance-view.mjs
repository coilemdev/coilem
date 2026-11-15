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
assert.match(lines[3], /^# experimental: The d\/q gates cover 12 operating points, not a map's full range/, 'the points say they are experimental, and why');
assert.equal(lines[4].split(',')[0], 'current_peak_A');
assert.equal(lines.length, 4 + 1 + 5);
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

// Tiles, tables and readouts keep three significant figures, trailing zeros included.
const { formatSignificant } = await importTypeScriptModule(new URL('../src/public/numberFormat.ts', import.meta.url));
assert.equal(formatSignificant(1.4), '1.40');
assert.equal(formatSignificant(0.14), '0.140');
assert.equal(formatSignificant(0.1394), '0.139');
assert.equal(formatSignificant(2153), '2,150');
assert.equal(formatSignificant(14.94), '14.9');
assert.equal(formatSignificant(0), '0');
assert.equal(formatSignificant(-3.4), '-3.40');
assert.equal(formatSignificant(Number.NaN), '—');
assert.equal(formatSignificant(null), '—');

console.log('performance view: current at a point ok');

// #274: a note when the run's solved point lies outside the map, and which limit keeps it out.
const { solvedPointOutsideMap, solvedPointOutsideNote } = await importTypeScriptModule(new URL('../src/public/performanceView.ts', import.meta.url));
const asRms = (peakA) => `${Number((peakA / Math.SQRT2).toPrecision(3)).toLocaleString()} A rms`;
const peakCurve = (speeds, torques) => ({
  limit: 'peak', speed_rpm: speeds, torque_Nm: torques, power_W: speeds.map((speed, index) => torques[index] * speed * Math.PI / 30),
  i_d_A: speeds.map(() => 0), i_q_A: speeds.map(() => 84.85), region: speeds.map(() => 'mtpa'),
  base_speed_rpm: speeds[1], max_speed_rpm: speeds[speeds.length - 1], peak_power_W: 0,
});
// The Example SPM 8p/12s run: 30 A rms at 2,400 rpm, 11.2 N·m, its loaded d/q record and its map's limits.
const spmLimits = { dc_bus_V: 48, modulation_index_max: SVPWM_MODULATION, peak_current_A: 84.8528, continuous_current_A: 42.4264, max_speed_rpm: 7200 };
const spmEnvelope = (limits, speeds, torques) => ({ limits, phase_resistance_ohm: 0.0057745, curves: [peakCurve(speeds, torques)] });
const spmDq = { i_d_A: -0.00095, i_q_A: 42.4264, lambda_d_Wb: 0.0438556, lambda_q_Wb: 0.0057824 };
// At 48 V the peak curve ends at 2,068 rpm, short of the solved 2,400 rpm.
const spm = { envelope: spmEnvelope(spmLimits, [0, 1437, 1800, 2068], [22.4, 22.4, 12, 0.3]), polePairs: 4, speedRpm: 2400, torqueNm: 11.1645, dq: spmDq };
const outsideAt48 = solvedPointOutsideMap(spm);
assert.equal(outsideAt48.aboveTopSpeed, false);
assert.equal(outsideAt48.currentAbovePeakA, null);
// ωe = 2,400 rpm × 4 pole pairs = 1,005 rad/s; |(R·id − ωe·λq, R·iq + ωe·λd)| = 44.7 V peak; Vdc = 2 × 44.7 V / (2/√3).
assert.ok(Math.abs(outsideAt48.busNeededV - 77.445) < 0.01, 'the map\'s voltage model at the run\'s own d/q point');
assert.equal(solvedPointOutsideNote(outsideAt48, asRms),
  'The solved point (2,400 rpm, 11.2 N·m) is outside this map at the 48 V DC bus. At its solved current it needs about 78 V; raise DC bus in Solve → Analysis → Torque–speed map to include it.');
// At 78 V the peak curve passes 2,400 rpm well above 11.2 N·m: no note.
assert.equal(solvedPointOutsideMap({ ...spm, envelope: spmEnvelope({ ...spmLimits, dc_bus_V: 78 }, [0, 2350, 3360], [22.4, 22.4, 0.5]) }), null);
// Within 1% above the drawn curve counts as on it.
assert.equal(solvedPointOutsideMap({ ...spm, envelope: spmEnvelope(spmLimits, [0, 1437, 2400, 3000], [22.4, 22.4, 11.1, 0.3]) }), null);
// Above the curve while the d/q record fits every limit: the gap is the map's interpolation, not a limit.
assert.equal(solvedPointOutsideMap({ ...spm, envelope: spmEnvelope({ ...spmLimits, dc_bus_V: 78 }, [0, 2350, 2400, 3360], [11, 11, 10.5, 0.5]) }), null);
// No d/q record (a six-step run): no estimate, and both limits named.
const noRecord = solvedPointOutsideMap({ ...spm, dq: null });
assert.equal(noRecord.busNeededV, null);
assert.equal(solvedPointOutsideNote(noRecord, asRms),
  'The solved point (2,400 rpm, 11.2 N·m) is outside this map at the 48 V DC bus and 60 A rms Peak current. Raise DC bus or Peak current in Solve → Analysis → Torque–speed map to include it.');
// Beyond the Top speed, alone and with the bus.
const slowMap = { ...spmLimits, max_speed_rpm: 2000 };
assert.equal(solvedPointOutsideNote(solvedPointOutsideMap({ ...spm, envelope: spmEnvelope(slowMap, [0, 1437, 1800, 2000], [22.4, 22.4, 12, 3]) }), asRms),
  'The solved point (2,400 rpm, 11.2 N·m) is outside this map at the 2,000 rpm Top speed and 48 V DC bus. At its solved current it needs about 78 V; raise Top speed and DC bus in Solve → Analysis → Torque–speed map to include it.');
assert.equal(solvedPointOutsideNote(solvedPointOutsideMap({ ...spm, envelope: spmEnvelope({ ...slowMap, dc_bus_V: 78 }, [0, 2000], [22.4, 22.4]) }), asRms),
  'The solved point (2,400 rpm, 11.2 N·m) is outside this map at the 2,000 rpm Top speed. Raise Top speed in Solve → Analysis → Torque–speed map to include it.');
// A Peak current below the solved current: at 1,000 rpm the bus is enough (32.5 V needed), the current is not.
const lowCurrent = { ...spmLimits, peak_current_A: 30, continuous_current_A: null };
assert.equal(solvedPointOutsideNote(solvedPointOutsideMap({ ...spm, speedRpm: 1000, envelope: spmEnvelope(lowCurrent, [0, 2500], [7.9, 7.9]) }), asRms),
  'The solved point (1,000 rpm, 11.2 N·m) is outside this map at the 21.2 A rms Peak current. It was solved at 30 A rms; raise Peak current in Solve → Analysis → Torque–speed map to include it.');
assert.equal(solvedPointOutsideNote(solvedPointOutsideMap({ ...spm, envelope: spmEnvelope(lowCurrent, [0, 1500, 2100], [7.9, 7.9, 0.2]) }), asRms),
  'The solved point (2,400 rpm, 11.2 N·m) is outside this map at the 48 V DC bus and 21.2 A rms Peak current. It was solved at 30 A rms, where it needs about 78 V; raise DC bus and Peak current in Solve → Analysis → Torque–speed map to include it.');
// No solved torque, no note.
assert.equal(solvedPointOutsideMap({ ...spm, torqueNm: 0 }), null);
assert.equal(solvedPointOutsideMap({ ...spm, torqueNm: Number.NaN }), null);
console.log('performance view: solved point outside the map ok');
