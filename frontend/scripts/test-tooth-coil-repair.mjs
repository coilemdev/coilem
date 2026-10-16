// The guided repair mirrors the backend's tooth-coil rules (#91): which concentrated
// layouts balance, and how many coils per phase the parallel paths must divide.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  coilsPerPhase,
  concentratedGuidedLayoutIsBalanced,
  concentratedUsesToothCoils,
  parallelPathsDividing,
  repairGuidedSection,
} = await importTypeScriptModule(new URL('../src/public/guidedConfigRepair.ts', import.meta.url));
const { windingLayerOptions, windingLayerWording } = await importTypeScriptModule(new URL('../src/public/toothCoils.ts', import.meta.url));
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
  // The Layers control offers every layer count the backend winds.
  assert.ok(windingLayerOptions(slots, poles, 'concentrated').find((option) => option.layers === layers).available, label);
}

// The Layers control: tooth coils take one or two layers when they balance,
// whole-slot concentrated maps one, distributed windings either.
const availability = (slots, poles, type) => windingLayerOptions(slots, poles, type)
  .map(({ layers, available, reason }) => [layers, available, reason]);
assert.deepEqual(availability(12, 8, 'concentrated'), [[1, true, null], [2, true, null]]);
assert.deepEqual(availability(27, 24, 'concentrated'), [[1, false, 'unbalanced with 27 slots'], [2, true, null]]);
assert.deepEqual(availability(12, 4, 'concentrated'), [[1, true, null], [2, false, 'needs a fractional-slot layout']]);
assert.deepEqual(availability(24, 8, 'distributed'), [[1, true, null], [2, true, null]]);

// The control is worded by layout (#102): tooth coils in teeth wound, distributed
// windings in coil sides per slot. Whole-slot concentrated maps have one layer only.
const wording = (slots, poles, type) => {
  const { label, choice, summary, hidden } = windingLayerWording(slots, poles, type);
  return [label, choice[1], choice[2], summary[1], summary[2], hidden];
};
assert.deepEqual(wording(12, 8, 'concentrated'), ['Wound teeth', 'Alternate', 'All', 'alternate teeth', 'all teeth', false]);
assert.deepEqual(wording(27, 24, 'concentrated'), ['Wound teeth', 'Alternate', 'All', 'alternate teeth', 'all teeth', false]);
assert.deepEqual(wording(24, 8, 'distributed'), ['Coil sides / slot', '1', '2', '1 coil side', '2 coil sides', false]);
assert.deepEqual(wording(12, 4, 'concentrated'), ['Layers', '1', '2', '1 layer', '2 layers', true]);
assert.match(windingLayerWording(12, 8, 'concentrated').hint, /not in the benchmark yet/);
for (const [slots, poles, type] of [[12, 8, 'concentrated'], [24, 8, 'distributed'], [12, 4, 'concentrated']]) {
  const { choice } = windingLayerWording(slots, poles, type);
  // The select box truncates longer choices.
  assert.ok(Object.values(choice).every((text) => text.length <= 11), `${slots}s${poles}p ${type}`);
}

// Changing layers keeps the parallel paths a divisor of the coils per phase:
// 8p/12s winds 4 coils per phase with two layers and 2 with one.
assert.equal(coilsPerPhase(12, 8, 'concentrated', 2), 4);
assert.equal(coilsPerPhase(12, 8, 'concentrated', 1), 2);
assert.equal(parallelPathsDividing(2, 4), 2);
assert.equal(parallelPathsDividing(4, 4), 4);
assert.equal(parallelPathsDividing(4, 3), 2);
assert.equal(parallelPathsDividing(6, 4), 3);
assert.equal(parallelPathsDividing(5, 2), 1);

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
