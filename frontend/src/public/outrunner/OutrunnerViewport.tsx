import { useMemo, useState } from 'react';
import { MotorCanvas, type PublicCanvasLayer } from '../MotorCanvas';
import { ReferenceMotor3D } from '../ReferenceMotor3D';
import type { PublicMotorComponentSelection } from '../model';
import { referenceGeometry, type ReferencePreview } from './geometry';
import type { OutrunnerProject } from './project';

export function OutrunnerViewport({ preview, project }: { preview: ReferencePreview | null; project: OutrunnerProject }) {
  const geometry = useMemo(() => preview ? referenceGeometry(preview, project) : null, [preview, project]);
  const [view, setView] = useState<'2d' | '3d' | 'materials' | 'winding'>('2d');
  const [layer, setLayer] = useState<PublicCanvasLayer>('none');
  const [angle, setAngle] = useState(0);
  const [reset, setReset] = useState(0);
  const [selected, setSelected] = useState<PublicMotorComponentSelection | null>(null);
  const [navigationSlot, setNavigationSlot] = useState<HTMLSpanElement | null>(null);
  const materials = project.fixture_data.materials as Array<{ BlockName: string; name?: string; LamFill: number; Mu_x: number }>;
  return <section className="viewport viewport-cad viewport-cad-grid public-motor-viewport outrunner-motor-viewport" aria-label="Outrunner motor viewport">
    <div className="viewport-label viewport-label-cad">SPM 14p / 12s · outer rotor</div>
    {view === '2d' && <><div className="public-viewport-stage public-viewport-stage-2d"><MotorCanvas geometry={geometry} mesh={null} mode="geometry"
      layer={layer} rotorAngleDeg={-angle} windingType="concentrated" selectedComponent={selected} onComponentSelect={setSelected} navigationSlot={navigationSlot} /></div>
      <div className="public-winding-key public-canvas-legend" aria-label="Winding phase and current direction legend">
        <span><i className="phase-a" />A</span><span><i className="phase-b" />B</span><span><i className="phase-c" />C</span><span>⊙ out · ⊗ in</span>
      </div></>}
    {view === '3d' && <div className="public-viewport-stage public-viewport-stage-3d"><ReferenceMotor3D geometry={geometry}
      resetSignal={reset} rotorAngleDeg={-angle} explodedAmount={0} onComponentSelect={setSelected} /></div>}
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
    <div className="viewport-bottom-bar has-dock-strip">
      <div className="public-dock-strip"><span className="vc-group public-primary-view-modes" role="group" aria-label="Motor view mode">
        {(['2d', '3d', 'materials', 'winding'] as const).map((mode) => <button key={mode} className={view === mode ? 'is-active' : ''}
          aria-label={`Show ${mode === '2d' ? '2D motor' : mode === '3d' ? '3D motor' : mode} view`} aria-pressed={view === mode}
          onClick={() => { setView(mode); setSelected(null); }}>{mode === '2d' ? '2D' : mode === '3d' ? '3D' : mode === 'materials' ? 'Materials' : 'Winding'}</button>)}</span>
        <div className="public-dock-strip-end"><span className="viewport-cad-status">29 source regions</span><span className="public-dock-nav-slot" ref={setNavigationSlot} />
          {view === '3d' && <button className="public-dock-reset-view" onClick={() => setReset((value) => value+1)}>Reset view</button>}</div>
      </div>
      <div className="viewport-controls viewport-controls-cad">
        {view === '2d' && <span className="vc-group"><span className="public-dock-group-label">Overlay</span>{(['none', 'slots', 'windings'] as const).map((value) =>
          <button key={value} className={layer === value ? 'is-active' : ''} aria-pressed={layer === value} onClick={() => setLayer(value)}>{value === 'none' ? 'None' : value === 'slots' ? 'Slots' : 'Winding'}</button>)}</span>}
        {(view === '2d' || view === '3d') && <label className="outrunner-angle-control">Rotor position <input aria-label="Rotor position CCW mechanical degrees" type="range"
          min="0" max={360/7} step="0.1" value={angle} onChange={(event) => setAngle(event.target.valueAsNumber)} /><output>{angle.toFixed(1)}° CCW</output></label>}
      </div>
    </div>
  </section>;
}
