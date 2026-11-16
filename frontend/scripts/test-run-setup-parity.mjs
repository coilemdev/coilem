/**
 * The Python client applies saved run setups with the app's own rules
 * (frontend/src/public/solveProfiles.ts). This script runs those rules over a
 * fixed set of designs and setups and keeps two files equal to what they give:
 *
 * - tests/fixtures/run_setup_parity.json, which tests/test_run_setups.py checks
 *   the Python port against;
 * - backend/client/reference_setups.json, the app's built-in Prius reference
 *   setups, which the Python package ships.
 *
 * Run with --write after changing the setup rules, then commit both files.
 */
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const write = process.argv.includes('--write');
const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));
const { parseDesignFile, serializeDesignFile } = await importTypeScriptModule(new URL('../src/public/designFile.ts', import.meta.url));
const P = await importTypeScriptModule(new URL('../src/public/solveProfiles.ts', import.meta.url));

const example = async (name) => parseDesignFile(
  await readFile(new URL(`../src/public/examples/${name}.coilem`, import.meta.url), 'utf8'),
).config;
const edit = (config, change) => {
  const next = structuredClone(config);
  change(next);
  return next;
};
const limits = (overrides = {}) => ({
  dc_bus_V: 96, peak_current_A: 60, continuous_current_A: 30, max_speed_rpm: 9000, modulation_index_max: 2 / Math.sqrt(3), ...overrides,
});

const starter = cloneDefaultConfig();
const priusNoLoad = await example('prius-2004-tutorial-bemf-v1');
const priusLoaded = await example('prius-2004-loaded-torque-v1');
const lrk = await example('lrk-12s14p-fixed-current-v1');
const builtins = P.builtinProfiles(priusNoLoad, priusLoaded);

const highSpeed = P.captureProfile(edit(starter, (c) => {
  Object.assign(c.solve_params, {
    rated_speed_rpm: 6000, current_amplitude_A: 20, current_angle_deg: 25, solve_quality: 'fine', mesh_density: 'fine',
    nonlinear_solver: 'newton', max_nonlinear_iterations: 50, magnet_temperature_C: 80, winding_temperature_C: 20, mechanical_loss_W: 3,
  });
  Object.assign(c.solve_options, { cogging_torque: true, losses_efficiency: true, torque_speed_envelope: true });
  c.torque_speed_analysis = { preset: 'standard', control: 'mtpa', limits: limits() };
}), 'High Speed', true, 'magneto2d', 'user-high-speed', 3);
const hot = P.captureProfile(edit(starter, (c) => {
  Object.assign(c.solve_params, { magnet_temperature_C: 120, winding_temperature_C: 90, current_angle_deg: 30, rated_speed_rpm: 1500 });
  c.solve_options.back_emf = false;
}), 'Hot operating point', false, 'magneto2d', 'user-hot', 1);
const mapOperatingOnly = P.captureProfile(edit(starter, (c) => {
  c.solve_params.current_amplitude_A = 25;
  c.solve_options.torque_speed_envelope = true;
  c.torque_speed_analysis = { preset: 'standard', control: 'least_loss', limits: limits({ dc_bus_V: 120, continuous_current_A: null }) };
}), 'Map, operating point only', false, 'magneto2d', 'user-map-operating', 2);
const elmer = P.captureProfile(starter, 'Elmer numerics', true, 'elmer', 'user-elmer', 1);
const priusUser = P.captureProfile(edit(priusLoaded, (c) => {
  c.solve_params.current_angle_deg += 10;
}), 'Prius advanced angle', true, 'magneto2d', 'user-prius', 1);
const lrkSetup = P.captureProfile(lrk, 'LRK as saved', true, 'magneto2d', 'user-lrk', 1);
const sectorDesign = edit(starter, (c) => { c.solve_params.symmetry = 'auto'; });
const sector = P.captureProfile(sectorDesign, 'One sector', true, 'magneto2d', 'user-sector', 1);
assert.equal(sector.parameters.symmetry, 'auto');
assert.equal('symmetry' in highSpeed.parameters, false, 'a full-motor setup leaves the solved region out');
const setups = {
  high_speed: highSpeed, hot, map_operating_only: mapOperatingOnly, elmer, prius_user: priusUser, lrk: lrkSetup, sector,
  builtin_noload: builtins[0], builtin_loaded: builtins[1],
};

