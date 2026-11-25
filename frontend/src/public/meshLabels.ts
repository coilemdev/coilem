/** Mesh densities by the names Solve gives them. Results, Compare and the reports use the same words (#348). */
export const MESH_DENSITY_LABELS: Readonly<Record<string, string>> = { coarse: 'Coarse', normal: 'Medium', fine: 'Fine', very_fine: 'Very fine' };

/** A stored mesh density as the app names it; null when none was recorded. */
export function meshDensityLabel(value: string | null | undefined): string | null {
  return value ? MESH_DENSITY_LABELS[value] ?? value.replace(/_/g, ' ') : null;
}
