/**
 * The loaded d/q operating point of a completed run (#113), as rows for the
 * Results card and an agreement check for the motor-constants table.
 *
 * The backend (backend/dq_flux_linkage.py) Park-transforms the loaded phase
 * flux linkages and the applied phase currents, with the d-axis placed from
 * the no-load flux linkage, and averages over the loaded positions. Its
 * d/q torque, 1.5·P·(λd·iq − λq·id), includes reluctance torque and
 * saturation, so unlike Kt / (1.5·Ke) the agreement holds at any current
 * angle.
 */

import type { DqFluxLinkage } from './performance';

export interface DqRow {
  key: string;
  symbol: string;
  name: string;
  value: string;
  unit: string;
  hint?: string;
}

export type DqAgreementStatus = 'ok' | 'check' | 'unavailable';

export interface DqView {
  rows: DqRow[];
  agreement: { text: string; status: DqAgreementStatus; hint: string };
}

/** Within this many percentage points of 100%, the d/q agreement reads OK. */
export const DQ_AGREEMENT_TOLERANCE_PCT = 5;

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function significant(value: number, digits = 3): string {
  if (value === 0) return '0';
  const rounded = Number(value.toPrecision(digits));
  const magnitude = Math.floor(Math.log10(Math.abs(rounded)));
  return value.toFixed(Math.max(0, digits - 1 - magnitude)).replace(/^-/, '−');
}

const show = (value: unknown, scale = 1, digits = 3) => (finite(value) ? significant(value * scale, digits) : '—');

export function dqAgreement(dq: Pick<DqFluxLinkage, 'torque_agreement_pct'> | null | undefined): DqView['agreement'] {
  const pct = dq?.torque_agreement_pct;
  const hint = 'Average torque divided by the torque the loaded flux linkage predicts, 1.5·P·(λd·iq − λq·id). '
    + 'It includes reluctance torque and saturation, so it holds at any current angle; 100% is ideal. '
    + `OK within ±${DQ_AGREEMENT_TOLERANCE_PCT} points of 100%.`;
  if (!finite(pct)) return { text: '—', status: 'unavailable', hint };
  const text = pct.toFixed(1);
  return { text, status: Math.abs(Number(text) - 100) <= DQ_AGREEMENT_TOLERANCE_PCT ? 'ok' : 'check', hint };
}

/** The card's content, or null for a run without a d/q record. */
export function dqView(dq: DqFluxLinkage | null | undefined): DqView | null {
  if (!dq) return null;
  const positions = finite(dq.positions) && dq.positions > 0 ? ` over ${dq.positions} rotor positions` : '';
  return {
    rows: [
      { key: 'gamma', symbol: 'γ', name: 'current angle', value: show(dq.current_angle_deg, 1, 3), unit: '°',
        hint: 'Measured from the applied currents: 0° is all q-axis current, positive angles add negative d-axis current (field weakening).' },
      { key: 'id', symbol: 'id', name: 'd-axis current', value: show(dq.i_d_A), unit: 'A peak' },
      { key: 'iq', symbol: 'iq', name: 'q-axis current', value: show(dq.i_q_A), unit: 'A peak' },
      { key: 'lambda-d', symbol: 'λd', name: 'd-axis flux linkage', value: show(dq.lambda_d_Wb, 1000), unit: 'mWb',
        hint: `Loaded, averaged${positions}. Below λpm when negative d-axis current opposes the magnets.` },
      { key: 'lambda-q', symbol: 'λq', name: 'q-axis flux linkage', value: show(dq.lambda_q_Wb, 1000), unit: 'mWb', hint: `Loaded, averaged${positions}.` },
      { key: 'lambda-pm', symbol: 'λpm', name: 'magnet flux linkage', value: show(dq.lambda_pm_Wb, 1000), unit: 'mWb',
        hint: 'No-load flux-linkage amplitude, from the same sweep.' },
      { key: 'ld', symbol: 'Ld', name: 'apparent d-axis inductance', value: show(dq.apparent_L_d_H, 1000), unit: 'mH',
        hint: finite(dq.apparent_L_d_H)
          ? '(λd − λpm) / id at this operating point: a secant value that includes saturation and cross-coupling.'
          : 'Needs d-axis current: solve at a nonzero current angle to read Ld.' },
      { key: 'lq', symbol: 'Lq', name: 'apparent q-axis inductance', value: show(dq.apparent_L_q_H, 1000), unit: 'mH',
        hint: finite(dq.apparent_L_q_H)
          ? 'λq / iq at this operating point: a secant value that includes saturation and cross-coupling.'
          : 'Needs q-axis current.' },
      { key: 'torque', symbol: 'Tdq', name: 'd/q torque', value: show(dq.torque_dq_Nm, 1, 4), unit: 'N·m',
        hint: '1.5·P·(λd·iq − λq·id), magnet and reluctance torque together.' },
    ],
    agreement: dqAgreement(dq),
  };
}
