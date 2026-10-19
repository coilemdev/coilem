import type { MotorConfig } from './model';

export const MOTOR_3D_FOV = 36;

/** Both the design geometry and solver mesh use Z for the shaft and Y for screen up. */
export function motor3DCameraOffset(config: MotorConfig): [number, number, number] {
  const radius = config.stator.OD_mm / 2;
  if (config.geometry_reference === 'pyleecan_prius_2004') {
    return [radius * 1.35, -radius * 1.65, radius * 3.6];
  }
  // Pull back for long stacks so the assembled motor stays inside the view.
  const framingRadius = Math.max(radius, Math.max(8, config.stator.stack_length_mm) * 0.42);
  return [framingRadius * 2.45, framingRadius * 1.8, framingRadius * 2.7];
}
