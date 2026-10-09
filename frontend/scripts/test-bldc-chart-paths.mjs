import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/public/bldcChartPaths.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { currentStepSegments } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
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
config.solve_params.current_amplitude_A = 200;
config.solve_params.commutation_advance_deg = 20;
({ config, drafts } = switchExcitationMode(config, 'sinusoidal', drafts));
assert.equal(config.solve_params.current_amplitude_A, 30);
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
  assert.equal(state.config.solve_params.current_amplitude_A, 30, 'other mode gets fresh defaults, never preceding project current');
  state = switchExcitationMode(state.config, loadedMode, state.drafts);
  assert.deepEqual(state.config.solve_params, loaded.solve_params, 'loaded active mode round-trips unchanged');
}
replace(structuredClone(defaults));
assert.deepEqual(excitationDraftRef.current, createExcitationDrafts(defaults, defaults), 'reset clears both drafts');
console.log('BLDC project draft lifecycle checks passed');
