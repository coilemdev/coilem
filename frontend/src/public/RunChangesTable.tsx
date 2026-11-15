import { INPUT_GROUPS, multipleInputChanges, type ComparisonInputs } from './runInputChanges';

export function RunInputChanges({ runs }: {
  /** Baseline first; letters keep their selection identity. */
  runs: Array<{ id: string; label: string; color: string; inputs?: ComparisonInputs | null; details: Record<string, string> }>;
}) {
  const changes = multipleInputChanges(runs.map(run => run.inputs));
  const missing = changes.filter(change => change.missing).length;
  const baseline = runs[0];
  const columnCount = runs.length + 1;
  return <section className="public-run-input-changes" aria-label="What changed between runs">
    <header><h3>What changed?</h3><span>{changes.filter(change => change.knownChanged).length} changed inputs{missing ? ` · ${missing} not recorded in one or more runs` : ''}</span></header>
    <p>{runs.length === 2 ? `${baseline.label} → ${runs[1].label}` : `${baseline.label} pinned baseline · ${runs.length} runs`} · Inputs recorded with these runs, independent of the open design.</p>
    {runs.some(run => !run.inputs?.config) && <p className="public-run-input-notice">Input snapshots were not recorded for one or {runs.length === 2 ? 'both' : 'more'} runs. Missing values are not filled from today’s defaults.</p>}
    {runs.some(run => !run.inputs?.run_setup) && <p className="public-run-input-notice">Saved setup identity was not recorded for one or {runs.length === 2 ? 'both' : 'more'} runs.</p>}
    {!changes.length && <p>{runs.every(run => run.inputs?.config) ? 'No differences in the recorded inputs.' : 'No recorded inputs available to compare.'}</p>}
    <div className="public-run-input-table-scroll" role="region" aria-label="Recorded input comparison table" tabIndex={0}><table>
      <thead><tr><th scope="col">Input</th>{runs.map((run, index) => <th key={run.id} scope="col" style={{ color: run.color }}>{run.label} · {index === 0 ? 'baseline' : 'candidate'}</th>)}</tr></thead>
      {INPUT_GROUPS.map(group => {
        const rows = changes.filter(change => change.group === group);
        return rows.length ? <tbody key={group}>
          <tr className="public-run-input-group"><th scope="rowgroup" colSpan={columnCount}>{group}</th></tr>
          {rows.map(change => <tr key={change.path} data-input-path={change.path}>
            <th scope="row">{change.label}</th>{change.values.map((value, index) => <td key={runs[index].id} data-changed={index > 0 && value !== change.values[0] ? 'true' : undefined}>{value}</td>)}
          </tr>)}
        </tbody> : null;
      })}
      <tbody aria-label="Recorded run details">
        <tr className="public-run-input-group"><th scope="rowgroup" colSpan={columnCount}>Run details</th></tr>
        {Object.keys(baseline.details).map(label => <tr key={label}>
          <th scope="row">{label}</th>{runs.map(run => <td key={run.id}>{run.details[label] ?? 'Not recorded'}</td>)}
        </tr>)}
      </tbody>
    </table></div>
  </section>;
}
