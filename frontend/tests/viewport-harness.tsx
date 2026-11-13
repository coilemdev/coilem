/** Browser-only fixtures for canvas interaction; never imported by the production entry point. */
import { createRoot } from 'react-dom/client';
import { useState, type CSSProperties } from 'react';
import { MotorCanvas } from '../src/public/MotorCanvas';
import { SolvedFieldViewer } from '../src/public/SolvedFieldViewer';
import { WindingLayoutView } from '../src/public/WindingLayoutView';
import { phaseDriveFrame } from '../src/public/phaseDrive';
import { DEFAULT_CONFIG, type GeometryPreview, type MaterialCatalog, type MeshPreview, type PublicFieldLinePlot, type SolveResult } from '../src/public/model';
import m350Curve from '../../materials/electrical-steel/M350-50A.csv?raw';
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
const materialCatalog = {
  models: { 'M350-50A': { curve: { points: m350Curve.split('\n')
    .filter(line => line && !line.startsWith('#') && !line.startsWith('B_T'))
    .map(line => line.split(',').map(Number)).map(([b, h]) => [h, b]) } } },
} as MaterialCatalog;
const saturatedResult = { field_line_plot: { ...plot,
  element_b_mag_t: [2.133, 1.65], element_bx_t: [1.2798, 0.99], element_by_t: [1.7064, 1.32],
} } as SolveResult;
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

function DockedMagnifier({ field, fieldResult = result }: { field: boolean; fieldResult?: SolveResult }) {
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  const [probeSlot, setProbeSlot] = useState<HTMLDivElement | null>(null);
  const [enabled, setEnabled] = useState(false);
  return <div style={{ display: 'flex', gap: 12, width: 1120, height: 700 }}>
    <section className="public-motor-viewport" style={{ width: 740, height: 700 }}>
      {field ? <SolvedFieldViewer magnifierSlot={slot} probeSlot={probeSlot} viewControls="Field solution" config={smallConfig} materials={materialCatalog} geometry={null} result={fieldResult}
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

const circle = (radius: number): Array<[number, number]> => Array.from({ length: 80 }, (_, i) => [radius * Math.cos(i * Math.PI / 40), radius * Math.sin(i * Math.PI / 40)]);
const phaseGeometry: GeometryPreview = {
  regions: [{ region_type: 'stator_yoke', points: circle(10) }, { region_type: 'rotor_core', points: circle(5) }],
  metadata: { stator_od_mm: 20, rotor_od_mm: 10, slot_count: 12, pole_count: 8 },
  validation_errors: [], generation_time_ms: 0,
};
const windingConfig = { ...DEFAULT_CONFIG, stator: { ...DEFAULT_CONFIG.stator, slot_count: 54 }, rotor: { ...DEFAULT_CONFIG.rotor, pole_count: 18 } };
const windingGeometry = { ...phaseGeometry, regions: [],
  winding_layout: Array.from({ length: 54 }, (_, slot_index) => ({ slot_index, phase: ['A', 'B', 'C'][Math.floor(slot_index / 2) % 3], direction: slot_index % 2 ? 'in' : 'out', layer: 1 })),
  winding_coils: Array.from({ length: 27 }, (_, coil_index) => ({ coil_index, slot_in: coil_index * 2, slot_out: coil_index * 2 + 1, phase: ['A', 'B', 'C'][coil_index % 3], polarity: 1, layer: 1, tooth_wound: true })),
} as GeometryPreview;
function WindingHarness() {
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  return <section className="public-motor-viewport" style={{ width: 1100, height: 700 }}>
    <WindingLayoutView config={windingConfig} geometry={windingGeometry} navigationSlot={slot} />
    <div ref={setSlot} />
  </section>;
}

Object.assign(window, { viewportTest: { renderMesh, state, phaseDriveFrame } });
const mode = new URLSearchParams(location.search).get('view');
if (mode === 'field') {
  root.render(<div style={{ width: 1100, height: 700 }}>
    <SolvedFieldViewer viewControls="Field solution" config={DEFAULT_CONFIG} geometry={null} result={result}
      armature={null} armatureBusy={false} armatureError={null} magnetoCompositionAvailable={false} onRequestArmature={() => {}} />
  </div>);
} else if (mode === 'saturated-field') root.render(<DockedMagnifier field fieldResult={saturatedResult} />);
else if (mode === 'winding') root.render(<WindingHarness />);
else if (mode === 'phases') root.render(<section className="public-motor-viewport" style={{ width: 1100, height: 700 }}>
  <MotorCanvas config={smallConfig} geometry={phaseGeometry} mode="geometry" layer="phases" onComponentSelect={selection => { state.selection = selection; }} />
</section>);
else if (mode === 'docked-field' || mode === 'docked-mesh') root.render(<DockedMagnifier field={mode === 'docked-field'} />);
else if (mode === 'mesh-menu') root.render(<MeshMenu />);
else renderMesh(90);
