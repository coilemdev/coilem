import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

interface MotorEffectLoop3DProps {
  currentA: number;
  fieldT: number;
  sideForceN: number;
  loopAngleDeg: number;
  torqueNm: number;
}

const BACKGROUND = 0x080d16;
const LOOP_HALF_WIDTH = 8;
const LOOP_BACK_Z = 13;
const LOOP_FRONT_Z = -18;
const LEAD_Z = -25;

function disposeSceneObject(object: THREE.Object3D) {
  if (object instanceof THREE.Sprite) {
    object.material.map?.dispose();
    object.material.dispose();
    return;
  }
  if (!(object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.LineSegments)) return;
  object.geometry?.dispose();
  const materials = Array.isArray(object.material) ? object.material : [object.material];
  materials.forEach((material) => material.dispose());
}

function addArrow(
  group: THREE.Group,
  direction: THREE.Vector3,
  origin: THREE.Vector3,
  length: number,
  color: number,
  headLength = 2.4,
) {
  group.add(new THREE.ArrowHelper(
    direction.clone().normalize(),
    origin,
    length,
    color,
    headLength,
    headLength * 0.6,
  ));
}

function openHorizontalLoopCurve() {
  const points = [
    new THREE.Vector3(-2, 0, LEAD_Z),
    new THREE.Vector3(-2, 0, LOOP_FRONT_Z),
    new THREE.Vector3(-LOOP_HALF_WIDTH, 0, LOOP_FRONT_Z),
    new THREE.Vector3(-LOOP_HALF_WIDTH, 0, LOOP_BACK_Z),
    new THREE.Vector3(LOOP_HALF_WIDTH, 0, LOOP_BACK_Z),
    new THREE.Vector3(LOOP_HALF_WIDTH, 0, LOOP_FRONT_Z),
    new THREE.Vector3(2, 0, LOOP_FRONT_Z),
    new THREE.Vector3(2, 0, LEAD_Z),
  ];
  return new THREE.CatmullRomCurve3(points, false, 'catmullrom', 0.05);
}

function makeTextSprite(text: string, color: string) {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 96;
  const context = canvas.getContext('2d');
  if (!context) return null;
  context.fillStyle = 'rgba(3, 7, 18, 0.88)';
  context.beginPath();
  context.roundRect(8, 8, 240, 80, 16);
  context.fill();
  context.strokeStyle = color;
  context.lineWidth = 4;
  context.stroke();
  context.fillStyle = color;
  context.font = '700 44px ui-monospace, SFMono-Regular, Menlo, monospace';
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText(text, 128, 49);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
  }));
  sprite.scale.set(6.4, 2.4, 1);
  return sprite;
}

