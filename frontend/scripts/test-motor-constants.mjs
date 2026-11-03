import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  CONSISTENCY_MAX_CURRENT_ANGLE_DEG,
  CONSISTENCY_TOLERANCE_PCT,
  consistencyNotApplicable,
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

// Kt shows once, per rms A = √2 × the stored per-peak-A value, which is the hover hint.
assert.equal(shown(view.kt), '0.407', 'Kt per rms A');
close(view.kt.value, kt * Math.SQRT2, 'Kt per rms A');
assert.equal(view.kt.unit, 'N·m/A rms');
assert.equal(view.kt.siHint, '0.288 N·m/A per peak ampere (SI)');

// Ke in V/krpm line-to-line rms, derived independently: at 1,000 rpm the
// per-phase peak EMF is Ke·ω, its rms is ÷√2, and line-to-line is ×√3.
const omegaAt1000Rpm = 1000 * 2 * Math.PI / 60;
const lineRmsAt1000Rpm = Math.sqrt(3) * (ke * omegaAt1000Rpm) / Math.SQRT2;
close(view.ke.value, lineRmsAt1000Rpm, 'Ke V/krpm L-L rms');
assert.equal(shown(view.ke), '25.8');
assert.equal(view.ke.unit, 'V/krpm L-L rms');
assert.equal(view.ke.siHint, '0.201 V·s/rad, phase peak per mechanical rad/s (SI)');
assert.equal(view.lambdaPm.siHint, undefined, 'only Kt and Ke carry an SI hint');

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
assert.equal(shown(sixStep.kt), '—');
assert.equal(sixStep.kt.siHint, undefined, 'no hint without a value');
assert.equal(shown(sixStep.consistency), '—');
assert.equal(sixStep.consistencyStatus, 'unavailable');
assert.equal(shown(sixStep.ke), '25.8');
assert.equal(motorConstantsView({ Kt_Nm_per_A: kt, Ke_Vs_per_rad_mech: 0 }).consistencyStatus, 'unavailable', 'no Ke, no ratio');

// Negative torque (a generating current angle) keeps its sign, with a true minus.
const generating = motorConstantsView({ Kt_Nm_per_A: -kt, Ke_Vs_per_rad_mech: ke });
assert.equal(shown(generating.kt), '−0.407');
assert.equal(generating.kt.siHint, '−0.288 N·m/A per peak ampere (SI)');
assert.equal(generating.consistencyStatus, 'check');

// The check assumes q-axis current and magnet torque only. The Pyleecan Prius loaded case
// runs at γ 50° with saliency 1.73: 118% there is reluctance torque, not an error, so it
// shows without a badge and a note points to the Torque–λdq agreement.
const priusKt = 353.95 / 250;
const priusKe = 4 * 0.1995;
const prius = motorConstantsView({
  Kt_Nm_per_A: priusKt, Ke_Vs_per_rad_mech: priusKe,
  dq_flux_linkage: { torque_agreement_pct: 99.96, current_angle_deg: 49.9997, apparent_L_d_H: 1.20e-3, apparent_L_q_H: 2.07e-3 },
});
assert.equal(shown(prius.consistency), '118.3');
assert.equal(prius.consistencyStatus, 'not-applicable');
assert.match(prius.consistencyNote, /current is at 50\.0°/);
assert.match(prius.consistencyNote, /saliency Lq\/Ld 1\.72/, "2.07 / 1.20 mH");
assert.match(prius.consistencyNote, /Torque–λdq agreement/);
assert.doesNotMatch(consistencyNotApplicable({ current_angle_deg: 30, apparent_L_d_H: 4.7e-5, apparent_L_q_H: 4.8e-5 }), /saliency/,
  'a surface-magnet rotor at 30° loses cos γ of its magnet torque but adds no reluctance torque');
// On the q-axis even an IPM has no d-axis current and so no reluctance torque: the check applies.
assert.equal(motorConstantsView({ Kt_Nm_per_A: kt, Ke_Vs_per_rad_mech: ke, dq_flux_linkage: { current_angle_deg: 0.0 } }).consistencyStatus, 'ok');
assert.equal(motorConstantsView({ Kt_Nm_per_A: kt, Ke_Vs_per_rad_mech: ke, dq_flux_linkage: { current_angle_deg: 4.9 } }).consistencyStatus, 'ok');
assert.equal(motorConstantsView({ Kt_Nm_per_A: kt, Ke_Vs_per_rad_mech: ke }).consistencyNote, null, 'no d/q record: the check stands');
assert.equal(CONSISTENCY_MAX_CURRENT_ANGLE_DEG, 5);

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
