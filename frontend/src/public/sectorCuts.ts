/**
 * A sector solve meshes one sector at the meshed rotor angle; every other rotor
 * position is solved as its own sector, cut where a tooth and a pole gap are
 * nearest each other. The backend sends where those cuts fall over one
 * revolution (backend/sector_geometry.py sector_cuts_by_turn).
 */
import type { SectorCut } from './model';

/**
 * The cuts a sector solve makes with the rotor turned from the meshed angle;
 * null without a table. A positive view angle turns the rotor clockwise, the
 * way a sweep turns it.
 */
export function sectorCutAt(cuts: SectorCut[] | null | undefined, rotorAngleDeg: number): SectorCut | null {
  if (!cuts?.length) return null;
  const turn = ((-rotorAngleDeg % 360) + 360) % 360;
  let low = 0;
  let high = cuts.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    // A sweep often stops exactly where the cut steps; there the new cut applies.
    if (cuts[middle].turn_from_deg <= turn + 1e-6) low = middle;
    else high = middle - 1;
  }
  return cuts[low];
}

/**
 * Where the stator and rotor are cut on screen, in the stator's frame (degrees,
 * counter-clockwise), with the rotor turned to the view angle. The wedges meet on
 * the mid-gap circle: the stator side of the air gap is cut with the stator, the
 * rotor side with the rotor.
 */
export function sectorCutAnglesDeg(cut: SectorCut, rotorAngleDeg: number): { statorDeg: number; rotorDeg: number } {
  const rotorDeg = cut.rotor_cut_deg - rotorAngleDeg;
  return { statorDeg: cut.stator_on_rotor_cut ? rotorDeg : cut.stator_cut_deg, rotorDeg };
}

export interface RingSector {
  startDeg: number;
  sweepDeg: number;
  innerMm: number;
  outerMm: number;
}

/**
 * The part of the motor solved at the cut (or, with ``solved`` false, the copies
 * outside it) as two ring sectors that meet on the mid-gap circle: the stator and
 * its side of the air gap from the stator cut, the rotor and its side from the
 * rotor cut. ``farMm`` is any radius beyond the motor.
 */
export function sectorRings(
  cut: { statorDeg: number; rotorDeg: number },
  spanDeg: number,
  midGapMm: number,
  farMm: number,
  rotorOutside: boolean,
  solved: boolean,
): RingSector[] {
  const sides: Array<[number, number, number]> = [
    [cut.statorDeg, rotorOutside ? 0 : midGapMm, rotorOutside ? midGapMm : farMm],
    [cut.rotorDeg, rotorOutside ? midGapMm : 0, rotorOutside ? farMm : midGapMm],
  ];
  return sides.map(([startDeg, innerMm, outerMm]) => ({
    startDeg: solved ? startDeg : startDeg + spanDeg,
    sweepDeg: solved ? spanDeg : 360 - spanDeg,
    innerMm,
    outerMm,
  }));
}
