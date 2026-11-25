import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/public/bldcChartPaths.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { currentStepSegments, recordedSector, recordedSectorSegments } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const identity = (value) => value;

// A -> floating -> A-: plateaus reach the actual transition, with a vertical
// edge at 60 and 120 degrees, independent of the preceding sample spacing.
const paths = currentStepSegments([0, 52.5, 60, 112.5, 120], [5, 5, 0, 0, -5], identity, identity);
assert.deepEqual(paths, [
  { conducting: true, path: 'M 0.00 5.00 H 52.50 V 5.00 H 60.00' },
  { conducting: false, path: 'M 60.00 5.00 V 0.00 H 112.50 V 0.00 H 120.00' },
  { conducting: true, path: 'M 120.00 0.00 V -5.00' },
]);
const fullCycle = currentStepSegments([0, 60, 120], [0, 5, 0], identity, identity, 360);
assert.equal(fullCycle.at(-1).path, 'M 120.00 5.00 V 0.00 H 360.00');
assert.equal(currentStepSegments([0, 60], [5, -5], identity, identity)[0].path, 'M 0.00 5.00 H 60.00 V -5.00');
assert.deepEqual(currentStepSegments([], [], identity, identity), []);

// #345: the SPM 8p/12s example commutates at 30°, 90°, … because its phase-A axis is
// offset, so the angle alone put two pairs under S1. A label follows the recorded pair.
assert.equal(recordedSector(30, -30, 0), 0);
assert.equal(recordedSector(0, -30, 30), 1);
assert.equal(recordedSector(-30, 0, 30), 2);
assert.equal(recordedSector(30, 0, -30), 5);
assert.equal(recordedSector(0, 0, 0), null);
assert.equal(recordedSector(10, 10, -20), null);
const byAngle = (angle) => Math.floor(angle / 60) % 6;
const sweepAngles = [0, 15, 30, 45, 60, 75, 90, 105];
const sweepA = [30, 30, 0, 0, 0, 0, -30, -30];
const sweepB = [-30, -30, -30, -30, -30, -30, 0, 0];
const sweepC = [0, 0, 30, 30, 30, 30, 30, 30];
assert.deepEqual(recordedSectorSegments(sweepAngles, sweepA, sweepB, sweepC, byAngle, false), [
  { start: 0, end: 30, sector: 0 },
  { start: 30, end: 90, sector: 1 },
  { start: 90, end: 105, sector: 2 },
]);
// A complete cycle runs its last sector to 360°, and a sweep that wraps continues from the left edge.
assert.deepEqual(recordedSectorSegments([0, 180], [30, -30], [-30, 30], [0, 0], byAngle, true), [
  { start: 0, end: 180, sector: 0 },
  { start: 180, end: 360, sector: 3 },
]);
assert.deepEqual(recordedSectorSegments([300, 330, 0, 30], [30, 30, 30, 0], [0, 0, -30, -30], [-30, -30, 0, 30], byAngle, false), [
  { start: 300, end: 360, sector: 5 },
  { start: 0, end: 30, sector: 0 },
]);
// Currents that are not an ideal pair fall back to the angle rule.
assert.deepEqual(recordedSectorSegments([0, 60, 120], [0, 0, 0], [0, 0, 0], [0, 0, 0], byAngle, false), [
  { start: 0, end: 60, sector: 0 },
  { start: 60, end: 120, sector: 1 },
]);
console.log('BLDC chart transition checks passed');


