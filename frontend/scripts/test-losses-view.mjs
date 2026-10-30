import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  DQ_FLUX_LINKAGE_STATUS_REASON,
  MAGNET_TEMPERATURE_STATUS_REASON,
  PHASE_RESISTANCE_STATUS_REASON,
  PHASE_RESISTANCE_UNRECORDED_STATUS_REASON,
} = await importTypeScriptModule(new URL('../src/public/outputStatus.ts', import.meta.url));

const { STEEL_RAMP, densityColor, formatPower, lossesView, lossSegments, rampColor, stackCopperWPerKg } = await importTypeScriptModule(
  new URL('../src/public/lossesView.ts', import.meta.url),
);

// A motoring point: 10 N·m at 3,000 rpm, 20 A rms through 50 mΩ, 40 W of iron loss.
const omega = 3000 * 2 * Math.PI / 60;
const copper = 3 * 20 ** 2 * 0.05;
const loss = {
  speed_rpm: 3000,
  phase_current_rms_A: 20,
  electromagnetic_torque_Nm: 10,
  shaft_torque_Nm: 10 - 50 / omega,
  electromagnetic_power_W: 10 * omega,
  phase_resistance_ohm: 0.05,
  winding_temperature_C: 80,
  copper_loss_W: copper,
  copper_active_loss_W: copper * 0.6,
  copper_end_winding_loss_W: copper * 0.4,
  iron_loss_W: 40,
  iron_hysteresis_loss_W: 30,
  iron_eddy_loss_W: 10,
  iron_loss_status: 'experimental',
  iron_loss_status_reason: 'Grade limits.',
  mechanical_loss_W: 10,
  total_loss_W: copper + 50,
  shaft_power_W: 10 * omega - 50,
  input_power_W: 10 * omega + copper,
  efficiency_pct: 100 * (10 * omega - 50) / (10 * omega + copper),
  efficiency_status: 'experimental',
  efficiency_status_reason: 'Uses the experimental iron loss.',
};
const iron = {
  status: 'experimental', model: 'grade_limit_harmonic_steinmetz', steel: 'M350-50A',
  iron_teeth_loss_W: 25, iron_yoke_loss_W: 15,
  share_above_validated_frequency: 0.012, share_above_validated_flux_density: 0.69,
  validated_max_frequency_Hz: 1000, validated_max_flux_density_T: 1.5,
};

const view = lossesView(loss, iron);
assert.equal(view.efficiency.text, '96.6%'); // 3,091.6 W shaft of 3,201.6 W input
assert.equal(view.efficiency.status, 'experimental');
assert.deepEqual(view.rows.map((row) => row.key), ['input', 'shaft', 'torque', 'copper', 'iron', 'mechanical', 'total']);
assert.equal(view.rows.find((row) => row.key === 'copper').value, '60');
assert.match(view.rows.find((row) => row.key === 'copper').hint, /3 × \(20 A rms\)² × 50 mΩ at 80 °C/);
assert.equal(view.rows.find((row) => row.key === 'iron').status, 'experimental');
assert.match(view.rows.find((row) => row.key === 'iron').hint, /Teeth 25 W, yoke 15 W\./);
assert.match(view.rows.find((row) => row.key === 'iron').hint, /69% comes from flux densities above 1\.5 T/);
assert.match(view.rows.find((row) => row.key === 'torque').hint, /The solved torque, 10 N·m/);

// Segments follow the five components in order and their shares add to one.
const { segments, totalW } = lossSegments(loss);
assert.deepEqual(segments.map((segment) => segment.key), ['copper_stack', 'copper_end', 'iron_hysteresis', 'iron_eddy', 'mechanical']);
assert.ok(Math.abs(totalW - (copper + 50)) < 1e-9);
assert.ok(Math.abs(segments.reduce((sum, segment) => sum + segment.share, 0) - 1) < 1e-12);
assert.equal(segments[2].color, 'var(--loss-iron-hysteresis)');

