import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { normalizeComparisonResult, previousCompletedRun } = await importTypeScriptModule(new URL('../src/public/runComparison.ts', import.meta.url));
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
  assert.equal(source.torque_waveform, missing, 'normalization must not change stored input');
}
const torqueOnly = { summary: {}, solve_metadata: {}, torque_waveform: { electrical_angle_deg: [0, 30], torque_Nm: [4.2, 4.3] }, back_emf_waveform: {} };
assert.deepEqual(normalizeComparisonResult(torqueOnly).torque_waveform, torqueOnly.torque_waveform);
assert.deepEqual(normalizeComparisonResult(torqueOnly).back_emf_waveform, emptyEmf);
assert.deepEqual(normalizeComparisonResult({ ...torqueOnly, torque_waveform: emptyTorque, back_emf_waveform: emptyEmf }).torque_waveform, emptyTorque);
console.log('Saved-run comparison preserves samples and handles unrequested/legacy waveforms.');

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
