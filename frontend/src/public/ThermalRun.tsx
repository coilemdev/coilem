import { useEffect, useState } from 'react';
import { cancelPublicSolve, computeThermalPoint, getLatestThermalAnalysis, getThermalAnalysis } from './api';
import { validationErrorMessage } from './apiErrors';
import type { MotorConfig, SolveResult } from './model';
import type { DriveControl, DriveLimits, TorqueSpeedEnvelope } from './performance';
import { currentUnits, defaultDriveLimits } from './performanceView';
import { asPublicConfig } from './publicRequest';
import { isHeldSpeed, legacyThermalKey, recordedThermalInputs, rotorLayoutOf, sameThermalInputs, thermalFieldMeta, thermalInputs, thermalKey, unavailableEstimateReason, type RotorLayout, type ThermalAnalysis } from './thermal';
import { currentThermalJob, rememberThermal, startThermalJob, subscribeThermalJob, thermalSlot } from './thermalJob';
import { TemperatureInput } from './TemperatureInput';
import { useThermalSetup } from './ThermalSetup';
import { designDcBusV } from './torqueSpeedAnalysis';
import { unitSymbol, type TemperatureUnit } from './thermalUnits';
import { differenceNumber, nodeTemperature, temperatureNumber, temperatureText, thermalNodeLabel, thermalNumber, thermalTotalHeat, tightestWinding } from './thermalVisual';
import { useTemperatureUnit } from './useTemperatureUnit';

/** A thermal request the API refused names its inputs by their form labels, not their internal keys. */
function errorText(error: unknown, layout: RotorLayout = 'inner'): string {
  if (!error || typeof error !== 'object' || !('message' in error)) return 'Thermal calculation failed.';
  const rejected = validationErrorMessage((error as { validation?: unknown }).validation,
    (path) => path[0] === 'inputs' && path.length > 1 ? thermalFieldMeta(path[1], layout)?.label ?? `Thermal input ${path.slice(1).join(' → ')}` : null);
  return rejected ?? String(error.message);
}

/** The thermal estimate, or the torque curve, last computed for this run, if any. */
export function useThermalRecord(config: MotorConfig, result: SolveResult | null, kind: ThermalAnalysis['kind'] = 'point') {
  const key = result ? thermalKey(config, result) : null;
  const project = result?.saved_run?.project_slug;
  const runId = result?.saved_run?.run_id;
  const legacy = result && runId ? legacyThermalKey(config, result) : null;
  const slot = key && thermalSlot(key, kind);
  const [loaded, setLoaded] = useState<{slot: string | null; record: ThermalAnalysis | null} | null>(null);
  useEffect(() => {
    let active = true;
    let sequence = 0;
    const load = async () => {
      const request = ++sequence;
      let value: ThermalAnalysis | null = null;
      if (key) {
        try {
          if (project && runId) value = await getLatestThermalAnalysis(project, runId, kind).catch(() => null);
          if (!value) {
            const job = currentThermalJob();
            if (kind === 'rating' && job?.key === key && job.analysis) value = job.analysis;
            else {
              let id = localStorage.getItem(thermalSlot(key, kind));
              if (!id && legacy) {
                id = localStorage.getItem(thermalSlot(legacy, kind));
                // Older versions hashed the editable configuration alongside the solve timestamp.
                const suffix = thermalSlot(legacy.slice(legacy.lastIndexOf('.')), kind);
                const matches = Object.keys(localStorage).filter((k) => k.startsWith('coilem.thermal.run.') && k.endsWith(suffix));
                if (!id && matches.length === 1) id = localStorage.getItem(matches[0]);
              }
              if (id) value = await getThermalAnalysis(id);
            }
          }
        } catch { /* The associated record may have been removed. */ }
      }
      if (active && request === sequence) setLoaded({slot, record: value?.kind === kind ? value : null});
    };
    void load(); window.addEventListener('coilem-thermal-updated', load);
    return () => { active = false; window.removeEventListener('coilem-thermal-updated', load); };
  }, [key, kind, project, runId, legacy, slot]);
  return !slot ? null : loaded?.slot === slot ? loaded.record : undefined;
}

/**
 * Drive limits and control law for a thermally limited torque curve: those of
 * the torque–speed analysis saved with the run, or the default limits when the
 * run was solved without one.
 */
