import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type { LinearMotorCapstoneFieldData } from './lessonSolveTypes';

interface LinearMotorCapstone3DProps {
  currentSign: 1 | -1;
  forceDirection: -1 | 0 | 1;
  netForceN: number | null;
  gapMm: number;
  windingSpacingMm: number;
  magnetOrientations: readonly number[];
  running: boolean;
  showFluxLines: boolean;
  showBMap: boolean;
  fieldData: LinearMotorCapstoneFieldData | null;
}

const BACKGROUND = 0x080d16;
const TRACK_LENGTH = 84;
const MAGNET_X = [-27, -9, 9, 27] as const;

function disposeObject(object: THREE.Object3D) {
  if (object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.LineSegments) {
    object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach((material) => material.dispose());
  }
}

function addEdges(group: THREE.Group, mesh: THREE.Mesh, color: number, opacity = 0.5) {
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry, 22),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity }),
  );
  edges.position.copy(mesh.position);
  edges.quaternion.copy(mesh.quaternion);
  group.add(edges);
}

function addArrow(
  group: THREE.Group,
  direction: THREE.Vector3,
  origin: THREE.Vector3,
  length: number,
  color: number,
  opacity = 1,
) {
  const arrow = new THREE.ArrowHelper(direction.normalize(), origin, length, color, 2.4, 1.35);
  [arrow.line.material, arrow.cone.material].forEach((material) => {
    const materials = Array.isArray(material) ? material : [material];
    materials.forEach((item) => {
      item.transparent = opacity < 1;
      item.opacity = opacity;
      item.depthTest = false;
    });
  });
  arrow.line.renderOrder = 6;
  arrow.cone.renderOrder = 6;
  group.add(arrow);
}

function tubeBetween(a: THREE.Vector3, b: THREE.Vector3, radius: number, material: THREE.Material) {
  const midpoint = a.clone().add(b).multiplyScalar(0.5);
  const direction = b.clone().sub(a);
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(radius, radius, direction.length(), 18),
    material,
  );
  mesh.position.copy(midpoint);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
  return mesh;
}

function fieldColor(value: number, high: number) {
  const t = Math.min(1, Math.max(0, value / Math.max(high, 1e-9)));
  const color = new THREE.Color();
  if (t < 0.34) return color.lerpColors(new THREE.Color(0x2563eb), new THREE.Color(0x22d3ee), t / 0.34);
  if (t < 0.68) return color.lerpColors(new THREE.Color(0x22d3ee), new THREE.Color(0xfde047), (t - 0.34) / 0.34);
  return color.lerpColors(new THREE.Color(0xfde047), new THREE.Color(0xf97316), (t - 0.68) / 0.32);
}

