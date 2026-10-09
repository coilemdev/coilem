import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

const PHASE_A = 0x22d3ee;
const PHASE_B = 0xf59e0b;
const CANVAS_BACKGROUND = 0x080d16;

function roundedLoopPoints(axis: 'x' | 'y'): THREE.Vector3[] {
  const transverse = 23;
  const halfLength = 45;
  const corner = 9;
  const points: THREE.Vector3[] = [];
  const push = (cross: number, z: number) => {
    points.push(axis === 'x'
      ? new THREE.Vector3(cross, 0, z)
      : new THREE.Vector3(0, cross, z));
  };

  push(-transverse, -halfLength + corner);
  push(-transverse, halfLength - corner);
  push(-transverse + corner * 0.35, halfLength - corner * 0.25);
  push(-transverse + corner, halfLength);
  push(transverse - corner, halfLength);
  push(transverse - corner * 0.35, halfLength - corner * 0.25);
  push(transverse, halfLength - corner);
  push(transverse, -halfLength + corner);
  push(transverse - corner * 0.35, -halfLength + corner * 0.25);
  push(transverse - corner, -halfLength);
  push(-transverse + corner, -halfLength);
  push(-transverse + corner * 0.35, -halfLength + corner * 0.25);
  return points;
}

function makeCoil(axis: 'x' | 'y', color: number): THREE.Mesh {
  const curve = new THREE.CatmullRomCurve3(roundedLoopPoints(axis), true, 'centripetal', 0.35);
  const geometry = new THREE.TubeGeometry(curve, 192, 2.6, 16, true);
  const material = new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.12,
    metalness: 0.72,
    roughness: 0.24,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function makeLabel(text: string, color: string): THREE.Sprite {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 96;
  const context = canvas.getContext('2d');
  if (context) {
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = 'rgba(6, 10, 18, 0.88)';
    context.strokeStyle = color;
    context.lineWidth = 3;
    context.beginPath();
    context.roundRect(5, 13, 246, 70, 14);
    context.fill();
    context.stroke();
    context.fillStyle = '#f8fafc';
    context.font = '700 34px ui-monospace, SFMono-Regular, Menlo, monospace';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(text, 128, 49);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(18, 6.75, 1);
  sprite.renderOrder = 8;
  return sprite;
}

function addSliceMarker(
  group: THREE.Group,
  position: THREE.Vector3,
  label: string,
  color: number,
  labelOffset: THREE.Vector3,
) {
  const collar = new THREE.Mesh(
    new THREE.TorusGeometry(4.25, 0.7, 12, 40),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.92 }),
  );
  collar.position.copy(position);
  group.add(collar);

  const dot = new THREE.Mesh(
    new THREE.CircleGeometry(3.35, 32),
    new THREE.MeshBasicMaterial({
      color: 0x0f172a,
      transparent: true,
      opacity: 0.92,
      side: THREE.DoubleSide,
    }),
  );
  dot.position.copy(position);
  dot.position.z += 0.08;
  group.add(dot);

  const sprite = makeLabel(label, `#${color.toString(16).padStart(6, '0')}`);
  sprite.position.copy(position).add(labelOffset);
  group.add(sprite);
}

