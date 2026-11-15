import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { normalizeComparisonResult, previousCompletedRun, compareRunTiming, compareRunLosses } = await importTypeScriptModule(new URL('../src/public/runComparison.ts', import.meta.url));
const { inputChanges } = await importTypeScriptModule(new URL('../src/public/runInputChanges.ts', import.meta.url));
const emptyTorque = { electrical_angle_deg: [], torque_Nm: [] };
const emptyEmf = { electrical_angle_deg: [], phase_a_V: [], phase_b_V: [], phase_c_V: [] };

const { compareRunDq } = await importTypeScriptModule(new URL('../src/public/dqComparison.ts', import.meta.url));
const dqRecord = { transform: 'amplitude_invariant_park', current_angle_convention: 'q_axis_gamma_flux_weakening_positive',
  d_axis_source: 'no_load_flux_linkage', i_d_A: -10, i_q_A: 20, current_angle_deg: 26.565,
  lambda_d_Wb: 0.01, lambda_q_Wb: 0.004, lambda_pm_Wb: 0.011,
  apparent_L_d_H: 0.0001, apparent_L_q_H: 0.0002, torque_dq_Nm: 1.44,
  status: 'qualified', status_reason: 'Stored flux qualification.',
  inductance_status: 'experimental', inductance_status_reason: 'Stored inductance uncertainty.' };
const dqRun = (record) => ({ summary: { dq_flux_linkage: record } });
const dqRow = (comparison, key) => comparison.rows.find(row => row.key === key);
const dqComparison = compareRunDq([dqRun(dqRecord), dqRun({ ...dqRecord, i_d_A: -15, apparent_L_d_H: 0.00015 })]);
assert.deepEqual(dqRow(dqComparison, 'apparent_L_d_H').cells.map(cell => cell.value), [0.1, 0.15], 'H → mH');
assert.deepEqual(dqRow(dqComparison, 'lambda_d_Wb').cells.map(cell => cell.value), [10, 10], 'Wb → mWb');
assert.deepEqual(dqRow(dqComparison, 'i_d_A').cells.map(cell => cell.value), [-10, -15], 'currents keep their signs and peak units');
assert.deepEqual(dqRow(dqComparison, 'apparent_L_d_H').cells[0].status, { status: 'experimental', reason: 'Stored inductance uncertainty.' });
assert.deepEqual(dqRow(dqComparison, 'lambda_d_Wb').cells[0].status, { status: 'qualified', reason: 'Stored flux qualification.' });
assert.equal(dqRow(dqComparison, 'i_d_A').cells[0].status, undefined, 'flux status is not a current qualification');
assert.equal(dqRow(dqComparison, 'apparent_L_d_H').comparable[1], true);

