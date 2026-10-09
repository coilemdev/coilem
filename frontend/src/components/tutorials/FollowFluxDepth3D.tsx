import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type { FollowFluxFieldData, FollowFluxMetrics } from './lessonSolveTypes';
import './follow-flux-three.css';

interface FollowFluxDepth3DProps {
  data: FollowFluxFieldData;
  depthMm: number;
  metrics: FollowFluxMetrics;
  onDepthChange: (depthMm: number) => void;
  onUnavailable?: () => void;
}

const MAGNET_WIDTH_MM = 36;
const MAGNET_HEIGHT_MM = 12;
const BACKGROUND = 0x07101f;
const STEEL_DIMENSIONS = {
  bar: { widthMm: 8, heightMm: 28 },
  plate: { widthMm: 28, heightMm: 8 },
  puck: { widthMm: 16, heightMm: 16 },
} as const;

function addEdges(target: THREE.Group, mesh: THREE.Mesh, color: number) {
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry, 24),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.58 }),
  );
  edges.position.copy(mesh.position);
  edges.rotation.copy(mesh.rotation);
  target.add(edges);
}

function labelPlane(text: string, color: string, textures: THREE.Texture[]) {
  const canvas = document.createElement('canvas');
  canvas.width = 192;
  canvas.height = 192;
  const context = canvas.getContext('2d');
  if (context) {
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = color;
    context.font = '800 112px system-ui, sans-serif';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(text, canvas.width / 2, canvas.height / 2 + 6);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  textures.push(texture);
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    depthWrite: false,
    side: THREE.FrontSide,
  });
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(6, 6), material);
  plane.renderOrder = 8;
  return plane;
}

function addMagnet(
  target: THREE.Group,
  xMm: number,
  yMm: number,
  angleDeg: number,
  depthMm: number,
  textures: THREE.Texture[],
) {
  const magnet = new THREE.Group();
  magnet.position.set(xMm, yMm, 0);
  magnet.rotation.z = angleDeg * Math.PI / 180;
  target.add(magnet);

  const south = new THREE.Mesh(
    new THREE.BoxGeometry(MAGNET_WIDTH_MM / 2, MAGNET_HEIGHT_MM, depthMm),
    new THREE.MeshStandardMaterial({
      color: 0x2563eb,
      emissive: 0x172554,
      emissiveIntensity: 0.16,
      metalness: 0.34,
      roughness: 0.3,
    }),
  );
  south.position.x = -MAGNET_WIDTH_MM / 4;
  south.castShadow = true;
  south.receiveShadow = true;
  magnet.add(south);
  addEdges(magnet, south, 0x93c5fd);

  const north = new THREE.Mesh(
    new THREE.BoxGeometry(MAGNET_WIDTH_MM / 2, MAGNET_HEIGHT_MM, depthMm),
    new THREE.MeshStandardMaterial({
      color: 0xef4444,
      emissive: 0x7f1d1d,
      emissiveIntensity: 0.14,
      metalness: 0.34,
      roughness: 0.3,
    }),
  );
  north.position.x = MAGNET_WIDTH_MM / 4;
  north.castShadow = true;
  north.receiveShadow = true;
  magnet.add(north);
  addEdges(magnet, north, 0xfca5a5);

  const southLabel = labelPlane('S', '#eff6ff', textures);
  southLabel.position.set(-MAGNET_WIDTH_MM / 4, 0, depthMm / 2 + 0.08);
  magnet.add(southLabel);
  const northLabel = labelPlane('N', '#fff7ed', textures);
  northLabel.position.set(MAGNET_WIDTH_MM / 4, 0, depthMm / 2 + 0.08);
  magnet.add(northLabel);

  return magnet;
}

