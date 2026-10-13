import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  formatWaveformReadoutAngle,
  formatWaveformReadoutDifference,
  formatWaveformReadoutValue,
  nearestWaveformReadoutIndex,
  steppedWaveformReadoutIndex,
  waveformReadoutAngles,
  waveformReadoutDifferenceValue,
  waveformReadoutValues,
} = await importTypeScriptModule(new URL('../src/public/chartReadout.ts', import.meta.url));

const grid = (count, step) => Array.from({ length: count }, (_, index) => index * step);
const torque = (angles, offset) => angles.map((angle) => offset + Math.sin(angle * Math.PI / 30) / 7);

// Compare: a Preview run (13 positions over 45°) against a Standard run (48 over 360°).
const previewAngles = grid(13, 3.75);
const standardAngles = grid(48, 7.5);
const runA = { key: 'run-a', label: 'Run A', color: '#f59e0b', unit: 'N·m', angles: previewAngles, values: torque(previewAngles, 12.2) };
const runB = { key: 'run-b', label: 'Run B', color: '#22d3ee', unit: 'N·m', angles: standardAngles, values: torque(standardAngles, 12.3) };
const difference = { minuendKey: 'run-b', subtrahendKey: 'run-a', label: 'Run B − Run A' };

const unionAngles = waveformReadoutAngles([runA, runB]);
assert.deepEqual(unionAngles.slice(0, 4), [0, 3.75, 7.5, 11.25], 'the readout offers every solved angle of the shown runs');
assert.equal(unionAngles.length, 48 + 6, 'angles both runs solved appear once');
assert.deepEqual(waveformReadoutAngles([runB]), standardAngles, 'one run offers its own grid');
assert.deepEqual(waveformReadoutAngles([]), [], 'no shown series, no angles');

// Snap to the nearest solved angle; never interpolate.
assert.equal(nearestWaveformReadoutIndex(standardAngles, 11.2), 1);
assert.equal(nearestWaveformReadoutIndex(standardAngles, 11.3), 2);
assert.equal(nearestWaveformReadoutIndex(standardAngles, -40), 0, 'left of the plot snaps to the first position');
assert.equal(nearestWaveformReadoutIndex(standardAngles, 400), 47, 'right of the plot snaps to the last position');
assert.equal(nearestWaveformReadoutIndex([], 10), -1);
assert.equal(nearestWaveformReadoutIndex(standardAngles, Number.NaN), -1);

// Values are the stored samples, labelled by series; a run without that angle is null.
const shared = waveformReadoutValues([runA, runB], 7.5);
assert.equal(shared[0].value, runA.values[2], 'Run A shows its stored sample exactly');
assert.equal(shared[1].value, runB.values[1], 'Run B shows its stored sample exactly');
assert.deepEqual(shared.map((item) => [item.key, item.label, item.color, item.unit]), [
  ['run-a', 'Run A', '#f59e0b', 'N·m'],
  ['run-b', 'Run B', '#22d3ee', 'N·m'],
]);
assert.equal(waveformReadoutDifferenceValue(shared, difference), runB.values[1] - runA.values[2], 'the difference is Run B − Run A');

const previewOnly = waveformReadoutValues([runA, runB], 3.75);
assert.equal(previewOnly[0].value, runA.values[1]);
assert.equal(previewOnly[1].value, null, 'Run B was not solved at 3.75°, so it has no value there');
assert.equal(waveformReadoutDifferenceValue(previewOnly, difference), null, 'no difference without both samples');

const standardOnly = waveformReadoutValues([runA, runB], 180);
assert.equal(standardOnly[0].value, null, 'Run A covers only 0–45°');
assert.equal(standardOnly[1].value, runB.values[24]);

// A hidden run is not passed in, so it is neither listed nor differenced.
const runBShown = waveformReadoutValues([runB], 7.5);
assert.deepEqual(runBShown.map((item) => item.key), ['run-b']);
assert.equal(waveformReadoutDifferenceValue(runBShown, difference), null);

