import { useState } from 'react';
import { downloadThermalAnalysis } from './api';
import { StatusBadge } from './OutputStatusBadge';
import type { MotorConfig, PublicFieldLinePlot, SolveResult } from './model';
import type { TorqueSpeedEnvelope } from './performance';
import { isHeldSpeed, readRatingRow, thermalCurvePath, thermalSetupSummary, unavailableEstimateReason, type ThermalAnalysis, type ThermalEstimate, type ThermalNode, type ThermalRating } from './thermal';
import { ThermalCrossSection } from './ThermalMotorView';
import { thermalDriveSettings, useThermalRun } from './ThermalRun';
import { useThermalSetup } from './ThermalSetup';
import { unitSymbol } from './thermalUnits';
import { useTemperatureUnit } from './useTemperatureUnit';
import { differenceNumber, differenceText, nodeTemperature, temperatureNumber, temperatureText, thermalColour, thermalMargin, thermalNodeLabel, thermalNumber, thermalRange, thermalTotalHeat, tightestWinding } from './thermalVisual';

export { useThermalRecord } from './ThermalRun';

const shown = (value: number | null | undefined) => value == null ? 'Unavailable' : value.toLocaleString(undefined, { maximumSignificantDigits: 4 });
const errorText = (error: unknown) => error && typeof error === 'object' && 'message' in error ? String(error.message) : 'Thermal calculation failed.';

// Hottest-running parts first, the air nodes last.
const PART_ORDER = ['end_winding', 'winding', 'teeth', 'yoke', 'housing', 'mount', 'magnets', 'rotor', 'bearings', 'airgap', 'end_air'];

const isOver = (node: ThermalNode | undefined) => nodeTemperature(node) !== null && node?.margin_K != null && node.margin_K < 0;

function Kpi({ label, value, unit, note, warn = false }: { label: string; value: string; unit?: string; note: string; warn?: boolean }) {
  return <div className={`thermal-kpi${warn ? ' is-over-limit' : ''}`}>
    <span>{label}</span><strong>{value}{unit && <small> {unit}</small>}</strong><em>{note}</em>
  </div>;
}

/**
 * Key numbers for the thermal estimate, shown among the other result cards.
 * `stale`: the estimate was computed with other thermal inputs than the setup now holds
 * (useThermalRun's `stale`, as the Solve monitor and the Thermal tab use it).
 */
export function ThermalSummaryCard({ analysis, stale = false }: { analysis: ThermalAnalysis | null; stale?: boolean }) {
  const [unit] = useTemperatureUnit();
  if (analysis?.result.kind !== 'steady_state_thermal') return null;
  const result = analysis.result;
  const hottest = result.hottest_node ? nodeTemperature(result.nodes[result.hottest_node]) : null;
  if (hottest === null) {
    // Say why there are no numbers; an empty space would read as "thermal was never run".
    const reason = unavailableEstimateReason(analysis) ?? result.status_reason;
    return <section className="motor-constants is-report thermal-summary-card" aria-label="Thermal estimate summary">
      <div className="results-card-heading"><h3>Thermal</h3><StatusBadge status="unavailable" title={reason} /></div>
      {stale
        ? <p className="motor-constants-note thermal-summary-previous" role="status">No temperatures could be estimated with the previous thermal inputs. Run it again under Solve → Thermal.</p>
        : <p className="motor-constants-note">No temperatures could be estimated. {reason}</p>}
    </section>;
  }
  const winding = tightestWinding(result);
  const magnets = nodeTemperature(result.nodes.magnets);
  return <section className="motor-constants is-report thermal-summary-card" aria-label="Thermal estimate summary">
    <div className="results-card-heading"><h3>Thermal</h3><StatusBadge status={result.status} title={result.status_reason} /></div>
    {/* Kept for reference once the inputs change, but not shown as the current temperatures. */}
    {stale && <p className="motor-constants-note thermal-summary-previous" role="status">From the previous thermal inputs. Run it again under Solve → Thermal to update it.</p>}
    <table className={stale ? 'is-previous' : undefined} aria-label={stale ? 'Previous estimate, from the previous inputs' : undefined}><tbody>
      <tr><th scope="row"><span className="motor-constants-name">Hottest part · {thermalNodeLabel(result.hottest_node!)}</span></th><td className="motor-constants-value">{temperatureNumber(hottest, unit)}</td><td className="motor-constants-unit">{unitSymbol(unit)}</td></tr>
      {winding && <tr><th scope="row"><span className="motor-constants-name">Winding against its {temperatureText(winding.limit_C!, unit)} limit</span></th>
        <td className="motor-constants-value">{differenceNumber(Math.abs(winding.margin_K!), unit)}</td>
        <td className="motor-constants-unit">{unitSymbol(unit)}<span className={`motor-constants-status is-${winding.margin_K! < 0 ? 'check' : 'ok'}`}>{winding.margin_K! < 0 ? 'Over' : 'Spare'}</span></td></tr>}
      {magnets !== null && <tr><th scope="row"><span className="motor-constants-name">Magnets</span></th><td className="motor-constants-value">{temperatureNumber(magnets, unit)}</td><td className="motor-constants-unit">{unitSymbol(unit)}</td></tr>}
    </tbody></table>
  </section>;
}

