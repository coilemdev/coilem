import type { AirgapBrBtProfile } from './lessonSolveTypes';

export type MagneticSurface = 'rotor' | 'stator';

export interface MagneticPolarityCue {
  angleDeg: number;
  label: 'N' | 'S';
}

/**
 * Fit the pole-pair spatial harmonic of signed air-gap Br. Tooth ripple and
 * local saturation remain in the field plot, while the N/S cues communicate
 * the stable electromagnetic pole centers a user is trying to identify.
 */
export function deriveMagneticPolarityCues(
  profile: AirgapBrBtProfile | null | undefined,
  poles: number,
  surface: MagneticSurface,
): MagneticPolarityCue[] {
  const finiteBins = profile?.bins?.filter((bin) => (
    Number.isFinite(bin.mech_angle_deg)
    && Number.isFinite(bin.br_t)
    && (bin.samples ?? 0) > 0
  )) ?? [];
  const evenPoleCount = Math.max(2, Math.round(poles / 2) * 2);
  const polePairs = evenPoleCount / 2;
  if (finiteBins.length < Math.max(4, polePairs * 2)) return [];

  let cosine = 0;
  let sine = 0;
  let weightSum = 0;
  for (const bin of finiteBins) {
    const weight = Math.max(1, bin.samples ?? 1);
    const angleRad = (bin.mech_angle_deg * Math.PI) / 180;
    cosine += weight * bin.br_t * Math.cos(polePairs * angleRad);
    sine += weight * bin.br_t * Math.sin(polePairs * angleRad);
    weightSum += weight;
  }
  if (weightSum <= 0) return [];
  cosine /= weightSum;
  sine /= weightSum;
  const harmonicAmplitudeT = 2 * Math.hypot(cosine, sine);
  if (!Number.isFinite(harmonicAmplitudeT) || harmonicAmplitudeT < 1e-6) return [];

  const positivePeakDeg = (
    (Math.atan2(sine, cosine) * 180) / Math.PI / polePairs
    + 360
  ) % (360 / polePairs);

  return Array.from({ length: evenPoleCount }, (_, index) => {
    const radialFieldIsPositive = index % 2 === 0;
    // Positive Br points rotor -> stator: it exits a rotor N pole and enters a
    // stator S pole. The labels therefore invert across the air gap.
    const label = surface === 'rotor'
      ? (radialFieldIsPositive ? 'N' : 'S')
      : (radialFieldIsPositive ? 'S' : 'N');
    return {
      angleDeg: positivePeakDeg + index * (360 / evenPoleCount),
      label,
    };
  });
}
