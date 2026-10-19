import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The 2D Phases preview: the terminal currents it shows are the ones a public
// solve drives, checked against vectors the backend tests pin to the solver.
const {
  PHASE_DRIVE_MIN_WIDTH,
  PHASE_SCOPE_WINDOW_S,
  STRIP_END,
  TRACE_AMPLITUDE,
  electricalFrequencyHz,
  formatHz,
  scopeWindowElecDeg,
  phaseCurrents,
  phaseDriveFrame,
  phaseStrips,
  rotorElectricalDeg,
  slotCurrents,
  toothIndexAt,
  toothPoles,
  waveformTrace,
} = await importTypeScriptModule(new URL('../src/public/phaseDrive.ts', import.meta.url));

const fixture = async (name) => JSON.parse(await readFile(new URL(`../../tests/fixtures/${name}`, import.meta.url), 'utf8'));
const drive = (overrides) => ({ mode: 'sinusoidal', currentAngleReference: 'q_axis', currentAmplitudeA: 1, currentAngleDeg: 0, commutationAdvanceDeg: 0, axisOffsetDeg: 0, poleCount: 8, ...overrides });
const close = (actual, expected, label, tolerance = 1e-9) => actual.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) <= tolerance, `${label}: ${actual} != ${expected}`));

// Six-step: the public clockwise sector table, boundaries included.
const sixStep = await fixture('bldc_six_step_golden_vectors.json');
assert.equal(sixStep.rotation_convention, 'public_clockwise_positive');
for (const vector of sixStep.vectors) {
  const currents = phaseCurrents(drive({ mode: 'ideal_six_step_120', commutationAdvanceDeg: vector.commutation_advance_deg }), vector.rotor_electrical_angle_deg);
  close(currents.map((value) => value * sixStep.plateau_current_A), vector.phase_current_A, `six-step ${vector.id}`, 0);
}
// Phase A's axis moves the sectors with it, as the solver's public resolver adds it.
close(phaseCurrents(drive({ mode: 'ideal_six_step_120', axisOffsetDeg: 30 }), 0), [1, -1, 0], 'six-step, axis 30 at 0');
close(phaseCurrents(drive({ mode: 'ideal_six_step_120', axisOffsetDeg: 30 }), 31), [0, -1, 1], 'six-step, axis 30 past the boundary');

// Sine: the launch-surface solve's terminal currents, gamma and axis included.
const sine = await fixture('public_sine_phase_current_vectors.json');
assert.equal(sine.rotation_convention, 'public_clockwise_positive');
assert.ok(sine.vectors.length >= 30);
for (const vector of sine.vectors) {
  const currents = phaseCurrents(drive({ currentAngleDeg: vector.current_angle_deg, axisOffsetDeg: vector.phase_axis_offset_elec_deg }), vector.rotor_electrical_angle_deg);
  close(currents, vector.phase_current, `sine ${vector.fixture} gamma ${vector.current_angle_deg} at ${vector.rotor_electrical_angle_deg}`);
}

// A balanced wye: the three currents sum to zero, and six-step has one phase off.
for (let angle = 0; angle < 360; angle += 7.5) {
  const [a, b, c] = phaseCurrents(drive({ currentAngleDeg: 20, axisOffsetDeg: 15 }), angle);
  assert.ok(Math.abs(a + b + c) < 1e-12, `sine sums to zero at ${angle}`);
  const step = phaseCurrents(drive({ mode: 'ideal_six_step_120', axisOffsetDeg: 30 }), angle);
  assert.equal(step.filter((value) => value === 0).length, 1, `six-step: one phase off at ${angle}`);
}

// Electrical angle: pole pairs times the mechanical preview angle, wrapped.
assert.equal(rotorElectricalDeg(10, 8), 40);
assert.equal(rotorElectricalDeg(100, 8), 40);
assert.equal(rotorElectricalDeg(-5, 6), 345);

