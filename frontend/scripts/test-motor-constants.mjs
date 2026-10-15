import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  CONSISTENCY_TOLERANCE_PCT,
  formatSignificant,
  hasMotorConstants,
  motorConstantsView,
} = await importTypeScriptModule(new URL('../src/public/machineConstants.ts', import.meta.url));

const shown = (item) => item.text;
const close = (actual, expected, message) => assert.ok(Math.abs(actual - expected) <= 1e-9 * Math.abs(expected), `${message}: ${actual} vs ${expected}`);

// The default example run in #99: 30 A rms, 2,400 rpm, 0°, 8 poles.
const kt = 0.288;
const ke = 0.201;
const view = motorConstantsView({ Kt_Nm_per_A: kt, Ke_Vs_per_rad_mech: ke, lambda_pm_Wb: 0.0501 });

assert.deepEqual(view.kt.map(shown), ['0.288', '0.407'], 'Kt per peak A, and per rms A = √2 × per peak A');
close(view.kt[1].value, kt * Math.SQRT2, 'Kt per rms A');
assert.deepEqual(view.kt.map((item) => item.unit), ['N·m/A pk', 'N·m/A rms']);

// Ke in V/krpm line-to-line rms, derived independently: at 1,000 rpm the
// per-phase peak EMF is Ke·ω, its rms is ÷√2, and line-to-line is ×√3.
const omegaAt1000Rpm = 1000 * 2 * Math.PI / 60;
const lineRmsAt1000Rpm = Math.sqrt(3) * (ke * omegaAt1000Rpm) / Math.SQRT2;
close(view.ke[1].value, lineRmsAt1000Rpm, 'Ke V/krpm L-L rms');
assert.deepEqual(view.ke.map(shown), ['0.201', '25.8']);
assert.deepEqual(view.ke.map((item) => item.unit), ['V·s/rad', 'V/krpm L-L rms']);

assert.equal(shown(view.lambdaPm), '50.1', 'λpm in mWb');
assert.equal(view.lambdaPm.unit, 'mWb');

// T·ω = 1.5·E_pk·I_pk, so Kt = 1.5·Ke; the check is their ratio as a percentage.
close(view.consistency.value, kt / (1.5 * ke) * 100, 'consistency');
assert.equal(shown(view.consistency), '95.5');
assert.equal(view.consistencyStatus, 'ok');
// A #80-type error, Ke read at half, would show about 200%.
assert.equal(motorConstantsView({ Kt_Nm_per_A: kt, Ke_Vs_per_rad_mech: ke / 2 }).consistencyStatus, 'check');

// OK within ±10 points of 100%, inclusive.
assert.equal(CONSISTENCY_TOLERANCE_PCT, 10);
const statusAt = (percent) => motorConstantsView({ Kt_Nm_per_A: 1.5 * 0.2 * percent / 100, Ke_Vs_per_rad_mech: 0.2 }).consistencyStatus;
assert.equal(statusAt(90), 'ok');
assert.equal(statusAt(110), 'ok');
assert.equal(statusAt(89.9), 'check');
assert.equal(statusAt(110.1), 'check');

// Six-step and no-load runs report no Kt: no consistency either, Ke and λpm stay.
const sixStep = motorConstantsView({ Kt_Nm_per_A: null, Ke_Vs_per_rad_mech: ke, lambda_pm_Wb: 0.0501 });
assert.deepEqual(sixStep.kt.map(shown), ['—', '—']);
assert.equal(shown(sixStep.consistency), '—');
assert.equal(sixStep.consistencyStatus, 'unavailable');
assert.deepEqual(sixStep.ke.map(shown), ['0.201', '25.8']);
assert.equal(motorConstantsView({ Kt_Nm_per_A: kt, Ke_Vs_per_rad_mech: 0 }).consistencyStatus, 'unavailable', 'no Ke, no ratio');

// Negative torque (a generating current angle) keeps its sign, with a true minus.
const generating = motorConstantsView({ Kt_Nm_per_A: -kt, Ke_Vs_per_rad_mech: ke });
assert.equal(shown(generating.kt[0]), '−0.288');
assert.equal(generating.consistencyStatus, 'check');

// Three significant figures, never an exponent; whole numbers keep every digit.
assert.equal(formatSignificant(0.288), '0.288');
assert.equal(formatSignificant(25.7795), '25.8');
assert.equal(formatSignificant(9.996), '10.0', 'rounding up to the next decade keeps three figures');
assert.equal(formatSignificant(0.000123456), '0.000123');
assert.equal(formatSignificant(1282.4), '1282');
assert.equal(formatSignificant(0), '0');

assert.equal(hasMotorConstants({}), false, 'older runs without constants render nothing');
assert.equal(hasMotorConstants({ Kt_Nm_per_A: null, Ke_Vs_per_rad_mech: Number.NaN }), false);
assert.equal(hasMotorConstants({ lambda_pm_Wb: 0.05 }), true);

console.log('motor constants: conversions, formatting and the consistency check pass');
