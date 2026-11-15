import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  deletePublicRun,
  listPublicRuns,
  loadPublicRunComparison,
  type PublicRunListRecord,
  type PublicRunStoragePolicy,
} from './api';
import { motorConstantsView } from './machineConstants';
import { compareRunDq, type ComparisonDqCell } from './dqComparison';
import type { PublicFieldLinePlot, SolveResult } from './model';
import { previousCompletedRun, type ComparisonFields, type ComparisonLossCell, type ComparisonResult } from './runComparison';
import type { ComparisonInputs } from './runInputChanges';
import { COGGING_METHOD_LABELS } from './coggingView';
import { RunInputChanges } from './RunChangesTable';
import { COMPARISON_STYLES, addComparisonRun, compareMultipleLosses, compareMultipleTiming, initialComparisonSelection, pinComparisonBaseline, reconcileComparisonSelection, removeComparisonRun, selectComparisonRun, type ComparisonSlotId } from './multiRunComparison';
import { formatSignificant, torqueDecimals } from './numberFormat';
import { torqueRippleView } from './resultMetrics';
import { WaveformChart } from './WaveformChart';
import { InfoTip } from './Popover';
import { formatSeconds } from './solveTime';
import { StatusDot } from './OutputStatusBadge';
import { ComparisonCells, ComparisonHeader } from './ComparisonTable';
import { comparisonPercentDelta as percentDelta, comparisonSignificantDelta as lossDelta } from './comparisonNumbers';
import { RunEnvelopeComparison, type EnvelopeComparisonState } from './RunEnvelopeComparison';
import { RunFieldComparison, type FieldComparisonState } from './RunFieldComparison';

interface LoadedRun {
  record: PublicRunListRecord;
  result: ComparisonResult;
  inputs?: ComparisonInputs | null;
  fields?: ComparisonFields | null;
}

interface PublicRunComparisonProps {
  currentResult?: SolveResult | null;
  manageRuns?: boolean;
  compareWithPrevious?: boolean;
  /** Opens a completed run's stored result in Solve and Results. */
  onOpenRun?: (run: PublicRunListRecord) => void;
}

const METRICS: Array<{
  label: string;
  unit: string;
  deltaUnit?: string;
  digits?: number;
  /** A torque in N·m: small values keep three significant figures (#270). */
  torque?: boolean;
  /** Shown only when either run has the value. */
  optional?: boolean;
  value: (result: ComparisonResult) => number | null | undefined;
}> = [
  { label: 'Average torque', unit: 'N·m', torque: true, value: (run) => run.summary.avg_torque_Nm },
  // No percentage where it means nothing (no current, near-zero average).
  { label: 'Torque ripple', unit: '%', deltaUnit: 'pp', value: (run) => torqueRippleView(run).ripplePct },
  { label: 'Back EMF', unit: 'V', value: (run) => run.summary.back_emf_fundamental_V },
  { label: 'Peak tooth B', unit: 'T', value: (run) => run.summary.peak_flux_density_teeth_T },
  { label: 'Peak yoke B', unit: 'T', value: (run) => run.summary.peak_flux_density_yoke_T },
  // Per rms ampere, as in Results: the summary stores Kt per peak ampere (#153).
  { label: 'Torque constant', unit: 'N·m/A rms', value: (run) => motorConstantsView(run.summary).kt.value },
  { label: 'Back EMF constant (Ke)', unit: 'V/krpm L-L rms', value: (run) => motorConstantsView(run.summary).ke.value },
  { label: 'Back EMF THD (headline)', unit: '%', deltaUnit: 'pp', value: (run) => run.summary.back_emf_thd_pct },
  // The cogging sweep (#185), for runs that solved one.
  { label: 'Cogging torque p-p', unit: 'N·m', torque: true, optional: true, value: (run) => run.summary.cogging?.peak_to_peak_Nm },
  { label: 'Cogging fundamental', unit: 'N·m', torque: true, optional: true, value: (run) => run.summary.cogging?.first_harmonic_Nm },
];

function runKey(run: Pick<PublicRunListRecord, 'project_slug' | 'run_id'>): string {
  return `${run.project_slug}/${run.run_id}`;
}

function solverLabel(solverName: string | null | undefined): string {
  if (!solverName) return 'Unknown solver';
  if (solverName.toLowerCase().startsWith('magneto2d')) return 'Magneto2D';
  return solverName;
}

function isMagneto2dRun(run: PublicRunListRecord): boolean {
  return run.solver_name?.toLowerCase().startsWith('magneto2d') === true;
}

const runDateTime = new Intl.DateTimeFormat('en-US', {
  month: '2-digit', day: '2-digit', year: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});

function formatRunTime(timestamp: string | null | undefined, fallback: string): string {
  const date = timestamp ? new Date(timestamp) : null;
  return date && Number.isFinite(date.getTime()) ? runDateTime.format(date).replace(',', '') : fallback;
}

