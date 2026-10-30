/**
 * Motor constants from a run's summary, in the units a datasheet uses (#99).
 *
 * The backend stores Kt per peak phase ampere, Ke as per-phase peak
 * line-to-neutral volts per mechanical rad/s and λpm in webers
 * (backend/machine_constants.py). Power balance at the operating point gives
 * T·ω = 3·E_rms·I_rms = 1.5·E_pk·I_pk, so Kt = 1.5·Ke in those units; the
 * consistency check shows Kt / (1.5·Ke) as a percentage, 100% ideal.
 *
 * Kt and Ke are shown once each, in datasheet units (per rms ampere, and
 * line-to-line rms volts per krpm). The stored SI peak value of each is
 * kept as a hover hint rather than a second row.
 */

export interface MotorConstantsSummary {
  Kt_Nm_per_A?: number | null;
  Ke_Vs_per_rad_mech?: number | null;
  lambda_pm_Wb?: number | null;
  /** The loaded d/q record (#113); its torque agreement holds at any current angle. */
  dq_flux_linkage?: {
    torque_agreement_pct?: number | null;
    current_angle_deg?: number | null;
    apparent_L_d_H?: number | null;
    apparent_L_q_H?: number | null;
  } | null;
}

export interface MotorConstantValue {
  key: string;
  unit: string;
  value: number | null;
  /** The number as displayed, with a true minus sign; '—' when unavailable. */
  text: string;
  /** The same constant as the backend stores it, in SI peak units, for a hover hint. */
  siHint?: string;
}

/** 'not-applicable': the run has reluctance torque or current off the q-axis, which the check leaves out. */
export type ConsistencyStatus = 'ok' | 'check' | 'unavailable' | 'not-applicable';

export interface MotorConstantsView {
  kt: MotorConstantValue;
  ke: MotorConstantValue;
  lambdaPm: MotorConstantValue;
  consistency: MotorConstantValue;
  consistencyStatus: ConsistencyStatus;
  /** Why the check does not apply to this run, when it does not. */
  consistencyNote: string | null;
}

/** Within this many percentage points of 100%, the check reads OK. */
export const CONSISTENCY_TOLERANCE_PCT = 10;

/**
 * Kt / (1.5·Ke) predicts the torque of magnets with every ampere on the
 * q-axis. Beyond this current angle only cos γ of the current makes magnet
 * torque, and a salient rotor adds reluctance torque with the d-axis current,
 * so the check no longer applies; Torque–λdq agreement covers any angle.
 * At γ = 0° there is no d-axis current, so even an IPM has no reluctance torque.
 */
export const CONSISTENCY_MAX_CURRENT_ANGLE_DEG = 5;

const RAD_PER_S_PER_KRPM = (1000 * 2 * Math.PI) / 60;
// Peak line-to-neutral to rms line-to-line: ×√3 / √2.
const PEAK_LN_TO_RMS_LL = Math.sqrt(3) / Math.SQRT2;

function finite(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** Three significant figures, without exponents; whole numbers keep every digit. */
export function formatSignificant(value: number, significant = 3): string {
  if (value === 0) return '0';
  const rounded = Number(value.toPrecision(significant));
  const magnitude = Math.floor(Math.log10(Math.abs(rounded)));
  return value.toFixed(Math.max(0, significant - 1 - magnitude));
}

function constantValue(key: string, unit: string, value: number | null, format: (value: number) => string = formatSignificant): MotorConstantValue {
  return { key, unit, value, text: value === null ? '—' : format(value).replace(/^-/, '−') };
}

/** Why Kt / (1.5·Ke) does not apply to a run, or null when it does. */
export function consistencyNotApplicable(dq: MotorConstantsSummary['dq_flux_linkage']): string | null {
  const gamma = finite(dq?.current_angle_deg);
  if (gamma === null || Math.abs(gamma) <= CONSISTENCY_MAX_CURRENT_ANGLE_DEG) return null;
  const ld = finite(dq?.apparent_L_d_H);
  const lq = finite(dq?.apparent_L_q_H);
  const reluctance = ld !== null && lq !== null && ld > 0 && Math.abs(lq / ld - 1) > 0.05
    ? ` and, with saliency Lq/Ld ${formatSignificant(lq / ld)}, the rotor adds reluctance torque`
    : '';
  return 'Torque–EMF consistency assumes current on the q-axis and magnet torque only. '
    + `This run's current is at ${formatSignificant(gamma)}°, so only part of it makes magnet torque${reluctance}; `
    + 'Torque–λdq agreement is the check that applies.';
}

export function motorConstantsView(summary: MotorConstantsSummary): MotorConstantsView {
  const kt = finite(summary.Kt_Nm_per_A);
  const ke = finite(summary.Ke_Vs_per_rad_mech);
  const lambdaPm = finite(summary.lambda_pm_Wb);
  const consistency = kt !== null && ke !== null && ke > 0 ? (kt / (1.5 * ke)) * 100 : null;
  const formatPercent = (value: number) => value.toFixed(1);
  // Judge the value as displayed, so "90.0 %" never reads Check.
  const shownPercent = consistency === null ? null : Number(formatPercent(consistency));
  const notApplicable = consistencyNotApplicable(summary.dq_flux_linkage);
  // Torque per rms ampere: I_rms = I_pk / √2, so Kt_rms = √2 · Kt_pk.
  const ktShown = constantValue('kt-rms', 'N·m/A rms', kt === null ? null : kt * Math.SQRT2);
  const keShown = constantValue('ke-krpm', 'V/krpm L-L rms', ke === null ? null : ke * RAD_PER_S_PER_KRPM * PEAK_LN_TO_RMS_LL);
  return {
    kt: kt === null ? ktShown : { ...ktShown, siHint: `${constantValue('kt-peak', '', kt).text} N·m/A per peak ampere (SI)` },
    ke: ke === null ? keShown : { ...keShown, siHint: `${constantValue('ke-si', '', ke).text} V·s/rad, phase peak per mechanical rad/s (SI)` },
    lambdaPm: constantValue('lambda-pm', 'mWb', lambdaPm === null ? null : lambdaPm * 1000),
    consistency: constantValue('consistency', '%', consistency, formatPercent),
    consistencyStatus: shownPercent === null
      ? 'unavailable'
      : notApplicable !== null ? 'not-applicable'
        : Math.abs(shownPercent - 100) <= CONSISTENCY_TOLERANCE_PCT ? 'ok' : 'check',
    consistencyNote: shownPercent === null ? null : notApplicable,
  };
}

/** Whether a run reported any of the three constants. */
export function hasMotorConstants(summary: MotorConstantsSummary): boolean {
  return [summary.Kt_Nm_per_A, summary.Ke_Vs_per_rad_mech, summary.lambda_pm_Wb].some((value) => finite(value) !== null);
}
