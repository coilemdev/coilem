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

import { DQ_FLUX_LINKAGE_STATUS_REASON, recordStatus, type OutputStatus } from './outputStatus';
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

export interface DqAgreement { text: string; status: DqAgreementStatus; hint: string }

export interface DqView {
  /** What a designer reads first; the detail rows hold the rest of the record. */
  main: DqRow[];
  detail: DqRow[];
  /** Why some main values are missing, when they are. */
  note: string | null;
  /** The torque check; null for an open-circuit run, which has no current and no torque to compare. */
  agreement: DqAgreement | null;
  /** Whether the record is qualified or experimental, and why (public issue 143). */
  status: OutputStatus;
}

/** Within this many percentage points of 100%, the d/q agreement reads OK. */
export const DQ_AGREEMENT_TOLERANCE_PCT = 5;

/** Below this phase current (A peak) a run is open-circuit, as backend/dq_flux_linkage.py treats it. */
export const OPEN_CIRCUIT_CURRENT_A = 1e-6;

/** No current flows: a back-EMF (no-load) run, such as the Pyleecan Prius tutorial case. */
export function isOpenCircuit(dq: Pick<DqFluxLinkage, 'i_d_A' | 'i_q_A'>): boolean {
  const current = Math.hypot(dq.i_d_A, dq.i_q_A);
  return Number.isFinite(current) && current <= OPEN_CIRCUIT_CURRENT_A;
}

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function significant(value: number, digits = 3): string {
  if (value === 0) return '0';
  const rounded = Number(value.toPrecision(digits));
  const magnitude = Math.floor(Math.log10(Math.abs(rounded)));
  return value.toFixed(Math.max(0, digits - 1 - magnitude)).replace(/^-/, '−');
}

const show = (value: unknown, scale = 1, digits = 3) => (finite(value) ? significant(value * scale, digits) : '—');

export function dqAgreement(dq: Pick<DqFluxLinkage, 'torque_agreement_pct'> | null | undefined): DqAgreement {
  const pct = dq?.torque_agreement_pct;
  const hint = 'Average torque divided by the torque the loaded flux linkage predicts, 1.5·P·(λd·iq − λq·id). '
    + 'It includes reluctance torque and saturation, so it holds at any current angle; 100% is ideal. '
    + `OK within ±${DQ_AGREEMENT_TOLERANCE_PCT} points of 100%.`;
  if (!finite(pct)) return { text: '—', status: 'unavailable', hint };
  const text = pct.toFixed(1);
  return { text, status: Math.abs(Number(text) - 100) <= DQ_AGREEMENT_TOLERANCE_PCT ? 'ok' : 'check', hint };
}

/** The card's content, or null for a run without a d/q record. */
/** Units the d/q currents are shown in: the Solve page's rms or peak. d/q values are peak amplitudes underneath. */
export type DqCurrentUnit = 'A rms' | 'A peak';

/**
 * The card's content, or null for a run without a d/q record. The main rows
 * are what a designer reads first: the inductances, the saliency and the
 * characteristic current, which together say how much reluctance torque the
 * rotor offers and how far field weakening can stretch the speed. The rest
 * of the record is in detail rows.
 */
