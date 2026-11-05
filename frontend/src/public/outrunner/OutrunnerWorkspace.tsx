import { useEffect, useRef, useState } from 'react';
import { PUBLIC_API_BASE } from '../api';
import { WaveformChart } from '../WaveformChart';
import { downloadReferenceFile, parseOutrunnerProject, type OutrunnerProject } from './project';
import './outrunner.css';

interface Region { id: string; kind: string; loops: number[][][]; phase: string; signed_turns: number; material: string }
interface Preview { regions: Region[] }
interface Curve {
  angles_electrical_deg: number[];
  torque_Nm: number[];
  phase_linkage_Wb: number[][];
  bemf_phase_V?: number[][];
  bemf_line_to_line_V?: number[][];
  bemf_phase_fundamental?: { peak: number[] };
}
interface RunState {
  run_id: string; status: string; completed: number; total: number; error?: string;
  curves?: { loaded?: Curve; noload?: Curve };
  rows?: Array<{ outer_rotor_torque_Nm: number; phase_linkage_Wb: number[] }>;
}
type Analysis = 'source_point' | 'loaded_torque' | 'noload_bemf' | 'both';
const COLORS = ['#f58e6c', '#73c9a8', '#91b9ef'];

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

export function OutrunnerWorkspace({ initialProject, onHome }: { initialProject: OutrunnerProject; onHome: () => void }) {
  const [project, setProject] = useState(initialProject);
  const [geometry, setGeometry] = useState<Preview | null>(null);
  const [analysis, setAnalysis] = useState<Analysis>('both');
  const [run, setRun] = useState<RunState | null>(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const busy = starting || run?.status === 'QUEUED' || run?.status === 'RUNNING';
  const jobKey = `coilem.outrunner.run:${project.fixture_id}`;

  useEffect(() => {
    let cancelled = false;
    setGeometry(null);
    api<Preview>('/preview', project).then((value) => { if (!cancelled) { setGeometry(value); setError(''); } })
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
      const value = parseOutrunnerProject(await file.text());
      if (!value) throw new Error('Open an LRK frozen-reference .coilem file in this workspace.');
      setProject(value); setRun(null); setError('');
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
  };
  const updateAnalysis = (update: Partial<OutrunnerProject['analysis']>) => {
    setProject((previous) => ({ ...previous, analysis: { ...previous.analysis, ...update } }));
    setRun(null);
  };
  const series = (values: number[][], prefix: string) => COLORS.map((color, index) => ({
    label: `${prefix} ${'ABC'[index]}`, values: values.map((row) => row[index]), color,
  }));
  const loaded = run?.curves?.loaded;
  const noload = run?.curves?.noload;

  return <main className="outrunner-workspace">
    <header>
      <button onClick={onHome}>← coilEM</button>
      <div><h1>{project.name}</h1><span className="outrunner-tag">Local experiment</span></div>
      <button disabled={busy} onClick={() => input.current?.click()}>Open .coilem</button>
      <button onClick={() => downloadReferenceFile('lrk-12s14p.coilem', project)}>Save .coilem</button>
      <input ref={input} hidden type="file" accept=".coilem,application/json" onChange={(event) => {
        const file = event.target.files?.[0]; if (file) void openFile(file); event.target.value = '';
      }} />
    </header>
    <p className="outrunner-notice">Frozen software reference · 14 poles / 12 slots · 10 mm stack · 0.2 mm main gap. Geometry, winding signs and source materials are fixed. Numerical qualification is in progress.</p>
    <div className="outrunner-layout">
      <section className="outrunner-card">
        <h2>Motor cross-section</h2>
        <svg viewBox="-16.5 -16.5 33 33" role="img" aria-label="Outer rotor, fourteen magnets and twelve winding regions">
          <g transform="scale(1,-1)">{geometry?.regions.map((region) => <path key={region.id}
            fill={region.kind === 'Magnet' ? '#c4776a' : region.kind === 'SlotWinding' ? COLORS['ABC'.indexOf(region.phase)] || '#d0a266' : '#687789'}
            fillRule="evenodd" stroke="#d5dfed" strokeWidth="0.025"
            d={region.loops.map((loop) => loop.map(([x, y], i) => `${i ? 'L' : 'M'}${x},${y}`).join(' ') + ' Z').join(' ')}>
            <title>{region.material}{region.phase ? ` · ${region.phase} · ${region.signed_turns} signed turns` : ''}</title>
          </path>)}</g>
        </svg>
        <p>Outer magnets and back iron rotate; the stator stays fixed. Positive mechanical angle and torque are counterclockwise.</p>
      </section>
      <section className="outrunner-card outrunner-settings">
        <h2>Reproduce the analysis</h2>
        <label>Analysis<select aria-label="Analysis" disabled={busy} value={analysis} onChange={(event) => { setAnalysis(event.target.value as Analysis); setRun(null); }}>
          <option value="source_point">Original operating point</option><option value="loaded_torque">Fixed-current torque curve</option>
          <option value="noload_bemf">No-load linkage and back-EMF</option><option value="both">Torque and back-EMF curves</option>
        </select></label>
        <label>Unique angles per electrical period<select aria-label="Unique angles per electrical period" disabled={busy} value={project.analysis.unique_samples}
          onChange={(event) => updateAnalysis({ unique_samples: Number(event.target.value) as 48 | 96 | 192 | 384 })}>
          {[48, 96, 192, 384].map((count) => <option key={count}>{count}</option>)}
        </select></label>
        <label>Gap mesh target (mm)<select aria-label="Gap mesh target (mm)" disabled={busy} value={project.analysis.gap_size_mm}
          onChange={(event) => updateAnalysis({ gap_size_mm: Number(event.target.value) as 0.05 | 0.025 | 0.0125 })}>
          {[0.05, 0.025, 0.0125].map((size) => <option key={size}>{size}</option>)}
        </select></label>
        <label>Back-EMF speed (rpm)<input aria-label="Back-EMF speed (rpm)" type="number" min="1" max="100000" disabled={busy} value={project.analysis.speed_rpm}
          onChange={(event) => { const speed = event.target.valueAsNumber; if (Number.isFinite(speed) && speed > 0 && speed <= 100000) updateAnalysis({ speed_rpm: speed }); }} /></label>
        <p>Loaded currents A/B/C: {project.analysis.loaded_currents_A.join(' / ')} A. Back-EMF always uses a separate zero-current sweep.</p>
        <p>One electrical period is 360/7 mechanical degrees. Each curve includes a separately solved endpoint. Larger grids and finer meshes take longer.</p>
        <button disabled={busy || !geometry} onClick={() => void start()}>Run fresh analysis</button>
        {busy && run && <><progress max={run.total || 1} value={run.completed || 0} /><p role="status">{run.status}: {run.completed || 0} / {run.total || '…'} points</p>
          <button onClick={() => void api<RunState>(`/runs/${run.run_id}/cancel`, {}).then(setRun)}>Cancel analysis</button></>}
        {run && ['INTERRUPTED', 'CANCELLED', 'ERROR'].includes(run.status) && <button disabled={busy} onClick={() => void start(true)}>Resume saved analysis</button>}
        {run && <p>Run {run.run_id} · {run.status}</p>}
        {(error || run?.error) && <p role="alert">{error || run?.error}</p>}
      </section>
    </div>
    {run?.rows?.length === 1 && analysis === 'source_point' && <section className="outrunner-card"><h2>Original operating point</h2>
      <p>Outer-rotor torque: {(run.rows[0].outer_rotor_torque_Nm * 1000).toFixed(4)} mN·m</p>
      <p>Phase linkages A/B/C: {run.rows[0].phase_linkage_Wb.map((value) => (value * 1000).toFixed(6)).join(' / ')} mWb</p></section>}
    {loaded && loaded.torque_Nm.length > 1 && <section className="outrunner-card"><h2>Fixed-current torque versus rotor angle</h2>
      <WaveformChart angles={loaded.angles_electrical_deg} values={loaded.torque_Nm.map((value) => value * 1000)} label="Outer-rotor torque" unit="mN·m" samplingLabel="Actual solved points; horizontal axis is electrical angle" /></section>}
    {noload && noload.phase_linkage_Wb.length > 1 && <section className="outrunner-card"><h2>No-load phase flux linkage</h2>
      <WaveformChart angles={noload.angles_electrical_deg} series={series(noload.phase_linkage_Wb.map((row) => row.map((value) => value * 1000)), 'Phase')} label="Phase flux linkage" unit="mWb" /></section>}
    {noload?.bemf_phase_V && <section className="outrunner-card"><h2>Back-EMF at {project.analysis.speed_rpm} rpm</h2>
      <p>Induced EMF: e = −ω dλ/dθ, using mechanical radians and positive counterclockwise speed. Full periodic spectral derivative; no harmonic filtering.</p>
      <WaveformChart angles={noload.angles_electrical_deg.slice(0, -1)} series={series(noload.bemf_phase_V, 'Phase')} label="No-load phase EMF" unit="V" />
      <p>Phase fundamental peaks: {noload.bemf_phase_fundamental?.peak.map((value) => value.toFixed(4)).join(' / ')} V</p>
      {noload.bemf_line_to_line_V && <WaveformChart angles={noload.angles_electrical_deg.slice(0, -1)} series={noload.bemf_line_to_line_V[0].map((_, index) => ({
        label: ['A − B', 'B − C', 'C − A'][index], values: noload.bemf_line_to_line_V!.map((row) => row[index]), color: COLORS[index],
      }))} label="Line-to-line EMF" unit="V" />}
      <p>The source does not establish a terminal winding connection; these phase and line-to-line results do not define a terminal Kv rating.</p></section>}
    {run && run.completed > 0 && <section className="outrunner-card"><button onClick={() => downloadReferenceFile(`lrk-${run.run_id}-results.json`, { project, run })}>Export results and design</button></section>}
  </main>;
}