// Exercise the same state transitions used by App, including project replacement.
const draftSource = await readFile(new URL('../src/public/excitationDrafts.ts', import.meta.url), 'utf8');
const draftCode = ts.transpileModule(draftSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { createExcitationDrafts, switchExcitationMode } = await import(`data:text/javascript;base64,${Buffer.from(draftCode).toString('base64')}`);
const defaults = { solve_params: { excitation_mode: 'sinusoidal', current_amplitude_A: 30, current_amplitude_convention: 'rms', current_angle_deg: 0, commutation_advance_deg: 0, phase_connection: 'wye' } };
let config = structuredClone(defaults);
let drafts = createExcitationDrafts(config, defaults);
({ config, drafts } = switchExcitationMode(config, 'ideal_six_step_120', drafts));
// Switching the drive keeps the current: 30 A rms is a 42.43 A peak, which is the six-step plateau.
assert.equal(config.solve_params.current_amplitude_A, 42.43);
assert.equal(config.solve_params.current_amplitude_convention, 'plateau');
// Straight back with the current untouched: the exact value it had, not 42.43 / sqrt(2).
assert.equal(switchExcitationMode(config, 'sinusoidal', drafts).config.solve_params.current_amplitude_A, 30);
config.solve_params.current_amplitude_A = 200;
config.solve_params.commutation_advance_deg = 20;
({ config, drafts } = switchExcitationMode(config, 'sinusoidal', drafts));
// A current edited under six-step carries over at the same peak: 200 A peak is 141.4 A rms.
assert.equal(config.solve_params.current_amplitude_A, 141.4);
assert.equal(config.solve_params.current_amplitude_convention, 'rms');
({ config, drafts } = switchExcitationMode(config, 'ideal_six_step_120', drafts));
assert.equal(config.solve_params.current_amplitude_A, 200, 'same design keeps BLDC current');
assert.equal(config.solve_params.commutation_advance_deg, 20, 'same design keeps advance');
({ config, drafts } = switchExcitationMode(config, 'sinusoidal', drafts));

// Execute App's actual shared replacement callback, as every reset/load pathway does.
const appSource = await readFile(new URL('../src/public/App.tsx', import.meta.url), 'utf8');
const appAst = ts.createSourceFile('App.tsx', appSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let replacementCallback;
function findCallback(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(appAst) === 'rememberPresetSweep') replacementCallback = node.initializer.arguments[0];
  ts.forEachChild(node, findCallback);
}
findCallback(appAst);
assert.ok(replacementCallback, 'project replacement callback exists');
const replacementCode = ts.transpileModule(`const replace = ${replacementCallback.getText(appAst)};`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
const excitationDraftRef = { current: drafts };
const replace = new Function('excitationDraftRef', 'createExcitationDrafts', 'cloneDefaultConfig', 'presetSweepRef', 'capturePublicPresetSweep', 'PUBLIC_DEFAULT_PRESET_SWEEP', `${replacementCode}; return replace;`)(excitationDraftRef, createExcitationDrafts, () => structuredClone(defaults), { current: {} }, () => ({}), {});
for (const loadedMode of ['sinusoidal', 'ideal_six_step_120']) {
  const loaded = structuredClone(defaults);
  Object.assign(loaded.solve_params, loadedMode === 'sinusoidal'
    ? { current_amplitude_A: 7, current_amplitude_convention: 'peak', current_angle_deg: 12 }
    : { excitation_mode: loadedMode, current_amplitude_A: 42, current_amplitude_convention: 'plateau', commutation_advance_deg: -8 });
  replace(loaded);
  let state = switchExcitationMode(loaded, loadedMode === 'sinusoidal' ? 'ideal_six_step_120' : 'sinusoidal', excitationDraftRef.current);
  // The other mode starts at this project's own peak current (7 A peak, or a 42 A plateau), never a preceding project's.
  assert.equal(state.config.solve_params.current_amplitude_A, loadedMode === 'sinusoidal' ? 7 : 42, 'other mode starts at the same peak current');
  assert.equal(state.config.solve_params.current_amplitude_convention, loadedMode === 'sinusoidal' ? 'plateau' : 'peak');
  state = switchExcitationMode(state.config, loadedMode, state.drafts);
  assert.deepEqual(state.config.solve_params, loaded.solve_params, 'loaded active mode round-trips unchanged');
}
replace(structuredClone(defaults));
assert.deepEqual(excitationDraftRef.current, createExcitationDrafts(defaults, defaults), 'reset clears both drafts');
console.log('BLDC project draft lifecycle checks passed');

{
  // A small six-step motor: 10 A plateau stays 10 A (peak) under sinusoidal, never a default sized for a large motor.
  const small = structuredClone(defaults);
  Object.assign(small.solve_params, { excitation_mode: 'ideal_six_step_120', current_amplitude_A: 10, current_amplitude_convention: 'plateau' });
  let state = switchExcitationMode(small, 'sinusoidal', createExcitationDrafts(small, defaults));
  assert.equal(state.config.solve_params.current_amplitude_A, 10);
  assert.equal(state.config.solve_params.current_amplitude_convention, 'peak');
  state.config.solve_params.current_amplitude_A = 12;
  state = switchExcitationMode(state.config, 'ideal_six_step_120', state.drafts);
  assert.equal(state.config.solve_params.current_amplitude_A, 12, 'an edited current carries back too');
  // Under sinusoidal, 12 A peak relabelled as 12 A rms is a larger current: it carries back as its peak, 16.97 A.
  state = switchExcitationMode(state.config, 'sinusoidal', state.drafts);
  assert.equal(state.config.solve_params.current_amplitude_A, 12);
  state.config.solve_params.current_amplitude_convention = 'rms';
  state = switchExcitationMode(state.config, 'ideal_six_step_120', state.drafts);
  assert.equal(state.config.solve_params.current_amplitude_A, 16.97, 'a changed convention is a changed current');
  console.log('drive switch keeps the current');
}
