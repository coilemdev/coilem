/**
 * The Field solution's Phases layer: which coils carry current at the rotor
 * position on screen, and which way, beside the field they make.
 *
 * The currents are the ones the solver applied at each solved position, as the
 * result records them (slot_excitation_frames), so the marks belong to the frame
 * shown and not to a model of it. The coils and their in / out sides come from
 * the design's geometry preview, as in the Geometry view's Phases
 * (phaseDrive.ts): an "in" side carries +J, out of the page (⊙).
 */

import { COIL_SIDE_CURRENT_FLOOR, coilSideOutOfPage, wrap360, type WindingSide } from './phaseDrive';
import type { GeometryPreview } from './model';

export type PhaseId = WindingSide['phase'];
export type PhaseCurrents = readonly [number, number, number];

/** One solved position: its electrical angle and the A / B / C currents applied there, A. */
export interface PhaseCycleSample {
  angleDeg: number;
  currentsA: PhaseCurrents;
}

/** The applied currents over the solved positions, in angle order, and their largest magnitude. */
export interface PhaseCycle {
  samples: PhaseCycleSample[];
  peakA: number;
}

/** What the Phases layer shows for the frame on screen. */
export interface FieldPhaseView {
  /** The shown frame's electrical angle, degrees. */
  angleDeg: number;
  /** The currents in this field's solve, A; null for a field with no stator current (PM only). */
  currentsA: PhaseCurrents | null;
  cycle: PhaseCycle;
}

/** A coil side of the stator, in model millimetres (y up). */
export interface CoilSide {
  phase: PhaseId;
  direction: WindingSide['direction'];
  points: Array<[number, number]>;
  centre: [number, number];
  /** A mark radius that fits inside the side, mm. */
  markRadiusMm: number;
}

interface RecordedFrame {
  angle_deg?: unknown;
  phase_current_a?: unknown;
}

/** The solver's applied currents per position, from a result's slot_excitation_frames; null without them. */
export function phaseCycleFromFrames(frames: readonly RecordedFrame[] | null | undefined): PhaseCycle | null {
  const samples = (frames ?? []).flatMap((frame): PhaseCycleSample[] => {
    const angle = Number(frame?.angle_deg);
    const currents = Array.isArray(frame?.phase_current_a) ? frame.phase_current_a.map(Number) : [];
    if (!Number.isFinite(angle) || currents.length !== 3 || !currents.every(Number.isFinite)) return [];
    return [{ angleDeg: wrap360(angle), currentsA: [currents[0], currents[1], currents[2]] }];
  }).sort((first, second) => first.angleDeg - second.angleDeg);
  if (samples.length === 0) return null;
  const peakA = samples.reduce((peak, sample) => Math.max(peak, ...sample.currentsA.map(Math.abs)), 0);
  return { samples, peakA };
}

/** The currents at the solved position nearest an angle (wrapping round the cycle). */
export function phaseCurrentsAt(cycle: PhaseCycle, angleDeg: number): PhaseCurrents {
  const target = wrap360(angleDeg);
  const gap = (sample: PhaseCycleSample) => {
    const difference = Math.abs(sample.angleDeg - target);
    return Math.min(difference, 360 - difference);
  };
  return cycle.samples.reduce((best, sample) => (gap(sample) < gap(best) ? sample : best)).currentsA;
}

/** The phase and side of a coil region from its type, "slot_3_(a−)": "+" goes in, "−" comes out. */
export function coilRegionSide(regionType: string): Pick<CoilSide, 'phase' | 'direction'> | null {
  const match = /\(([abc])([+\-−])\)/i.exec(regionType);
  if (!match) return null;
  return { phase: match[1].toUpperCase() as PhaseId, direction: match[2] === '+' ? 'in' : 'out' };
}

function polygonArea(points: ReadonlyArray<readonly [number, number]>): number {
  let twice = 0;
  points.forEach(([x, y], index) => {
    const [nextX, nextY] = points[(index + 1) % points.length];
    twice += x * nextY - nextX * y;
  });
  return twice / 2;
}

/** Every coil side in the geometry preview, with its place for a ⊙ / ⊗ mark. */
export function coilSidesFromGeometry(geometry: GeometryPreview | null | undefined): CoilSide[] {
  if (!geometry) return [];
  return geometry.regions.flatMap((region): CoilSide[] => {
    const side = coilRegionSide(region.region_type);
    if (!side || region.points.length < 3) return [];
    const points = region.points.map(([x, y]) => [x, y] as [number, number]);
    const area = polygonArea(points);
    let centre: [number, number];
    if (Math.abs(area) > 1e-12) {
      let cx = 0;
      let cy = 0;
      points.forEach(([x, y], index) => {
        const [nextX, nextY] = points[(index + 1) % points.length];
        const cross = x * nextY - nextX * y;
        cx += (x + nextX) * cross;
        cy += (y + nextY) * cross;
      });
      centre = [cx / (6 * area), cy / (6 * area)];
    } else {
      centre = [
        points.reduce((sum, [x]) => sum + x, 0) / points.length,
        points.reduce((sum, [, y]) => sum + y, 0) / points.length,
      ];
    }
    return [{ ...side, points, centre, markRadiusMm: Math.sqrt(Math.abs(area)) * 0.24 }];
  });
}

/**
 * Which way a side's current flows now: true out of the page (⊙), false into it
 * (⊗), null while its phase carries next to none of the cycle's peak.
 */
export function coilSideMark(side: Pick<CoilSide, 'phase' | 'direction'>, currentsA: PhaseCurrents, peakA: number): boolean | null {
  const current = currentsA[{ A: 0, B: 1, C: 2 }[side.phase]];
  return coilSideOutOfPage(side.direction, peakA > 0 ? current / peakA : 0);
}

/** How strongly a side's phase is driven now, 0–1 of the cycle's peak. */
export function coilSideDrive(side: Pick<CoilSide, 'phase'>, currentsA: PhaseCurrents, peakA: number): number {
  if (!(peakA > 0)) return 0;
  const share = Math.abs(currentsA[{ A: 0, B: 1, C: 2 }[side.phase]]) / peakA;
  return share < COIL_SIDE_CURRENT_FLOOR ? 0 : Math.min(1, share);
}
