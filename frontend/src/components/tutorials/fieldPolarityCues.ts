import type { AirgapBrBtProfile } from './lessonSolveTypes';

export type MagneticSurface = 'rotor' | 'stator';

export interface MagneticPolarityCue {
  angleDeg: number;
  label: 'N' | 'S';
}

export interface AirgapHarmonic {
  /** Mechanical angle of one positive-Br peak (flux crossing rotor -> stator). */
  peakDeg: number;
  amplitudeT: number;
}

function finiteAirgapBins(profile: AirgapBrBtProfile | null | undefined) {
  return profile?.bins?.filter((bin) => (
    Number.isFinite(bin.mech_angle_deg)
    && Number.isFinite(bin.br_t)
    && (bin.samples ?? 0) > 0
  )) ?? [];
}

/** Fit one spatial harmonic (in pole pairs) of signed air-gap Br. */
export function airgapHarmonic(
  profile: AirgapBrBtProfile | null | undefined,
  polePairs: number,
): AirgapHarmonic | null {
  const finiteBins = finiteAirgapBins(profile);
  if (finiteBins.length < Math.max(4, polePairs * 2)) return null;

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
  if (weightSum <= 0) return null;
  cosine /= weightSum;
  sine /= weightSum;
  const amplitudeT = 2 * Math.hypot(cosine, sine);
  if (!Number.isFinite(amplitudeT) || amplitudeT < 1e-6) return null;
  return {
    peakDeg: ((Math.atan2(sine, cosine) * 180) / Math.PI / polePairs + 360) % (360 / polePairs),
    amplitudeT,
  };
}

/**
 * The pole-pair count of the strongest air-gap Br harmonic up to `maxPolePairs`,
 * for a profile covering the full circle; null otherwise.
 */
export function strongestAirgapPolePairs(
  profile: AirgapBrBtProfile | null | undefined,
  maxPolePairs: number,
): number | null {
  if (!profile || Math.abs(profile.span_deg - 360) > 1e-6) return null;
  let strongest: number | null = null;
  let strongestAmplitude = 0;
  for (let order = 1; order <= maxPolePairs; order += 1) {
    const amplitude = airgapHarmonic(profile, order)?.amplitudeT ?? 0;
    if (amplitude > strongestAmplitude) {
      strongest = order;
      strongestAmplitude = amplitude;
    }
  }
  return strongest;
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
  const evenPoleCount = Math.max(2, Math.round(poles / 2) * 2);
  const polePairs = evenPoleCount / 2;
  const harmonic = airgapHarmonic(profile, polePairs);
  if (!harmonic) return [];
  const positivePeakDeg = harmonic.peakDeg;

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