const differentReference = { ...dqRecord, d_axis_source: 'applied_current_angle', apparent_L_d_H: null, lambda_pm_Wb: null };
const unavailableDq = { ...dqRecord, status: 'unavailable', status_reason: 'Stored failure.', inductance_status: 'unavailable' };
const openDq = { ...dqRecord, i_d_A: 0, i_q_A: 0, current_angle_deg: null, apparent_L_d_H: null, apparent_L_q_H: null, torque_dq_Nm: 0, lambda_q_Wb: 0 };
const sixDq = compareRunDq([dqRun(dqRecord), dqRun(differentReference), dqRun(null), dqRun(unavailableDq), dqRun(openDq), dqRun({ ...dqRecord, lambda_d_Wb: 0 })]);
assert.deepEqual(sixDq.references.slice(0, 3), ['No-load flux linkage', 'Applied current angle', 'Not recorded']);
assert.deepEqual(dqRow(sixDq, 'lambda_d_Wb').comparable, [true, false, false, false, true, true], 'comparability is pairwise with the pinned baseline');
assert.equal(dqRow(sixDq, 'torque_dq_Nm').comparable[1], true, 'torque is frame independent under the same transform and sign convention');
assert.equal(dqRow(sixDq, 'lambda_d_Wb').cells[3].value, null, 'an unavailable status overrides any stored number');
assert.equal(dqRow(sixDq, 'torque_dq_Nm').cells[3].value, null, 'torque derived from unavailable flux linkage is also unavailable');
assert.equal(dqRow(sixDq, 'lambda_d_Wb').cells[3].status.reason, 'Stored failure.');
assert.equal(dqRow(sixDq, 'apparent_L_d_H').cells[4].missing, 'Not applicable', 'open-circuit Ld is not a zero inductance');
assert.equal(dqRow(sixDq, 'torque_dq_Nm').cells[4].missing, 'Not applicable');
assert.equal(dqRow(sixDq, 'i_d_A').cells[4].value, 0, 'zero applied current is valid');
assert.equal(dqRow(sixDq, 'lambda_q_Wb').cells[4].value, 0, 'zero flux linkage is valid');
assert.equal(dqRow(sixDq, 'lambda_d_Wb').cells[5].value, 0);
assert.equal(dqRow(sixDq, 'lambda_d_Wb').cells[2].missing, 'Not recorded');
assert.match(sixDq.notes[1], /references differ/);
assert.equal(sixDq.notes[5], null);
assert.equal(compareRunDq([dqRun(null), { summary: {} }]).recorded, false);
assert.equal(compareRunDq([]).recorded, false);
const missingBaseline = compareRunDq([dqRun(null), dqRun(dqRecord)]);
assert.equal(dqRow(missingBaseline, 'i_q_A').comparable[1], false);
assert.match(missingBaseline.notes[1], /recorded baseline/);
const repinnedDq = compareRunDq([dqRun(differentReference), dqRun(dqRecord), dqRun({ ...differentReference, i_d_A: -20 })]);
assert.deepEqual(dqRow(repinnedDq, 'i_d_A').comparable, [true, false, true]);
for (const override of [{ transform: 'other' }, { current_angle_convention: 'other' }, { transform: undefined }]) {
  const result = compareRunDq([dqRun(dqRecord), dqRun({ ...dqRecord, ...override })]);
  assert.equal(dqRow(result, 'torque_dq_Nm').comparable[1], false);
  assert.match(result.notes[1], /convention/);
}
for (const override of [{ d_axis_source: undefined }, { d_axis_source: 'future_reference' }]) {
  assert.equal(dqRow(compareRunDq([dqRun(dqRecord), dqRun({ ...dqRecord, ...override })]), 'lambda_d_Wb').comparable[1], false);
}
for (const value of [null, undefined, NaN, Infinity, -0.1, 0]) {
  assert.equal(dqRow(compareRunDq([dqRun({ ...dqRecord, apparent_L_d_H: value })]), 'apparent_L_d_H').cells[0].value, null);
}
const legacyDq = { ...dqRecord, status: undefined, status_reason: undefined, inductance_status: undefined, inductance_status_reason: undefined };
const legacyComparison = compareRunDq([dqRun(legacyDq)]);
assert.equal(dqRow(legacyComparison, 'lambda_d_Wb').cells[0].status.status, 'experimental', 'historical results are not requalified by current policy');
assert.equal(dqRow(legacyComparison, 'apparent_L_d_H').cells[0].status.status, 'experimental');
assert.equal(dqRecord.i_d_A, -10, 'comparison does not mutate saved records');
console.log('D/q comparison preserves recorded units, signs and statuses and gates deltas by the pinned reference.');

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

const fullLoss = { efficiency_pct: 90, efficiency_status: 'experimental', efficiency_status_reason: 'Recorded efficiency scope.',
  input_power_W: 1000, shaft_power_W: 900, shaft_torque_Nm: 2.86,
  copper_loss_W: 50, copper_active_loss_W: 30, copper_end_winding_loss_W: 20,
  iron_loss_W: 40, iron_hysteresis_loss_W: 40, iron_eddy_loss_W: 0, iron_loss_status: 'experimental', iron_loss_status_reason: 'Recorded iron scope.',
  mechanical_loss_W: 10, total_loss_W: 100 };
const withLoss = loss => ({ ...torqueOnly, summary: { loss_breakdown: loss,
  winding_resistance: { status: 'qualified', status_reason: 'Recorded resistance scope.' } } });
const lossA = withLoss(fullLoss), lossB = withLoss({ ...fullLoss, efficiency_pct: 92, copper_loss_W: 40, total_loss_W: 80 });
const lossesOriginal = JSON.stringify([lossA, lossB]);
const lossRows = compareRunLosses(lossA, lossB);
assert.equal(lossRows.find(row => row.key === 'efficiency').after.value, 92);
assert.equal(lossRows.find(row => row.key === 'efficiency').before.reason, 'Recorded efficiency scope.');
assert.equal(lossRows.find(row => row.key === 'copper').before.status, 'qualified');
assert.equal(lossRows.find(row => row.key === 'eddy').before.value, 0);
assert.equal(lossRows.find(row => row.key === 'total').after.value, 80, 'compare reads stored totals without summing component fields');
assert.equal(lossRows.some(row => row.key === 'subtotal'), false);
assert.equal(JSON.stringify([lossA, lossB]), lossesOriginal);
assert.equal(compareRunLosses(torqueOnly, torqueOnly), null);
assert.equal(compareRunLosses(torqueOnly, lossB).find(row => row.key === 'efficiency').before.missing, 'Not recorded');
const partialLoss = { ...fullLoss, iron_loss_W: null, iron_hysteresis_loss_W: null, iron_eddy_loss_W: null,
  iron_loss_status: 'unavailable', iron_loss_status_reason: 'Requires a full electrical cycle.',
  efficiency_pct: null, efficiency_status: 'unavailable', total_loss_W: 60, shaft_power_W: 940 };
