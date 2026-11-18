/**
 * The Field solution's Phases layer: the Geometry view's drive panel (A / B / C
 * waveforms wired into the motor) beside the field, the coils outlined by phase,
 * and a ⊙ or ⊗ on each coil side for the way its current flows at the position
 * on screen.
 *
 * The currents are the ones the solver applied at each solved position, as the
 * result records them (slot_excitation_frames), so the marks and waveforms
 * belong to the frame shown even if the design's drive settings have changed
 * since. The coils and their marks come from the design's geometry preview, as
 * in the Geometry view (phaseDrive.ts): an "in" side carries +J, out of the page.
 */

import {
  coilSideOutOfPage,
  toothPosition,
  windingSymbolSide,
  wrap360,
  type PhaseCurrentSampler,
  type PhaseDrive,
  type WindingSide,
} from './phaseDrive';
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
  /** The drive's kind and poles, for the panel's caption and frequency. */
  drive: PhaseDrive;
  /** Playback speed: the panel's waveforms show the cycles the drive runs at it in one second. */
  rpm: number;
}

/** A coil side of the stator, in model millimetres (y up). */
export interface CoilSide {
  phase: PhaseId;
  direction: WindingSide['direction'];
  points: Array<[number, number]>;
}

/** A ⊙ / ⊗ place from the geometry preview's glyphs, in model millimetres. */
export interface CoilMark {
  phase: PhaseId;
  direction: WindingSide['direction'];
  centre: [number, number];
  radiusMm: number;
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

/** Whether every recorded current is off or at full, as a six-step drive's are. */
export function isSteppedCycle(cycle: PhaseCycle): boolean {
  if (!(cycle.peakA > 0)) return false;
  return cycle.samples.every((sample) => sample.currentsA.every((current) => {
    const share = Math.abs(current) / cycle.peakA;
    return share < 1e-3 || Math.abs(share - 1) < 1e-3;
  }));
}

/**
 * The recorded currents as shares of their peak at any angle, for the drive
 * panel's waveforms: straight between solved positions, or held from one to the
 * next where every current is off or at full (six-step), so its steps stay steps.
 */
export function phaseCycleSampler(cycle: PhaseCycle): PhaseCurrentSampler {
  const { samples, peakA } = cycle;
  if (!(peakA > 0)) return () => [0, 0, 0];
  const shares = samples.map((sample) => sample.currentsA.map((current) => current / peakA) as [number, number, number]);
  const stepped = isSteppedCycle(cycle);
  return (angleDeg) => {
    const angle = wrap360(angleDeg);
    // The last position at or before the angle, wrapping to the cycle's end.
    let index = samples.length - 1;
    for (let candidate = 0; candidate < samples.length; candidate += 1) {
      if (samples[candidate].angleDeg <= angle) index = candidate;
      else break;
    }
    const next = (index + 1) % samples.length;
    if (stepped || samples.length === 1) return [...shares[index]] as [number, number, number];
    const start = samples[index].angleDeg;
    const span = wrap360(samples[next].angleDeg - start) || 360;
    const t = Math.min(1, wrap360(angle - start) / span);
    return shares[index].map((value, phase) => value + (shares[next][phase] - value) * t) as [number, number, number];
  };
}

/** The phase and side of a coil region from its type, "slot_3_(a−)": "+" goes in, "−" comes out. */
export function coilRegionSide(regionType: string): Pick<CoilSide, 'phase' | 'direction'> | null {
  const match = /\(([abc])([+\-−])\)/i.exec(regionType);
  if (!match) return null;
  return { phase: match[1].toUpperCase() as PhaseId, direction: match[2] === '+' ? 'in' : 'out' };
}

/** Every coil side in the geometry preview, for its outline. */
export function coilSidesFromGeometry(geometry: GeometryPreview | null | undefined): CoilSide[] {
  if (!geometry) return [];
  return geometry.regions.flatMap((region): CoilSide[] => {
    const side = coilRegionSide(region.region_type);
    if (!side || region.points.length < 3) return [];
    return [{ ...side, points: region.points.map(([x, y]) => [x, y] as [number, number]) }];
  });
}

/** Stationary tooth polygons in model millimetres, indexed the same way as Geometry's tooth poles. */
export function statorTeethFromGeometry(geometry: GeometryPreview | null | undefined) {
  const slotCount = Number(geometry?.metadata?.slot_count);
  if (!geometry || !Number.isInteger(slotCount) || slotCount <= 0) return [];
  return geometry.regions.flatMap(({ region_type, points }) => {
    if (!/stator_tooth/i.test(region_type) || points.length < 3) return [];
    return [{ points, ...toothPosition(points, slotCount) }];
  });
}

/**
 * The ⊙ / ⊗ places the geometry preview draws (its winding_symbol glyphs, as the
 * Geometry view reads them): one per coil side, a ⊗'s two bars counted once and
 * centred between them.
 */
export function coilMarksFromGeometry(geometry: GeometryPreview | null | undefined): CoilMark[] {
  if (!geometry) return [];
  const marks: CoilMark[] = [];
  let lastOut: CoilMark | null = null;
  geometry.regions.forEach((region) => {
    if (region.region_type !== 'winding_symbol') return;
    const side = windingSymbolSide(region.label);
    if (!side) return;
    const corners = region.points.length > 1 ? region.points.slice(0, -1) : region.points;
    if (corners.length === 0) return;
    const centre: [number, number] = [
      corners.reduce((sum, [x]) => sum + x, 0) / corners.length,
      corners.reduce((sum, [, y]) => sum + y, 0) / corners.length,
    ];
    const radiusMm = Math.max(...corners.map(([x, y]) => Math.hypot(x - centre[0], y - centre[1])));
    if (
      side.direction === 'out'
      && lastOut?.phase === side.phase
      && Math.hypot(centre[0] - lastOut.centre[0], centre[1] - lastOut.centre[1]) < radiusMm
    ) {
      lastOut.centre = [(centre[0] + lastOut.centre[0]) / 2, (centre[1] + lastOut.centre[1]) / 2];
      lastOut = null;
      return;
    }
    const mark: CoilMark = { ...side, centre, radiusMm };
    marks.push(mark);
    lastOut = side.direction === 'out' ? mark : null;
  });
  return marks;
}

/**
 * Which way a side's current flows now: true out of the page (⊙), false into it
 * (⊗), null while its phase carries next to none of the cycle's peak.
 */
export function coilSideMark(side: Pick<CoilSide, 'phase' | 'direction'>, currentsA: PhaseCurrents, peakA: number): boolean | null {
  const current = currentsA[{ A: 0, B: 1, C: 2 }[side.phase]];
  return coilSideOutOfPage(side.direction, peakA > 0 ? current / peakA : 0);
}
