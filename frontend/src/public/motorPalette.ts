/**
 * The one motor palette the public app draws from.
 *
 * The 2D canvas and the 3D viewer used to declare their own hexes, and they had
 * drifted: the 3D magnets, windings and stator were all lighter and more
 * saturated than the same parts in 2D, so switching views changed the colour of
 * the motor. Both now read these values.
 *
 * 3D is lit, tone-mapped and reflective, so feeding a material the raw 2D hex
 * renders noticeably lighter than the flat 2D fill. `renderTargetColor` bakes in
 * that compensation, which is why the 3D materials multiply these values down
 * rather than using them directly.
 */

/** Flat fills the 2D canvas paints. These are the colours to match. */
export const PUBLIC_MOTOR_COLORS = {
  /** Stator lamination stack, as painted by the 2D materials layer. */
  statorSteel: '#8fa3b8',
  /** Teeth read a step lighter than the yoke so the slots stay legible. */
  statorTooth: '#a3b5c8',
  rotorSteel: '#566579',
  magnetNorth: '#ef4444',
  magnetSouth: '#3b82f6',
  /** Neutral base used beneath the display-only split-polarity overlay. */
  magnetBody: '#929eae',
  /** Bare copper, used where a slot is drawn without a phase. */
  winding: '#c77b30',
} as const;

/** Per-phase winding colours, shared by the 2D slot fills and the 3D coils. */
export const PUBLIC_PHASE_COLORS = {
  A: '#f59e0b',
  B: '#34d399',
  C: '#a78bfa',
} as const;

export type PublicPhaseId = keyof typeof PUBLIC_PHASE_COLORS;

/**
 * How much to scale a flat 2D fill down before handing it to a lit 3D material.
 *
 * The 3D scene runs ACES tone mapping at 1.12 exposure over a key light, three
 * fills and an environment map, which together lift a material well above its
 * base colour. This factor was tuned by eye against the 2D canvas rather than
 * derived: the framebuffer is not readable (`preserveDrawingBuffer` is off), so
 * there is no cheap way to solve for it. Specular highlights still ride above the
 * result, which keeps the parts reading as metal and moulded magnet, not flat ink.
 */
export const LIT_3D_COLOR_SCALE = 0.72;

/**
 * A 2D fill converted to the base colour a lit 3D material needs to render at
 * roughly that fill. `scale` is exposed for the few parts that want more or less
 * compensation than the shared default.
 */
export function renderTargetColor(hex: string, scale: number = LIT_3D_COLOR_SCALE): number {
  const value = hex.replace('#', '');
  const channel = (offset: number) => {
    const raw = parseInt(value.slice(offset, offset + 2), 16);
    return Math.max(0, Math.min(255, Math.round(raw * scale)));
  };
  return (channel(0) << 16) | (channel(2) << 8) | channel(4);
}