export function dqView(dq: DqFluxLinkage | null | undefined, currentUnit: DqCurrentUnit = 'A peak'): DqView | null {
  if (!dq) return null;
  const positions = finite(dq.positions) && dq.positions > 0 ? ` over ${dq.positions} rotor positions` : '';
  const perShown = currentUnit === 'A rms' ? 1 / Math.SQRT2 : 1;
  const ld = finite(dq.apparent_L_d_H) && dq.apparent_L_d_H > 0 ? dq.apparent_L_d_H : null;
  const lq = finite(dq.apparent_L_q_H) && dq.apparent_L_q_H > 0 ? dq.apparent_L_q_H : null;
  const lambdaPm = finite(dq.lambda_pm_Wb) ? dq.lambda_pm_Wb : null;
  const characteristic = ld !== null && lambdaPm !== null ? lambdaPm / ld : null;
  const all: Record<string, DqRow> = {
    ld: { key: 'ld', symbol: 'Ld', name: 'd-axis inductance', value: show(ld, 1000), unit: 'mH',
      hint: '(λd − λpm) / id at this operating point. With λpm it sets how far the drive can weaken the magnet flux, '
        + 'and so the speed range above base speed. A secant value: it includes saturation and cross-coupling.' },
    lq: { key: 'lq', symbol: 'Lq', name: 'q-axis inductance', value: show(lq, 1000), unit: 'mH',
      hint: 'λq / iq at this operating point. With Ld it sets the reluctance torque, and the voltage the winding needs under load. '
        + 'A secant value: it includes saturation and cross-coupling.' },
    saliency: { key: 'saliency', symbol: 'Lq/Ld', name: 'saliency', value: ld !== null && lq !== null ? show(lq / ld, 1, 3) : '—', unit: '',
      hint: 'About 1 for a surface-magnet rotor: torque is magnet torque only and MTPA sits at 0°. Above about 1.5 the rotor adds useful '
        + 'reluctance torque with negative d-axis current, and MTPA moves to a positive current angle.' },
    characteristic: { key: 'characteristic', symbol: 'λpm/Ld', name: 'characteristic current', value: show(characteristic === null ? null : characteristic * perShown), unit: currentUnit,
      hint: 'The d-axis current that would cancel the magnet flux. If the drive\'s peak current reaches it, field weakening can hold '
        + 'power to very high speed; well below it, the torque falls away soon after base speed and the top speed is limited.' },
    gamma: { key: 'gamma', symbol: 'γ', name: 'current angle', value: show(dq.current_angle_deg, 1, 3), unit: '°',
      hint: dq.d_axis_source === 'applied_current_angle'
        ? 'The commanded angle: this run had no no-load sweep to measure it against.'
        : 'Measured from the applied currents: 0° is all q-axis current, positive angles add negative d-axis current.' },
    id: { key: 'id', symbol: 'id', name: 'd-axis current', value: show(dq.i_d_A * perShown), unit: currentUnit },
    iq: { key: 'iq', symbol: 'iq', name: 'q-axis current', value: show(dq.i_q_A * perShown), unit: currentUnit },
    'lambda-d': { key: 'lambda-d', symbol: 'λd', name: 'd-axis flux linkage', value: show(dq.lambda_d_Wb, 1000), unit: 'mWb',
      hint: `Loaded, averaged${positions}. Below λpm when negative d-axis current opposes the magnets.` },
    'lambda-q': { key: 'lambda-q', symbol: 'λq', name: 'q-axis flux linkage', value: show(dq.lambda_q_Wb, 1000), unit: 'mWb', hint: `Loaded, averaged${positions}.` },
    'lambda-pm': { key: 'lambda-pm', symbol: 'λpm', name: 'magnet flux linkage', value: show(lambdaPm, 1000), unit: 'mWb',
      hint: 'No-load flux-linkage amplitude, from the same sweep.' },
    torque: { key: 'torque', symbol: 'Tdq', name: 'd/q torque', value: show(dq.torque_dq_Nm, 1, 4), unit: 'N·m',
      hint: '1.5·P·(λd·iq − λq·id), magnet and reluctance torque together.' },
  };
  if (isOpenCircuit(dq)) {
    // No current: no current angle, inductance or torque to report. The flux
    // linkages are the magnets' own, so λd is λpm and λq is about zero.
    const noLoad = (row: DqRow): DqRow => ({ ...row, hint: `Open circuit, averaged${positions}: the magnets' flux alone.` });
    return {
      main: [all['lambda-pm']],
      detail: [noLoad(all['lambda-d']), noLoad(all['lambda-q'])],
      note: 'Open-circuit run: no current flows, so there is no current angle, inductance or torque check. '
        + 'λd is the magnet flux linkage λpm and λq is about zero.',
      agreement: null,
      status: recordStatus(dq, DQ_FLUX_LINKAGE_STATUS_REASON),
    };
  }
  const mainKeys = ld !== null ? ['ld', 'lq', 'saliency', 'characteristic'] : ['lq', 'lambda-pm'];
  return {
    main: mainKeys.map((key) => all[key]),
    detail: Object.keys(all).filter((key) => !mainKeys.includes(key) && (ld !== null || !['ld', 'saliency', 'characteristic'].includes(key))).map((key) => all[key]),
    note: ld === null
      ? 'Ld, the saliency and the characteristic current need d-axis current: solve at a nonzero current angle, such as 20°.'
      : null,
    agreement: dqAgreement(dq),
    status: recordStatus(dq, DQ_FLUX_LINKAGE_STATUS_REASON),
  };
}
