import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';
const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));
const profiles = await importTypeScriptModule(new URL('../src/public/solveProfiles.ts', import.meta.url));
const { parseDesignFile, serializeDesignFile } = await importTypeScriptModule(new URL('../src/public/designFile.ts', import.meta.url));
const { torqueSpeedSettings, designDcBusV, DEFAULT_DC_BUS_V } = await importTypeScriptModule(new URL('../src/public/torqueSpeedAnalysis.ts', import.meta.url));
const { captureProfile, applyProfile, profileMatches, profileCompatible, profileProvenance, builtinProfiles,
  newProfileDocument, saveProfile, parseProfileDocument, restoreActiveProfile, readProfileDocument, mergeProfileDocuments } = profiles;
const original = cloneDefaultConfig();
{
  const selected = structuredClone(original);
  selected.solve_options.losses_efficiency = true;
  selected.solve_options.rotor_iron_loss = true;
  const saved = captureProfile(selected, 'Rotor losses', true, 'magneto2d', 'rotor-test');
  assert.equal(saved.outputs.rotor_iron_loss, true);
  assert.equal(applyProfile(original, saved).solve_options.rotor_iron_loss, true);
  assert.equal(profileMatches(saved, selected, 'magneto2d'), true);
  const disabled = { ...saved, outputs: { ...saved.outputs, rotor_iron_loss: false } };
  const doc = { ...newProfileDocument('rotor-test'), profiles: [disabled] };
  assert.equal(parseProfileDocument(doc).profiles[0].outputs.rotor_iron_loss, undefined);
}
const oldLossProfile = { ...captureProfile(original, 'Old loss setup', true, 'magneto2d', 'old-loss'),
  outputs: { ...original.solve_options, losses_efficiency: true } };
