import { useId } from 'react';
import { solveTimeView, type SolveTimeBreakdown } from './solveTime';

const WORKER_TIME_HELP = 'Adds the measured duration of every occurrence across all workers. Workers run in parallel, so this can exceed the elapsed time above. Average = combined worker time ÷ times run.';
const PREPARE_SETTINGS_HELP = "Measures the time spent checking the design and mesh, preparing solver inputs and process settings, and choosing sweep positions before launching the solver. If a mesh must be generated here, that time is included. Durations are added across every occurrence and worker; parallel work overlaps, so the combined worker time can exceed elapsed time.";

/**
 * Solve time: where the elapsed time went. Three steps that add up to the
 * total, then the stages inside each step. Stage times are summed over the
 * workers that ran in parallel, so they exceed the elapsed time; the same
 * figures are in the report, so two runs can be compared stage by stage.
 */
export function SolveTimeCard({ breakdown }: { breakdown?: SolveTimeBreakdown | null }) {
  const headingId = useId();
  const view = solveTimeView(breakdown);
  return (
    <section className="public-solve-time" aria-labelledby={headingId}>
      <header>
        <h3 id={headingId}>Solve time</h3>
        {view && <span className="public-solve-time-total">{view.elapsed} elapsed</span>}
      </header>
      {!view && <p className="public-solve-time-note">This run did not record a time breakdown.</p>}
      {view && view.segments.length > 0 && (
        <>
          <div className="public-solve-time-bar" role="img" aria-label={view.segments.map(segment => `${segment.label} ${segment.text}`).join(', ')}>
            {view.segments.map(segment => (
              <span key={segment.key} className={`is-${segment.key}`} style={{ flexGrow: Math.max(segment.share, 0.004) }} title={`${segment.label}: ${segment.text} (${segment.shareText})`} />
            ))}
          </div>
          <dl className="public-solve-time-steps">
            {view.segments.map(segment => (
              <div key={segment.key}>
                <dt><span className={`public-solve-time-swatch is-${segment.key}`} aria-hidden="true" />{segment.label}</dt>
                <dd>{segment.text}<small>{segment.shareText}</small></dd>
                <p>{segment.detail}</p>
              </div>
            ))}
          </dl>
        </>
      )}
      {view && view.facts.length > 0 && (
        <dl className="public-solve-time-facts">
          {view.facts.map(fact => <div key={fact.key}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}
        </dl>
      )}
      {view && view.steps.length > 0 && (
        <details className="public-solve-time-details">
          <summary>Stages of each step</summary>
          <p className="public-solve-time-note">
            Times add up every occurrence of a stage across the workers that ran in parallel, so they exceed the elapsed time above.
          </p>
          {view.steps.map(step => (
            <div key={step.key} className="public-solve-time-stage">
              <h4>{step.label}</h4>
              <p className="public-solve-time-note">{step.summary}</p>
              <div className="public-solve-time-scroll">
                <table>
                  <thead><tr><th scope="col">Stage</th><th scope="col">Times run</th><th scope="col" title={WORKER_TIME_HELP}>Combined worker time</th><th scope="col">Each, average</th><th scope="col">Slowest</th></tr></thead>
                  <tbody>{step.rows.map(row => (
                    <tr key={row.key} className={row.indent ? 'is-part' : undefined}>
                      <th scope="row">
                        <span className="public-solve-time-weight" style={{ width: `${Math.round(row.weight * 100)}%` }} aria-hidden="true" />
                        <span
                          title={row.label === "Prepare the solver's settings" ? PREPARE_SETTINGS_HELP : undefined}
                          tabIndex={row.label === "Prepare the solver's settings" ? 0 : undefined}
                          aria-label={row.label === "Prepare the solver's settings" ? `${row.label}. ${PREPARE_SETTINGS_HELP}` : undefined}
                        >{row.label}{row.label === "Prepare the solver's settings" && <span aria-hidden="true"> ⓘ</span>}</span>
                      </th>
                      <td>{row.count}</td><td>{row.total}</td><td>{row.mean}</td><td>{row.max}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
          ))}
        </details>
      )}
    </section>
  );
}
