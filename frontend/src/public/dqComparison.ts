import { isOpenCircuit } from './dqView';
import { DQ_FLUX_LINKAGE_STATUS_REASON, DQ_INDUCTANCE_STATUS_REASON, recordStatus, type OutputStatus } from './outputStatus';
import type { DqFluxLinkage } from './performance';
import type { ComparisonResult } from './runComparison';

export interface ComparisonDqCell {
  value: number | null;
  missing: 'Not recorded' | 'Unavailable' | 'Not applicable';
  reason?: string;
  status?: OutputStatus;
}

interface DqMetric {
  key: keyof DqFluxLinkage;
  label: string;
  unit: string;
  hint?: string;
  scale?: number;
  loadedOnly?: boolean;
  positive?: boolean;
  status?: 'flux' | 'inductance';
  /** Signed components and secant inductances require the same recorded frame. */
  frameDependent?: boolean;
}

const METRICS: DqMetric[] = [
  { key: 'apparent_L_d_H', label: 'Ld · d-axis inductance', unit: 'mH', scale: 1000, loadedOnly: true, positive: true, status: 'inductance', frameDependent: true,
    hint: 'Apparent (secant) inductance (λd − λpm) / id at this operating point, including saturation and cross-coupling. Unavailable near zero d-axis current or without magnet flux linkage.' },
  { key: 'apparent_L_q_H', label: 'Lq · q-axis inductance', unit: 'mH', scale: 1000, loadedOnly: true, positive: true, status: 'inductance', frameDependent: true,
    hint: 'Apparent (secant) inductance λq / iq at this operating point, including saturation and cross-coupling. Unavailable near zero q-axis current.' },
  { key: 'current_angle_deg', label: 'γ · current angle', unit: '°', loadedOnly: true, frameDependent: true,
    hint: '0° is all q-axis current; positive angles add negative d-axis current. With an applied-current reference this is the commanded angle; with a no-load flux reference it is measured from the applied currents.' },
  { key: 'i_d_A', label: 'id · d-axis current', unit: 'A peak', frameDependent: true },
  { key: 'i_q_A', label: 'iq · q-axis current', unit: 'A peak', frameDependent: true },
  { key: 'lambda_d_Wb', label: 'λd · d-axis flux linkage', unit: 'mWb', scale: 1000, status: 'flux', frameDependent: true },
  { key: 'lambda_q_Wb', label: 'λq · q-axis flux linkage', unit: 'mWb', scale: 1000, status: 'flux', frameDependent: true },
  { key: 'lambda_pm_Wb', label: 'λpm · magnet flux linkage', unit: 'mWb', scale: 1000,
    hint: 'No-load flux-linkage amplitude recorded in this d/q result. Not inferred from another run or from the open design.' },
  { key: 'torque_dq_Nm', label: 'Tdq · d/q torque', unit: 'N·m', loadedOnly: true,
    hint: 'Torque predicted by the loaded flux linkage, 1.5 · pole pairs · (λd · iq − λq · id), including magnet and reluctance torque.' },
];

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const knownFrame = (dq: DqFluxLinkage) => dq.transform === 'amplitude_invariant_park'
  && dq.current_angle_convention === 'q_axis_gamma_flux_weakening_positive';
const knownSource = (dq: DqFluxLinkage) => dq.d_axis_source === 'no_load_flux_linkage' || dq.d_axis_source === 'applied_current_angle';

export function dqReferenceLabel(dq: DqFluxLinkage | null | undefined): string {
  if (!dq) return 'Not recorded';
  const source = dq.d_axis_source === 'no_load_flux_linkage' ? 'No-load flux linkage'
    : dq.d_axis_source === 'applied_current_angle' ? 'Applied current angle' : 'Reference not recorded';
  return knownFrame(dq) ? source : `${source} · convention not supported or not recorded`;
}