function addSteel(target: THREE.Group, data: FollowFluxFieldData, depthMm: number) {
  const steel = new THREE.Group();
  steel.position.set(data.steel_center_x_mm, data.steel_center_y_mm, 0);
  steel.rotation.z = data.steel_angle_deg * Math.PI / 180;
  target.add(steel);
  const dimensions = STEEL_DIMENSIONS[data.steel_shape];
  const material = new THREE.MeshStandardMaterial({
    color: 0x64748b,
    emissive: 0x0f172a,
    emissiveIntensity: 0.04,
    metalness: 0.62,
    roughness: 0.31,
  });
  const geometry = data.steel_shape === 'puck'
    ? new THREE.CylinderGeometry(dimensions.widthMm / 2, dimensions.widthMm / 2, depthMm, 48)
    : new THREE.BoxGeometry(dimensions.widthMm, dimensions.heightMm, depthMm);
  const body = new THREE.Mesh(geometry, material);
  if (data.steel_shape === 'puck') body.rotation.x = Math.PI / 2;
  body.castShadow = true;
  body.receiveShadow = true;
  steel.add(body);
  addEdges(steel, body, 0xcbd5e1);
}

function addFluxSurface(target: THREE.Group, data: FollowFluxFieldData, depthMm: number) {
  const surfaceGroup = new THREE.Group();
  surfaceGroup.position.set(data.magnet_center_x_mm, data.magnet_center_y_mm, 0);
  surfaceGroup.rotation.z = data.magnet_angle_deg * Math.PI / 180;
  target.add(surfaceGroup);
  const geometry = new THREE.PlaneGeometry(depthMm, MAGNET_HEIGHT_MM);
  const surface = new THREE.Mesh(
    geometry,
    new THREE.MeshBasicMaterial({
      color: 0x22d3ee,
      transparent: true,
      opacity: 0.22,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  surface.rotation.y = Math.PI / 2;
  surface.position.x = MAGNET_WIDTH_MM / 2 + 0.12;
  surface.renderOrder = 5;
  surfaceGroup.add(surface);
  const border = new THREE.LineSegments(
    new THREE.EdgesGeometry(geometry),
    new THREE.LineBasicMaterial({ color: 0x67e8f9, transparent: true, opacity: 0.95 }),
  );
  border.rotation.copy(surface.rotation);
  border.position.copy(surface.position);
  border.renderOrder = 6;
  surfaceGroup.add(border);
}

function addSolvedField(
  target: THREE.Group,
  data: FollowFluxFieldData,
  depthMm: number,
  animatedMaterials: Array<{ material: THREE.LineBasicMaterial; baseOpacity: number }>,
) {
  const levels = data.contour_levels ?? [];
  const levelStep = Math.max(1, Math.ceil(levels.length / 14));
  const selectedLevels = levels.filter((_, index) => index % levelStep === 0);
  const slices = depthMm < 8 ? [0] : [-depthMm / 2 + 0.6, 0, depthMm / 2 - 0.6];
  slices.forEach((zMm, sliceIndex) => {
    selectedLevels.forEach((level, selectedIndex) => {
      const segmentStep = Math.max(1, Math.ceil(level.segments_mm.length / 180));
      const points: THREE.Vector3[] = [];
      for (let index = 0; index < level.segments_mm.length; index += segmentStep) {
        const [x1, y1, x2, y2] = level.segments_mm[index];
        points.push(new THREE.Vector3(x1, y1, zMm), new THREE.Vector3(x2, y2, zMm));
      }
      if (points.length === 0) return;
      const centralSlice = Math.abs(zMm) < 0.01;
      const material = new THREE.LineBasicMaterial({
        color: selectedIndex % 3 === 0 ? 0x67e8f9 : 0x3b82f6,
        transparent: true,
        opacity: centralSlice ? 0.5 : 0.2,
        depthWrite: false,
      });
      const lines = new THREE.LineSegments(
        new THREE.BufferGeometry().setFromPoints(points),
        material,
      );
      lines.renderOrder = centralSlice ? 4 : 2;
      target.add(lines);
      animatedMaterials.push({ material, baseOpacity: centralSlice ? 0.5 : 0.2 });
    });
  });

  const arrowCandidates: Array<{ origin: THREE.Vector3; direction: THREE.Vector3 }> = [];
  selectedLevels.forEach((level) => {
    const step = Math.max(1, Math.ceil(level.segments_mm.length / 3));
    for (let index = Math.floor(step / 2); index < level.segments_mm.length; index += step) {
      const [x1, y1, x2, y2] = level.segments_mm[index];
      const bx = level.segment_bx_t?.[index];
      const by = level.segment_by_t?.[index];
      const direction = bx !== undefined && by !== undefined
        ? new THREE.Vector3(bx, by, 0)
        : new THREE.Vector3(x2 - x1, y2 - y1, 0);
      if (direction.lengthSq() < 1e-8) continue;
      arrowCandidates.push({
        origin: new THREE.Vector3((x1 + x2) / 2, (y1 + y2) / 2, depthMm / 2 + 0.7),
        direction: direction.normalize(),
      });
    }
  });
  const arrowStep = Math.max(1, Math.ceil(arrowCandidates.length / 18));
  arrowCandidates.filter((_, index) => index % arrowStep === 0).slice(0, 18).forEach(({ origin, direction }) => {
    const arrow = new THREE.ArrowHelper(direction, origin, 4.5, 0xa5f3fc, 1.6, 0.95);
    arrow.line.renderOrder = 7;
    arrow.cone.renderOrder = 7;
    target.add(arrow);
  });
}

function formatMicroWebers(value?: number) {
  return value === undefined ? '—' : `${(value * 1e6).toFixed(1)} µWb`;
}

export const FollowFluxDepth3D: React.FC<FollowFluxDepth3DProps> = ({
  data,
  depthMm,
  metrics,
  onDepthChange,
  onUnavailable,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const resetViewRef = React.useRef<() => void>(() => undefined);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BACKGROUND);
    let xMin = Number.POSITIVE_INFINITY;
    let xMax = Number.NEGATIVE_INFINITY;
    let yMin = Number.POSITIVE_INFINITY;
    let yMax = Number.NEGATIVE_INFINITY;
    data.nodes_mm.forEach(([x, y]) => {
      xMin = Math.min(xMin, x);
      xMax = Math.max(xMax, x);
      yMin = Math.min(yMin, y);
      yMax = Math.max(yMax, y);
    });
    if (!Number.isFinite(xMin)) {
      xMin = -60;
      xMax = 60;
      yMin = -45;
      yMax = 45;
    }
    const center = new THREE.Vector3((xMin + xMax) / 2, (yMin + yMax) / 2, 0);
    const span = Math.max(xMax - xMin, yMax - yMin, 80);
    scene.fog = new THREE.Fog(BACKGROUND, span * 1.65, span * 3.2);

    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, span * 8);
    const initialCameraPosition = new THREE.Vector3(
      center.x + span * 0.88,
      center.y + span * 0.58,
      span * 1.08,
    );
    camera.position.copy(initialCameraPosition);

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      onUnavailable?.();
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.domElement.style.display = 'block';
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.touchAction = 'none';
    container.appendChild(renderer.domElement);

    const pmrem = new THREE.PMREMGenerator(renderer);
    const environmentTarget = pmrem.fromScene(new RoomEnvironment(), 0.04);
    scene.environment = environmentTarget.texture;
    scene.environmentIntensity = 0.5;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(center);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.minDistance = span * 0.42;
    controls.maxDistance = span * 2.9;
    controls.minPolarAngle = 0.12;
    controls.maxPolarAngle = Math.PI - 0.12;
    controls.update();
    resetViewRef.current = () => {
      camera.position.copy(initialCameraPosition);
      controls.target.copy(center);
      controls.update();
    };

    scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.22));
    const key = new THREE.DirectionalLight(0xffffff, 2.35);
    key.position.set(center.x + span, center.y + span, span * 1.3);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x67e8f9, 1.25);
    rim.position.set(center.x - span, center.y, -span);
    scene.add(rim);

    const model = new THREE.Group();
    scene.add(model);
    const labelTextures: THREE.Texture[] = [];
    const animatedMaterials: Array<{ material: THREE.LineBasicMaterial; baseOpacity: number }> = [];
    addSolvedField(model, data, depthMm, animatedMaterials);
    addMagnet(
      model,
      data.magnet_center_x_mm,
      data.magnet_center_y_mm,
      data.magnet_angle_deg,
      depthMm,
      labelTextures,
    );
    if (data.magnet2_enabled) {
      addMagnet(
        model,
        data.magnet2_center_x_mm ?? 20,
        data.magnet2_center_y_mm ?? 0,
        data.magnet2_angle_deg ?? 0,
        depthMm,
        labelTextures,
      );
    }
    if (data.steel_return) addSteel(model, data, depthMm);
    if (metrics.north_face_flux_wb !== undefined) addFluxSurface(model, data, depthMm);

    const grid = new THREE.GridHelper(span * 1.35, 24, 0x334155, 0x1e293b);
    grid.rotation.x = Math.PI / 2;
    grid.position.set(center.x, center.y, -depthMm / 2 - 2.5);
    const gridMaterial = grid.material as THREE.Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = 0.24;
    scene.add(grid);

    const axes = new THREE.AxesHelper(Math.min(22, span * 0.18));
    axes.position.set(xMin + span * 0.12, yMin + span * 0.1, -depthMm / 2);
    scene.add(axes);

    const resize = () => {
      const width = Math.max(container.clientWidth, 1);
      const height = Math.max(container.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);

    let animationFrame = 0;
    const startedAt = performance.now();
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const render = () => {
      const pulse = reduceMotion
        ? 1
        : 0.88 + Math.sin((performance.now() - startedAt) * 0.0024) * 0.12;
      animatedMaterials.forEach(({ material, baseOpacity }) => {
        material.opacity = baseOpacity * pulse;
      });
      controls.update();
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(render);
    };
    render();

    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      resetViewRef.current = () => undefined;
      controls.dispose();
      scene.traverse((object) => {
        if (
          object instanceof THREE.Mesh
          || object instanceof THREE.Line
          || object instanceof THREE.LineSegments
          || object instanceof THREE.GridHelper
        ) {
          object.geometry?.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => material.dispose());
        }
      });
      labelTextures.forEach((texture) => texture.dispose());
      environmentTarget.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [data, depthMm, metrics.north_face_flux_wb, onUnavailable]);

  const fixtureLabel = data.magnet2_enabled
    ? 'Two magnets'
    : data.steel_return ? 'Magnet + steel' : 'Open air';

  return (
    <section id="follow-flux-depth-inset" className="follow-flux-depth-three" aria-label="Interactive three-dimensional field depth view">
      <div className="follow-flux-depth-three-legend" aria-hidden="true">
        <strong>{fixtureLabel}</strong>
        <span className="is-magnet">N / S magnet</span>
        {data.steel_return ? <span className="is-steel">M350-50A steel</span> : null}
        <span className="is-field">Solved field</span>
        <span className="is-surface">Flux surface</span>
      </div>
      <button type="button" className="follow-flux-depth-three-reset" onClick={() => resetViewRef.current()}>
        Reset view
      </button>
      <div
        ref={containerRef}
        className="follow-flux-depth-three-canvas"
        role="img"
        aria-label={`Interactive three-dimensional ${fixtureLabel.toLowerCase()} view with ${depthMm} millimeters of physical depth, solved field contours repeated through the stack, and a north-face flux surface`}
      />
      <div className="follow-flux-depth-three-hint">Drag to orbit · Scroll to zoom · 2D FEM repeated through Z</div>
      <div className="follow-flux-depth-three-controls">
        <label>
          <span><strong>Stack depth</strong><em>{depthMm} mm</em></span>
          <input
            type="range"
            min={5}
            max={20}
            step={1}
            value={depthMm}
            onInput={(event) => onDepthChange(Number(event.currentTarget.value))}
            aria-label={`Physical stack depth ${depthMm} millimeters`}
          />
        </label>
        <div className="follow-flux-depth-three-readout" aria-live="polite">
          <span><b>|B|</b> solved in 2D</span>
          <span><b>Area</b> {metrics.north_face_area_mm2?.toFixed(0) ?? '—'} mm²</span>
          <span><b>&Phi;</b> {formatMicroWebers(metrics.north_face_flux_wb)}</span>
        </div>
      </div>
    </section>
  );
};
