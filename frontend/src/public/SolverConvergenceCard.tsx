import { useId, useState } from 'react';
import { electricalAngleTicks, formatElectricalAngleTick } from './chartAxis';
import { ConvergenceHelp } from './ConvergenceHelp';
import {
  SWEEP_LABELS,
  convergenceAngleTable,
  convergenceChart,
  convergenceOverview,
  type ConvergenceChart,
  type PositionStatus,
} from './convergenceOverview';
import type { ConvergenceRow, SolverConvergenceReport } from './model';

const SWEEP_STYLE = {
  no_load: { color: '#60a5fa', dash: undefined },
  loaded: { color: '#f59e0b', dash: '6 4' },
} as const;

function Rows({ rows }: { rows: ConvergenceRow[] }) {
  return <dl className="public-convergence-rows">{rows.map(row => (
    <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>
  ))}</dl>;
}

function StatusMark({ status }: { status: PositionStatus }) {
  if (status.tone === 'muted') return null;
  return <span className={`public-convergence-mark ${status.tone === 'ok' ? 'is-ok' : 'is-warning'}`} aria-hidden="true">{status.tone === 'ok' ? '✓' : '!'}</span>;
}

/** Share of the iteration limit each position used, with the 80% review line and the limit. */
function IterationChart({ chart }: { chart: ConvergenceChart }) {
  const width = 1000;
  const height = 210;
  const margin = { top: 12, right: 100, bottom: 46, left: 52 };
  const xs = chart.series.flatMap(item => item.points.map(point => point.x));
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const span = xMax - xMin || 1;
  const x = (value: number) => margin.left + (xMax === xMin ? 0.5 : (value - xMin) / span) * (width - margin.left - margin.right);
  const y = (fraction: number) => margin.top + (1 - Math.min(fraction, 1)) * (height - margin.top - margin.bottom);
  const xTicks = chart.axis === 'angle'
    ? electricalAngleTicks(xMin, xMax, 6)
    : [...new Set([xMin, Math.round((xMin + xMax) / 2), xMax])];
  const most = Math.max(...chart.series.flatMap(item => item.points.map(point => point.fraction)));
  const summary = `Share of the iteration limit used at each rotor position, at most ${Math.round(most * 100)}%. Positions at 80% or more need review.`;
  return (
    <figure className="public-convergence-chart">
      <figcaption>
        <span>Iteration limit used at each position</span>
        <span className="public-convergence-chart-legend">
          {chart.series.map(item => (
            <span key={item.sweep}>
              <svg width="18" height="6" aria-hidden="true"><line x1="0" x2="18" y1="3" y2="3" stroke={SWEEP_STYLE[item.sweep].color} strokeWidth="2" strokeDasharray={SWEEP_STYLE[item.sweep].dash} /></svg>
              {SWEEP_LABELS[item.sweep]}
            </span>
          ))}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={summary}>
        {[0, 0.5, 1].map(tick => (
          <g key={tick}>
            <line x1={margin.left} x2={width - margin.right} y1={y(tick)} y2={y(tick)} className="chart-grid" />
            <text x={margin.left - 10} y={y(tick) + 4} textAnchor="end" className="chart-label">{Math.round(tick * 100)}%</text>
          </g>
        ))}
        <line x1={margin.left} x2={width - margin.right} y1={y(1)} y2={y(1)} className="public-convergence-limit" />
        <text x={width - margin.right + 8} y={y(1) + 4} className="chart-label">limit</text>
        <line x1={margin.left} x2={width - margin.right} y1={y(0.8)} y2={y(0.8)} className="public-convergence-review-line" />
        <text x={width - margin.right + 8} y={y(0.8) + 4} className="chart-label public-convergence-review-label">review 80%</text>
        {chart.series.map(item => (
          <g key={item.sweep}>
            {item.points.length > 1 && (
              <polyline
                points={item.points.map(point => `${x(point.x).toFixed(1)},${y(point.fraction).toFixed(1)}`).join(' ')}
                fill="none" stroke={SWEEP_STYLE[item.sweep].color} strokeWidth="2" strokeDasharray={SWEEP_STYLE[item.sweep].dash}
                strokeLinejoin="round" strokeLinecap="round"
              />
            )}
            {item.points.map((point, index) => (
              <circle key={`${point.x}-${index}`} cx={x(point.x)} cy={y(point.fraction)} r={point.flagged ? 4.5 : item.points.length > 1 ? 1.6 : 3}
                className={point.flagged ? 'public-convergence-flag' : undefined} fill={point.flagged ? undefined : SWEEP_STYLE[item.sweep].color}>
                <title>{point.title}</title>
              </circle>
            ))}
          </g>
        ))}
        {xTicks.map(tick => (
          <text key={tick} x={x(tick)} y={height - margin.bottom + 20} textAnchor="middle" className="chart-label">
            {chart.axis === 'angle' ? formatElectricalAngleTick(tick) : tick}
          </text>
        ))}
        <text x={width - margin.right} y={height - 4} textAnchor="end" className="chart-label">{chart.axis === 'angle' ? 'electrical angle' : 'position'}</text>
      </svg>
    </figure>
  );
}

