// Design errors in plain words: the parallel-paths check reads as a sentence with
// the fixes that work, and each error flags the Design section holding its field.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  designErrorSection,
  designErrorText,
  parallelPathsMessage,
} = await importTypeScriptModule(new URL('../src/public/designErrors.ts', import.meta.url));
const { coilsPerPhase } = await importTypeScriptModule(new URL('../src/public/toothCoils.ts', import.meta.url));
const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));

function design(slots, poles, type, layers, paths) {
  const config = cloneDefaultConfig();
  config.stator.slot_count = slots;
  config.rotor.pole_count = poles;
  config.winding.type = type;
  config.winding.layers = layers;
  config.winding.parallel_paths = paths;
  return config;
}

// The reported case: 6 slots, 4 poles, coils on alternate teeth, 2 parallel paths.
const reported = design(6, 4, 'concentrated', 1, 2);
const plain = '2 parallel paths can\'t split this winding evenly: it has 1 coil per phase '
  + '(6 slots, coils on alternate teeth), and each path needs the same number of coils in series. '
  + 'Use 1 parallel path, or set Wound teeth to All, which gives 2 coils per phase.';
assert.equal(parallelPathsMessage(reported), plain);

// Fixes list every dividing count, and Wound teeth: All only when it divides too.
assert.equal(
  parallelPathsMessage(design(12, 8, 'concentrated', 1, 3)),
  '3 parallel paths can\'t split this winding evenly: it has 2 coils per phase '
    + '(12 slots, coils on alternate teeth), and each path needs the same number of coils in series. '
    + 'Use 1 or 2 parallel paths.',
);
assert.match(parallelPathsMessage(design(12, 8, 'concentrated', 1, 4)), /Use 1 or 2 parallel paths, or set Wound teeth to All, which gives 4 coils per phase\.$/);
assert.equal(
  parallelPathsMessage(design(24, 4, 'distributed', 2, 3)),
  '3 parallel paths can\'t split this winding evenly: it has 4 coils per phase '
    + '(24 slots, distributed), and each path needs the same number of coils in series. '
    + 'Use 1, 2 or 4 parallel paths.',
);
assert.match(parallelPathsMessage(design(6, 4, 'concentrated', 2, 4)), /\(6 slots, a coil on every tooth\)/);

// No message whenever the paths divide the coils, for every layout the backend winds.
const layouts = JSON.parse(
  await readFile(new URL('../../tests/fixtures/tooth_coil_layouts.json', import.meta.url), 'utf8'),
).cases;
for (const { slot_count: slots, pole_count: poles, layers } of layouts) {
  const coils = coilsPerPhase(slots, poles, 'concentrated', layers);
  for (let paths = 1; paths <= 8; paths += 1) {
    const message = parallelPathsMessage(design(slots, poles, 'concentrated', layers, paths));
    assert.equal(message === null, paths === 1 || coils % paths === 0, `${slots}s${poles}p layers=${layers} paths=${paths}`);
  }
}

// The text shown: the plain sentence for this check, whether the error keeps its
// field (preview, mesh) or arrives flattened from /solve/validate; others unchanged.
const backendMessage = 'parallel_paths=2 does not evenly divide the 1 coils per phase of this concentrated layout '
  + '(6 slots, one coil on every other tooth).';
assert.equal(designErrorText({
  error_code: 'INVALID_GEOMETRY',
  message: backendMessage,
  field: 'winding.parallel_paths',
  suggestion: 'Use one of: [1]',
}, reported), plain);
assert.equal(designErrorText({
  error_code: 'LOCAL_REQUEST_FAILED',
  message: `${backendMessage} Use one of: [1]`,
}, reported), plain);
// Edited since the request so it no longer applies: the backend text stays.
assert.equal(designErrorText({
  error_code: 'INVALID_GEOMETRY',
  message: backendMessage,
  field: 'winding.parallel_paths',
  suggestion: 'Use one of: [1]',
}, design(6, 4, 'concentrated', 1, 1)), `${backendMessage} Use one of: [1]`);
assert.equal(designErrorText({
  error_code: 'INVALID_GEOMETRY',
  message: 'Tooth too narrow.',
  field: 'stator.tooth_width_mm',
  suggestion: 'Widen it.',
}, reported), 'Tooth too narrow. Widen it.');

// Each error flags the section whose control sets its field.
const section = (field) => designErrorSection({ error_code: 'INVALID_GEOMETRY', message: 'x', field });
assert.equal(section('winding.parallel_paths'), 'winding');
assert.equal(section('winding.coil_span'), 'winding');
assert.equal(section('solve_params.current_amplitude_A'), 'winding');
assert.equal(section('stator.slot_count'), 'stator');
assert.equal(section('stator.tooth_width_mm'), 'advanced');
assert.equal(section('rotor.pole_count'), 'rotor');
assert.equal(section('rotor.v_angle_deg'), 'advanced');
assert.equal(section('materials.stator_steel'), 'materials');
assert.equal(section('solve_params.solve_quality'), null);
assert.equal(section(null), null);
assert.equal(designErrorSection(null), null);
assert.equal(designErrorSection({ error_code: 'LOCAL_REQUEST_FAILED', message: `${backendMessage} Use one of: [1]` }), 'winding');

console.log('design error wording and section checks passed');