// Layout: waveforms on the left, the motor smaller to the right; too narrow, none.
assert.equal(phaseDriveFrame(PHASE_DRIVE_MIN_WIDTH - 1, 600), null);
for (const [width, height] of [[480, 420], [760, 600], [1440, 700]]) {
  const frame = phaseDriveFrame(width, height);
  assert.ok(frame, `${width}x${height}: room for the waveforms`);
  const { panel, motor } = frame;
  assert.ok(panel.x > 0 && panel.x + panel.width + 30 <= motor.x, `${width}x${height}: a gap for the wires before the motor`);
  assert.ok(motor.x + motor.width <= width && motor.y >= 0 && motor.y + motor.height <= height, `${width}x${height}: motor inside the canvas`);
  assert.ok(motor.width < width - panel.width && motor.height < height, `${width}x${height}: motor smaller than alone`);
  assert.ok(panel.y >= 0 && panel.y + panel.height <= height, `${width}x${height}: waveforms inside the canvas`);
  // Waveforms: right end is now, the trace stays in its strip.
  const strips = phaseStrips(panel);
  assert.equal(strips.length, 3);
  assert.ok(strips.every((strip, index) => index === 0 || strip.y >= strips[index - 1].y + strips[index - 1].height), 'strips do not overlap');
  const sixStepDrive = drive({ mode: 'ideal_six_step_120', axisOffsetDeg: 30 });
  for (const [phaseIndex, strip] of strips.entries()) {
    for (const now of [0, 47, 133.5, 290]) {
      const trace = waveformTrace(sixStepDrive, phaseIndex, now, strip);
      const [endX, endY] = trace[trace.length - 1];
      const mid = strip.y + strip.height / 2;
      assert.equal(endX, strip.x + strip.width - STRIP_END);
      assert.ok(Math.abs((mid - endY) / (strip.height * TRACE_AMPLITUDE) - phaseCurrents(sixStepDrive, now)[phaseIndex]) < 1e-9, 'trace ends at the current value now');
      assert.ok(trace.every(([x, y], index) => y >= strip.y && y <= strip.y + strip.height && (index === 0 || x > trace[index - 1][0])), 'trace inside its strip, left to right');
    }
  }
}

// The strips are a scope with a fixed sweep: the electrical frequency is rev/s
// times pole pairs, so at 18 rpm IPM 14p shows 2.1 cycles in its second and twice
// the speed shows twice as many.
assert.equal(PHASE_SCOPE_WINDOW_S, 1);
assert.ok(Math.abs(electricalFrequencyHz(18, 14) - 2.1) < 1e-12);
assert.ok(Math.abs(electricalFrequencyHz(18, 8) - 1.2) < 1e-12);
assert.ok(Math.abs(electricalFrequencyHz(2400, 14) - 280) < 1e-9, 'rated speed: 280 Hz');
assert.ok(Math.abs(scopeWindowElecDeg(18, 14) - 756) < 1e-9);
assert.deepEqual([formatHz(2.1), formatHz(0.3), formatHz(11.67)], ['2.1 Hz', '0.30 Hz', '12 Hz']);
const scopeStrip = { x: 0, y: 0, width: 330, height: 90 };
const crossings = (rpm, poles, mode = 'sinusoidal') => {
  const values = waveformTrace(drive({ mode, poleCount: poles }), 0, 123, scopeStrip, scopeWindowElecDeg(rpm, poles))
    .map(([, y]) => scopeStrip.height / 2 - y);
  let count = 0;
  for (let i = 1; i < values.length; i += 1) if ((values[i - 1] < 0) !== (values[i] < 0)) count += 1;
  return count;
};
// Two sign changes a cycle: 2.1 cycles is 4 or 5, 4.2 cycles 8 or 9.
assert.ok([4, 5].includes(crossings(18, 14)), `18 rpm, 14 poles: ${crossings(18, 14)} crossings`);
assert.ok([8, 9].includes(crossings(36, 14)), `36 rpm, 14 poles: ${crossings(36, 14)} crossings`);
assert.ok([22, 23, 24].includes(crossings(100, 14)), `100 rpm, 14 poles: ${crossings(100, 14)} crossings`);
// The scroll is the real time base: one second later the trace has moved by the
// sweep, so the value now was at the left end... one window back.
const window = scopeWindowElecDeg(18, 14);
const later = waveformTrace(drive({ poleCount: 14 }), 0, 123 + window, scopeStrip, window);
const earlier = waveformTrace(drive({ poleCount: 14 }), 0, 123, scopeStrip, window);
assert.ok(Math.abs(later[0][1] - earlier[earlier.length - 1][1]) < 1e-9, 'the sweep is one second of rotor travel');

// Tooth poles. One coil round tooth 0, current out of the page in slot 0 and into
// it in slot 1: by the right-hand rule its flux leaves tooth 0's face, an N pole.
const lone = toothPoles([1, -1, 0, 0, 0, 0]);
assert.equal(lone.indexOf(Math.max(...lone)), 0);
assert.equal(Math.max(...lone), 1);
assert.ok(Math.abs(lone.reduce((total, value) => total + value, 0)) < 1e-12, 'no net pole');
assert.equal(toothIndexAt(Math.PI / 12, 12), 0);
assert.equal(toothIndexAt(-Math.PI / 12, 12), 11);
assert.equal(toothIndexAt(2 * Math.PI + 0.01, 12), 0);
close(slotCurrents([
  { slot_index: 0, phase: 'A', direction: 'in' },
  { slot_index: 0, phase: 'B', direction: 'out' },
  { slot_index: 1, phase: 'C', direction: 'out' },
], 2, [1, 0.5, -1]), [0.25, 1], 'slot currents: shared slots split, in is out of the page');

