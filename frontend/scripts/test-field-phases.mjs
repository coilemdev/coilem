import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The Field solution's Phases layer (fieldPhases.ts): the currents the solver
// applied at each solved position, and the ⊙ / ⊗ each coil side shows for them.
const {
  coilMarksFromGeometry,
  coilRegionSide,
  coilSideMark,
  coilSidesFromGeometry,
  isSteppedCycle,
  phaseCurrentsAt,
  phaseCycleFromFrames,
  phaseCycleSampler,
  recordedPhaseHistory,
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
assert.equal(phaseCurrentsAt(cycle, 21), null);
assert.equal(phaseCurrentsAt(cycle, 359), null);
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
// At 0° phase C carries nothing: its sides show no mark.
const at0 = phaseCurrentsAt(cycle, 0);
assert.equal(coilSideMark({ phase: 'C', direction: 'in' }, at0, cycle.peakA), null);

// The drive panel's waveforms are the recorded currents as shares of their
// peak: exact at each solved position, straight between them.
const sample = phaseCycleSampler(cycle);
const near = (actual, expected) => actual.every((value, index) => Math.abs(value - expected[index]) < 1e-12);
assert.ok(near(sample(22.5), at22.map((current) => current / cycle.peakA)));
assert.ok(near(sample(3.75), [0, 1, 2].map((phase) => (frames[1].phase_current_a[phase] + frames[2].phase_current_a[phase]) / 2 / cycle.peakA)));
// Neither a missing current record nor the rest of an unsolved cycle is interpolated.
assert.equal(sample(15), null);
assert.equal(sample(191.25), null);
assert.equal(isSteppedCycle(cycle), false);
// A six-step drive's currents are off or at full: they are held from one position to the next.
const sixStep = phaseCycleFromFrames([
  { angle_deg: 0, phase_current_a: [10, -10, 0] },
  { angle_deg: 60, phase_current_a: [0, -10, 10] },
]);
assert.equal(isSteppedCycle(sixStep), true);
assert.deepEqual(phaseCycleSampler(sixStep)(45), [1, -1, 0]);
assert.equal(phaseCycleSampler(sixStep)(75), null);
const single = phaseCycleFromFrames([{ angle_deg: 0, phase_current_a: [0, 0, 0] }]);
assert.deepEqual(phaseCycleSampler(single)(0), [0, 0, 0]);
assert.equal(phaseCycleSampler(single)(10), null);

const observed = angles => angles.map(angle_deg => ({ angle_deg, phase_current_a: [Math.cos(angle_deg * Math.PI / 180), -0.5, 0] }));
for (const declared of [true, undefined]) {
  const full = phaseCycleFromFrames(observed([0, 90, 180, 270, 360]), declared, 4);
  assert.ok(full.complete);
  assert.ok(near(phaseCycleSampler(full)(315), phaseCycleSampler(full)(-45)));
}
assert.equal(phaseCycleFromFrames(observed([0, 90, 180, 270]), false).complete, false);
const missing = phaseCycleFromFrames(observed([0, 15, 45, 60]), true, 24);
assert.equal(missing.complete, false);
assert.equal(phaseCycleSampler(missing)(30), null);
const history = recordedPhaseHistory(missing, phaseCycleSampler(missing), 60, 720);
assert.equal(history.gaps.length, 2);
assert.deepEqual(history.segments.map(s => s.map(p => Math.round(p.fraction * 720 - 660))), [[0, 15], [45, 60]]);
const wrapped = phaseCycleFromFrames(observed([0, 15, 345]), false);
assert.deepEqual(wrapped.windows, [[345, 375]]);
const covered = recordedPhaseHistory(wrapped, phaseCycleSampler(wrapped), 15, 30);
assert.equal(covered.gaps.length, 0);
assert.deepEqual(covered.segments[0].map(p => p.fraction), [0, 0.5, 1]);
assert.equal(phaseCycleSampler(wrapped)(90), null);
const steps = recordedPhaseHistory(sixStep, phaseCycleSampler(sixStep), 60, 60);
assert.deepEqual(steps.segments[0].map(p => [p.fraction, p.currents[0]]), [[0, 1], [1, 1], [1, 0]]);

// Coil outlines come from the geometry preview's coil regions.
const sides = coilSidesFromGeometry({
  regions: [
    { region_type: 'slot_1_(b−)', points: [[10, 0], [12, 0], [12, 4], [10, 4]] },
    { region_type: 'stator_tooth', points: [[0, 0], [1, 0], [1, 1]] },
    { region_type: 'slot_2_(b+)', points: [[0, 0], [1, 1]] },
  ],
});
assert.equal(sides.length, 1);
assert.equal(sides[0].phase, 'B');
assert.equal(sides[0].direction, 'out');
assert.deepEqual(coilSidesFromGeometry(null), []);

// ⊙ / ⊗ go where the preview draws its glyphs, as in the Geometry view: a ⊗'s
// two bars count once, centred between them; each glyph's size sets the mark's.
const square = (x, y, half) => [[x - half, y - half], [x + half, y - half], [x + half, y + half], [x - half, y + half], [x - half, y - half]];
const marks = coilMarksFromGeometry({
  regions: [
    { region_type: 'winding_symbol', label: 'A+ (in)', points: square(10, 0, 0.5) },
    { region_type: 'winding_symbol', label: 'A− (out)', points: square(20, 0, 0.5) },
    { region_type: 'winding_symbol', label: 'A− (out)', points: square(20.4, 0, 0.5) },
    { region_type: 'winding_symbol', label: 'B− (out)', points: square(30, 0, 0.5) },
    { region_type: 'slot_1_(a+)', label: 'Slot 1 (A+)', points: square(10, 0, 3) },
  ],
});
assert.deepEqual(marks.map((mark) => [mark.phase, mark.direction, Number(mark.centre[0].toFixed(6))]), [['A', 'in', 10], ['A', 'out', 20.2], ['B', 'out', 30]]);
assert.ok(Math.abs(marks[0].radiusMm - Math.SQRT1_2) < 1e-12);

console.log('field phases: recorded currents, nearest position and ⊙ / ⊗ match the solver');