const oldLossSnapshot = JSON.stringify(oldLossProfile);
const appliedLosses = applyProfile(original, oldLossProfile);
for (const key of ['solve_quality', 'rotor_sweep_range_deg', 'rotor_step_deg', 'mesh_density']) {
  assert.equal(appliedLosses.solve_params[key], original.solve_params[key], 'applying a loss setup keeps its plan');
}
assert.equal(JSON.stringify(oldLossProfile), oldLossSnapshot, 'old setup versions remain immutable');
assert.equal(profileMatches(oldLossProfile, appliedLosses, 'magneto2d'), true, 'the full-cycle rule shapes requests, not saved setups');
const recapturedLossProfile = captureProfile(appliedLosses, 'Old loss setup', true, 'magneto2d', 'old-loss', 2);
assert.equal(profileMatches(recapturedLossProfile, appliedLosses, 'magneto2d'), true);
const physical = c => JSON.stringify([c.topology, c.rotor, c.stator, c.winding, c.materials]);
const user = captureProfile(original, 'Rated speed', false, 'magneto2d', 'user-1');
const changed = structuredClone(original);
changed.solve_params.rated_speed_rpm = 9000;
changed.solve_params.current_amplitude_A = 80;
changed.solve_params.mesh_density = 'very_fine';
changed.solve_params.solve_quality = 'fine';
const applied = applyProfile(changed, user);
assert.equal(applied.solve_params.rated_speed_rpm, original.solve_params.rated_speed_rpm);
assert.equal(applied.solve_params.current_amplitude_A, original.solve_params.current_amplitude_A);
assert.equal(applied.solve_params.mesh_density, 'very_fine');
assert.equal(applied.solve_params.solve_quality, 'fine');
assert.equal(physical(applied), physical(changed));
assert.ok(profileMatches(user, applied, 'magneto2d'), 'ordinary setups do not pin numerical quality');
const exact = captureProfile(original, 'Exact grid', true, 'magneto2d', 'user-exact');
assert.equal(applyProfile(changed, exact).solve_params.mesh_density, original.solve_params.mesh_density);
assert.equal(profileMatches(exact, original, 'elmer'), false);
let doc = saveProfile(newProfileDocument('motor-1'), user);
const oldMetadata = profileProvenance(user, original, 'magneto2d');
doc = saveProfile(doc, captureProfile(changed, 'Rated speed', false, 'magneto2d', 'user-1', 2));
assert.equal(oldMetadata.version, 1);
assert.equal(doc.profiles[0].version, 2);
assert.throws(() => saveProfile(doc, user), /new version/);
assert.throws(() => saveProfile(doc, captureProfile(original, 'Rated speed', false, 'magneto2d', 'different')), /name already exists/);
assert.equal(profileProvenance(user, changed, 'magneto2d'), null, 'edited settings do not retain an unchanged setup identity');
const restored = restoreActiveProfile(original, doc);
assert.equal(restored.config.solve_params.rated_speed_rpm, 9000);
assert.equal(restored.config.solve_params.current_amplitude_A, 80);
assert.equal(restored.config.solve_params.mesh_density, original.solve_params.mesh_density);
assert.equal(physical(restored.config), physical(original));
assert.equal(restored.document.activeVersion, 2);
assert.equal(restoreActiveProfile(original, { ...doc, activeVersion: 1 }).document.activeId, null, 'a stale version is not applied');
assert.equal(restoreActiveProfile(original, { ...doc, activeId: 'missing' }).document.activeId, null);
const exactRestored = restoreActiveProfile(changed, saveProfile(newProfileDocument(), exact));
assert.equal(exactRestored.solver, 'magneto2d');
assert.equal(exactRestored.config.solve_params.mesh_density, original.solve_params.mesh_density);
const reopened = parseDesignFile(serializeDesignFile(changed, 'Motor', doc));
assert.deepEqual(reopened.runSetups, doc);
assert.equal(physical(reopened.config), physical(parseDesignFile(serializeDesignFile(changed, 'Motor')).config));
assert.equal(parseDesignFile(serializeDesignFile(original, 'Old file')).runSetups, undefined);
assert.throws(() => parseProfileDocument({ ...doc, schema: 2 }), /unsupported/);
const malicious = structuredClone(doc); malicious.profiles[0].parameters.stator = { OD_mm: 99 };
assert.throws(() => parseProfileDocument(malicious), /settings/);
const badValue = structuredClone(doc); badValue.profiles[0].parameters.current_amplitude_A = 'wrong';
assert.throws(() => parseProfileDocument(badValue), /values/);
const configs = [];
for (const name of ['prius-2004-tutorial-bemf-v1', 'prius-2004-loaded-torque-v1']) {
  configs.push(parseDesignFile(await readFile(new URL(`../src/public/examples/${name}.coilem`, import.meta.url), 'utf8')).config);
}
const builtins = builtinProfiles(...configs);
for (const [i, profile] of builtins.entries()) {
  assert.equal(restoreActiveProfile(original, { ...newProfileDocument(), activeId: profile.id, activeVersion: 1 }, builtins).document.activeId,
    null, 'a remembered setup cannot be applied to an incompatible design');
  const altered = structuredClone(configs[1 - i]); altered.solve_params.mesh_density = 'coarse';
  const result = applyProfile(altered, profile);
  assert.equal(physical(result), physical(altered));
  assert.equal(result.solve_params.rated_speed_rpm, i === 0 ? 1000 : 2000);
  assert.equal(result.solve_params.magnet_temperature_C, i === 0 ? 20 : 60);
  assert.equal(result.solve_params.current_amplitude_A, i === 0 ? 0 : 250);
  assert.equal(result.solve_params.current_amplitude_convention, 'peak');
  assert.equal(result.solve_params.current_angle_deg, 140);
  assert.deepEqual(result.solve_options, configs[i].solve_options);
  assert.ok(profileMatches(profile, result, 'magneto2d'));
  result.solve_params.current_amplitude_A += 1;
  assert.equal(profileProvenance(profile, result, 'magneto2d'), null);
  assert.equal(profileCompatible({ ...profile, referenceRevision: 'wrong' }, configs[i]), false);
  assert.equal(profileCompatible(profile, original), false);
  const differentGeometry = structuredClone(configs[i]); differentGeometry.stator.OD_mm += 1;
  assert.equal(profileCompatible(profile, differentGeometry), false);
  assert.throws(() => applyProfile(original, profile), /different reference/);
  assert.throws(() => saveProfile(doc, profile), /cannot be overwritten/);
}
// Catalogue defaults stay unset. An explicit 20 °C is refused for magnet grades without
// temperature coefficients, and the LRK reference requires no temperature at all.
const holeM50 = parseDesignFile(await readFile(new URL('../src/public/examples/ornl_prius_2004_holem50.coilem', import.meta.url), 'utf8')).config;
const ferrite = structuredClone(original); ferrite.materials.magnet_grade = 'Ferrite_Y30';
for (const config of [ferrite, holeM50]) {
  const setup = captureProfile(config, 'Unset temperature', false, 'magneto2d', 'unset');
  assert.equal(setup.parameters.magnet_temperature_C, null);
  const applied = applyProfile(config, setup);
  for (const key of ['magnet_temperature_C', 'winding_temperature_C', 'mechanical_loss_W']) {
    assert.equal(applied.solve_params[key] ?? null, null, `${key} stays unset`);
  }
  // A setup stored with an explicit catalogue value still applies as unset and still matches.
  const explicit = { ...setup, parameters: { ...setup.parameters, magnet_temperature_C: 20, winding_temperature_C: 20, mechanical_loss_W: 0 } };
  assert.equal(applyProfile(config, explicit).solve_params.magnet_temperature_C, null);
  assert.ok(profileMatches(explicit, applied, 'magneto2d'));
}
const heated = structuredClone(original); heated.solve_params.magnet_temperature_C = 80;
assert.equal(applyProfile(original, captureProfile(heated, 'Hot', false, 'magneto2d', 'hot')).solve_params.magnet_temperature_C, 80);
for (const name of ['lrk-12s14p-fixed-current-v1', 'lrk-12s14p-six-step']) {
  const lrk = parseDesignFile(await readFile(new URL(`../src/public/examples/${name}.coilem`, import.meta.url), 'utf8')).config;
  const applied = applyProfile(lrk, captureProfile(lrk, 'LRK point', true, 'magneto2d', 'lrk'));
  assert.equal(parseDesignFile(serializeDesignFile(applied, 'LRK')).config.solve_params.magnet_temperature_C ?? null, null,
    'an LRK design saved after applying a setup reopens');
}
// Values without a starter default reopen as saved, so the file's active setup still matches.
const tuned = structuredClone(original);
Object.assign(tuned.solve_params, { magnet_temperature_C: 80, mechanical_loss_W: 15, max_nonlinear_iterations: 120 });
const tunedSetup = captureProfile(tuned, 'Tuned', true, 'magneto2d', 'tuned');
const tunedFile = parseDesignFile(serializeDesignFile(tuned, 'Tuned', saveProfile(newProfileDocument('tuned'), tunedSetup))).config;
for (const key of ['magnet_temperature_C', 'mechanical_loss_W', 'max_nonlinear_iterations']) {
  assert.equal(tunedFile.solve_params[key], tuned.solve_params[key], `${key} reopens as saved`);
}
assert.ok(profileMatches(tunedSetup, tunedFile, 'magneto2d'));
// An unset iteration limit stays unset, so Elmer keeps its frozen limit.
const defaultNumerics = captureProfile(original, 'Default numerics', true, 'elmer', 'numerics');
assert.equal(defaultNumerics.parameters.max_nonlinear_iterations, null);
assert.equal('max_nonlinear_iterations' in applyProfile(tuned, defaultNumerics).solve_params, false);
assert.ok(profileMatches(defaultNumerics, applyProfile(tuned, defaultNumerics), 'elmer'));
assert.equal(parseProfileDocument(saveProfile(newProfileDocument('n'), defaultNumerics)).profiles[0].parameters.max_nonlinear_iterations, null);
// A setup captured with the map off leaves the design's drive limits in place.
const mapOff = captureProfile(original, 'Map off', false, 'magneto2d', 'map-off');
assert.equal(mapOff.map, null);
const limited = structuredClone(original); limited.torque_speed_analysis = torqueSpeedSettings(original);
// The map's DC bus is the design's supply voltage: one value, wherever it is shown (#274).
{
  assert.equal(DEFAULT_DC_BUS_V, 48);
  assert.equal(designDcBusV(original), 48);
  assert.equal(torqueSpeedSettings(original).limits.dc_bus_V, 48);
  const supplied = structuredClone(original); supplied.solve_params.motor_input_dc_bus_V = 96;
  assert.equal(torqueSpeedSettings(supplied).limits.dc_bus_V, 96);
  // Map settings stored at another bus follow the design's.
  const stale = structuredClone(supplied); stale.torque_speed_analysis = torqueSpeedSettings(original);
  assert.equal(torqueSpeedSettings(stale).limits.dc_bus_V, 96);
  assert.equal(torqueSpeedSettings(stale).limits.peak_current_A, stale.torque_speed_analysis.limits.peak_current_A);
  // A design saved before Operating point had the input keeps the bus its map settings named.
  const older = structuredClone(original);
  older.torque_speed_analysis = { ...torqueSpeedSettings(original), limits: { ...torqueSpeedSettings(original).limits, dc_bus_V: 200 } };
  assert.equal(designDcBusV(older), 200);
  assert.equal(torqueSpeedSettings(older).limits.dc_bus_V, 200);
  assert.equal(torqueSpeedSettings(older), older.torque_speed_analysis, 'settings already on the design bus are returned as stored');
}
assert.deepEqual(applyProfile(limited, mapOff).torque_speed_analysis, limited.torque_speed_analysis);
assert.ok(profileMatches(mapOff, applyProfile(limited, mapOff), 'magneto2d'));
// An operating-only setup records the design's analyses whichever solver is selected.
const analyses = structuredClone(original); Object.assign(analyses.solve_options, { cogging_torque: true, losses_efficiency: true });
const rated = captureProfile(analyses, 'Rated', false, 'elmer', 'rated');
assert.equal(rated.outputs.cogging_torque, true);
assert.equal(rated.outputs.losses_efficiency, true);
assert.ok(profileMatches(rated, analyses, 'magneto2d') && profileMatches(rated, analyses, 'elmer'), 'switching solver does not modify it');
// Published references solve on Magneto2D, so an imported Elmer reference setup is not read.
const { builtin: _builtin, ...importedReference } = { ...structuredClone(builtins[0]), id: 'imported' };
assert.equal(parseProfileDocument({ ...newProfileDocument('prius'), profiles: [importedReference] }).profiles.length, 1);
assert.throws(() => parseProfileDocument({ ...newProfileDocument('prius'), profiles: [{ ...importedReference, solver: 'elmer' }] }), /invalid saved run setup/);
// Setups this version cannot read are skipped with a notice; the motor and the rest still open.
const future = structuredClone(doc);
future.profiles.push({ ...structuredClone(future.profiles[0]), id: 'future', name: 'From a newer version',
  parameters: { ...future.profiles[0].parameters, future_setting: 1 } });
