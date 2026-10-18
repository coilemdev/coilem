import type { FieldProbe, FieldProbeDescription } from './FieldResultPlot';
import type { MotorConfig } from './model';

/**
 * What the field probe calls the element under the cursor. The solver tags each
 * element with one region: rotor_core, magnet, airgap, stator_tooth,
 * stator_yoke, slot_winding, flux_barrier or magnet_pocket_air. The last one is
 * air, not magnet: the pockets around buried magnets, the gaps between surface
 * magnets, and the shaft bore at the centre. The bore is told apart by radius.
 */
export type FieldRegionKind =
  | 'stator_tooth'
  | 'stator_yoke'
  | 'stator_steel'
  | 'rotor_steel'
  | 'magnet'
  | 'winding'
  | 'airgap'
  | 'shaft_bore'
  | 'magnet_pocket'
  | 'flux_barrier'
  | 'air'
  | 'other';

const AIR_KINDS: ReadonlySet<FieldRegionKind> = new Set(['airgap', 'shaft_bore', 'magnet_pocket', 'flux_barrier', 'air']);

export function isAirFieldRegion(kind: FieldRegionKind): boolean {
  return AIR_KINDS.has(kind);
}

/**
 * The kind of a solver region tag. `radiusMm` is the element's distance from
 * the axis, and `rotorBoreRadiusMm` the rotor's inner radius (null for a solid
 * rotor), which separate the shaft bore from the magnet pockets.
 */
export function fieldRegionKind(
  region: string,
  radiusMm: number | null = null,
  rotorBoreRadiusMm: number | null = null,
): FieldRegionKind {
  const name = region.replace(/[_-]+/g, ' ').trim().toLowerCase();
  // Air tags first: "magnet pocket air" names air, not a magnet.
  if (/\bpocket\b/.test(name)) {
    return radiusMm !== null && rotorBoreRadiusMm !== null && radiusMm < rotorBoreRadiusMm
      ? 'shaft_bore'
      : 'magnet_pocket';
  }
  if (/flux barrier/.test(name)) return 'flux_barrier';
  if (/stator.*tooth|tooth.*stator/.test(name)) return 'stator_tooth';
  if (/stator.*yoke|yoke.*stator/.test(name)) return 'stator_yoke';
  if (/stator/.test(name)) return 'stator_steel';
  if (/rotor/.test(name)) return 'rotor_steel';
  if (/magnet/.test(name)) return 'magnet';
  if (/slot|winding|coil|copper/.test(name)) return 'winding';
  if (/air ?gap/.test(name)) return 'airgap';
  if (/air/.test(name)) return 'air';
  return 'other';
}

/** The probe card's heading for a region. Surface magnets have gaps, not pockets. */
export function fieldRegionLabel(kind: FieldRegionKind, region: string, surfaceMagnets = false): string {
  switch (kind) {
    case 'stator_tooth': return 'Stator tooth';
    case 'stator_yoke': return 'Stator yoke';
    case 'stator_steel': return 'Stator steel';
    case 'rotor_steel': return 'Rotor steel';
    case 'magnet': return 'Permanent magnet';
    case 'winding': return 'Winding region';
    case 'airgap': return 'Air gap';
    case 'shaft_bore': return 'Shaft bore (air)';
    case 'magnet_pocket': return surfaceMagnets ? 'Air between magnets' : 'Magnet pocket (air)';
    case 'flux_barrier': return 'Flux barrier (air)';
    case 'air': return 'Air';
    default: return region.replace(/[_-]+/g, ' ').trim() || 'Unclassified region';
  }
}

/** The probe card: region, material and, for steel, where |B| sits against the knee. */
export function describeFieldProbe(
  probe: FieldProbe,
  config: Pick<MotorConfig, 'topology' | 'rotor' | 'materials'>,
): FieldProbeDescription {
  const boreRadiusMm = config.rotor.ID_mm ? config.rotor.ID_mm / 2 : null;
  const kind = fieldRegionKind(probe.region, probe.radiusMm ?? null, boreRadiusMm);
  const regionLabel = fieldRegionLabel(kind, probe.region, config.topology === 'SPM');
  const isStatorSteel = kind === 'stator_tooth' || kind === 'stator_yoke' || kind === 'stator_steel';
  if (isStatorSteel || kind === 'rotor_steel') {
    const materialLabel = isStatorSteel ? config.materials.stator_steel : config.materials.rotor_steel;
    if (probe.bMagT >= 1.6) {
      return { regionLabel, materialLabel, saturationLabel: 'Above the 1.4–1.6 T reference knee', saturationTone: 'warning' };
    }
    if (probe.bMagT >= 1.4) {
      return { regionLabel, materialLabel, saturationLabel: 'Within the 1.4–1.6 T reference knee', saturationTone: 'warning' };
    }
    return { regionLabel, materialLabel, saturationLabel: 'Below the 1.4–1.6 T reference knee', saturationTone: 'good' };
  }
  if (kind === 'magnet') {
    return { regionLabel, materialLabel: config.materials.magnet_grade, saturationLabel: 'Steel saturation does not apply', saturationTone: 'neutral' };
  }
  if (kind === 'winding') {
    return { regionLabel, materialLabel: config.materials.conductor, saturationLabel: 'Approximately nonmagnetic · μr ≈ 1', saturationTone: 'neutral' };
  }
  return {
    regionLabel,
    materialLabel: isAirFieldRegion(kind) ? 'Air' : 'Solver region',
    saturationLabel: 'No steel saturation assessment',
    saturationTone: 'neutral',
  };
}
