import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { normalizeComparisonResult, previousCompletedRun, compareRunTiming } = await importTypeScriptModule(new URL('../src/public/runComparison.ts', import.meta.url));
const { inputChanges, recordedSetupLabel } = await importTypeScriptModule(new URL('../src/public/runInputChanges.ts', import.meta.url));
const emptyTorque = { electrical_angle_deg: [], torque_Nm: [] };
const emptyEmf = { electrical_angle_deg: [], phase_a_V: [], phase_b_V: [], phase_c_V: [] };

// The old comparison route emits {} for analyses with no CSV rows. Opening
// Previous runs must not hand undefined angle arrays to the comparison view.
for (const missing of [undefined, null, {}]) {
  const source = { summary: {}, solve_metadata: {}, torque_waveform: missing, back_emf_waveform: missing };
  const normalized = normalizeComparisonResult(source);
  assert.deepEqual(normalized.torque_waveform, emptyTorque);
  assert.deepEqual(normalized.back_emf_waveform, emptyEmf);
  assert.equal(normalized.cogging_torque_waveform, null);
  assert.equal(source.torque_waveform, missing, 'normalization must not change stored input');
}
const torqueOnly = { summary: {}, solve_metadata: {}, torque_waveform: { electrical_angle_deg: [0, 30], torque_Nm: [4.2, 4.3] }, back_emf_waveform: {} };
assert.deepEqual(normalizeComparisonResult(torqueOnly).torque_waveform, torqueOnly.torque_waveform);
assert.deepEqual(normalizeComparisonResult(torqueOnly).back_emf_waveform, emptyEmf);
assert.deepEqual(normalizeComparisonResult({ ...torqueOnly, torque_waveform: emptyTorque, back_emf_waveform: emptyEmf }).torque_waveform, emptyTorque);
console.log('Saved-run comparison preserves samples and handles unrequested/legacy waveforms.');

const cogging = { electrical_angle_deg: [0, 10, 20, 30], torque_Nm: [0, 0.002, -0.002, 0] };
assert.deepEqual(normalizeComparisonResult({ ...torqueOnly, cogging_torque_waveform: cogging }).cogging_torque_waveform, cogging);
for (const malformed of [null, {}, { electrical_angle_deg: [0, 30], torque_Nm: [1] },
  { electrical_angle_deg: [0, 30], torque_Nm: [0, NaN] }, { electrical_angle_deg: [0, Infinity], torque_Nm: [0, 1] }]) {
  assert.equal(normalizeComparisonResult({ ...torqueOnly, cogging_torque_waveform: malformed }).cogging_torque_waveform, null);
}

const timed = (elapsed, stages, counts) => ({ ...torqueOnly, solve_metadata: {
  mesh_element_count: 1000, rotor_positions: 48,
  time_breakdown: { schema_version: 'coilem.solve_time_breakdown.v1', elapsed_s: elapsed,
    elapsed_steps: ['meshing', 'field_solve', 'packaging'].map((key, index) => ({ key, seconds: stages[index] })),
    steps: [{ key: 'meshing', work_s: 99999, parts: [{ total_s: 99999 }] }], counts },
} });
const timedA = timed(60, [30, 20, 10], { meshes_built: 42, meshes_rotated: 0, solves: 144, field_frames: 72 });
const timedB = timed(90, [45, 30, 15], { meshes_built: 48, meshes_rotated: 8, solves: 192, field_frames: 96 });
const timing = compareRunTiming(timedA, timedB);
assert.equal(timing.recordedBefore, true);
assert.deepEqual(timing.rows.filter(row => row.group === 'Elapsed time').map(row => [row.before, row.after]), [[60, 90], [30, 45], [20, 30], [10, 15]]);
assert.deepEqual(timing.rows.find(row => row.key === 'meshes_rotated'), { key: 'meshes_rotated', label: 'Meshes rotated', group: 'Work performed', unit: '', before: 0, after: 8 });
assert.equal(timing.rows.find(row => row.key === 'solves').after, 192);
const missingTime = compareRunTiming(torqueOnly, timedB);
assert.equal(missingTime.recordedBefore, false);
assert.equal(missingTime.rows.find(row => row.key === 'meshing').before, null);
assert.equal(missingTime.rows.find(row => row.key === 'meshes_built').before, null);
const invalid = structuredClone(timedA);
invalid.solve_metadata.time_breakdown.elapsed_steps[0].seconds = -1;
invalid.solve_metadata.time_breakdown.counts.solves = NaN;
assert.equal(compareRunTiming(invalid, timedB).rows.find(row => row.key === 'meshing').before, null);
assert.equal(compareRunTiming(invalid, timedB).rows.find(row => row.key === 'solves').before, null);
assert.equal(compareRunTiming(torqueOnly, torqueOnly).rows.length, 0);
assert.equal(compareRunTiming({ ...timedA, solve_metadata: { time_breakdown: { schema_version: 'unknown' } } }, torqueOnly).recordedBefore, false);
console.log('Cogging samples remain unmodified; timing comparisons use elapsed partitions, preserve zero counts and leave missing/invalid data unrecorded.');