export const MotorEffectLoop3D: React.FC<MotorEffectLoop3DProps> = ({
  currentA,
  fieldT,
  sideForceN,
  loopAngleDeg,
  torqueNm,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BACKGROUND);
    scene.fog = new THREE.Fog(BACKGROUND, 92, 210);

    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 400);
    camera.position.set(8, 50, -78);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    renderer.shadowMap.enabled = true;
    renderer.domElement.style.display = 'block';
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.touchAction = 'none';
    container.appendChild(renderer.domElement);

    const pmrem = new THREE.PMREMGenerator(renderer);
    const environmentTarget = pmrem.fromScene(new RoomEnvironment(), 0.04);
    scene.environment = environmentTarget.texture;
    scene.environmentIntensity = 0.55;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, -3);
    controls.enableDamping = true;
    controls.enablePan = false;
    controls.minDistance = 38;
    controls.maxDistance = 145;

    scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.45));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(55, 75, 70);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x67e8f9, 1.1);
    rim.position.set(-60, 15, -55);
    scene.add(rim);

    const model = new THREE.Group();
    model.rotation.x = -0.04;
    scene.add(model);
    const loopAssembly = new THREE.Group();
    const loopRotationRad = THREE.MathUtils.degToRad(loopAngleDeg - 90);
    loopAssembly.rotation.z = loopRotationRad;
    model.add(loopAssembly);

    const northMaterial = new THREE.MeshStandardMaterial({
      color: 0xef4444,
      emissive: 0x991b1b,
      emissiveIntensity: 0.12,
      metalness: 0.38,
      roughness: 0.3,
    });
    const southMaterial = new THREE.MeshStandardMaterial({
      color: 0x2563eb,
      emissive: 0x1e3a8a,
      emissiveIntensity: 0.12,
      metalness: 0.38,
      roughness: 0.3,
    });
    const poleGeometry = new THREE.BoxGeometry(18, 34, 18);
    const leftPole = new THREE.Mesh(poleGeometry.clone(), northMaterial);
    leftPole.position.x = -24;
    leftPole.castShadow = true;
    leftPole.receiveShadow = true;
    model.add(leftPole);
    const rightPole = new THREE.Mesh(poleGeometry.clone(), southMaterial);
    rightPole.position.x = 24;
    rightPole.castShadow = true;
    rightPole.receiveShadow = true;
    model.add(rightPole);

    const loopCurve = openHorizontalLoopCurve();
    const copperMaterial = new THREE.MeshStandardMaterial({
      color: 0xd97706,
      emissive: 0x92400e,
      emissiveIntensity: 0.18,
      metalness: 0.74,
      roughness: 0.22,
    });
    const loop = new THREE.Mesh(
      new THREE.TubeGeometry(loopCurve, 190, 1.05, 18, false),
      copperMaterial,
    );
    loop.castShadow = true;
    loop.receiveShadow = true;
    loopAssembly.add(loop);

    const positive = currentA >= 0;
    const sourcePositiveMaterial = new THREE.MeshStandardMaterial({
      color: 0xdc2626,
      emissive: 0x7f1d1d,
      emissiveIntensity: 0.2,
      metalness: 0.42,
      roughness: 0.3,
    });
    const sourceNegativeMaterial = new THREE.MeshStandardMaterial({
      color: 0x2563eb,
      emissive: 0x1e3a8a,
      emissiveIntensity: 0.2,
      metalness: 0.42,
      roughness: 0.3,
    });
    const sourceGeometry = new THREE.BoxGeometry(4, 3.4, 5.2);
    const leftSource = new THREE.Mesh(
      sourceGeometry.clone(),
      positive ? sourcePositiveMaterial : sourceNegativeMaterial,
    );
    leftSource.position.set(-2.1, 0, -29);
    loopAssembly.add(leftSource);
    const rightSource = new THREE.Mesh(
      sourceGeometry.clone(),
      positive ? sourceNegativeMaterial : sourcePositiveMaterial,
    );
    rightSource.position.set(2.1, 0, -29);
    loopAssembly.add(rightSource);
    const leftLabel = makeTextSprite(positive ? '+V' : '−', positive ? '#fca5a5' : '#93c5fd');
    if (leftLabel) {
      leftLabel.position.set(-3.5, 4, -29);
      loopAssembly.add(leftLabel);
    }
    const rightLabel = makeTextSprite(positive ? '−' : '+V', positive ? '#93c5fd' : '#fca5a5');
    if (rightLabel) {
      rightLabel.position.set(3.5, 4, -29);
      loopAssembly.add(rightLabel);
    }

    const fieldLength = 31;
    [-5, 1, 7].forEach((y) => {
      [-10, 0, 10].forEach((z) => {
        addArrow(
          model,
          new THREE.Vector3(1, 0, 0),
          new THREE.Vector3(-fieldLength / 2, y, z),
          fieldLength,
          0x67e8f9,
          1.8,
        );
      });
    });

    const leftCurrentDirection = new THREE.Vector3(0, 0, positive ? 1 : -1);
    const rightCurrentDirection = new THREE.Vector3(0, 0, positive ? -1 : 1);
    addArrow(
      loopAssembly,
      leftCurrentDirection,
      new THREE.Vector3(-LOOP_HALF_WIDTH, 1.4, positive ? -10 : 10),
      16,
      0xfbbf24,
      2.2,
    );
    addArrow(
      loopAssembly,
      rightCurrentDirection,
      new THREE.Vector3(LOOP_HALF_WIDTH, 1.4, positive ? 10 : -10),
      16,
      0xfbbf24,
      2.2,
    );

    const leftForceDirection = new THREE.Vector3(0, positive ? 1 : -1, 0);
    const rightForceDirection = new THREE.Vector3(0, positive ? -1 : 1, 0);
    const leftForceOrigin = new THREE.Vector3(-LOOP_HALF_WIDTH, 0, 0)
      .applyAxisAngle(new THREE.Vector3(0, 0, 1), loopRotationRad)
      .add(new THREE.Vector3(0, positive ? 1.5 : -1.5, 0));
    const rightForceOrigin = new THREE.Vector3(LOOP_HALF_WIDTH, 0, 0)
      .applyAxisAngle(new THREE.Vector3(0, 0, 1), loopRotationRad)
      .add(new THREE.Vector3(0, positive ? -1.5 : 1.5, 0));
    addArrow(
      model,
      leftForceDirection,
      leftForceOrigin,
      13,
      0xf59e0b,
      3,
    );
    addArrow(
      model,
      rightForceDirection,
      rightForceOrigin,
      13,
      0xf59e0b,
      3,
    );
    addArrow(
      loopAssembly,
      new THREE.Vector3(0, positive ? 1 : -1, 0),
      new THREE.Vector3(0, positive ? 1.5 : -1.5, 0),
      10,
      0xa5f3fc,
      2.4,
    );

    const beadMaterial = new THREE.MeshStandardMaterial({
      color: 0xfef3c7,
      emissive: 0xfbbf24,
      emissiveIntensity: 0.75,
      roughness: 0.18,
    });
    const beads = Array.from({ length: 8 }, () => {
      const bead = new THREE.Mesh(new THREE.SphereGeometry(0.7, 14, 10), beadMaterial);
      loopAssembly.add(bead);
      return bead;
    });

    const grid = new THREE.GridHelper(92, 18, 0x334155, 0x1e293b);
    grid.position.y = -18;
    const gridMaterial = grid.material as THREE.Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = 0.28;
    scene.add(grid);

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

    const startedAt = performance.now();
    let animationFrame = 0;
    const render = (now: number) => {
      const elapsed = (now - startedAt) / 1000;
      const direction = currentA >= 0 ? 1 : -1;
      beads.forEach((bead, index) => {
        const progress = ((index / beads.length) + direction * elapsed * 0.08 + 10) % 1;
        bead.position.copy(loopCurve.getPointAt(progress));
      });
      controls.update();
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(render);
    };
    animationFrame = window.requestAnimationFrame(render);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      controls.dispose();
      scene.traverse(disposeSceneObject);
      poleGeometry.dispose();
      sourceGeometry.dispose();
      environmentTarget.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [currentA, loopAngleDeg]);

  const positive = currentA >= 0;
  const torqueDirection = Math.abs(torqueNm) < 1e-9 ? '0' : torqueNm > 0 ? '+Z' : '−Z';
  const referenceMomentAngleDeg = (loopAngleDeg + (positive ? 0 : 180)) % 360;

  return (
    <div className="field-force-three motor-effect-three">
      <div className="field-force-three-legend" aria-hidden="true">
        <span className="is-magnet">N42 poles · B +X</span>
        <span className="is-copper">Horizontal copper loop · {Math.abs(currentA).toFixed(0)} A</span>
        <span className="is-voltage">Applied voltage · separated +V / − leads</span>
        <span className="is-area">Magnetic moment angle {referenceMomentAngleDeg}° · reference δ {loopAngleDeg}°</span>
        <span className="is-force">Opposite force pair · torque about {torqueDirection}</span>
        <em>B {fieldT.toFixed(3)} T · F each {(sideForceN * 1e3).toFixed(1)} mN · τ {(torqueNm * 1e3).toFixed(2)} mN·m</em>
      </div>
      <div className="field-force-three-axis" aria-hidden="true">
        <span><b>Y</b> ↑ loop area / force</span>
        <span><b>X</b> → field</span>
        <span><b>Z</b> ↗ active-side current / torque axis</span>
      </div>
      <div className="field-force-three-hint">Drag to orbit · glowing beads travel from +V through the open loop to −V</div>
      <div
        ref={containerRef}
        className="field-force-three-canvas"
        role="img"
        aria-label={`Interactive three-dimensional motor-effect loop at reference torque angle ${loopAngleDeg} degrees. The actual magnetic moment is at ${referenceMomentAngleDeg} degrees from the field after current polarity is applied. Two separated feed leads apply voltage across the open loop; the active copper sides carry opposite Z-direction currents, experience equal opposite Y-direction forces of ${(sideForceN * 1e3).toFixed(1)} millinewtons, and produce ${(torqueNm * 1e3).toFixed(2)} millinewton meters about ${torqueDirection}.`}
      />
    </div>
  );
};
