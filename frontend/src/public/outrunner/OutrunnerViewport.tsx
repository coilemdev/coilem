import { useEffect, useMemo, useState } from 'react';
import { MotorCanvas, type PublicCanvasLayer, type PublicMeshDisplayMode, type PublicMeshElementSelection } from '../MotorCanvas';
import { ReferenceMotor3D } from '../ReferenceMotor3D';
import type { MeshPreview, PublicMotorComponentSelection } from '../model';
import { summarizePublicMeshQuality } from '../meshQuality';
import { referenceGeometry, type ReferencePreview } from './geometry';
import type { OutrunnerProject } from './project';
import { OutrunnerFieldViewer } from './OutrunnerFieldViewer';
import type { RunState } from './types';
import type { PhaseDrive } from '../phaseDrive';

export function OutrunnerViewport({ preview, project, mesh = null, meshBusy = false, meshError = '', context = 'design', run = null, inspection }: {
  preview: ReferencePreview | null; project: OutrunnerProject; mesh?: MeshPreview | null; meshBusy?: boolean; meshError?: string;
  context?: 'design' | 'solve'; run?: RunState | null; inspection?: { serial: number; mode: PublicMeshDisplayMode };
}) {
  const geometry = useMemo(() => preview ? referenceGeometry(preview, project) : null, [preview, project]);
  const [view, setView] = useState<'2d' | '3d' | 'mesh' | 'field' | 'materials' | 'winding'>(context === 'solve' ? 'mesh' : '2d');
  const [layer, setLayer] = useState<PublicCanvasLayer>('none');
  const [angle, setAngle] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rpm, setRpm] = useState(18);
  const [toothPoles, setToothPoles] = useState(false);
  const drive = useMemo<PhaseDrive>(() => ({ mode: 'fixed_phase_currents',
    fixedCurrentsA: project.analysis.loaded_currents_A as [number, number, number],
    currentAmplitudeA: Math.max(...project.analysis.loaded_currents_A.map(Math.abs)),
    currentAngleDeg: 0, currentAngleReference: 'q_axis', commutationAdvanceDeg: 0, axisOffsetDeg: 0, poleCount: 14,
  }), [project.analysis.loaded_currents_A]);
  const [meshMode, setMeshMode] = useState<PublicMeshDisplayMode>('geometry');
  const [edges, setEdges] = useState(true);
  const [hoveredMesh, setHoveredMesh] = useState<PublicMeshElementSelection | null>(null);
  const quality = useMemo(() => summarizePublicMeshQuality(mesh), [mesh]);
  const [reset, setReset] = useState(0);
  const [selected, setSelected] = useState<PublicMotorComponentSelection | null>(null);
  const [navigationSlot, setNavigationSlot] = useState<HTMLSpanElement | null>(null);
  useEffect(() => { if (inspection) { setView('mesh'); setMeshMode(inspection.mode); } }, [inspection?.serial]);
  useEffect(() => {
    if (!playing || !['2d', '3d'].includes(view)) return;
    let frame = 0, last = 0;
    const animate = (time: number) => {
      if (last) setAngle((value) => (value+Math.min(.1, (time-last)/1000)*rpm*6) % 360);
      last = time; frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [playing, rpm, view]);
  useEffect(() => { if (!['2d', '3d'].includes(view)) setPlaying(false); }, [view]);
  const materials = project.fixture_data.materials as Array<{ BlockName: string; name?: string; LamFill: number; Mu_x: number }>;
  const modes = context === 'solve' ? (['2d', 'mesh', 'field'] as const) : (['2d', '3d', 'mesh', 'materials', 'winding'] as const);
  const tabs = <span className="vc-group public-primary-view-modes" role="group" aria-label={context === 'solve' ? 'Solve view' : 'Motor view mode'}>
    {modes.map((mode) => <button key={mode} className={view === mode ? 'is-active' : ''} disabled={mode === 'field' && !run?.completed}
      aria-label={`Show ${mode === '2d' ? context === 'solve' ? 'Geometry' : '2D motor' : mode === '3d' ? '3D motor' : mode === 'field' ? 'Field solution' : mode} view`}
      aria-pressed={view === mode} onClick={() => { setView(mode); setSelected(null); }}>
      {mode === '2d' ? context === 'solve' ? 'Geometry' : '2D' : mode === '3d' ? '3D' : mode === 'mesh' ? 'Mesh' : mode === 'field' ? 'Field solution' : mode === 'materials' ? 'Materials' : 'Winding'}</button>)}</span>;
  return <section className="viewport viewport-cad viewport-cad-grid public-motor-viewport outrunner-motor-viewport" aria-label="Outrunner motor viewport">
    {view !== 'field' && <div className="viewport-label viewport-label-cad">SPM 14p / 12s · outer rotor</div>}
    {view === '2d' && <><div className="public-viewport-stage public-viewport-stage-2d"><MotorCanvas geometry={geometry} mesh={null} mode="geometry"
      layer={layer} rotorAngleDeg={angle} windingType="concentrated" selectedComponent={selected} onComponentSelect={setSelected} navigationSlot={navigationSlot}
      phaseDrive={drive} showToothPoles={toothPoles} previewRpm={rpm} /></div>
      <div className="public-winding-key public-canvas-legend" aria-label="Winding phase and current direction legend">
        <span><i className="phase-a" />A</span><span><i className="phase-b" />B</span><span><i className="phase-c" />C</span><span>⊙ out · ⊗ in</span>
      </div></>}
    {view === '3d' && <div className="public-viewport-stage public-viewport-stage-3d"><ReferenceMotor3D geometry={geometry}
      resetSignal={reset} rotorAngleDeg={angle} explodedAmount={0} onComponentSelect={setSelected} /></div>}
    {view === 'mesh' && <div className="public-viewport-stage public-viewport-stage-2d"><MotorCanvas geometry={geometry} mesh={mesh} mode="mesh"
      layer="none" meshDisplayMode={meshMode} showMeshEdges={edges} meshQualities={quality.qualities} meshQualityThreshold={quality.threshold}
      navigationSlot={navigationSlot} onMeshElementHover={setHoveredMesh} />
      {(meshBusy || !mesh) && <div className="public-viewport-message" role="status">{meshError || 'Preparing native Gmsh mesh…'}</div>}
      {hoveredMesh && <div className="public-mesh-element-card"><strong>Element {hoveredMesh.index+1}</strong><span>Quality {hoveredMesh.quality.toFixed(4)}</span></div>}
    </div>}
    {view === 'field' && run && <OutrunnerFieldViewer runId={run.run_id} geometry={geometry} completed={run.completed} viewControls={tabs} />}
    {view === 'materials' && <div className="outrunner-reference-table"><h2>Source materials</h2>
      <p>The frozen source curves and magnet properties are preserved in the design file.</p>
      <table><thead><tr><th>Part</th><th>Material</th><th>Model</th></tr></thead><tbody>
        <tr><td>Stator</td><td>M-19 steel</td><td>13 B–H points · 95% fill</td></tr>
        <tr><td>Rotor</td><td>1018 steel</td><td>13 B–H points</td></tr>
        <tr><td>Magnets</td><td>NdFeB 40 MGOe</td><td>µr 1.049 · Hc 979 kA/m</td></tr>
        <tr><td>Windings</td><td>AWG22</td><td>Signed 15-turn coil sides</td></tr>
      </tbody></table><p>Effective steel law: source points with piecewise-linear interpolation. Spline-law parity remains under review.</p>
      <small>{materials.length} original material definitions retained.</small></div>}
    {view === 'winding' && <div className="outrunner-reference-table"><h2>Signed winding map</h2><p>Phase labels and turns come from the original source regions.</p>
      <table><thead><tr><th>Source region</th><th>Phase</th><th>Signed turns</th></tr></thead><tbody>{preview?.regions.filter((region) => region.phase).map((region) =>
        <tr key={region.id}><td>{region.id.replace('source_block_', '')}</td><td>{region.phase}</td><td>{region.signed_turns > 0 ? '+' : ''}{region.signed_turns}</td></tr>)}</tbody></table></div>}
    {selected && (view === '2d' || view === '3d') && <aside className="outrunner-selection"><strong>{selected.label}</strong><span>{selected.role}</span>
      <button onClick={() => setSelected(null)} aria-label="Clear selected component">×</button></aside>}
    {!geometry && <div className="public-viewport-message">Loading published geometry…</div>}
    {view !== 'field' && <div className="viewport-bottom-bar has-dock-strip">
      <div className="public-dock-strip">{tabs}
        <div className="public-dock-strip-end"><span className="viewport-cad-status">{view === 'mesh' ? mesh ? `${mesh.triangles.length.toLocaleString()} elements` : 'Preparing mesh…' : '29 source regions'}</span><span className="public-dock-nav-slot" ref={setNavigationSlot} />
          {view === '3d' && <button className="public-dock-reset-view" onClick={() => setReset((value) => value+1)}>Reset view</button>}</div>
      </div>
      <div className="viewport-controls viewport-controls-cad">
        {view === 'mesh' && <><span className="public-dock-group-label">Color by</span><span className="public-dock-segmented">
          {(['geometry', 'quality', 'problems'] as const).map((mode) => <button key={mode} aria-pressed={meshMode === mode} onClick={() => setMeshMode(mode)}>{mode === 'geometry' ? 'Regions' : mode === 'quality' ? 'Quality' : `Weak elements ${quality.weakElementIndices.length}`}</button>)}</span>
          <span className="public-dock-group-label">Show</span><button className="public-dock-toggle" aria-pressed={edges} onClick={() => setEdges((value) => !value)}>Element edges</button></>}
        {view === '2d' && <span className="vc-group"><span className="public-dock-group-label">Overlay</span>{(['none', 'slots', 'windings'] as const).map((value) =>
          <button key={value} className={layer === value ? 'is-active' : ''} aria-pressed={layer === value} onClick={() => setLayer(value)}>{value === 'none' ? 'None' : value === 'slots' ? 'Slots' : 'Winding'}</button>)}</span>}
        {(view === '2d' || view === '3d') && <><span className="public-dock-group-label">Preview</span>
          <button className="public-field-transport-play" aria-label={playing ? 'Pause motor preview' : 'Play motor preview'} aria-pressed={playing} onClick={() => setPlaying((value) => !value)}>{playing ? 'Ⅱ' : '▶'}</button>
          <button aria-label="Reset motor preview" onClick={() => { setPlaying(false); setAngle(0); }}>■</button>
          <label className="outrunner-angle-control">Speed <input className="outrunner-preview-rpm" aria-label="Preview speed (RPM)" type="number" min="1" max="300" value={rpm}
            onChange={(event) => { const value = event.target.valueAsNumber; if (Number.isFinite(value) && value > 0 && value <= 300) setRpm(value); }} />RPM</label>
          {view === '2d' && <><button className="public-dock-toggle" aria-pressed={layer === 'phases'} onClick={() => setLayer(current => current === 'phases' ? 'windings' : 'phases')}>Phases</button>
            <button className="public-dock-toggle" aria-pressed={toothPoles} onClick={() => setToothPoles(value => !value)}>Tooth poles</button></>}
          <label className="outrunner-angle-control">Rotor position <input aria-label="Rotor position CW mechanical degrees" type="range"
          min="0" max="360" step="0.1" value={angle} onChange={(event) => { setPlaying(false); setAngle(event.target.valueAsNumber); }} /><output>{angle.toFixed(1)}° CW</output></label></>}
      </div>
    </div>}
  </section>;
}
