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
