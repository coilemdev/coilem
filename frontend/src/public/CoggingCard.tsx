import { useId } from 'react';
import { electricalAngleTicks, formatElectricalAngleTick } from './chartAxis';
import { coggingView, type CoggingRow, type CoggingView } from './coggingView';
import type { SolveResult } from './model';
import { StatusSummary } from './OutputStatusBadge';

const PLOT = { width: 360, height: 150, left: 40, right: 10, top: 24, bottom: 26 };

function Row({ row }: { row: CoggingRow }) {
  return (
    <tr title={row.hint}>
      <th scope="row">{row.label}</th>
      <td className="motor-constants-value">{row.value}</td>
      <td className="motor-constants-unit">{row.unit}</td>
    </tr>
  );
}

/** One cogging period, electrical degrees below and mechanical degrees above. */
function CoggingPlot({ waveform, label }: { waveform: NonNullable<CoggingView['waveform']>; label: string }) {
  const { electricalDeg, mechanicalDeg, torqueNm } = waveform;
  const plotWidth = PLOT.width - PLOT.left - PLOT.right;
  const plotHeight = PLOT.height - PLOT.top - PLOT.bottom;
  const low = Math.min(0, ...torqueNm);
  const high = Math.max(0, ...torqueNm);
  const span = high - low || 1;
  const first = electricalDeg[0];
  const last = electricalDeg[electricalDeg.length - 1];
  const x = (angle: number) => PLOT.left + ((angle - first) / (last - first || 1)) * plotWidth;
  const y = (value: number) => PLOT.top + (1 - (value - low) / span) * plotHeight;
  const path = electricalDeg.map((angle, index) => `${index ? 'L' : 'M'}${x(angle).toFixed(1)} ${y(torqueNm[index]).toFixed(1)}`).join(' ');
  const scale = (last - first) / (mechanicalDeg[mechanicalDeg.length - 1] - mechanicalDeg[0] || 1);
  const mechanicalTicks = electricalAngleTicks(mechanicalDeg[0], mechanicalDeg[mechanicalDeg.length - 1], 5);
  return (
    <svg className="cogging-plot" viewBox={`0 0 ${PLOT.width} ${PLOT.height}`} role="img" aria-label={label}>
      <line className="cogging-plot-zero" x1={PLOT.left} x2={PLOT.width - PLOT.right} y1={y(0)} y2={y(0)} />
      {electricalAngleTicks(first, last, 6).map((tick) => (
        <text key={`e${tick}`} x={x(tick)} y={PLOT.height - 12} textAnchor="middle">{formatElectricalAngleTick(tick)}</text>
      ))}
      {mechanicalTicks.map((tick) => (
        <text key={`m${tick}`} x={x(first + (tick - mechanicalDeg[0]) * scale)} y={PLOT.top - 8} textAnchor="middle">{formatElectricalAngleTick(tick)}</text>
      ))}
      <text x={PLOT.left - 6} y={y(high) + 3} textAnchor="end">{high.toPrecision(2)}</text>
      <text x={PLOT.left - 6} y={y(low) + 3} textAnchor="end">{low.toPrecision(2)}</text>
      <text className="cogging-plot-axis" x={PLOT.left + plotWidth / 2} y={PLOT.height - 1} textAnchor="middle">electrical</text>
      <text className="cogging-plot-axis" x={PLOT.left + plotWidth / 2} y={9} textAnchor="middle">mechanical</text>
      <text className="cogging-plot-axis" x={2} y={PLOT.top + plotHeight / 2} textAnchor="start">N·m</text>
      <path d={path} />
    </svg>
  );
}

/**
 * The cogging sweep of a completed run (#185): one cogging period with no
 * current, its main values, the waveform and the harmonic spectrum. Renders
 * nothing for a run without one.
 */
export function CoggingCard({ result, poleCount, variant = 'panel' }: {
  result: Pick<SolveResult, 'summary' | 'cogging_torque_waveform'>;
  poleCount: number;
  variant?: 'panel' | 'report';
}) {
  const headingId = useId();
  const view = coggingView(result, poleCount);
  if (!view) return null;
  return (
    <section className={`motor-constants cogging-card${variant === 'report' ? ' is-report' : ''}`} aria-labelledby={headingId}>
      <div className="results-card-heading">
        <h3 id={headingId}>Cogging torque</h3>
        <StatusSummary statuses={[{ key: 'cogging', label: 'Cogging torque', ...view.status }]} />
      </div>
      <div className="cogging-card-body">
        <table>
          <tbody>{view.rows.map((row) => <Row key={row.key} row={row} />)}</tbody>
          <tbody className="cogging-card-noise">{view.noise.map((row) => <Row key={row.key} row={row} />)}</tbody>
        </table>
        <div className="cogging-card-figures">
          {view.waveform && <CoggingPlot waveform={view.waveform} label={`Cogging torque over one period, ${view.period}`} />}
          {view.harmonics.length > 0 && (
            <ol className="cogging-harmonics" aria-label="Cogging harmonics, cycles per mechanical revolution">
              {view.harmonics.map((harmonic) => (
                <li key={harmonic.order} title={`${harmonic.multiple} × the fundamental cogging order`}>
                  <span className="cogging-harmonic-order">{harmonic.order}/rev</span>
                  <span className="cogging-harmonic-bar"><span style={{ width: `${(harmonic.share * 100).toFixed(1)}%` }} /></span>
                  <span className="cogging-harmonic-value">{harmonic.value} N·m</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
      <p className="motor-constants-note">
        One cogging period, {view.period}, solved with no current. Harmonics are peak amplitudes in cycles per mechanical revolution.
      </p>
    </section>
  );
}