function PointResult({ result, plot }: { result: ThermalEstimate; plot?: PublicFieldLinePlot | null }) {
  const [unit] = useTemperatureUnit();
  const symbol = unitSymbol(unit);
  const names = PART_ORDER.filter((name) => result.nodes[name]);
  const [selection, setSelection] = useState<string | null>(result.hottest_node);
  const selected = selection && result.nodes[selection] ? selection : result.hottest_node ?? names[0] ?? null;
  const range = thermalRange(result.nodes);
  if (!names.length || !range) {
    return <div className="thermal-result">
      <p className="thermal-unavailable" role="status">No temperatures could be estimated. {result.status_reason}</p>
      <ThermalCrossSection result={result} plot={plot} selected={null} onSelect={() => undefined} />
    </div>;
  }
  const recordedAmbient = typeof result.inputs.ambient_C === 'number' ? result.inputs.ambient_C : null;
  const base = nodeTemperature(result.nodes.ambient) ?? recordedAmbient ?? range[0];
  const top = Math.max(range[1], ...names.flatMap((name) => result.nodes[name].limit_C ?? []));
  const position = (temperature: number) => top > base ? Math.max(0, Math.min(100, (temperature - base) / (top - base) * 100)) : 0;
  const hottest = result.hottest_node ? nodeTemperature(result.nodes[result.hottest_node]) : null;
  const winding = tightestWinding(result);
  const magnets = result.nodes.magnets;
  const heat = (name: string) => result.nodes[name]?.heat_W ?? 0;
  const totalHeat = thermalTotalHeat(result);
  const node = selected ? result.nodes[selected] : undefined;
  const feedback = result.copper_feedback;
  return <div className="thermal-result">
    <div className="thermal-kpis">
      <Kpi label="Hottest part" value={hottest === null ? '—' : temperatureNumber(hottest, unit)} unit={symbol} note={result.hottest_node ? thermalNodeLabel(result.hottest_node) : 'Unavailable'} warn={isOver(result.nodes[result.hottest_node ?? ''])} />
      {winding
        ? <Kpi label="Winding against its limit" value={differenceNumber(Math.abs(winding.margin_K!), unit)} unit={`${symbol} ${winding.margin_K! < 0 ? 'over' : 'spare'}`} note={`Limit ${temperatureText(winding.limit_C!, unit)}, hotspot allowance included`} warn={winding.margin_K! < 0} />
        : <Kpi label="Winding against its limit" value="—" note="No limit recorded" />}
      <Kpi label="Magnets" value={nodeTemperature(magnets) === null ? '—' : temperatureNumber(nodeTemperature(magnets)!, unit)} unit={symbol}
        note={magnets?.limit_C != null && nodeTemperature(magnets) !== null ? thermalMargin(magnets, unit) : 'Their own eddy heat is not included'} warn={isOver(magnets)} />
      <Kpi label="Heat to remove" value={thermalNumber(totalHeat)} unit="W" note={`Copper ${thermalNumber(heat('winding') + heat('end_winding'))} W · iron ${thermalNumber(heat('teeth') + heat('yoke'))} W`} />
    </div>
    <div className="thermal-result-body">
      <ThermalCrossSection result={result} plot={plot} selected={selected} onSelect={setSelection} />
      <div className="thermal-parts-block">
        <table className="thermal-parts">
          <thead><tr><th scope="col">Part</th><th scope="col">Temperature</th>
            <th scope="col"><span className="thermal-parts-scale"><span>{temperatureText(base, unit)}</span><span>{temperatureText(top, unit)}</span></span></th><th scope="col">Against limit</th></tr></thead>
          <tbody>{names.map((name) => {
            const part = result.nodes[name]; const temperature = nodeTemperature(part);
            const colour = temperature === null ? '#697487' : thermalColour(temperature, range);
            return <tr key={name} className={`${selected === name ? 'is-selected' : ''}${isOver(part) ? ' is-over-limit' : ''}`} onClick={() => setSelection(name)}>
              <th scope="row"><button type="button" aria-pressed={selected === name} onClick={() => setSelection(name)}><i style={{ background: colour }} aria-hidden="true" />{thermalNodeLabel(name)}</button></th>
              <td className="thermal-parts-temp">{temperature === null ? 'Unavailable' : <>{temperatureNumber(temperature, unit)}<small> {symbol}</small></>}</td>
              <td className="thermal-parts-bar"><span className="thermal-bar" aria-hidden="true">
                {temperature !== null && <i style={{ width: `${position(temperature)}%`, background: colour }} />}
                {part.limit_C != null && <b style={{ left: `${position(part.limit_C)}%` }} title={`Limit ${temperatureText(part.limit_C, unit)}`} />}
              </span></td>
              <td className="thermal-parts-margin">{part.limit_C == null || temperature === null ? <span title="No temperature limit is set for this part.">—</span> : thermalMargin(part, unit)}</td>
            </tr>;
          })}</tbody>
        </table>
        <p className="thermal-visual-note">Bars run from the coolant temperature. The tick marks a part&apos;s limit.</p>
        {node && selected && <div className={`thermal-selected${isOver(node) ? ' is-over-limit' : ''}`} role="region" aria-label="Selected thermal part" aria-live="polite">
          <p><strong>{thermalNodeLabel(selected)}</strong>{nodeTemperature(node) === null ? ' · Unavailable' : ` · ${temperatureText(nodeTemperature(node)!, unit)}`}
            {node.limit_C != null && nodeTemperature(node) !== null && ` · ${thermalMargin(node, unit)} of ${temperatureText(node.limit_C, unit)}`}
            {` · ${thermalNumber(node.heat_W)} W generated in this part`}</p>
          <p>{node.status_reason}{['winding', 'end_winding'].includes(selected) && node.limit_C != null ? ' The limit includes the hotspot allowance.' : ''}</p>
        </div>}
      </div>
    </div>
    <details className="thermal-notes"><summary>What this estimate includes and leaves out</summary><ul>
      <li>{result.status_reason}</li>
      <li>Each value is one average temperature for the part, not its hottest spot.{result.nodes.housing ? ' Housing means its outer surface.' : ''}</li>
      {feedback && <li>Copper loss is recalculated at the estimated winding temperature: {shown(feedback.copper_loss_W)} W, against {shown(feedback.reference_copper_loss_W)} W at {temperatureText(feedback.reference_temperature_C, unit)}
        ({shown(feedback.copper_active_loss_W)} W in the slots, {shown(feedback.copper_end_winding_loss_W)} W in the end windings, {shown(feedback.phase_current_rms_A)} A rms, {shown(feedback.phase_resistance_ohm * 1000)} mΩ per phase).
        Current and iron loss stay at their solved values. {feedback.wire_source === 'derived' ? 'Wire size is estimated to fill the slots.' : 'Uses the specified winding wire.'}</li>}
      {result.rotor_heating && <li>{result.rotor_heating.basis === 'heat_transfer_only' ? 'Rotor and magnets are warmed only by heat from the stator.' : 'Rotor and magnets are warmed by heat from the stator and the heat you added.'} {result.rotor_heating.status_reason}
        {' '}Added heat: {shown(result.rotor_heating.additional_heat_W)} W. Mechanical heat in the rotor: {shown(result.rotor_heating.mechanical_heat_to_rotor_W)} W.</li>}
      {result.notes.map((note) => <li key={note}>{note}</li>)}
      <li>{result.calibrated ? 'Calibrated to the recorded measurement; still experimental.' : 'Not calibrated to a measurement.'} Thermal resistance multiplier: {shown(typeof result.inputs.calibration_multiplier === 'number' ? result.inputs.calibration_multiplier : null)}.</li>
    </ul></details>
    {result.baseline_without_extra_rotor_C && <details className="thermal-notes"><summary>Without the added rotor heat</summary><ul>{Object.entries(result.baseline_without_extra_rotor_C).map(([name, temperature]) => <li key={name}>{thermalNodeLabel(name)}: {temperatureText(temperature, unit)}</li>)}</ul></details>}
  </div>;
}

