/**
 * SPM magnet pole fills shared by the tutorial motor diagram, the 2D design
 * overlay, and the 3D viewer.
 *
 * Moved out of motor-viewport/designPreviewVisuals.ts so the shared tutorial
 * tree owns the single declaration; designPreviewVisuals re-exports every name
 * below for its existing consumers.
 */

/** Shared airgap-facing SPM pole colors across the main, lesson, and 3D views. */
export const DESIGN_MAGNET_N_FILL = '#e53e3e';
export const DESIGN_MAGNET_S_FILL = '#3182ce';

function mixHexToward(hex: string, target: string, t: number): string {
  const parse = (value: string) => [
    parseInt(value.slice(1, 3), 16),
    parseInt(value.slice(3, 5), 16),
    parseInt(value.slice(5, 7), 16),
  ];
  const from = parse(hex);
  const to = parse(target);
  const mixed = from.map((channel, i) => Math.round(channel + (to[i] - channel) * t));
  return `#${mixed.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}

/**
 * How far the inactive (back) pole of a magnet dipole is pushed toward the
 * canvas dark. Shared by the 2D overlay and the 3D back-pole material so
 * the two views tell the same story.
 */
export const MAGNET_BACK_POLE_DIM = 0.68;

/**
 * Fill for the back-pole half of a magnet dipole: the opposite polarity
 * color, strongly dimmed so the labeled working pole reads at a glance.
 */
export function designMagnetBackPoleFill(north: boolean): string {
  return mixHexToward(
    north ? DESIGN_MAGNET_S_FILL : DESIGN_MAGNET_N_FILL,
    '#10141c',
    MAGNET_BACK_POLE_DIM,
  );
}
