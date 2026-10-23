import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  DQ_FLUX_LINKAGE_STATUS_REASON,
  MAGNET_TEMPERATURE_STATUS_REASON,
  PHASE_RESISTANCE_STATUS_REASON,
} = await importTypeScriptModule(new URL('../src/public/outputStatus.ts', import.meta.url));

const { DQ_AGREEMENT_TOLERANCE_PCT, dqAgreement, dqView, isOpenCircuit } = await importTypeScriptModule(
  new URL('../src/public/dqView.ts', import.meta.url),
);

// The 4p12s fixture at 10 A peak and a 30° current angle (#113 validation solve).
const dq = {
  current_angle_convention: 'q_axis_gamma_flux_weakening_positive',
  transform: 'amplitude_invariant_park',
  i_d_A: -5.0000088,
  i_q_A: 8.6602490,
  lambda_d_Wb: 0.0110205,
  lambda_q_Wb: 0.000415939,
  torque_dq_Nm: 0.2925608,
  torque_agreement_pct: 100.3255,
  current_angle_deg: 30.000058,
  lambda_pm_Wb: 0.0112566,
  apparent_L_d_H: 4.7205e-5,
  apparent_L_q_H: 4.8029e-5,
  positions: 48,
};

const view = dqView(dq);
const row = (key) => [...view.main, ...view.detail].find((item) => item.key === key);
// What a designer reads first: the inductances, the saliency and the characteristic current.
assert.deepEqual(view.main.map((item) => item.key), ['ld', 'lq', 'saliency', 'characteristic']);
assert.deepEqual(view.detail.map((item) => item.key), ['gamma', 'id', 'iq', 'lambda-d', 'lambda-q', 'lambda-pm', 'torque']);
assert.equal(view.note, null);
assert.equal(row('ld').value, '0.0472');
assert.equal(row('ld').unit, 'mH');
assert.equal(row('lq').value, '0.0480');
assert.equal(row('saliency').value, '1.02', 'Lq/Ld of a surface-magnet rotor sits near 1');
assert.equal(row('characteristic').value, '238', 'λpm/Ld = 11.26 mWb / 0.0472 mH, in A peak');
assert.equal(row('gamma').value, '30.0');
assert.equal(row('id').value, '−5.00', 'negative d-axis current keeps a true minus sign');
assert.equal(row('iq').value, '8.66');
assert.equal(row('lambda-d').value, '11.0');
assert.equal(row('lambda-q').value, '0.416');
assert.equal(row('lambda-pm').value, '11.3');
assert.equal(row('torque').value, '0.2926');
assert.match(row('lambda-d').hint, /over 48 rotor positions/);
assert.deepEqual(view.agreement, { ...view.agreement, text: '100.3', status: 'ok' });

// In the Solve page's rms units the currents scale by 1/√2; the inductances do not.
const rmsView = dqView(dq, 'A rms');
const rmsRow = (key) => [...rmsView.main, ...rmsView.detail].find((item) => item.key === key);
assert.equal(rmsRow('characteristic').value, '169');
assert.equal(rmsRow('characteristic').unit, 'A rms');
assert.equal(rmsRow('id').value, '−3.54');
assert.equal(rmsRow('ld').value, '0.0472');

// No d-axis current: Ld and what depends on it are left out, and the note says how to get them.
const onQAxis = dqView({ ...dq, i_d_A: 0, apparent_L_d_H: null, current_angle_deg: 0 });
assert.deepEqual(onQAxis.main.map((item) => item.key), ['lq', 'lambda-pm']);
assert.ok(!onQAxis.detail.some((item) => ['ld', 'saliency', 'characteristic'].includes(item.key)));
assert.match(onQAxis.note, /nonzero current angle/);

// An open-circuit (back-EMF) run, like the Pyleecan Prius tutorial case: no current, so
// no current angle, inductance or torque check; the card says so instead of asking for a
// nonzero current angle, and leaves out the empty rows and the agreement.
const noCurrent = {
  ...dq, i_d_A: 3.6e-14, i_q_A: -5.2e-14, lambda_d_Wb: 0.0112566, lambda_q_Wb: 2e-7, torque_dq_Nm: 6e-14,
  torque_agreement_pct: null, current_angle_deg: null, apparent_L_d_H: null, apparent_L_q_H: null,
};
const openCircuit = dqView(noCurrent);
assert.ok(isOpenCircuit(noCurrent));
assert.deepEqual(openCircuit.main.map((item) => item.key), ['lambda-pm']);
assert.deepEqual(openCircuit.detail.map((item) => item.key), ['lambda-d', 'lambda-q']);
assert.equal(openCircuit.agreement, null);
assert.match(openCircuit.note, /Open-circuit run/);
assert.doesNotMatch(openCircuit.note, /nonzero current angle/);
assert.match(openCircuit.detail[0].hint, /Open circuit/);
// A small but real current is still a loaded run.
assert.ok(!isOpenCircuit({ i_d_A: 0, i_q_A: 1e-3 }));
assert.notEqual(dqView({ ...dq, i_d_A: 0, i_q_A: 1e-3 }).agreement, null);

// The agreement judges the value as shown, at the tolerance edge.
assert.equal(DQ_AGREEMENT_TOLERANCE_PCT, 5);
assert.equal(dqAgreement({ torque_agreement_pct: 95.04 }).status, 'ok');
assert.equal(dqAgreement({ torque_agreement_pct: 94.94 }).status, 'check');
assert.equal(dqAgreement({ torque_agreement_pct: null }).status, 'unavailable');
assert.equal(dqAgreement(null).text, '—');
assert.equal(dqView(null), null);


// Public issue 143: the card says the d/q record is experimental, and why.
assert.deepEqual(view.status, { status: 'experimental', reason: DQ_FLUX_LINKAGE_STATUS_REASON }, 'a record stored before it carried a status');
assert.deepEqual(dqView({ ...dq, status: 'qualified', status_reason: 'Gate passed.' }).status, { status: 'qualified', reason: 'Gate passed.' });

console.log('d/q view: ok');
