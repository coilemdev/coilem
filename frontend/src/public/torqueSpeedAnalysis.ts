import type { MotorConfig } from './model';
import type { TorqueSpeedAnalysisSettings } from './performance';
import { currentUnits, defaultDriveLimits } from './performanceView';

/** Defaults come from the design, before any operating-point solve exists. */
export function torqueSpeedSettings(config: MotorConfig): TorqueSpeedAnalysisSettings {
  if (config.torque_speed_analysis) return config.torque_speed_analysis;
  const units = currentUnits(config.solve_params.current_amplitude_convention);
  return {
    preset: 'preview', control: 'mtpa',
    limits: defaultDriveLimits({
      ratedSpeedRpm: config.solve_params.rated_speed_rpm,
      phaseCurrentRmsA: units.toPeak(config.solve_params.current_amplitude_A) / Math.SQRT2,
      backEmfRmsV: null,
      dcBusV: config.solve_params.motor_input_dc_bus_V ?? 48,
      shownUnitPeakA: units.toPeak(1),
    }),
  };
}

export function parseTorqueSpeedSettings(value: unknown): TorqueSpeedAnalysisSettings {
  if (!value || typeof value !== 'object') throw new Error('Invalid torque–speed map settings.');
  const raw = value as Record<string, unknown>;
  const limits = raw.limits as Record<string, unknown> | null;
  const positive = (key: string, maximum: number) => typeof limits?.[key] === 'number'
    && Number.isFinite(limits[key]) && limits[key] > 0 && limits[key] <= maximum;
  if (!limits || !['preview', 'standard'].includes(String(raw.preset)) || !['mtpa', 'least_loss'].includes(String(raw.control))
    || !positive('dc_bus_V', 2000) || Number(limits.dc_bus_V) < 1 || !positive('peak_current_A', 5000)
    || !positive('max_speed_rpm', 100000) || !positive('modulation_index_max', 2 / Math.sqrt(3))
    || (limits.continuous_current_A != null && (!positive('continuous_current_A', Number(limits.peak_current_A))))) {
    throw new Error('Invalid torque–speed map settings: check the grid, control and drive limits.');
  }
  return structuredClone(value) as TorqueSpeedAnalysisSettings;
}