const library = (profiles, active) => ({
  schema: 1, scope: 'parity-library', profiles, activeId: active?.id ?? null, activeVersion: active?.version ?? null,
});
const userSetups = [highSpeed, hot, mapOperatingOnly, elmer];
const highSpeedSaved = P.applyProfile(starter, highSpeed);
const designs = {
  starter, high_speed_saved: highSpeedSaved,
  high_speed_edited: edit(highSpeedSaved, (c) => { c.solve_params.current_amplitude_A = 35; }),
  prius_noload: priusNoLoad, prius_loaded: priusLoaded, lrk, sector: sectorDesign,
};
const libraries = {
  starter: library(userSetups, null), high_speed_saved: library(userSetups, highSpeed),
  high_speed_edited: library(userSetups, highSpeed), prius_noload: library([priusUser], builtins[0]),
  prius_loaded: library([priusUser], priusUser), lrk: library([lrkSetup], lrkSetup),
  sector: library([highSpeed, hot, sector], sector),
};
const designFiles = Object.fromEntries(Object.entries(designs).map(([name, config]) => (
  [name, JSON.parse(serializeDesignFile(config, name, libraries[name]))]
)));
for (const [name, config] of Object.entries(designs)) {
  // The Python client reads the saved file; the app works on the parsed design. They must agree.
  assert.deepEqual(parseDesignFile(JSON.stringify(designFiles[name])).config, config, `${name} reopens unchanged`);
}

const picked = (config) => ({
  solve_params: config.solve_params, solve_options: config.solve_options,
  torque_speed_analysis: config.torque_speed_analysis ?? null, reference_case: config.reference_case ?? null,
});
const cases = [];
for (const [designName, config] of Object.entries(designs)) {
  for (const [setupName, setup] of Object.entries(setups)) {
    const compatible = P.profileCompatible(setup, config);
    const applied = compatible ? P.applyProfile(config, setup) : null;
    cases.push({
      design: designName, setup: setupName, compatible,
      applied: applied ? picked(applied) : null,
      matches_saved: P.profileMatches(setup, config, 'magneto2d'),
      matches_applied: applied ? P.profileMatches(setup, applied, 'magneto2d') : null,
      provenance_applied: applied ? P.profileProvenance(setup, applied, 'magneto2d') : null,
    });
  }
}
// The solved region: a setup with accuracy and solver settings sets it (the full motor when it
// names none), an operating-only setup leaves the design's choice alone.
const caseFor = (design, setup) => cases.find((row) => row.design === design && row.setup === setup);
assert.equal(caseFor('sector', 'high_speed').applied.solve_params.symmetry, 'full');
assert.equal(caseFor('sector', 'hot').applied.solve_params.symmetry, 'auto');
assert.equal(caseFor('starter', 'sector').applied.solve_params.symmetry, 'auto');
assert.equal(caseFor('starter', 'sector').matches_applied, true);
assert.equal(caseFor('sector', 'sector').matches_saved, true);
assert.equal(caseFor('sector', 'high_speed').matches_saved, false, 'a full-motor setup does not describe a sector design');
assert.equal(caseFor('high_speed_saved', 'high_speed').matches_saved, true, 'full-motor setups still match');