function addSolvedMagnetoField(
  target: THREE.Group,
  data: LinearMotorCapstoneFieldData,
  showFluxLines: boolean,
  showBMap: boolean,
) {
  if (showBMap && data.element_b_mag_t?.length) {
    const finite = data.element_b_mag_t.filter(Number.isFinite).sort((a, b) => a - b);
    const high = finite[Math.max(0, Math.floor(finite.length * 0.96) - 1)]
      ?? finite[finite.length - 1]
      ?? 1;
    const positions: number[] = [];
    const colors: number[] = [];
    data.triangles.forEach((triangle, index) => {
      const color = fieldColor(data.element_b_mag_t?.[index] ?? 0, high);
      triangle.forEach((nodeIndex) => {
        const [xMm, yMm] = data.nodes_mm[nodeIndex] ?? [0, 0];
        positions.push(xMm, yMm, 0);
        colors.push(color.r, color.g, color.b);
      });
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    const map = new THREE.Mesh(
      geometry,
      new THREE.MeshBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0.44,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    map.renderOrder = 3;
    target.add(map);
  }

  if (!showFluxLines) return;
  const levels = data.contour_levels ?? [];
  const levelStep = Math.max(1, Math.ceil(levels.length / 16));
  const slices = [-4.6, 0, 4.6];
  slices.forEach((zMm) => {
    levels.filter((_, index) => index % levelStep === 0).forEach((level, levelIndex) => {
      const segmentStep = Math.max(1, Math.ceil(level.segments_mm.length / 220));
      const points: THREE.Vector3[] = [];
      for (let index = 0; index < level.segments_mm.length; index += segmentStep) {
        const [x1, y1, x2, y2] = level.segments_mm[index];
        points.push(new THREE.Vector3(x1, y1, zMm), new THREE.Vector3(x2, y2, zMm));
      }
      if (!points.length) return;
      const centerSlice = Math.abs(zMm) < 0.1;
      const lines = new THREE.LineSegments(
        new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({
          color: levelIndex % 3 === 0 ? 0x67e8f9 : 0x3b82f6,
          transparent: true,
          opacity: centerSlice ? 0.64 : 0.27,
          depthWrite: false,
        }),
      );
      lines.renderOrder = centerSlice ? 6 : 4;
      target.add(lines);
    });
  });
}

function VectorGuide3D({
  currentSign,
  fieldSign,
  forceDirection,
}: {
  currentSign: 1 | -1;
  fieldSign: 1 | -1;
  forceDirection: -1 | 0 | 1;
}) {
  const currentEnd = currentSign > 0 ? { x: 90, y: 25 } : { x: 24, y: 89 };
  const fieldEnd = fieldSign > 0 ? { x: 56, y: 7 } : { x: 56, y: 92 };
  const forceEnd = forceDirection > 0 ? { x: 105, y: 58 } : { x: 7, y: 58 };
  const currentLabel = currentSign > 0 ? '+Z · out' : '−Z · in';
  const fieldLabel = fieldSign > 0 ? '+Y · up' : '−Y · down';
  const forceLabel = forceDirection > 0 ? '+X · right' : forceDirection < 0 ? '−X · left' : 'awaiting solve';

  return (
    <div
      className="linear-capstone-vector-guide"
      aria-label={`Representative active-side vector guide. Current ${currentLabel}. Field ${fieldLabel}. Force ${forceLabel}.`}
    >
      <span>Representative active side</span>
      <div>
        <svg viewBox="0 0 112 100" aria-hidden="true">
          <defs>
            <marker id="capstoneGuideCurrent" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
              <path d="M0 0 L7 3.5 L0 7 Z" className="is-current" />
            </marker>
            <marker id="capstoneGuideField" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
              <path d="M0 0 L7 3.5 L0 7 Z" className="is-field" />
            </marker>
            <marker id="capstoneGuideForce" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
              <path d="M0 0 L7 3.5 L0 7 Z" className="is-force" />
            </marker>
          </defs>
          <circle cx="56" cy="58" r="4" />
          <line x1="56" y1="58" x2={currentEnd.x} y2={currentEnd.y} className="is-current" markerEnd="url(#capstoneGuideCurrent)" />
          <line x1="56" y1="58" x2={fieldEnd.x} y2={fieldEnd.y} className="is-field" markerEnd="url(#capstoneGuideField)" />
          {forceDirection !== 0 ? (
            <line x1="56" y1="58" x2={forceEnd.x} y2={forceEnd.y} className="is-force" markerEnd="url(#capstoneGuideForce)" />
          ) : null}
          <text x={currentEnd.x} y={currentEnd.y + (currentSign > 0 ? -5 : 9)} className="is-current">I</text>
          <text x={fieldEnd.x + 7} y={fieldEnd.y + (fieldSign > 0 ? 6 : 0)} className="is-field">B</text>
          <text x={forceDirection > 0 ? 96 : 10} y="51" className="is-force">F</text>
        </svg>
        <div className="linear-capstone-vector-guide-labels">
          <p><i className="is-current" /><b>I</b><small>{currentLabel}</small></p>
          <p><i className="is-field" /><b>B</b><small>{fieldLabel}</small></p>
          <p><i className="is-force" /><b>F</b><small>{forceLabel}</small></p>
        </div>
      </div>
      <small>I × B → F · verified by Magneto2D</small>
    </div>
  );
}

export const LinearMotorCapstone3D: React.FC<LinearMotorCapstone3DProps> = ({
  currentSign,
  forceDirection,
  netForceN,
  gapMm,
  windingSpacingMm,
  magnetOrientations,
  running,
  showFluxLines,
  showBMap,
  fieldData,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [assemblyView, setAssemblyView] = React.useState<'assembled' | 'exploded'>('assembled');
  const exploded = assemblyView === 'exploded';

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BACKGROUND);
    scene.fog = new THREE.Fog(BACKGROUND, 110, 210);

    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 400);
    camera.position.set(72, 54, 78);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    renderer.shadowMap.enabled = true;
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.display = 'block';
    renderer.domElement.style.touchAction = 'none';
    container.appendChild(renderer.domElement);

    const pmrem = new THREE.PMREMGenerator(renderer);
    const environment = pmrem.fromScene(new RoomEnvironment(), 0.04);
    scene.environment = environment.texture;
    scene.environmentIntensity = 0.58;

    scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.55));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(50, 80, 65);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x67e8f9, 1.2);
    rim.position.set(-60, 10, -55);
    scene.add(rim);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 4, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.minDistance = 45;
    controls.maxDistance = 155;

    const model = new THREE.Group();
    scene.add(model);

    const frameMaterial = new THREE.MeshStandardMaterial({ color: 0x273449, metalness: 0.72, roughness: 0.38 });
    const backIronMaterial = new THREE.MeshStandardMaterial({ color: 0x475569, metalness: 0.88, roughness: 0.27 });
    const railMaterial = new THREE.MeshStandardMaterial({ color: 0xb7c4d4, metalness: 0.92, roughness: 0.2 });
    const bearingMaterial = new THREE.MeshStandardMaterial({ color: 0x64748b, metalness: 0.76, roughness: 0.26 });
    const northMaterial = new THREE.MeshStandardMaterial({
      color: 0xef4444,
      emissive: 0x7f1d1d,
      emissiveIntensity: 0.14,
      metalness: 0.35,
      roughness: 0.3,
    });
    const southMaterial = new THREE.MeshStandardMaterial({
      color: 0x2563eb,
      emissive: 0x1e3a8a,
      emissiveIntensity: 0.14,
      metalness: 0.35,
      roughness: 0.3,
    });
    const copperMaterial = new THREE.MeshStandardMaterial({
      color: 0xf59e0b,
      emissive: 0x92400e,
      emissiveIntensity: 0.22,
      metalness: 0.72,
      roughness: 0.22,
    });
    const carriageMaterial = new THREE.MeshStandardMaterial({
      color: 0xe2e8f0,
      metalness: 0.46,
      roughness: 0.3,
      transparent: true,
      opacity: exploded ? 0.76 : 0.92,
    });
    const formerMaterial = new THREE.MeshStandardMaterial({
      color: 0xcbd5e1,
      metalness: 0.05,
      roughness: 0.55,
      transparent: true,
      opacity: 0.44,
    });
    const cableMaterial = new THREE.MeshStandardMaterial({ color: 0x111827, metalness: 0.12, roughness: 0.72 });
    const terminalPositiveMaterial = new THREE.MeshStandardMaterial({ color: 0xef4444, roughness: 0.42 });
    const terminalNegativeMaterial = new THREE.MeshStandardMaterial({ color: 0x2563eb, roughness: 0.42 });
    const encoderMaterial = new THREE.MeshStandardMaterial({
      color: 0x22d3ee,
      emissive: 0x0891b2,
      emissiveIntensity: 0.38,
      metalness: 0.45,
      roughness: 0.32,
    });

    const addBox = (
      parent: THREE.Group,
      size: [number, number, number],
      position: [number, number, number],
      material: THREE.Material,
      edgeColor?: number,
    ) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
      mesh.position.set(...position);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      parent.add(mesh);
      if (edgeColor != null) addEdges(parent, mesh, edgeColor, 0.5);
      return mesh;
    };

    // STATOR: a structural frame supports the steel return path, magnet array,
    // linear guides, travel stops, and encoder. These parts never translate.
    addBox(model, [TRACK_LENGTH + 12, 4, 38], [0, -15.5, 0], frameMaterial, 0x64748b);
    addBox(model, [TRACK_LENGTH, 6, 28], [0, exploded ? -14.5 : -11, 0], backIronMaterial, 0x94a3b8);

    const railZ = exploded ? 18 : 15;
    [-railZ, railZ].forEach((z) => {
      addBox(model, [TRACK_LENGTH + 8, 1.4, 2.4], [0, 5, z], railMaterial, 0xe2e8f0);
      [-34, 0, 34].forEach((x) => addBox(model, [4, 5, 5], [x, 1.9, z], frameMaterial));
      [-45, 45].forEach((x) => addBox(model, [3, 5.5, 7], [x, 6.4, z], frameMaterial, 0xf59e0b));
    });
    addBox(model, [TRACK_LENGTH + 2, 0.45, 1.4], [0, 2.8, railZ + 3.5], encoderMaterial);

    const magnetY = exploded ? 1.4 : -4;

    magnetOrientations.forEach((orientation, index) => {
      const magnetGroup = new THREE.Group();
      magnetGroup.position.x = MAGNET_X[index] ?? 0;
      const magnet = addBox(
        magnetGroup,
        [14, 8, 20],
        [0, magnetY, 0],
        orientation > 0 ? northMaterial : southMaterial,
        orientation > 0 ? 0xfca5a5 : 0x93c5fd,
      );
      const poleBand = addBox(
        magnetGroup,
        [14, 0.8, 20],
        [0, magnetY - 4.4, 0],
        orientation > 0 ? southMaterial : northMaterial,
      );
      magnet.castShadow = true;
      poleBand.castShadow = true;
      model.add(magnetGroup);

    });

    if (fieldData) addSolvedMagnetoField(model, fieldData, showFluxLines, showBMap);

    // MOVER: the winding, coil former, carriage plate, bearing blocks, and
    // brackets are one rigid assembly. Only this group translates on the rails.
    const mover = new THREE.Group();
    model.add(mover);
    const coilY = exploded ? gapMm + 11 : gapMm + 3;
    const carriageY = coilY + (exploded ? 17 : 11.5);

    const carriage = addBox(mover, [38, 2.2, 38], [0, carriageY, 0], carriageMaterial, 0xe2e8f0);
    carriage.castShadow = true;

    [-11, 11].forEach((x) => {
      [-railZ, railZ].forEach((z) => {
        const bearing = addBox(mover, [8, 3.6, 6], [x, 5, z], bearingMaterial, 0xcbd5e1);
        const uprightHeight = carriageY - 7.5;
        addBox(mover, [2.2, uprightHeight, 2.2], [x, 6.8 + uprightHeight / 2, z], frameMaterial);
        bearing.castShadow = true;
      });
    });

    // A translucent, nonmagnetic former supports the winding without becoming
    // part of the magnetic circuit.
    addBox(mover, [36, 1.2, 2], [0, coilY - 1.35, -11], formerMaterial);
    addBox(mover, [36, 1.2, 2], [0, coilY - 1.35, 11], formerMaterial);
    addBox(mover, [2, 1.2, 22], [-17, coilY - 1.35, 0], formerMaterial);
    addBox(mover, [2, 1.2, 22], [17, coilY - 1.35, 0], formerMaterial);
    [-13, 13].forEach((x) => {
      [-9, 9].forEach((z) => {
        const bracketHeight = carriageY - coilY - 3;
        addBox(mover, [1.8, bracketHeight, 1.8], [x, coilY + 1 + bracketHeight / 2, z], formerMaterial);
      });
    });

    // ELECTRICAL PATH: a single conductor enters at +, makes three series
    // turns, changes layer through two insulated crossovers, and exits at −.
    // No turn is a separately closed (shorted) loop.
    const conductor = (a: THREE.Vector3, b: THREE.Vector3, radius = 0.66) => {
      const segment = tubeBetween(a, b, radius, copperMaterial);
      segment.castShadow = true;
      mover.add(segment);
      return segment;
    };
    const turnStart: THREE.Vector3[] = [];
    const turnEnd: THREE.Vector3[] = [];
    const windingHalfWidth = Math.min(17, Math.max(10, windingSpacingMm * 0.78));
    for (let turnIndex = 0; turnIndex < 3; turnIndex += 1) {
      const layerY = coilY + (turnIndex - 1) * 0.9;
      const halfX = windingHalfWidth - turnIndex * 1.2;
      const halfZ = 9 - turnIndex * 0.9;
      const start = new THREE.Vector3(-halfX, layerY, 2.3);
      const end = new THREE.Vector3(-halfX, layerY, -2.3);
      const path = [
        start,
        new THREE.Vector3(-halfX, layerY, halfZ),
        new THREE.Vector3(halfX, layerY, halfZ),
        new THREE.Vector3(halfX, layerY, -halfZ),
        new THREE.Vector3(-halfX, layerY, -halfZ),
        end,
      ];
      path.slice(0, -1).forEach((point, index) => conductor(point, path[index + 1]));
      turnStart.push(start);
      turnEnd.push(end);
      if (turnIndex > 0) conductor(turnEnd[turnIndex - 1], start, 0.62);
    }

    const positiveTerminal = new THREE.Vector3(-19, coilY + 2.4, -12.5);
    const negativeTerminal = new THREE.Vector3(-13, coilY + 2.4, -12.5);
    conductor(positiveTerminal, new THREE.Vector3(-17, coilY + 2.4, 4.4), 0.58);
    conductor(new THREE.Vector3(-17, coilY + 2.4, 4.4), turnStart[0], 0.58);
    conductor(turnEnd[2], negativeTerminal, 0.58);
    addBox(mover, [3.4, 2.1, 3.4], positiveTerminal.toArray() as [number, number, number], terminalPositiveMaterial, 0xfca5a5);
    addBox(mover, [3.4, 2.1, 3.4], negativeTerminal.toArray() as [number, number, number], terminalNegativeMaterial, 0x93c5fd);

    const currentColor = currentSign > 0 ? 0x22c55e : 0xf97316;
    addArrow(
      mover,
      new THREE.Vector3(currentSign, 0, 0),
      new THREE.Vector3(currentSign > 0 ? -13 : 13, coilY + 1.2, 9),
      12,
      currentColor,
    );
    addArrow(
      mover,
      new THREE.Vector3(-currentSign, 0, 0),
      new THREE.Vector3(currentSign > 0 ? 13 : -13, coilY + 1.2, -9),
      12,
      currentColor,
    );

    if (forceDirection !== 0) {
      addArrow(
        mover,
        new THREE.Vector3(forceDirection, 0, 0),
        new THREE.Vector3(forceDirection > 0 ? 8 : -8, carriageY + 5, 0),
        22,
        0xf59e0b,
      );
    }

    // A flexible cable chain connects the moving terminal block to a fixed
    // frame anchor. Its links reshape as the carriage translates.
    const cableLinks = Array.from({ length: 13 }, () => addBox(model, [2.8, 1.2, 3.4], [0, 0, 0], cableMaterial));
    const updateCable = () => {
      const start = new THREE.Vector3(-44, 1.5, -22);
      const end = new THREE.Vector3(mover.position.x - 16, coilY + 2.4, -15.5);
      const control = new THREE.Vector3((start.x + end.x) / 2, -1.8, -23);
      const curve = new THREE.QuadraticBezierCurve3(start, control, end);
      cableLinks.forEach((link, index) => {
        const t = index / (cableLinks.length - 1);
        link.position.copy(curve.getPoint(t));
        link.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), curve.getTangent(t).normalize());
      });
    };
    updateCable();

    const grid = new THREE.GridHelper(128, 24, 0x334155, 0x1e293b);
    grid.position.y = -9.1;
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

    let animationFrame = 0;
    const clock = new THREE.Clock();
    const render = () => {
      const elapsed = clock.getElapsedTime();
      if (running && forceDirection !== 0) {
        mover.position.x = forceDirection * (6 + Math.sin(elapsed * 2.2) * 4);
      } else {
        mover.position.x += (0 - mover.position.x) * 0.08;
      }
      updateCable();
      controls.update();
      renderer.render(scene, camera);
      animationFrame = window.requestAnimationFrame(render);
    };
    render();

    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      controls.dispose();
      scene.traverse(disposeObject);
      frameMaterial.dispose();
      backIronMaterial.dispose();
      railMaterial.dispose();
      bearingMaterial.dispose();
      northMaterial.dispose();
      southMaterial.dispose();
      copperMaterial.dispose();
      carriageMaterial.dispose();
      formerMaterial.dispose();
      cableMaterial.dispose();
      terminalPositiveMaterial.dispose();
      terminalNegativeMaterial.dispose();
      encoderMaterial.dispose();
      environment.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [currentSign, exploded, fieldData, forceDirection, gapMm, magnetOrientations, running, showBMap, showFluxLines, windingSpacingMm]);

  const motionLabel = forceDirection > 0 ? 'right' : forceDirection < 0 ? 'left' : 'stationary';
  const representativeFieldSign: 1 | -1 = (magnetOrientations[0] ?? 1) > 0 ? 1 : -1;
  const forceLabel = netForceN === null
    ? null
    : Math.abs(netForceN) < 1
      ? `${Math.round(Math.abs(netForceN) * 1000)} mN`
      : `${Math.abs(netForceN).toFixed(2)} N`;

  return (
    <div className="linear-capstone-three">
      <div className="linear-capstone-three-legend" aria-hidden="true">
        <span>Stator · magnets + back iron</span>
        <span>Mover · continuous 3-turn winding</span>
        <span>Guides · rails + 4 bearings</span>
        <span>{fieldData ? `Magneto2D · ${Math.abs(fieldData.current_a) < 0.01 ? 'PM only' : 'PM + winding'}` : 'Field not solved'}</span>
        <span>Force {motionLabel}</span>
      </div>
      <div className="linear-capstone-three-mode" role="group" aria-label="Three-dimensional assembly view">
        <button type="button" className={assemblyView === 'assembled' ? 'is-active' : ''} onClick={() => setAssemblyView('assembled')}>Assembled</button>
        <button type="button" className={assemblyView === 'exploded' ? 'is-active' : ''} onClick={() => setAssemblyView('exploded')}>Exploded</button>
      </div>
      {forceLabel && forceDirection !== 0 ? (
        <div className={`linear-capstone-three-force${forceDirection > 0 ? ' is-right' : ' is-left'}`} role="status">
          <span>Magneto2D net force</span>
          <strong><b aria-hidden="true">{forceDirection > 0 ? '⟶' : '⟵'}</b>{forceLabel}</strong>
          <small>∫ winding J × B dV</small>
        </div>
      ) : null}
      <VectorGuide3D
        currentSign={currentSign}
        fieldSign={representativeFieldSign}
        forceDirection={forceDirection}
      />
      <div className="linear-capstone-three-hint">{exploded ? 'Exploded teaching view' : 'Drag to orbit · scroll to zoom'}</div>
      <div
        ref={containerRef}
        className="linear-capstone-three-canvas"
        role="img"
        aria-label={`Interactive three-dimensional moving-coil linear motor shown ${assemblyView}. A stationary steel back iron and magnet array support two fixed guide rails. Four bearing blocks carry a mechanical carriage, nonmagnetic coil former, one continuous three-turn winding, terminals, and flexible cable chain. The carriage is ${motionLabel}.`}
      />
    </div>
  );
};
