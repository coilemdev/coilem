import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { deletePublicRun, listPublicRuns, type PublicRunListRecord, type PublicRunStoragePolicy } from './api';
import { InfoTip } from './Popover';
import {
  RUNS_CHANGED_EVENT, formatBytes, formatRunTime, runClock, runDesigns, runDuration, runKey, runName, runResults, runSetupLine,
  runsByDay, unfinishedRunLabel,
} from './runRecords';

interface PublicRunHistoryProps {
  /** Opens a completed run's stored result in Results. Resolves to null once shown, or to why it could not be. */
  onOpenRun?: (run: PublicRunListRecord) => Promise<string | null>;
}

function errorMessage(reason: unknown, fallback: string): string {
  if (reason && typeof reason === 'object' && 'message' in reason) return String((reason as { message: unknown }).message);
  return reason instanceof Error ? reason.message : fallback;
}

/** Every saved run, newest first: what it was, what it gave, and one click to open it. */
export function PublicRunHistory({ onOpenRun }: PublicRunHistoryProps) {
  const [records, setRecords] = useState<PublicRunListRecord[] | null>(null);
  const [storage, setStorage] = useState<PublicRunStoragePolicy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [design, setDesign] = useState<string | null>(null);
  const [confirmingKey, setConfirmingKey] = useState<string | null>(null);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const [opening, setOpening] = useState<PublicRunListRecord | null>(null);
  const [openProblem, setOpenProblem] = useState<string | null>(null);
  const mounted = useRef(true);
  // Set on mount as well as cleared on unmount: a development double-mount would otherwise leave it false.
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const refresh = useCallback(async () => {
    const payload = await listPublicRuns();
    setRecords(payload.runs);
    setStorage(payload.storage);
    setError(null);
  }, []);
  useEffect(() => {
    let active = true;
    refresh().catch((reason: unknown) => { if (active) setError(errorMessage(reason, 'Saved runs could not be listed.')); });
    return () => { active = false; };
  }, [refresh]);

  const designs = useMemo(() => runDesigns(records ?? []), [records]);
  // A filter whose last run was deleted falls back to every design.
  const shownDesign = design !== null && designs.some((row) => row.key === design) ? design : null;
  const days = useMemo(() => runsByDay((records ?? []).filter((run) => shownDesign === null || run.project_slug === shownDesign)), [records, shownDesign]);

  const deleteRun = async (record: PublicRunListRecord) => {
    const key = runKey(record);
    setDeletingKey(key);
    setNotice(null);
    try {
      const deleted = await deletePublicRun(record.project_slug, record.run_id);
      setStorage(deleted.storage);
      setRecords((previous) => (previous ?? []).filter((candidate) => runKey(candidate) !== key));
      setConfirmingKey(null);
      setNotice(`Deleted the ${runName(record)} run of ${formatRunTime(record.completed_at || record.started_at, record.run_id)}.`);
      window.dispatchEvent(new Event(RUNS_CHANGED_EVENT));
      await refresh().catch(() => undefined);
    } catch (reason: unknown) {
      setNotice(errorMessage(reason, 'The run could not be deleted.'));
    } finally {
      setDeletingKey(null);
    }
  };

  const open = async (record: PublicRunListRecord) => {
    if (!onOpenRun || opening) return;
    setOpening(record);
    setNotice(null);
    setOpenProblem(null);
    const problem = await onOpenRun(record).catch((reason: unknown) => errorMessage(reason, 'The run could not be opened.'));
    if (!mounted.current) return;
    setOpening(null);
    setOpenProblem(problem);
  };
  const busy = deletingKey !== null || opening !== null;

  const used = storage && storage.max_bytes > 0 ? Math.min(100, storage.used_bytes / storage.max_bytes * 100) : 0;
  return (
    <section className="run-history" aria-label="Saved runs">
      <div className="run-history-bar">
        <div className="run-history-filter" role="group" aria-label="Show runs of">
          {designs.length > 1 && <>
            <button type="button" aria-pressed={shownDesign === null} onClick={() => setDesign(null)}>All <span>{records?.length ?? 0}</span></button>
            {designs.map((row) => (
              <button key={row.key} type="button" aria-pressed={shownDesign === row.key} onClick={() => setDesign(row.key)}>{row.name} <span>{row.count}</span></button>
            ))}
          </>}
        </div>
        {storage && (
          <div className={`run-history-storage${storage.accepting_new_runs ? '' : ' is-full'}`}>
            <span>{formatBytes(storage.used_bytes)} of {formatBytes(storage.max_bytes)} used</span>
            <div className="run-history-meter" role="progressbar" aria-label="Saved-run storage used" aria-valuemin={0}
              aria-valuemax={storage.max_bytes} aria-valuenow={Math.min(storage.used_bytes, storage.max_bytes)}><i style={{ width: `${used}%` }} /></div>
            <InfoTip label="About saved-run storage" align="end">
              <p>Saved results stay on this computer and are never removed automatically.</p>
              {storage.field_playback_keep_latest_per_project ? <p>Field playback is most of a run&apos;s size. It is kept for each design&apos;s newest {storage.field_playback_keep_latest_per_project} runs; older runs give theirs up first when storage fills, and keep their results and reports.</p> : null}
            </InfoTip>
          </div>
        )}
      </div>
      {storage && !storage.accepting_new_runs && (
        <div className="run-history-warning" role="alert">Storage is full. Delete a run below to make room for the next analysis.</div>
      )}
      {error && <div className="run-history-warning" role="alert">{error}</div>}
      {openProblem && <div className="run-history-warning" role="alert">{openProblem}</div>}
      {opening && (
        <div className="run-history-opening" role="status">
          <i aria-hidden="true" />Loading the {runName(opening)} run of {runClock(opening)}…
        </div>
      )}
      {notice && <div className="run-history-notice" role="status">{notice}</div>}
      {records === null && !error && <p className="run-history-empty" role="status">Loading saved runs…</p>}
      {records !== null && records.length === 0 && (
        <p className="run-history-empty">No runs yet. Run an analysis and it is saved here.</p>
      )}
      {days.length > 0 && (
        <table className="run-history-table">
          <thead>
            <tr>
              <th scope="col">Time</th><th scope="col">Run</th>
              <th scope="col" className="is-number">Torque</th><th scope="col" className="is-number">Efficiency</th>
              <th scope="col" className="is-number is-extra">Back EMF</th><th scope="col" className="is-number is-extra">Size</th>
              <th scope="col"><span className="public-visually-hidden">Actions</span></th>
            </tr>
          </thead>
          {days.map((day) => (
            <tbody key={day.label}>
              <tr className="run-history-day"><th colSpan={7} scope="rowgroup">{day.label}</th></tr>
              {day.runs.map((record) => {
                const key = runKey(record);
                const confirming = confirmingKey === key;
                const deleting = deletingKey === key;
                const unfinished = unfinishedRunLabel(record);
                const canOpen = Boolean(onOpenRun) && record.status === 'complete';
                const isOpening = opening !== null && runKey(opening) === key;
                const duration = runDuration(record);
                const results = runResults(record);
                return (
                  <tr key={key} className={`run-history-row${canOpen && !busy ? ' is-openable' : ''}${unfinished ? ' is-unfinished' : ''}${isOpening ? ' is-opening' : ''}`} data-run-id={record.run_id}
                    title={`Run ${record.run_id}`}
                    onClick={canOpen && !confirming && !busy ? (event) => {
                      // The row opens the run; its own buttons keep their meaning.
                      if (!(event.target as HTMLElement).closest('button')) void open(record);
                    } : undefined}>
                    <td className="run-history-when"><strong>{runClock(record)}</strong>{duration && <small>{duration}</small>}</td>
                    <td className="run-history-what">
                      <strong><b>{runName(record)}</b>{record.run_setup?.name ? <span className="run-history-setup">{record.run_setup.name}</span> : null}
                        {unfinished && <span className={`run-history-status is-${record.status}`}>{unfinished}</span>}</strong>
                      <small>{runSetupLine(record) || (unfinished ? 'No result was saved.' : 'Setup not recorded')}</small>
                    </td>
                    <td className="is-number">{results.torque ?? <i>—</i>}</td>
                    <td className="is-number">{results.efficiency ?? <i>—</i>}</td>
                    <td className="is-number is-extra">{results.backEmf ?? <i>—</i>}</td>
                    <td className="is-number is-extra run-history-size">{formatBytes(record.size_bytes)}{record.field_playback_removed_at ? <small>playback removed</small> : null}</td>
                    <td className="run-history-actions">
                      <div>
                        {confirming ? <>
                          <button type="button" className="danger" disabled={deleting} onClick={() => void deleteRun(record)}>{deleting ? 'Deleting…' : 'Delete permanently'}</button>
                          <button type="button" disabled={deleting} onClick={() => setConfirmingKey(null)}>Cancel</button>
                        </> : <>
                          {canOpen && <button type="button" className="primary" disabled={busy} onClick={() => void open(record)}>{isOpening ? 'Loading…' : 'Open results'}</button>}
                          <button type="button" className="quiet" aria-label="Delete run"
                            title={record.status === 'running' ? 'Cancel the active analysis before deleting its run.' : 'Delete this run'}
                            disabled={busy || record.status === 'running'} onClick={() => setConfirmingKey(key)}>Delete</button>
                        </>}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          ))}
        </table>
      )}
      {records !== null && records.length > 0 && (
        <p className="run-history-hint">To compare runs, open one and choose <b>Compare runs</b> in Results.</p>
      )}
    </section>
  );
}
