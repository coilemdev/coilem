import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type {
  ThreePhaseMotorFieldComponent,
  ThreePhaseMotorFrameData,
} from './lessonSolveTypes';

interface ThreePhaseMotor3DProps {
  frameData: ThreePhaseMotorFrameData;
  fieldMode: ThreePhaseMotorFieldComponent;
  showFieldIntensity?: boolean;
  fieldIntensityRange?: Readonly<{ low: number; high: number }>;
  playing?: boolean;
}

interface DynamicSceneParts {
  fieldOverlay: THREE.Group;
  rotor: THREE.Group;
  rotorMaterials: THREE.MeshStandardMaterial[];
  phaseMaterials: Record<'A' | 'B' | 'C', THREE.MeshStandardMaterial[]>;
  targetArrow: THREE.ArrowHelper;
}

const BACKGROUND = 0x080d16;
const STEEL = 0x64748b;
const ROTOR_STEEL = 0x263244;
const NORTH = 0xef4444;
const SOUTH = 0x2563eb;
const PHASE_COLORS = {
  A: 0xf0a030,
  B: 0x34d399,
  C: 0xa78bfa,
} as const;
const POLE_PHASES: Array<keyof typeof PHASE_COLORS> = ['A', 'C', 'B', 'A', 'C', 'B'];
const FIELD_INTENSITY_COLORS = [
  '#30123b',
  '#4145ab',
  '#4675ed',
  '#39a2fc',
  '#1bcdd4',
  '#24f894',
  '#7dff5f',
  '#c1f334',
  '#f8ca25',
  '#f39411',
  '#e64c02',
  '#a21401',
] as const;

function finiteOr(value: number | null | undefined, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function disposeSceneObject(object: THREE.Object3D) {
  if (!(object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.LineSegments)) return;
  object.geometry?.dispose();
  const materials = Array.isArray(object.material) ? object.material : [object.material];
  materials.forEach((material) => material.dispose());
}

function clearGroup(group: THREE.Group) {
  group.traverse(disposeSceneObject);
  group.clear();
}

function fieldIntensityColor(value: number, low: number, high: number) {
  const normalized = THREE.MathUtils.clamp((value - low) / Math.max(high - low, 1e-9), 0, 1);
  const palettePosition = normalized * (FIELD_INTENSITY_COLORS.length - 1);
  const lowerIndex = Math.floor(palettePosition);
  const upperIndex = Math.min(FIELD_INTENSITY_COLORS.length - 1, Math.ceil(palettePosition));
  return new THREE.Color(FIELD_INTENSITY_COLORS[lowerIndex]).lerp(
    new THREE.Color(FIELD_INTENSITY_COLORS[upperIndex]),
    palettePosition - lowerIndex,
  );
}

function resolvedFieldIntensityRange(
  frameData: ThreePhaseMotorFrameData,
  requestedRange?: Readonly<{ low: number; high: number }>,
) {
  if (
    requestedRange
    && Number.isFinite(requestedRange.low)
    && Number.isFinite(requestedRange.high)
    && requestedRange.high > requestedRange.low
  ) {
    return requestedRange;
  }
  const values = (frameData.element_b_mag_t ?? [])
    .filter((value) => Number.isFinite(value) && value >= 0)
    .sort((left, right) => left - right);
  if (!values.length) return null;
  return {
    low: values[Math.floor((values.length - 1) * 0.03)],
    high: values[Math.floor((values.length - 1) * 0.98)],
  };
}

function populateFieldOverlay(
  group: THREE.Group,
  frameData: ThreePhaseMotorFrameData,
  depthMm: number,
  requestedRange?: Readonly<{ low: number; high: number }>,
) {
  clearGroup(group);
  const values = frameData.element_b_mag_t;
  const range = resolvedFieldIntensityRange(frameData, requestedRange);
  if (!values || values.length !== frameData.triangles.length || !range) return;

  const positions: number[] = [];
  const colors: number[] = [];
  frameData.triangles.forEach((triangle, triangleIndex) => {
    const region = frameData.regions[triangleIndex];
    const isStator = region === 'three_phase_stator_pole';
    const isRotor = region === 'three_phase_rotor_magnet';
    const fieldValue = values[triangleIndex];
    if ((!isStator && !isRotor) || !Number.isFinite(fieldValue)) return;

    const nodes = triangle.map((nodeIndex) => frameData.nodes_mm[nodeIndex]);
    if (nodes.some((node) => !node)) return;
    const color = fieldIntensityColor(fieldValue, range.low, range.high);
    const surfaceZ = (isRotor ? depthMm * 1.18 : depthMm) / 2 + 0.06;
    const addFace = (nodeOrder: readonly number[], z: number) => {
      nodeOrder.forEach((nodeOffset) => {
        const [x, y] = nodes[nodeOffset];
        positions.push(x, y, z);
        colors.push(color.r, color.g, color.b);
      });
    };
    addFace([0, 1, 2], surfaceZ);
    addFace([2, 1, 0], -surfaceZ);
  });
  if (!positions.length) return;

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  geometry.computeBoundingSphere();
  const material = new THREE.MeshBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.84,
    depthTest: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    polygonOffset: true,
    polygonOffsetFactor: -2,
    polygonOffsetUnits: -2,
  });
  const overlay = new THREE.Mesh(geometry, material);
  overlay.name = 'Solved FEM |B| overlay';
  overlay.renderOrder = 6;
  group.add(overlay);
}

