import { useEffect, useRef, useState, type ReactNode } from 'react';
import { CoilEmTopBar, type PublicConnectionStatus, type PublicWorkflowStep } from '../CoilEmWorkspace';
import { MotorWorkflowShell } from '../MotorWorkflowShell';
import { RotorArrangement } from '../RotorArrangement';
import { WaveformChart } from '../WaveformChart';
import { PUBLIC_PHASE_COLORS } from '../motorPalette';
import { OutrunnerViewport } from './OutrunnerViewport';
import type { ReferencePreview } from './geometry';
import { downloadReferenceFile, type OutrunnerProject } from './project';
import type { Analysis, RunState } from './types';

interface Props {
  project: OutrunnerProject; geometry: ReferencePreview | null; analysis: Analysis; run: RunState | null; busy: boolean; error: string;
  appVersion?: string | null; connectionStatus?: PublicConnectionStatus;
  onHome: () => void; onOpenFile: (file: File) => void; onReset: () => void;
  onStart: () => void; onResume: () => void; onCancel: () => void;
  onAnalysisChange: (value: Analysis) => void; onUpdateAnalysis: (update: Partial<OutrunnerProject['analysis']>) => void;
}
const PHASES = ['A', 'B', 'C'] as const;

function FixedRow({ label, value, unit = '' }: { label: string; value: string | number; unit?: string }) {
  return <div className="param-row public-param-row"><span className="param-label">{label}{unit && <small>{unit}</small>}</span>
    <output className="outrunner-fixed-value">{value}</output></div>;
}
function Group({ title, subtitle, children, open = false }: { title: string; subtitle: string; children: ReactNode; open?: boolean }) {
  return <details className="param-group outrunner-fixed-group" open={open}><summary className="param-group-header">
    <span className="outrunner-source-check">✓</span><span className="param-group-titles"><strong className="param-group-label">{title}</strong>
      <small className="param-group-chip">{subtitle}</small></span><span className="chevron">▾</span></summary>
    <div className="param-group-content">{children}</div></details>;
}

