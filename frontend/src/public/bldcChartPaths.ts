// Phase signs (A, B, C) of each ideal six-step sector; _PUBLIC_SIX_STEP_TABLE in backend/excitation.py.
const SIX_STEP_SECTOR_SIGNS = [[1, -1, 0], [0, -1, 1], [-1, 0, 1], [-1, 1, 0], [0, 1, -1], [1, 0, -1]] as const;

/** The sector (0–5) whose phase pair conducts in these recorded currents, or null when they are not an ideal six-step pair. */
export function recordedSector(a: number, b: number, c: number): number | null {
  const signs = [a, b, c].map((current) => (Math.abs(current) > 1e-9 ? Math.sign(current) : 0));
  const sector = SIX_STEP_SECTOR_SIGNS.findIndex((row) => row.every((sign, phase) => sign === signs[phase]));
  return sector < 0 ? null : sector;
}

export interface SectorSegment { start: number; end: number; sector: number }

/**
 * Commutation sectors as the solve recorded them (#345): each solved angle carries the
 * sector of its conducting pair until the next solved angle, so a label always changes
 * with the currents. The motor's electrical-axis offset is in the recorded currents and
 * not in the angle, so a sector cannot be read from the angle alone; `fallback` is for a
 * sample whose currents are not an ideal pair. Angles are in [0, 360), in solved order.
 */
export function recordedSectorSegments(
  angles: number[],
  phaseA: number[],
  phaseB: number[],
  phaseC: number[],
  fallback: (angle: number) => number,
  cycleComplete: boolean,
): SectorSegment[] {
  const segments: SectorSegment[] = [];
  for (let index = 0; index < angles.length; index += 1) {
    const start = angles[index];
    const next = index + 1 < angles.length ? angles[index + 1] : cycleComplete ? 360 : start;
    // A sweep that passes 360° continues from the left edge with its next sample.
    const end = next < start ? 360 : next;
    const sector = recordedSector(phaseA[index], phaseB[index], phaseC[index]) ?? fallback(start);
    const previous = segments[segments.length - 1];
    if (previous && previous.sector === sector && previous.end === start) previous.end = end;
    else segments.push({ start, end, sector });
  }
  // The last angle of a partial sweep has no span to shade.
  return segments.filter((segment) => segment.end > segment.start);
}

/** Step-after paths, split by conducting state without shifting transitions. */
export function currentStepSegments(
  angles: number[],
  values: number[],
  x: (angle: number) => number,
  y: (value: number) => number,
  cycleEndX?: number,
): Array<{ conducting: boolean; path: string }> {
  const segments: Array<{ conducting: boolean; path: string }> = [];
  let current: { conducting: boolean; path: string } | undefined;
  for (let index = 0; index < values.length; index += 1) {
    const conducting = Math.abs(values[index]) > 1e-9;
    const px = x(angles[index]).toFixed(2);
    const py = y(values[index]).toFixed(2);
    if (!current) {
      current = { conducting, path: `M ${px} ${py}` };
    } else if (current.conducting !== conducting) {
      current.path += ` H ${px}`;
      segments.push(current);
      current = {
        conducting,
        path: `M ${px} ${y(values[index - 1]).toFixed(2)} V ${py}`,
      };
    } else {
      current.path += ` H ${px} V ${py}`;
    }
  }
  if (current) {
    if (cycleEndX !== undefined) current.path += ` H ${cycleEndX.toFixed(2)}`;
    segments.push(current);
  }
  return segments;
}
