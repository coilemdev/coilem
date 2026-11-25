import { meshDensityLabel } from './meshLabels';
import { motorConstantsView } from './machineConstants';
import { torqueRippleView } from './resultMetrics';
import { COGGING_METHOD_LABELS } from './coggingView';
import type { ComparisonResult } from './runComparison';
import { rotorHistoryPositions } from './performance';

export const COMPARISON_METRICS: Array<{
  label: string;
  unit: string;
  deltaUnit?: string;
  digits?: number;
  /** A torque in N·m: small values keep three significant figures (#270). */
  torque?: boolean;
  /** Shown only when either run has the value. */
  optional?: boolean;
  value: (result: ComparisonResult) => number | null | undefined;
}> = [
  { label: 'Average torque', unit: 'N·m', torque: true, value: (run) => run.summary.avg_torque_Nm },
  // No percentage where it means nothing (no current, near-zero average).
  { label: 'Torque ripple', unit: '%', deltaUnit: 'pp', value: (run) => torqueRippleView(run).ripplePct },
  { label: 'Back EMF', unit: 'V', value: (run) => run.summary.back_emf_fundamental_V },
  { label: 'Peak tooth B', unit: 'T', value: (run) => run.summary.peak_flux_density_teeth_T },
  { label: 'Peak yoke B', unit: 'T', value: (run) => run.summary.peak_flux_density_yoke_T },
  // Per rms ampere, as in Results: the summary stores Kt per peak ampere (#153).
  { label: 'Torque constant', unit: 'N·m/A rms', value: (run) => motorConstantsView(run.summary).kt.value },
  { label: 'Back EMF constant (Ke)', unit: 'V/krpm L-L rms', value: (run) => motorConstantsView(run.summary).ke.value },
  { label: 'Back EMF THD (headline)', unit: '%', deltaUnit: 'pp', value: (run) => run.summary.back_emf_thd_pct },
  // The cogging sweep (#185), for runs that solved one.
  { label: 'Cogging torque p-p', unit: 'N·m', torque: true, optional: true, value: (run) => run.summary.cogging?.peak_to_peak_Nm },
  { label: 'Cogging fundamental', unit: 'N·m', torque: true, optional: true, value: (run) => run.summary.cogging?.first_harmonic_Nm },
];

export function actualMeshProvenance(result: ComparisonResult): string {
  const metadata = result.solve_metadata;
  // What was actually solved: a sector request on a motor that does not repeat solves the full motor.
  const sector = typeof metadata.sector_repeats === 'number' && metadata.sector_repeats > 1 ? `1/${metadata.sector_repeats} sector` : null;
  return [metadata.mesh_source, metadata.mesher, meshDensityLabel(metadata.mesh_density), metadata.mesh_source_detail, sector]
    .filter((value): value is string => typeof value === 'string' && value.length > 0)
    .join(' · ') || 'Not recorded';
}

/** The loaded sweep, cogging period, and separate rotor-material history recorded by the run. */
export function actualPositionsProvenance(result: ComparisonResult): string {
  const loaded = result.solve_metadata.rotor_positions ?? result.torque_waveform?.electrical_angle_deg?.length ?? 0;
  const cogging = result.summary.cogging?.positions_per_period;
  const rotor = result.summary.rotor_iron_loss;
  const history = rotorHistoryPositions(rotor);
  const rotorText = history !== null ? `${history - 1} rotor history + 1 closure`
    : rotor?.status === 'unavailable' ? 'Rotor history unavailable' : null;
  return [loaded > 0 ? `${loaded} loaded` : null, typeof cogging === 'number' && cogging > 0 ? `${cogging} per cogging period` : null, rotorText]
    .filter((value): value is string => value !== null)
    .join(' · ') || 'Not recorded';
}

export function actualTorqueProvenance(result: ComparisonResult): string {
  const metadata = result.solve_metadata;
  const labels: Record<string, string> = { ...COGGING_METHOD_LABELS, remesh_per_step: 'Remesh Per Step', fixed_mesh: 'Fixed Mesh' };
  return [metadata.torque_method, metadata.rotor_rotation_model]
    .filter((value): value is string => typeof value === 'string' && value.length > 0)
    .map(value => labels[value] || value.replace(/_/g, ' '))
    .join(' · ') || 'Not recorded';
}

export function excitationProvenance(result: ComparisonResult): string {
  const metadata = result.solve_metadata;
  if (metadata.excitation_mode !== 'ideal_six_step_120') return 'Sinusoidal';
  const advance = typeof metadata.commutation_advance_deg === 'number'
    ? `${metadata.commutation_advance_deg.toFixed(2)}° advance`
    : 'advance not recorded';
  return `Ideal six-step (120°) · ${advance} · ${metadata.phase_connection || 'wye'} · ${metadata.current_amplitude_convention || 'plateau'}`;
}