// Without iron loss, efficiency is unavailable and says why.
const noIron = lossesView({ ...loss, iron_loss_W: null, iron_hysteresis_loss_W: null, iron_eddy_loss_W: null,
  iron_loss_status: 'unavailable', iron_loss_status_reason: 'Needs one full electrical cycle.',
  efficiency_pct: null, efficiency_status: 'unavailable', efficiency_status_reason: 'Efficiency needs the iron loss.' }, null);
assert.equal(noIron.efficiency.text, '—');
assert.equal(noIron.efficiency.status, 'unavailable');
assert.equal(noIron.rows.find((row) => row.key === 'iron').value, '—');
assert.match(noIron.rows.find((row) => row.key === 'iron').hint, /full electrical cycle/);
assert.equal(lossesView(null, null), null);

assert.deepEqual(formatPower(1234), { value: '1.23', unit: 'kW' });
assert.deepEqual(formatPower(2.527), { value: '2.53', unit: 'W' });
// The iron-loss map runs slate to pale steel: lighter is more loss.
assert.equal(densityColor(0), 'rgb(65, 82, 99)');
assert.equal(densityColor(1), 'rgb(218, 235, 247)');
assert.equal(densityColor(5), densityColor(1), 'values clamp to the scale');
assert.equal(rampColor(['#000000', '#ffffff'], 0.5), 'rgb(128, 128, 128)');
assert.deepEqual([...STEEL_RAMP], ['#415263', '#5d748b', '#7c99b2', '#a5c2d9', '#daebf7']);

// Copper loss per kilogram of stack copper: 12 slots × 40% of 100 mm² × 50 mm of copper = 0.215 kg.
const winding = { conductor: 'copper', copper_fill: 0.4, slot_area_mm2: 100, stack_length_mm: 50 };
const stackKg = 12 * 0.4 * 100e-6 * 0.05 * 8960;
assert.ok(Math.abs(stackCopperWPerKg({ ...loss, copper_active_loss_W: 10 }, winding, 12) - 10 / stackKg) < 1e-9);
assert.ok(Math.abs(stackCopperWPerKg({ ...loss, copper_active_loss_W: 10 }, { ...winding, conductor: 'aluminum' }, 12) - 10 / (stackKg * 2700 / 8960)) < 1e-9);
assert.equal(stackCopperWPerKg(loss, null, 12), null);
assert.equal(stackCopperWPerKg(loss, winding, 0), null);


// Public issue 143: efficiency, iron loss and copper loss each say whether they are qualified, and why.
assert.deepEqual(view.statuses.map((item) => [item.key, item.status]), [['efficiency', 'experimental'], ['iron', 'experimental'], ['copper', 'experimental']]);
assert.equal(view.statuses[0].reason, loss.efficiency_status_reason);
assert.equal(view.statuses[1].reason, loss.iron_loss_status_reason, 'the loss record reason when the iron record has none');
assert.equal(view.statuses[2].reason, PHASE_RESISTANCE_UNRECORDED_STATUS_REASON, 'a run stored before the winding carried a status');
assert.equal(view.rows.find((row) => row.key === 'copper').status, 'experimental', 'the copper row carries the badge');
const recorded = lossesView(loss, iron, { status: 'experimental', status_reason: 'As recorded.' });
assert.equal(recorded.statuses[2].reason, 'As recorded.');
const qualified = lossesView(loss, iron, { status: 'qualified', status_reason: PHASE_RESISTANCE_STATUS_REASON });
assert.deepEqual(qualified.statuses[2], { key: 'copper', label: 'Copper loss, from the phase resistance', status: 'qualified', reason: PHASE_RESISTANCE_STATUS_REASON });
assert.equal(qualified.rows.find((row) => row.key === 'copper').status, 'qualified', 'a qualified winding badges its copper loss');
assert.deepEqual(noIron.statuses.map((item) => item.key), ['copper'], 'no status for an unavailable efficiency or iron loss');

console.log('losses view: rows, efficiency status, bar segments, density scale and copper per kilogram pass');
