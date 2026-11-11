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

/** Where the viewport shows the rotor while a solve works through its positions. */
export interface PublicSolveRotorTurn {
  /** Mechanical degrees from the first position of the sweep. */
  turnDeg: number;
  phase: 'meshing' | 'solving';
  /** The sweep is over and the result is being put together: the rotor is shown as designed again. */
  finished: boolean;
}

/**
 * The rotor turn to show after an event, or null when no sweep is under way.
 *
 * It follows the live-solve bar, so it turns once through the sweep and never
 * backwards: meshing takes the rotor through the first part of the turn and
 * the field solves through the rest. It is drawn from progress the solver
 * already reports, so showing it costs the solve nothing; it is a picture of
 * how far the sweep has got, not of any one mesh.
 */
export function nextPublicSolveRotorTurn(
  previous: PublicSolveRotorTurn | null,
  progress: PublicSolveProgress | null,
  progressPercent: number,
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
  if (!(polePairs > 0) || !(sweepRangeElectricalDeg > 0) || !(progressPercent > 0)) return null;
  const turnDeg = (sweepRangeElectricalDeg / polePairs) * clampUnit(progressPercent / 100);
  const phase = publicSolveMeshFraction(progress) !== null
    ? 'meshing'
    : publicSolvePositionFraction(progress) !== null ? 'solving' : previous?.phase ?? 'meshing';
  return { turnDeg: Math.max(previous?.turnDeg ?? 0, turnDeg), phase, finished: false };
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