function cell(dq: DqFluxLinkage | null | undefined, metric: DqMetric): ComparisonDqCell {
  if (!dq) return { value: null, missing: 'Not recorded' };
  if (metric.loadedOnly && isOpenCircuit(dq)) return { value: null, missing: 'Not applicable', reason: 'Open circuit: no current flows, so inductance, current angle and the torque check do not apply.' };
  const status = metric.status === 'flux' ? recordStatus(dq, DQ_FLUX_LINKAGE_STATUS_REASON)
    : metric.status === 'inductance' ? recordStatus({ status: dq.inductance_status, status_reason: dq.inductance_status_reason }, DQ_INDUCTANCE_STATUS_REASON) : undefined;
  const unavailable = status?.status === 'unavailable' || (metric.key === 'torque_dq_Nm' && dq.status === 'unavailable');
  const raw = dq[metric.key];
  const value = finite(raw) && (!metric.positive || raw > 0) && !unavailable ? raw * (metric.scale ?? 1) : null;
  return { value, missing: 'Unavailable', status, reason: unavailable ? status?.reason || dq.status_reason || 'The recorded flux linkage is unavailable.'
    : value === null ? metric.hint || 'This value was not recorded as a finite number in the saved run.' : undefined };
}

// Smallest baseline magnitude a percentage change is shown for, in the row's
// display unit. An all-q-axis run records a current angle of a few hundredths of
// a degree and a d-axis current of a few mA, which turn any change into a
// five-digit percentage. Components under 1% of their d/q vector, and angles
// under 0.5° (about the same share of the current), count as zero.
const COMPONENT_SHARE = 0.01;
const ANGLE_FLOOR_DEG = 0.5;

function percentFloor(metric: DqMetric, baseline: DqFluxLinkage | null | undefined): number {
  if (!baseline) return 0;
  const magnitude = (d: unknown, q: unknown) => Math.hypot(finite(d) ? d : 0, finite(q) ? q : 0);
  if (metric.key === 'current_angle_deg') return ANGLE_FLOOR_DEG;
  if (metric.key === 'i_d_A' || metric.key === 'i_q_A') return COMPONENT_SHARE * magnitude(baseline.i_d_A, baseline.i_q_A);
  if (metric.key === 'lambda_d_Wb' || metric.key === 'lambda_q_Wb') {
    return COMPONENT_SHARE * magnitude(baseline.lambda_d_Wb, baseline.lambda_q_Wb) * (metric.scale ?? 1);
  }
  return 0;
}

/** Read stored outputs only. Missing records, unavailable statuses and frame mismatches never produce deltas. */
export function compareRunDq(results: ComparisonResult[]) {
  const records = results.map(result => result.summary.dq_flux_linkage);
  const baseline = records[0];
  const frameComparable = records.map(dq => Boolean(baseline && dq && knownFrame(baseline) && knownFrame(dq)
    && knownSource(baseline) && baseline.d_axis_source === dq.d_axis_source));
  return {
    recorded: records.some(Boolean),
    references: records.map(dqReferenceLabel),
    // A change of convention also prevents a scalar d/q torque delta; the formula's scale may differ.
    notes: records.map((dq, index) => !dq || index === 0 ? null
      : !baseline ? 'D/q deltas need a recorded baseline result.'
      : !knownFrame(baseline) || !knownFrame(dq) ? 'D/q deltas are hidden because a transform or current-angle convention is unsupported or was not recorded.'
      : !frameComparable[index] ? 'Component and inductance deltas are hidden because the d-axis references differ or were not recorded.' : null),
    rows: METRICS.map(metric => {
      const cells = records.map(dq => cell(dq, metric));
      return { ...metric, cells, percentFloor: percentFloor(metric, baseline), comparable: records.map((dq, index) => cells[0].value !== null && cells[index].value !== null
        && Boolean(baseline && dq && knownFrame(baseline) && knownFrame(dq))
        && (!metric.frameDependent || frameComparable[index])) };
    }),
  };
}
