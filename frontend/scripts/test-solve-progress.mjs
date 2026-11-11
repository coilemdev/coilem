import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  EMPTY_PUBLIC_SOLVE_PROGRESS_BAR,
  PUBLIC_SOLVE_MESH_SHARE,
  nextPublicSolveProgressBar,
  nextPublicSolveRotorTurn,
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

// Completing the preview must leave room for the selected map and final save.
const mapped = replay([
  event('Validating', 0, 1),
  event('magneto2d_complete', 1, 1, { analysis_fraction: 0.05 }),
  event('torque_speed_map', 1, 29, { analysis_fraction: 0.08 }),
  event('torque_speed_map', 29, 29, { analysis_fraction: 0.95 }),
  event('saving_run', 29, 29),
]);
assertMonotonic(mapped, 'operating point followed by a map');
assert.equal(mapped[1], 5);
assert.equal(mapped[3], 95);
assert.equal(mapped.at(-1), 100);

console.log('solve progress checks passed (monotonic bar across meshing, solving and finalizing)');

// The viewport turns the rotor through the sweep, following the bar.
{
  const meshing = event('gmsh_mesh', 0, 48, { mesh_completed: 12, mesh_total: 48 });
  const turn = (previous, progress, percent) => nextPublicSolveRotorTurn(previous, progress, percent, 360, 8);
  assert.equal(turn(null, null, 0), null, 'no solve, no turn');
  assert.equal(turn(null, event('Validating', 0, 0), 0), null, 'validating shows the design as it is');
  assert.equal(turn(null, event('starting', 0, 0), 0), null, 'nothing turns before progress is reported');
  const early = turn(null, meshing, 17.5);
  assert.deepEqual(early, { turnDeg: 90 * 0.175, phase: 'meshing', finished: false }, 'the turn is the bar\'s share of the 90 degree sweep of an 8-pole motor');
  const held = turn(early, event('solver_timing', 0, 0), 17.5);
  assert.deepEqual(held, early, 'an event with no counts keeps the rotor and its phase');
  const solving = turn(early, event('magneto2d_sweep', 24, 48), 85);
  assert.deepEqual(solving, { turnDeg: 76.5, phase: 'solving', finished: false }, 'solved positions carry it on from where meshing left it');
  assert.equal(turn(solving, event('magneto2d_sweep', 2, 48), 71).turnDeg, 76.5, 'it never turns backwards within one solve');
  const finished = turn(solving, event('magneto2d_complete', 48, 48), 100);
  assert.equal(finished.finished, true, 'finalizing ends the turn');
  assert.equal(turn(finished, event('solver_timing', 3, 48), 100), finished, 'a late timing event does not start it again');
  assert.equal(turn(finished, event('Validating', 0, 0), 0), null, 'the next solve starts clean');
  assert.equal(turn(null, event('magneto2d_complete', 48, 48), 100), null, 'finalizing with no sweep shown stays empty');
  assert.equal(turn(early, event('torque_speed_map', 3, 10, { analysis_fraction: 0.3 }), 30), null, 'a map does not sweep the rotor once');
  assert.equal(nextPublicSolveRotorTurn(null, meshing, 50, 360, 0), null, 'no poles, no turn');
  assert.deepEqual(nextPublicSolveRotorTurn(null, meshing, 100, 60, 14), { turnDeg: 60 / 7, phase: 'meshing', finished: false }, 'the span is the electrical range over the pole pairs');

  // Replayed against the bar itself, a whole solve turns the rotor once, forwards.
  const stream = [
    event('starting', 0, 0),
    ...[1, 2, 3, 4].map((ready) => event('gmsh_mesh', 0, 8, { mesh_completed: ready, mesh_total: 4 })),
    event('solver_timing', 0, 0),
    ...[1, 2, 5, 8].map((position) => event('magneto2d_sweep', position, 8)),
  ];
  let bar = EMPTY_PUBLIC_SOLVE_PROGRESS_BAR;
  let rotor = null;
  const turns = stream.map((progress) => {
    bar = nextPublicSolveProgressBar(bar, progress);
    rotor = nextPublicSolveRotorTurn(rotor, progress, bar.percent, 360, 8);
    return rotor && !rotor.finished ? rotor.turnDeg : 0;
  });
  assertMonotonic(turns, 'rotor turn');
  assert.equal(turns.at(-1), 90, 'the last solved position completes the sweep');
}