export function thermalDriveSettings(config: MotorConfig, result: SolveResult): { limits: DriveLimits; control: DriveControl; envelope: TorqueSpeedEnvelope | null } {
  const analysis = result.torque_speed_analysis;
  const units = currentUnits(config.solve_params.current_amplitude_convention);
  const limits = analysis?.settings.limits ?? defaultDriveLimits({
    ratedSpeedRpm: config.solve_params.rated_speed_rpm,
    phaseCurrentRmsA: result.summary.loss_breakdown?.phase_current_rms_A,
    backEmfRmsV: result.summary.back_emf_fundamental_V,
    dcBusV: designDcBusV(config),
    shownUnitPeakA: units.toPeak(1),
  });
  return { limits, control: analysis?.settings.control ?? 'mtpa', envelope: analysis?.envelope ?? null };
}

export interface RatingOptions { lowC: number; highC: number; userMagnetC: number | null }

// The estimate comes back in milliseconds. Without a floor its running state would never be seen,
// and pressing the button would look as if nothing had happened.
const SHORTEST_RUN_SHOWN_MS = 600;

/**
 * Everything needed to run a thermal estimate for a solved run, from Solve or
 * from Results: what is still missing, the actions, and the latest estimate.
 */
export function useThermalRun(config: MotorConfig, result: SolveResult | null, designName: string | null) {
  const key = result ? thermalKey(config, result) : null;
  const savedPoint = useThermalRecord(config, result);
  const analysis = savedPoint ?? null;
  const rating = useThermalRecord(config, result, 'rating') ?? null;
  const [values] = useThermalSetup(config);
  const savedRef = result?.saved_run ? {project_slug: result.saved_run.project_slug, run_id: result.saved_run.run_id} : null;
  const [unit] = useTemperatureUnit();
  const [job, setJob] = useState(currentThermalJob);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [finishedAt, setFinishedAt] = useState<Date | null>(null);
  useEffect(() => subscribeThermalJob(setJob), []);
  // A time belongs to the run it was measured on.
  useEffect(() => setFinishedAt(null), [key]);
  const mechanicalW = result?.summary.loss_breakdown?.mechanical_loss_W ?? config.solve_params.mechanical_loss_W ?? 0;
  let inputs: Record<string, unknown> | null = null;
  let validation = '';
  const layout = rotorLayoutOf(config);
  try { inputs = thermalInputs(values, mechanicalW, layout, unit, config.materials.conductor); } catch (error) { validation = error instanceof Error ? error.message : 'Review the thermal inputs.'; }
  // Thermal starts from the losses of a solved run; without them there is nothing to distribute.
  const blocked: 'no-run' | 'no-losses' | null = !result ? 'no-run' : !result.summary.iron_loss ? 'no-losses' : null;
  const running = job?.phase === 'running';
  const ready = blocked === null && inputs !== null && !busy && !running;
  // A saved result is looked up by its electromagnetic run, so it outlives an edit to the cooling.
  // It belongs to the thermal inputs it recorded: once they differ from the setup, it is from the previous inputs.
  const changedSince = (record: ThermalAnalysis | null) => !!record && (!inputs || !sameThermalInputs(inputs, recordedThermalInputs(record)));
  const name = designName ?? 'Motor';

  const runPoint = async () => {
    if (!result || !key || !inputs) return;
    setBusy(true); setMessage(null);
    const started = performance.now();
    const shown = () => new Promise((resolve) => { window.setTimeout(resolve, Math.max(0, SHORTEST_RUN_SHOWN_MS - (performance.now() - started))); });
    try {
      const analysis = await computeThermalPoint({ saved_run: savedRef, request: { config: asPublicConfig(config) }, source: { summary: result.summary, solve_metadata: result.solve_metadata }, inputs, design_name: name });
      await shown();
      rememberThermal(key, analysis); setFinishedAt(new Date());
    } catch (error) { await shown(); setMessage(errorText(error, layout)); } finally { setBusy(false); }
  };
  const runRating = (options: RatingOptions) => {
    if (!result || !key || !inputs) return;
    setMessage(null);
    const { limits, control } = thermalDriveSettings(config, result);
    const started = startThermalJob(key, { saved_run: savedRef, request: { config: asPublicConfig(config) }, inputs, limits, control,
      low_C: options.lowC, high_C: options.highC, preset: 'preview', design_name: name, user_magnet_C: options.userMagnetC });
    if (!started) setMessage('A thermal job is already running.');
  };
  const stale = changedSince(analysis);
  const previous = rating?.curve_options;
  const low = previous?.lowC ?? rating?.bracket?.low.magnet_temperature_C;
  const high = previous?.highC ?? rating?.bracket?.high.magnet_temperature_C;
  const differs = (draft: string, saved: number | undefined) => saved != null && (!draft.trim() || Number(draft) !== saved);
  const curveInputsChanged = differs(values.curve_low_C ?? '20', low)
    || differs(values.curve_high_C ?? '80', high)
    || (!!previous && (values.curve_user_C?.trim() ? Number(values.curve_user_C) : null) !== previous.userMagnetC);
  return { analysis, rating, loadingPoint: savedPoint === undefined, values, mechanicalW, layout, validation, blocked, busy, running, ready, message, finishedAt,
    // The saved estimate, or the torque curve, was computed with other thermal inputs than the setup now holds.
    stale, curveStale: changedSince(rating) || curveInputsChanged,
    // An estimate that came back without temperatures, and why. Not shown once the inputs have changed.
    unavailable: stale ? null : unavailableEstimateReason(analysis),
    job: job && job.key === key ? job : null, runPoint, runRating, cancel: () => { void cancelPublicSolve(); } };
}