const left = { config: { topology: 'SPM', rotor: { magnet_thickness_mm: 4 }, winding: { turns_per_coil: 20 },
  materials: { magnet_grade: 'N42' }, solve_params: { current_amplitude_A: 20, current_amplitude_convention: 'rms', mesh_density: 'normal' },
  solve_options: { cogging_torque: false } }, run_setup: { id: 'setup-1', name: 'Report', version: 1 } };
const right = structuredClone(left);
right.config.rotor.magnet_thickness_mm = 4.5;
right.config.winding.turns_per_coil = 24;
right.config.materials.magnet_grade = 'N52';
right.config.solve_params.current_amplitude_A = 30;
right.config.solve_params.mesh_density = 'fine';
right.config.solve_options.cogging_torque = true;
right.run_setup.version = 2;
const original = JSON.stringify([left, right]);
const changes = inputChanges(left, right);
assert.equal(changes.length, 7);
assert.deepEqual(new Set(changes.map(row => row.group)), new Set(['Geometry', 'Materials', 'Analyses', 'Operating point', 'Accuracy and solver', 'Winding', 'Saved setup']));
assert.deepEqual(changes.find(row => row.path === 'config.rotor.magnet_thickness_mm'), {
  path: 'config.rotor.magnet_thickness_mm', group: 'Geometry', label: 'Magnet thickness', before: '4 mm', after: '4.5 mm', missing: false,
});
assert.equal(changes.find(row => row.path === 'config.solve_params.current_amplitude_A').before, '20 A rms');
assert.equal(changes.find(row => row.path === 'config.solve_options.cogging_torque').before, 'Off');
assert.equal(recordedSetupLabel(left), 'Report · v1');
assert.equal(recordedSetupLabel(null), 'Not recorded');
assert.equal(JSON.stringify([left, right]), original, 'diffs must not rewrite saved input snapshots');
assert.deepEqual(inputChanges(left, structuredClone(left)), []);
assert.deepEqual(inputChanges({ config: { rotor: { a: 1, b: 2 } } }, { config: { rotor: { b: 2, a: 1 } } }), []);
const legacy = inputChanges({ config: { solve_params: { winding_temperature_C: null } } }, { config: { solve_params: { winding_temperature_C: 20, magnet_temperature_C: 20 } } });
assert.equal(legacy.find(row => row.path.endsWith('winding_temperature_C')).before, 'Not set');
assert.equal(legacy.find(row => row.path.endsWith('winding_temperature_C')).missing, false);
assert.equal(legacy.find(row => row.path.endsWith('magnet_temperature_C')).before, 'Not recorded');
assert.equal(legacy.find(row => row.path.endsWith('magnet_temperature_C')).missing, true);
assert.equal(inputChanges(null, { config: { winding: { coil_map: [] } } })[0].before, 'Not recorded');
assert.equal(inputChanges({ config: { winding: { coil_map: [0, 1] } } }, { config: { winding: { coil_map: [1, 0] } } }).length, 2);
assert.deepEqual(inputChanges(null, null), []);

const current = { project_slug: 'motor', run_id: 'current', status: 'complete', solver_name: 'magneto2d-test', completed_at: '2026-11-14T12:00:00Z' };
const run = (run_id, minutes, extra = {}) => ({ ...current, run_id, completed_at: `2026-11-14T11:${minutes}:00Z`, ...extra });
const records = [run('older', '00'), run('future', '59', { completed_at: '2026-11-14T13:00:00Z' }),
  run('other', '59', { project_slug: 'other' }), run('failed', '58', { status: 'failed' }),
  run('running', '57', { status: 'running' }), run('elmer', '56', { solver_name: 'Elmer' }),
  run('missing-time', '55', { completed_at: null }), run('previous', '30'), current];
const order = records.map(row => row.run_id);
assert.equal(previousCompletedRun(records, current).run_id, 'previous');
assert.deepEqual(records.map(row => row.run_id), order, 'selection must not reorder saved run records');
assert.equal(previousCompletedRun(records.filter(row => row.project_slug === 'other'), current), undefined);
assert.equal(previousCompletedRun(records, { ...current, completed_at: null }), undefined);
assert.equal(previousCompletedRun([current], current), undefined);
console.log('Saved input diffs preserve units, missing historical values and profile versions; previous-run selection stays in the completed project history.');