/** Why a speed has no torque, in a few words for the table. The full reason is in the summary above it. */
function missingSpeedLabel(reason: string): string {
  const first = reason.split('; ')[0];
  if (/^A direct solve at this point/.test(first)) return 'Not confirmed by the direct solve';
  if (/below the cold map/.test(first)) return 'Magnets colder than the cold map';
  if (/above the hot map/.test(first)) return 'Magnets hotter than the hot map';
  if (/outside the two solved maps/.test(first)) return 'Magnets outside the solved maps';
  if (/outside -50 to 250/.test(first)) return 'Too hot with this cooling';
  if (/No stable thermal equilibrium/.test(first)) return 'No stable temperature';
  if (/^temperature: /.test(first)) return 'Past a temperature limit at any current';
  if (/^voltage/.test(first)) return 'Past the voltage limit at any current';
  if (/cancel/i.test(first)) return 'Cancelled';
  return 'No result';
}

function RatingResult({ rating, envelope }: { rating: ThermalRating; envelope?: TorqueSpeedEnvelope | null }) {
  // Each speed as this version records it: an older curve's speed whose direct solve could not run reads as a new one's.
  const points = rating.points.map(readRatingRow);
  // A speed whose direct solve rejected it keeps its point for the record, but it is not a result.
  const held = points.filter(isHeldSpeed);
  const firstMissing = points.find((row) => !isHeldSpeed(row));
  const number = (value: number | null | undefined) => value == null ? '—' : shown(value);
  const [unit] = useTemperatureUnit();
  const symbol = unitSymbol(unit);
  const temperature = (value: number | null | undefined) => value == null ? '—' : temperatureNumber(value, unit);
  return <div className="thermal-result">
    <p className={`thermal-rating-summary${firstMissing ? ' needs-attention' : ''}`} role="status">
      <strong>{held.length} of {points.length} speeds have a result.</strong>
      {firstMissing && ` No result from ${shown(firstMissing.speed_rpm)} rpm: ${firstMissing.status_reason.split('; ')[0]}`}
      {firstMissing && /above the hot map/.test(firstMissing.status_reason) && ' Raise “Hot map magnets” under Solve → Thermal → Torque curve if the magnet grade allows it, or improve the cooling.'}
      {firstMissing && /below the cold map/.test(firstMissing.status_reason) && ' Lower “Cold map magnets” under Solve → Thermal → Torque curve if the magnet grade allows it.'}
    </p>
    <ThermalCurve rating={rating} envelope={envelope} />
    <div className="thermal-table-scroll"><table className="thermal-rating-table">
      <thead><tr><th scope="col">Speed (rpm)</th><th scope="col">Torque (N·m)</th><th scope="col">Current (A peak)</th><th scope="col">Winding ({symbol})</th><th scope="col">Magnets ({symbol})</th><th scope="col">Limited by</th></tr></thead>
      <tbody>{points.map((row) => <tr key={row.speed_rpm}>
        <td>{shown(row.speed_rpm)}</td><td>{number(isHeldSpeed(row) ? row.point?.torque_Nm : null)}</td><td>{number(isHeldSpeed(row) ? row.point?.current_peak_A : null)}</td>
        <td>{temperature(isHeldSpeed(row) ? row.point?.winding_temperature_C : null)}</td><td>{temperature(isHeldSpeed(row) ? row.point?.magnet_temperature_C : null)}</td>
        <td title={row.status === 'unavailable' ? row.status_reason : undefined}>{row.status === 'unavailable' ? missingSpeedLabel(row.status_reason) : row.limiting_constraint.replace(/_/g, ' ')}</td>
      </tr>)}</tbody>
    </table></div>
    <details className="thermal-notes"><summary>Checks behind each speed</summary><ul>
      <li>Interpolation check against stored evidence: {rating.acceptance_status.replace(/_/g, ' ').toLowerCase()}.{rating.acceptance_status === 'NOT_COMPARED' ? ' No matching evidence exists for this design and grid, so no verdict is given.' : ''}{rating.cancelled ? ' The calculation was cancelled; the remaining speeds are unavailable.' : ''}</li>
      {points.map((row) => <li key={row.speed_rpm}>{shown(row.speed_rpm)} rpm: {row.status_reason} Iterations {row.point?.iterations ?? 0}, residual {row.point?.temperature_residual_K == null ? 'unavailable' : differenceText(row.point.temperature_residual_K, unit)}. Direct check: {(row.point?.verification_status ?? 'NOT_COMPARED').replace(/_/g, ' ').toLowerCase()}. {row.point?.verification_reason}</li>)}
      {rating.notes.map((note) => <li key={note}>{note}</li>)}
    </ul></details>
    {rating.points.some((row) => row.user_magnet_case) && <details className="thermal-notes"><summary>With magnets at your chosen temperature</summary><ul>{rating.points.map((row) => <li key={row.speed_rpm}>{shown(row.speed_rpm)} rpm: {shown(row.user_magnet_case?.torque_Nm)} N·m at {row.user_magnet_case?.magnet_temperature_C == null ? 'an unknown temperature' : temperatureText(row.user_magnet_case.magnet_temperature_C, unit)}. {row.user_magnet_case?.status_reason}</li>)}</ul></details>}
  </div>;
}

