import type { MotorConfig } from './model';
import { publishedReference } from './publishedReferences';

export const MOTOR_3D_FOV = 36;

/** Both the design geometry and solver mesh use Z for the shaft and Y for screen up. */
export function motor3DCameraOffset(config: MotorConfig): [number, number, number] {
  const radius = config.stator.OD_mm / 2;
  const referenceOffset = publishedReference(config)?.cameraOffset;
  if (referenceOffset) return referenceOffset(radius);
  // Pull back for long stacks so the assembled motor stays inside the view.
  const framingRadius = Math.max(radius, Math.max(8, config.stator.stack_length_mm) * 0.42);
  return [framingRadius * 2.45, framingRadius * 1.8, framingRadius * 2.7];
}
