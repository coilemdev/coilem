import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import './current-conductor-three.css';

interface CurrentConductor3DProps {
  currentA: number;
  mode?: 'air' | 'iron-ring';
  saturated?: boolean;
}

const BACKGROUND = 0x080d16;
const CONDUCTOR_RADIUS_MM = 5;
const CONDUCTOR_LENGTH_MM = 92;

function ironRingGeometry(): THREE.ExtrudeGeometry {
  const shape = new THREE.Shape();
  shape.absarc(0, 0, 39, 0, Math.PI * 2, false);
  const hole = new THREE.Path();
  hole.absarc(0, 0, 11, 0, Math.PI * 2, true);
  shape.holes.push(hole);
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: 18,
    bevelEnabled: true,
    bevelSegments: 2,
    bevelSize: 0.7,
    bevelThickness: 0.7,
    curveSegments: 72,
  });
  geometry.translate(0, 0, -9);
  geometry.computeVertexNormals();
  return geometry;
}

function orientAlong(mesh: THREE.Object3D, direction: THREE.Vector3) {
  mesh.quaternion.setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    direction.clone().normalize(),
  );
}

export const CurrentConductor3D: React.FC<CurrentConductor3DProps> = ({
  currentA,
  mode = 'air',
  saturated = false,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BACKGROUND);
    scene.fog = new THREE.Fog(BACKGROUND, 155, 290);

    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 600);
    camera.position.set(92, 68, 112);

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
    controls.minDistance = 58;
    controls.maxDistance = 205;

    scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.22));
    const key = new THREE.DirectionalLight(0xffffff, 2.35);
    key.position.set(75, 100, 105);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x67e8f9, 1.25);
    rim.position.set(-90, 20, -85);
    scene.add(rim);
    const copperFill = new THREE.DirectionalLight(0xf59e0b, 0.78);
    copperFill.position.set(65, -48, 75);
    scene.add(copperFill);

    const model = new THREE.Group();
    model.rotation.x = -0.06;
    scene.add(model);

    if (mode === 'iron-ring') {
      const ringMaterial = new THREE.MeshStandardMaterial({
        color: saturated ? 0x9f3f46 : 0x64748b,
        emissive: saturated ? 0x7f1d1d : 0x0f172a,
        emissiveIntensity: saturated ? 0.22 : 0.04,
        metalness: 0.58,
        roughness: 0.34,
      });
      const ring = new THREE.Mesh(ironRingGeometry(), ringMaterial);
      ring.castShadow = true;
      ring.receiveShadow = true;
      model.add(ring);
      const ringEdges = new THREE.LineSegments(
        new THREE.EdgesGeometry(ring.geometry, 24),
        new THREE.LineBasicMaterial({
          color: saturated ? 0xfca5a5 : 0x94a3b8,
          transparent: true,
          opacity: 0.54,
        }),
      );
      model.add(ringEdges);
    } else {
      const domain = new THREE.Mesh(
        new THREE.CircleGeometry(49, 96),
        new THREE.MeshBasicMaterial({
          color: 0x0f1d35,
          transparent: true,
          opacity: 0.42,
          side: THREE.DoubleSide,
          depthWrite: false,
        }),
      );
      domain.position.z = -4;
      model.add(domain);
      const boundary = new THREE.LineLoop(
        new THREE.BufferGeometry().setFromPoints(
          Array.from({ length: 97 }, (_, index) => {
            const angle = index / 96 * Math.PI * 2;
            return new THREE.Vector3(49 * Math.cos(angle), 49 * Math.sin(angle), -3.8);
          }),
        ),
        new THREE.LineBasicMaterial({
          color: 0x334155,
          transparent: true,
          opacity: 0.7,
        }),
      );
      model.add(boundary);
    }

    const conductor = new THREE.Mesh(
      new THREE.CylinderGeometry(
        CONDUCTOR_RADIUS_MM,
        CONDUCTOR_RADIUS_MM,
        CONDUCTOR_LENGTH_MM,
        48,
      ),
      new THREE.MeshStandardMaterial({
        color: 0xc96b16,
        emissive: 0x7c2d12,
        emissiveIntensity: 0.12,
        metalness: 0.76,
        roughness: 0.22,
      }),
    );
    conductor.rotation.x = Math.PI / 2;
    conductor.castShadow = true;
    conductor.receiveShadow = true;
    model.add(conductor);
    const conductorEdges = new THREE.LineSegments(
      new THREE.EdgesGeometry(conductor.geometry, 28),
      new THREE.LineBasicMaterial({
        color: 0xfbbf24,
        transparent: true,
        opacity: 0.76,
      }),
    );
    conductorEdges.rotation.copy(conductor.rotation);
    model.add(conductorEdges);

    const normalizedStrength = Math.min(1, Math.abs(currentA) / (mode === 'iron-ring' ? 800 : 16));
    const fieldOpacity = currentA === 0 ? 0.12 : 0.36 + normalizedStrength * 0.46;
    const fieldDirection = currentA < 0 ? -1 : 1;
    const loopRadii = mode === 'iron-ring' ? [16, 23, 31, 36] : [13, 21, 31, 42];
    const loopZ = mode === 'iron-ring' ? 10.2 : 1;
    loopRadii.forEach((radius, radiusIndex) => {
      const loop = new THREE.Mesh(
        new THREE.TorusGeometry(radius, radiusIndex === 0 ? 0.68 : 0.48, 10, 112),
        new THREE.MeshBasicMaterial({
          color: radiusIndex === 0 ? 0x67e8f9 : 0x38bdf8,
          transparent: true,
          opacity: fieldOpacity * (1 - radiusIndex * 0.08),
          depthTest: mode !== 'iron-ring',
        }),
      );
      loop.position.z = loopZ;
      loop.renderOrder = 3;
      model.add(loop);

      [0.55, 2.65, 4.75].forEach((angle) => {
        const tangent = new THREE.Vector3(
          -Math.sin(angle) * fieldDirection,
          Math.cos(angle) * fieldDirection,
          0,
        );
        const arrow = new THREE.Mesh(
          new THREE.ConeGeometry(1.25, 4.2, 12),
          new THREE.MeshBasicMaterial({
            color: 0xa5f3fc,
            transparent: true,
            opacity: Math.min(1, fieldOpacity + 0.18),
            depthTest: mode !== 'iron-ring',
          }),
        );
        arrow.position.set(radius * Math.cos(angle), radius * Math.sin(angle), loopZ + 0.4);
        orientAlong(arrow, tangent);
        arrow.renderOrder = 4;
        model.add(arrow);
      });
    });

    if (Math.abs(currentA) > 0.01) {
      const axialDirection = new THREE.Vector3(0, 0, fieldDirection);
      const arrowShaft = new THREE.Mesh(
        new THREE.CylinderGeometry(0.72, 0.72, 20, 16),
        new THREE.MeshBasicMaterial({ color: 0xfef3c7 }),
      );
      orientAlong(arrowShaft, axialDirection);
      arrowShaft.position.z = fieldDirection * 34;
      model.add(arrowShaft);
      const arrowHead = new THREE.Mesh(
        new THREE.ConeGeometry(2.5, 7.5, 20),
        new THREE.MeshBasicMaterial({ color: 0xfef3c7 }),
      );
      orientAlong(arrowHead, axialDirection);
      arrowHead.position.z = fieldDirection * 48;
      model.add(arrowHead);
    }

    const grid = new THREE.GridHelper(110, 22, 0x334155, 0x1e293b);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -12;
    const gridMaterial = grid.material as THREE.Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = mode === 'iron-ring' ? 0.18 : 0.32;
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
      scene.traverse((object) => {
        if (
          object instanceof THREE.Mesh
          || object instanceof THREE.Line
          || object instanceof THREE.LineLoop
          || object instanceof THREE.LineSegments
        ) {
          object.geometry?.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => material.dispose());
        }
      });
      environmentTarget.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [currentA, mode, saturated]);

  const hasCurrent = Math.abs(currentA) > 0.01;
  const circulation = !hasCurrent ? 'no field' : currentA > 0 ? 'counterclockwise B' : 'clockwise B';
  const axialDirection = !hasCurrent ? '0 A' : currentA > 0 ? 'out of screen' : 'into screen';

  return (
    <div className={`current-conductor-three is-${mode}`}>
      <div className="current-conductor-three-legend" aria-hidden="true">
        <span className="is-copper">Copper conductor · {currentA > 0 ? '+' : ''}{currentA.toFixed(0)} A</span>
        {mode === 'iron-ring' ? (
          <span className={saturated ? 'is-saturated' : 'is-steel'}>
            M350-50A ring · {saturated ? 'saturated' : 'below knee'}
          </span>
        ) : (
          <span className="is-air">Air domain</span>
        )}
        <span className="is-field">{circulation}</span>
        <em>{axialDirection} · interactive extrusion of the 2D field model</em>
      </div>
      <div className="current-conductor-three-hint">
        Drag to orbit · Scroll to zoom · field loops wrap around the conductor
      </div>
      <div
        ref={containerRef}
        className="current-conductor-three-canvas"
        role="img"
        aria-label={`Interactive three-dimensional ${mode === 'iron-ring' ? 'M350-50A ring and ' : ''}straight copper conductor carrying ${currentA.toFixed(0)} amperes ${axialDirection}, with ${circulation}`}
      />
    </div>
  );
};