function makeMaterial(
  color: number,
  metalness = 0.5,
  roughness = 0.32,
) {
  return new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.07,
    metalness,
    roughness,
    transparent: true,
  });
}

function addEdges(group: THREE.Group, mesh: THREE.Mesh, color = 0x94a3b8) {
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry, 25),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.42 }),
  );
  edges.position.copy(mesh.position);
  edges.rotation.copy(mesh.rotation);
  group.add(edges);
}

function makeAnnulus(
  outerRadius: number,
  innerRadius: number,
  depth: number,
  material: THREE.Material,
) {
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
  return new THREE.Mesh(geometry, material);
}

function makeWindingTurn(
  angleRad: number,
  radius: number,
  halfTangential: number,
  halfAxial: number,
  material: THREE.Material,
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
      0.42,
      8,
      true,
    ),
    material,
  );
}

export const ThreePhaseMotor3D: React.FC<ThreePhaseMotor3DProps> = ({
  frameData,
  fieldMode,
  showFieldIntensity = false,
  fieldIntensityRange,
  playing = false,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const dynamicRef = React.useRef<DynamicSceneParts | null>(null);

  const depthMm = 11;
  const rotorRadius = Math.max(finiteOr(frameData.rotor_radius_mm, 6), 4);
  const coreInner = Math.max(finiteOr(frameData.core_inner_mm, 12), rotorRadius + 3);
  const coreOuter = Math.max(finiteOr(frameData.core_outer_mm, 28), coreInner + 8);
  const coreHalfWidth = Math.max(finiteOr(frameData.core_half_width_mm, 3.3), 2.4);
  const toothLength = coreOuter - coreInner;
  const yokeInnerRadius = coreOuter - 0.4;
  const yokeOuterRadius = coreOuter + 5.2;
  const coilRadius = Math.max(
    Math.min(finiteOr(frameData.coil_center_mm, coreInner + toothLength * 0.56), coreOuter - 1.6),
    coreInner + 2,
  );

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BACKGROUND);
    scene.fog = new THREE.Fog(BACKGROUND, 100, 210);

    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 500);
    camera.position.set(62, -68, 62);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.06;
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
    scene.environmentIntensity = 0.5;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.minDistance = 34;
    controls.maxDistance = 155;

    scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.35));
    const key = new THREE.DirectionalLight(0xffffff, 2.15);
    key.position.set(70, -50, 90);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x67e8f9, 1.05);
    rim.position.set(-60, 30, -45);
    scene.add(rim);
    const copperFill = new THREE.DirectionalLight(0xf59e0b, 0.55);
    copperFill.position.set(30, 45, 30);
    scene.add(copperFill);

    const model = new THREE.Group();
    model.rotation.x = -0.04;
    scene.add(model);
    const fieldOverlay = new THREE.Group();
    fieldOverlay.visible = false;
    model.add(fieldOverlay);

    const steelMaterial = makeMaterial(STEEL, 0.68, 0.34);
    const yoke = makeAnnulus(yokeOuterRadius, yokeInnerRadius, depthMm, steelMaterial);
    yoke.castShadow = true;
    yoke.receiveShadow = true;
    model.add(yoke);

    const phaseMaterials: DynamicSceneParts['phaseMaterials'] = { A: [], B: [], C: [] };
    for (let poleIndex = 0; poleIndex < 6; poleIndex += 1) {
      const angleRad = poleIndex / 6 * Math.PI * 2;
      const phase = POLE_PHASES[poleIndex];
      const phaseCoreMaterial = makeMaterial(PHASE_COLORS[phase], 0.72, 0.28);
      const core = new THREE.Mesh(
        new THREE.BoxGeometry(toothLength + 1.4, coreHalfWidth * 2, depthMm),
        phaseCoreMaterial,
      );
      core.position.set(
        (coreInner + toothLength / 2) * Math.cos(angleRad),
        (coreInner + toothLength / 2) * Math.sin(angleRad),
        0,
      );
      core.rotation.z = angleRad;
      core.castShadow = true;
      core.receiveShadow = true;
      model.add(core);
      addEdges(model, core);

      const windingMaterial = makeMaterial(PHASE_COLORS[phase], 0.62, 0.25);
      phaseMaterials[phase].push(windingMaterial);
      [-1.45, -0.5, 0.5, 1.45].forEach((offset) => {
        const turn = makeWindingTurn(
          angleRad,
          coilRadius + offset,
          coreHalfWidth + 1.25,
          depthMm / 2 + 1.5,
          windingMaterial,
        );
        turn.castShadow = true;
        model.add(turn);
      });
    }

    const rotor = new THREE.Group();
    model.add(rotor);
    const rotorSteelMaterial = makeMaterial(ROTOR_STEEL, 0.72, 0.28);
    const rotorHub = new THREE.Mesh(
      new THREE.CylinderGeometry(rotorRadius * 1.08, rotorRadius * 1.08, depthMm * 1.08, 64),
      rotorSteelMaterial,
    );
    rotorHub.rotation.x = Math.PI / 2;
    rotorHub.castShadow = true;
    rotorHub.receiveShadow = true;
    rotor.add(rotorHub);

    const rotorMaterials = [makeMaterial(SOUTH), makeMaterial(NORTH)];
    const magnetLength = rotorRadius * 1.72;
    const magnetWidth = rotorRadius * 0.72;
    [-1, 1].forEach((side, index) => {
      const magnet = new THREE.Mesh(
        new THREE.BoxGeometry(magnetLength / 2, magnetWidth, depthMm * 1.18),
        rotorMaterials[index],
      );
      magnet.position.x = side * magnetLength / 4;
      magnet.castShadow = true;
      magnet.receiveShadow = true;
      rotor.add(magnet);
      addEdges(rotor, magnet, index === 0 ? 0x93c5fd : 0xfca5a5);
    });

    const shaft = new THREE.Mesh(
      new THREE.CylinderGeometry(rotorRadius * 0.24, rotorRadius * 0.24, depthMm * 2.2, 40),
      makeMaterial(0xcbd5e1, 0.92, 0.18),
    );
    shaft.rotation.x = Math.PI / 2;
    shaft.castShadow = true;
    rotor.add(shaft);

    const targetArrow = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(-rotorRadius * 0.2, 0, depthMm / 2 + 4),
      rotorRadius * 2.5,
      0x67e8f9,
      2.4,
      1.5,
    );
    model.add(targetArrow);

    const floor = new THREE.GridHelper(92, 18, 0x334155, 0x1e293b);
    floor.rotation.x = Math.PI / 2;
    floor.position.z = -depthMm / 2 - 7;
    const floorMaterial = floor.material as THREE.Material;
    floorMaterial.transparent = true;
    floorMaterial.opacity = 0.22;
    scene.add(floor);

    dynamicRef.current = {
      fieldOverlay,
      rotor,
      rotorMaterials,
      phaseMaterials,
      targetArrow,
    };

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
      dynamicRef.current = null;
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      controls.dispose();
      scene.traverse(disposeSceneObject);
      environmentTarget.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [
    coilRadius,
    coreHalfWidth,
    coreInner,
    depthMm,
    rotorRadius,
    toothLength,
    yokeInnerRadius,
    yokeOuterRadius,
  ]);

  React.useEffect(() => {
    const dynamic = dynamicRef.current;
    if (!dynamic) return;

    const phaseCurrents = {
      A: frameData.phase_a_current_a,
      B: frameData.phase_b_current_a,
      C: frameData.phase_c_current_a,
    };
    (Object.keys(dynamic.phaseMaterials) as Array<keyof typeof dynamic.phaseMaterials>).forEach((phase) => {
      const phaseMode = `phase_${phase.toLowerCase()}` as ThreePhaseMotorFieldComponent;
      const sourceVisible = fieldMode !== 'rotor'
        && (fieldMode === 'combined'
          || fieldMode === 'stator'
          || fieldMode === 'open_c'
          || fieldMode === phaseMode);
      const strength = Math.min(1, Math.abs(phaseCurrents[phase]) / Math.max(frameData.peak_current_a, 0.1));
      dynamic.phaseMaterials[phase].forEach((phaseMaterial) => {
        phaseMaterial.opacity = sourceVisible ? 0.42 + 0.58 * strength : 0.16;
        phaseMaterial.emissiveIntensity = sourceVisible ? 0.04 + 0.25 * strength : 0.01;
      });
    });

    const rotorVisible = fieldMode === 'combined' || fieldMode === 'rotor' || fieldMode === 'open_c';
    dynamic.rotor.rotation.z = frameData.rotor_angle_deg * Math.PI / 180;
    dynamic.rotorMaterials.forEach((rotorMaterial) => {
      rotorMaterial.opacity = rotorVisible ? 1 : 0.25;
      rotorMaterial.emissiveIntensity = rotorVisible ? 0.09 : 0.01;
    });

    const targetVisible = fieldMode !== 'rotor';
    const targetAngleRad = frameData.field_target_angle_deg * Math.PI / 180;
    dynamic.targetArrow.visible = targetVisible;
    dynamic.targetArrow.position.set(
      -rotorRadius * 0.2 * Math.cos(targetAngleRad),
      -rotorRadius * 0.2 * Math.sin(targetAngleRad),
      depthMm / 2 + 4,
    );
    dynamic.targetArrow.setDirection(new THREE.Vector3(
      Math.cos(targetAngleRad),
      Math.sin(targetAngleRad),
      0,
    ));
    dynamic.targetArrow.setLength(
      rotorRadius * (playing ? 2.75 : 2.5),
      2.4,
      1.5,
    );

    dynamic.fieldOverlay.visible = showFieldIntensity;
    if (showFieldIntensity) {
      populateFieldOverlay(dynamic.fieldOverlay, frameData, depthMm, fieldIntensityRange);
    } else {
      clearGroup(dynamic.fieldOverlay);
    }
  }, [
    depthMm,
    fieldIntensityRange,
    fieldMode,
    frameData,
    playing,
    rotorRadius,
    showFieldIntensity,
  ]);

  const visibleFieldRange = showFieldIntensity
    ? resolvedFieldIntensityRange(frameData, fieldIntensityRange)
    : null;

  return (
    <div className="three-phase-three">
      <div className="three-phase-three-legend" aria-hidden="true">
        <span className="is-a">Phase A · {frameData.phase_a_current_a.toFixed(1)} A</span>
        <span className="is-b">Phase B · {frameData.phase_b_current_a.toFixed(1)} A</span>
        <span className="is-c">Phase C · {frameData.phase_c_open ? 'OPEN' : `${frameData.phase_c_current_a.toFixed(1)} A`}</span>
        <span className="is-rotor">N42 PM rotor · {frameData.rotor_angle_deg.toFixed(0)}°</span>
        <em>
          {showFieldIntensity
            ? 'FEM |B| colors on solved stator poles + rotor face'
            : 'Illustrative extrusion · angles and currents come from the 2D FEM frame'}
        </em>
      </div>
      {visibleFieldRange ? (
        <div className="three-phase-three-field-scale" aria-label={`Flux density color scale from ${visibleFieldRange.low.toFixed(2)} to ${visibleFieldRange.high.toFixed(2)} tesla`}>
          <span>|B| FEM</span>
          <i />
          <b>{visibleFieldRange.low.toFixed(2)}</b>
          <b>{visibleFieldRange.high.toFixed(2)} T</b>
        </div>
      ) : null}
      <div className="three-phase-three-axis" aria-hidden="true">
        <span><b>Y</b> ↑</span>
        <span><b>X</b> →</span>
        <span><b>Z</b> stack ↗</span>
      </div>
      <div className="three-phase-three-hint">Drag to orbit · Scroll to zoom · six wound teeth surround one PM rotor</div>
      <div
        ref={containerRef}
        className="three-phase-three-canvas"
        role="img"
        aria-label={`Interactive three-dimensional extrusion of the Lesson 8 six-tooth three-phase motor with the permanent-magnet rotor at ${frameData.rotor_angle_deg.toFixed(0)} degrees${showFieldIntensity ? ' and solved flux-density colors overlaid on its stator poles and rotor face' : ''}.`}
      />
    </div>
  );
};
