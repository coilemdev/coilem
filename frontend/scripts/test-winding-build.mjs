import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  WIRE_FILL_COMFORTABLE,
  WIRE_FILL_LIMIT,
  endTurnOverhangMm,
  insulatedDiameterMm,
  insulatedWireFill,
  suggestedStrands,
  windingBuildChecks,
} = await importTypeScriptModule(new URL('../src/public/windingBuild.ts', import.meta.url));

const record = (overrides = {}) => ({
  wire_source: 'specified',
  conductor: 'copper',
  strand_diameter_mm: 1,
  strands_in_hand: 1,
  turn_copper_area_mm2: Math.PI / 4,
  conductors_per_slot: 30,
  series_turns_per_phase: 60,
  parallel_paths: 1,
  slot_area_mm2: 100,
  copper_fill: 0.2356,
  copper_fill_limit: 0.45,
  wire_fill: null,
  fits: true,
  stack_length_mm: 100,
  end_turn_length_mm: 62.83,
  mean_turn_length_mm: 325.7,
  active_fraction: 0.61,
  phase_resistance_20C_ohm: 0.1,
  temperature_coefficient_per_K: 0.00393,
  winding_temperature_C: 20,
  phase_resistance_ohm: 0.1,
  notes: [],
  ...overrides,
});
const titles = (input) => windingBuildChecks({ slotMouthMm: 3, windingType: 'distributed', toothWidthMm: 10, ...input }).map((check) => check.title);

// Grade 2 enamel on common sizes, to a few hundredths of a millimetre.
assert.ok(Math.abs(insulatedDiameterMm(1) - 1.093) < 0.01);
assert.ok(Math.abs(insulatedDiameterMm(0.5) - 0.566) < 0.02);
// 30 conductors of 1 mm wire in 100 mm²: 28% with enamel; the preview's own figure wins when it gives one.
assert.ok(Math.abs(insulatedWireFill(record()) - 0.2788) < 0.005);
assert.equal(insulatedWireFill(record({ wire_fill: 0.5 })), 0.5);
// A half-circle end turn 62.83 mm long stands 20 mm proud.
assert.ok(Math.abs(endTurnOverhangMm(record()) - 20) < 0.01);

// A wire with room: fits, passes the mouth, nothing else to say.
assert.deepEqual(titles({ record: record() }), ['Wire fits the slot', 'Wire passes the slot mouth']);
// Fill above the comfortable share is tight; above the limit it will not go in.
assert.ok(WIRE_FILL_COMFORTABLE < WIRE_FILL_LIMIT);
assert.equal(titles({ record: record({ wire_fill: 0.6 }) })[0], 'Slot is tight to wind');
assert.equal(titles({ record: record({ wire_fill: 0.8 }) })[0], 'Too much wire for the slot');
// The wire has to pass the slot mouth with its liner.
assert.equal(titles({ record: record(), slotMouthMm: 1.2 })[1], 'Wire does not pass the slot mouth');
// Thick single strands, and wire bent tightly round a narrow tooth, are flagged as stiff.
assert.ok(titles({ record: record({ strand_diameter_mm: 2 }), slotMouthMm: 6 }).includes('Wire is stiff to form'));
assert.ok(titles({ record: record(), windingType: 'concentrated', toothWidthMm: 3 }).includes('Wire is stiff to form'));
// A derived wire is a suggestion: the same copper as strands in hand that pass the slot mouth and lay easily.
const suggest = (overrides, slotMouthMm) => windingBuildChecks({ record: record({ wire_source: 'derived', copper_fill: 0.45, ...overrides }), slotMouthMm, windingType: 'distributed', toothWidthMm: 10 });
assert.deepEqual(suggestedStrands(1.2, 3), { strands: 1, strandDiameterMm: 1.2 });
const split = suggestedStrands(3.02, 3);
assert.equal(split.strands, 6);
assert.ok(split.strandDiameterMm <= 1.25 && Math.abs(split.strands * split.strandDiameterMm ** 2 - 3.02 ** 2) < 1e-9, 'same copper');
assert.equal(suggestedStrands(3, 0.1), null);
const derived = suggest({ strand_diameter_mm: 3.02 }, 3);
assert.equal(derived.length, 1);
assert.match(derived[0].title, /^Suggested wire: 6 × 1\.23 mm$/);
assert.equal(derived[0].severity, 'positive');
assert.equal(suggest({ strand_diameter_mm: 3 }, 0.1)[0].title, 'No wire passes the slot mouth');

console.log('winding build checks passed');
