import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The preview speed field reaches 0.1 RPM so the phases and poles can be watched
// slowly: tenths below 1 RPM, whole RPM from 1 up. The field playback keeps a
// minimum of 1 RPM and so stays a whole-RPM field.
const { clampRpm, formatRpm, nativeRpmStep, shiftSteppedRpm, snapRpm, steppedRpm } = await importTypeScriptModule(
  new URL('../src/public/rpmSteps.ts', import.meta.url),
);

assert.deepEqual([0.34, 0.06, 0.96, 1.4, 17.6].map(snapRpm), [0.3, 0.1, 1, 1, 18]);
assert.deepEqual([clampRpm(0.04, 0.1, 100), clampRpm(0.25, 0.1, 100), clampRpm(140, 0.1, 100)], [0.1, 0.3, 100]);
assert.deepEqual([clampRpm(0.5, 1, 100), clampRpm(0.4, 1, 100)], [1, 1], 'a whole-RPM field clamps tenths up to 1');
assert.deepEqual([nativeRpmStep(0.1), nativeRpmStep(1)], [0.1, 1]);

// The arrow keys and the up/down buttons move the input by a tenth.
const preview = (previous, next) => steppedRpm(previous, next, 0.1, 100);
assert.equal(preview(18, 18.1), 19, 'up from a whole RPM goes to the next one');
assert.equal(preview(18, 17.9), 17, 'down from a whole RPM goes to the one below');
assert.equal(preview(1, 1.1), 2);
assert.equal(preview(1, 0.9), 0.9, 'down from 1 enters the tenths');
assert.equal(preview(0.9, 1), 1, 'up from 0.9 leaves them');
assert.equal(preview(0.3, 0.4), 0.4);
assert.equal(preview(0.30000000000000004, 0.4), 0.4, 'float noise in the previous value');
assert.equal(preview(0.1, 0.1), 0.1, 'the bottom holds');
assert.equal(preview(100, 99.9), 99);
assert.equal(preview(18, 25), 25, 'a typed speed is taken as typed');
assert.equal(preview(18, 0.25), 0.3, 'a typed tenth is snapped');
assert.equal(preview(18, 2.5), 3);
// The field playback (minimum 1, native step 1) is unchanged.
assert.deepEqual([steppedRpm(18, 19, 1, 100), steppedRpm(18, 17, 1, 100), steppedRpm(1, 0.5, 1, 100)], [19, 17, 1]);

// Shift+arrow: ten at a time, stopping at 1 before the tenths on the way down.
assert.deepEqual([shiftSteppedRpm(18, true, 0.1, 100), shiftSteppedRpm(95, true, 0.1, 100), shiftSteppedRpm(0.5, true, 0.1, 100)], [28, 100, 10]);
assert.deepEqual([shiftSteppedRpm(18, false, 0.1, 100), shiftSteppedRpm(5, false, 0.1, 100), shiftSteppedRpm(1, false, 0.1, 100), shiftSteppedRpm(0.5, false, 0.1, 100)], [8, 1, 0.1, 0.1]);
assert.deepEqual([shiftSteppedRpm(5, false, 1, 100), shiftSteppedRpm(1, false, 1, 100)], [1, 1]);

assert.deepEqual([0.1, 0.5, 1, 18, 17.6].map(formatRpm), ['0.1', '0.5', '1', '18', '18']);

console.log('rpm steps: ok');
