import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  deletePublicRun,
  listPublicRuns,
  loadPublicRunComparison,
  type PublicRunListRecord,
  type PublicRunStoragePolicy,
} from './api';
import type { SolveResult } from './model';
import { WaveformChart } from './WaveformChart';

interface LoadedRun {
  record: PublicRunListRecord;
  result: SolveResult;
}

interface PublicRunComparisonProps {
  currentResult?: SolveResult | null;
  manageRuns?: boolean;
}

const METRICS: Array<{
  label: string;
  unit: string;
  deltaUnit?: string;
  digits?: number;
  value: (result: SolveResult) => number | null | undefined;
}> = [
  { label: 'Average torque', unit: 'N·m', value: (run) => run.summary.avg_torque_Nm },
  { label: 'Torque ripple', unit: '%', deltaUnit: 'pp', value: (run) => run.summary.torque_ripple_pct },
  { label: 'Back EMF', unit: 'V', value: (run) => run.summary.back_emf_fundamental_V },
  { label: 'Peak tooth B', unit: 'T', value: (run) => run.summary.peak_flux_density_teeth_T },
  { label: 'Peak yoke B', unit: 'T', value: (run) => run.summary.peak_flux_density_yoke_T },
  { label: 'Torque constant', unit: 'N·m/A', value: (run) => run.summary.Kt_Nm_per_A },
  { label: 'Back EMF THD (headline)', unit: '%', deltaUnit: 'pp', value: (run) => run.summary.back_emf_thd_pct },
  { label: 'Solve time', unit: 's', digits: 1, value: (run) => run.summary.solve_time_s },
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

function runLabel(run: PublicRunListRecord): string {
  const name = run.project_name || run.project_slug;
  const timestamp = run.completed_at ? new Date(run.completed_at).toLocaleString() : run.run_id;
  return `${name} · ${solverLabel(run.solver_name)} · ${timestamp}`;
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
  const timestamp = run.completed_at || run.started_at;
  return timestamp ? new Date(timestamp).toLocaleString() : run.run_id;
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

function percentDelta(left: number | null | undefined, right: number | null | undefined): string {
  if (typeof left !== 'number' || typeof right !== 'number' || !Number.isFinite(left) || !Number.isFinite(right)) return '—';
  const difference = right - left;
  if (Math.abs(left) <= 1e-12) return Math.abs(difference) <= 1e-12 ? '0.0%' : '—';
  const percentage = difference / Math.abs(left) * 100;
  const rounded = Number(percentage.toFixed(1));
  return `${rounded > 0 ? '+' : ''}${rounded.toFixed(1)}%`;
}

function sameAngleGrid(left: number[], right: number[]): boolean {
  return left.length === right.length && left.every((angle, index) => Math.abs(angle - right[index]) <= 1e-6);
}

function samplingLabel(left: number[], right: number[]): string {
  if (!sameAngleGrid(left, right)) return `Run A ${left.length} · Run B ${right.length} positions`;
  const step = left.length >= 2 ? left[1] - left[0] : 0;
  return `${left.length} shared positions${step > 0 ? ` · ${step.toFixed(1)}° step` : ''}`;
}

function actualMeshProvenance(result: SolveResult): string {
  const metadata = result.solve_metadata;
  return [metadata.mesh_source, metadata.mesher, metadata.mesh_density, metadata.mesh_source_detail]
    .filter((value): value is string => typeof value === 'string' && value.length > 0)
    .join(' · ') || 'Not recorded';
}

function actualTorqueProvenance(result: SolveResult): string {
  const metadata = result.solve_metadata;
  return [metadata.torque_method, metadata.rotor_rotation_model]
    .filter((value): value is string => typeof value === 'string' && value.length > 0)
    .join(' · ') || 'Not recorded';
}

function excitationProvenance(result: SolveResult): string {
  const metadata = result.solve_metadata;
  if (metadata.excitation_mode !== 'ideal_six_step_120') return 'Sinusoidal';
  const advance = typeof metadata.commutation_advance_deg === 'number'
    ? `${metadata.commutation_advance_deg.toFixed(2)}° advance`
    : 'advance not recorded';
  return `Ideal six-step (120°) · ${advance} · ${metadata.phase_connection || 'wye'} · ${metadata.current_amplitude_convention || 'plateau'}`;
}

export function PublicRunComparison({ currentResult, manageRuns = false }: PublicRunComparisonProps) {
  const currentSaved = currentResult?.saved_run;
  const [allRecords, setAllRecords] = useState<PublicRunListRecord[]>([]);
  const [records, setRecords] = useState<PublicRunListRecord[]>([]);
  const [storage, setStorage] = useState<PublicRunStoragePolicy | null>(null);
  const [leftKey, setLeftKey] = useState(currentSaved ? runKey(currentSaved) : '');
  const [rightKey, setRightKey] = useState('');
  const [loaded, setLoaded] = useState<Record<string, LoadedRun>>({});
  const [error, setError] = useState<string | null>(null);
  const [managementNotice, setManagementNotice] = useState<string | null>(null);
  const [confirmingDeleteKey, setConfirmingDeleteKey] = useState<string | null>(null);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const [plot, setPlot] = useState<'torque' | 'back-emf'>('torque');
  const [hiddenSeriesKeys, setHiddenSeriesKeys] = useState<string[]>([]);

  const refreshRuns = useCallback(async (): Promise<void> => {
    const payload = await listPublicRuns();
    setAllRecords(payload.runs);
    setStorage(payload.storage);
    setRecords(payload.runs.filter((run) => run.status === 'complete' && isMagneto2dRun(run)));
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

  useEffect(() => {
    const keys = new Set(records.map(runKey));
    const currentKey = currentSaved ? runKey(currentSaved) : '';
    const nextLeft = keys.has(leftKey)
      ? leftKey
      : keys.has(currentKey)
        ? currentKey
        : runKey(records[0] || { project_slug: '', run_id: '' });
    const nextRight = keys.has(rightKey) && rightKey !== nextLeft
      ? rightKey
      : runKey(records.find((run) => runKey(run) !== nextLeft) || { project_slug: '', run_id: '' });
    if (nextLeft !== leftKey) setLeftKey(nextLeft);
    if (nextRight !== rightKey) setRightKey(nextRight);
  }, [currentSaved, leftKey, records, rightKey]);

  useEffect(() => {
    if (!records.length) return;
    const missing = [...new Set([leftKey, rightKey])]
      .filter((key) => key && !loaded[key])
      .map((key) => records.find((candidate) => runKey(candidate) === key))
      .filter((record): record is PublicRunListRecord => Boolean(record));
    if (!missing.length) return;
    let active = true;
    void Promise.all(missing.map(async (record) => {
      const payload = await loadPublicRunComparison(record.project_slug, record.run_id);
      return {
        key: runKey(record),
        value: {
          record,
          result: payload.result,
        },
      };
    })).then((entries) => {
      if (!active) return;
      setLoaded((previous) => {
        const next = { ...previous };
        let changed = false;
        entries.forEach((entry) => {
          if (!previous[entry.key]) {
            next[entry.key] = entry.value;
            changed = true;
          }
        });
        return changed ? next : previous;
      });
      setError(null);
    }).catch((reason: unknown) => {
      if (active) setError(apiErrorMessage(reason, 'A saved run could not be loaded.'));
    });
    return () => { active = false; };
  }, [leftKey, rightKey, records, loaded]);

  const deleteRun = async (record: PublicRunListRecord) => {
    const key = runKey(record);
    setDeletingKey(key);
    setManagementNotice(null);
    try {
      const deleted = await deletePublicRun(record.project_slug, record.run_id);
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

  const left = loaded[leftKey];
  const right = loaded[rightKey];
  const ready = Boolean(left && right && leftKey !== rightKey);
  const torqueSeries = useMemo(() => ready ? [
    {
      id: 'run-a',
      label: `Run A · ${solverLabel(left.result.solve_metadata.solver_name)} · ${left.record.project_name || left.record.project_slug}`,
      angles: left.result.torque_waveform.electrical_angle_deg,
      values: left.result.torque_waveform.torque_Nm,
      color: '#f59e0b',
    },
    {
      id: 'run-b',
      label: `Run B · ${solverLabel(right.result.solve_metadata.solver_name)} · ${right.record.project_name || right.record.project_slug}`,
      angles: right.result.torque_waveform.electrical_angle_deg,
      values: right.result.torque_waveform.torque_Nm,
      color: '#22d3ee',
    },
  ] : [], [ready, left, right]);
  const emfSeries = useMemo(() => ready ? [
    {
      id: 'run-a-phase-a',
      label: `Run A · ${solverLabel(left.result.solve_metadata.solver_name)} · Phase A`,
      legendLabel: 'Phase A',
      groupLabel: `Run A · ${solverLabel(left.result.solve_metadata.solver_name)}`,
      angles: left.result.back_emf_waveform.electrical_angle_deg,
      values: left.result.back_emf_waveform.phase_a_V,
      color: '#f59e0b',
    },
    {
      id: 'run-a-phase-b',
      label: `Run A · ${solverLabel(left.result.solve_metadata.solver_name)} · Phase B`,
      legendLabel: 'Phase B',
      groupLabel: `Run A · ${solverLabel(left.result.solve_metadata.solver_name)}`,
      angles: left.result.back_emf_waveform.electrical_angle_deg,
      values: left.result.back_emf_waveform.phase_b_V,
      color: '#fb7185',
    },
    {
      id: 'run-a-phase-c',
      label: `Run A · ${solverLabel(left.result.solve_metadata.solver_name)} · Phase C`,
      legendLabel: 'Phase C',
      groupLabel: `Run A · ${solverLabel(left.result.solve_metadata.solver_name)}`,
      angles: left.result.back_emf_waveform.electrical_angle_deg,
      values: left.result.back_emf_waveform.phase_c_V,
      color: '#facc15',
    },
    {
      id: 'run-b-phase-a',
      label: `Run B · ${solverLabel(right.result.solve_metadata.solver_name)} · Phase A`,
      legendLabel: 'Phase A',
      groupLabel: `Run B · ${solverLabel(right.result.solve_metadata.solver_name)}`,
      angles: right.result.back_emf_waveform.electrical_angle_deg,
      values: right.result.back_emf_waveform.phase_a_V,
      color: '#22d3ee',
    },
    {
      id: 'run-b-phase-b',
      label: `Run B · ${solverLabel(right.result.solve_metadata.solver_name)} · Phase B`,
      legendLabel: 'Phase B',
      groupLabel: `Run B · ${solverLabel(right.result.solve_metadata.solver_name)}`,
      angles: right.result.back_emf_waveform.electrical_angle_deg,
      values: right.result.back_emf_waveform.phase_b_V,
      color: '#60a5fa',
    },
    {
      id: 'run-b-phase-c',
      label: `Run B · ${solverLabel(right.result.solve_metadata.solver_name)} · Phase C`,
      legendLabel: 'Phase C',
      groupLabel: `Run B · ${solverLabel(right.result.solve_metadata.solver_name)}`,
      angles: right.result.back_emf_waveform.electrical_angle_deg,
      values: right.result.back_emf_waveform.phase_c_V,
      color: '#2dd4bf',
    },
  ] : [], [ready, left, right]);
  const torqueSampling = ready ? samplingLabel(
    left.result.torque_waveform.electrical_angle_deg,
    right.result.torque_waveform.electrical_angle_deg,
  ) : '';
  const emfSampling = ready ? samplingLabel(
    left.result.back_emf_waveform.electrical_angle_deg,
    right.result.back_emf_waveform.electrical_angle_deg,
  ) : '';
  return (
    <section className="public-run-compare" aria-label="Compare two saved runs">
      {manageRuns && (
        <section className="public-run-storage" aria-label="Local run storage">
          <div className="public-run-storage-summary">
            <div>
              <span className="eyebrow">Local run storage</span>
              <strong>{storage ? `${formatBytes(storage.used_bytes)} of ${formatBytes(storage.max_bytes)} used` : 'Checking saved runs…'}</strong>
              <small>Saved results stay on this computer and are never removed automatically.</small>
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
                      <strong>{record.project_name || record.project_slug}</strong>
                      <small>{storedRunTime(record)} · {record.run_id}</small>
                    </div>
                    <span className={`public-run-storage-status is-${record.status}`}>{storedRunStatus(record)}</span>
                    <span className="public-run-storage-size">{formatBytes(record.size_bytes)}</span>
                    <div className="public-run-storage-actions">
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
        <div><span className="eyebrow">Run comparison</span><h2>Compare two completed Magneto2D analyses</h2><p>Review how design inputs, operating points, or numerical settings changed the saved results.</p></div>
        <div className="public-run-compare-legend"><span><i className="run-a" />Run A</span><span><i className="run-b" />Run B</span></div>
      </div>
      <div className="public-run-compare-selectors">
        <label><span>Run A · baseline</span><select value={leftKey} onChange={(event) => setLeftKey(event.target.value)}>{records.map((run) => <option key={runKey(run)} value={runKey(run)} disabled={runKey(run) === rightKey}>{runLabel(run)}</option>)}</select></label>
        <label><span>Run B · candidate</span><select value={rightKey} onChange={(event) => setRightKey(event.target.value)}>{records.map((run) => <option key={runKey(run)} value={runKey(run)} disabled={runKey(run) === leftKey}>{runLabel(run)}</option>)}</select></label>
      </div>
      {error && <div className="public-run-compare-message error" role="alert">{error}</div>}
      {!error && records.length < 2 && <div className="public-run-compare-message">Complete one more Magneto2D analysis to compare two runs.</div>}
      {!error && records.length >= 2 && !ready && <div className="public-run-compare-message">Loading saved run data…</div>}
      {ready && <>
        <div className="public-run-compare-identities" aria-label="Compared run identity and provenance">
          {[
            { key: 'run-a', side: 'Run A · baseline', run: left },
            { key: 'run-b', side: 'Run B · candidate', run: right },
          ].map(({ key, side, run }) => (
            <article className={key} key={key}>
              <span>{side}</span>
              <strong>{solverLabel(run.result.solve_metadata.solver_name)}</strong>
              <small>{run.record.project_name || run.record.project_slug}</small>
              <dl>
                <div><dt>Actual mesh</dt><dd>{actualMeshProvenance(run.result)}</dd></div>
                <div><dt>Torque extraction</dt><dd>{actualTorqueProvenance(run.result)}</dd></div>
                <div><dt>Excitation identity</dt><dd>{excitationProvenance(run.result)}</dd></div>
                <div><dt>Completed</dt><dd>{run.record.completed_at ? new Date(run.record.completed_at).toLocaleString() : 'Not recorded'}</dd></div>
              </dl>
            </article>
          ))}
        </div>
        <section className="public-run-compare-mode-note design" aria-live="polite">
          <strong>Descriptive run comparison</strong>
          <p>Deltas may come from the motor design, materials, operating point, or numerical setup. They describe change and are not a solver-validation verdict.</p>
        </section>
        <div className="public-run-compare-metrics" aria-label="Run comparison metric differences">
          {METRICS.map((metric) => {
            const leftValue = metric.value(left.result);
            const rightValue = metric.value(right.result);
            return <article key={metric.label}><span>{metric.label}</span><div><strong>{number(leftValue, metric.digits)} <small>{metric.unit}</small></strong><strong>{number(rightValue, metric.digits)} <small>{metric.unit}</small></strong></div><em><span>{delta(leftValue, rightValue, metric.digits)} {metric.deltaUnit || metric.unit}</span><span>{percentDelta(leftValue, rightValue)} vs A</span></em></article>;
          })}
        </div>
        <div className="public-report-plot-tabs" role="tablist" aria-label="Comparison plots">
          <button type="button" role="tab" aria-selected={plot === 'torque'} className={plot === 'torque' ? 'active' : ''} onClick={() => setPlot('torque')}>Torque overlay</button>
          <button type="button" role="tab" aria-selected={plot === 'back-emf'} className={plot === 'back-emf' ? 'active' : ''} onClick={() => setPlot('back-emf')}>Back EMF overlay</button>
        </div>
        {plot === 'torque' && <WaveformChart angles={left.result.torque_waveform.electrical_angle_deg} series={torqueSeries} label="Torque comparison" unit="N·m" samplingLabel={torqueSampling} toggleableSeries hiddenSeriesKeys={hiddenSeriesKeys} onHiddenSeriesKeysChange={setHiddenSeriesKeys} />}
        {plot === 'back-emf' && <WaveformChart angles={left.result.back_emf_waveform.electrical_angle_deg} series={emfSeries} label="Three-phase back EMF comparison" unit="V" samplingLabel={emfSampling} toggleableSeries hiddenSeriesKeys={hiddenSeriesKeys} onHiddenSeriesKeysChange={setHiddenSeriesKeys} />}
      </>}
    </section>
  );
}