// The poles turn with the rotor and lead it by 90 degrees electrical at gamma = 0:
// the stator N axis sits counter-clockwise of the rotor's N, so stator S, ahead in
// the clockwise direction of motoring, pulls it round. Layouts and the rotor axis
// are the backend preview's (test_public_phase_drive.py keeps them current).
const layouts = await fixture('phase_drive_winding_layouts.json');
const elecAxis = (poles, slotCount, pairs) => {
  let re = 0; let im = 0;
  poles.forEach((value, k) => {
    const angle = pairs * (k + 0.5) * (2 * Math.PI / slotCount);
    re += value * Math.cos(angle); im += value * Math.sin(angle);
  });
  return ((Math.atan2(im, re) * 180 / Math.PI) + 360) % 360;
};
const wrapDiff = (a, b) => ((a - b) % 360 + 540) % 360 - 180;
// Stepped through a whole electrical cycle, 1 degree at a time:
// - sine: the stator field turns smoothly with the rotor, the lead never moves;
// - six-step: it sits in exactly 6 places 60 degrees apart and the lead saws from
//   120 down to 60 before each commutation, the ideal 120-degree pattern.
// (About 1 degree of the 90 is the rotor axis taken from the magnet centroids.)
for (const layout of layouts.cases) {
  const pairs = layout.pole_count / 2;
  for (const mode of ['sinusoidal', 'ideal_six_step_120']) {
    const caseDrive = drive({ mode, axisOffsetDeg: layout.phase_axis_offset_elec_deg, poleCount: layout.pole_count });
    const leads = [];
    const statorAxes = new Set();
    for (let stepDeg = 0; stepDeg < 360; stepDeg += 1) {
      const theta = rotorElectricalDeg(stepDeg / pairs, layout.pole_count);
      const poles = toothPoles(slotCurrents(layout.winding_layout, layout.slot_count, phaseCurrents(caseDrive, theta)));
      const statorAxis = elecAxis(poles, layout.slot_count, pairs);
      statorAxes.add(Math.round(statorAxis) % 360);
      // The rotor turns clockwise: its N axis moves back by theta, electrically.
      leads.push(wrapDiff(statorAxis, layout.rotor_n_axis_elec_deg - theta));
    }
    const low = Math.min(...leads);
    const high = Math.max(...leads);
    const label = `${layout.fixture} ${mode}`;
    if (mode === 'sinusoidal') {
      assert.ok(high - low < 0.1, `${label}: the lead holds (${low.toFixed(2)}..${high.toFixed(2)})`);
      assert.ok(Math.abs((low + high) / 2 - 90) <= 1.5, `${label}: stator N leads rotor N by 90 elec (${low.toFixed(2)})`);
      assert.equal(statorAxes.size, 360, `${label}: the stator field turns with every step`);
    } else {
      assert.ok(low >= 59 && high <= 121.5, `${label}: the lead stays within 60..120 elec (${low.toFixed(2)}..${high.toFixed(2)})`);
      const axes = [...statorAxes].sort((a, b) => a - b);
      assert.equal(axes.length, 6, `${label}: six stator positions a cycle (${axes})`);
      axes.forEach((axis, index) => index && assert.equal(axis - axes[index - 1], 60, `${label}: 60 degrees apart (${axes})`));
    }
  }
}

console.log('phase drive checks passed');

// Reference presets use the published d-axis Phi0 and retained A/B/C order.
// These samples come from the public solver resolver, including zero current.
const prius = await fixture('prius_phase_drive_vectors.json');
for (const vector of prius.vectors) {
  const shown = phaseCurrents(drive({ currentAngleReference: 'pyleecan_d_axis', currentAmplitudeA: vector.current_amplitude_A,
    currentAngleDeg: vector.current_angle_deg, axisOffsetDeg: 15 }), vector.rotor_electrical_angle_deg);
  close(shown, vector.normalized_current, `${vector.case_id} at ${vector.rotor_electrical_angle_deg}`);
}
for (const mode of ['sinusoidal', 'ideal_six_step_120']) {
  for (let theta = 0; theta < 360; theta += 15) {
    const current = phaseCurrents(drive({ mode, currentAmplitudeA: 0 }), theta);
    assert.deepEqual(current, [0, 0, 0]);
    assert.ok(toothPoles(slotCurrents(layouts.cases[0].winding_layout, layouts.cases[0].slot_count, current)).every(x => x === 0));
    const trace = waveformTrace(drive({ mode, currentAmplitudeA: 0 }), 0, theta, scopeStrip);
    assert.ok(trace.every(([, y]) => y === scopeStrip.height / 2), 'zero-current traces stay flat');
  }
}
console.log('Prius convention and zero-current checks passed');
