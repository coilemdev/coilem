import { useCallback, useEffect, useState } from 'react';
import { getPublicFieldFrame, loadPublicRunComparisonField, type PublicRunListRecord } from './api';
import { FieldResultPlot } from './FieldResultPlot';
import { comparisonFieldAngles, comparisonFieldTarget, type ComparisonFieldPosition } from './fieldComparison';
import type { PublicFieldLinePlot } from './model';
import type { ComparisonFields } from './runComparison';
import { InfoTip } from './Popover';

interface FieldRun { id: string; label: string; color: string; title?: string; record: PublicRunListRecord; fields?: ComparisonFields | null }
export interface FieldComparisonState { position: ComparisonFieldPosition; source: 'resultant' | 'pm' }
type Target = NonNullable<ReturnType<typeof comparisonFieldTarget>>;
type LoadField = (run: FieldRun, target: Target, signal: AbortSignal) => Promise<PublicFieldLinePlot>;

function FieldCard({ run, baseline, position, source, load }: { run: FieldRun; baseline: boolean; position: ComparisonFieldPosition; source: 'resultant' | 'pm'; load: LoadField }) {
  const target = comparisonFieldTarget(run.fields, position);
  const key = target ? `${run.record.project_slug}/${run.record.run_id}/${target.id}` : '';
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<{ key: string; plot?: PublicFieldLinePlot; error?: string }>({ key: '' });
  useEffect(() => {
    if (!target) return;
    const controller = new AbortController();
    setState({ key });
    void load(run, target, controller.signal).then(plot => {
      if (!controller.signal.aborted) setState({ key, plot });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      const message = error && typeof error === 'object' && 'message' in error ? String(error.message) : 'The saved field could not be loaded.';
      setState({ key, error: message });
    });
    return () => controller.abort();
  }, [key, retry, load]);
  const current = state.key === key ? state : null;
  const plot = source === 'pm' ? current?.plot?.noload_plot : current?.plot;
  return <article className="public-compare-field-card" aria-label={`${run.label} field`}>
    <header><strong style={{ color: run.color }}>{run.label} · {baseline ? 'baseline' : 'candidate'}</strong><span>{run.record.project_name || run.record.project_slug} · {run.record.run_setup?.name || 'Setup not recorded'}</span></header>
    {target && <p className="public-compare-field-position">{target.id === 'snapshot' ? 'Stored snapshot' : 'Recorded frame'} · {target.angle === null ? 'angle not recorded' : `${Number(target.angle.toFixed(3))}° electrical`}</p>}
    {!target ? <p className="public-compare-field-placeholder">{!run.fields ? 'Field metadata was not recorded.'
      : position === 'snapshot' ? 'A field snapshot was not recorded.'
      : run.fields.playback_removed ? 'Field playback was removed to free storage. The stored snapshot is still available if recorded.' : `No field frame was recorded at ${position}° electrical.`}</p>
      : current?.error ? <div className="public-compare-field-placeholder" role="alert">{current.error} <button type="button" onClick={() => setRetry(value => value + 1)}>Retry {run.label} field</button></div>
      : !current?.plot ? <p className="public-compare-field-placeholder" role="status">Loading {run.label} field…</p>
      : !plot ? <p className="public-compare-field-placeholder">The PM-only field was not recorded at this position.</p>
      : <FieldResultPlot plot={plot} showHeading={false} showControls={false} showHeatmap showMesh={false} showFieldLines colorRangeMode="fixed" title={`${run.label} field`} />}
  </article>;
}

export function RunFieldComparison({ runs, cache, state, onChange }: { runs: FieldRun[]; cache: Map<string, PublicFieldLinePlot>; state: FieldComparisonState; onChange: (state: FieldComparisonState) => void }) {
  const { position, source } = state;
  const angles = comparisonFieldAngles(runs.map(run => run.fields));
  const selected = position === 'snapshot' || angles.some(angle => Math.abs(angle - position) <= 1e-3) ? position : 'snapshot';
  const load = useCallback<LoadField>(async (run, target, signal) => {
    // A position can be superseded during effect cleanup, including StrictMode's
    // initial check. Let that cleanup cancel before starting a large transfer.
    await Promise.resolve();
    if (signal.aborted) throw new DOMException('Field request cancelled', 'AbortError');
    const key = `${run.record.project_slug}/${run.record.run_id}/${target.id}`;
    const cached = cache.get(key);
    if (cached) return cached;
    const result = target.artifactId ? await getPublicFieldFrame(target.artifactId, signal)
      : await loadPublicRunComparisonField(run.record.project_slug, run.record.run_id, signal);
    if (signal.aborted) throw new DOMException('Field request cancelled', 'AbortError');
    const plot = result.field_line_frame as PublicFieldLinePlot | null;
    if (!plot || !Array.isArray(plot.nodes_mm) || !Array.isArray(plot.triangles) || !Array.isArray(plot.element_b_mag_t)) throw new Error('The saved field snapshot is unavailable or invalid.');
    cache.set(key, plot);
    // Bound large numerical frames to the six visible runs plus one previous position each.
    while (cache.size > 12) cache.delete(cache.keys().next().value!);
    return plot;
  }, [cache]);
  return <section className="public-field-comparison" aria-label="Side-by-side field comparison">
    <div className="public-compare-view-heading"><h3>Field comparison</h3><InfoTip label="Field comparison help">Colors use the same fixed 0–2.0 T scale, with values above 2.0 T in magenta. Each motor is fitted independently; pictures do not compare physical dimensions. Stored snapshots can have different angles. Choose an electrical angle for matching recorded positions. No new field solve is started.</InfoTip></div>
    <div className="public-compare-view-controls">
      <label>Position <select aria-label="Comparison field position" value={selected} onChange={event => onChange({ ...state, position: event.target.value === 'snapshot' ? 'snapshot' : Number(event.target.value) })}>
        <option value="snapshot">Stored snapshot</option>{angles.map(angle => <option key={angle} value={angle}>{Number(angle.toFixed(3))}° electrical</option>)}
      </select></label>
      <label>Field <select aria-label="Comparison field source" value={source} onChange={event => onChange({ ...state, source: event.target.value as 'resultant' | 'pm' })}><option value="resultant">Resultant</option><option value="pm">PM only</option></select></label>
      <span>Fixed color scale · 0–2.0 T</span>
    </div>
    {selected === 'snapshot' && <p className="public-run-compare-timing-note">Each saved snapshot shows its recorded position below. Select an electrical angle to compare matching positions.</p>}
    <div className="public-compare-field-grid">{runs.map((run, index) => <FieldCard key={run.id} run={run} baseline={index === 0} position={selected} source={source} load={load} />)}</div>
  </section>;
}