const futureFile = parseDesignFile(serializeDesignFile(changed, 'Motor', future));
assert.equal(futureFile.runSetups.profiles.length, doc.profiles.length);
assert.match(futureFile.runSetupsNotice, /One saved run setup could not be read/);
const unsupported = parseDesignFile(serializeDesignFile(changed, 'Motor', { ...doc, schema: 2 }));
assert.equal(unsupported.runSetups, undefined);
assert.match(unsupported.runSetupsNotice, /cannot read/);
assert.equal(physical(unsupported.config), physical(changed));
assert.equal(parseDesignFile(serializeDesignFile(original, 'Old file')).runSetupsNotice, null);
const { activeId: _activeId, activeVersion: _activeVersion, ...withoutActive } = doc;
assert.equal(readProfileDocument(withoutActive).document.activeId, null, 'a library without an active setup still opens');
// Opening an older copy keeps setups and versions saved since; same-named setups are not duplicated.
const olderCopy = saveProfile(newProfileDocument('motor-1'), user);
const newerLibrary = saveProfile(saveProfile(newProfileDocument('motor-1'),
  captureProfile(changed, 'Rated speed', false, 'magneto2d', 'user-1', 2)), captureProfile(original, 'Second', false, 'magneto2d', 'user-2'));
for (const [local, incoming] of [[newerLibrary, olderCopy], [olderCopy, newerLibrary]]) {
  assert.deepEqual(mergeProfileDocuments(local, incoming).profiles.map(p => [p.id, p.version]), [['user-1', 2], ['user-2', 1]]);
}
const sameName = saveProfile(newProfileDocument('motor-1'), captureProfile(original, 'Second', false, 'magneto2d', 'user-3'));
assert.deepEqual(mergeProfileDocuments(sameName, newerLibrary).profiles.map(p => p.id).sort(), ['user-1', 'user-3'], 'identical settings are not copied');
// Separately edited setups are added as renamed copies, never dropped silently.
const mine = saveProfile(newProfileDocument('motor-1'), captureProfile(changed, 'Rated speed', false, 'magneto2d', 'user-1', 2));
const theirs = { ...newProfileDocument('motor-1'), profiles: [captureProfile(heated, 'Rated speed', false, 'magneto2d', 'user-1', 2)] };
const merged = mergeProfileDocuments(mine, theirs);
assert.deepEqual(merged.profiles.map(p => p.name), ['Rated speed', 'Rated speed (from file)']);
assert.notEqual(merged.profiles[1].id, 'user-1', 'the copy has its own identity');
assert.equal(mergeProfileDocuments(merged, theirs).profiles.length, 2, 'reopening the file adds no further copy');
const otherSecond = { ...newProfileDocument('motor-1'), profiles: [captureProfile(heated, 'Second', false, 'magneto2d', 'user-9')] };
assert.deepEqual(mergeProfileDocuments(sameName, otherSecond).profiles.map(p => p.name), ['Second', 'Second (from file)']);
// Browser storage keeps what it cannot read and leaves no entry for an empty library.
const store = new Map();
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
  getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => { store.set(k, String(v)); }, removeItem: k => { store.delete(k); },
} });
const { profileScopeForFile, loadProfileDocument, storeProfileDocument, readStoredProfileDocument, newSessionProfileDocument, keepProfileScope }
  = await importTypeScriptModule(new URL('../src/public/profileStorage.ts', import.meta.url));
