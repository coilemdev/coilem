/**
 * Motor constants from a run's summary, in the units a datasheet uses (#99).
 *
 * The backend stores Kt per peak phase ampere, Ke as per-phase peak
 * line-to-neutral volts per mechanical rad/s and λpm in webers
 * (backend/machine_constants.py). Power balance at the operating point gives
 * T·ω = 3·E_rms·I_rms = 1.5·E_pk·I_pk, so Kt = 1.5·Ke in those units; the
 * consistency check shows Kt / (1.5·Ke) as a percentage, 100% ideal.
 */

export interface MotorConstantsSummary {
  Kt_Nm_per_A?: number | null;
  Ke_Vs_per_rad_mech?: number | null;
  lambda_pm_Wb?: number | null;
}

export interface MotorConstantValue {
  key: string;
  unit: string;
  value: number | null;
  /** The number as displayed, with a true minus sign; '—' when unavailable. */
  text: string;
}

export type ConsistencyStatus = 'ok' | 'check' | 'unavailable';

export interface MotorConstantsView {
  kt: MotorConstantValue[];
  ke: MotorConstantValue[];
  lambdaPm: MotorConstantValue;
  consistency: MotorConstantValue;
  consistencyStatus: ConsistencyStatus;
}

/** Within this many percentage points of 100%, the check reads OK. */
export const CONSISTENCY_TOLERANCE_PCT = 10;

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

export function motorConstantsView(summary: MotorConstantsSummary): MotorConstantsView {
  const kt = finite(summary.Kt_Nm_per_A);
  const ke = finite(summary.Ke_Vs_per_rad_mech);
  const lambdaPm = finite(summary.lambda_pm_Wb);
  const consistency = kt !== null && ke !== null && ke > 0 ? (kt / (1.5 * ke)) * 100 : null;
  const formatPercent = (value: number) => value.toFixed(1);
  // Judge the value as displayed, so "90.0 %" never reads Check.
  const shownPercent = consistency === null ? null : Number(formatPercent(consistency));
  return {
    kt: [
      constantValue('kt-peak', 'N·m/A pk', kt),
      // Torque per rms ampere: I_rms = I_pk / √2, so Kt_rms = √2 · Kt_pk.
      constantValue('kt-rms', 'N·m/A rms', kt === null ? null : kt * Math.SQRT2),
    ],
    ke: [
      constantValue('ke-si', 'V·s/rad', ke),
      constantValue('ke-krpm', 'V/krpm L-L rms', ke === null ? null : ke * RAD_PER_S_PER_KRPM * PEAK_LN_TO_RMS_LL),
    ],
    lambdaPm: constantValue('lambda-pm', 'mWb', lambdaPm === null ? null : lambdaPm * 1000),
    consistency: constantValue('consistency', '%', consistency, formatPercent),
    consistencyStatus: shownPercent === null
      ? 'unavailable'
      : Math.abs(shownPercent - 100) <= CONSISTENCY_TOLERANCE_PCT ? 'ok' : 'check',
  };
}

/** Whether a run reported any of the three constants. */
export function hasMotorConstants(summary: MotorConstantsSummary): boolean {
  return [summary.Kt_Nm_per_A, summary.Ke_Vs_per_rad_mech, summary.lambda_pm_Wb].some((value) => finite(value) !== null);
}
