import { phaseCurrents, type PhaseDrive } from '../phaseDrive';
import type { OutrunnerProject } from './project';

export type OperatingSettings = OutrunnerProject['analysis'];
export const isRunning = (settings: OperatingSettings) => settings.excitation_mode !== 'fixed_phase_currents';
export const excitationLabel = (settings: OperatingSettings) => settings.excitation_mode === 'sinusoidal' ? 'Sinusoidal'
  : settings.excitation_mode === 'ideal_six_step_120' ? 'Ideal six-step (120°)' : 'Fixed-current benchmark';
export const directionLabel = (settings: OperatingSettings) => isRunning(settings) ? 'CW' : 'CCW';

/** Source winding phasors: A=-90°, B=150°, C=30°; gap-facing rotor N at 0°. */
export function outrunnerDrive(settings: OperatingSettings): PhaseDrive {
  if (!isRunning(settings)) return { mode: 'fixed_phase_currents',
    fixedCurrentsA: settings.loaded_currents_A as [number, number, number],
    currentAmplitudeA: Math.max(...settings.loaded_currents_A.map(Math.abs)),
    currentAngleDeg: 0, currentAngleReference: 'q_axis', commutationAdvanceDeg: 0, axisOffsetDeg: 0, poleCount: 14 };
  return { mode: settings.excitation_mode, phaseOrder: [0, 2, 1], axisOffsetDeg: 90,
    currentAmplitudeA: settings.current_amplitude_A*(settings.excitation_mode === 'sinusoidal' && settings.current_amplitude_convention === 'rms' ? Math.SQRT2 : 1),
    currentAngleDeg: settings.current_angle_deg, currentAngleReference: 'q_axis',
    commutationAdvanceDeg: settings.commutation_advance_deg, poleCount: 14 };
}

export function currentsAtCW(settings: OperatingSettings, electricalAngle: number): [number, number, number] {
  const drive = outrunnerDrive(settings);
  return phaseCurrents(drive, electricalAngle).map(value => value*drive.currentAmplitudeA) as [number, number, number];
}
