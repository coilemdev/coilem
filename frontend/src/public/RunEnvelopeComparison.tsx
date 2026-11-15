import type { Dispatch, SetStateAction } from 'react';
import { ComparisonCells, ComparisonHeader, type ComparisonTableRun } from './ComparisonTable';
import { comparisonPercentDelta, comparisonSignificantDelta } from './comparisonNumbers';
import { comparisonEnvelope, ENVELOPE_METRICS, envelopePoint } from './envelopeComparison';
import { formatSignificant } from './numberFormat';
import { axisTop, niceTicks } from './performanceView';
import { StatusDot } from './OutputStatusBadge';
import { InfoTip } from './Popover';
import type { ComparisonResult } from './runComparison';

interface EnvelopeRun extends ComparisonTableRun { result: ComparisonResult; dashArray?: string }
export interface EnvelopeComparisonState { limit: 'peak' | 'continuous'; quantity: 'torque' | 'power'; hidden: string[]; speed: number }

export function RunEnvelopeComparison({ runs, state, onChange }: { runs: EnvelopeRun[]; state: EnvelopeComparisonState; onChange: Dispatch<SetStateAction<EnvelopeComparisonState>> }) {
  const { limit, quantity, hidden, speed } = state;
  const setLimit = (limit: EnvelopeComparisonState['limit']) => onChange(previous => ({ ...previous, limit }));
  const setQuantity = (quantity: EnvelopeComparisonState['quantity']) => onChange(previous => ({ ...previous, quantity }));
  const setSpeed = (speed: number) => onChange(previous => ({ ...previous, speed }));
  const data = runs.map(run => comparisonEnvelope(run.result));
  const curves = data.map(item => item.curves.find(curve => curve.limit === limit));
  const series = runs.flatMap((run, index) => curves[index] ? [{ ...run, curve: curves[index]! }] : []);
  const shown = series.filter(run => !hidden.includes(run.id));
  const points = curves.map(curve => envelopePoint(curve, speed));
  const values = points.map(point => point ? quantity === 'torque' ? point.torque : point.power / 1000 : null);
  const unit = quantity === 'torque' ? 'N·m' : 'kW';
  const curveValues = (curve: NonNullable<typeof curves[number]>) => quantity === 'torque' ? curve.torque_Nm : curve.power_W.map(value => value / 1000);
  const maxX = axisTop(Math.max(1, ...series.flatMap(run => run.curve.speed_rpm)), 5);
  const maxY = axisTop(Math.max(1e-6, ...series.flatMap(run => curveValues(run.curve))) * 1.05, 5);
  const x = (value: number) => 60 + value / maxX * 670;
  const y = (value: number) => 24 + (1 - value / maxY) * 220;
  const tableClass = `public-run-compare-metrics${runs.length > 2 ? ' is-multi-run' : ''}`;
  const differences = (numbers: Array<number | null>, rowUnit: string) => numbers.map(value => ({
    absolute: numbers[0] === null || value === null ? '—' : <>{comparisonSignificantDelta(numbers[0], value)} <small>{rowUnit}</small></>,
    percent: comparisonPercentDelta(numbers[0], value),
  }));
  const metricValues = ENVELOPE_METRICS.map(metric => data.map((item, index) => {
    const value = item.envelope && item.status?.status !== 'unavailable' ? metric.value(item.envelope, curves[index]) : null;
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  }));
  return <section className="public-envelope-comparison" aria-label="Torque–speed comparison">
    <div className="public-compare-view-heading"><h3>Torque–speed envelopes</h3><InfoTip label="Torque–speed comparison help">Stored drive envelopes, using each run’s recorded bus, current limits and map settings. Readouts interpolate between recorded speeds and never extrapolate. Differences describe both motor and drive changes.</InfoTip></div>
    <div className="public-compare-view-controls">
      <div className="performance-toggle" role="group" aria-label="Envelope limit">{(['peak', 'continuous'] as const).map(value => <button key={value} type="button" aria-pressed={limit === value} onClick={() => setLimit(value)}>{value === 'peak' ? 'Peak' : 'Continuous'}</button>)}</div>
      <div className="performance-toggle" role="group" aria-label="Envelope quantity">{(['torque', 'power'] as const).map(value => <button key={value} type="button" aria-pressed={quantity === value} onClick={() => setQuantity(value)}>{value === 'torque' ? 'Torque' : 'Power'}</button>)}</div>
    </div>
    {data.map((item, index) => (item.reason || !curves[index]) && <p key={runs[index].id} className="public-run-compare-timing-note" role="note">{runs[index].label}: {item.reason || `A ${limit} envelope was not recorded.`}</p>)}
    {series.length > 0 && <figure className="chart-shell public-envelope-chart">
      <div className="public-waveform-legend" aria-label="Torque–speed comparison series">{series.map(run => <button key={run.id} type="button" aria-label={`${hidden.includes(run.id) ? 'Show' : 'Hide'} ${run.label} envelope`} aria-pressed={!hidden.includes(run.id)} onClick={() => onChange(previous => ({ ...previous, hidden: previous.hidden.includes(run.id) ? previous.hidden.filter(id => id !== run.id) : [...previous.hidden, run.id] }))}>
        <svg width="24" height="8" aria-hidden="true"><path d="M 1 4 H 23" stroke={run.color} strokeWidth="3" strokeDasharray={run.dashArray} /></svg>{run.label}
      </button>)}</div>
      {!shown.length ? <p className="public-waveform-empty" role="status">All envelopes are hidden. Use the legend to show a run.</p> : <svg viewBox="0 0 760 280" role="img" aria-label={`${quantity === 'torque' ? 'Torque' : 'Power'}–speed comparison`} onPointerMove={event => {
        const bounds = event.currentTarget.getBoundingClientRect();
        const coordinate = ((event.clientX - bounds.left) / bounds.width * 760 - 60) / 670 * maxX;
        if (coordinate >= 0 && coordinate <= maxX) setSpeed(Math.round(coordinate));
      }}>
        {niceTicks(maxY, 5).filter(tick => tick <= maxY).map(tick => <g key={`y-${tick}`}><line x1="60" x2="730" y1={y(tick)} y2={y(tick)} className="chart-grid" /><text x="50" y={y(tick) + 4} textAnchor="end" className="chart-label">{formatSignificant(tick)}</text></g>)}
        {niceTicks(maxX, 5).filter(tick => tick <= maxX).map(tick => <g key={`x-${tick}`}><line x1={x(tick)} x2={x(tick)} y1="24" y2="244" className="chart-grid" /><text x={x(tick)} y="261" textAnchor="middle" className="chart-label">{tick.toLocaleString()}</text></g>)}
        <text x="60" y="13" className="chart-label">{unit}</text><text x="730" y="277" textAnchor="end" className="chart-label">speed, rpm</text>
        {shown.map(run => <path key={run.id} d={run.curve.speed_rpm.map((rpm, index) => `${index ? 'L' : 'M'} ${x(rpm)} ${y(curveValues(run.curve)[index])}`).join(' ')} fill="none" stroke={run.color} strokeWidth="2" strokeDasharray={run.dashArray} />)}
        {speed <= maxX && <line x1={x(speed)} x2={x(speed)} y1="24" y2="244" className="performance-crosshair" />}
      </svg>}
      <label className="public-envelope-readout-speed">Read at speed <input type="number" aria-label="Envelope readout speed" min="0" max={maxX} step="1" value={speed} onChange={event => { const next = event.target.valueAsNumber; if (Number.isFinite(next) && next >= 0 && next <= maxX) setSpeed(next); }} /> rpm</label>
    </figure>}
    <div className={tableClass} role="region" aria-label="Envelope metrics and drive limits" tabIndex={0}><table>
      <caption>{limit === 'peak' ? 'Peak' : 'Continuous'} envelope &amp; drive limits</caption><ComparisonHeader runs={runs} />
      <tbody>
        {series.length > 0 && <tr><th scope="row">{quantity === 'torque' ? 'Torque' : 'Power'} at {speed.toLocaleString()} rpm <InfoTip label="Envelope readout help">Interpolated within each stored curve. A dash means this speed is outside that run’s recorded curve, or the requested curve is unavailable.</InfoTip></th><ComparisonCells runs={runs} values={values.map(value => value === null ? '—' : <>{formatSignificant(value)} <small>{unit}</small></>)} differences={differences(values, unit)} /></tr>}
        <tr><th scope="row">Envelope status</th><ComparisonCells runs={runs} values={data.map((item, index) => item.status ? <>{item.status.status === 'qualified' ? 'Qualified' : item.status.status === 'experimental' ? 'Experimental' : 'Unavailable'} <StatusDot status={item.status.status} label={`${runs[index].label} envelope`} reason={item.status.reason || 'No status reason was recorded.'} /></> : item.missing)} /></tr>
        {ENVELOPE_METRICS.map((metric, index) => <tr key={metric.label}><th scope="row">{metric.label}</th><ComparisonCells runs={runs} values={metricValues[index].map((value, runIndex) => value === null ? !data[runIndex].envelope ? data[runIndex].missing : metric.label === 'Continuous current limit' ? 'Not set' : 'Unavailable' : <>{formatSignificant(value)} <small>{metric.unit}</small></>)} differences={differences(metricValues[index], metric.unit)} /></tr>)}
        <tr><th scope="row">Map grid / control</th><ComparisonCells runs={runs} values={data.map(item => item.settings ? `${item.settings.preset === 'standard' ? 'Standard' : item.settings.preset === 'preview' ? 'Preview' : 'Not recorded'} · ${item.settings.control === 'mtpa' ? 'MTPA' : item.settings.control === 'least_loss' ? 'Least loss' : 'Not recorded'}` : 'Not recorded')} /></tr>
      </tbody>
    </table></div>
  </section>;
}
