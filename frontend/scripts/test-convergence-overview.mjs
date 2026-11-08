import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The plain-language reading of the solver convergence report (convergenceOverview.ts).
const { convergenceOverview, convergenceAngleTable, convergenceChart, positionStatus } = await importTypeScriptModule(
  new URL('../src/public/convergenceOverview.ts', import.meta.url),
);

const summary = [
  { key: 'accuracy_plan', label: 'Accuracy plan', value: 'Standard' },
  { key: 'mesh_density', label: 'Mesh density', value: 'normal' },
  { key: 'mesh_elements', label: 'Mesh elements', value: '49812' },
];
const position = (index, { method = 'picard', iterations = 101, limit = 200, ratio = 0.94, reused = false, record = true, sweep = 'loaded' } = {}) => {
  const fraction = record ? iterations / limit : null;
  return {
    sweep, index, electrical_angle_deg: index * 7.5,
    stopping_ratio: !record || method === 'linear' ? null : ratio,
    iteration_fraction: fraction,
    review: Boolean(record && ((fraction ?? 0) >= 0.8 || (method !== 'linear' && ratio > 1))),
    record: record ? { method, iterations, max_iterations: limit, stage_iterations: [iterations], stage_iteration_cap: limit,
      solution_reused: reused, raw_max_residual: ratio * 0.01, scaled_residual: null, tolerance: 0.01,
      residual_definition: 'max steel elements', stopping_test: 'raw_max_residual <= tolerance' } : null,
  };
};
const report = (status, positions) => ({ schema_version: 'coilem.solver_convergence.v1', status, status_label: '', summary, methods: [], warnings: [], notes: [], positions });

// The 40p/36s robot-joint run: 96 positions, every one just under the limit.
const joint = Array.from({ length: 96 }, (_, index) => position(index, { iterations: index === 0 ? 102 : 101, ratio: index === 5 ? 0.978 : 0.94 }));
const ok = convergenceOverview(report('ok', joint));
assert.equal(ok.label, 'Converged');
assert.equal(ok.tone, 'ok');
assert.equal(ok.verdict, 'All 96 rotor positions converged, using at most 102 of 200 iterations.');
assert.equal(ok.stoppingRule, 'the steel changes by less than 1%');
assert.deepEqual(ok.facts.map((fact) => [fact.label, fact.value, fact.hint]), [
  ['Rotor positions', '96 of 96', undefined],
  ['Under the allowed error', '96 of 96', undefined],
  ['Most iterations', '102 of 200', 'Median 101'],
  ['Mesh', 'normal · 49,812 elements', 'Standard accuracy plan'],
]);

// One row per electrical angle with both sweeps side by side; nothing flagged.
const sweeps = [...Array.from({ length: 4 }, (_, index) => position(index, { sweep: 'no_load' })),
  ...Array.from({ length: 4 }, (_, index) => position(index, { iterations: 100 + index }))];
const table = convergenceAngleTable(report('ok', sweeps));
assert.equal(table.axis, 'angle');
assert.deepEqual(table.sweeps, ['no_load', 'loaded']);
assert.deepEqual(table.rows.map((row) => [row.label, row.cells.no_load.text, row.cells.loaded.text, row.flagged]), [
  ['0°', '101', '100', false], ['7.5°', '101', '101', false], ['15°', '101', '102', false], ['22.5°', '101', '103', false],
]);
assert.equal(table.rows[0].cells.loaded.title, 'Picard: 100 of 200 iterations, final error 94% of allowed');
const chart = convergenceChart(report('ok', sweeps));
assert.deepEqual(chart.series.map((item) => [item.sweep, item.points.map((point) => point.fraction)]), [
  ['no_load', [0.505, 0.505, 0.505, 0.505]], ['loaded', [0.5, 0.505, 0.51, 0.515]],
]);

// Each position's status follows the backend review rule.
assert.equal(positionStatus(position(0)).kind, 'converged');
assert.equal(positionStatus(position(0, { iterations: 160 })).kind, 'slow');
assert.equal(positionStatus(position(0, { ratio: 1.3, iterations: 200 })).kind, 'stopped_early');
assert.equal(positionStatus(position(0, { method: 'linear', iterations: 1 })).kind, 'linear');
assert.equal(positionStatus(position(0, { record: false })).kind, 'not_recorded');
assert.equal(convergenceAngleTable(report('review', [position(0, { ratio: 1.3, iterations: 200 })])).rows[0].cells.loaded.text,
  '200 · Stopped early, error 130%');

// Without angles, rows fall back to position numbers.
const unangled = convergenceAngleTable(report('ok', [{ ...position(0), electrical_angle_deg: null }]));
assert.equal(unangled.axis, 'position');
assert.equal(unangled.rows[0].label, 'Position 1');

// Positions that stopped above the allowed error or ran near the limit are named.
const review = convergenceOverview(report('review', [
  position(0), position(1, { ratio: 1.3 }), position(2, { iterations: 170 }), position(3, { ratio: 0.5 }),
]));
assert.equal(review.label, 'Needs review');
assert.equal(review.tone, 'review');
assert.match(review.verdict, /^2 of 4 rotor positions need a look: 1 stopped above the allowed error; 1 used 80% or more of the iteration limit\./);
assert.match(review.verdict, /Check the waveforms at those angles\.$/);
assert.deepEqual(review.facts.find((fact) => fact.key === 'under_error'), { key: 'under_error', label: 'Under the allowed error', value: '3 of 4', hint: '1 stopped early' });
assert.deepEqual(convergenceAngleTable(report('review', [position(0), position(1, { ratio: 1.3 })])).rows.map((row) => row.flagged), [false, true]);

// Reused fields are counted, not treated as solves.
const reused = convergenceOverview(report('ok', [position(0), position(1, { reused: true, iterations: 40 })]));
assert.equal(reused.verdict, 'All 2 rotor positions converged (1 reused), using at most 101 of 200 iterations.');
assert.deepEqual([reused.facts[0].value, reused.facts[0].hint], ['2 of 2', '1 reused an earlier field']);
assert.equal(reused.facts.find((fact) => fact.key === 'iterations').value, '101 of 200');
assert.equal(convergenceAngleTable(report('ok', [position(1, { reused: true, iterations: 40 })])).rows[0].cells.loaded.text, '40 · reused');

// Missing records cannot be checked and say so.
const partial = convergenceOverview(report('partial', [position(0), position(1, { record: false })]));
assert.equal(partial.label, 'Incomplete records');
assert.match(partial.verdict, /^1 position has no convergence record, so it can't be checked\./);

// Linear materials need no iteration.
const linear = convergenceOverview(report('ok', [position(0, { method: 'linear', iterations: 1 })]));
assert.equal(linear.label, 'Linear solves');
assert.equal(linear.facts.some((fact) => fact.key === 'under_error'), false);
assert.deepEqual(convergenceChart(report('ok', [position(0, { method: 'linear', iterations: 1 })])).series, []);

// No report, or an old one without residuals, never earns a green badge.
for (const missing of [undefined, null, report('not_recorded', [])]) {
  const view = convergenceOverview(missing);
  assert.equal(view.label, 'Not recorded');
  assert.equal(view.tone, 'muted');
  assert.match(view.verdict, /cannot be recovered from iteration counts/);
  assert.deepEqual(view.facts, []);
}

console.log('convergence overview checks passed');