assert.ok(storeProfileDocument(newProfileDocument('empty-design')));
assert.equal(store.size, 0, 'an empty library leaves no browser entry');
assert.ok(storeProfileDocument({ ...newProfileDocument('prius'), activeId: 'builtin:prius-2004-tutorial-bemf-v1', activeVersion: 1 }));
assert.equal(loadProfileDocument('prius').activeId, 'builtin:prius-2004-tutorial-bemf-v1', 'a selected reference setup is remembered');
// A library this version cannot fully read is never written over; this version keeps its own copy.
const futureText = JSON.stringify(future);
store.set('coilem.run-setups.v1:motor-1', futureText);
const partial = loadProfileDocument('motor-1');
assert.equal(partial.profiles.length, doc.profiles.length, 'one unreadable setup does not discard the library');
assert.ok(storeProfileDocument({ ...partial, activeId: null, activeVersion: null }));
assert.equal(store.get('coilem.run-setups.v1:motor-1'), futureText, 'the newer library is left as it is');
assert.equal(loadProfileDocument('motor-1').activeId, null, "this version's own copy is read back");
store.set('coilem.run-setups.v1:broken', '{not json');
assert.equal(loadProfileDocument('broken').profiles.length, 0);
assert.ok(storeProfileDocument(saveProfile(newProfileDocument('broken'), user)));
assert.equal(store.get('coilem.run-setups.v1:broken'), '{not json');
assert.equal(readStoredProfileDocument('motor-1', futureText), undefined, 'another window adopts only a library it can fully read');
assert.deepEqual(readStoredProfileDocument('motor-1', JSON.stringify(doc)), doc);
// A design that exists only in this window stores its library once its file is saved.
const session = newSessionProfileDocument(doc);
const entries = store.size;
assert.ok(storeProfileDocument(session));
assert.equal(store.size, entries, 'an unsaved design leaves no browser entry');
keepProfileScope(session.scope);
assert.ok(storeProfileDocument(session));
assert.equal(loadProfileDocument(session.scope).profiles.length, doc.profiles.length);
assert.equal(await profileScopeForFile('motor A'), await profileScopeForFile('motor A'));
assert.notEqual(await profileScopeForFile('motor A'), await profileScopeForFile('motor B'));
console.log('Solve profiles: complete reference settings, unset catalogue defaults, ordinary accuracy separation, immutable provenance, compatibility, tolerant reading, library merge, storage and file round-trip passed.');
