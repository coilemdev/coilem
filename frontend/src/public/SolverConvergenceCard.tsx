import { useId } from 'react';
import type { ConvergenceRow, SolverConvergenceReport } from './model';

function Rows({ rows }: { rows: ConvergenceRow[] }) {
  return <dl className="public-convergence-rows">{rows.map(row => (
    <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>
  ))}</dl>;
}

function number(value: number | null): string {
  return value !== null && Number.isFinite(value) ? Number(value.toPrecision(4)).toString() : 'Not recorded';
}

/** Display the same backend report used by the stored PDF and CSV. */
export function SolverConvergenceCard({ report }: { report?: SolverConvergenceReport | null }) {
  const headingId = useId();
  const review = report?.status === 'review' || report?.status === 'partial';
  return (
    <section className="public-solver-convergence" aria-labelledby={headingId}>
      <header>
        <h2 id={headingId}>Solver convergence</h2>
        <span className={`public-convergence-status${review ? ' is-warning' : report?.status === 'ok' ? ' is-ok' : ''}`}>
          {report?.status_label ?? 'Not recorded'}
        </span>
      </header>
      {!report || report.status === 'not_recorded'
        ? <p className="public-convergence-note">Convergence evidence was not recorded for this run. Missing residuals and limits cannot be recovered from iteration counts or current settings.</p>
        : null}
      {report && <>
        <Rows rows={report.summary} />
        <div className="public-convergence-methods">{report.methods.map(method => (
          <div key={method.method}><h3>{method.label}</h3><Rows rows={method.summary} /></div>
        ))}</div>
        {report.warnings.length > 0 && <ul className="public-convergence-warnings">{report.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}
        <details className="public-convergence-details">
          <summary>Thresholds and per-position records</summary>
          {report.methods.map(method => <div key={method.method}><h3>{method.label} thresholds</h3><Rows rows={method.details} /></div>)}
          {report.notes.map(note => <p className="public-convergence-note" key={note}>{note}</p>)}
          {report.positions.length > 0 && <div className="public-convergence-table-scroll">
            <table aria-label="Per-position solver convergence">
              <thead><tr><th scope="col">Sweep / position</th><th scope="col">Method</th><th scope="col">Iterations / limit</th><th scope="col">Final residual</th><th scope="col">Stopping ratio</th><th scope="col">Field</th></tr></thead>
              <tbody>{report.positions.map(position => {
                const record = position.record;
                const residual = record?.method === 'picard' ? record.raw_max_residual : record?.scaled_residual ?? null;
                return <tr key={`${position.sweep}-${position.index}`} className={position.review ? 'is-warning' : ''}>
                  <th scope="row">{position.sweep === 'loaded' ? 'Loaded' : 'No-load'} {position.index + 1}{position.electrical_angle_deg !== null ? ` · ${number(position.electrical_angle_deg)}°` : ''}</th>
                  <td>{record?.method ?? 'Not recorded'}</td>
                  <td title={record ? `Per-stage limit ${record.stage_iteration_cap}; stage iterations ${record.stage_iterations.join(', ')}` : undefined}>{record ? `${record.iterations} / ${record.max_iterations}` : 'Not recorded'}</td>
                  <td title={record?.residual_definition}>{record?.method === 'linear' ? 'Not applicable' : number(residual)}</td>
                  <td title={record?.stopping_test}>{record?.method === 'linear' ? 'Not applicable' : number(position.stopping_ratio)}</td>
                  <td>{!record ? 'Not recorded' : record.solution_reused ? 'Reused' : 'Solved'}{position.review ? ' · Review' : ''}</td>
                </tr>;
              })}</tbody>
            </table>
          </div>}
        </details>
      </>}
    </section>
  );
}