export type ThermalRun = ReturnType<typeof useThermalRun>;

/** "Solving the cold map: 12 of 58", or the stage alone when it has no count. */
export function jobStageText(job: { stage: string; done?: number; total?: number } | null | undefined): string {
  if (!job) return 'Working';
  return job.total ? `${job.stage}: ${job.done ?? 0} of ${job.total}` : job.stage;
}

/** "End winding at 164.1 °C", or null when the estimate has no temperatures. */
export function hottestPartText(analysis: ThermalAnalysis | null, unit: TemperatureUnit = 'C'): string | null {
  if (analysis?.result.kind !== 'steady_state_thermal' || !analysis.result.hottest_node) return null;
  const temperature = nodeTemperature(analysis.result.nodes[analysis.result.hottest_node]);
  return temperature === null ? null : `${thermalNodeLabel(analysis.result.hottest_node)} at ${temperatureText(temperature, unit)}`;
}

const STALE_ESTIMATE = 'The thermal inputs changed since the last estimate. Run it again to update the temperatures.';

/** The Solve page's run button and status while the Thermal setup is shown. */
export function ThermalRunControls({ run, solving = false, onOpenReport, onShowElectromagnetic }: {
  /** Shared with the monitor beside it, so both show the same run. */
  run: ThermalRun;
  /** The electromagnetic analysis is running, so its losses are on their way. */
  solving?: boolean; onOpenReport: () => void; onShowElectromagnetic: () => void;
}) {
  const [unit] = useTemperatureUnit();
  const hottest = hottestPartText(run.analysis, unit);
  const status = solving ? 'The electromagnetic analysis is running. The thermal estimate can run when it finishes.'
    : run.blocked === 'no-run' ? 'Thermal uses the losses of a solved run. Run the electromagnetic analysis first.'
    : run.blocked === 'no-losses' ? 'The last run has no losses. Turn on Losses & efficiency under Electromagnetic → Analysis, then run it again.'
      : run.validation ? run.validation
        : run.busy ? 'Computing the thermal estimate…'
          : run.stale ? STALE_ESTIMATE
          : hottest ? `Estimate ready: hottest part is the ${hottest.charAt(0).toLowerCase()}${hottest.slice(1)}.`
            : run.unavailable ? `No estimate. ${run.unavailable}`
              : 'Ready. Uses the losses of the solved operating point.';
  return <div className="thermal-run-controls">
    <p className={`thermal-run-status${!solving && (run.blocked || run.validation || ((run.unavailable || run.stale) && !run.busy)) ? ' needs-attention' : ''}`} role="status">{status}</p>
    {solving ? null : run.blocked ? <button className="public-run-btn" type="button" onClick={onShowElectromagnetic}>Go to Electromagnetic setup</button>
      : run.stale ? <button className="public-run-btn" type="button" disabled={!run.ready} onClick={() => void run.runPoint()}>{run.busy ? 'Running…' : '▶ Run thermal estimate again'}</button>
      : hottest ? <>
        <button className="public-run-btn" type="button" onClick={onOpenReport}>View Results →</button>
        <button className="public-run-again-btn" type="button" disabled={!run.ready} onClick={() => void run.runPoint()}>Run again</button>
      </> : <button className="public-run-btn" type="button" disabled={!run.ready} onClick={() => void run.runPoint()}>{run.busy ? 'Running…' : '▶ Run thermal estimate'}</button>}
    {run.message && <p className="thermal-run-status needs-attention" role="alert">{run.message}</p>}
  </div>;
}

/**
 * The Solve page's side panel while the Thermal setup is shown: what the
 * estimate is doing, then what it found. It sits where the electromagnetic
 * solve reports its progress, so a run is seen in the same place either way.
 */