function PositionTable({ report }: { report: SolverConvergenceReport }) {
  const [showAll, setShowAll] = useState(false);
  const table = convergenceAngleTable(report);
  if (!table.rows.length) return null;
  const flagged = table.rows.filter(row => row.flagged);
  const rows = showAll ? table.rows : flagged;
  const noun = table.axis === 'angle' ? 'angle' : 'position';
  return (
    <div className="public-convergence-positions">
      <div className="public-convergence-positions-head">
        <p className={flagged.length ? 'is-warning' : 'is-ok'}>
          <span className="public-convergence-mark" aria-hidden="true">{flagged.length ? '!' : '✓'}</span>
          <span>{flagged.length
            ? `${flagged.length} ${noun}${flagged.length === 1 ? '' : 's'} need${flagged.length === 1 ? 's' : ''} a look`
            : 'No positions need a look'}</span>
        </p>
        {table.rows.length > flagged.length && (
          <button type="button" className="public-convergence-toggle" aria-expanded={showAll} onClick={() => setShowAll(value => !value)}>
            {showAll ? (flagged.length ? `Show only the ${flagged.length} to check` : 'Hide the list') : `Show all ${table.rows.length} ${noun}s`}
          </button>
        )}
      </div>
      {rows.length > 0 && (
        <div className="public-convergence-table-scroll">
          <table aria-label="Iterations at each rotor position">
            <thead><tr>
              <th scope="col">{table.axis === 'angle' ? 'Electrical angle' : 'Position'}</th>
              {table.sweeps.map(sweep => <th scope="col" key={sweep}>{SWEEP_LABELS[sweep]} iterations</th>)}
            </tr></thead>
            <tbody>{rows.map(row => (
              <tr key={row.key}>
                <th scope="row">{row.label}</th>
                {table.sweeps.map(sweep => {
                  const value = row.cells[sweep];
                  return <td key={sweep} title={value?.title} className={value?.status.tone === 'review' ? 'is-warning' : undefined}>
                    {value ? <><StatusMark status={value.status} />{value.text}</> : '—'}
                  </td>;
                })}
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/**
 * Solver convergence: a verdict and four facts, the share of the iteration
 * limit each position used, and the positions to check. The info button beside
 * the title sketches how the solver converges.
 * The backend report's own rows (shared with the PDF) sit under technical
 * details; every position's record is in the CSV.
 */
export function SolverConvergenceCard({ report }: { report?: SolverConvergenceReport | null }) {
  const headingId = useId();
  const overview = convergenceOverview(report);
  const chart = convergenceChart(report);
  const recorded = report && report.status !== 'not_recorded' ? report : null;
  return (
    <section className="public-solver-convergence" aria-labelledby={headingId}>
      <header>
        <div className="public-convergence-title">
          <h3 id={headingId}>Solver convergence</h3>
          {recorded && <ConvergenceHelp stoppingRule={overview.stoppingRule} allowedError={overview.allowedError} iterationLimit={overview.iterationLimit} />}
        </div>
        <span className={`public-convergence-status${overview.tone === 'review' ? ' is-warning' : overview.tone === 'ok' ? ' is-ok' : ''}`}>
          {overview.label}
        </span>
      </header>
      <p className="public-convergence-verdict">{overview.verdict}</p>
      {overview.facts.length > 0 && (
        <dl className="public-convergence-facts">{overview.facts.map(fact => (
          <div key={fact.key}><dt>{fact.label}</dt><dd>{fact.value}</dd>{fact.hint && <p>{fact.hint}</p>}</div>
        ))}</dl>
      )}
      {recorded && chart.series.length > 0 && (
        <>
          <IterationChart chart={chart} />
          <ul className="public-convergence-key" aria-label="Position status">
            <li><span className="public-convergence-mark is-ok" aria-hidden="true">✓</span><strong>Converged</strong> under the allowed error</li>
            <li><span className="public-convergence-mark is-warning" aria-hidden="true">!</span><strong>Slow</strong> used 80% or more of the limit</li>
            <li><span className="public-convergence-mark is-warning" aria-hidden="true">!</span><strong>Stopped early</strong> still above the allowed error</li>
            <li className="public-convergence-key-note">Not checked here: mesh accuracy</li>
          </ul>
        </>
      )}
      {recorded && <PositionTable report={recorded} />}
      {recorded && (
        <details className="public-convergence-details">
          <summary>Technical details: solver settings and limits</summary>
          <Rows rows={recorded.summary} />
          <div className="public-convergence-methods">{recorded.methods.map(method => (
            <div key={method.method}><h4>{method.label}</h4><Rows rows={[...method.summary, ...method.details]} /></div>
          ))}</div>
          {recorded.warnings.length > 0 && <ul className="public-convergence-warnings">{recorded.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}
          <p className="public-convergence-note">Every position's full record is in the CSV export.</p>
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
      <p className="public-diagnostics-intro">How far to trust the results above.</p>
      <SolverConvergenceCard report={report} />
    </section>
  );
}
