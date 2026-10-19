import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { PUBLIC_API_BASE } from './api';
import type { GeometryPreview, MotorConfig, PublicMotorComponentSelection } from './model';
import { PUBLIC_PHASE_COLORS } from './motorPalette';
import { addMotorStudioLighting, motorMagnetMaterial, motorSteelMaterial, phaseMaterial } from './motor3DStyle';
import { MOTOR_3D_FOV, motor3DCameraOffset } from './motor3DCamera';
import { extrudePreviewRegion } from './referenceMotorGeometry';

type Part = 'stator' | 'windings' | 'rotor' | 'magnets' | 'airgap';
const PARTS: Array<{ id: Part; label: string }> = [
  { id: 'stator', label: 'Stator' }, { id: 'windings', label: 'Windings' },
  { id: 'rotor', label: 'Rotor' }, { id: 'magnets', label: 'Magnets' }, { id: 'airgap', label: 'Air gap' },
];
interface Props {
  config: MotorConfig;
  geometry?: GeometryPreview | null;
  resetSignal: number;
  rotorAngleDeg: number;
  explodedAmount: number;
  introProgress?: number | null;
  onInteraction?: () => void;
  onComponentSelect?: (selection: PublicMotorComponentSelection | null) => void;
}

/** An extrusion of the imported reference, including the bore and all HoleM50 cavities. */
export function ReferenceMotor3D(props: Props) {
  const { config, geometry, resetSignal } = props;
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const latest = useRef(props);
  latest.current = props;
  const renderRef = useRef<(() => void) | null>(null);
  const resetRef = useRef<(() => void) | null>(null);
  const [fetched, setFetched] = useState<{ config: MotorConfig; preview: GeometryPreview } | null>(null);
  const [error, setError] = useState('');
  const [hidden, setHidden] = useState<ReadonlySet<Part>>(() => new Set());
  const hiddenRef = useRef(hidden);
  hiddenRef.current = hidden;
  const preview = geometry === undefined ? (fetched?.config === config ? fetched.preview : null) : geometry;

  useEffect(() => {
    if (geometry !== undefined) return;
    const abort = new AbortController();
    setError('');
    void fetch(`${PUBLIC_API_BASE}/preview`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config), signal: abort.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error('Reference geometry preview could not be loaded.');
      const value = await response.json() as GeometryPreview;
      if (!abort.signal.aborted) setFetched({ config, preview: value });
    }).catch((e: Error) => { if (!abort.signal.aborted) setError(e.message); });
    return () => abort.abort();
  }, [config, geometry]);

  useEffect(() => {
    const host = hostRef.current, canvas = canvasRef.current;
    if (!host || !canvas || !preview) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); }
    catch { setError('3D preview is unavailable on this graphics device.'); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(MOTOR_3D_FOV, 1, .1, 10000);
    const radius = config.stator.OD_mm / 2, depth = config.stator.stack_length_mm;
    const assembled = new THREE.Vector3(...motor3DCameraOffset(config));
    const controls = new OrbitControls(camera, canvas);
    controls.enablePan = true;
    controls.minDistance = radius * 1.2;
    controls.maxDistance = radius * 12;
    const reset = () => { camera.position.copy(assembled); controls.target.set(0, 0, 0); controls.update(); };
    reset();
    resetRef.current = reset;
    const disposeStudio = addMotorStudioLighting(renderer, scene, radius);
    const groups = Object.fromEntries(PARTS.map(({ id }) => [id, new THREE.Group()])) as Record<Part, THREE.Group>;
    const rotor = new THREE.Group();
    rotor.add(groups.rotor, groups.magnets);
    scene.add(groups.stator, groups.windings, groups.airgap, rotor);
    const meshes: THREE.Mesh[] = [];
    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.Material[] = [];
    try {
      preview.regions.forEach((region, regionIndex) => {
        const type = region.region_type;
        let part: Part, material: THREE.MeshPhysicalMaterial;
        if (/^stator/.test(type)) { part = 'stator'; material = motorSteelMaterial('stator'); }
        else if (type === 'rotor_core') { part = 'rotor'; material = motorSteelMaterial('rotor'); }
        else if (/^magnet_[ns]_/.test(type)) {
          part = 'magnets'; material = motorMagnetMaterial(type.startsWith('magnet_n_') ? 'N' : 'S');
        } else if (/^slot_/.test(type)) {
          part = 'windings';
          const phase = type.match(/\(([abc])/i)?.[1].toUpperCase() as keyof typeof PUBLIC_PHASE_COLORS | undefined;
          material = phaseMaterial(phase ? PUBLIC_PHASE_COLORS[phase] : '#c77b30');
        } else if (type === 'airgap') {
          part = 'airgap'; material = new THREE.MeshPhysicalMaterial({
            color: '#5ee7f7', emissive: 0x063a42, metalness: 0, roughness: .18,
            transparent: true, opacity: .09, depthWrite: false, clearcoat: .8, clearcoatRoughness: .1,
          });
        }
        else return; // Pockets remain empty holes in the rotor steel.
        const shape = extrudePreviewRegion(region, depth);
        geometries.push(shape);
        materials.push(material);
        const mesh = new THREE.Mesh(shape, material);
        mesh.castShadow = part !== 'airgap';
        mesh.receiveShadow = part !== 'airgap';
        const kind = part === 'magnets' ? 'magnet' : part === 'windings' ? 'winding' : part;
        const selection: PublicMotorComponentSelection = {
          id: `region-${regionIndex}`, regionIndex, regionType: type, kind,
          label: region.label ?? type, role: part === 'magnets' ? 'Permanent-magnet field source' : 'Published reference cross-section',
        };
        mesh.userData.selection = selection;
        groups[part].add(mesh);
        if (part !== 'airgap') meshes.push(mesh);
        const edgesGeometry = new THREE.EdgesGeometry(shape, 35);
        const edgesMaterial = new THREE.LineBasicMaterial({ color: 0x18202a, transparent: true, opacity: .5 });
        geometries.push(edgesGeometry); materials.push(edgesMaterial);
        if (part !== 'airgap') mesh.add(new THREE.LineSegments(edgesGeometry, edgesMaterial));
      });
      setError('');
    } catch (e) { setError((e as Error).message); }
    let frame = 0;
    const render = () => {
      frame = 0;
      const state = latest.current;
      rotor.rotation.z = -state.rotorAngleDeg * Math.PI / 180;
      const explode = THREE.MathUtils.clamp(state.explodedAmount, 0, 1);
      groups.stator.position.z = -depth * 1.25 * explode;
      groups.windings.position.z = -depth * .2 * explode;
      groups.magnets.position.z = depth * .85 * explode;
      groups.rotor.position.z = depth * 1.9 * explode;
      PARTS.forEach(({ id }) => { groups[id].visible = !hiddenRef.current.has(id); });
      const intro = state.introProgress;
      if (intro != null) {
        camera.position.lerpVectors(assembled, new THREE.Vector3(0, 0, radius * 3.6), intro);
        camera.lookAt(0, 0, 0);
      }
      renderer.render(scene, camera);
    };
    const requestRender = () => { if (!frame) frame = requestAnimationFrame(render); };
    renderRef.current = requestRender;
    controls.addEventListener('change', requestRender);
    const resize = new ResizeObserver(() => {
      const { width, height } = host.getBoundingClientRect();
      renderer.setSize(width, height, false); camera.aspect = width / Math.max(height, 1); camera.updateProjectionMatrix(); requestRender();
    });
    resize.observe(host);
    let down = [0, 0];
    const onDown = (e: PointerEvent) => { down = [e.clientX, e.clientY]; latest.current.onInteraction?.(); };
    const onWheel = () => latest.current.onInteraction?.();
    const onUp = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
      const rect = canvas.getBoundingClientRect();
      const pointer = new THREE.Vector2((e.clientX - rect.left) / rect.width * 2 - 1, -(e.clientY - rect.top) / rect.height * 2 + 1);
      const ray = new THREE.Raycaster(); ray.setFromCamera(pointer, camera);
      const hit = ray.intersectObjects(meshes, false).find(({ object }) => object.parent?.visible);
      latest.current.onComponentSelect?.(hit?.object.userData.selection ?? null);
    };
    canvas.addEventListener('pointerdown', onDown); canvas.addEventListener('pointerup', onUp); canvas.addEventListener('wheel', onWheel);
    requestRender();
    return () => {
      cancelAnimationFrame(frame); resize.disconnect(); controls.dispose();
      canvas.removeEventListener('pointerdown', onDown); canvas.removeEventListener('pointerup', onUp); canvas.removeEventListener('wheel', onWheel);
      renderRef.current = null; resetRef.current = null;
      geometries.forEach((item) => item.dispose()); materials.forEach((item) => item.dispose()); disposeStudio(); renderer.dispose();
    };
  }, [preview, config]);

  useEffect(() => { renderRef.current?.(); }, [hidden, props.rotorAngleDeg, props.explodedAmount, props.introProgress]);
  useEffect(() => { if (resetSignal > 0) { resetRef.current?.(); renderRef.current?.(); } }, [resetSignal]);
  return <div className="public-motor-3d-stage" ref={hostRef} aria-label="Interactive 3D motor view">
    <canvas ref={canvasRef} />
    {props.introProgress == null && <div className="public-3d-part-toggles" role="group" aria-label="Show or hide motor parts">
      {PARTS.map(({ id, label }) => <button key={id} type="button"
        className={`public-3d-part-toggle${hidden.has(id) ? ' is-off' : ''}`} aria-pressed={!hidden.has(id)}
        title={`${hidden.has(id) ? 'Show' : 'Hide'} ${label.toLowerCase()}`}
        onClick={() => setHidden((current) => { const next = new Set(current); if (!next.delete(id)) next.add(id); return next; })}>{label}</button>)}
    </div>}
    <div className="public-3d-hint">Reference cross-section · click a part · drag to orbit · wheel to zoom</div>
    {(error || !preview) && <div className="public-viewport-message">{error || 'Loading reference geometry…'}</div>}
  </div>;
}