function runLabel(run: PublicRunListRecord): string {
  const name = run.project_name || run.project_slug;
  const timestamp = formatRunTime(run.completed_at, run.run_id);
  return `${name} · ${run.run_setup?.name || 'Setup not recorded'} · ${timestamp}`;
}

function formatBytes(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '—';
  if (value < 1024) return `${value.toFixed(0)} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let scaled = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && scaled >= 1024; index += 1) {
    scaled /= 1024;
    unit = units[index];
  }
  return `${scaled.toFixed(scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2)} ${unit}`;
}

function apiErrorMessage(reason: unknown, fallback: string): string {
  if (reason && typeof reason === 'object' && 'message' in reason) {
    return String((reason as { message: unknown }).message);
  }
  return reason instanceof Error ? reason.message : fallback;
}

function storedRunTime(run: PublicRunListRecord): string {
  return formatRunTime(run.completed_at || run.started_at, run.run_id);
}

function storedRunStatus(run: PublicRunListRecord): string {
  if (run.status === 'complete') return 'Saved';
  if (run.status === 'cancelled') return 'Cancelled';
  if (run.status === 'failed') return 'Incomplete';
  if (run.status === 'running') return 'Running';
  return run.status || 'Unknown';
}

function number(value: number | null | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

function delta(left: number | null | undefined, right: number | null | undefined, digits = 2): string {
  if (typeof left !== 'number' || typeof right !== 'number' || !Number.isFinite(left) || !Number.isFinite(right)) return '—';
  const difference = right - left;
  const rounded = Number(difference.toFixed(digits));
  return `${rounded > 0 ? '+' : ''}${rounded.toFixed(digits)}`;
}

function timingValue(value: number | null, unit: string): string {
  return value === null ? 'Not recorded' : unit === 's' ? formatSeconds(value) : number(value, 0);
}

function lossNumber(value: number, unit: string): string {
  return unit === '%' ? value.toFixed(1) : formatSignificant(value);
}

function LossComparisonValue({ cell, label, unit }: { cell: ComparisonLossCell; label: string; unit: string }) {
  return <>
    <span className="public-run-compare-loss-value">{cell.value === null ? cell.missing : <>{lossNumber(cell.value, unit)} <small>{unit}</small></>}</span>
    {cell.status && <StatusDot status={cell.status} label={label} reason={cell.reason || 'No status reason was recorded.'} />}
    {cell.partial && <small className="public-run-compare-loss-partial">Partial <InfoTip label={`${label} partial output`}>This recorded shaft output excludes the unavailable iron loss. Deltas require the same loss basis in both runs.</InfoTip></small>}
  </>;
}

function DqComparisonValue({ cell, label, unit }: { cell: ComparisonDqCell; label: string; unit: string }) {
  return <>
    {cell.value === null ? <>{cell.missing}{cell.reason && cell.status?.status !== 'unavailable' && <InfoTip label={`${label} availability`}>{cell.reason}</InfoTip>}</>
      : <>{formatSignificant(cell.value)} <small>{unit}</small></>}
    {cell.status && <StatusDot status={cell.status.status} label={label} reason={cell.status.reason || 'No status reason was recorded.'} />}
  </>;
}

function timingDelta(before: number | null, after: number | null, unit: string): string {
  if (before === null || after === null) return '—';
  if (unit !== 's') return delta(before, after, 0);
  const difference = after - before;
  return `${difference > 0 ? '+' : difference < 0 ? '−' : ''}${formatSeconds(Math.abs(difference))}`;
}

function coggingCoverage(label: string, waveform: ComparisonResult['cogging_torque_waveform']): string {
  if (!waveform) return `${label} not recorded`;
  const angles = waveform.electrical_angle_deg;
  return `${label} ${Number(Math.min(...angles).toFixed(3))}–${Number(Math.max(...angles).toFixed(3))}° electrical`;
}

function sameAngleGrid(left: number[], right: number[]): boolean {
  return left.length === right.length && left.every((angle, index) => Math.abs(angle - right[index]) <= 1e-6);
}

function samplingLabel(runs: Array<{ label: string; angles: number[] }>): string {
  const first = runs[0]?.angles || [];
  if (first.length && runs.every(run => sameAngleGrid(first, run.angles))) {
    const step = first.length >= 2 ? first[1] - first[0] : 0;
    return `${first.length} shared positions${step > 0 ? ` · ${step.toFixed(1)}° step` : ''}`;
  }
  return runs.map(run => `${run.label} ${run.angles.length ? `${run.angles.length} positions` : 'not computed'}`).join(' · ');
}

function actualMeshProvenance(result: ComparisonResult): string {
  const metadata = result.solve_metadata;
  return [metadata.mesh_source, metadata.mesher, metadata.mesh_density, metadata.mesh_source_detail]
    .filter((value): value is string => typeof value === 'string' && value.length > 0)
    .join(' · ') || 'Not recorded';
}

function actualTorqueProvenance(result: ComparisonResult): string {
  const metadata = result.solve_metadata;
  const labels: Record<string, string> = { ...COGGING_METHOD_LABELS, remesh_per_step: 'Remesh Per Step', fixed_mesh: 'Fixed Mesh' };
  return [metadata.torque_method, metadata.rotor_rotation_model]
    .filter((value): value is string => typeof value === 'string' && value.length > 0)
    .map(value => labels[value] || value.replace(/_/g, ' '))
    .join(' · ') || 'Not recorded';
}

function excitationProvenance(result: ComparisonResult): string {
  const metadata = result.solve_metadata;
  if (metadata.excitation_mode !== 'ideal_six_step_120') return 'Sinusoidal';
  const advance = typeof metadata.commutation_advance_deg === 'number'
    ? `${metadata.commutation_advance_deg.toFixed(2)}° advance`
    : 'advance not recorded';
  return `Ideal six-step (120°) · ${advance} · ${metadata.phase_connection || 'wye'} · ${metadata.current_amplitude_convention || 'plateau'}`;
}

interface ComparisonColumn extends LoadedRun {
  id: ComparisonSlotId;
  label: string;
  color: string;
  dashArray?: string;
  title: string;
}

export function PublicRunComparison({ currentResult, manageRuns = false, compareWithPrevious = false, onOpenRun }: PublicRunComparisonProps) {
  const currentSaved = currentResult?.saved_run;
  const [allRecords, setAllRecords] = useState<PublicRunListRecord[]>([]);
  const [records, setRecords] = useState<PublicRunListRecord[]>([]);
  const [storage, setStorage] = useState<PublicRunStoragePolicy | null>(null);
  const [selection, setSelection] = useState(() => initialComparisonSelection());
  const selectionContext = useRef<string | null>(null);
  const [loadErrors, setLoadErrors] = useState<Record<string, string>>({});
  const [runsLoaded, setRunsLoaded] = useState(false);
  const [loaded, setLoaded] = useState<Record<string, LoadedRun>>({});
  const comparisonRequests = useRef(new Map<string, Promise<LoadedRun>>());
  const fieldCache = useRef(new Map<string, PublicFieldLinePlot>());
  const [error, setError] = useState<string | null>(null);
  const [managementNotice, setManagementNotice] = useState<string | null>(null);
  const [confirmingDeleteKey, setConfirmingDeleteKey] = useState<string | null>(null);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const [plotChoice, setPlot] = useState<'auto' | 'torque' | 'back-emf' | 'cogging' | 'torque-speed' | 'fields'>('auto');
  const [hiddenSeriesKeys, setHiddenSeriesKeys] = useState<string[]>([]);
  const [envelopeState, setEnvelopeState] = useState<EnvelopeComparisonState>({ limit: 'peak', quantity: 'torque', hidden: [], speed: 0 });
  const [fieldState, setFieldState] = useState<FieldComparisonState>({ position: 'snapshot', source: 'resultant' });

  const refreshRuns = useCallback(async (): Promise<void> => {
    const payload = await listPublicRuns();
    setAllRecords(payload.runs);
    setStorage(payload.storage);
    setRecords(payload.runs.filter((run) => run.status === 'complete' && isMagneto2dRun(run)));
    setRunsLoaded(true);
    setError(null);
  }, []);

  useEffect(() => {
    let active = true;
    void refreshRuns().then(() => {
      if (!active) return;
    }).catch((reason: unknown) => {
      if (active) setError(apiErrorMessage(reason, 'Saved runs could not be listed.'));
    });
    return () => { active = false; };
  }, [refreshRuns]);

  const currentKey = currentSaved ? runKey(currentSaved) : '';
  const currentRecord = records.find(run => runKey(run) === currentKey);
  const previousRecord = currentRecord ? previousCompletedRun(records, currentRecord) : undefined;
  const previousKey = previousRecord ? runKey(previousRecord) : '';

  useEffect(() => {
    if (!runsLoaded) return;
    const context = `${compareWithPrevious}:${currentKey}`;
    const available = new Set(records.map(runKey));
    if (selectionContext.current !== context) {
      selectionContext.current = context;
      const baseline = compareWithPrevious ? previousKey : available.has(currentKey) ? currentKey : records[0] ? runKey(records[0]) : '';
      const candidate = compareWithPrevious ? available.has(currentKey) ? currentKey : '' : records.find(run => runKey(run) !== baseline);
      setSelection(initialComparisonSelection(baseline, typeof candidate === 'string' ? candidate : candidate ? runKey(candidate) : ''));
    } else setSelection(previous => reconcileComparisonSelection(previous, available));
  }, [compareWithPrevious, currentKey, previousKey, records, runsLoaded]);

  const selectedKeys = useMemo(() => selection.slots.map(slot => slot.key).filter(Boolean), [selection]);
  useEffect(() => {
    if (!records.length) return;
    const missing = selectedKeys.filter(key => !loaded[key] && !loadErrors[key])
      .map(key => records.find(record => runKey(record) === key)).filter((record): record is PublicRunListRecord => Boolean(record));
    if (!missing.length) return;
    let active = true;
    void Promise.allSettled(missing.map(record => {
      const key = runKey(record);
      let request = comparisonRequests.current.get(key);
      if (!request) {
        request = loadPublicRunComparison(record.project_slug, record.run_id)
          .then(payload => ({ record, result: payload.result, inputs: payload.inputs, fields: payload.fields }))
          .catch(reason => { comparisonRequests.current.delete(key); throw reason; });
        comparisonRequests.current.set(key, request);
      }
      return request;
    })).then(outcomes => {
      if (!active) return;
      setLoaded(previous => {
        const next = { ...previous };
        let changed = false;
        outcomes.forEach((outcome, index) => {
          if (outcome.status === 'fulfilled') { next[runKey(missing[index])] = outcome.value; changed = true; }
        });
        return changed ? next : previous;
      });
      setLoadErrors(previous => {
        const next = { ...previous };
        outcomes.forEach((outcome, index) => {
          if (outcome.status === 'rejected') next[runKey(missing[index])] = apiErrorMessage(outcome.reason, 'This saved run could not be loaded.');
        });
        return next;
      });
    });
    return () => { active = false; };
  }, [selectedKeys, records, loaded, loadErrors]);

  const deleteRun = async (record: PublicRunListRecord) => {
    const key = runKey(record);
    setDeletingKey(key);
    setManagementNotice(null);
    try {
      const deleted = await deletePublicRun(record.project_slug, record.run_id);
      comparisonRequests.current.delete(key);
      setStorage(deleted.storage);
      setAllRecords((previous) => previous.filter((candidate) => runKey(candidate) !== key));
      setRecords((previous) => previous.filter((candidate) => runKey(candidate) !== key));
      setLoaded((previous) => {
        const next = { ...previous };
        delete next[key];
        return next;
      });
      setConfirmingDeleteKey(null);
      setManagementNotice(`Deleted ${record.project_name || record.project_slug} run ${record.run_id}.`);
      try {
        await refreshRuns();
      } catch {
        setManagementNotice(`Deleted ${record.project_name || record.project_slug} run ${record.run_id}. Refresh Previous runs to recheck the workspace total.`);
      }
    } catch (reason: unknown) {
      setManagementNotice(apiErrorMessage(reason, 'The selected run could not be deleted.'));
    } finally {
      setDeletingKey(null);
    }
  };

  const baselineSlot = selection.slots.find(slot => slot.id === selection.baselineId)!;
  const orderedSlots = [baselineSlot, ...selection.slots.filter(slot => slot.id !== selection.baselineId)];
  const ready = selection.slots.every(slot => slot.key && loaded[slot.key]);
  const runs: ComparisonColumn[] = ready ? orderedSlots.map(slot => ({ ...loaded[slot.key], title: runLabel(loaded[slot.key].record), ...COMPARISON_STYLES.find(style => style.id === slot.id)! })) : [];
  const noPrevious = compareWithPrevious && runsLoaded && !previousKey && !baselineSlot.key;
  const selectionErrors = selection.slots.filter(slot => loadErrors[slot.key]);
  const loadingStatus = error || selectionErrors.length ? null : !runsLoaded ? 'Loading saved runs…'
    : selectedKeys.length === selection.slots.length && !ready ? 'Preparing comparison…' : null;
  const unused = records.find(record => !selectedKeys.includes(runKey(record)));
  const changeSelection = (id: ComparisonSlotId, key: string) => {
    setSelection(previous => selectComparisonRun(previous, id, key));
    setHiddenSeriesKeys([]);
    setEnvelopeState(previous => ({ ...previous, hidden: [] }));
  };
  const torqueSeries = runs.map(run => ({ id: `${run.id}:${runKey(run.record)}`, label: `${run.label} · ${solverLabel(run.result.solve_metadata.solver_name)} · ${run.record.project_name || run.record.project_slug}`,
    angles: run.result.torque_waveform.electrical_angle_deg, values: run.result.torque_waveform.torque_Nm, color: run.color, dashArray: run.dashArray }));
  const emfSeries = runs.flatMap(run => {
    const style = COMPARISON_STYLES.find(style => style.id === run.id)!;
    return (['a', 'b', 'c'] as const).map((phase, index) => ({ id: `${run.id}:${runKey(run.record)}:phase-${phase}`,
      label: `${run.label} · ${solverLabel(run.result.solve_metadata.solver_name)} · Phase ${phase.toUpperCase()}`,
      legendLabel: `Phase ${phase.toUpperCase()}`, groupLabel: `${run.label} · ${solverLabel(run.result.solve_metadata.solver_name)}`,
      angles: run.result.back_emf_waveform.electrical_angle_deg, values: run.result.back_emf_waveform[`phase_${phase}_V`], color: style.phases[index], dashArray: run.dashArray }));
  });
  const coggingSeries = runs.map(run => ({ id: `cogging-${run.id}:${runKey(run.record)}`, label: `${run.label} · ${run.inputs?.run_setup?.name || run.record.project_name || run.record.project_slug}`,
    angles: run.result.cogging_torque_waveform?.electrical_angle_deg || [], values: run.result.cogging_torque_waveform?.torque_Nm || [], color: run.color, dashArray: run.dashArray }));
  const differencesFor = (series: typeof torqueSeries) => series.slice(1).map((item, index) => ({ minuendKey: item.id, subtrahendKey: series[0].id, label: `${runs[index + 1].label} − ${runs[0].label}` }));
  const torqueAvailable = torqueSeries.some(series => series.angles.length >= 2 && series.values.length === series.angles.length);
  const emfAvailable = emfSeries.some(series => series.angles.length >= 2 && series.values.length === series.angles.length);
  const coggingAvailable = coggingSeries.some(series => series.angles.length >= 2 && series.values.length === series.angles.length);
  const automaticPlot = torqueAvailable ? 'torque' : emfAvailable ? 'back-emf' : coggingAvailable ? 'cogging' : 'torque-speed';
  const selectedPlotAvailable = plotChoice === 'torque-speed' || plotChoice === 'fields'
    || (plotChoice === 'torque' && torqueAvailable) || (plotChoice === 'back-emf' && emfAvailable) || (plotChoice === 'cogging' && coggingAvailable);
  const plot = selectedPlotAvailable ? plotChoice : automaticPlot;
  const timing = ready ? compareMultipleTiming(runs.map(run => run.result)) : null;
  const losses = ready ? compareMultipleLosses(runs.map(run => run.result)) : [];
  const dq = compareRunDq(runs.map(run => run.result));
  return (
    <section className="public-run-compare" aria-label="Compare saved runs">
      {manageRuns && (
        <section className="public-run-storage" aria-label="Local run storage">
          <div className="public-run-storage-summary">
            <div>
              <span className="eyebrow">Local run storage</span>
              <strong>{storage ? `${formatBytes(storage.used_bytes)} of ${formatBytes(storage.max_bytes)} used` : 'Checking saved runs…'}</strong>
              <small>
                Saved results stay on this computer and are never removed automatically.
                {storage?.field_playback_keep_latest_per_project
                  ? ` Field playback, most of a run's size, is kept for each design's newest ${storage.field_playback_keep_latest_per_project} runs, and older runs give theirs up first when storage fills; their results and reports stay.`
                  : ''}
              </small>
            </div>
            {storage && (
              <span className={`public-run-storage-state${storage.accepting_new_runs ? '' : ' is-full'}`}>
                {storage.accepting_new_runs ? `${formatBytes(storage.available_bytes)} available` : 'Storage full'}
              </span>
            )}
          </div>
          {storage && (
            <div
              className="public-run-storage-meter"
              role="progressbar"
              aria-label="Saved-run workspace usage"
              aria-valuemin={0}
              aria-valuemax={storage.max_bytes}
              aria-valuenow={Math.min(storage.used_bytes, storage.max_bytes)}
            >
              <i style={{ width: `${Math.min(100, storage.max_bytes > 0 ? storage.used_bytes / storage.max_bytes * 100 : 0)}%` }} />
            </div>
          )}
          {storage && !storage.accepting_new_runs && (
            <div className="public-run-storage-warning" role="alert">
              Delete an older saved or incomplete run below to make room for the next analysis.
            </div>
          )}
          <details className="public-run-storage-manager" open={storage?.accepting_new_runs === false}>
            <summary>Manage stored runs <span>{allRecords.length}</span></summary>
            <div className="public-run-storage-list" role="list">
              {allRecords.length === 0 && <p>No saved or incomplete runs are using this workspace.</p>}
              {allRecords.map((record) => {
                const key = runKey(record);
                const confirming = confirmingDeleteKey === key;
                const deleting = deletingKey === key;
                return (
                  <article className="public-run-storage-row" role="listitem" key={key} data-run-id={record.run_id}>
                    <div>
                      <strong>{record.project_name || record.project_slug}{record.run_setup?.name ? ` · ${record.run_setup.name}` : ''}</strong>
                      <small>{storedRunTime(record)} · {record.run_id}{record.field_playback_removed_at ? ' · field playback removed' : ''}</small>
                    </div>
                    <span className={`public-run-storage-status is-${record.status}`}>{storedRunStatus(record)}</span>
                    <span className="public-run-storage-size">{formatBytes(record.size_bytes)}</span>
                    <div className="public-run-storage-actions">
                      {onOpenRun && record.status === 'complete' && !confirming && (
                        <button type="button" disabled={deletingKey !== null} onClick={() => onOpenRun(record)}>Open results</button>
                      )}
                      {confirming ? (
                        <>
                          <button type="button" className="danger" disabled={deleting} onClick={() => void deleteRun(record)}>{deleting ? 'Deleting…' : 'Delete permanently'}</button>
                          <button type="button" disabled={deleting} onClick={() => setConfirmingDeleteKey(null)}>Cancel</button>
                        </>
                      ) : (
                        <button type="button" title={record.status === 'running' ? 'Cancel the active analysis before deleting its incomplete run.' : undefined} disabled={deletingKey !== null || record.status === 'running'} onClick={() => setConfirmingDeleteKey(key)}>Delete run</button>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          </details>
          {managementNotice && <div className="public-run-storage-notice" role="status">{managementNotice}</div>}
        </section>
      )}
      <div className="public-run-compare-heading">
        <div><span className="eyebrow">Run comparison</span><p>Pin a baseline and compare recorded inputs and results. Each delta is relative to the pinned run.</p></div>
      </div>
      <div className="public-run-compare-selectors" aria-busy={Boolean(loadingStatus)}>
        {selection.slots.map(slot => {
          const style = COMPARISON_STYLES.find(style => style.id === slot.id)!;
          const baseline = slot.id === selection.baselineId;
          return <div key={slot.id} className={`public-run-compare-choice${baseline ? ' is-baseline' : ''}`} data-comparison-slot={slot.id}>
            <label><span style={{ color: style.color }}>{style.label} · {baseline ? 'baseline' : 'candidate'}</span>
              <select value={runsLoaded ? slot.key : ''} disabled={!runsLoaded} onChange={event => changeSelection(slot.id, event.target.value)}>
                {(!runsLoaded || !slot.key) && <option value="">{runsLoaded ? baseline ? 'Choose a baseline' : 'Choose a candidate' : 'Loading saved runs…'}</option>}
                {records.map(record => <option key={runKey(record)} value={runKey(record)} disabled={selection.slots.some(other => other.id !== slot.id && other.key === runKey(record))}>{runLabel(record)}</option>)}
              </select>
            </label>
            <div className="public-run-compare-choice-actions">
              {baseline ? <span className="public-run-compare-pinned">Pinned baseline</span> : <button type="button" disabled={!slot.key || !runsLoaded} onClick={() => setSelection(previous => pinComparisonBaseline(previous, slot.id))} aria-label={`Pin ${style.label} as baseline`}>Pin as baseline</button>}
              <button type="button" disabled={baseline || selection.slots.length <= 2} aria-label={`Remove ${style.label} from comparison`} onClick={() => setSelection(previous => removeComparisonRun(previous, slot.id))}>Remove</button>
            </div>
            {loadErrors[slot.key] && <div className="public-run-compare-load-error" role="alert">{style.label}: {loadErrors[slot.key]} <button type="button" onClick={() => setLoadErrors(previous => { const next = { ...previous }; delete next[slot.key]; return next; })}>Retry {style.label}</button></div>}
          </div>;
        })}
        <div className="public-run-compare-add"><button type="button" disabled={!runsLoaded || selection.slots.length >= 6 || !unused || selectedKeys.length !== selection.slots.length} onClick={() => unused && setSelection(previous => addComparisonRun(previous, runKey(unused)))}>+ Add run</button><span>{selection.slots.length} of 6 runs · baseline stays pinned</span></div>
      </div>
      {error && <div className="public-run-compare-message error" role="alert">{error}</div>}
      {!error && noPrevious && <div className="public-run-compare-message" role="status">{currentRecord
        ? 'No earlier completed Magneto2D run with a recorded completion time was found in this saved project. Choose a baseline manually to compare another run.'
        : 'The current run is no longer available in saved runs. Choose two saved runs manually.'}</div>}
      {!error && runsLoaded && !noPrevious && !baselineSlot.key && selectedKeys.length > 0 && <p className="public-run-compare-message" role="status">Choose a baseline to resume the comparison.</p>}
      {!error && runsLoaded && !compareWithPrevious && records.length < 2 && <div className="public-run-compare-message">Complete one more Magneto2D analysis to compare two runs.</div>}
      {loadingStatus && <div className="public-run-compare-message public-run-compare-loading" role="status" aria-live="polite" aria-atomic="true"><i aria-hidden="true" />{loadingStatus}</div>}
      {ready && <>
        {compareWithPrevious && baselineSlot.key === previousKey && selection.slots.find(slot => slot.id === 'run-b')?.key === currentKey && <p className="public-run-compare-previous-note">Run A is the previous completed run in this saved project. Run B is the result you opened.</p>}
        <RunInputChanges runs={runs.map(run => ({ ...run, details: {
          Design: run.record.project_name || run.record.project_slug,
          'Actual mesh': actualMeshProvenance(run.result), 'Torque extraction': actualTorqueProvenance(run.result),
          'Excitation identity': excitationProvenance(run.result), Completed: formatRunTime(run.record.completed_at, 'Not recorded'),
        } }))} />
        {runs.length > 2 && <p className="public-run-compare-delta-note">Values below include Δ and percentage change from {runs[0].label}, the pinned baseline.</p>}
        <section className="public-run-compare-mode-note design" aria-live="polite">
          <strong>Descriptive run comparison</strong>
          <p>Deltas may come from the motor design, materials, operating point, or numerical setup. They describe change and are not a solver-validation verdict.</p>
        </section>
        <div className={`public-run-compare-metrics${runs.length > 2 ? ' is-multi-run' : ''}`} role="region" aria-label="Run comparison metric differences" tabIndex={0}>
          <table>
            <caption>Results comparison</caption>
            <ComparisonHeader runs={runs} />
            <tbody>{METRICS.filter(metric => !metric.optional || runs.some(run => metric.value(run.result) != null)).map(metric => {
              const values = runs.map(run => metric.value(run.result));
              return <tr key={metric.label}><th scope="row">{metric.label}</th>
                <ComparisonCells runs={runs} values={values.map(value => <>{number(value, metric.torque ? torqueDecimals(value) : metric.digits)} <small>{metric.unit}</small></>)}
                  differences={values.map(value => ({ absolute: <>{delta(values[0], value, metric.torque ? Math.min(torqueDecimals(values[0]), torqueDecimals(value)) : metric.digits)} <small>{metric.deltaUnit || metric.unit}</small></>, percent: percentDelta(values[0], value) }))} />
              </tr>;
            })}</tbody>
          </table>
        </div>
        <div className={`public-run-compare-metrics public-run-compare-dq${runs.length > 2 ? ' is-multi-run' : ''}`} role="region" aria-label="Inductance and d/q comparison" tabIndex={0}>
          <table>
            <caption>Inductance &amp; d/q <InfoTip label="Inductance and d/q comparison help">Recorded values at each run’s operating point. Currents use peak amperes for every run, regardless of the setup’s current units. Ld and Lq are apparent (secant) inductances, with their own output status. Component and inductance deltas require the same recorded d-axis reference and supported conventions.</InfoTip></caption>
            {dq.recorded && <>
              <ComparisonHeader runs={runs} />
              <tbody>
                <tr><th scope="row">D-axis reference</th>{runs.map((run, index) => <td key={run.id} data-run-column={run.id} style={{ color: run.color }}>{dq.references[index]}</td>)}{runs.length === 2 && <><td>—</td><td>—</td></>}</tr>
                {dq.rows.map(row => <tr key={row.key}>
                  <th scope="row" aria-label={row.label}>{row.label}{row.hint && <InfoTip label={`${row.label} help`}>{row.hint}</InfoTip>}</th>
                  <ComparisonCells runs={runs} values={row.cells.map((cell, index) => <DqComparisonValue cell={cell} label={`${runs[index].label} ${row.label}`} unit={row.unit} />)}
                    differences={row.cells.map((cell, index) => ({ absolute: row.comparable[index] ? <>{lossDelta(row.cells[0].value, cell.value, row.unit)} <small>{row.unit}</small></> : '—', percent: row.comparable[index] ? percentDelta(row.cells[0].value, cell.value) : '—' }))} />
                </tr>)}
              </tbody>
            </>}
          </table>
          {!dq.recorded && <p className="public-run-compare-timing-note">Inductance and d/q results were not recorded for the selected runs.</p>}
          {dq.notes.some(Boolean) && <p className="public-run-compare-timing-note" role="note">{dq.notes.map((note, index) => note ? `${runs[index].label}: ${note}` : null).filter(Boolean).join(' ')}</p>}
        </div>
        <div className="public-report-plot-tabs" role="tablist" aria-label="Comparison plots">
          {torqueAvailable && <button type="button" role="tab" aria-selected={plot === 'torque'} className={plot === 'torque' ? 'active' : ''} onClick={() => setPlot('torque')}>Torque overlay</button>}
          {emfAvailable && <button type="button" role="tab" aria-selected={plot === 'back-emf'} className={plot === 'back-emf' ? 'active' : ''} onClick={() => setPlot('back-emf')}>Back EMF overlay</button>}
          {coggingAvailable && <button type="button" role="tab" aria-selected={plot === 'cogging'} className={plot === 'cogging' ? 'active' : ''} onClick={() => setPlot('cogging')}>Cogging overlay</button>}
          <button type="button" role="tab" aria-selected={plot === 'torque-speed'} className={plot === 'torque-speed' ? 'active' : ''} onClick={() => setPlot('torque-speed')}>Torque–speed</button>
          <button type="button" role="tab" aria-selected={plot === 'fields'} className={plot === 'fields' ? 'active' : ''} onClick={() => setPlot('fields')}>Fields</button>
        </div>
        {plot === 'torque-speed' && <RunEnvelopeComparison runs={runs} state={envelopeState} onChange={setEnvelopeState} />}
        {plot === 'fields' && <RunFieldComparison runs={runs} cache={fieldCache.current} state={fieldState} onChange={setFieldState} />}
        {!torqueAvailable && !emfAvailable && !coggingAvailable && plot !== 'torque-speed' && plot !== 'fields' && <p className="public-run-compare-message">{runs.length === 2 ? 'Neither run has torque, Back EMF or cogging waveforms to overlay.' : 'No selected run has torque, Back EMF or cogging waveforms to overlay.'} Available summary metrics are shown above.</p>}
        {plot === 'torque' && torqueAvailable && <WaveformChart angles={torqueSeries[0].angles} series={torqueSeries} label="Torque comparison" unit="N·m" samplingLabel={samplingLabel(runs.map((run, index) => ({ label: run.label, angles: torqueSeries[index].angles })))} toggleableSeries hiddenSeriesKeys={hiddenSeriesKeys} onHiddenSeriesKeysChange={setHiddenSeriesKeys} readoutDifferences={differencesFor(torqueSeries)} />}
        {plot === 'back-emf' && emfAvailable && <WaveformChart angles={emfSeries[0].angles} series={emfSeries} label="Three-phase back EMF comparison" unit="V" samplingLabel={samplingLabel(runs.map(run => ({ label: run.label, angles: run.result.back_emf_waveform.electrical_angle_deg })))} toggleableSeries hiddenSeriesKeys={hiddenSeriesKeys} onHiddenSeriesKeysChange={setHiddenSeriesKeys} />}
        {plot === 'cogging' && coggingAvailable && <>
          <p className="public-run-compare-cogging-coverage">{runs.map(run => coggingCoverage(run.label, run.result.cogging_torque_waveform)).join(' · ')}</p>
          <WaveformChart angles={coggingSeries[0].angles} series={coggingSeries} label="Cogging torque comparison" unit="N·m" samplingLabel={samplingLabel(runs.map((run, index) => ({ label: run.label, angles: coggingSeries[index].angles })))} toggleableSeries hiddenSeriesKeys={hiddenSeriesKeys} onHiddenSeriesKeysChange={setHiddenSeriesKeys} readoutDifferences={differencesFor(coggingSeries)} />
        </>}
        <div className={`public-run-compare-metrics public-run-compare-losses${runs.length > 2 ? ' is-multi-run' : ''}`} role="region" aria-label="Losses and efficiency comparison" tabIndex={0}>
          <table>
            <caption>Losses &amp; efficiency <InfoTip label="Losses comparison help">Values and output statuses come from each saved run. Absolute efficiency changes are in percentage points. Total loss and known loss subtotals use separate rows; partial shaft outputs are compared only with other partial outputs.</InfoTip></caption>
            {losses.length > 0 && <>
              <ComparisonHeader runs={runs} />
              <tbody>{losses.map(row => <tr key={row.key} className={row.indent ? 'public-run-compare-loss-component' : undefined}>
                <th scope="row">{row.label}</th>
                <ComparisonCells runs={runs} values={row.cells.map((cell, index) => <LossComparisonValue cell={cell} label={`${runs[index].label} ${row.label}`} unit={row.unit} />)}
                  differences={row.cells.map((cell, index) => ({ absolute: row.comparable[index] ? <>{lossDelta(row.cells[0].value, cell.value, row.unit)} <small>{row.unit === '%' ? 'pp' : row.unit}</small></> : '—', percent: row.comparable[index] ? percentDelta(row.cells[0].value, cell.value) : '—' }))} />
              </tr>)}</tbody>
            </>}
          </table>
          {!losses.length && <p className="public-run-compare-timing-note">Losses &amp; efficiency were not recorded for {runs.length === 2 ? 'either run' : 'the selected runs'}. Enable Losses &amp; efficiency in Analysis and solve to compare them.</p>}
        </div>
        {timing && <div className={`public-run-compare-metrics public-run-compare-timing${runs.length > 2 ? ' is-multi-run' : ''}`} role="region" aria-label="Solve time breakdown comparison" tabIndex={0}>
          <table>
            <caption>Solve time breakdown <InfoTip label="Solve time breakdown help">Elapsed times for each stage, separate from combined worker time. Mesh and solve counts show how much work each run performed. Changes compare each run with the pinned baseline.</InfoTip></caption>
            <ComparisonHeader runs={runs} label="Stage / workload" />
            {(['Elapsed time', 'Work performed'] as const).map(group => {
              const rows = timing.rows.filter(row => row.group === group);
              return rows.length > 0 && <tbody key={group} aria-label={group}>
                <tr className="public-run-compare-timing-group"><th scope="rowgroup" colSpan={runs.length === 2 ? 5 : runs.length + 1}>{group}</th></tr>
                {rows.map(row => <tr key={row.key}>
                  <th scope="row">{row.label}</th>
                  <ComparisonCells runs={runs} values={row.values.map(value => timingValue(value, row.unit))}
                    differences={row.values.map(value => ({ absolute: timingDelta(row.values[0], value, row.unit), percent: percentDelta(row.values[0], value) }))} />
                </tr>)}
              </tbody>;
            })}
          </table>
          {timing.recorded.some(recorded => !recorded) && <p className="public-run-compare-timing-note" role="note">{timing.recorded.map((recorded, index) => !recorded ? `${runs[index].label}: stage timings were not recorded.` : null).filter(Boolean).join(' ')}</p>}
        </div>}
      </>}
    </section>
  );
}
