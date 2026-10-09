import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type { RotorChaseFieldData, RotorChaseFieldSource } from './lessonSolveTypes';

interface RotorChase3DProps {
  fieldData: RotorChaseFieldData;
  fieldSource: RotorChaseFieldSource;
  rotorAngleDeg: number;
  sourceCurrentA: number;
}

interface DynamicSceneParts {
  rotor: THREE.Group;
  rotorMaterials: THREE.MeshStandardMaterial[];
  sourceMaterials: THREE.MeshStandardMaterial[];
  coilMaterials: THREE.MeshStandardMaterial[];
  sourceFieldPaths: THREE.Group;
  rotorFieldPaths: THREE.Group;
  sourceArrow: THREE.ArrowHelper;
  rotorArrow: THREE.ArrowHelper;
}

const BACKGROUND = 0x080d16;
const NORTH = 0xef4444;
const SOUTH = 0x2563eb;
const STEEL = 0x64748b;
const COPPER = 0xd97706;

function finiteOr(value: number | null | undefined, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function disposeSceneObject(object: THREE.Object3D) {
  if (!(object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.LineSegments)) return;
  object.geometry?.dispose();
  const materials = Array.isArray(object.material) ? object.material : [object.material];
  materials.forEach((material) => material.dispose());
}

function material(
  color: number,
  metalness = 0.45,
  roughness = 0.3,
) {
  return new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.09,
    metalness,
    roughness,
    transparent: true,
  });
}

function addEdges(group: THREE.Group, mesh: THREE.Mesh, color = 0x94a3b8) {
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry, 25),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.52 }),
  );
  edges.position.copy(mesh.position);
  edges.rotation.copy(mesh.rotation);
  group.add(edges);
}

function makeTube(
  points: THREE.Vector3[],
  color: number,
  opacity: number,
  closed = false,
) {
  const curvePoints = closed && points.length < 8
    ? points.flatMap((point, index) => {
      const next = points[(index + 1) % points.length];
      return Array.from({ length: 8 }, (_, step) => point.clone().lerp(next, step / 8));
    })
    : points;
  const curve = new THREE.CatmullRomCurve3(curvePoints, closed, 'centripetal');
  return new THREE.Mesh(
    new THREE.TubeGeometry(curve, 64, 0.16, 7, closed),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      depthWrite: false,
    }),
  );
}

function makeWindingTurn(
  x: number,
  radiusY: number,
  radiusZ: number,
  copperMaterial: THREE.MeshStandardMaterial,
) {
  const points = Array.from({ length: 48 }, (_, index) => {
    const angle = index / 48 * Math.PI * 2;
    return new THREE.Vector3(
      x,
      radiusY * Math.cos(angle),
      radiusZ * Math.sin(angle),
    );
  });
  return new THREE.Mesh(
    new THREE.TubeGeometry(
      new THREE.CatmullRomCurve3(points, true, 'centripetal'),
      64,
      0.48,
      9,
      true,
    ),
    copperMaterial,
  );
}

