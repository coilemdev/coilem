import type { ReactNode } from 'react';

export interface ComparisonTableRun { id: string; label: string; color: string; title?: string }

export function ComparisonHeader({ runs, label = 'Metric' }: { runs: ComparisonTableRun[]; label?: string }) {
  return <thead><tr><th scope="col">{label}</th>{runs.map((run, index) => <th key={run.id} scope="col" style={{ color: run.color }} title={run.title}>{run.label} · {index === 0 ? 'baseline' : 'candidate'}</th>)}
    {runs.length === 2 && <><th scope="col">Δ ({runs[1].label.slice(4)} − {runs[0].label.slice(4)})</th><th scope="col">Δ vs {runs[0].label.slice(4)} (%)</th></>}
  </tr></thead>;
}

export function ComparisonCells({ runs, values, differences }: {
  runs: ComparisonTableRun[]; values: ReactNode[]; differences?: Array<{ absolute: ReactNode; percent: string }>;
}) {
  return <>{runs.map((run, index) => <td key={run.id} style={{ color: run.color }} data-run-column={run.id}>
    {values[index]}
    {differences && runs.length > 2 && index > 0 && <small className="public-run-compare-cell-delta" aria-label={`${run.label} change from ${runs[0].label}`}>Δ {differences[index].absolute} · {differences[index].percent}</small>}
  </td>)}{runs.length === 2 && <><td>{differences?.[1]?.absolute ?? '—'}</td><td>{differences?.[1]?.percent ?? '—'}</td></>}</>;
}
