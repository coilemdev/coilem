import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  EMPTY_PUBLIC_SOLVE_PROGRESS_BAR,
  PUBLIC_SOLVE_MESH_SHARE,
  nextPublicSolveProgressBar,
  publicSolveMeshFraction,
  publicSolvePositionFraction,
} = await importTypeScriptModule(new URL('../src/public/solveProgress.ts', import.meta.url));

const event = (stage, position, total, solverDetail) => ({
  position, total, elapsed_s: 0, stage, ...(solverDetail ? { solver_detail: solverDetail } : {}),
});

function replay(stream, start = EMPTY_PUBLIC_SOLVE_PROGRESS_BAR) {
  let bar = start;
  return stream.map((progress) => {
    bar = nextPublicSolveProgressBar(bar, progress);
    return bar.percent;
  });
}

function assertMonotonic(shown, label) {
  for (let index = 1; index < shown.length; index += 1) {
    assert.ok(shown[index] >= shown[index - 1], `${label}: the bar never moves backwards (event ${index}: ${shown[index - 1]} -> ${shown[index]})`);
  }
}

// The event order of a Standard IPM 14p solve: 48 mesh ticks at position 0,
// timing events with stale or empty counts, interleaved loaded and no-load
// solves reported after meshing, then finalization with a different total (#53).
const stream = [event('Validating', 0, 1), event('starting', 0, 0)];
for (let mesh = 1; mesh <= 48; mesh += 1) stream.push(event('gmsh_mesh', 0, 97, { mesh_completed: mesh, mesh_total: 48 }));
stream.push(event('solver_timing', 0, 97, { timing_key: 'gmsh_mesh' }));
for (let position = 1; position <= 96; position += 1) {
  stream.push(event(position % 2 ? 'noload_sweep' : 'magneto2d_sweep', position, 97));
  if (position === 40) stream.push(event('magneto2d_sweep', 38, 97)); // a late, out-of-order report
}
stream.push(
  event('solver_timing', 96, 97, { timing_key: 'loaded_field_solve' }),
  event('magneto2d_sweep', 96, 97),
  event('magneto2d_complete', 49, 49),
  event('solver_timing', 0, 0, { timing_key: 'result_packaging' }),
  event('packaging_results', 49, 49),
  event('saving_run', 49, 49),
);
const shown = replay(stream);
assertMonotonic(shown, 'mesh-stage solve');
const meshEnd = stream.findIndex((progress) => progress.stage === 'solver_timing');
assert.equal(shown[0], 0, 'a new solve starts empty');
assert.ok(shown[2] > 0 && shown[2] < 2, 'the first mesh tick moves the bar a little');
assert.ok(Math.abs(shown[meshEnd - 1] - PUBLIC_SOLVE_MESH_SHARE * 100) < 1e-9, 'meshing fills its share');
assert.ok(shown[meshEnd + 1] > PUBLIC_SOLVE_MESH_SHARE * 100, 'the first field solve continues from meshing instead of dropping');
assert.equal(shown.at(-1), 100, 'finalizing holds the full bar');

// A solve without a mesh stage fills the whole bar from solve positions,
// instead of jumping to the mesh share on its first position.
const plain = replay([event('Validating', 0, 1), ...[1, 2, 3, 2, 4].map((position) => event('magneto2d_sweep', position, 4)), event('packaging_results', 4, 4)]);
assertMonotonic(plain, 'solve without mesh stage');
assert.equal(plain[1], 25, 'first of four positions is a quarter of the bar');
assert.equal(plain.at(-1), 100);

// Timing events and position 0 report no solve progress; only mesh events report meshes.
assert.equal(publicSolvePositionFraction(event('solver_timing', 0, 0)), null);
assert.equal(publicSolvePositionFraction(event('magneto2d_sweep', 0, 97)), null);
assert.equal(publicSolvePositionFraction(null), null);
assert.equal(publicSolveMeshFraction(event('gmsh_mesh', 0, 97, { mesh_completed: 12, mesh_total: 48 })), 0.25);
assert.equal(publicSolveMeshFraction(event('magneto2d_sweep', 3, 97)), null);

// The next solve, or a cleared progress, restarts the bar.
const done = { percent: 100, meshStage: true };
assert.deepEqual(nextPublicSolveProgressBar(done, event('Validating', 0, 1)), EMPTY_PUBLIC_SOLVE_PROGRESS_BAR);
assert.deepEqual(nextPublicSolveProgressBar(done, null), EMPTY_PUBLIC_SOLVE_PROGRESS_BAR);

console.log('solve progress checks passed (monotonic bar across meshing, solving and finalizing)');
