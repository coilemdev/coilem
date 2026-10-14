// The guided repair mirrors the backend's tooth-coil rules (#91): which concentrated
// layouts balance, and how many coils per phase the parallel paths must divide.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { coilsPerPhase, concentratedGuidedLayoutIsBalanced, concentratedUsesToothCoils, repairGuidedSection } =
  await importTypeScriptModule(new URL('../src/public/guidedConfigRepair.ts', import.meta.url));
const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));

// Every layout the backend can wind, shared with tests/test_tooth_coil_windings.py and Magneto2D.
const layouts = JSON.parse(
  await readFile(new URL('../../tests/fixtures/tooth_coil_layouts.json', import.meta.url), 'utf8'),
).cases;
assert.ok(layouts.length > 0);
for (const { slot_count: slots, pole_count: poles, layers, slots: sides } of layouts) {
  const label = `${slots}s${poles}p layers=${layers}`;
  assert.ok(concentratedUsesToothCoils(slots, poles), label);
  assert.ok(concentratedGuidedLayoutIsBalanced(slots, poles, layers), label);
  // Each coil puts one go side in its own tooth's slot.
  const goSides = layers >= 2 ? slots : slots / 2;
  assert.equal(coilsPerPhase(slots, poles, 'concentrated', layers), goSides / 3, label);
  assert.equal(sides.length, slots, label);
}

// An odd slot count can only be wound with two layers.
assert.equal(concentratedGuidedLayoutIsBalanced(27, 24, 1), false);
assert.equal(concentratedGuidedLayoutIsBalanced(27, 24, 2), true);
// q >= 1 keeps the whole-slot map; slot counts the phases cannot share never balance.
assert.equal(concentratedUsesToothCoils(12, 4), false);
assert.equal(concentratedGuidedLayoutIsBalanced(12, 4, 1), true);
assert.equal(concentratedGuidedLayoutIsBalanced(10, 8, 2), false);

// The Accord's 24s16p double layer has 8 coils per phase, so 8 parallel paths stay.
const accord = cloneDefaultConfig();
accord.stator.slot_count = 24;
accord.rotor.pole_count = 16;
accord.winding.type = 'concentrated';
accord.winding.layers = 2;
accord.winding.parallel_paths = 8;
assert.deepEqual(repairGuidedSection(accord, 'winding').adjustments, []);
// One layer winds alternate teeth: 4 coils per phase, so 8 paths drop to 4.
accord.winding.layers = 1;
assert.deepEqual(
  repairGuidedSection(accord, 'winding').adjustments.map(({ field, next }) => [field, next]),
  [['winding.parallel_paths', 4]],
);

console.log(`tooth-coil guided repair: ${layouts.length} shared layouts OK`);
