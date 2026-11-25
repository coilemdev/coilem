import type { MotorConfig } from './model';
import type { TorqueSpeedAnalysisSettings } from './performance';
import { currentUnits, defaultDriveLimits } from './performanceView';

/** The supply voltage of a design that names none. */
export const DEFAULT_DC_BUS_V = 48;

/**
 * The design's supply voltage: what Operating point shows and the map is limited by.
 * A design saved before the supply had its own input may carry it only in its map settings.
 */
export function designDcBusV(config: MotorConfig): number {
  return config.solve_params.motor_input_dc_bus_V ?? config.torque_speed_analysis?.limits.dc_bus_V ?? DEFAULT_DC_BUS_V;
}

/** Defaults come from the design, before any operating-point solve exists. The DC bus is always the design's. */
export function torqueSpeedSettings(config: MotorConfig): TorqueSpeedAnalysisSettings {
  const stored = config.torque_speed_analysis;
  if (stored) {
    const bus = designDcBusV(config);
    return stored.limits.dc_bus_V === bus ? stored : { ...stored, limits: { ...stored.limits, dc_bus_V: bus } };
  }
  const units = currentUnits(config.solve_params.current_amplitude_convention);
  return {
    preset: 'preview', control: 'mtpa',
    limits: defaultDriveLimits({
      ratedSpeedRpm: config.solve_params.rated_speed_rpm,
      phaseCurrentRmsA: units.toPeak(config.solve_params.current_amplitude_A) / Math.SQRT2,
      backEmfRmsV: null,
      dcBusV: designDcBusV(config),
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
