import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

interface FieldForce3DProps {
  angleDeg?: number;
  currentA: number;
  fieldSource: 'combined' | 'magnet' | 'wire';
  forceYN: number;
  poleGapMm: number;
}

const BACKGROUND = 0x080d16;
const MAGNET_WIDTH_MM = 24;
const MAGNET_HEIGHT_MM = 12;
const SOLVED_DEPTH_MM = 10;
const WIRE_RADIUS_MM = 4;
const FIELD_DEPTH_SLICES = [-3.6, 0, 3.6] as const;
const CURRENT_VECTOR_COLOR = 0x22c55e;
const FORCE_VECTOR_COLOR = 0xf59e0b;

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

function addEdges(group: THREE.Group, mesh: THREE.Mesh, color: number) {
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry, 24),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.58 }),
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
  headLength = 2.2,
) {
  const arrow = new THREE.ArrowHelper(
    direction.clone().normalize(),
    origin,
    length,
    color,
    headLength,
    headLength * 0.62,
  );
  group.add(arrow);
  return arrow;
}

function wireFieldRing(radiusMm: number, opacity: number) {
  return new THREE.Mesh(
    new THREE.TorusGeometry(radiusMm, 0.2, 8, 80),
    new THREE.MeshBasicMaterial({
      color: 0x67e8f9,
      transparent: true,
      opacity,
      depthWrite: false,
    }),
  );
}

function makeAngleLabel(angleDeg: number) {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 96;
  const context = canvas.getContext('2d');
  if (!context) return null;
  context.fillStyle = 'rgba(3, 7, 18, 0.9)';
  context.beginPath();
  context.roundRect(8, 8, 240, 80, 16);
  context.fill();
  context.strokeStyle = '#fef3c7';
  context.lineWidth = 4;
  context.stroke();
  context.fillStyle = '#fef3c7';
  context.font = '700 38px ui-monospace, SFMono-Regular, Menlo, monospace';
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText(`θ = ${angleDeg}°`, 128, 49);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
  }));
  sprite.scale.set(7.5, 2.8, 1);
  return sprite;
}

