import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { BACK_EMF_PHASE_COLORS } from './phaseColors';

interface TwoPhaseMotor3DProps {
  electricalAngleDeg: number;
  rotorAngleDeg: number;
  phaseACurrentA: number;
  phaseBCurrentA: number;
  fieldMode: 'combined' | 'stator' | 'rotor';
  showStator: boolean;
  showRotor: boolean;
  playing?: boolean;
}

interface DynamicParts {
  stator: THREE.Group;
  rotor: THREE.Group;
  phaseAMaterials: THREE.MeshStandardMaterial[];
  phaseBMaterials: THREE.MeshStandardMaterial[];
  rotorMaterials: THREE.MeshStandardMaterial[];
  targetArrow: THREE.ArrowHelper;
  phaseAArrow: THREE.ArrowHelper;
  phaseBArrow: THREE.ArrowHelper;
}

const BACKGROUND = 0x080d16;
const STEEL = 0x64748b;
const ROTOR_STEEL = 0x273449;
const NORTH = 0xef4444;
const SOUTH = 0x2563eb;
const PHASE_A = Number.parseInt(BACK_EMF_PHASE_COLORS.A.slice(1), 16);
const PHASE_B = Number.parseInt(BACK_EMF_PHASE_COLORS.B.slice(1), 16);
const RESULTANT = 0x92ba65;
const PEAK_CURRENT_A = 8;

function material(color: number, metalness = 0.48, roughness = 0.32) {
  return new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.07,
    metalness,
    roughness,
    transparent: true,
  });
}

function disposeSceneObject(object: THREE.Object3D) {
  if (!(object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.LineSegments)) return;
  object.geometry?.dispose();
  const materials = Array.isArray(object.material) ? object.material : [object.material];
  materials.forEach((item) => item.dispose());
}

function makeAnnulus(outerRadius: number, innerRadius: number, depth: number, surface: THREE.Material) {
  const shape = new THREE.Shape();
  shape.absarc(0, 0, outerRadius, 0, Math.PI * 2, false);
  const hole = new THREE.Path();
  hole.absarc(0, 0, innerRadius, 0, Math.PI * 2, true);
  shape.holes.push(hole);
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: true,
    bevelSegments: 2,
    bevelSize: 0.35,
    bevelThickness: 0.3,
    curveSegments: 96,
  });
  geometry.translate(0, 0, -depth / 2);
  return new THREE.Mesh(geometry, surface);
}

function makeAnnularSector(
  innerRadius: number,
  outerRadius: number,
  startAngle: number,
  endAngle: number,
  depth: number,
  surface: THREE.Material,
) {
  const shape = new THREE.Shape();
  shape.moveTo(outerRadius * Math.cos(startAngle), outerRadius * Math.sin(startAngle));
  shape.absarc(0, 0, outerRadius, startAngle, endAngle, false);
  shape.lineTo(innerRadius * Math.cos(endAngle), innerRadius * Math.sin(endAngle));
  shape.absarc(0, 0, innerRadius, endAngle, startAngle, true);
  shape.closePath();
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: true,
    bevelSegments: 2,
    bevelSize: 0.22,
    bevelThickness: 0.2,
    curveSegments: 64,
  });
  geometry.translate(0, 0, -depth / 2);
  return new THREE.Mesh(geometry, surface);
}

function makeWindingTurn(
  angleRad: number,
  radius: number,
  halfTangential: number,
  halfAxial: number,
  surface: THREE.Material,
) {
  const radial = new THREE.Vector3(Math.cos(angleRad), Math.sin(angleRad), 0);
  const tangent = new THREE.Vector3(-Math.sin(angleRad), Math.cos(angleRad), 0);
  const center = radial.multiplyScalar(radius);
  const cornerRadius = Math.min(halfTangential, halfAxial) * 0.32;
  const points: THREE.Vector3[] = [];
  const addCorner = (tangentCenter: number, axialCenter: number, startAngle: number) => {
    for (let step = 0; step <= 5; step += 1) {
      const cornerAngle = startAngle + step / 5 * Math.PI / 2;
      points.push(
        center.clone()
          .addScaledVector(tangent, tangentCenter + Math.cos(cornerAngle) * cornerRadius)
          .add(new THREE.Vector3(0, 0, axialCenter + Math.sin(cornerAngle) * cornerRadius)),
      );
    }
  };
  addCorner(halfTangential - cornerRadius, halfAxial - cornerRadius, 0);
  addCorner(-halfTangential + cornerRadius, halfAxial - cornerRadius, Math.PI / 2);
  addCorner(-halfTangential + cornerRadius, -halfAxial + cornerRadius, Math.PI);
  addCorner(halfTangential - cornerRadius, -halfAxial + cornerRadius, Math.PI * 1.5);
  return new THREE.Mesh(
    new THREE.TubeGeometry(
      new THREE.CatmullRomCurve3(points, true, 'centripetal'),
      72,
      0.52,
      9,
      true,
    ),
    surface,
  );
}

