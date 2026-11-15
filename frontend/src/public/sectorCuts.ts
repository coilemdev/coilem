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
