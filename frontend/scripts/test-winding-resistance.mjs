import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  formatResistance,
  readWindingResistance,
  resistanceAt,
  windingReadout,
} = await importTypeScriptModule(new URL('../src/public/windingResistance.ts', import.meta.url));

// The Honda Accord as built (#136): 1.55 mm wire, 416 turns per phase in 8 paths.
const accord = {
  wire_source: 'specified',
  conductor: 'copper',
  strand_diameter_mm: 1.55,
  strands_in_hand: 1,
  turn_copper_area_mm2: 1.887,
  conductors_per_slot: 104,
  series_turns_per_phase: 416,
  parallel_paths: 8,
  slot_area_mm2: 470.2,
  copper_fill: 0.417,
  copper_fill_limit: 0.45,
  wire_fill: null,
  fits: true,
  stack_length_mm: 40.1,
  end_turn_length_mm: 42.1,
  mean_turn_length_mm: 164.4,
  active_fraction: 0.488,
  phase_resistance_20C_ohm: 0.009761,
  temperature_coefficient_per_K: 0.00393,
  winding_temperature_C: 20,
  phase_resistance_ohm: 0.009761,
  notes: [],
};

const record = readWindingResistance(accord);
assert.ok(record, 'a complete record reads');
assert.equal(readWindingResistance({ ...accord, phase_resistance_20C_ohm: 'x' }), null, 'a malformed record is refused');
assert.equal(readWindingResistance(null), null);

// R(T) = R20 · (1 + α (T − 20)), so 120 °C adds 39.3 %.
assert.ok(Math.abs(resistanceAt(record, 120) - 0.009761 * 1.393) < 1e-12);
assert.equal(formatResistance(0.009761), '9.76 mΩ');
assert.equal(formatResistance(1.234), '1.23 Ω');

const cold = windingReadout(record, 20);
assert.deepEqual(cold.map((row) => row.key), ['fill', 'resistance', 'turn']);
assert.equal(cold[0].text, '42% Cu');
assert.equal(cold[1].text, '9.76 mΩ');
assert.equal(cold[1].tag, '20 °C');
assert.equal(cold[2].text, '164 mm');
assert.match(cold[1].hint, /416 turns per phase in 8 paths/);
const hot = windingReadout(record, 120);
assert.equal(hot[1].text, '13.6 mΩ');
assert.equal(hot[1].tag, '120 °C');

const crowded = windingReadout({ ...record, fits: false, copper_fill: 0.6 }, 20);
assert.equal(crowded[0].warning, true, 'an over-full slot is flagged');
const derived = windingReadout({ ...record, wire_source: 'derived', strand_diameter_mm: 0.94 }, 20);
assert.match(derived[1].hint, /^Derived 0\.94 mm wire\./);

console.log('winding resistance: reading, temperature, formatting and fill warning pass');