export function OutrunnerWorkflow(props: Props) {
  const { project, geometry, run, busy, analysis } = props;
  const [step, setStep] = useState<PublicWorkflowStep>('design');
  const [resultTab, setResultTab] = useState<'torque' | 'bemf' | 'linkage'>('torque');
  const previousStatus = useRef(run?.status);
  useEffect(() => {
    if (run?.status === 'COMPLETE' && ['QUEUED', 'RUNNING'].includes(previousStatus.current || '')) setStep('report');
    previousStatus.current = run?.status;
  }, [run?.status]);
  const resultReady = Boolean(run && run.completed > 0);
  const loaded = run?.curves?.loaded, noload = run?.curves?.noload;
  const series = (values: number[][], prefix = 'Phase') => PHASES.map((phase, index) => ({
    label: `${prefix} ${phase}`, values: values.map((row) => row[index]), color: PUBLIC_PHASE_COLORS[phase],
  }));
  const error = props.error || run?.error;
  const status = run?.status || 'Ready to solve';
  const healthy = Boolean(geometry) && !error;
  const pointCount = analysis === 'source_point' ? 1 : (project.analysis.unique_samples+1)*(analysis === 'both' ? 2 : 1);

  const health = <aside className="design-workspace-health"><div className="design-workspace-health-scroll"><section className="design-health-panel tone-warning">
    <span className="eyebrow">Design health</span><p>Source checks for this published fixture.</p>
    <div className="outrunner-health-status"><span>{healthy ? '✓' : '!'}</span><div><strong>{healthy ? 'Ready to solve · experimental' : 'Review source checks'}</strong>
      <p>Geometry and winding identities are fixed.</p></div></div>
    <div className="outrunner-health-metrics"><div><small>Air gap</small><strong>0.20 <em>mm</em></strong></div>
      <div><small>Coverage</small><strong>77.8 <em>%</em></strong></div><div><small>Poles / slots</small><strong>14 / 12</strong></div></div>
    <h3 className="eyebrow">Pre-solve checks</h3>
    <ul className="outrunner-checks"><li>✓ Exact source regions and bore hole</li><li>✓ 14 magnets and 12 winding regions</li><li>✓ Signed turns and balanced currents</li>
      <li>✓ M-19 and 1018 source curves</li><li className="is-warning">! Numerical qualification in progress</li></ul>
    <p className="outrunner-muted">Published geometry and materials stay fixed. Set operating conditions and accuracy in Solve.</p>
    {error && <p role="alert">{error}</p>}
  </section></div></aside>;

  const settings = <>
    <Group title="Analysis" subtitle="Torque, linkage and back-EMF" open>
      <label className="outrunner-setting">Analysis<select aria-label="Analysis" disabled={busy} value={analysis}
        onChange={(event) => props.onAnalysisChange(event.target.value as Analysis)}>
        <option value="source_point">Original operating point</option><option value="loaded_torque">Fixed-current torque curve</option>
        <option value="noload_bemf">No-load linkage and back-EMF</option><option value="both">Torque and back-EMF curves</option></select></label>
    </Group>
    <Group title="Operating point" subtitle={`${project.analysis.speed_rpm} rpm · source phase currents`} open>
      <FixedRow label="Phase A / B / C" value={project.analysis.loaded_currents_A.join(' / ')} unit="A" />
      <label className="outrunner-setting">Back-EMF speed <span>rpm</span><input aria-label="Back-EMF speed (rpm)" type="number" min="1" max="100000"
        disabled={busy} value={project.analysis.speed_rpm} onChange={(event) => { const value = event.target.valueAsNumber;
          if (Number.isFinite(value) && value > 0 && value <= 100000) props.onUpdateAnalysis({ speed_rpm: value }); }} /></label>
      <p className="outrunner-panel-note">Back-EMF uses a separate zero-current sweep. Positive rotor position and torque are CCW.</p>
    </Group>
    <Group title="Accuracy" subtitle={`${project.analysis.unique_samples} angles · ${project.analysis.gap_size_mm} mm gap target`} open>
      <label className="outrunner-setting">Angles per electrical period<select aria-label="Unique angles per electrical period" disabled={busy}
        value={project.analysis.unique_samples} onChange={(event) => props.onUpdateAnalysis({ unique_samples: Number(event.target.value) as 48 | 96 | 192 | 384 })}>
        {[48, 96, 192, 384].map((count) => <option key={count}>{count}</option>)}</select></label>
      <label className="outrunner-setting">Gap mesh target <span>mm</span><select aria-label="Gap mesh target (mm)" disabled={busy}
        value={project.analysis.gap_size_mm} onChange={(event) => props.onUpdateAnalysis({ gap_size_mm: Number(event.target.value) as .05 | .025 | .0125 })}>
        {[.05, .025, .0125].map((size) => <option key={size}>{size}</option>)}</select></label>
      <p className="outrunner-panel-note">Each curve includes a separately solved endpoint. Finer meshes and larger grids take longer.</p>
    </Group>
  </>;

  return <MotorWorkflowShell topBar={<CoilEmTopBar config={{ topology: 'SPM', rotor: { pole_count: 14 }, stator: { slot_count: 12 } }}
    appVersion={props.appVersion} designName={project.name} activeStep={step} solveAvailable={Boolean(geometry)} resultReady={resultReady}
    solveRunning={busy} connectionStatus={props.connectionStatus || 'online'} onHome={props.onHome} onStepChange={setStep}
    onOpenDesignFile={props.onOpenFile} onSaveDesign={() => downloadReferenceFile('lrk-12s14p.coilem', project)} onResetDesign={props.onReset}
    showRunHistory={false} />}>
    {step === 'design' && <div className="design-workspace workflow-stage-content outrunner-standard-workspace"><div className="design-workspace-main">
      <aside className="public-parameter-panel"><div className="panel-header"><span className="panel-header-title">Design</span><span className="public-setting-pill">Fixed source</span></div>
        <div className="panel-left-scroll"><div className="public-design-notice">Published reference · exact geometry, winding and source materials.</div>
          <RotorArrangement value="outrunner" disabled={busy} onInrunner={props.onHome} />
          <div className="param-section"><div className="param-section-label">Topology</div><div className="topology-cards">
            <button className="topo-card active" type="button" aria-pressed="true"><span className="topo-icon">◉</span><span className="topo-text"><strong className="topo-name">SPM</strong><small className="topo-sub">Surface PM</small></span></button>
            <button className="topo-card" type="button" disabled title="The published outer-rotor fixture uses surface magnets"><span className="topo-icon">◉</span><span className="topo-text"><strong className="topo-name">IPM</strong><small className="topo-sub">Fixture uses SPM</small></span></button>
          </div></div>
          <Group title="Stator Geometry" subtitle="12 slots · 10 mm stack" open><FixedRow label="Outer diameter" value="25.60" unit="mm" />
            <FixedRow label="Bore diameter" value="13.00" unit="mm" /><FixedRow label="Slot count" value={12} /><FixedRow label="Stack length" value="10.00" unit="mm" /></Group>
          <Group title="Rotor & Magnets" subtitle="14 poles · outer rotor" open><FixedRow label="Outer diameter" value="30.78" unit="mm" />
            <FixedRow label="Magnet thickness" value="1.00" unit="mm" /><FixedRow label="Main air gap" value="0.20" unit="mm" /><FixedRow label="Back clearance" value="0.14" unit="mm" /></Group>
          <Group title="Winding" subtitle="3 phases · signed 15-turn coil sides"><p className="outrunner-panel-note">Single-layer concentrated winding. Review the exact signed source map in the Winding view.</p></Group>
          <Group title="Materials" subtitle="M-19 stator · 1018 rotor"><p className="outrunner-panel-note">Source steel curves and NdFeB 40 MGOe magnets. Review the Materials view.</p></Group>
        </div><footer className="panel-footer-cta"><div className="validation-ok">✓ Frozen reference loaded</div><button className="panel-next-btn" disabled={!geometry} onClick={() => setStep('solve')}>Continue to Solve</button></footer>
      </aside><OutrunnerViewport preview={geometry} project={project} /></div>{health}</div>}

    {step === 'solve' && <div className="public-solve-workspace outrunner-standard-workspace">
      <aside className="public-solve-setup"><div className="public-solve-setup-frame"><div className="mesh-panel-header"><span className="mesh-panel-header-title">Analysis setup</span></div>
        <div className="public-solve-setup-scroll">{settings}</div><footer className="outrunner-solve-footer">
          {error && <p role="alert">{error}</p>}
          <button className={busy ? 'public-cancel-btn' : 'public-run-btn'} disabled={!busy && !geometry} onClick={busy ? props.onCancel : props.onStart}>{busy ? '■ Cancel solve' : '▶ Run analysis'}</button>
          {run && ['INTERRUPTED', 'CANCELLED', 'ERROR'].includes(run.status) && <button className="public-run-again-btn" disabled={busy} onClick={props.onResume}>Resume saved analysis</button>}
          {resultReady && <button className="public-run-again-btn" onClick={() => setStep('report')}>View Results →</button>}
          <button className="public-back-link" onClick={() => setStep('design')}>← Back to Design</button></footer></div></aside>
      <div className="public-live-stage"><OutrunnerViewport preview={geometry} project={project} /></div>
      <aside className="public-run-plan"><div className="mesh-panel-header"><span className="mesh-panel-header-title">Run plan</span></div><div className="outrunner-run-plan-body">
        <span className="eyebrow">Magneto2D · Gmsh native</span><h2>{busy ? 'Analysis running' : status}</h2>
        <p>{analysis === 'source_point' ? 'Original fixed-current point' : analysis === 'both' ? 'Loaded torque + no-load back-EMF' : analysis === 'loaded_torque' ? 'Fixed-current torque sweep' : 'No-load linkage + back-EMF'}</p>
        <dl className="outrunner-run-facts"><div><dt>Positions</dt><dd>{run?.total || pointCount}</dd></div><div><dt>Electrical period</dt><dd>360°</dd></div><div><dt>Mechanical period</dt><dd>51.4286°</dd></div></dl>
        {run && <><progress max={run.total || 1} value={run.completed || 0} /><p role="status">{run.status}: {run.completed || 0} / {run.total || '…'} points</p></>}
        <p className="outrunner-muted">Torque uses all outer magnets and back iron as the moving body. Source material-law parity and fine cogging convergence remain under review.</p>
        {loaded && loaded.torque_Nm.length > 1 && <WaveformChart angles={loaded.angles_electrical_deg} values={loaded.torque_Nm.map((value) => value*1000)} label="Live outer-rotor torque" unit="mN·m" />}
      </div></aside>
    </div>}

    {step === 'report' && <section className="outrunner-results-standard"><header className="outrunner-results-heading"><div><span className="eyebrow">Results · local experiment</span><h1>{project.name}</h1><p>{run?.status} · {run?.completed || 0} solved points · Magneto2D</p></div>
      <button className="public-run-again-btn" onClick={() => downloadReferenceFile(`lrk-${run?.run_id}-results.json`, { project, run })}>Export results and design</button></header>
      {run?.rows?.length === 1 && analysis === 'source_point' && <div className="outrunner-result-card"><h2>Original operating point</h2>
        <strong className="outrunner-result-number">{(run.rows[0].outer_rotor_torque_Nm*1000).toFixed(4)} <small>mN·m</small></strong><p>Outer-rotor torque · CCW positive</p>
        <p>Phase linkages A/B/C: {run.rows[0].phase_linkage_Wb.map((value) => (value*1000).toFixed(6)).join(' / ')} mWb</p></div>}
      <nav className="outrunner-result-tabs" aria-label="Completed result plots" role="tablist">{[
        { id: 'torque', label: 'Torque', available: Boolean(loaded?.torque_Nm.length) },
        { id: 'bemf', label: 'Back EMF', available: Boolean(noload?.bemf_phase_V) },
        { id: 'linkage', label: 'Flux linkage', available: Boolean(noload?.phase_linkage_Wb.length) },
      ].filter((tab) => tab.available).map((tab) => <button key={tab.id} role="tab" aria-selected={resultTab === tab.id}
        className={resultTab === tab.id ? 'active' : ''} onClick={() => setResultTab(tab.id as typeof resultTab)}>{tab.label}</button>)}</nav>
      {resultTab === 'torque' && loaded && loaded.torque_Nm.length > 1 && <div className="outrunner-result-card"><h2>Fixed-current torque versus rotor angle</h2>
        <WaveformChart angles={loaded.angles_electrical_deg} values={loaded.torque_Nm.map((value) => value*1000)} label="Outer-rotor torque" unit="mN·m" samplingLabel="Actual solved points · electrical angle" />
        <p>Phase currents [A,B,C] = [{project.analysis.loaded_currents_A.join(', ')}] A stay fixed as the outer body rotates.</p></div>}
      {resultTab === 'linkage' && noload && <div className="outrunner-result-card"><h2>No-load phase flux linkage</h2>
        <WaveformChart angles={noload.angles_electrical_deg} series={series(noload.phase_linkage_Wb.map((row) => row.map((value) => value*1000)))} label="Phase flux linkage" unit="mWb" /></div>}
      {(resultTab === 'bemf' || (resultTab === 'torque' && !loaded)) && noload?.bemf_phase_V && <div className="outrunner-result-card"><h2>Back EMF · {project.analysis.speed_rpm} rpm</h2>
        <WaveformChart angles={noload.angles_electrical_deg.slice(0,-1)} series={series(noload.bemf_phase_V)} label="No-load phase EMF" unit="V" />
        <p>Phase fundamental peaks: {noload.bemf_phase_fundamental?.peak.map((value) => value.toFixed(4)).join(' / ')} V.</p>
        {noload.bemf_line_to_line_V && <WaveformChart angles={noload.angles_electrical_deg.slice(0,-1)} series={series(noload.bemf_line_to_line_V).map((item, i) => ({ ...item, label: ['A − B', 'B − C', 'C − A'][i] }))} label="Line-to-line EMF" unit="V" />}
        <p>Induced e = −ω dλ/dθ, using mechanical radians and positive CCW speed. The terminal winding connection is unspecified by the source.</p></div>}
      <p className="outrunner-muted">Frozen software reference. Numerical qualification is in progress.</p><button className="public-back-link" onClick={() => setStep('solve')}>← Back to Solve</button>
    </section>}
  </MotorWorkflowShell>;
}