// Non-finite stored samples are not shown as numbers.
assert.equal(waveformReadoutValues([{ ...runB, values: standardAngles.map(() => Number.NaN) }], 0)[0].value, null);

// Keyboard: arrows step and stop at the ends; Home and End jump; other keys do nothing.
assert.equal(steppedWaveformReadoutIndex(null, 48, 'ArrowRight'), 0, 'the first step right selects the first position');
assert.equal(steppedWaveformReadoutIndex(null, 48, 'ArrowLeft'), 47, 'the first step left selects the last position');
assert.equal(steppedWaveformReadoutIndex(5, 48, 'ArrowRight'), 6);
assert.equal(steppedWaveformReadoutIndex(5, 48, 'ArrowUp'), 6);
assert.equal(steppedWaveformReadoutIndex(5, 48, 'ArrowLeft'), 4);
assert.equal(steppedWaveformReadoutIndex(5, 48, 'ArrowDown'), 4);
assert.equal(steppedWaveformReadoutIndex(47, 48, 'ArrowRight'), 47);
assert.equal(steppedWaveformReadoutIndex(0, 48, 'ArrowLeft'), 0);
assert.equal(steppedWaveformReadoutIndex(20, 48, 'Home'), 0);
assert.equal(steppedWaveformReadoutIndex(20, 48, 'End'), 47);
assert.equal(steppedWaveformReadoutIndex(20, 48, 'Enter'), null);
assert.equal(steppedWaveformReadoutIndex(null, 0, 'ArrowRight'), null);

// Formatting follows the result and Compare cards.
assert.equal(formatWaveformReadoutAngle(0), '0°');
assert.equal(formatWaveformReadoutAngle(-0), '0°');
assert.equal(formatWaveformReadoutAngle(3.75), '3.75°');
assert.equal(formatWaveformReadoutAngle(352.5), '352.5°');
assert.equal(formatWaveformReadoutAngle(7.500000000001), '7.5°');
assert.equal(formatWaveformReadoutValue(12.2349, 'N·m'), '12.23 N·m');
assert.equal(formatWaveformReadoutValue(-31.5, 'V'), '-31.50 V');
assert.equal(formatWaveformReadoutDifference(0.1234, 'N·m'), '+0.12 N·m');
assert.equal(formatWaveformReadoutDifference(-0.1234, 'N·m'), '-0.12 N·m');
assert.equal(formatWaveformReadoutDifference(0.001, 'N·m'), '0.00 N·m', 'a difference that rounds to zero carries no sign');
assert.equal(formatWaveformReadoutDifference(-0.001, 'N·m'), '0.00 N·m');

// Angle axis labels (#54 follow-up): regular, round steps.
const { electricalAngleTicks, formatElectricalAngleTick } = await importTypeScriptModule(
  new URL('../src/public/chartAxis.ts', import.meta.url),
);
assert.deepEqual(electricalAngleTicks(0, 360), [0, 45, 90, 135, 180, 225, 270, 315, 360], 'a full cycle every 45°');
assert.deepEqual(electricalAngleTicks(0, 180), [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5, 180]);
assert.deepEqual(electricalAngleTicks(0, 60), [0, 7.5, 15, 22.5, 30, 37.5, 45, 52.5, 60], 'the 60° Preview window');
assert.deepEqual(electricalAngleTicks(0, 45), [0, 7.5, 15, 22.5, 30, 37.5, 45], 'the 45° Preview window');
assert.deepEqual(electricalAngleTicks(0, 352.5), [0, 45, 90, 135, 180, 225, 270, 315], 'no label past the axis end');
assert.deepEqual(electricalAngleTicks(-90, 90), [-90, -67.5, -45, -22.5, 0, 22.5, 45, 67.5, 90]);
assert.deepEqual(electricalAngleTicks(30, 30), [30], 'a single angle');
assert.deepEqual(electricalAngleTicks(Number.NaN, 360), []);
assert.equal(formatElectricalAngleTick(7.5), '7.5°');
assert.equal(formatElectricalAngleTick(45), '45°');
assert.equal(formatElectricalAngleTick(-0), '0°');

console.log('Chart readout tests passed.');
