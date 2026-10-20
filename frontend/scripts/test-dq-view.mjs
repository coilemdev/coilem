import assert from 'node:assert/strict';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const { DQ_AGREEMENT_TOLERANCE_PCT, dqAgreement, dqView } = await importTypeScriptModule(
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
const row = (key) => view.rows.find((item) => item.key === key);
assert.equal(row('gamma').value, '30.0');
assert.equal(row('id').value, '−5.00', 'negative d-axis current keeps a true minus sign');
assert.equal(row('iq').value, '8.66');
assert.equal(row('lambda-d').value, '11.0');
assert.equal(row('lambda-d').unit, 'mWb');
assert.equal(row('lambda-q').value, '0.416');
assert.equal(row('lambda-pm').value, '11.3');
assert.equal(row('ld').value, '0.0472');
assert.equal(row('ld').unit, 'mH');
assert.equal(row('lq').value, '0.0480');
assert.equal(row('torque').value, '0.2926');
assert.match(row('lambda-d').hint, /over 48 rotor positions/);
assert.deepEqual(view.agreement, { ...view.agreement, text: '100.3', status: 'ok' });

// No d-axis current: Ld is not readable, and the hint says how to get it.
const onQAxis = dqView({ ...dq, i_d_A: 0, apparent_L_d_H: null, current_angle_deg: 0 });
assert.equal(onQAxis.rows.find((item) => item.key === 'ld').value, '—');
assert.match(onQAxis.rows.find((item) => item.key === 'ld').hint, /nonzero current angle/);

// The agreement judges the value as shown, at the tolerance edge.
assert.equal(DQ_AGREEMENT_TOLERANCE_PCT, 5);
assert.equal(dqAgreement({ torque_agreement_pct: 95.04 }).status, 'ok');
assert.equal(dqAgreement({ torque_agreement_pct: 94.94 }).status, 'check');
assert.equal(dqAgreement({ torque_agreement_pct: null }).status, 'unavailable');
assert.equal(dqAgreement(null).text, '—');
assert.equal(dqView(null), null);

console.log('d/q view: ok');
