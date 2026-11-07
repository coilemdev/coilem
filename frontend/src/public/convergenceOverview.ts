/**
 * A plain-language reading of the solver convergence report (the same backend
 * report the PDF and CSV carry). The card leads with this; the report's own
 * rows and per-position table stay underneath as technical details.
 */
import type { SolverConvergenceReport } from './model';

export interface ConvergenceFact {
  key: string;
  label: string;
  value: string;
  hint: string;
}

export interface ConvergenceOverview {
  tone: 'ok' | 'review' | 'muted';
  label: string;
  verdict: string;
  facts: ConvergenceFact[];
}

const percent = (ratio: number) => `${Math.round(ratio * 100)}%`;
const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
const rowValue = (report: SolverConvergenceReport, key: string) => report.summary.find((row) => row.key === key)?.value ?? null;

function median(values: number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function convergenceOverview(report?: SolverConvergenceReport | null): ConvergenceOverview {
  if (!report || report.status === 'not_recorded') {
    return {
      tone: 'muted',
      label: 'Not recorded',
      verdict: 'This run did not record solver convergence, so it cannot be checked here. Missing residuals and limits cannot be recovered from iteration counts or current settings.',
      facts: [],
    };
  }
  const recorded = report.positions.filter((position) => position.record);
  const nonlinear = recorded.filter((position) => position.record?.method !== 'linear');
  const solved = nonlinear.filter((position) => !position.record?.solution_reused);
  const reused = recorded.filter((position) => position.record?.solution_reused).length;
  const ratios = nonlinear.flatMap((position) => (position.stopping_ratio === null ? [] : [position.stopping_ratio]));
  const worstRatio = ratios.length ? Math.max(...ratios) : null;
  const iterations = solved.map((position) => position.record!.iterations);
  const hardest = solved.reduce<(typeof solved)[number] | null>(
    (worst, position) => (!worst || position.record!.iterations > worst.record!.iterations ? position : worst),
    null,
  );
  const aboveLimit = nonlinear.filter((position) => position.stopping_ratio !== null && position.stopping_ratio > 1).length;
  const nearCap = nonlinear.filter((position) => position.iteration_fraction !== null && position.iteration_fraction >= 0.8).length;
  const missing = report.positions.length - recorded.length;
  const flagged = report.positions.filter((position) => position.review).length;

  const plan = rowValue(report, 'accuracy_plan');
  const density = rowValue(report, 'mesh_density');
  const elements = Number(rowValue(report, 'mesh_elements'));
  const facts: ConvergenceFact[] = [
    {
      key: 'positions',
      label: 'Rotor positions checked',
      value: `${recorded.length} of ${report.positions.length}${reused ? ` · ${reused} reused` : ''}`,
      hint: reused
        ? 'Reused positions took a field already solved for the same inputs.'
        : 'Every recorded position was solved on its own.',
    },
  ];
  if (worstRatio !== null) {
    facts.push({
      key: 'worst_error',
      label: 'Worst remaining error',
      value: `${percent(worstRatio)} of allowed`,
      hint: 'Each position stops once its error is under the allowed value (100%).',
    });
  }
  if (hardest) {
    facts.push({
      key: 'iterations',
      label: 'Iterations',
      value: `${hardest.record!.iterations} of ${hardest.record!.max_iterations} allowed`,
      hint: `The slowest position; the typical one took ${Math.round(median(iterations))}.`,
    });
  }
  if (plan || density || Number.isFinite(elements)) {
    facts.push({
      key: 'mesh',
      label: 'Mesh',
      value: [density, Number.isFinite(elements) && elements > 0 ? `${elements.toLocaleString('en-US')} elements` : null].filter(Boolean).join(' · ') || 'Not recorded',
      hint: plan ? `${plan} accuracy plan. Convergence does not check mesh accuracy.` : 'Convergence does not check mesh accuracy.',
    });
  }

  if (report.status === 'review') {
    const reasons = [
      aboveLimit ? `${aboveLimit} stopped above the allowed error` : null,
      nearCap ? `${nearCap} used 80% or more of the iteration limit` : null,
    ].filter(Boolean);
    return {
      tone: 'review',
      label: 'Needs review',
      verdict: `${flagged} of ${recorded.length} rotor positions need a look: ${reasons.join('; ')}. `
        + 'Their torque and Back EMF are less certain, so check the waveforms for a spike at those angles.',
      facts,
    };
  }
  if (report.status === 'partial') {
    const missingResidual = nonlinear.length - ratios.length;
    const gaps = [
      missing ? `${plural(missing, 'position has', 'positions have')} no convergence record` : null,
      missingResidual ? `${plural(missingResidual, 'position has', 'positions have')} no final error recorded` : null,
    ].filter(Boolean);
    return {
      tone: 'muted',
      label: 'Incomplete records',
      verdict: `${gaps.join('; ')}, so ${missing + missingResidual === 1 ? 'it' : 'they'} cannot be checked. The recorded positions are within their limits.`,
      facts,
    };
  }
  if (!nonlinear.length) {
    return {
      tone: 'ok',
      label: 'Linear solves',
      verdict: 'Every position was solved in one step with linear materials, so there was nothing to iterate.',
      facts,
    };
  }
  const reuseNote = reused ? ` (${plural(reused, 'reused a field', 'reused fields')} already solved for the same inputs)` : '';
  const hardestNote = worstRatio !== null && hardest
    ? ` The hardest finished at ${percent(worstRatio)} of the allowed error, using ${hardest.record!.iterations} of ${hardest.record!.max_iterations} iterations.`
    : '';
  return {
    tone: 'ok',
    label: 'Converged',
    verdict: `All ${recorded.length} rotor positions converged${reuseNote}.${hardestNote}`,
    facts,
  };
}
