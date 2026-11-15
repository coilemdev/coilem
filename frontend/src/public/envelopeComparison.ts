import type { TorqueSpeedCurve, TorqueSpeedEnvelope } from './performance';
import type { ComparisonResult } from './runComparison';
import { curveAt } from './performanceView';
import { recordStatus } from './outputStatus';

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

export function validEnvelopeCurve(curve: TorqueSpeedCurve): boolean {
  const speeds = curve?.speed_rpm;
  return Array.isArray(speeds) && speeds.length >= 2 && speeds.every((speed, index) => finite(speed) && speed >= 0 && (index === 0 || speed > speeds[index - 1]))
    && [curve.torque_Nm, curve.power_W, curve.i_d_A, curve.i_q_A].every(values => Array.isArray(values) && values.length === speeds.length && values.every(finite))
    && curve.torque_Nm.every(value => value >= 0) && curve.power_W.every(value => value >= 0);
}

/** Keep the archived status and omit curves that cannot be drawn without inventing samples. */
export function comparisonEnvelope(result: ComparisonResult) {
  const analysis = result.torque_speed_analysis;
  const envelope = analysis?.status === 'partial' ? null : analysis?.envelope;
  const status = envelope ? recordStatus(envelope, 'This saved envelope predates recorded output statuses.') : null;
  const curves = status?.status === 'unavailable' ? [] : (envelope?.curves || []).filter(validEnvelopeCurve);
  return { envelope, curves, status, settings: analysis?.settings,
    missing: !analysis ? 'Not recorded' : analysis.status === 'partial' ? 'Incomplete map' : 'Unavailable',
    reason: !analysis ? 'A torque–speed map was not recorded for this run.'
      : analysis.status === 'partial' ? analysis.status_reason || 'The recorded map is incomplete; it has no completed envelope.'
      : status?.status === 'unavailable' ? status.reason
      : !curves.length ? 'No usable envelope curves were recorded.' : null,
  };
}

/** Interpolate only inside a recorded curve, never across an unavailable curve or beyond its speed range. */
export function envelopePoint(curve: TorqueSpeedCurve | null | undefined, speed: number) {
  return curve && validEnvelopeCurve(curve) && finite(speed) ? curveAt(curve, speed) : null;
}

export const ENVELOPE_METRICS: Array<{ label: string; unit: string; value: (envelope: TorqueSpeedEnvelope, curve?: TorqueSpeedCurve) => number | null | undefined }> = [
  { label: 'Base speed', unit: 'rpm', value: (_, curve) => curve?.base_speed_rpm },
  { label: 'Maximum speed', unit: 'rpm', value: (_, curve) => curve?.max_speed_rpm },
  { label: 'Peak power', unit: 'kW', value: (_, curve) => finite(curve?.peak_power_W) ? curve.peak_power_W / 1000 : null },
  { label: 'DC bus', unit: 'V', value: envelope => envelope.limits?.dc_bus_V },
  { label: 'Peak current limit', unit: 'A peak', value: envelope => envelope.limits?.peak_current_A },
  { label: 'Continuous current limit', unit: 'A peak', value: envelope => envelope.limits?.continuous_current_A },
  { label: 'Maximum modulation index', unit: '', value: envelope => envelope.limits?.modulation_index_max },
  { label: 'Phase resistance', unit: 'Ω', value: envelope => envelope.phase_resistance_ohm },
  { label: 'Winding temperature', unit: '°C', value: envelope => envelope.winding_temperature_C },
];
