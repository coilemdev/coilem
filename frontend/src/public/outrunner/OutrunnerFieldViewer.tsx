import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { FieldResultPlot, type FieldResultRaster } from '../FieldResultPlot';
import type { GeometryPreview, PublicFieldLinePlot } from '../model';
import { OUTRUNNER_API, outrunnerRequest as api } from './api';

interface Frame { index: number; case_id: string; family: string; angle_ccw_deg: number; currents_A: number[]; torque_Nm: number; raster_ready: boolean }
interface Descriptor extends Omit<FieldResultRaster, 'base' | 'heat' | 'mesh' | 'lines'> { case: { angle_ccw_deg: number; currents_A: number[] } }
interface Loaded { raster: FieldResultRaster; descriptor: Descriptor }
function close(value: Loaded) { value.raster.base.close(); value.raster.heat.close(); value.raster.mesh?.close(); value.raster.lines.close(); }

export function OutrunnerFieldViewer({ runId, geometry, completed, viewControls }: { runId: string; geometry: GeometryPreview | null; completed: number; viewControls?: ReactNode }) {
  const [frames, setFrames] = useState<Frame[]>([]);
  const [family, setFamily] = useState('loaded');
  const [position, setPosition] = useState(0);
  const [current, setCurrent] = useState<Loaded | null>(null);
  const [exact, setExact] = useState<PublicFieldLinePlot | null>(null);
  const [playing, setPlaying] = useState(false);
  const [fps, setFps] = useState(5);
  const [direction, setDirection] = useState<'clockwise' | 'counterclockwise'>('clockwise');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [heat, setHeat] = useState(true), [mesh, setMesh] = useState(false), [lines, setLines] = useState(true);
  const cache = useRef(new Map<number, Loaded>());
  const pending = useRef(new Map<number, Promise<Loaded>>());
  const alive = useRef(true), cursor = useRef(0), visibleFrame = useRef(-1), generation = useRef(0);
  const [navigationSlot, setNavigationSlot] = useState<HTMLSpanElement | null>(null);

  useEffect(() => {
    alive.current = true;
    setFrames([]); setCurrent(null); setExact(null); setPosition(0); setPlaying(false);
    for (const item of cache.current.values()) close(item);
    cache.current.clear(); pending.current.clear();
    void api(`/runs/${runId}/prepare-playback`, {}).catch((failure) => setError(failure.message));
    const refresh = () => void api<{ frames: Frame[] }>(`/runs/${runId}/frames`).then((data) => {
      if (alive.current) { setFrames(data.frames); setFamily((selected) => data.frames.some((f) => f.family === selected) ? selected : data.frames[0]?.family || 'loaded'); }
    }).catch((failure) => { if (alive.current) setError(failure.message); });
    refresh();
    const timer = window.setInterval(refresh, 2500);
    return () => { alive.current = false; generation.current++; window.clearInterval(timer); for (const item of cache.current.values()) close(item); cache.current.clear(); };
  }, [runId]);
  useEffect(() => { void api(`/runs/${runId}/prepare-playback`, {}).catch(() => undefined); }, [runId, completed]);

  const selected = useMemo(() => frames.filter((frame) => frame.family === family), [frames, family]);
  const selectedKey = selected.map((frame) => frame.index).join(',');
  const load = (index: number): Promise<Loaded> => {
    const existing = cache.current.get(index);
    if (existing) { cache.current.delete(index); cache.current.set(index, existing); return Promise.resolve(existing); }
    const waiting = pending.current.get(index);
    if (waiting) return waiting;
    const activeGeneration = generation.current;
    const promise = api<Descriptor>(`/runs/${runId}/frames/${index}`).then(async (descriptor) => {
      const results = await Promise.allSettled(['base', 'heat', 'mesh', 'lines'].map(async (layer) => {
        const response = await fetch(`${OUTRUNNER_API}/runs/${runId}/frames/${index}/layers/${layer}.webp`);
        if (!response.ok) throw new Error(`Field ${layer} layer is unavailable`);
        return createImageBitmap(await response.blob());
      }));
      if (results.some((result) => result.status === 'rejected')) {
        for (const result of results) if (result.status === 'fulfilled') result.value.close();
        throw new Error('Solved-field images could not be loaded');
      }
      const images = results.map((result) => (result as PromiseFulfilledResult<ImageBitmap>).value);
      const value = { descriptor, raster: { ...descriptor, base: images[0], heat: images[1], mesh: images[2], lines: images[3] } };
      if (!alive.current || generation.current !== activeGeneration) { close(value); throw new Error('Field view changed'); }
      cache.current.set(index, value);
      // Bound decoded image memory. The whole solution stays on disk; only a
      // small moving window is decoded in the browser.
      while (cache.current.size > 6) {
        const victim = [...cache.current.keys()].find((key) => key !== visibleFrame.current && key !== index);
        if (victim === undefined) break;
        close(cache.current.get(victim)!); cache.current.delete(victim);
      }
      return value;
    }).finally(() => { if (pending.current.get(index) === promise) pending.current.delete(index); });
    pending.current.set(index, promise);
    return promise;
  };

  useEffect(() => { setPlaying(false); setPosition(0); cursor.current = 0; }, [family]);
  useEffect(() => {
    const frame = selected[position];
    if (!frame) return;
    let stale = false;
    cursor.current = position; setLoading(true); setExact(null);
    void load(frame.index).then((value) => { if (!stale) { visibleFrame.current = frame.index; setCurrent(value); setLoading(false); setError(''); } })
      .catch((failure) => { if (!stale) { setError(failure.message); setLoading(false); setPlaying(false); } });
    return () => { stale = true; };
  }, [runId, selectedKey, position]);

  useEffect(() => {
    const frame = selected[position];
    if (playing || !frame || loading) return;
    const abort = new AbortController();
    void api<PublicFieldLinePlot>(`/runs/${runId}/frames/${frame.index}/numerical`, undefined, abort.signal)
      .then(setExact).catch((failure) => { if (!abort.signal.aborted) setError(failure.message); });
    return () => abort.abort();
  }, [playing, runId, position, selectedKey, loading]);

  useEffect(() => {
    if (!playing || selected.length < 2) return;
    let stopped = false, timer = 0;
    const span = selected[selected.length-1].angle_ccw_deg-selected[0].angle_ccw_deg;
    const hasEndpoint = selected.length > 2 && Math.abs(Math.abs(span)-360/7) < 1e-7;
    const count = selected.length-(hasEndpoint ? 1 : 0);
    const advance = async () => {
      // Stored solver angles are positive CCW. Reverse the actual frames for
      // the same clockwise playback default as the regular motor workspace.
      const sourceStep = Math.sign(span) || 1;
      const next = (cursor.current+(direction === 'clockwise' ? -sourceStep : sourceStep)+count) % count;
      try {
        await load(selected[next].index);
        if (stopped) return;
        cursor.current = next; setPosition(next);
        timer = window.setTimeout(advance, 1000/fps);
      } catch (failure) { if (!stopped) { setError((failure as Error).message); setPlaying(false); } }
    };
    timer = window.setTimeout(advance, 1000/fps);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [playing, fps, direction, runId, selectedKey]);
  const frame = selected[position];
  const ready = selected.filter((item) => item.raster_ready).length;
  return <div className="outrunner-field-viewer">
    <div className="outrunner-field-stage public-solved-field-canvas"><FieldResultPlot raster={current?.raster || null} plot={playing ? null : exact}
      showHeatmap={heat} showMesh={mesh} showFieldLines={lines} showControls={false} showHeading={false}
      geometry={geometry} showMagnets={false} magnetRotationDeg={-(frame?.angle_ccw_deg || 0)} poles={14}
      probeEnabled={!playing && !loading} navigationSlot={navigationSlot}
      describeProbe={(probe) => ({ regionLabel: probe.region.split('/')[1]?.trim() || probe.region,
        materialLabel: probe.region.split('/')[0].trim(), saturationLabel: 'Source material · solved element', saturationTone: 'neutral' })} />
      {(loading || !current) && <div className="outrunner-field-buffer" role="status">Preparing actual solved frame…</div>}
    </div>
    <div className="outrunner-field-controls">
      <div className="public-dock-strip">{viewControls || <strong>Field solution</strong>}<span>{frame ? `Source: ${(current?.descriptor.case.angle_ccw_deg ?? frame.angle_ccw_deg).toFixed(2)}° mech CCW · ${((current?.descriptor.case.angle_ccw_deg ?? frame.angle_ccw_deg)*7).toFixed(1)}° elec` : 'No completed field yet'}</span>
        <span className="public-dock-strip-end" ref={setNavigationSlot} /></div>
      <div className="outrunner-field-transport">
        <button className="public-field-transport-play" aria-label={playing ? 'Pause field solution' : 'Play field solution'} disabled={selected.length < 2}
          onClick={() => setPlaying((value) => !value)}>{playing ? 'Ⅱ' : '▶'}</button>
        <button aria-label="First solved frame" disabled={!selected.length} onClick={() => { setPlaying(false); setPosition(0); }}>■</button>
        <input type="range" aria-label="Solved field position" min="0" max={Math.max(0, selected.length-1)} step="1" value={position}
          disabled={!selected.length} onChange={(event) => { setPlaying(false); setPosition(event.target.valueAsNumber); }} />
        <select aria-label="Field playback speed" value={fps} onChange={(event) => setFps(Number(event.target.value))}>
          {[1, 2, 5, 10].map((speed) => <option key={speed} value={speed}>{speed} frames/s</option>)}</select>
        <select aria-label="Field playback direction" value={direction} title="Clockwise plays the actual CCW source frames in reverse order."
          onChange={(event) => setDirection(event.target.value as typeof direction)}>
          <option value="clockwise">Clockwise</option><option value="counterclockwise">Counterclockwise</option></select>
        <select aria-label="Solved field family" value={family} onChange={(event) => setFamily(event.target.value)}>
          {[...new Set(frames.map((item) => item.family))].map((value) => <option key={value} value={value}>{value === 'loaded' ? 'Loaded torque' : value === 'noload' ? 'No-load BEMF' : 'Single point'}</option>)}</select>
      </div>
      <div className="outrunner-field-toggles">{[['Heatmap', heat, setHeat], ['Element edges', mesh, setMesh], ['Field lines', lines, setLines]].map(([label, checked, setter]) =>
        <label key={String(label)}><input type="checkbox" checked={Boolean(checked)} onChange={(event) => (setter as (value: boolean) => void)(event.target.checked)} />{String(label)}</label>)}
        <span>{current && `A / B / C: ${current.descriptor.case.currents_A.map(value => value.toFixed(2)).join(' / ')} A · `}{position+1} / {selected.length} frames · {ready} images ready</span></div>
      {selected.length === 1 && <p className="outrunner-panel-note">Run an angle sweep to play the changing solved field.</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  </div>;
}
