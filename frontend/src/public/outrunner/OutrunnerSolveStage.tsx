import { useEffect, useMemo, useState } from 'react';
import { NumberRow, ParameterSectionBlock, StatusTag, formatRunTimeRange } from '../CoilEmWorkspace';
import type { MeshPreview } from '../model';
import { summarizePublicMeshQuality } from '../meshQuality';
import { PUBLIC_PHASE_COLORS } from '../motorPalette';
import { WaveformChart } from '../WaveformChart';
import { OutrunnerViewport } from './OutrunnerViewport';
import type { ReferencePreview } from './geometry';
import type { OutrunnerProject } from './project';
import type { Analysis, RunEstimate, RunState } from './types';

export function timingText(range?: [number, number]): string {
  if (!range) return 'Calculating…';
  if (range[1] >= 7200) return `about ${Math.max(1, Math.floor(range[0]/3600))}–${Math.ceil(range[1]/3600)} h`;
  return formatRunTimeRange({ estimated_solve_time_s: (range[0]+range[1])/2, estimated_solve_time_range_s: range });
}
interface Props {
  project: OutrunnerProject; geometry: ReferencePreview | null; mesh: MeshPreview | null; meshBusy: boolean; meshError: string;
  estimate: RunEstimate | null; analysis: Analysis; run: RunState | null; busy: boolean; error: string;
  onStart: () => void; onCancel: () => void; onResume: () => void; onBack: () => void; onResults: () => void;
  onAnalysisChange: (analysis: Analysis) => void; onUpdateAnalysis: (update: Partial<OutrunnerProject['analysis']>) => void;
}
type Section = 'operating' | 'analysis' | 'plan' | 'advanced';