export const RotorChase3D: React.FC<RotorChase3DProps> = ({
  fieldData,
  fieldSource,
  rotorAngleDeg,
  sourceCurrentA,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const dynamicRef = React.useRef<DynamicSceneParts | null>(null);

  const sourceKind = fieldData.source_kind;
  const depthMm = Math.max(finiteOr(fieldData.teaching_depth_mm, 10), 2);
  const rotorLength = Math.max(finiteOr(fieldData.rotor_length_mm, 12), 8);
  const rotorThickness = Math.max(finiteOr(fieldData.rotor_thickness_mm, 4), 3);
  const poleGapMm = Math.max(finiteOr(fieldData.pole_gap_mm, 8), 0.5);
  const sourceWidth = Math.max(finiteOr(fieldData.stator_magnet_width_mm, 24), 8);
  const reportedInnerX = Math.abs(finiteOr(fieldData.magnet_inner_x_mm, 0));
  const innerX = Math.max(
    reportedInnerX,
    rotorLength / 2 + poleGapMm,
  );
  const outerX = Math.max(
    Math.abs(finiteOr(fieldData.magnet_outer_x_mm, innerX + sourceWidth)),
    innerX + sourceWidth,
  );
  const sourceHeight = Math.max(
    finiteOr(fieldData.stator_magnet_half_height_mm, 0) * 2,
    finiteOr(fieldData.magnet_half_height_mm, 0) * 2,
    12,
  );

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BACKGROUND);
    scene.fog = new THREE.Fog(BACKGROUND, 105, 230);

    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 500);
    camera.position.set(82, 60, 108);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
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
    controls.minDistance = 36;
    controls.maxDistance = 150;

    scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.3));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(70, 85, 80);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x67e8f9, 1.15);
    rim.position.set(-65, 20, -70);
    scene.add(rim);
    const copperFill = new THREE.DirectionalLight(0xf59e0b, 0.7);
    copperFill.position.set(35, -35, 60);
    scene.add(copperFill);

    const model = new THREE.Group();
    model.rotation.x = -0.035;
    scene.add(model);

    const sourceMaterials: THREE.MeshStandardMaterial[] = [];
    const coilMaterials: THREE.MeshStandardMaterial[] = [];
    if (sourceKind === 'pm') {
      const halfWidth = (outerX - innerX) / 2;
      const halfGeometry = new THREE.BoxGeometry(
        halfWidth,
        sourceHeight,
        depthMm,
      );
      [
        { x: -outerX + halfWidth / 2, color: SOUTH, edge: 0x93c5fd },
        { x: -innerX - halfWidth / 2, color: NORTH, edge: 0xfca5a5 },
        { x: innerX + halfWidth / 2, color: SOUTH, edge: 0x93c5fd },
        { x: outerX - halfWidth / 2, color: NORTH, edge: 0xfca5a5 },
      ].forEach(({ x, color, edge }) => {
        const sourceMaterial = material(color);
        sourceMaterials.push(sourceMaterial);
        const magnet = new THREE.Mesh(halfGeometry.clone(), sourceMaterial);
        magnet.position.x = x;
        magnet.castShadow = true;
        magnet.receiveShadow = true;
        model.add(magnet);
        addEdges(model, magnet, edge);
      });
      halfGeometry.dispose();
    } else {
      const coreWidth = outerX - innerX;
      [-1, 1].forEach((side) => {
        const coreMaterial = material(STEEL, 0.6, 0.34);
        sourceMaterials.push(coreMaterial);
        const core = new THREE.Mesh(
          new THREE.BoxGeometry(coreWidth, sourceHeight, depthMm),
          coreMaterial,
        );
        core.position.x = side * (innerX + coreWidth / 2);
        core.castShadow = true;
        core.receiveShadow = true;
        model.add(core);
        addEdges(model, core);

        const copperMaterial = material(COPPER, 0.72, 0.24);
        coilMaterials.push(copperMaterial);
        const coilCenterX = side * (innerX + coreWidth * 0.56);
        [-2.4, -1.2, 0, 1.2, 2.4].forEach((offset) => {
          const turn = makeWindingTurn(
            coilCenterX + side * offset,
            sourceHeight / 2 + 2.2,
            depthMm / 2 + 2.1,
            copperMaterial,
          );
          turn.castShadow = true;
          model.add(turn);
        });
      });
    }

    const rotor = new THREE.Group();
    model.add(rotor);
    const hubMaterial = material(0x263244, 0.68, 0.3);
    const hub = new THREE.Mesh(
      new THREE.CylinderGeometry(
        Math.max(rotorThickness * 1.1, 3.4),
        Math.max(rotorThickness * 1.1, 3.4),
        depthMm * 0.72,
        48,
      ),
      hubMaterial,
    );
    hub.rotation.x = Math.PI / 2;
    hub.castShadow = true;
    rotor.add(hub);
    const shaft = new THREE.Mesh(
      new THREE.CylinderGeometry(
        Math.max(rotorThickness * 0.32, 1.25),
        Math.max(rotorThickness * 0.32, 1.25),
        depthMm * 2.2,
        36,
      ),
      material(0xb8c4d4, 0.9, 0.2),
    );
    shaft.rotation.x = Math.PI / 2;
    shaft.castShadow = true;
    rotor.add(shaft);

    const rotorMaterials = [
      material(SOUTH),
      material(NORTH),
    ];
    const rotorHalfGeometry = new THREE.BoxGeometry(
      rotorLength / 2,
      rotorThickness,
      depthMm * 1.12,
    );
    [-1, 1].forEach((side, index) => {
      const rotorHalf = new THREE.Mesh(rotorHalfGeometry.clone(), rotorMaterials[index]);
      rotorHalf.position.x = side * rotorLength / 4;
      rotorHalf.castShadow = true;
      rotorHalf.receiveShadow = true;
      rotor.add(rotorHalf);
      addEdges(rotor, rotorHalf, index === 0 ? 0x93c5fd : 0xfca5a5);
    });
    rotorHalfGeometry.dispose();

    const sourceFieldPaths = new THREE.Group();
    const fieldExtentY = sourceHeight / 2 + 7;
    [-1, 1].forEach((sign) => {
      [-1.4, 1.4].forEach((zOffset) => {
        sourceFieldPaths.add(makeTube([
          new THREE.Vector3(-innerX, 0, zOffset),
          new THREE.Vector3(0, sign * 2.2, zOffset),
          new THREE.Vector3(innerX, 0, zOffset),
          new THREE.Vector3(0, sign * fieldExtentY, zOffset),
        ], 0x67e8f9, 0.58, true));
      });
    });
    model.add(sourceFieldPaths);

    const rotorFieldPaths = new THREE.Group();
    [-1.1, 1.1].forEach((zOffset) => {
      rotorFieldPaths.add(makeTube([
        new THREE.Vector3(-rotorLength / 2, 0, zOffset),
        new THREE.Vector3(0, rotorLength * 0.64, zOffset),
        new THREE.Vector3(rotorLength / 2, 0, zOffset),
        new THREE.Vector3(0, -rotorLength * 0.64, zOffset),
      ], 0xfbbf24, 0.52, true));
    });
    rotor.add(rotorFieldPaths);

    const sourceArrow = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(-innerX * 0.72, 0, depthMm / 2 + 4),
      innerX * 1.44,
      0x67e8f9,
      2.4,
      1.5,
    );
    model.add(sourceArrow);
    const rotorArrow = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(-rotorLength * 0.42, 0, depthMm / 2 + 6),
      rotorLength * 0.84,
      0xfbbf24,
      2,
      1.3,
    );
    rotor.add(rotorArrow);

    const grid = new THREE.GridHelper(90, 18, 0x334155, 0x1e293b);
    grid.position.y = -sourceHeight / 2 - 10;
    const gridMaterial = grid.material as THREE.Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = 0.3;
    scene.add(grid);

    dynamicRef.current = {
      rotor,
      rotorMaterials,
      sourceMaterials,
      coilMaterials,
      sourceFieldPaths,
      rotorFieldPaths,
      sourceArrow,
      rotorArrow,
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
    depthMm,
    innerX,
    outerX,
    rotorLength,
    rotorThickness,
    sourceHeight,
    sourceKind,
  ]);

  React.useEffect(() => {
    const dynamic = dynamicRef.current;
    if (!dynamic) return;

    const sourceActive = fieldSource !== 'rotor';
    const rotorActive = fieldSource !== 'stator';
    const sourceStrength = sourceKind === 'pm'
      ? 1
      : Math.min(1, Math.abs(sourceCurrentA) / 8);
    const currentSign = sourceCurrentA < -0.01 ? -1 : 1;

    dynamic.rotor.rotation.z = rotorAngleDeg * Math.PI / 180;
    dynamic.rotorMaterials.forEach((rotorMaterial) => {
      rotorMaterial.opacity = rotorActive ? 1 : 0.32;
      rotorMaterial.emissiveIntensity = rotorActive ? 0.09 : 0.01;
    });

    dynamic.sourceMaterials.forEach((sourceMaterial, index) => {
      if (sourceKind === 'electromagnet') {
        const isLeft = index === 0;
        const leftIsNorth = currentSign > 0;
        const faceColor = (isLeft ? leftIsNorth : !leftIsNorth) ? NORTH : SOUTH;
        sourceMaterial.color.setHex(sourceStrength > 0.01 ? faceColor : STEEL);
        sourceMaterial.emissive.setHex(sourceStrength > 0.01 ? faceColor : 0x0f172a);
      }
      sourceMaterial.opacity = sourceActive ? 1 : 0.3;
      sourceMaterial.emissiveIntensity = sourceActive ? 0.09 * sourceStrength : 0.01;
    });
    dynamic.coilMaterials.forEach((coilMaterial) => {
      coilMaterial.opacity = sourceActive ? 0.45 + sourceStrength * 0.55 : 0.24;
      coilMaterial.emissiveIntensity = sourceActive ? 0.05 + sourceStrength * 0.18 : 0.01;
    });

    const showSourceField = sourceActive && sourceStrength > 0.015;
    dynamic.sourceFieldPaths.visible = showSourceField;
    dynamic.sourceArrow.visible = showSourceField;
    dynamic.sourceArrow.position.x = currentSign > 0 ? -innerX * 0.72 : innerX * 0.72;
    dynamic.sourceArrow.setDirection(new THREE.Vector3(currentSign, 0, 0));
    dynamic.sourceArrow.setLength(
      innerX * 1.44 * Math.max(sourceStrength, 0.2),
      2.4,
      1.5,
    );

    dynamic.rotorFieldPaths.visible = rotorActive;
    dynamic.rotorArrow.visible = rotorActive;
  }, [
    fieldSource,
    innerX,
    rotorAngleDeg,
    sourceCurrentA,
    sourceKind,
  ]);

  const sourceLabel = sourceKind === 'pm'
    ? 'Fixed N42 stator pair'
    : Math.abs(sourceCurrentA) < 0.01
      ? 'Wound M350-50A poles · current off'
      : `Wound M350-50A poles · ${sourceCurrentA > 0 ? '+' : ''}${sourceCurrentA.toFixed(2)} A`;
  const targetDirection = sourceKind === 'pm' || sourceCurrentA >= 0
    ? '+X'
    : '−X';

  return (
    <div className={`rotor-chase-three${sourceKind === 'electromagnet' ? ' is-electromagnet' : ''}`}>
      <div className="rotor-chase-three-title" aria-hidden="true">
        <h3>3D source + rotor</h3>
        <p>{sourceLabel} · PM rotor at {rotorAngleDeg.toFixed(0)}°</p>
      </div>
      <div className="rotor-chase-three-legend" aria-hidden="true">
        <span className="is-source">{sourceLabel}</span>
        <span className="is-rotor">N42 rotor · N axis {rotorAngleDeg.toFixed(0)}°</span>
        {fieldSource !== 'rotor' && (sourceKind === 'pm' || Math.abs(sourceCurrentA) > 0.01)
          ? <span className="is-target">B target {targetDirection}</span>
          : null}
        <em>Illustrative extrusion · field values come from the 2D FEM frame</em>
      </div>
      <div className="rotor-chase-three-axis" aria-hidden="true">
        <span><b>Y</b> ↑</span>
        <span><b>X</b> →</span>
        <span><b>Z</b> axial ↗</span>
      </div>
      <div className="rotor-chase-three-hint">Drag to orbit · Scroll to zoom · magnetic parts extend through the stack</div>
      <div
        ref={containerRef}
        className="rotor-chase-three-canvas"
        role="img"
        aria-label={`Interactive three-dimensional extrusion of the Lesson 6 ${sourceKind === 'pm' ? 'permanent-magnet stator fixture' : 'wound-pole electromagnet fixture'} with the permanent-magnet rotor at ${rotorAngleDeg.toFixed(0)} degrees. This is an illustrative extrusion of the two-dimensional solved field.`}
      />
    </div>
  );
};