export const RotatingFieldCoils3D: React.FC = () => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(CANVAS_BACKGROUND);
    scene.fog = new THREE.Fog(CANVAS_BACKGROUND, 180, 360);

    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 1000);
    camera.position.set(104, 82, 126);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.style.display = 'block';
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.touchAction = 'none';
    container.appendChild(renderer.domElement);

    const pmrem = new THREE.PMREMGenerator(renderer);
    const environmentTarget = pmrem.fromScene(new RoomEnvironment(), 0.04);
    scene.environment = environmentTarget.texture;
    scene.environmentIntensity = 0.52;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.minDistance = 100;
    controls.maxDistance = 260;
    controls.autoRotate = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    controls.autoRotateSpeed = 0.45;

    scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.15));
    const key = new THREE.DirectionalLight(0xffffff, 2.1);
    key.position.set(90, 130, 110);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x67e8f9, 0.95);
    rim.position.set(-100, 20, -100);
    scene.add(rim);
    const amberFill = new THREE.DirectionalLight(0xf59e0b, 0.55);
    amberFill.position.set(80, -80, 30);
    scene.add(amberFill);

    const model = new THREE.Group();
    model.rotation.x = -0.08;
    scene.add(model);

    const slice = new THREE.Mesh(
      new THREE.CircleGeometry(54, 96),
      new THREE.MeshPhysicalMaterial({
        color: 0x0e7490,
        transparent: true,
        opacity: 0.1,
        roughness: 0.3,
        metalness: 0,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    model.add(slice);

    const sliceRing = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(
        Array.from({ length: 96 }, (_, index) => {
          const angle = (index / 96) * Math.PI * 2;
          return new THREE.Vector3(Math.cos(angle) * 54, Math.sin(angle) * 54, 0.04);
        }),
      ),
      new THREE.LineBasicMaterial({ color: 0x64748b, transparent: true, opacity: 0.75 }),
    );
    model.add(sliceRing);

    const grid = new THREE.GridHelper(96, 12, 0x475569, 0x334155);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -0.08;
    const gridMaterial = grid.material as THREE.Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = 0.24;
    model.add(grid);

    model.add(makeCoil('y', PHASE_A));
    model.add(makeCoil('x', PHASE_B));

    addSliceMarker(model, new THREE.Vector3(0, 23, 0.2), 'A+', PHASE_A, new THREE.Vector3(0, 7, 2));
    addSliceMarker(model, new THREE.Vector3(0, -23, 0.2), 'A−', PHASE_A, new THREE.Vector3(0, -7, 2));
    addSliceMarker(model, new THREE.Vector3(-23, 0, 0.2), 'B+', PHASE_B, new THREE.Vector3(-7, 0, 2));
    addSliceMarker(model, new THREE.Vector3(23, 0, 0.2), 'B−', PHASE_B, new THREE.Vector3(7, 0, 2));

    const axis = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 0, -58),
        new THREE.Vector3(0, 0, 58),
      ]),
      new THREE.LineDashedMaterial({
        color: 0x94a3b8,
        dashSize: 3,
        gapSize: 2,
        transparent: true,
        opacity: 0.75,
      }),
    );
    axis.computeLineDistances();
    model.add(axis);

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
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(render);
    };
    render();

    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      controls.dispose();
      scene.traverse((object) => {
        if (
          object instanceof THREE.Mesh
          || object instanceof THREE.Line
          || object instanceof THREE.LineLoop
          || object instanceof THREE.Sprite
        ) {
          object.geometry?.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => {
            if (material instanceof THREE.SpriteMaterial) material.map?.dispose();
            material.dispose();
          });
        }
      });
      environmentTarget.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return (
    <div className="rotating-field-coils-three">
      <div className="rotating-field-coils-three-legend" aria-hidden="true">
        <span className="is-a">Phase A coil</span>
        <span className="is-b">Phase B coil</span>
        <span className="is-slice">X–Y solver slice</span>
      </div>
      <div className="rotating-field-coils-three-wiring" aria-label="Two-phase winding connections">
        <span className="is-a"><b>A+</b><i>→</i><em>Phase A winding</em><i>→</i><b>A−</b></span>
        <span className="is-b"><b>B+</b><i>→</i><em>Phase B winding</em><i>→</i><b>B−</b></span>
        <small>+ and − define positive current reference. AC reverses each half-cycle.</small>
      </div>
      <div className="rotating-field-coils-three-hint">Drag to orbit · Scroll to zoom · dashed axis is Z</div>
      <div
        ref={containerRef}
        className="rotating-field-coils-three-canvas"
        role="img"
        aria-label="Interactive three-dimensional view of two perpendicular closed coils crossing the X–Y solver slice"
      />
    </div>
  );
};
