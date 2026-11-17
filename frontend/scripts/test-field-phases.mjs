import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The Field solution's Phases layer (fieldPhases.ts): the currents the solver
// applied at each solved position, and the ⊙ / ⊗ each coil side shows for them.
const {
  coilRegionSide,
  coilSideDrive,
  coilSideMark,
  coilSidesFromGeometry,
  phaseCurrentsAt,
  phaseCycleFromFrames,
} = await importTypeScriptModule(new URL('../src/public/fieldPhases.ts', import.meta.url));

// The example SPM 8p/12s at 30 A rms: its result's slot_excitation_frames at
// 0°, 7.5° and 22.5° elec (amps, as recorded), one entry out of order and one broken.
const frames = [
  { angle_deg: 22.5, phase_current_a: [25.827560074612762, -42.06344307899867, 16.235883004385883] },
  { angle_deg: 0, phase_current_a: [36.74234614174767, -36.74234614174767, 0] },
  { angle_deg: 7.5, phase_current_a: [33.66, -39.2, 5.54] },
  { angle_deg: 15, phase_current_a: [30, 'x', 10.98] },
];
const cycle = phaseCycleFromFrames(frames);
assert.deepEqual(cycle.samples.map((sample) => sample.angleDeg), [0, 7.5, 22.5]);
assert.equal(cycle.peakA, 42.06344307899867);
assert.equal(phaseCycleFromFrames([]), null);
assert.equal(phaseCycleFromFrames(undefined), null);
// The nearest solved position, wrapping round the cycle.
assert.equal(phaseCurrentsAt(cycle, 21)[0], 25.827560074612762);
assert.equal(phaseCurrentsAt(cycle, 359)[0], 36.74234614174767);
assert.equal(phaseCurrentsAt(cycle, 4)[1], -39.2);

// Coil regions: "slot_3_(a−)" is phase A's out side, "+" an in side.
assert.deepEqual(coilRegionSide('slot_3_(a−)'), { phase: 'A', direction: 'out' });
assert.deepEqual(coilRegionSide('slot_2_(b+)'), { phase: 'B', direction: 'in' });
assert.deepEqual(coilRegionSide('slot_7_(C-)'), { phase: 'C', direction: 'out' });
assert.equal(coilRegionSide('stator_tooth'), null);

// The solver's own record at 22.5°: each slot's phase, side and current density.
// A side shows ⊙ (current out of the page) exactly where J is positive.
const recorded = [
  ['B', 'out', 1319887.82], ['B', 'in', -1319887.82], ['A', 'out', -810430.13], ['A', 'in', 810430.17],
  ['C', 'out', -509457.70], ['C', 'in', 509457.68], ['B', 'out', 1319887.84], ['B', 'in', -1319887.87],
  ['A', 'out', -810430.12], ['A', 'in', 810430.17], ['C', 'out', -509457.67], ['C', 'in', 509457.68],
];
const at22 = phaseCurrentsAt(cycle, 22.5);
recorded.forEach(([phase, direction, density], slot) => {
  assert.equal(coilSideMark({ phase, direction }, at22, cycle.peakA), density > 0, `slot ${slot + 1} ${phase} ${direction}`);
});
// At 0° phase C carries nothing: its sides show no mark and no drive.
const at0 = phaseCurrentsAt(cycle, 0);
assert.equal(coilSideMark({ phase: 'C', direction: 'in' }, at0, cycle.peakA), null);
assert.equal(coilSideDrive({ phase: 'C' }, at0, cycle.peakA), 0);
assert.equal(coilSideDrive({ phase: 'B' }, at22, cycle.peakA), 1);
assert.ok(Math.abs(coilSideDrive({ phase: 'A' }, at22, cycle.peakA) - 25.827560074612762 / 42.06344307899867) < 1e-12);

// Coil sides come from the geometry preview's coil regions, with a mark at the centroid.
const sides = coilSidesFromGeometry({
  regions: [
    { region_type: 'slot_1_(b−)', points: [[10, 0], [12, 0], [12, 4], [10, 4]] },
    { region_type: 'stator_tooth', points: [[0, 0], [1, 0], [1, 1]] },
    { region_type: 'slot_2_(b+)', points: [[0, 0], [1, 1]] },
  ],
});
assert.equal(sides.length, 1);
assert.deepEqual(sides[0].centre, [11, 2]);
assert.equal(sides[0].phase, 'B');
assert.equal(sides[0].direction, 'out');
assert.ok(Math.abs(sides[0].markRadiusMm - Math.sqrt(8) * 0.24) < 1e-12);
assert.deepEqual(coilSidesFromGeometry(null), []);

console.log('field phases: recorded currents, nearest position and ⊙ / ⊗ match the solver');