const partialRows = compareRunLosses(withLoss(partialLoss), lossB);
assert.equal(partialRows.find(row => row.key === 'total').before.value, null);
assert.equal(partialRows.find(row => row.key === 'subtotal').before.value, 60);
assert.equal(partialRows.find(row => row.key === 'subtotal').after.missing, 'Not applicable');
assert.equal(partialRows.find(row => row.key === 'efficiency').before.missing, 'Unavailable');
assert.equal(partialRows.find(row => row.key === 'shaft').before.partial, true);
assert.equal(partialRows.find(row => row.key === 'shaft').comparable, false, 'partial and complete shaft outputs have different bases');
const bothPartial = compareRunLosses(withLoss(partialLoss), withLoss({ ...partialLoss, total_loss_W: 70 }));
assert.equal(bothPartial.some(row => row.key === 'total'), false);
assert.equal(bothPartial.find(row => row.key === 'subtotal').comparable, true);
assert.equal(compareRunLosses(withLoss({ ...fullLoss, copper_end_winding_loss_W: NaN }), lossB).find(row => row.key === 'copper_end').before.value, null);
console.log('Loss comparisons preserve archived statuses and zeros, distinguish full totals from known subtotals, and suppress mixed-basis shaft deltas.');

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
assert.equal(JSON.stringify([left, right]), original, 'diffs must not rewrite saved input snapshots');
assert.deepEqual(inputChanges(left, structuredClone(left)), []);
assert.deepEqual(inputChanges({ config: { rotor: { a: 1, b: 2 } } }, { config: { rotor: { b: 2, a: 1 } } }), []);
const legacy = inputChanges({ config: { solve_params: { winding_temperature_C: null } } }, { config: { solve_params: { winding_temperature_C: 20, magnet_temperature_C: 20 } } });
assert.equal(legacy.find(row => row.path.endsWith('winding_temperature_C')).before, 'Not set');
assert.equal(legacy.find(row => row.path.endsWith('winding_temperature_C')).missing, false);
assert.equal(legacy.find(row => row.path.endsWith('magnet_temperature_C')).before, 'Not recorded');
assert.equal(legacy.find(row => row.path.endsWith('magnet_temperature_C')).missing, true);
// A run without a config snapshot is reported by the table notice, not leaf by leaf.
assert.deepEqual(inputChanges(null, { config: { winding: { coil_map: [] } } }), []);
assert.deepEqual(inputChanges({ config: null, solver: 'magneto2d' }, { config: left.config, solver: 'magneto2d' }), []);
assert.equal(inputChanges({ config: { winding: { coil_map: [0, 1] } } }, { config: { winding: { coil_map: [1, 0] } } }).length, 2);
// Entries both runs recorded, but only one has, read 'Not set' and are not counted as missing.
const grown = inputChanges({ config: { winding: { coil_map: [0, 1] } } }, { config: { winding: { coil_map: [0, 1, 2, 3] } } });
assert.deepEqual(grown.map(row => [row.path, row.before, row.after, row.missing]),
  [['config.winding.coil_map.3', 'Not set', '2', false], ['config.winding.coil_map.4', 'Not set', '3', false]]);
for (const steels of [undefined, {}]) {
  const added = inputChanges({ config: { materials: { stator_steel: 'M19', ...(steels ? { custom_steels: steels } : {}) } } },
    { config: { materials: { stator_steel: 'Mine', custom_steels: { Mine: { density_kg_m3: 7650 } } } } });
  assert.equal(added.find(row => row.path === 'config.materials.custom_steels.Mine.density_kg_m3').before, 'Not set');
  assert.equal(added.filter(row => row.missing).length, 0);
}
// An unset section is compared field by field, never printed as one JSON cell.
const envelope = inputChanges({ config: { torque_speed_analysis: null } }, { config: { torque_speed_analysis: { preset: 'preview', speeds_rpm: [1000, 2000] } } });
assert.deepEqual(envelope.map(row => [row.path, row.before, row.after, row.missing]), [
  ['config.torque_speed_analysis.preset', 'Not set', 'preview', false],
  ['config.torque_speed_analysis.speeds_rpm.1', 'Not set', '1000', false],
  ['config.torque_speed_analysis.speeds_rpm.2', 'Not set', '2000', false]]);
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
// Unnamed designs share a slug; a different design (scope) is never the previous run.
const scoped = { ...current, design_scope: 'design-1' };
assert.equal(previousCompletedRun([run('other-design', '40', { design_scope: 'design-2' }), run('same', '20', { design_scope: 'design-1' })], scoped).run_id, 'same');
assert.equal(previousCompletedRun([run('unscoped', '40')], scoped).run_id, 'unscoped', 'runs from before setup scopes stay comparable');
assert.equal(previousCompletedRun(records.filter(row => row.project_slug === 'other'), current), undefined);
assert.equal(previousCompletedRun(records, { ...current, completed_at: null }), undefined);
assert.equal(previousCompletedRun([current], current), undefined);
console.log('Saved input diffs preserve units, missing historical values and profile versions; previous-run selection stays in the completed project history.');

