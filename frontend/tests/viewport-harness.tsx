/** Browser-only fixtures for canvas interaction; never imported by the production entry point. */
import { createRoot } from 'react-dom/client';
import { useState, type CSSProperties } from 'react';
import { MotorCanvas } from '../src/public/MotorCanvas';
import { SolvedFieldViewer } from '../src/public/SolvedFieldViewer';
import { DEFAULT_CONFIG, type MeshPreview, type PublicFieldLinePlot, type SolveResult } from '../src/public/model';
import { useLayerMenu } from '../src/public/useLayerMenu';
import '../src/styles/variables.css';
import '../src/public/styles.css';

document.documentElement.dataset.theme = 'coilem-amber';
document.documentElement.dataset.skin = 'fable';

const mesh: MeshPreview = {
  nodes_mm: [[-10, -10], [10, -10], [10, 10], [-10, 10], [7, 0], [9, 0], [8, 2], [-8, 0], [-6, 0], [-7, 2]],
  triangles: [[4, 5, 6], [7, 8, 9]],
  regions: ['rotor_core', 'stator_tooth'],
  mesh_info: {}, mesh_qa: {}, generation_time_ms: 0,
};
const denseMesh: MeshPreview = {
  ...mesh,
  triangles: Array.from({ length: 20_000 }, (_, index) => mesh.triangles[index % 2]),
  regions: Array.from({ length: 20_000 }, (_, index) => mesh.regions[index % 2]),
};
const plot: PublicFieldLinePlot = {
  nodes_mm: mesh.nodes_mm,
  triangles: mesh.triangles,
  regions: mesh.regions,
  element_b_mag_t: [1, 1.5],
  element_bx_t: [0.6, 0.9],
  element_by_t: [0.8, 1.2],
  contour_levels: [{ level: 0, segments_mm: [[-10, -10, 10, 10]] }],
  az_min: 0, az_max: 1, n_pole_pitches: 8, total_span_deg: 360,
};
const result = { field_line_plot: plot } as SolveResult;
const smallConfig = {
  ...DEFAULT_CONFIG,
  stator: { ...DEFAULT_CONFIG.stator, OD_mm: 20, ID_mm: 12, yoke_thickness_mm: 2 },
  rotor: { ...DEFAULT_CONFIG.rotor, OD_mm: 10, magnet_thickness_mm: 0.5 },
};
const root = createRoot(document.getElementById('root')!);
const state = { selection: null as unknown };

function MeshMenu() {
  const menu = useLayerMenu();
  return <div className="public-live-stage" style={{ width: 900, height: 650 }}>
    <section className="viewport public-motor-viewport" style={{ width: '100%', height: '100%', '--viewport-dock-height': '186px' } as CSSProperties}>
      <div className="viewport-bottom-bar has-dock-strip">
        <div className="public-dock-strip">Mesh</div>
        <div className="viewport-controls viewport-controls-cad">
          <span className="vc-group">Regions · Quality · Weak elements</span>
          <span className="public-dock-row-break" />
          <span className="vc-group">Overlay · Slots · Tooth · Winding</span>
          <details className="public-field-layer-menu public-dock-more" {...menu}>
            <summary>More</summary>
            <div className="public-field-layer-controls" role="group" aria-label="More mesh layers">
              <button type="button">Magnifier</button>
              <button type="button">Tooth poles</button>
              <button type="button">Coil colors</button>
            </div>
          </details>
          <span className="public-dock-row-break" />
          <span className="vc-group">Spin</span>
        </div>
      </div>
    </section>
  </div>;
}

function renderMesh(angle: number, width = 600, height = 600, dense = false) {
  root.render(<section className="public-motor-viewport" style={{ width, height }}>
    <MotorCanvas geometry={null} mesh={dense ? denseMesh : mesh} mode="mesh" layer="none" rotorAngleDeg={angle}
      onMeshElementSelect={(hit) => { state.selection = hit; }} />
  </section>);
}

function DockedMagnifier({ field }: { field: boolean }) {
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  const [probeSlot, setProbeSlot] = useState<HTMLDivElement | null>(null);
  const [enabled, setEnabled] = useState(false);
  return <div style={{ display: 'flex', gap: 12, width: 1120, height: 700 }}>
    <section className="public-motor-viewport" style={{ width: 740, height: 700 }}>
      {field ? <SolvedFieldViewer magnifierSlot={slot} probeSlot={probeSlot} viewControls="Field solution" config={smallConfig} geometry={null} result={result}
        armature={null} armatureBusy={false} armatureError={null} magnetoCompositionAvailable={false} onRequestArmature={() => {}} />
        : <><button type="button" aria-label="Toggle mesh magnifier" onClick={() => setEnabled(value => !value)}>Magnifier</button>
          <div style={{ height: 600 }}><MotorCanvas geometry={null} mesh={mesh} mode="mesh" layer="none" magnifier={enabled} magnifierSlot={slot} /></div></>}
    </section>
    <aside className="public-run-plan" style={{ width: 360, minWidth: 360 }}>
      <div className="public-run-plan-scroll">
        <div className="mesh-panel-header">Run plan</div>
        <div className="public-run-magnifier-slot" ref={setSlot} />
        <div className="public-run-field-data-slot" ref={setProbeSlot} />
        <div className="public-run-plan-section" style={{ minHeight: 1000 }}>Analysis</div>
      </div>
    </aside>
  </div>;
}

Object.assign(window, { viewportTest: { renderMesh, state } });
const mode = new URLSearchParams(location.search).get('view');
if (mode === 'field') {
  root.render(<div style={{ width: 1100, height: 700 }}>
    <SolvedFieldViewer viewControls="Field solution" config={DEFAULT_CONFIG} geometry={null} result={result}
      armature={null} armatureBusy={false} armatureError={null} magnetoCompositionAvailable={false} onRequestArmature={() => {}} />
  </div>);
} else if (mode === 'docked-field' || mode === 'docked-mesh') root.render(<DockedMagnifier field={mode === 'docked-field'} />);
else if (mode === 'mesh-menu') root.render(<MeshMenu />);
else renderMesh(90);