export function OutrunnerSolveStage(props: Props) {
  const { project, geometry, mesh, meshBusy, meshError, run, busy, analysis, estimate } = props;
  const settings = project.analysis;
  const [section, setSection] = useState<Section | null>('operating');
  const [customOpen, setCustomOpen] = useState(false);
  const [inspection, setInspection] = useState({ serial: 0, mode: 'geometry' as 'geometry' | 'quality' | 'problems' });
  const [elapsedNow, setElapsedNow] = useState(run?.elapsed_s || 0);
  const quality = useMemo(() => summarizePublicMeshQuality(mesh), [mesh]);
  const toggle = (next: Section) => setSection((current) => current === next ? null : next);
  const inspect = (mode: typeof inspection.mode = 'geometry') => setInspection((old) => ({ serial: old.serial+1, mode }));
  useEffect(() => {
    const started = Date.now(), elapsed = run?.elapsed_s || 0;
    setElapsedNow(elapsed);
    if (!busy) return;
    const timer = window.setInterval(() => setElapsedNow(elapsed+(Date.now()-started)/1000), 1000);
    return () => window.clearInterval(timer);
  }, [busy, run?.elapsed_s]);
  const plans = estimate?.plans;
  const planLabel = settings.accuracy_plan === 'custom' ? 'Custom' : plans?.[settings.accuracy_plan]?.label || 'Standard';
  const timeText = timingText(estimate?.total_range_s);
  const analysisLabel = analysis === 'both' ? 'Torque · Back EMF' : analysis === 'loaded_torque' ? 'Torque' : analysis === 'noload_bemf' ? 'Back EMF' : 'Original point';
  const ready = Boolean(geometry && mesh && !meshBusy && !meshError);
  const status = busy ? 'Running' : meshBusy ? 'Preparing mesh' : run?.status === 'COMPLETE' ? 'Complete' : ready ? 'Ready to run' : 'Review setup';
  const disabled = !busy && !ready;
  const pointCount = estimate?.positions || (analysis === 'source_point' ? 1 : (settings.unique_samples+1)*(analysis === 'both' ? 2 : 1));
  const setPlan = (name: 'preview' | 'standard' | 'high_accuracy') => {
    if (!plans) return;
    const { label: _label, ...values } = plans[name];
    props.onUpdateAnalysis(values); setCustomOpen(false); inspect();
  };
  const current = settings.loaded_currents_A;
  return <div className="public-solve-workspace outrunner-standard-workspace">
    <aside className="public-solve-setup"><div className="public-solve-setup-frame"><div className="mesh-panel-header"><span className="mesh-panel-header-title">Analysis setup</span></div>
      <div className="public-solve-setup-scroll">
        <ParameterSectionBlock id="operating" label="Operating point" summary={`Fixed phase currents · ${settings.speed_rpm} rpm`} active={section === 'operating'} onToggle={toggle}>
          <div className="public-excitation-selector" role="group" aria-label="Stator excitation"><button className="active" type="button" aria-pressed="true"><strong>Fixed phase currents</strong><small>Source A / B / C circuit convention</small></button></div>
          <NumberRow label="Conducting current" unit="A" value={current[1]} min={-20} max={20} step={.5} disabled={busy}
            onChange={(value) => props.onUpdateAnalysis({ loaded_currents_A: [0, value, -value] })} />
          <p className="public-solver-help">Phase A = 0 A; B and C carry equal opposite currents. The angle sweep keeps these currents fixed.</p>
          <NumberRow label="Speed" unit="rpm" value={settings.speed_rpm} min={1} max={100000} disabled={busy}
            onChange={(value) => { if (value > 0 && value <= 100000) props.onUpdateAnalysis({ speed_rpm: value }); }} />
          <p className="public-solver-help">Speed normalizes no-load back-EMF. Rotor angle and torque are positive CCW.</p>
        </ParameterSectionBlock>
        <ParameterSectionBlock id="analysis" label="Analysis" summary={analysisLabel} active={section === 'analysis'} onToggle={toggle}>
          <label className="public-check-row"><input type="checkbox" disabled={busy} checked={analysis === 'both' || analysis === 'loaded_torque'}
            onChange={(event) => props.onAnalysisChange(event.target.checked ? analysis === 'noload_bemf' ? 'both' : 'loaded_torque' : analysis === 'both' ? 'noload_bemf' : 'source_point')} />Torque</label>
          <label className="public-check-row"><input type="checkbox" disabled={busy} checked={analysis === 'both' || analysis === 'noload_bemf'}
            onChange={(event) => props.onAnalysisChange(event.target.checked ? analysis === 'loaded_torque' ? 'both' : 'noload_bemf' : analysis === 'both' ? 'loaded_torque' : 'source_point')} />Back EMF</label>
          <label className="public-check-row"><input type="radio" name="source-point" disabled={busy} checked={analysis === 'source_point'} onChange={() => props.onAnalysisChange('source_point')} />Original operating point only</label>
          <p className="public-solver-help">Back-EMF uses a separate zero-current sweep. Every completed angle retains its field solution for inspection and playback.</p>
        </ParameterSectionBlock>
        <ParameterSectionBlock id="plan" label="Accuracy plan" summary={`${planLabel} · ${settings.unique_samples} angles`} active={section === 'plan'} onToggle={toggle}>
          <div className="public-choice-row public-solve-plan-choices">{(['preview', 'standard', 'high_accuracy'] as const).map((name, i) =>
            <button key={name} type="button" className={settings.accuracy_plan === name ? 'active' : ''} aria-pressed={settings.accuracy_plan === name}
              disabled={busy || !plans} onClick={() => setPlan(name)}>{name === 'standard' && <em>Recommended</em>}
              <span>{['Preview', 'Standard', 'High accuracy'][i]}</span><small>{['Coarse mesh', 'Medium mesh', 'Fine mesh'][i]}</small>
              <small>{settings.accuracy_plan === name ? timeText : ['Fast iteration', 'Balanced', 'Finer detail'][i]}</small></button>)}</div>
          <div className={`public-custom-sweep${settings.accuracy_plan === 'custom' ? ' active' : ''}`}>
            <button className="public-custom-sweep-toggle" type="button" aria-expanded={customOpen} disabled={busy}
              onClick={() => { setCustomOpen((value) => !value); props.onUpdateAnalysis({ accuracy_plan: 'custom' }); }}>
              <span>Custom…</span><small>Choose the electrical-angle step</small><i>{customOpen ? '▴' : '▾'}</i></button>
            {customOpen && <div className="public-custom-sweep-body"><label className="outrunner-setting">Step size (° elec)<select aria-label="Electrical step size" disabled={busy} value={settings.unique_samples}
              onChange={(event) => props.onUpdateAnalysis({ unique_samples: Number(event.target.value) as typeof settings.unique_samples })}>
              {[24, 48, 96, 192, 384].map((count) => <option key={count} value={count}>{360/count}° · {count} positions</option>)}</select></label>
              <div className="public-custom-sweep-estimate"><strong>{pointCount} solves including endpoints</strong><span>{timeText}</span></div></div>}
          </div>
          {settings.accuracy_plan === 'preview' && <p className="public-plan-advisory">Preview is intended for iteration, not final result sign-off.</p>}
        </ParameterSectionBlock>
        <ParameterSectionBlock id="advanced" label="Advanced options" summary={`WST · Newton · Direct · ${settings.gap_size_mm} mm gap`} active={section === 'advanced'} onToggle={toggle}>
          <div className="public-advanced-body"><section className="public-advanced-section"><span className="public-section-kicker">Mesh preparation</span>
            <label className="outrunner-setting">Gap element target (mm)<select aria-label="Gap mesh target (mm)" disabled={busy} value={settings.gap_size_mm}
              onChange={(event) => { props.onUpdateAnalysis({ gap_size_mm: Number(event.target.value) as typeof settings.gap_size_mm }); inspect(); }}>
              {[.1, .05, .025, .0125].map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="outrunner-setting">Bulk element target (mm)<select aria-label="Bulk mesh target (mm)" disabled={busy} value={settings.bulk_size_mm}
              onChange={(event) => { props.onUpdateAnalysis({ bulk_size_mm: Number(event.target.value) as typeof settings.bulk_size_mm }); inspect(); }}>
              {[.5, .25, .125].map((value) => <option key={value}>{value}</option>)}</select></label>
            <button className="public-run-again-btn" onClick={() => inspect()}>Inspect prepared mesh</button></section>
            <section className="public-advanced-section"><span className="public-section-kicker">Solver settings</span><dl className="public-solver-settings">
              <div><dt>Torque method</dt><dd>WST · outer body</dd></div><div><dt>Linear solver</dt><dd>Direct Cholesky</dd></div><div><dt>Nonlinear solver</dt><dd>Newton</dd></div></dl>
              <label className="outrunner-setting">Nonlinear tolerance<select aria-label="Nonlinear tolerance" disabled={busy} value={settings.nonlinear_tolerance}
                onChange={(event) => props.onUpdateAnalysis({ nonlinear_tolerance: Number(event.target.value) as typeof settings.nonlinear_tolerance })}>
                <option value={1e-5}>1e-5</option><option value={1e-6}>1e-6</option></select></label></section>
            <section className="public-advanced-section"><span className="public-section-kicker">Generated outputs</span><div className="public-output-chips">
              {['Torque', 'Flux linkage', 'Field frames', 'Mesh', ...(analysis === 'both' || analysis === 'noload_bemf' ? ['Back EMF'] : [])].map((label) => <span key={label}><i>✓</i>{label}</span>)}</div></section>
          </div>
        </ParameterSectionBlock>
      </div>
      <footer className="public-solve-footer"><div className="public-run-consequence"><StatusTag tone={busy ? 'running' : ready ? 'good' : 'warning'} label={status} placement="above" /><strong>{timeText}</strong></div>
        {(props.error || meshError || run?.error) && <p role="alert">{props.error || meshError || run?.error}</p>}
        {run?.status === 'COMPLETE' && <button className="public-run-btn" onClick={props.onResults}>View Results →</button>}
        <button className={busy ? 'public-cancel-btn' : run?.status === 'COMPLETE' ? 'public-run-again-btn' : 'public-run-btn'} disabled={disabled} onClick={busy ? props.onCancel : props.onStart}>
          {busy ? '■ Cancel solve' : run?.status === 'COMPLETE' ? 'Run again' : '▶ Run analysis'}</button>
        {run && ['INTERRUPTED', 'CANCELLED', 'ERROR'].includes(run.status) && <button className="public-run-again-btn" disabled={busy} onClick={props.onResume}>Resume saved analysis</button>}
        {run && run.status !== 'COMPLETE' && run.completed > 0 && <button className="public-run-again-btn" onClick={props.onResults}>View Results →</button>}
        <button className="public-back-link" onClick={props.onBack}>← Back to Design</button></footer>
    </div></aside>
    <div className="public-live-stage"><OutrunnerViewport preview={geometry} project={project} mesh={mesh} meshBusy={meshBusy} meshError={meshError}
      context="solve" run={run} inspection={inspection} /></div>
    <aside className="public-run-plan"><div className="public-run-plan-scroll"><div className="mesh-panel-header"><span className="mesh-panel-header-title">Run plan</span>
      <div className="public-run-plan-tags"><StatusTag tone={busy ? 'warning' : 'good'} label={status} align="end" /><StatusTag tone="warning" label="Experimental" heading="Numerical qualification in progress" /></div></div>
      <details className="public-run-plan-section public-run-analysis" open><summary className="public-run-copy"><span className="eyebrow">Analysis</span><strong className="public-run-plan-title">Magneto2D</strong>
        <small className="public-run-plan-caption">Built-in field solver using the prepared native Gmsh mesh.</small></summary><div className="public-run-analysis-body">
        <section className="public-excitation-preview"><div className="public-excitation-preview-heading"><span className="eyebrow">Excitation</span><strong>Fixed phase currents</strong></div>
          <svg viewBox="0 0 280 62" aria-label="Fixed phase current preview">{current.map((value, i) => <path key={i} d={`M 8 ${31-value/Math.max(1,...current.map(Math.abs))*22} H 272`} fill="none" stroke={PUBLIC_PHASE_COLORS[(['A','B','C'] as const)[i]]} strokeWidth="2" />)}</svg>
          <small>A / B / C: {current.join(' / ')} A</small></section>
        {run && <div className="outrunner-run-monitor"><strong>{run.stage || run.status}</strong><progress max={run.total || 1} value={run.completed || 0} />
          <span role="status">{run.status}: {run.completed || 0} / {run.total || pointCount} points</span>
          {busy && <span>Elapsed {Math.floor(elapsedNow/60)}m {Math.floor(elapsedNow % 60)}s · remaining {timingText(run.estimated_remaining_range_s || estimate?.total_range_s)}</span>}</div>}
        <dl className="public-quality-list"><div><dt>Solver</dt><dd>Magneto2D</dd></div><div><dt>Accuracy plan</dt><dd>{planLabel}</dd></div>
          <div><dt>Mesh</dt><dd>{mesh ? `${mesh.triangles.length.toLocaleString()} elements` : 'Preparing…'}</dd></div>
          <div className="public-minimum-quality-row"><dt>Minimum quality</dt><dd><button className={quality.minimum >= quality.threshold ? 'pass' : 'fail'} onClick={() => inspect('quality')} disabled={!mesh}><strong>{mesh ? `${quality.minimum.toFixed(3)} · ${quality.minimum >= quality.threshold ? 'Pass' : 'Inspect'}` : 'Pending'}</strong><small>Required ≥ {quality.threshold.toFixed(3)} · inspect</small></button></dd></div>
          <div><dt>Gap refinement</dt><dd>{settings.gap_size_mm} mm</dd></div><div><dt>Positions</dt><dd>{pointCount} including endpoints</dd></div>
          <div><dt>Run-time estimate</dt><dd>{timeText}</dd></div><div><dt>Estimate basis</dt><dd>{estimate?.observed_points ? `${estimate.observed_points} local points` : 'Measured profile'}</dd></div>
          <div><dt>Qualification</dt><dd>Experimental</dd></div></dl>
      </div></details>
      {mesh && <details className="public-run-plan-section public-mesh-quality-summary" open><summary className="public-mesh-quality-heading"><span className="public-section-kicker">Element quality</span>
        <strong className={quality.counts.failing ? 'is-fail' : 'is-pass'}>{quality.counts.failing ? 'Inspect mesh' : 'Shape check passed'}</strong></summary><div className="public-mesh-quality-body">
        <div className="public-quality-distribution">{(['good', 'acceptable', 'marginal', 'failing'] as const).map((band) => <i className={band} key={band} style={{ width: `${quality.counts[band]/mesh.triangles.length*100}%` }} />)}</div>
        <div className="public-quality-counts">{(['good', 'acceptable', 'marginal', 'failing'] as const).map((band) => <span key={band}><i className={band} />{band}<strong>{quality.counts[band].toLocaleString()}</strong></span>)}</div>
        <p>Element shape is separate from field convergence and mesh independence.</p></div></details>}
      {run?.curves?.loaded && run.curves.loaded.torque_Nm.length > 1 && <div className="outrunner-live-curve"><WaveformChart angles={run.curves.loaded.angles_electrical_deg}
        values={run.curves.loaded.torque_Nm.map((value) => value*1000)} label="Live outer-rotor torque" unit="mN·m" /></div>}
    </div></aside>
  </div>;
}