const { initialComparisonSelection, addComparisonRun, removeComparisonRun, pinComparisonBaseline,
  selectComparisonRun, reconcileComparisonSelection, compareMultipleLosses, compareMultipleTiming } = await importTypeScriptModule(new URL('../src/public/multiRunComparison.ts', import.meta.url));
const { multipleInputChanges, recordedInputValue } = await importTypeScriptModule(new URL('../src/public/runInputChanges.ts', import.meta.url));
let selection = initialComparisonSelection('baseline', 'candidate');
for (const key of ['third', 'fourth', 'fifth', 'sixth']) selection = addComparisonRun(selection, key);
assert.equal(addComparisonRun(selection, 'seventh'), selection, 'at most six distinct runs');
assert.equal(selectComparisonRun(selection, 'run-b', 'baseline'), selection, 'a run cannot occupy two columns');
assert.equal(removeComparisonRun(selection, 'run-a'), selection, 'the pinned baseline cannot be removed');
selection = pinComparisonBaseline(selection, 'run-c');
selection = removeComparisonRun(selection, 'run-a');
assert.equal(selection.baselineId, 'run-c');
assert.deepEqual(selection.slots.map(slot => slot.id), ['run-b', 'run-c', 'run-d', 'run-e', 'run-f']);
assert.equal(selection.slots.find(slot => slot.id === 'run-c').key, 'third');
selection = reconcileComparisonSelection(selection, new Set(['candidate', 'fourth', 'fifth', 'sixth']));
assert.equal(selection.slots.find(slot => slot.id === 'run-c').key, '', 'a missing pinned run is never silently replaced');
const unchangedPoint = structuredClone(left);
unchangedPoint.config.solve_params.current_amplitude_convention = 'peak';
const multiInputs = multipleInputChanges([left, right, unchangedPoint, null]);
assert.deepEqual(multiInputs.find(row => row.path === 'config.solve_params.current_amplitude_A').values,
  ['20 A rms', '30 A rms', '20 A peak', 'Not recorded']);
assert.equal(multiInputs.find(row => row.path === 'config.rotor.magnet_thickness_mm').knownChanged, true, 'a missing third record does not hide known changes');
assert.equal(recordedInputValue({ config: { rotor: { test: null } } }, 'config.rotor.test'), 'Not set');
const multipleLosses = compareMultipleLosses([withLoss(fullLoss), lossB, withLoss(partialLoss), torqueOnly]);
assert.deepEqual(multipleLosses.find(row => row.key === 'total').cells.map(cell => cell.missing ?? cell.value),
  [fullLoss.total_loss_W, lossB.summary.loss_breakdown.total_loss_W, 'Unavailable', 'Not recorded']);
assert.deepEqual(multipleLosses.find(row => row.key === 'subtotal').cells.map(cell => cell.missing ?? cell.value),
  ['Not applicable', 'Not applicable', partialLoss.total_loss_W, 'Not recorded']);
assert.deepEqual(multipleLosses.find(row => row.key === 'shaft').comparable, [false, true, false, false]);
const partialBaseline = compareMultipleLosses([withLoss(partialLoss), withLoss({ ...partialLoss, total_loss_W: 70 }), lossB]);
assert.deepEqual(partialBaseline.find(row => row.key === 'shaft').comparable, [false, true, false]);
const multipleTiming = compareMultipleTiming([torqueOnly, timedA, timedB]);
assert.deepEqual(multipleTiming.recorded, [false, true, true]);
assert.deepEqual(multipleTiming.rows.find(row => row.key === 'elapsed').values, [null, 60, 90]);
assert.deepEqual(multipleTiming.rows.find(row => row.key === 'meshes_rotated').values, [null, 0, 8]);
assert.equal(JSON.stringify([left, right]), original, 'multi-run input tables preserve archived inputs');
console.log('Multi-run comparison preserves pinned identities, the six-run limit, units, missing evidence, partial loss bases and elapsed timings.');