export function ThermalRunMonitor({ run, solving = false, onOpenReport }: { run: ThermalRun; solving?: boolean; onOpenReport: () => void }) {
  const estimate = run.analysis?.result.kind === 'steady_state_thermal' ? run.analysis.result : null;
  const curve = run.rating?.result.kind === 'thermally_limited_rating' ? run.rating.result : null;
  const held = curve ? curve.points.filter(isHeldSpeed) : [];
  const hottest = estimate?.hottest_node ? nodeTemperature(estimate.nodes[estimate.hottest_node]) : null;
  const working = run.busy || run.running;
  const [unit] = useTemperatureUnit();
  const symbol = unitSymbol(unit);
  const counted = run.running && !!run.job?.total && run.job.done != null;
  const winding = estimate ? tightestWinding(estimate) : undefined;
  const magnets = estimate ? nodeTemperature(estimate.nodes.magnets) : null;
  const headline = run.busy ? 'Running'
    : run.running ? 'Torque curve running'
      : solving ? 'Waiting for the electromagnetic analysis'
        : run.blocked === 'no-run' ? 'Needs a solved run'
          : run.blocked === 'no-losses' ? 'Needs a run with losses'
            : run.message || run.job?.error ? 'Stopped'
              : run.validation ? 'Check the thermal setup'
                : run.stale ? 'Inputs changed'
                  : hottest !== null ? 'Complete'
                    : run.unavailable ? 'No estimate'
                      : curve ? (run.curveStale ? 'Inputs changed' : 'Torque curve complete')
                        : 'Ready to run';
  const row = (label: string, value: string, unit: string, over = false) => <tr className={over ? 'is-over-limit' : undefined}>
    <th scope="row">{label}</th><td className="motor-constants-value">{value}</td><td className="motor-constants-unit">{unit}</td>
  </tr>;
  return <section className={`public-live-monitor thermal-run-monitor${working ? ' is-running' : ''}`} aria-label="Thermal estimate status" aria-busy={working}>
    <div className="public-live-monitor-heading"><span className="public-section-kicker">Thermal estimate</span><strong>{headline}</strong></div>
    {working && <>
      {counted
        ? <div className="progress-track" role="progressbar" aria-label="Thermal estimate progress" aria-valuemin={0} aria-valuemax={run.job!.total} aria-valuenow={run.job!.done}>
          <span style={{ width: `${Math.min(100, 100 * run.job!.done! / run.job!.total!)}%` }} /></div>
        : <div className="progress-track indeterminate" role="progressbar" aria-label="Thermal estimate progress"><span style={{ width: '32%' }} /></div>}
      <p className="thermal-run-monitor-note" role="status">{run.busy
        ? 'Placing the solved losses in the parts and balancing the heat paths to the surroundings.'
        : `${jobStageText(run.job)}. A torque curve solves two torque–speed maps first, so it takes minutes.`}</p>
    </>}
    {!working && (run.message || run.job?.error) && <p className="thermal-run-monitor-note needs-attention">{run.message ?? run.job?.error}</p>}
    {!working && !run.message && run.stale && <p className="thermal-run-monitor-note needs-attention">{hottest === null ? STALE_ESTIMATE
      : 'The thermal inputs changed since the last estimate. The temperatures below are from the previous inputs. Run it again to update them.'}</p>}
    {!working && !run.message && !run.stale && hottest === null && !curve && <p className="thermal-run-monitor-note">{
      solving ? 'The estimate uses the losses of the run being solved now.'
        : run.blocked === 'no-run' ? 'Run the electromagnetic analysis first. The estimate starts from its losses.'
          : run.blocked === 'no-losses' ? 'The last run was solved without losses. Turn on Losses & efficiency and run it again.'
            : run.validation ? run.validation
              : run.unavailable ? run.unavailable
                : 'Takes about a second. It uses the losses of the solved operating point and the cooling entered on the left.'}</p>}
    {!run.busy && estimate && hottest !== null && <>
      <table className={`motor-constants public-result-list thermal-run-monitor-results${run.stale ? ' is-previous' : ''}`}
        aria-label={run.stale ? 'Previous estimate, from the previous inputs' : undefined}><tbody>
        {row(`Hottest part · ${thermalNodeLabel(estimate.hottest_node!)}`, temperatureNumber(hottest, unit), symbol, (estimate.nodes[estimate.hottest_node!]?.margin_K ?? 0) < 0)}
        {winding && row(`Winding against its ${temperatureText(winding.limit_C!, unit)} limit`, differenceNumber(Math.abs(winding.margin_K!), unit), `${symbol} ${winding.margin_K! < 0 ? 'over' : 'spare'}`, winding.margin_K! < 0)}
        {magnets !== null && row('Magnets', temperatureNumber(magnets, unit), symbol, (estimate.nodes.magnets?.margin_K ?? 0) < 0)}
        {row('Heat to remove', thermalNumber(thermalTotalHeat(estimate)), 'W')}
      </tbody></table>
      <div className="thermal-run-monitor-foot">
        <span>{run.stale ? 'From the previous inputs' : run.finishedAt ? `Finished ${run.finishedAt.toLocaleTimeString()}` : 'From the last estimate for this run'} · uncalibrated</span>
        <button type="button" onClick={onOpenReport}>Thermal results →</button>
      </div>
    </>}
    {!working && curve && <div className="thermal-run-monitor-curve">
      <p className="thermal-run-monitor-note"><strong>Torque curve</strong> · {held.length} of {curve.points.length} speeds{curve.cancelled ? ' · cancelled' : ''}{run.curveStale ? ' · from the previous inputs' : ''}</p>
      {run.curveStale && <p className="thermal-run-monitor-note needs-attention">The thermal inputs changed since this torque curve. Run it again under Torque curve to update it.</p>}
      {held.length > 0 && <table className={`motor-constants public-result-list thermal-run-monitor-results${run.curveStale ? ' is-previous' : ''}`}
        aria-label={run.curveStale ? 'Previous torque curve, from the previous inputs' : undefined}><tbody>
        {row(`Held at ${thermalNumber(held[0].speed_rpm)} rpm`, thermalNumber(held[0].point!.torque_Nm!), 'N·m')}
        {held.length > 1 && row(`Held at ${thermalNumber(held[held.length - 1].speed_rpm)} rpm`, thermalNumber(held[held.length - 1].point!.torque_Nm!), 'N·m')}
      </tbody></table>}
      {hottest === null && <div className="thermal-run-monitor-foot"><span>Uncalibrated</span><button type="button" onClick={onOpenReport}>Thermal results →</button></div>}
    </div>}
  </section>;
}

