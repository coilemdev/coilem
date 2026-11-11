import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The plain reading of a solve's time breakdown (solveTime.ts).
const { formatSeconds, isSolveTimeBreakdown, solveTimeView } = await importTypeScriptModule(
  new URL('../src/public/solveTime.ts', import.meta.url),
);

assert.equal(formatSeconds(0.0431), '0.043 s');
assert.equal(formatSeconds(1.346), '1.35 s');
assert.equal(formatSeconds(12.776), '12.8 s');
assert.equal(formatSeconds(155.1), '155 s');
assert.equal(formatSeconds(7200), '120 min');
assert.equal(formatSeconds(Number.NaN), '—');
assert.equal(formatSeconds(-1), '0.000 s');

// A 72-position outrunner solve: 42 meshes generated, meshing is most of the wait.
const breakdown = {
  schema_version: 'coilem.solve_time_breakdown.v1',
  elapsed_s: 206.1,
  elapsed_steps: [
    { key: 'meshing', label: 'Meshing', detail: 'until the last mesh was ready', seconds: 155.1 },
    { key: 'field_solve', label: 'Field solve', detail: 'from then until the last position was solved', seconds: 43.7 },
    { key: 'packaging', label: 'Packaging results', detail: 'field frames and the result, after the last solve', seconds: 7.3 },
  ],
  steps: [
    {
      key: 'meshing', label: 'Meshing', work_s: 1039.42, started_s: 1.7, ended_s: 154.6,
      parts: [
        { label: 'Build a mesh', indent: 0, count: 42, total_s: 667.7, mean_s: 15.898, max_s: 27.3 },
        { label: 'Gmsh generates the mesh', indent: 1, count: 42, total_s: 536.6, mean_s: 12.776, max_s: 23.3 },
        { label: 'Hash each mesh for the run record', indent: 0, count: 72, total_s: 339.6, mean_s: 4.717, max_s: 8.97 },
      ],
    },
  ],
  counts: { meshes_built: 42, meshes_rotated: 30, solves: 144, field_frames: 72 },
};
assert.equal(isSolveTimeBreakdown(breakdown), true);
const view = solveTimeView(breakdown);
assert.equal(view.elapsed, '206 s');
assert.deepEqual(view.segments.map(segment => [segment.key, segment.text, segment.shareText]), [
  ['meshing', '155 s', '75%'],
  ['field_solve', '43.7 s', '21%'],
  ['packaging', '7.30 s', '4%'],
]);
// The three steps partition the elapsed time.
assert.ok(Math.abs(view.segments.reduce((sum, segment) => sum + segment.share, 0) - 1) < 1e-3);
assert.deepEqual(view.facts, [
  { key: 'meshes', label: 'Meshes', value: '42 generated, 30 rotated from them' },
  { key: 'solves', label: 'Field solves', value: '144' },
  { key: 'frames', label: 'Field frames', value: '72' },
]);
const [meshing] = view.steps;
assert.equal(meshing.summary, '1039 s of work across workers, between 1.70 s and 155 s into the solve');
assert.deepEqual(meshing.rows.map(row => [row.label, row.indent, row.count, row.total, row.mean, row.max]), [
  ['Build a mesh', 0, '42', '668 s', '15.9 s', '27.3 s'],
  ['Gmsh generates the mesh', 1, '42', '537 s', '12.8 s', '23.3 s'],
  ['Hash each mesh for the run record', 0, '72', '340 s', '4.72 s', '8.97 s'],
]);
// Row bars are relative to the step's largest top-level stage.
assert.equal(meshing.rows[0].weight, 1);
assert.ok(Math.abs(meshing.rows[2].weight - 339.6 / 667.7) < 1e-9);

// A solve with every mesh cached has no meshing wait and no meshes line beyond rotations.
const cached = solveTimeView({ ...breakdown, elapsed_steps: [
  { key: 'meshing', label: 'Meshing', detail: '', seconds: 0 },
  { key: 'field_solve', label: 'Field solve', detail: '', seconds: 40 },
  { key: 'packaging', label: 'Packaging results', detail: '', seconds: 10 },
], elapsed_s: 50, counts: { meshes_built: 6, meshes_rotated: 0, solves: 12, field_frames: 6 } });
assert.equal(cached.segments[0].shareText, '0%');
assert.equal(cached.facts[0].value, '6 generated');

// Runs solved before the breakdown existed, or with an unknown layout, show nothing.
assert.equal(solveTimeView(null), null);
assert.equal(solveTimeView(undefined), null);
assert.equal(solveTimeView({ schema_version: 'coilem.solve_time_breakdown.v2', elapsed_s: 1, steps: [], elapsed_steps: [] }), null);
assert.equal(isSolveTimeBreakdown({ schema_version: 'coilem.solve_time_breakdown.v1', elapsed_s: 1 }), false);

console.log('solve time view: ok');
