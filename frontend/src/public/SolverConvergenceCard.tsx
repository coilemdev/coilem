import { useId } from 'react';
import { convergenceOverview } from './convergenceOverview';
import type { ConvergenceRow, SolverConvergenceReport } from './model';

function Rows({ rows }: { rows: ConvergenceRow[] }) {
  return <dl className="public-convergence-rows">{rows.map(row => (
    <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>
  ))}</dl>;
}

function number(value: number | null): string {
  return value !== null && Number.isFinite(value) ? Number(value.toPrecision(4)).toString() : 'Not recorded';
}

/**
 * Solver convergence: a plain verdict and four facts first, a short guide to
 * reading them, then the backend report the PDF and CSV carry, unchanged, as
 * technical details.
 */
export function SolverConvergenceCard({ report }: { report?: SolverConvergenceReport | null }) {
  const headingId = useId();
  const overview = convergenceOverview(report);
  return (
    <section className="public-solver-convergence" aria-labelledby={headingId}>
      <header>
        <h3 id={headingId}>Solver convergence</h3>
        <span className={`public-convergence-status${overview.tone === 'review' ? ' is-warning' : overview.tone === 'ok' ? ' is-ok' : ''}`}>
          {overview.label}
        </span>
      </header>
      <p className="public-convergence-verdict">{overview.verdict}</p>
      {overview.facts.length > 0 && (
        <dl className="public-convergence-facts">{overview.facts.map(fact => (
          <div key={fact.key}><dt>{fact.label}</dt><dd>{fact.value}</dd><p>{fact.hint}</p></div>
        ))}</dl>
      )}
      <details className="public-convergence-guide">
        <summary>What this checks and what to look for</summary>
        <p>
          Steel saturates, so how easily it carries flux depends on the field in it. At each rotor position the
          solver repeats a loop: solve the field, update every steel element from its new flux density, and solve
          again, until the steel stops changing. This card records how close each position got when its loop stopped.
        </p>
        <ul>
          <li><strong>Converged:</strong> every position finished under the allowed error. Nothing to do.</li>
          <li><strong>Worst remaining error above 100%:</strong> a position stopped before reaching the allowed error, so its torque and Back EMF are less certain. Look for a spike at that angle in the waveforms.</li>
          <li><strong>Iterations at 80% or more of the limit:</strong> those positions converged slowly. They passed, but they were close to stopping early.</li>
          <li><strong>Small results,</strong> such as cogging torque, are the most sensitive to error left in the field.</li>
          <li><strong>Convergence is not mesh accuracy.</strong> It shows the equations were solved on this mesh, not that the mesh is fine enough; the accuracy plan sets that.</li>
        </ul>
      </details>
      {report && report.status !== 'not_recorded' && (
        <details className="public-convergence-details">
          <summary>Technical details: limits and every position</summary>
          <Rows rows={report.summary} />
          <div className="public-convergence-methods">{report.methods.map(method => (
            <div key={method.method}><h4>{method.label}</h4><Rows rows={method.summary} /></div>
          ))}</div>
          {report.warnings.length > 0 && <ul className="public-convergence-warnings">{report.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}
          {report.methods.map(method => <div key={method.method}><h4>{method.label} thresholds</h4><Rows rows={method.details} /></div>)}
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
      )}
    </section>
  );
}

/** The end of Results: checks on how the numbers were computed. */
export function ResultDiagnostics({ report }: { report?: SolverConvergenceReport | null }) {
  const headingId = useId();
  return (
    <section className="public-diagnostics" aria-labelledby={headingId}>
      <h2 id={headingId}>Diagnostics</h2>
      <p className="public-diagnostics-intro">Checks on how the results above were computed. They don't change the results; they show how far to trust them.</p>
      <SolverConvergenceCard report={report} />
    </section>
  );
}
