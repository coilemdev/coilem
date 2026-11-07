import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The plain-language reading of the solver convergence report (convergenceOverview.ts).
const { convergenceOverview } = await importTypeScriptModule(
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
assert.equal(ok.verdict, 'All 96 rotor positions converged. The hardest finished at 98% of the allowed error, using 102 of 200 iterations.');
assert.deepEqual(ok.facts.map((fact) => [fact.label, fact.value]), [
  ['Rotor positions checked', '96 of 96'],
  ['Worst remaining error', '98% of allowed'],
  ['Iterations', '102 of 200 allowed'],
  ['Mesh', 'normal · 49,812 elements'],
]);

// Positions that stopped above the allowed error or ran near the limit are named.
const review = convergenceOverview(report('review', [
  position(0), position(1, { ratio: 1.3 }), position(2, { iterations: 170 }), position(3, { ratio: 0.5 }),
]));
assert.equal(review.label, 'Needs review');
assert.equal(review.tone, 'review');
assert.match(review.verdict, /^2 of 4 rotor positions need a look: 1 stopped above the allowed error; 1 used 80% or more of the iteration limit\./);
assert.match(review.verdict, /spike at those angles/);
assert.equal(review.facts.find((fact) => fact.key === 'worst_error').value, '130% of allowed');

// Reused fields are counted, not treated as solves.
const reused = convergenceOverview(report('ok', [position(0), position(1, { reused: true, iterations: 40 })]));
assert.match(reused.verdict, /^All 2 rotor positions converged \(1 reused a field already solved for the same inputs\)\./);
assert.equal(reused.facts[0].value, '2 of 2 · 1 reused');
assert.equal(reused.facts.find((fact) => fact.key === 'iterations').value, '101 of 200 allowed');

// Missing records cannot be checked and say so.
const partial = convergenceOverview(report('partial', [position(0), position(1, { record: false })]));
assert.equal(partial.label, 'Incomplete records');
assert.match(partial.verdict, /^1 position has no convergence record, so it cannot be checked\./);

// Linear materials need no iteration.
const linear = convergenceOverview(report('ok', [position(0, { method: 'linear', iterations: 1 })]));
assert.equal(linear.label, 'Linear solves');
assert.equal(linear.facts.some((fact) => fact.key === 'worst_error'), false);

// No report, or an old one without residuals, never earns a green badge.
for (const missing of [undefined, null, report('not_recorded', [])]) {
  const view = convergenceOverview(missing);
  assert.equal(view.label, 'Not recorded');
  assert.equal(view.tone, 'muted');
  assert.match(view.verdict, /cannot be recovered from iteration counts/);
  assert.deepEqual(view.facts, []);
}

console.log('convergence overview checks passed');
