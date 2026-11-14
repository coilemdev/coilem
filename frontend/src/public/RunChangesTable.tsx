import { INPUT_GROUPS, inputChanges, type ComparisonInputs } from './runInputChanges';

export function RunInputChanges({ before, after }: { before?: ComparisonInputs | null; after?: ComparisonInputs | null }) {
  const changes = inputChanges(before, after);
  const missing = changes.filter(change => change.missing).length;
  return <section className="public-run-input-changes" aria-label="What changed between runs">
    <header><h3>What changed?</h3><span>{changes.length - missing} changed inputs{missing ? ` · ${missing} not recorded in one run` : ''}</span></header>
    <p>Run A → Run B · Inputs recorded with these runs, independent of the open design.</p>
    {(!before?.config || !after?.config) && <p className="public-run-input-notice">Input snapshots were not recorded for one or both runs. Missing values are not filled from today’s defaults.</p>}
    {(!before?.run_setup || !after?.run_setup) && <p className="public-run-input-notice">Saved setup identity was not recorded for one or both runs.</p>}
    {!changes.length && <p>{before?.config && after?.config ? 'No differences in the recorded inputs.' : 'No recorded inputs available to compare.'}</p>}
    {changes.length > 0 && <div className="public-run-input-table-scroll"><table>
      <thead><tr><th scope="col">Input</th><th scope="col">Run A · baseline</th><th scope="col">Run B · candidate</th></tr></thead>
      {INPUT_GROUPS.map(group => {
        const rows = changes.filter(change => change.group === group);
        return rows.length ? <tbody key={group}>
          <tr className="public-run-input-group"><th scope="rowgroup" colSpan={3}>{group}</th></tr>
          {rows.map(change => <tr key={change.path} data-input-path={change.path}>
            <th scope="row">{change.label}</th><td>{change.before}</td><td>{change.after}</td>
          </tr>)}
        </tbody> : null;
      })}
    </table></div>}
  </section>;
}
