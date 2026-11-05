import { useEffect, useState } from 'react';
import type { PublicConnectionStatus } from '../CoilEmWorkspace';
import type { MeshPreview } from '../model';
import { DEFAULT_OUTRUNNER_PROJECT, normalizeOutrunnerProject, parseOutrunnerProject, sameOutrunnerProject, type OutrunnerProject } from './project';
import { OutrunnerWorkflow } from './OutrunnerWorkflow';
import type { ReferencePreview } from './geometry';
import type { Analysis, RunEstimate, RunState } from './types';
import { outrunnerRequest as api } from './api';
import './outrunner.css';

export function OutrunnerWorkspace({ initialProject, onHome, onOpenOtherDesign, connectionStatus, appVersion }: {
  initialProject: OutrunnerProject; onHome: () => void; onOpenOtherDesign?: (file: File) => void;
  connectionStatus?: PublicConnectionStatus; appVersion?: string | null;
}) {
  const [project, setProject] = useState(() => normalizeOutrunnerProject(initialProject));
  const [geometry, setGeometry] = useState<ReferencePreview | null>(null);
  const [analysis, setAnalysis] = useState<Analysis>('both');
  const [run, setRun] = useState<RunState | null>(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [mesh, setMesh] = useState<MeshPreview | null>(null);
  const [meshBusy, setMeshBusy] = useState(false);
  const [meshError, setMeshError] = useState('');
  const [estimate, setEstimate] = useState<RunEstimate | null>(null);
  const busy = starting || run?.status === 'QUEUED' || run?.status === 'RUNNING';
  const jobKey = `coilem.outrunner.run:${project.fixture_id}`;
  const meshKey = JSON.stringify([project.fixture_asset_sha256, project.analysis.mesh_policy, project.analysis.gap_size_mm, project.analysis.bulk_size_mm]);

  useEffect(() => {
    let cancelled = false;
    setGeometry(null);
    api<ReferencePreview>('/preview', project).then((value) => { if (!cancelled) { setGeometry(value); setError(''); } })
      .catch((failure) => { if (!cancelled) setError(`The local experimental workspace is unavailable: ${String(failure.message)}`); });
    return () => { cancelled = true; };
  }, [project.fixture_data]);

  useEffect(() => {
    const abort = new AbortController();
    setMesh(null); setMeshBusy(true); setMeshError('');
    void api<MeshPreview>('/mesh-preview', project, abort.signal).then((value) => { if (!abort.signal.aborted) setMesh(value); })
      .catch((failure) => { if (!abort.signal.aborted) setMeshError(failure.message); })
      .finally(() => { if (!abort.signal.aborted) setMeshBusy(false); });
    return () => abort.abort();
  }, [meshKey]);

  useEffect(() => {
    const abort = new AbortController();
    void api<RunEstimate>('/estimate', { project, analysis }, abort.signal).then(setEstimate)
      .catch((failure) => { if (!abort.signal.aborted) setError(failure.message); });
    return () => abort.abort();
  }, [project.analysis, analysis]);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(jobKey) || 'null');
      if (saved && sameOutrunnerProject(saved.project, project)) {
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
    const changesMesh = ['unique_samples', 'gap_size_mm', 'bulk_size_mm', 'nonlinear_tolerance'].some((key) => key in update);
    setProject((previous) => ({ ...previous, analysis: { ...previous.analysis, ...update,
      ...(changesMesh && !update.accuracy_plan ? { accuracy_plan: 'custom' as const } : {}) } }));
    setRun(null);
  };
  return <OutrunnerWorkflow project={project} geometry={geometry} analysis={analysis} run={run} busy={Boolean(busy)} error={error}
    mesh={mesh} meshBusy={meshBusy} meshError={meshError} estimate={estimate}
    appVersion={appVersion} connectionStatus={connectionStatus} onHome={onHome} onOpenFile={(file) => void openFile(file)}
    onReset={() => { if (!busy) { setProject(DEFAULT_OUTRUNNER_PROJECT); setRun(null); } }}
    onStart={() => void start()} onResume={() => void start(true)}
    onCancel={() => { if (run) void api<RunState>(`/runs/${run.run_id}/cancel`, {}).then(setRun).catch((failure) => setError(failure.message)); }}
    onAnalysisChange={(value) => { setAnalysis(value); setRun(null); }} onUpdateAnalysis={updateAnalysis} />;
}