/** Optional: the torque the motor can hold at each speed without exceeding its temperature limits. */
export function ThermalRatingControls({ config, result, designName }: { config: MotorConfig; result: SolveResult | null; designName: string | null }) {
  const run = useThermalRun(config, result, designName);
  const [values, setValues] = useThermalSetup(config);
  const {curve_low_C: low = '20', curve_high_C: high = '80', curve_user_C: userMagnet = ''} = values;
  const change = (key: string) => (value: string) => setValues({...values, [key]: value});
  const numbersOk = [low, high].every((text) => text.trim() !== '' && Number.isFinite(Number(text))) && Number(low) < Number(high);
  const [unit] = useTemperatureUnit();
  // The three temperatures are kept in °C, as the request takes them, and typed in the chosen unit.
  const field = (label: string, value: string, change: (text: string) => void, accessible: string) => <label className="param-row public-param-row thermal-param-row">
    <span className="param-label">{label}<small>{unitSymbol(unit)}</small></span>
    <span className="param-control"><TemperatureInput ariaLabel={accessible} unit={unit} value={value} onChange={change} /></span>
  </label>;
  return <div className="thermal-fields">
    <p className="thermal-setup-hint" role="note">Finds the torque the motor can hold at each speed without passing a temperature limit. It solves two torque–speed maps, one cold and one hot (58 solves when not cached), so it takes minutes.</p>
    {field('Cold map magnets', low, change('curve_low_C'), 'Cold map temperature')}
    {field('Hot map magnets', high, change('curve_high_C'), 'Hot map temperature')}
    {field('Also try magnets at', userMagnet, change('curve_user_C'), 'User magnet sensitivity')}
    <div className="thermal-rating-actions">
      {run.running
        ? <button type="button" className="thermal-starter-button" onClick={run.cancel}>Cancel torque curve</button>
        : <button type="button" className="thermal-starter-button" disabled={!run.ready || !numbersOk} onClick={() => run.runRating({ lowC: Number(low), highC: Number(high), userMagnetC: userMagnet.trim() ? Number(userMagnet) : null })}>Run torque curve</button>}
    </div>
    {run.job && <p className="thermal-run-status" role="status">{run.job.phase === 'running' ? jobStageText(run.job) : run.job.stage}{run.job.error ? `: ${run.job.error}` : ''}</p>}
    {run.message && <p className="thermal-run-status needs-attention" role="alert">{run.message}</p>}
  </div>;
}
