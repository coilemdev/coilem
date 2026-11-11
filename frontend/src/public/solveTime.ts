/**
 * The plain reading of a solve's time breakdown (solve_metadata.time_breakdown):
 * three steps that add up to the elapsed time, and the stages inside each
 * step with their time across parallel workers.
 */

export type SolveTimePart = {
  label: string;
  indent: number;
  count: number;
  total_s: number;
  mean_s: number;
  max_s: number;
};

export type SolveTimeStep = {
  key: string;
  label: string;
  work_s: number;
  started_s: number;
  ended_s: number;
  parts: SolveTimePart[];
};

export type SolveTimeBreakdown = {
  schema_version: 'coilem.solve_time_breakdown.v1';
  elapsed_s: number;
  elapsed_steps: Array<{ key: string; label: string; detail: string; seconds: number }>;
  steps: SolveTimeStep[];
  counts: { meshes_built: number; meshes_rotated: number; solves: number; field_frames: number };
};

export type SolveTimeSegment = {
  key: string;
  label: string;
  detail: string;
  seconds: number;
  /** Share of the elapsed time, 0 to 1. */
  share: number;
  text: string;
  shareText: string;
};

export type SolveTimeRow = {
  key: string;
  label: string;
  indent: number;
  count: string;
  total: string;
  mean: string;
  max: string;
  /** Share of its step's largest top-level row, 0 to 1, for the bar behind the row. */
  weight: number;
};

export type SolveTimeView = {
  elapsed: string;
  segments: SolveTimeSegment[];
  facts: Array<{ key: string; label: string; value: string }>;
  steps: Array<{ key: string; label: string; summary: string; rows: SolveTimeRow[] }>;
};

/** Seconds as a short figure: 0.043 s, 1.35 s, 12.8 s, 155 s, 21 min. */
export function formatSeconds(seconds: number): string {
  if (!Number.isFinite(seconds)) return '—';
  const value = Math.max(0, seconds);
  if (value >= 6000) return `${Math.round(value / 60)} min`;
  if (value >= 100) return `${Math.round(value)} s`;
  if (value >= 10) return `${value.toFixed(1)} s`;
  if (value >= 1) return `${value.toFixed(2)} s`;
  return `${value.toFixed(3)} s`;
}

function percent(share: number): string {
  if (!Number.isFinite(share) || share <= 0) return '0%';
  return share < 0.01 ? '<1%' : `${Math.round(share * 100)}%`;
}

export function isSolveTimeBreakdown(value: unknown): value is SolveTimeBreakdown {
  const candidate = value as SolveTimeBreakdown | null | undefined;
  return Boolean(
    candidate
      && candidate.schema_version === 'coilem.solve_time_breakdown.v1'
      && Number.isFinite(candidate.elapsed_s)
      && Array.isArray(candidate.steps)
      && Array.isArray(candidate.elapsed_steps),
  );
}

export function solveTimeView(breakdown: SolveTimeBreakdown | null | undefined): SolveTimeView | null {
  if (!isSolveTimeBreakdown(breakdown)) return null;
  const elapsed = Math.max(breakdown.elapsed_s, 1e-9);
  const segments = breakdown.elapsed_steps.map(step => {
    const share = Math.min(1, Math.max(0, step.seconds / elapsed));
    return { ...step, share, text: formatSeconds(step.seconds), shareText: percent(share) };
  });
  const counts = breakdown.counts;
  const facts: SolveTimeView['facts'] = [];
  if (counts) {
    if (counts.meshes_built || counts.meshes_rotated) {
      facts.push({
        key: 'meshes',
        label: 'Meshes',
        value: counts.meshes_rotated
          ? `${counts.meshes_built} generated, ${counts.meshes_rotated} rotated from them`
          : `${counts.meshes_built} generated`,
      });
    }
    if (counts.solves) facts.push({ key: 'solves', label: 'Field solves', value: String(counts.solves) });
    if (counts.field_frames) facts.push({ key: 'frames', label: 'Field frames', value: String(counts.field_frames) });
  }
  const steps = breakdown.steps.map(step => {
    const largest = Math.max(1e-9, ...step.parts.filter(part => part.indent === 0).map(part => part.total_s));
    return {
      key: step.key,
      label: step.label,
      summary: `${formatSeconds(step.work_s)} of work across workers, between ${formatSeconds(step.started_s)} and ${formatSeconds(step.ended_s)} into the solve`,
      rows: step.parts.map((part, index) => ({
        key: `${step.key}-${index}`,
        label: part.label,
        indent: part.indent,
        count: String(part.count),
        total: formatSeconds(part.total_s),
        mean: formatSeconds(part.mean_s),
        max: formatSeconds(part.max_s),
        weight: Math.min(1, Math.max(0, part.total_s / largest)),
      })),
    };
  });
  return { elapsed: formatSeconds(breakdown.elapsed_s), segments, facts, steps };
}
