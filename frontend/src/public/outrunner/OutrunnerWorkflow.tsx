import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { CoilEmTopBar, type PublicConnectionStatus, type PublicWorkflowStep } from '../CoilEmWorkspace';
import { MotorWorkflowShell } from '../MotorWorkflowShell';
import { RotorArrangement } from '../RotorArrangement';
import { WaveformChart } from '../WaveformChart';
import { PUBLIC_PHASE_COLORS } from '../motorPalette';
import { OutrunnerViewport } from './OutrunnerViewport';
import { OutrunnerSolveStage } from './OutrunnerSolveStage';
import { OutrunnerFieldViewer } from './OutrunnerFieldViewer';
import type { MeshPreview } from '../model';
import { referenceGeometry, type ReferencePreview } from './geometry';
import { downloadReferenceFile, type OutrunnerProject } from './project';
import type { Analysis, RunEstimate, RunState } from './types';
import { directionLabel, excitationLabel, isRunning } from './excitation';

interface Props {
  project: OutrunnerProject; geometry: ReferencePreview | null; analysis: Analysis; run: RunState | null; busy: boolean; error: string;
  mesh: MeshPreview | null; meshBusy: boolean; meshError: string; estimate: RunEstimate | null;
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
  const running = isRunning(project.analysis), direction = directionLabel(project.analysis);
  const [step, setStep] = useState<PublicWorkflowStep>('design');
  const [resultTab, setResultTab] = useState<'torque' | 'bemf' | 'linkage' | 'field'>('torque');
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
  const fieldGeometry = useMemo(() => geometry ? referenceGeometry(geometry, project) : null, [geometry, project]);
  const healthy = Boolean(geometry) && !error;

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

  return <MotorWorkflowShell topBar={<CoilEmTopBar config={{ topology: 'SPM', rotor: { pole_count: 14 }, stator: { slot_count: 12 } }}
    appVersion={props.appVersion} designName={project.name} activeStep={step} solveAvailable={Boolean(geometry)} resultReady={resultReady}
    solveRunning={busy} connectionStatus={props.connectionStatus || 'online'} onHome={props.onHome} onStepChange={setStep}
    onOpenDesignFile={props.onOpenFile} onSaveDesign={() => downloadReferenceFile('lrk-12s14p.coilem', project)} onResetDesign={props.onReset}
    showRunHistory={false} />}>
    {step === 'design' && <div className="design-workspace workflow-stage-content outrunner-standard-workspace"><div className="design-workspace-main">
      <aside className="public-parameter-panel"><div className="panel-header"><span className="panel-header-title">Design</span><span className="public-setting-pill">Reference geometry</span></div>
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
      </aside><OutrunnerViewport preview={geometry} project={project} mesh={props.mesh} meshBusy={props.meshBusy} meshError={props.meshError} /></div>{health}</div>}

    {step === 'solve' && <OutrunnerSolveStage {...props} onBack={() => setStep('design')} onResults={() => setStep('report')} />}

    {step === 'report' && <section className="outrunner-results-standard"><header className="outrunner-results-heading"><div><span className="eyebrow">Results · local experiment</span><h1>{project.name}</h1><p>{run?.status} · {run?.completed || 0} solved points · Magneto2D</p></div>
      <button className="public-run-again-btn" onClick={() => downloadReferenceFile(`lrk-${run?.run_id}-results.json`, { project, run })}>Export results and design</button></header>
      {run?.rows?.length === 1 && analysis === 'source_point' && <div className="outrunner-result-card"><h2>{running ? 'Operating point' : 'Original operating point'}</h2>
        <strong className="outrunner-result-number">{(run.rows[0].outer_rotor_torque_Nm*1000*(running ? -1 : 1)).toFixed(4)} <small>mN·m</small></strong><p>Outer-rotor torque · {direction} positive</p>
        <p>Phase linkages A/B/C: {run.rows[0].phase_linkage_Wb.map((value) => (value*1000).toFixed(6)).join(' / ')} mWb</p></div>}
      <nav className="outrunner-result-tabs" aria-label="Completed result plots" role="tablist">{[
        { id: 'torque', label: 'Torque', available: Boolean(loaded?.torque_Nm.length) },
        { id: 'bemf', label: 'Back EMF', available: Boolean(noload?.bemf_phase_V) },
        { id: 'linkage', label: 'Flux linkage', available: Boolean(noload?.phase_linkage_Wb.length) },
        { id: 'field', label: 'Field solution', available: Boolean(run?.completed) },
      ].filter((tab) => tab.available).map((tab) => <button key={tab.id} role="tab" aria-selected={resultTab === tab.id}
        className={resultTab === tab.id ? 'active' : ''} onClick={() => setResultTab(tab.id as typeof resultTab)}>{tab.label}</button>)}</nav>
      {resultTab === 'field' && run && <div className="outrunner-result-field"><OutrunnerFieldViewer runId={run.run_id} geometry={fieldGeometry} completed={run.completed} /></div>}
      {resultTab === 'torque' && loaded && loaded.torque_Nm.length > 1 && <div className="outrunner-result-card"><h2>{running ? 'Commutated torque versus rotor angle' : 'Fixed-current torque versus rotor angle'}</h2>
        <WaveformChart angles={loaded.angles_electrical_deg} values={loaded.torque_Nm.map((value) => value*1000)} label="Outer-rotor torque" unit="mN·m" samplingLabel={`Actual solved points · ${direction} electrical angle`} />
        <p>{running ? `${excitationLabel(project.analysis)} · ${project.analysis.current_amplitude_A} A ${project.analysis.current_amplitude_convention} · clockwise rotation` : `Phase currents [A,B,C] = [${project.analysis.loaded_currents_A.join(', ')}] A stay fixed as the outer body rotates.`}</p>
        {loaded.mean_torque_Nm !== undefined && <p>Mean torque: {(loaded.mean_torque_Nm*1000).toFixed(3)} mN·m · {direction} positive.</p>}</div>}
      {resultTab === 'linkage' && noload && <div className="outrunner-result-card"><h2>No-load phase flux linkage</h2>
        <WaveformChart angles={noload.angles_electrical_deg} series={series(noload.phase_linkage_Wb.map((row) => row.map((value) => value*1000)))} label="Phase flux linkage" unit="mWb" /></div>}
      {(resultTab === 'bemf' || (resultTab === 'torque' && !loaded)) && noload?.bemf_phase_V && <div className="outrunner-result-card"><h2>Back EMF · {project.analysis.speed_rpm} rpm</h2>
        <WaveformChart angles={noload.angles_electrical_deg.slice(0,-1)} series={series(noload.bemf_phase_V)} label="No-load phase EMF" unit="V" />
        <p>Phase fundamental peaks: {noload.bemf_phase_fundamental?.peak.map((value) => value.toFixed(4)).join(' / ')} V.</p>
        {noload.bemf_line_to_line_V && <WaveformChart angles={noload.angles_electrical_deg.slice(0,-1)} series={series(noload.bemf_line_to_line_V).map((item, i) => ({ ...item, label: ['A − B', 'B − C', 'C − A'][i] }))} label="Line-to-line EMF" unit="V" />}
        <p>Induced e = −ω dλ/dθ, using mechanical radians and positive {direction} speed. The terminal winding connection is unspecified by the source.</p></div>}
      <p className="outrunner-muted">Frozen software reference. Numerical qualification is in progress.</p><button className="public-back-link" onClick={() => setStep('solve')}>← Back to Solve</button>
    </section>}
  </MotorWorkflowShell>;
}
