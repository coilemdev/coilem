import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const { COGGING_TORQUE_STATUS_REASON } = await importTypeScriptModule(new URL('../src/public/outputStatus.ts', import.meta.url));
const { asPublicConfig } = await importTypeScriptModule(new URL('../src/public/publicRequest.ts', import.meta.url));
const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));
const { COGGING_HARMONIC_BARS, coggingPeriod, coggingPlanNote, coggingView } = await importTypeScriptModule(
  new URL('../src/public/coggingView.ts', import.meta.url),
);

// The 8p/12s example's cogging sweep and the record backend/cogging.py makes of it;
// tests/test_cogging.py checks the record and the PDF and CSV against the same file.
const example = JSON.parse(await readFile(new URL('../../tests/fixtures/cogging_example_8p12s.json', import.meta.url), 'utf8'));
const record = example.record;
const result = {
  summary: { cogging: record },
  cogging_torque_waveform: { electrical_angle_deg: example.electrical_angle_deg, torque_Nm: example.torque_Nm },
};

const significant = (value) => {
  if (value === 0) return '0';
  const magnitude = Math.floor(Math.log10(Math.abs(Number(value.toPrecision(3)))));
  return value.toFixed(Math.max(0, 2 - magnitude)).replace(/^-/, '−');
};

const view = coggingView(result, 8);
const row = (key) => [...view.rows, ...view.noise].find((item) => item.key === key);
// The record's numbers, as the PDF and CSV carry them.
assert.equal(row('peak-to-peak').value, significant(record.peak_to_peak_Nm));
assert.equal(row('peak').value, significant(record.peak_Nm));
assert.equal(row('first-harmonic').value, significant(record.first_harmonic_Nm));
assert.equal(row('first-harmonic').label, 'Fundamental, 24/rev');
assert.equal(row('loaded-share').value, significant(record.peak_to_peak_of_loaded_pct));
assert.equal(row('loaded-share').unit, '%');
assert.equal(row('positions').value, String(record.positions_per_period));
assert.equal(row('mean').value, significant(record.mean_Nm));
assert.equal(row('end-mismatch').value, significant(record.endpoint_mismatch_Nm));
assert.equal(view.period, '60° elec · 15° mech');
assert.deepEqual(view.status, { status: 'experimental', reason: COGGING_TORQUE_STATUS_REASON });
// The fundamental and its next multiples, as bars scaled to the largest.
assert.equal(view.harmonics.length, Math.min(COGGING_HARMONIC_BARS, record.harmonics.length));
assert.deepEqual(view.harmonics.slice(0, 3).map((harmonic) => harmonic.order), [24, 48, 72]);
assert.ok(view.harmonics.every((harmonic) => harmonic.share >= 0 && harmonic.share <= 1));
assert.ok(view.harmonics.some((harmonic) => harmonic.share === 1));
// One period in both angle units: 4 pole pairs, so 60° electrical is 15° mechanical.
assert.equal(view.waveform.mechanicalDeg.at(-1), 15);
assert.deepEqual(view.waveform.electricalDeg, example.electrical_angle_deg);

// A run without a loaded torque says so instead of a percentage.
const open = coggingView({ summary: { cogging: { ...record, peak_to_peak_of_loaded_pct: null, loaded_mean_torque_Nm: null } } }, 8);
assert.equal(open.rows.find((item) => item.key === 'loaded-share').value, '—');
assert.match(open.rows.find((item) => item.key === 'loaded-share').hint, /comparison unavailable/);
for (const reason of ['Loaded torque was not requested.', 'No loaded torque (0 A run).', 'Loaded mean torque is near zero.']) {
  const unavailable = coggingView({ summary: { cogging: { ...record, peak_to_peak_of_loaded_pct: null, loaded_comparison_reason: reason } } }, 8);
  assert.equal(unavailable.rows.find((item) => item.key === 'loaded-share').hint, reason);
}
assert.equal(open.waveform, null);
assert.equal(coggingView({ summary: { cogging: null } }, 8), null);

const reused = coggingView({ summary: { cogging: { ...record, endpoint_mismatch_Nm: null } } }, 8);
const mismatch = reused.noise.find((item) => item.key === 'end-mismatch');
assert.equal(mismatch.value, '—');
assert.match(mismatch.hint, /Unavailable.*share a mesh or solution/);

// An imported design may carry cogging while Elmer is selected. Both request
// paths must omit it, without losing the user's choice when returning to Magneto2D.
const config = cloneDefaultConfig();
config.solve_options.cogging_torque = true;
assert.equal(asPublicConfig(config, 'magneto2d').solve_options.cogging_torque, true);
assert.equal(asPublicConfig(config, 'elmer').solve_options.cogging_torque, false);
assert.equal(config.solve_options.cogging_torque, true);

assert.deepEqual(coggingPeriod(12, 8), { elecDeg: 60, mechDeg: 15, order: 24 });
assert.deepEqual(coggingPeriod(48, 8), { elecDeg: 30, mechDeg: 7.5, order: 48 });
assert.equal(coggingPeriod(0, 8), null);
assert.equal(
  coggingPlanNote(12, 8, 24),
  'Adds a no-current sweep over one cogging period (60° electrical, 15° mechanical), at 24 positions plus the repeated end. '
    + 'Experimental: no cogging benchmark gate yet.',
);
assert.doesNotMatch(coggingPlanNote(12, 8), /positions/);
// Without corner refinement the note says to turn it on.
assert.match(coggingPlanNote(12, 8, 24, false), /Corner refinement is off, which makes cogging much noisier; turn it on under Advanced options\.$/);
assert.doesNotMatch(coggingPlanNote(12, 8, 24, true), /Corner refinement/);

console.log('cogging view: record values, harmonics, angle units, status and plan note pass');
