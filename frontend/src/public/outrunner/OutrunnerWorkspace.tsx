import { useEffect, useState } from 'react';
import { PUBLIC_API_BASE } from '../api';
import type { PublicConnectionStatus } from '../CoilEmWorkspace';
import { DEFAULT_OUTRUNNER_PROJECT, parseOutrunnerProject, type OutrunnerProject } from './project';
import { OutrunnerWorkflow } from './OutrunnerWorkflow';
import type { ReferencePreview } from './geometry';
import type { Analysis, RunState } from './types';
import './outrunner.css';

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${PUBLIC_API_BASE}/experimental/outrunner${path}`, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === 'string' ? data.detail
      : Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail?.message;
    throw new Error(String(message || `Local analysis request failed (${response.status}).`).slice(0, 500));
  }
  return data as T;
}

export function OutrunnerWorkspace({ initialProject, onHome, onOpenOtherDesign, connectionStatus, appVersion }: {
  initialProject: OutrunnerProject; onHome: () => void; onOpenOtherDesign?: (file: File) => void;
  connectionStatus?: PublicConnectionStatus; appVersion?: string | null;
}) {
  const [project, setProject] = useState(initialProject);
  const [geometry, setGeometry] = useState<ReferencePreview | null>(null);
  const [analysis, setAnalysis] = useState<Analysis>('both');
  const [run, setRun] = useState<RunState | null>(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const busy = starting || run?.status === 'QUEUED' || run?.status === 'RUNNING';
  const jobKey = `coilem.outrunner.run:${project.fixture_id}`;

  useEffect(() => {
    let cancelled = false;
    setGeometry(null);
    api<ReferencePreview>('/preview', project).then((value) => { if (!cancelled) { setGeometry(value); setError(''); } })
      .catch((failure) => { if (!cancelled) setError(`The local experimental workspace is unavailable: ${String(failure.message)}`); });
    return () => { cancelled = true; };
  }, [project]);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(jobKey) || 'null');
      if (saved && JSON.stringify(saved.project) === JSON.stringify(project)) {
        setAnalysis(saved.analysis);
        api<RunState>(`/runs/${saved.run_id}`).then(setRun).catch(() => undefined);
      }
    } catch { /* A stale local record does not alter the opened design. */ }
  }, []);

  useEffect(() => {
    if (!run || !['QUEUED', 'RUNNING'].includes(run.status)) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      api<RunState>(`/runs/${run.run_id}`).then((value) => { if (!stopped) setRun(value); })
        .catch((failure) => { if (!stopped) setError(failure.message); });
    }, 1500);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [run?.run_id, run?.status]);

  const start = async (resume = false) => {
    setStarting(true); setError('');
    try {
      const value = await api<RunState>(resume && run ? `/runs/${run.run_id}/resume` : '/runs', { project, analysis });
      localStorage.setItem(jobKey, JSON.stringify({ run_id: value.run_id, project, analysis }));
      setRun(value);
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setStarting(false); }
  };

  const openFile = async (file: File) => {
    try {
      if (busy) throw new Error('Finish or cancel the running analysis before opening another design.');
      const value = parseOutrunnerProject(await file.text());
      if (!value) {
        onOpenOtherDesign?.(file);
        return;
      }
      setProject(value); setRun(null); setError('');
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
  };
  const updateAnalysis = (update: Partial<OutrunnerProject['analysis']>) => {
    setProject((previous) => ({ ...previous, analysis: { ...previous.analysis, ...update } }));
    setRun(null);
  };
  return <OutrunnerWorkflow project={project} geometry={geometry} analysis={analysis} run={run} busy={Boolean(busy)} error={error}
    appVersion={appVersion} connectionStatus={connectionStatus} onHome={onHome} onOpenFile={(file) => void openFile(file)}
    onReset={() => { if (!busy) { setProject(DEFAULT_OUTRUNNER_PROJECT); setRun(null); } }}
    onStart={() => void start()} onResume={() => void start(true)}
    onCancel={() => { if (run) void api<RunState>(`/runs/${run.run_id}/cancel`, {}).then(setRun).catch((failure) => setError(failure.message)); }}
    onAnalysisChange={(value) => { setAnalysis(value); setRun(null); }} onUpdateAnalysis={updateAnalysis} />;
}
