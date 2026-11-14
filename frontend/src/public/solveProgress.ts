import type { PublicSolveProgress } from './api';

const PUBLIC_FINALIZATION_STAGES = new Set([
  'magneto2d_complete',
  'packaging_results',
  'saving_run',
]);

export function isPublicSolveFinalizing(progress: PublicSolveProgress | null): boolean {
  if (!progress) return false;
  if (PUBLIC_FINALIZATION_STAGES.has(progress.stage)) return true;
  return progress.stage === 'solver_timing'
    && progress.total > 0
    && progress.position >= progress.total - 1;
}

/**
 * Share of the live-solve bar that the Gmsh mesh stage fills when a solve
 * reports one. Field solves run while meshing and are reported right after
 * it, so meshing is most of the wall time; solve positions fill the rest.
 */
export const PUBLIC_SOLVE_MESH_SHARE = 0.7;

/** What the live-solve bar shows: a percentage that only moves forward within one solve. */
export interface PublicSolveProgressBar {
  percent: number;
  /** Whether this solve reported a mesh stage, which then owns the first part of the bar. */
  meshStage: boolean;
}

export const EMPTY_PUBLIC_SOLVE_PROGRESS_BAR: PublicSolveProgressBar = { percent: 0, meshStage: false };

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function clampUnit(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/** Fraction of meshes ready (0..1) a mesh-stage event reports, or null. */
export function publicSolveMeshFraction(progress: PublicSolveProgress | null): number | null {
  const detail = (progress?.solver_detail ?? {}) as Record<string, unknown>;
  const completed = finiteNumber(detail.mesh_completed);
  const total = finiteNumber(detail.mesh_total);
  return completed !== null && total !== null && total > 0 ? clampUnit(completed / total) : null;
}

/** Fraction of field solves done (0..1) a sweep event reports, or null. */
export function publicSolvePositionFraction(progress: PublicSolveProgress | null): number | null {
  // Timing events repeat stale or empty counts (0 / 0 while packaging), and
  // position 0 means no field solve has finished yet.
  if (!progress || progress.stage === 'solver_timing' || progress.total <= 0 || progress.position <= 0) return null;
  return clampUnit(progress.position / progress.total);
}

/**
 * The live-solve bar after an event (#53). It restarts empty when a solve
 * starts, never decreases within one solve, and holds the full bar while
 * the result is finalized.
 */
export function nextPublicSolveProgressBar(
  previous: PublicSolveProgressBar,
  progress: PublicSolveProgress | null,
): PublicSolveProgressBar {
  if (!progress || progress.stage === 'Validating') return EMPTY_PUBLIC_SOLVE_PROGRESS_BAR;
  const analysisFraction = finiteNumber(progress.solver_detail?.analysis_fraction);
  if (analysisFraction !== null) return { percent: Math.max(previous.percent, clampUnit(analysisFraction) * 100), meshStage: false };
  if (isPublicSolveFinalizing(progress)) return { ...previous, percent: 100 };
  const meshFraction = publicSolveMeshFraction(progress);
  if (meshFraction !== null) {
    return { percent: Math.max(previous.percent, PUBLIC_SOLVE_MESH_SHARE * meshFraction * 100), meshStage: true };
  }
  const positionFraction = publicSolvePositionFraction(progress);
  if (positionFraction === null) return previous;
  const solveStart = previous.meshStage ? PUBLIC_SOLVE_MESH_SHARE : 0;
  const percent = (solveStart + (1 - solveStart) * positionFraction) * 100;
  return { ...previous, percent: Math.max(previous.percent, percent) };
}

/** What the viewport shows while a solve works through its positions. */
export interface PublicSolveRotorTurn {
  /** Mechanical degrees from the first position of the sweep. */
  turnDeg: number;
  /** Meshing turns the rotor; solving holds it where meshing left it, and the view pulses instead. */
  phase: 'meshing' | 'solving';
  /** The sweep is over and the result is being put together: the rotor is shown as designed again. */
  finished: boolean;
}

/**
 * The rotor turn to show after an event, or null when no sweep is under way.
 *
 * The rotor turns through the sweep as the meshes are prepared, forwards only,
 * and then stays still while the field is solved. It is drawn from progress
 * the solver already reports, so showing it costs the solve nothing; it is a
 * picture of how far meshing has got, not of any one mesh.
 */
export function nextPublicSolveRotorTurn(
  previous: PublicSolveRotorTurn | null,
  progress: PublicSolveProgress | null,
  sweepRangeElectricalDeg: number,
  poleCount: number,
): PublicSolveRotorTurn | null {
  if (!progress || progress.stage === 'Validating') return null;
  // Late timing events follow the end of a sweep; they must not start the turn again.
  if (previous?.finished) return previous;
  if (isPublicSolveFinalizing(progress)) {
    return previous ? { ...previous, finished: true } : null;
  }
  // A torque-speed map and other analyses that report one fraction do not sweep the rotor once.
  if (finiteNumber(progress.solver_detail?.analysis_fraction) !== null) return null;
  const polePairs = poleCount / 2;
  if (!(polePairs > 0) || !(sweepRangeElectricalDeg > 0)) return null;
  const meshFraction = publicSolveMeshFraction(progress);
  if (meshFraction !== null) {
    const turnDeg = (sweepRangeElectricalDeg / polePairs) * meshFraction;
    return { turnDeg: Math.max(previous?.turnDeg ?? 0, turnDeg), phase: 'meshing', finished: false };
  }
  if (publicSolvePositionFraction(progress) !== null) {
    return { turnDeg: previous?.turnDeg ?? 0, phase: 'solving', finished: false };
  }
  // Before the first mesh is ready the solve is already meshing.
  return previous ?? { turnDeg: 0, phase: 'meshing', finished: false };
}

type NamedFieldFrame = {
  field_frame_artifact?: { artifact_id?: unknown };
  full_field_frame_artifact?: { artifact_id?: unknown };
};

function namedFieldFrameId(frame: unknown): string | null {
  if (!frame || typeof frame !== 'object') return null;
  const named = frame as NamedFieldFrame;
  const artifactId = named.full_field_frame_artifact?.artifact_id ?? named.field_frame_artifact?.artifact_id;
  return typeof artifactId === 'string' && artifactId ? artifactId : null;
}

/**
 * The id of the stored field frame a progress event names, or null. The solve
 * stream names it on the frame it sends; the stator-field stream on a descriptor.
 */
export function publicProgressFieldFrameId(progress: PublicSolveProgress | null): string | null {
  return namedFieldFrameId(progress?.field_frame) ?? namedFieldFrameId(progress?.field_line_frame);
}

/**
 * The progress to keep after an event, with the first stored field frame the
 * solve named carried along as `field_frame`. Events arrive in bursts and only
 * the latest is kept, so without this the one event that names a frame is
 * usually replaced before anything can read it.
 */
export function withFirstPublicSolveFieldFrame(
  previous: PublicSolveProgress | null,
  next: PublicSolveProgress,
): PublicSolveProgress {
  if (next.stage === 'Validating') return next;
  const carriedId = publicProgressFieldFrameId(previous);
  if (carriedId === null) return next;
  return { ...next, field_frame: { field_frame_artifact: { artifact_id: carriedId } } };
}

export function projectedPublicSolveElapsedSeconds(
  reportedSeconds: number | undefined,
  observedAtMs: number,
  nowMs: number,
): number {
  const safeReportedSeconds = Number.isFinite(reportedSeconds)
    ? Math.max(0, reportedSeconds ?? 0)
    : 0;
  const additionalSeconds = Math.max(0, nowMs - observedAtMs) / 1000;
  return safeReportedSeconds + additionalSeconds;
}