function addEdges(group: THREE.Group, mesh: THREE.Mesh, color = 0x94a3b8) {
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry, 24),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.42 }),
  );
  edges.position.copy(mesh.position);
  edges.rotation.copy(mesh.rotation);
  group.add(edges);
}

export const TwoPhaseMotor3D: React.FC<TwoPhaseMotor3DProps> = ({
  electricalAngleDeg,
  rotorAngleDeg,
  phaseACurrentA,
  phaseBCurrentA,
  fieldMode,
  showStator,
  showRotor,
  playing = false,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const dynamicRef = React.useRef<DynamicParts | null>(null);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BACKGROUND);
    scene.fog = new THREE.Fog(BACKGROUND, 100, 205);

    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 400);
    camera.position.set(67, 58, 78);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
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
    scene.environmentIntensity = 0.52;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.minDistance = 48;
    controls.maxDistance = 145;

    scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.35));
    const key = new THREE.DirectionalLight(0xffffff, 2.25);
    key.position.set(70, 82, 76);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x67e8f9, 1.05);
    rim.position.set(-58, 22, -65);
    scene.add(rim);
    const warm = new THREE.DirectionalLight(0xf59e0b, 0.7);
    warm.position.set(28, -42, 58);
    scene.add(warm);

    const grid = new THREE.GridHelper(150, 30, 0x1e3a5f, 0x132238);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -13;
    const gridMaterial = grid.material as THREE.Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = 0.26;
    scene.add(grid);

    const stator = new THREE.Group();
    const rotor = new THREE.Group();
    scene.add(stator, rotor);

    const steelMaterial = material(STEEL, 0.62, 0.34);
    const yoke = makeAnnulus(39, 29, 15, steelMaterial);
    yoke.castShadow = true;
    yoke.receiveShadow = true;
    stator.add(yoke);
    addEdges(stator, yoke);

    const phaseAMaterials: THREE.MeshStandardMaterial[] = [];
    const phaseBMaterials: THREE.MeshStandardMaterial[] = [];
    const toothGeometry = new THREE.BoxGeometry(13, 14, 15);
    [0, Math.PI / 2, Math.PI, Math.PI * 1.5].forEach((angle, index) => {
      const phase = index % 2 === 0 ? 'A' : 'B';
      const phaseColor = phase === 'A' ? PHASE_A : PHASE_B;
      const toothMaterial = material(phaseColor, 0.5, 0.36);
      const windingMaterial = material(phaseColor, 0.76, 0.24);
      if (phase === 'A') phaseAMaterials.push(toothMaterial, windingMaterial);
      else phaseBMaterials.push(toothMaterial, windingMaterial);

      const tooth = new THREE.Mesh(toothGeometry.clone(), toothMaterial);
      tooth.position.set(24.2 * Math.cos(angle), 24.2 * Math.sin(angle), 0);
      tooth.rotation.z = angle;
      tooth.castShadow = true;
      tooth.receiveShadow = true;
      stator.add(tooth);
      addEdges(stator, tooth, phase === 'A' ? 0xfcd34d : 0x86efac);

      for (let turn = 0; turn < 5; turn += 1) {
        const winding = makeWindingTurn(
          angle,
          27.8 + turn * 0.56,
          7.6 + turn * 0.34,
          8.9 + turn * 0.42,
          windingMaterial,
        );
        winding.castShadow = true;
        stator.add(winding);
      }
    });

    const rotorMaterials: THREE.MeshStandardMaterial[] = [];
    const rotorCoreMaterial = material(ROTOR_STEEL, 0.68, 0.28);
    rotorMaterials.push(rotorCoreMaterial);
    const rotorCore = new THREE.Mesh(new THREE.CylinderGeometry(11.4, 11.4, 18, 80), rotorCoreMaterial);
    rotorCore.rotation.x = Math.PI / 2;
    rotorCore.castShadow = true;
    rotor.add(rotorCore);

    const shaftMaterial = material(0xb9c4d4, 0.88, 0.18);
    rotorMaterials.push(shaftMaterial);
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(3.15, 3.15, 30, 48), shaftMaterial);
    shaft.rotation.x = Math.PI / 2;
    shaft.castShadow = true;
    rotor.add(shaft);

    const poleSpan = THREE.MathUtils.degToRad(132);
    const northMaterial = material(NORTH, 0.44, 0.3);
    const southMaterial = material(SOUTH, 0.44, 0.3);
    rotorMaterials.push(northMaterial, southMaterial);
    const north = makeAnnularSector(11.05, 13.5, -poleSpan / 2, poleSpan / 2, 19, northMaterial);
    const south = makeAnnularSector(11.05, 13.5, Math.PI - poleSpan / 2, Math.PI + poleSpan / 2, 19, southMaterial);
    north.castShadow = true;
    south.castShadow = true;
    rotor.add(north, south);

    const phaseAArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 1, PHASE_A, 2.3, 1.4);
    const phaseBArrow = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), new THREE.Vector3(), 1, PHASE_B, 2.3, 1.4);
    const targetArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 24, RESULTANT, 3.1, 1.9);
    [phaseAArrow, phaseBArrow, targetArrow].forEach((arrow) => {
      arrow.position.z = 13;
      scene.add(arrow);
    });

    dynamicRef.current = {
      stator,
      rotor,
      phaseAMaterials,
      phaseBMaterials,
      rotorMaterials,
      targetArrow,
      phaseAArrow,
      phaseBArrow,
    };

    const resize = () => {
      const width = Math.max(container.clientWidth, 1);
      const height = Math.max(container.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
    resize();

    let animationFrame = 0;
    const animate = () => {
      controls.update();
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(animate);
    };
    animate();

    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      controls.dispose();
      dynamicRef.current = null;
      scene.traverse(disposeSceneObject);
      gridMaterial.dispose();
      environmentTarget.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  React.useEffect(() => {
    const dynamic = dynamicRef.current;
    if (!dynamic) return;
    const statorVisible = fieldMode !== 'rotor';
    const rotorFieldVisible = fieldMode !== 'stator';
    const phaseAStrength = Math.min(1, Math.abs(phaseACurrentA) / PEAK_CURRENT_A);
    const phaseBStrength = Math.min(1, Math.abs(phaseBCurrentA) / PEAK_CURRENT_A);

    dynamic.stator.visible = showStator;
    dynamic.rotor.visible = showRotor;
    dynamic.phaseAMaterials.forEach((surface) => {
      surface.opacity = statorVisible ? 0.35 + phaseAStrength * 0.65 : 0.14;
      surface.emissiveIntensity = statorVisible ? 0.04 + phaseAStrength * 0.24 : 0.01;
    });
    dynamic.phaseBMaterials.forEach((surface) => {
      surface.opacity = statorVisible ? 0.35 + phaseBStrength * 0.65 : 0.14;
      surface.emissiveIntensity = statorVisible ? 0.04 + phaseBStrength * 0.24 : 0.01;
    });
    dynamic.rotor.rotation.z = THREE.MathUtils.degToRad(rotorAngleDeg);
    dynamic.rotorMaterials.forEach((surface) => {
      surface.opacity = rotorFieldVisible ? 1 : 0.22;
      surface.emissiveIntensity = rotorFieldVisible ? 0.08 : 0.01;
    });

    const angleRad = THREE.MathUtils.degToRad(electricalAngleDeg);
    const phaseALength = 16 * phaseAStrength;
    const phaseBLength = 16 * phaseBStrength;
    dynamic.phaseAArrow.visible = statorVisible && phaseAStrength > 0.02;
    dynamic.phaseAArrow.setDirection(new THREE.Vector3(Math.sign(phaseACurrentA) || 1, 0, 0));
    dynamic.phaseAArrow.setLength(Math.max(phaseALength, 0.01), 2.1, 1.25);
    dynamic.phaseBArrow.visible = statorVisible && phaseBStrength > 0.02;
    dynamic.phaseBArrow.setDirection(new THREE.Vector3(0, Math.sign(phaseBCurrentA) || 1, 0));
    dynamic.phaseBArrow.setLength(Math.max(phaseBLength, 0.01), 2.1, 1.25);
    dynamic.targetArrow.visible = statorVisible;
    dynamic.targetArrow.setDirection(new THREE.Vector3(Math.cos(angleRad), Math.sin(angleRad), 0));
    dynamic.targetArrow.setLength(playing ? 27 : 24, 3.1, 1.9);
  }, [
    electricalAngleDeg,
    fieldMode,
    phaseACurrentA,
    phaseBCurrentA,
    playing,
    rotorAngleDeg,
    showRotor,
    showStator,
  ]);

  return (
    <div className="two-phase-motor-three">
      <div className="two-phase-motor-three-legend" aria-hidden="true">
        <span className="is-a">Phase A · {phaseACurrentA.toFixed(1)} A</span>
        <span className="is-b">Phase B · {phaseBCurrentA.toFixed(1)} A</span>
        <span className="is-rotor">Two-pole surface PM rotor · {rotorAngleDeg.toFixed(0)}°</span>
        <em>Physical teaching view · electrical state comes from the 2D FEM checkpoint</em>
      </div>
      <div className="two-phase-motor-three-axis" aria-hidden="true">
        <span><b>Y</b> ↑</span>
        <span><b>X</b> →</span>
        <span><b>Z</b> stack ↗</span>
      </div>
      <div className="two-phase-motor-three-hint">Drag to orbit · Scroll to zoom · four wound poles surround one two-pole rotor</div>
      <div
        ref={containerRef}
        className="two-phase-motor-three-canvas"
        role="img"
        aria-label={`Interactive three-dimensional view of the Lesson 7 two-phase motor. Phase A current is ${phaseACurrentA.toFixed(1)} amperes, Phase B current is ${phaseBCurrentA.toFixed(1)} amperes, and the two-pole surface permanent-magnet rotor is at ${rotorAngleDeg.toFixed(0)} degrees.`}
      />
    </div>
  );
};
