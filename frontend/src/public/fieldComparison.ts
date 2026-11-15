import type { ComparisonFields } from './runComparison';

export type ComparisonFieldPosition = 'snapshot' | number;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const matches = (a: number, b: number) => Math.abs(a - b) <= 1e-3;

export function comparisonFieldAngles(fields: Array<ComparisonFields | null | undefined>): number[] {
  const angles = fields.flatMap(field => [...(field?.frames || []).map(frame => frame.angle_deg), ...(finite(field?.snapshot_angle_deg) ? [field.snapshot_angle_deg] : [])])
    .filter(finite).sort((a, b) => a - b);
  return angles.filter((angle, index) => index === 0 || !matches(angle, angles[index - 1]));
}

/** Exact saved positions only: never choose a nearest frame or wrap a different period onto this angle. */
export function comparisonFieldTarget(fields: ComparisonFields | null | undefined, position: ComparisonFieldPosition) {
  if (!fields) return null;
  if (position === 'snapshot') return fields.snapshot_available ? { id: 'snapshot', artifactId: null, angle: fields.snapshot_angle_deg } : null;
  const frame = (fields.frames || []).find(frame => finite(frame.angle_deg) && matches(frame.angle_deg, position) && Boolean(frame.artifact_id));
  if (frame) return { id: frame.artifact_id, artifactId: frame.artifact_id, angle: frame.angle_deg };
  return fields.snapshot_available && finite(fields.snapshot_angle_deg) && matches(fields.snapshot_angle_deg, position)
    ? { id: 'snapshot', artifactId: null, angle: fields.snapshot_angle_deg } : null;
}