const valid = JSON.parse(JSON.stringify(highSpeed));
const variant = (change) => {
  const raw = structuredClone(valid);
  change(raw);
  return raw;
};
const parseInputs = {
  valid,
  operating_only: JSON.parse(JSON.stringify(hot)),
  prius_user: JSON.parse(JSON.stringify(priusUser)),
  unset_temperature: variant((raw) => { raw.parameters.magnet_temperature_C = null; }),
  unknown_parameter: variant((raw) => { raw.parameters.surprise = 1; }),
  bad_enum: variant((raw) => { raw.parameters.solve_quality = 'ultra'; }),
  numerics_in_operating_only: variant((raw) => { raw.includesNumerics = false; delete raw.solver; }),
  missing_required: variant((raw) => { delete raw.parameters.rated_speed_rpm; }),
  null_current: variant((raw) => { raw.parameters.current_amplitude_A = null; }),
  string_number: variant((raw) => { raw.parameters.rated_speed_rpm = '6000'; }),
  builtin_flag: variant((raw) => { raw.builtin = true; }),
  builtin_id: variant((raw) => { raw.id = 'builtin:prius-2004-tutorial-bemf-v1'; }),
  elmer_reference: variant((raw) => { raw.solver = 'elmer'; raw.referenceModel = 'pyleecan_prius_2004'; raw.referenceCase = 'prius-2004-loaded-torque-v1'; }),
  unknown_solver: variant((raw) => { raw.solver = 'femm'; }),
  missing_output: variant((raw) => { delete raw.outputs.cogging_torque; }),
  extra_output: variant((raw) => { raw.outputs.extra = true; }),
  version_zero: variant((raw) => { raw.version = 0; }),
  blank_name: variant((raw) => { raw.name = '   '; }),
  long_name: variant((raw) => { raw.name = 'x'.repeat(101); }),
  bad_angle_convention: variant((raw) => { raw.angleConvention = 'd_axis'; }),
  bad_reference_case: variant((raw) => { raw.referenceModel = 'pyleecan_prius_2004'; raw.referenceCase = 'lrk-12s14p-fixed-current-v1'; }),
  bad_map: variant((raw) => { raw.map.limits.dc_bus_V = 0; }),
  map_bad_preset: variant((raw) => { raw.map.preset = 'fine'; }),
  map_continuous_above_peak: variant((raw) => { raw.map.limits.continuous_current_A = 61; }),
  boolean_number: variant((raw) => { raw.parameters.current_angle_deg = true; }),
  corner_refinement_number: variant((raw) => { raw.parameters.corner_refinement = 1; }),
  sector: JSON.parse(JSON.stringify(sector)),
  explicit_full_motor: variant((raw) => { raw.parameters.symmetry = 'full'; }),
  bad_symmetry: variant((raw) => { raw.parameters.symmetry = 'half'; }),
  symmetry_in_operating_only: variant((raw) => { raw.includesNumerics = false; delete raw.solver; raw.parameters = { ...JSON.parse(JSON.stringify(hot)).parameters, symmetry: 'auto' }; }),
};
const parse = Object.entries(parseInputs).map(([name, raw]) => {
  let parsed = null;
  try {
    parsed = P.parseProfileDocument(library([raw], null)).profiles[0];
  } catch { /* invalid */ }
  return { name, raw, valid: parsed !== null, parsed };
});
const documents = [
  { name: 'one_bad_setup_is_skipped', raw: library([valid, parseInputs.bad_enum, JSON.parse(JSON.stringify(hot))], hot) },
  { name: 'duplicate_name_is_skipped', raw: library([valid, { ...JSON.parse(JSON.stringify(hot)), name: 'HIGH SPEED' }], null) },
  { name: 'unsupported_schema', raw: { ...library([valid], null), schema: 2 } },
  { name: 'profiles_not_a_list', raw: { ...library([], null), profiles: {} } },
  { name: 'bad_active_version', raw: { ...library([valid], null), activeVersion: 0 } },
  { name: 'missing_scope', raw: { ...library([valid], null), scope: '' } },
].map(({ name, raw }) => {
  const read = P.readProfileDocument(raw);
  return { name, raw, error: Boolean(read.error), skipped: read.skipped, names: read.document?.profiles.map((p) => p.name) ?? [] };
});

const fixture = {
  generated_by: 'frontend/scripts/test-run-setup-parity.mjs',
  designs: designFiles, setups: JSON.parse(JSON.stringify(setups)), cases, parse, documents,
};
const references = { schema: 1, generated_by: 'frontend/scripts/test-run-setup-parity.mjs', setups: builtins };
const outputs = [
  [new URL('../../tests/fixtures/run_setup_parity.json', import.meta.url), fixture],
  [new URL('../../backend/client/reference_setups.json', import.meta.url), references],
];
for (const [url, value] of outputs) {
  const text = `${JSON.stringify(value, null, 2)}\n`;
  if (write) {
    await writeFile(url, text);
    continue;
  }
  const current = await readFile(url, 'utf8').catch(() => '');
  assert.equal(current, text, `${url.pathname} is out of date with solveProfiles.ts: run node scripts/test-run-setup-parity.mjs --write`);
}
console.log(write ? 'run setup parity files written' : 'run setup parity files match the app');