export const FieldForce3D: React.FC<FieldForce3DProps> = ({
  angleDeg = 90,
  currentA,
  fieldSource,
  forceYN,
  poleGapMm,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const normalizedAngleDeg = Math.min(360, Math.max(0, Math.round(angleDeg)));
  const angleRad = (normalizedAngleDeg * Math.PI) / 180;
  const currentSign = currentA >= 0 ? 1 : -1;
  const currentDirectionX = Math.cos(angleRad);
  const currentDirectionZ = Math.sin(angleRad) * currentSign;

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const currentDirectionVector = new THREE.Vector3(
      currentDirectionX,
      0,
      currentDirectionZ,
    ).normalize();

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BACKGROUND);
    scene.fog = new THREE.Fog(BACKGROUND, 100, 220);

    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 500);
    camera.position.set(66, 42, 72);

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
    controls.minDistance = 38;
    controls.maxDistance = 150;

    scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.35));
    const key = new THREE.DirectionalLight(0xffffff, 2.1);
    key.position.set(65, 85, 75);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x67e8f9, 1.2);
    rim.position.set(-60, 10, -65);
    scene.add(rim);
    const copperFill = new THREE.DirectionalLight(0xf59e0b, 0.8);
    copperFill.position.set(30, -35, 55);
    scene.add(copperFill);

    const model = new THREE.Group();
    model.rotation.x = -0.03;
    scene.add(model);

    const magnetActive = fieldSource !== 'wire';
    const wireActive = fieldSource !== 'magnet';
    const magnetMaterial = (color: number) => new THREE.MeshStandardMaterial({
      color: magnetActive ? color : 0x475569,
      emissive: magnetActive ? color : 0x0f172a,
      emissiveIntensity: magnetActive ? 0.11 : 0.02,
      metalness: 0.42,
      roughness: 0.29,
      transparent: !magnetActive,
      opacity: magnetActive ? 1 : 0.48,
    });
    const northMaterial = magnetMaterial(0xef4444);
    const southMaterial = magnetMaterial(0x2563eb);
    const copperMaterial = new THREE.MeshStandardMaterial({
      color: wireActive ? 0xd97706 : 0x64748b,
      emissive: wireActive ? 0x92400e : 0x0f172a,
      emissiveIntensity: wireActive ? 0.16 : 0.02,
      metalness: 0.72,
      roughness: 0.24,
      transparent: !wireActive,
      opacity: wireActive ? 1 : 0.52,
    });

    const innerX = WIRE_RADIUS_MM + poleGapMm;
    const outerX = innerX + MAGNET_WIDTH_MM;
    const halfMagnetWidth = MAGNET_WIDTH_MM / 2;
    const magnetHalfGeometry = new THREE.BoxGeometry(
      halfMagnetWidth,
      MAGNET_HEIGHT_MM,
      SOLVED_DEPTH_MM,
      1,
      1,
      1,
    );
    const magnetHalves = [
      { x: -outerX + halfMagnetWidth / 2, material: southMaterial, edge: 0x93c5fd },
      { x: -innerX - halfMagnetWidth / 2, material: northMaterial, edge: 0xfca5a5 },
      { x: innerX + halfMagnetWidth / 2, material: southMaterial, edge: 0x93c5fd },
      { x: outerX - halfMagnetWidth / 2, material: northMaterial, edge: 0xfca5a5 },
    ];
    magnetHalves.forEach(({ x, material, edge }) => {
      const half = new THREE.Mesh(magnetHalfGeometry.clone(), material);
      half.position.x = x;
      half.castShadow = true;
      half.receiveShadow = true;
      model.add(half);
      addEdges(model, half, edge);
    });

    const wire = new THREE.Mesh(
      new THREE.CylinderGeometry(WIRE_RADIUS_MM, WIRE_RADIUS_MM, SOLVED_DEPTH_MM, 48, 1, false),
      copperMaterial,
    );
    wire.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), currentDirectionVector);
    wire.castShadow = true;
    wire.receiveShadow = true;
    model.add(wire);
    addEdges(model, wire, 0xfbbf24);

    if (wireActive && Math.abs(currentA) > 1e-6) {
      const fieldRingRadius = 9;
      const ringQuaternion = new THREE.Quaternion().setFromUnitVectors(
        new THREE.Vector3(0, 0, 1),
        currentDirectionVector,
      );
      FIELD_DEPTH_SLICES.forEach((depth) => {
        const ring = wireFieldRing(fieldRingRadius, 0.54);
        ring.position.copy(currentDirectionVector.clone().multiplyScalar(depth));
        ring.quaternion.copy(ringQuaternion);
        model.add(ring);
        [0, Math.PI].forEach((angle) => {
          const tangent = new THREE.Vector3(
            -Math.sin(angle),
            Math.cos(angle),
            0,
          ).applyQuaternion(ringQuaternion);
          const ringPoint = new THREE.Vector3(
            fieldRingRadius * Math.cos(angle),
            fieldRingRadius * Math.sin(angle),
            0,
          )
            .applyQuaternion(ringQuaternion)
            .add(currentDirectionVector.clone().multiplyScalar(depth + 0.22));
          addArrow(
            model,
            tangent,
            ringPoint,
            3,
            0x67e8f9,
            0.9,
          );
        });
      });
      const currentOrigin = currentDirectionVector.clone().multiplyScalar(-SOLVED_DEPTH_MM / 2 - 7);
      const currentArrow = addArrow(
        model,
        currentDirectionVector,
        currentOrigin,
        SOLVED_DEPTH_MM + 14,
        CURRENT_VECTOR_COLOR,
        2.7,
      );
      [currentArrow.line.material, currentArrow.cone.material].forEach((material) => {
        const materials = Array.isArray(material) ? material : [material];
        materials.forEach((currentMaterial) => {
          currentMaterial.depthTest = false;
          currentMaterial.transparent = true;
          currentMaterial.opacity = 0.96;
        });
      });
      currentArrow.line.renderOrder = 6;
      currentArrow.cone.renderOrder = 6;

      const angleOrigin = new THREE.Vector3(-2, -10, 0);
      addArrow(model, new THREE.Vector3(1, 0, 0), angleOrigin, 8, 0x67e8f9, 1.7);
      addArrow(model, currentDirectionVector, angleOrigin, 8, CURRENT_VECTOR_COLOR, 1.7);
      const signedAngleRad = angleRad * currentSign;
      const arcSegments = Math.max(24, Math.ceil(Math.abs(normalizedAngleDeg) / 5));
      const arcPoints = Array.from({ length: arcSegments + 1 }, (_, index) => {
        const angle = (index / arcSegments) * signedAngleRad;
        return new THREE.Vector3(
          angleOrigin.x + Math.cos(angle) * 4.2,
          angleOrigin.y,
          angleOrigin.z + Math.sin(angle) * 4.2,
        );
      });
      const angleArc = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(arcPoints),
        new THREE.LineBasicMaterial({ color: 0xfef3c7, transparent: true, opacity: 0.9, depthTest: false }),
      );
      angleArc.renderOrder = 5;
      model.add(angleArc);
      const angleLabel = makeAngleLabel(normalizedAngleDeg);
      if (angleLabel) {
        const labelAngle = signedAngleRad / 2;
        angleLabel.position.set(
          angleOrigin.x + Math.cos(labelAngle) * 7,
          angleOrigin.y + 1.2,
          angleOrigin.z + Math.sin(labelAngle) * 7,
        );
        model.add(angleLabel);
      }
    }

    if (magnetActive) {
      const fieldSampleY = [-2.8, 0, 2.8] as const;
      FIELD_DEPTH_SLICES.forEach((z, sampleIndex) => {
        const fieldSample = addArrow(
          model,
          new THREE.Vector3(1, 0, 0),
          new THREE.Vector3(-innerX + 0.4, fieldSampleY[sampleIndex], z),
          Math.max(1, innerX * 2 - 0.8),
          0x67e8f9,
          1.7,
        );
        [fieldSample.line.material, fieldSample.cone.material].forEach((material, partIndex) => {
          const materials = Array.isArray(material) ? material : [material];
          materials.forEach((sampleMaterial) => {
            sampleMaterial.depthTest = false;
            sampleMaterial.transparent = true;
            sampleMaterial.opacity = partIndex === 0 ? 0.76 : 0.88;
          });
        });
        fieldSample.line.renderOrder = 4;
        fieldSample.cone.renderOrder = 4;
      });
    }

    if (fieldSource === 'combined' && Math.abs(forceYN) > 1e-9) {
      const forceUp = forceYN > 0;
      addArrow(
        model,
        new THREE.Vector3(0, forceUp ? 1 : -1, 0),
        new THREE.Vector3(0, forceUp ? WIRE_RADIUS_MM + 1 : -WIRE_RADIUS_MM - 1, SOLVED_DEPTH_MM / 2 + 2),
        13,
        FORCE_VECTOR_COLOR,
        3,
      );
    }

    const grid = new THREE.GridHelper(90, 18, 0x334155, 0x1e293b);
    grid.position.y = -11;
    const gridMaterial = grid.material as THREE.Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = 0.3;
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
      scene.traverse(disposeSceneObject);
      magnetHalfGeometry.dispose();
      northMaterial.dispose();
      southMaterial.dispose();
      copperMaterial.dispose();
      environmentTarget.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [angleRad, currentA, currentDirectionX, currentDirectionZ, currentSign, fieldSource, forceYN, normalizedAngleDeg, poleGapMm]);

  const currentDirection = normalizedAngleDeg === 0 || normalizedAngleDeg === 360
    ? currentA >= 0 ? 'along field (+X)' : 'against field (−X)'
    : normalizedAngleDeg === 180
      ? currentA >= 0 ? 'against field (−X)' : 'along field (+X)'
      : normalizedAngleDeg === 90
        ? currentA >= 0 ? 'out of screen (+Z)' : 'into screen (−Z)'
        : normalizedAngleDeg === 270
          ? currentA >= 0 ? 'into screen (−Z)' : 'out of screen (+Z)'
          : `${normalizedAngleDeg}° signed phase from +X`;
  const forceDirection = Math.abs(forceYN) < 1e-9 ? 'zero' : forceYN > 0 ? 'up (+Y)' : 'down (−Y)';
  const rawSinTheta = Math.sin(angleRad);
  const sinTheta = Math.abs(rawSinTheta) < 1e-9 ? 0 : rawSinTheta;

  return (
    <div className="field-force-three">
      <div className="field-force-three-legend" aria-hidden="true">
        <span className="is-magnet">N42 pole pair · B +X · 3 depth samples</span>
        <span className="is-copper">Copper conductor</span>
        <span className="is-current">Current I {currentDirection} · 3 self-field rings</span>
        {fieldSource === 'combined' ? <span className="is-force">Force {forceDirection}</span> : null}
        <span className="is-angle">signed phase θ = {normalizedAngleDeg}° · sin θ = {sinTheta.toFixed(3)}</span>
        <em>{poleGapMm.toFixed(1)} mm each side · 10 mm solved depth</em>
      </div>
      <div className="field-force-three-axis" aria-hidden="true">
        <span><b>Y</b> ↑</span>
        <span><b>X</b> →</span>
        <span><b>Z</b> ↗</span>
      </div>
      <div className="field-force-three-hint">
        Drag to orbit · the conductor and its self-field rings rotate with θ while B stays along +X
      </div>
      <div
        ref={containerRef}
        className="field-force-three-canvas"
        role="img"
        aria-label={`Interactive three-dimensional extrusion of the Lesson 5 fixture: two N42 magnet poles separated from a copper conductor by ${poleGapMm.toFixed(1)} millimeters on each side. The signed current phase from the magnetic field is ${normalizedAngleDeg} degrees. Three transverse permanent-magnet field samples and three circular conductor self-field rings are distributed along the 10 millimeter solved depth. The conductor current points ${currentDirection}${fieldSource === 'combined' ? ` and the resulting force is ${forceDirection}` : ''}.`}
      />
    </div>
  );
};