/** The thermal result for a run: key numbers, the coloured cross-section and a table of parts. */
export function ThermalCard({ analysis, plot, envelope, origin, label = 'Thermal results' }: {
  origin?: SolveResult['saved_run']; analysis: ThermalAnalysis | null; plot?: PublicFieldLinePlot | null; envelope?: TorqueSpeedEnvelope | null; label?: string;
}) {
  const [message, setMessage] = useState<string | null>(null);
  if (!analysis) return null;
  const result = analysis.result;
  const download = async (kind: 'pdf' | 'csv') => { try { await downloadThermalAnalysis(analysis.id, kind, origin); } catch (error) { setMessage(errorText(error)); } };
  return <section className="thermal-card" aria-label={label}>
    {result.kind === 'steady_state_thermal' ? <PointResult key={analysis.id} result={result} plot={plot} /> : <RatingResult rating={result} envelope={envelope} />}
    <details className="thermal-notes"><summary>Recorded inputs</summary><dl className="thermal-recorded-inputs">{Object.entries(result.inputs).map(([key, value]) => <div key={key}><dt>{key.replace(/_/g, ' ')}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl></details>
    <div className="thermal-card-actions">
      <button type="button" onClick={() => void download('pdf')}>{analysis.kind === 'point' ? 'Run + thermal PDF' : 'Thermal performance PDF'}</button>
      <button type="button" onClick={() => void download('csv')}>{analysis.kind === 'point' ? 'Run + thermal CSV' : 'Thermal performance CSV'}</button>
    </div>
    {message && <p role="alert">{message}</p>}
  </section>;
}

function ThermalCurve({ rating, envelope }: {rating: ThermalRating; envelope?: TorqueSpeedEnvelope | null}) {
  const peak = envelope?.curves.find((curve) => curve.limit === 'peak');
  const maxSpeed = Math.max(...rating.points.map((p) => p.speed_rpm), 1);
  const maxTorque = Math.max(...rating.points.filter(isHeldSpeed).map((p) => p.point!.torque_Nm!), ...(peak?.torque_Nm ?? [])) || 1;
  const x = (value: number) => 55 + value / maxSpeed * 650;
  const y = (value: number) => 205 - value / maxTorque * 180;
  return <figure className="performance-chart"><figcaption>Peak and thermally limited torque — experimental</figcaption>
    <p>Blue: peak at the original map temperature. Green dashed: coupled thermally limited torque. Gaps are unavailable speeds.</p>
    <svg viewBox="0 0 760 250" role="img" aria-label="Thermally limited torque compared with peak">
      <line x1="55" y1="205" x2="705" y2="205" stroke="currentColor" /><line x1="55" y1="25" x2="55" y2="205" stroke="currentColor" />
      {peak && <path d={peak.speed_rpm.map((rpm, i) => `${i ? 'L' : 'M'}${x(rpm)},${y(peak.torque_Nm[i])}`).join(' ')} stroke="#3987e5" fill="none" strokeWidth="2" />}
      <path d={thermalCurvePath(rating, x, y)} stroke="#3dbb92" strokeDasharray="7 4" fill="none" strokeWidth="3" />
      {rating.points.filter(isHeldSpeed).map((row) => <circle key={row.speed_rpm} cx={x(row.speed_rpm)} cy={y(row.point!.torque_Nm!)} r="3" fill="#3dbb92" />)}
      {[0, maxSpeed / 2, maxSpeed].map((rpm) => <text key={rpm} x={x(rpm)} y="224" textAnchor="middle" fill="currentColor" fontSize="12">{shown(rpm)}</text>)}
      <text x="380" y="245" textAnchor="middle" fill="currentColor">Speed (rpm)</text><text x="5" y="20" fill="currentColor">N·m</text><text x="50" y="35" textAnchor="end" fill="currentColor" fontSize="12">{shown(maxTorque)}</text>
    </svg></figure>;
}

/**
 * The Thermal tab in Results: the estimate for this run.
 *
 * Results shows; Solve sets up and runs. The setup and the torque curve are
 * changed under Solve → Thermal. The one action kept here computes the first
 * estimate for a run that has none, with the setup as it stands.
 */
export function ThermalPanel({ config, result, designName }: { config: MotorConfig; result: SolveResult; designName: string | null }) {
  const run = useThermalRun(config, result, designName);
  const [values] = useThermalSetup(config);
  const [unit] = useTemperatureUnit();
  const { envelope } = thermalDriveSettings(config, result);
  // The header shows the setup as it is now; a result computed before an edit says so.
  const curveStale = !!run.rating && run.curveStale;
  const previousInputs = run.stale && curveStale ? 'The estimate and the torque curve are from the previous thermal inputs. Run them again under Solve → Thermal.'
    : run.stale ? 'This estimate is from the previous thermal inputs. Run it again under Solve → Thermal.'
      : curveStale ? 'The torque curve is from the previous thermal inputs. Run it again under Solve → Thermal → Torque curve.' : null;
  return <section className="thermal-panel" aria-label="Thermal estimate">
    <header className="thermal-panel-head">
      <div>
        <div className="results-card-heading"><h3>Thermal estimate</h3><StatusBadge status="experimental" title="Uncalibrated estimate under the entered cooling assumptions. No bench qualification." /></div>
        <p>{thermalSetupSummary(values, unit).replace(' · Experimental', '')} · steady state at the solved operating point</p>
      </div>
      {!run.loadingPoint && (!run.analysis || run.busy) && <button type="button" className="thermal-compute-button" disabled={!run.ready} onClick={() => void run.runPoint()}>{run.busy ? 'Computing…' : 'Compute thermal estimate'}</button>}
    </header>
    {run.validation && <p className="thermal-run-status needs-attention" role="status">{run.validation} Change it under Solve → Thermal.</p>}
    {previousInputs && <p className="thermal-run-status needs-attention" role="status">{previousInputs}</p>}
    {run.message && <p className="thermal-run-status needs-attention" role="alert">{run.message}</p>}
    {run.job && <p className="thermal-run-status" role="status">{run.job.stage}{run.job.error ? `: ${run.job.error}` : ''}</p>}
    {run.analysis
      ? <ThermalCard analysis={run.analysis} origin={result.saved_run} plot={result.field_line_plot} envelope={envelope} />
      : <p className="thermal-empty">{run.loadingPoint ? 'Loading the saved thermal estimate…' : 'No thermal estimate for this run yet. It takes a moment and uses the setup from Solve → Thermal.'}</p>}
    {run.rating && <>
      <h4 className="thermal-group-title">Thermally limited torque curve</h4>
      <ThermalCard analysis={run.rating} envelope={envelope} label="Thermally limited torque curve" />
    </>}
    <p className="thermal-visual-note">To change the cooling, the limits or the torque curve, go back to Solve and open the Thermal setup.</p>
  </section>;
}
