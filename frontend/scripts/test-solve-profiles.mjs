import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';
const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));
const profiles = await importTypeScriptModule(new URL('../src/public/solveProfiles.ts', import.meta.url));
const { parseDesignFile, serializeDesignFile } = await importTypeScriptModule(new URL('../src/public/designFile.ts', import.meta.url));
const { captureProfile, applyProfile, profileMatches, profileCompatible, profileProvenance, builtinProfiles,
  newProfileDocument, saveProfile, parseProfileDocument, restoreActiveProfile, readProfileDocument, mergeProfileDocuments } = profiles;
const original = cloneDefaultConfig();
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
assert.deepEqual(mergeProfileDocuments(sameName, newerLibrary).profiles.map(p => p.id).sort(), ['user-1', 'user-3']);
// Browser storage keeps what it cannot read and leaves no entry for an empty library.
const store = new Map();
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
  getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => { store.set(k, String(v)); }, removeItem: k => { store.delete(k); },
} });
const { profileScopeForFile, loadProfileDocument, storeProfileDocument } = await importTypeScriptModule(new URL('../src/public/profileStorage.ts', import.meta.url));
assert.ok(storeProfileDocument(newProfileDocument('empty-design')));
assert.equal(store.size, 0, 'an empty library leaves no browser entry');
assert.ok(storeProfileDocument({ ...newProfileDocument('prius'), activeId: 'builtin:prius-2004-tutorial-bemf-v1', activeVersion: 1 }));
assert.equal(loadProfileDocument('prius').activeId, 'builtin:prius-2004-tutorial-bemf-v1', 'a selected reference setup is remembered');
store.set('coilem.run-setups.v1:motor-1', JSON.stringify(future));
assert.equal(loadProfileDocument('motor-1').profiles.length, doc.profiles.length, 'one unreadable setup does not discard the library');
assert.equal(store.get('coilem.run-setups.v1:motor-1:unreadable'), JSON.stringify(future), 'what could not be read is kept');
store.set('coilem.run-setups.v1:broken', '{not json');
assert.equal(loadProfileDocument('broken').profiles.length, 0);
assert.equal(store.get('coilem.run-setups.v1:broken:unreadable'), '{not json');
assert.equal(await profileScopeForFile('motor A'), await profileScopeForFile('motor A'));
assert.notEqual(await profileScopeForFile('motor A'), await profileScopeForFile('motor B'));
console.log('Solve profiles: complete reference settings, unset catalogue defaults, ordinary accuracy separation, immutable provenance, compatibility, tolerant reading, library merge, storage and file round-trip passed.');
