/**
 * Stator radii for the parametric 3D view, named by role so one build serves
 * both rotor layouts. An outer rotor turns the machine inside out: the stator's
 * yoke sits on its hub with the teeth pointing out to the air gap at its OD, and
 * the rotor is a ring round it. An inner rotor's values are the ones it always had.
 */
import type { MotorConfig } from './model';

type StatorRadiiConfig = Pick<MotorConfig, 'rotor_layout'> & {
  stator: Pick<MotorConfig['stator'], 'OD_mm' | 'ID_mm' | 'yoke_thickness_mm'>;
  rotor: Pick<MotorConfig['rotor'], 'OD_mm'>;
};

export interface Stator3dRadii {
  outerRotor: boolean;
  /** The machine's overall radius: the stator OD, or an outer rotor's OD. */
  outerRadius: number;
  /** Where the teeth meet the air gap: an inner stator's bore, an outer stator's OD. */
  statorInnerRadius: number;
  /** Where the teeth meet the yoke, the slot bottom. */
  yokeInnerRadius: number;
  /** The yoke's far face: the stator OD, or an outer stator's hub bore. */
  yokeOuterRadius: number;
  /** Where the drawn coils start winding, which keeps them at least 2 mm long. */
  coilRootRadius: number;
}

// The drawn coils need about this much tooth to wind round.
const MIN_COIL_TOOTH_MM = 2;

export function stator3dRadii(config: StatorRadiiConfig): Stator3dRadii {
  const outerRotor = config.rotor_layout === 'outer';
  if (!outerRotor) {
    const outerRadius = config.stator.OD_mm / 2;
    const statorInnerRadius = config.stator.ID_mm / 2;
    const yokeInnerRadius = Math.max(statorInnerRadius + MIN_COIL_TOOTH_MM, outerRadius - config.stator.yoke_thickness_mm);
    return {
      outerRotor,
      outerRadius,
      statorInnerRadius,
      yokeInnerRadius,
      yokeOuterRadius: outerRadius,
      coilRootRadius: yokeInnerRadius,
    };
  }
  const statorInnerRadius = config.stator.OD_mm / 2;
  const yokeOuterRadius = config.stator.ID_mm / 2;
  // The hub plus its yoke, as the backend draws it. Outer slots may be as
  // shallow as 0.5 mm, so no tooth-depth floor here: it would move the slot
  // bottom onto the hub and leave the yoke a zero-width ring. The margin only
  // keeps an invalid in-progress edit from turning the tooth inside out.
  const yokeInnerRadius = Math.min(statorInnerRadius - 0.1, yokeOuterRadius + config.stator.yoke_thickness_mm);
  return {
    outerRotor,
    outerRadius: config.rotor.OD_mm / 2,
    statorInnerRadius,
    yokeInnerRadius,
    yokeOuterRadius,
    // In a slot shallower than that, the illustrative coil runs back into the
    // yoke rather than out across the air gap into the magnets.
    coilRootRadius: Math.min(yokeInnerRadius, statorInnerRadius - MIN_COIL_TOOTH_MM),
  };
}

/**
 * How far a tooth shoe's shoulder sits from the gap face towards the slot
 * bottom, 0 at the gap and 1 at the yoke. Measured as distances, so it holds
 * for an outer stator, whose radii decrease from the gap to the yoke.
 */
export function shoeShoulderFraction(statorInnerRadius: number, shoulderRadius: number, yokeInnerRadius: number): number {
  const fraction = Math.abs(shoulderRadius - statorInnerRadius) / Math.max(1e-6, Math.abs(yokeInnerRadius - statorInnerRadius));
  return Math.min(1, Math.max(0, fraction));
}
