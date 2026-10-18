import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// A loaded design must describe the geometry its file does. Fields a file
// leaves out must not inherit starter-motor values the backend would not use:
// the SPM 24p example inherited tooth shoes wider than its slot opening.
const { LOADED_STATOR_FALLBACKS, parseDesignFile, serializeDesignFile } = await importTypeScriptModule(
  new URL('../src/public/designFile.ts', import.meta.url),
);
const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));
const SECTIONS = ['stator', 'rotor', 'winding', 'materials', 'solve_params', 'solve_options'];
const SHOE_FIELDS = Object.keys(LOADED_STATOR_FALLBACKS);

function assertShoeFitsSlot(stator, label) {
  // Mirrors StatorConfig.tooth_shoe_must_fit_slot_pitch in backend/models/config.py.
  if (stator.tooth_shoe_enabled) {
    assert.ok(2 * stator.tooth_shoe_overhang_mm < stator.slot_opening_mm, `${label}: tooth shoes close the slot mouth`);
  }
}

const examplesDir = new URL('../src/public/examples/', import.meta.url);
const examples = (await readdir(examplesDir)).filter((name) => name.endsWith('.openem') || name.endsWith('.coilem')).sort();
assert.ok(examples.length >= 3, 'expected the bundled example designs');
for (const name of examples) {
  const file = JSON.parse(await readFile(new URL(name, examplesDir), 'utf8'));
  const { config } = parseDesignFile(JSON.stringify(file));
  for (const section of SECTIONS) {
    for (const [key, value] of Object.entries(file[section] ?? {})) {
      if (config[section][key] === undefined) continue; // not part of the public model
      assert.deepEqual(config[section][key], value, `${name}: ${section}.${key} changed on load`);
    }
  }
  for (const key of SHOE_FIELDS) {
    if (!(key in file.stator)) assert.equal(config.stator[key], LOADED_STATOR_FALLBACKS[key], `${name}: inherited ${key}`);
  }
  assertShoeFitsSlot(config.stator, name);
}

// A design saved before tooth shoes existed loads without them.
const legacy = JSON.parse(serializeDesignFile(cloneDefaultConfig(), 'Before tooth shoes'));
for (const key of SHOE_FIELDS) delete legacy.stator[key];
const legacyStator = parseDesignFile(JSON.stringify(legacy)).config.stator;
assert.equal(legacyStator.tooth_shoe_enabled, false);
assert.equal(legacyStator.slot_opening_mm, legacy.stator.slot_opening_mm);

// A file that enables shoes without sizing them gets the backend's sizes.
const unsized = JSON.parse(JSON.stringify(legacy));
unsized.stator.tooth_shoe_enabled = true;
const unsizedStator = parseDesignFile(JSON.stringify(unsized)).config.stator;
assert.equal(unsizedStator.tooth_shoe_enabled, true);
assert.equal(unsizedStator.tooth_shoe_height_mm, LOADED_STATOR_FALLBACKS.tooth_shoe_height_mm);
assert.equal(unsizedStator.tooth_shoe_overhang_mm, LOADED_STATOR_FALLBACKS.tooth_shoe_overhang_mm);

// New designs and saved designs keep the starter motor's shoes.
const starter = cloneDefaultConfig();
assert.equal(starter.stator.tooth_shoe_enabled, true);
const reopened = parseDesignFile(serializeDesignFile(starter, 'Starter')).config.stator;
for (const key of SHOE_FIELDS) assert.equal(reopened[key], starter.stator[key], `saved design lost ${key}`);
assertShoeFitsSlot(reopened, 'starter motor');

// A file without a stator section still falls back to the whole starter stator.
const statorless = JSON.parse(serializeDesignFile(starter, 'No stator'));
delete statorless.stator;
assert.deepEqual(parseDesignFile(JSON.stringify(statorless)).config.stator, starter.stator);

console.log(`design file defaults passed (${examples.length} bundled examples)`);

// An experimental HoleM50 design keeps its rotor family and pocket parameters,
// which are not part of the default design the section merge starts from.
const prius = JSON.parse(await readFile(new URL('ornl_prius_2004_holem50.coilem', examplesDir), 'utf8'));
const priusRotor = parseDesignFile(JSON.stringify(prius)).config.rotor;
assert.equal(priusRotor.ipm_topology, 'pyleecan_holem50');
for (const [key, value] of Object.entries(prius.rotor).filter(([key]) => key.startsWith('holem50_'))) {
  assert.equal(priusRotor[key], value, `HoleM50 ${key} lost on load`);
}
const reopenedPrius = parseDesignFile(serializeDesignFile(parseDesignFile(JSON.stringify(prius)).config, 'Prius')).config.rotor;
assert.deepEqual(reopenedPrius, priusRotor, 'HoleM50 rotor changed on save and reopen');
// Other rotor families never pick up HoleM50 fields.
const flat = JSON.parse(JSON.stringify(prius));
flat.rotor.ipm_topology = 'flat_buried';
assert.equal(parseDesignFile(JSON.stringify(flat)).config.rotor.holem50_w0_mm, undefined);

// Mesh build: new designs and files saved before it existed use Precise, the
// node placement the benchmark measured; a design saved with Fast keeps it.
assert.equal(cloneDefaultConfig().solve_params.mesh_build, 'precise');
const beforeMeshBuild = JSON.parse(serializeDesignFile(cloneDefaultConfig(), 'Before mesh build'));
delete beforeMeshBuild.solve_params.mesh_build;
assert.equal(parseDesignFile(JSON.stringify(beforeMeshBuild)).config.solve_params.mesh_build, 'precise');
const fastDesign = cloneDefaultConfig();
fastDesign.solve_params.mesh_build = 'fast';
assert.equal(parseDesignFile(serializeDesignFile(fastDesign, 'Fast mesh')).config.solve_params.mesh_build, 'fast');
console.log('mesh build defaults passed');
