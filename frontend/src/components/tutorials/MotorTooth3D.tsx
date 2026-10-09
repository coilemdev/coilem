import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

interface MotorTooth3DProps {
  currentA: number;
  rotorMode?: 'steel' | 'spm';
  saturated: boolean;
}

const BACKGROUND = 0x080d16;
const STACK_DEPTH_MM = 44;

function curvedBandShape(
  halfWidthMm: number,
  lowerYmm: number,
  upperYmm: number,
  sagMm: number,
): THREE.Shape {
  const shape = new THREE.Shape();
  const segments = 24;
  const point = (index: number, baseYmm: number) => {
    const x = -halfWidthMm + 2 * halfWidthMm * index / segments;
    const normalizedX = x / halfWidthMm;
    return new THREE.Vector2(x, baseYmm - sagMm * normalizedX * normalizedX);
  };
  const first = point(0, lowerYmm);
  shape.moveTo(first.x, first.y);
  for (let index = 1; index <= segments; index += 1) {
    const next = point(index, lowerYmm);
    shape.lineTo(next.x, next.y);
  }
  for (let index = segments; index >= 0; index -= 1) {
    const next = point(index, upperYmm);
    shape.lineTo(next.x, next.y);
  }
  shape.closePath();
  return shape;
}

function roundedRectShape(
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): THREE.Shape {
  const shape = new THREE.Shape();
  shape.moveTo(x + radius, y);
  shape.lineTo(x + width - radius, y);
  shape.quadraticCurveTo(x + width, y, x + width, y + radius);
  shape.lineTo(x + width, y + height - radius);
  shape.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  shape.lineTo(x + radius, y + height);
  shape.quadraticCurveTo(x, y + height, x, y + height - radius);
  shape.lineTo(x, y + radius);
  shape.quadraticCurveTo(x, y, x + radius, y);
  shape.closePath();
  return shape;
}

function extrudedPart(
  shape: THREE.Shape,
  material: THREE.Material,
  depthMm = STACK_DEPTH_MM,
): THREE.Mesh {
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: depthMm,
    bevelEnabled: true,
    bevelSegments: 2,
    bevelSize: 0.55,
    bevelThickness: 0.55,
    curveSegments: 24,
  });
  geometry.translate(0, 0, -depthMm / 2);
  geometry.computeVertexNormals();
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function addEdges(target: THREE.Group, mesh: THREE.Mesh, color = 0x94a3b8) {
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry, 26),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.52 }),
  );
  edges.position.copy(mesh.position);
  edges.rotation.copy(mesh.rotation);
  target.add(edges);
}

function windingLoop(yMm: number, halfWidthMm: number, color: number): THREE.Mesh {
  const halfDepth = STACK_DEPTH_MM / 2 + 7;
  const corner = 5.5;
  const points = [
    new THREE.Vector3(-halfWidthMm, yMm, -halfDepth + corner),
    new THREE.Vector3(-halfWidthMm, yMm, halfDepth - corner),
    new THREE.Vector3(-halfWidthMm + 1.4, yMm, halfDepth - 1.7),
    new THREE.Vector3(-halfWidthMm + corner, yMm, halfDepth),
    new THREE.Vector3(halfWidthMm - corner, yMm, halfDepth),
    new THREE.Vector3(halfWidthMm - 1.4, yMm, halfDepth - 1.7),
    new THREE.Vector3(halfWidthMm, yMm, halfDepth - corner),
    new THREE.Vector3(halfWidthMm, yMm, -halfDepth + corner),
    new THREE.Vector3(halfWidthMm - 1.4, yMm, -halfDepth + 1.7),
    new THREE.Vector3(halfWidthMm - corner, yMm, -halfDepth),
    new THREE.Vector3(-halfWidthMm + corner, yMm, -halfDepth),
    new THREE.Vector3(-halfWidthMm + 1.4, yMm, -halfDepth + 1.7),
  ];
  const curve = new THREE.CatmullRomCurve3(points, true, 'centripetal', 0.28);
  const geometry = new THREE.TubeGeometry(curve, 192, 1.15, 14, true);
  const material = new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 0.13,
    metalness: 0.72,
    roughness: 0.24,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function fluxLoop(side: -1 | 1): THREE.Mesh {
  const points = [
    new THREE.Vector3(0, 15, 23),
    new THREE.Vector3(0, 1, 23),
    new THREE.Vector3(side * 2, -9, 23),
    new THREE.Vector3(side * 18, -12, 23),
    new THREE.Vector3(side * 28, -5, 23),
    new THREE.Vector3(side * 28, 12, 23),
    new THREE.Vector3(side * 20, 19, 23),
    new THREE.Vector3(side * 7, 20, 23),
  ];
  const curve = new THREE.CatmullRomCurve3(points, false, 'centripetal', 0.32);
  return new THREE.Mesh(
    new THREE.TubeGeometry(curve, 120, 0.42, 8, false),
    new THREE.MeshBasicMaterial({
      color: 0x67e8f9,
      transparent: true,
      opacity: 0.7,
      depthTest: false,
    }),
  );
}

export const MotorTooth3D: React.FC<MotorTooth3DProps> = ({
  currentA,
  rotorMode = 'steel',
  saturated,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BACKGROUND);
    scene.fog = new THREE.Fog(BACKGROUND, 150, 300);

    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 700);
    camera.position.set(110, 74, 145);

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
    scene.environmentIntensity = 0.5;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 1, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.minDistance = 72;
    controls.maxDistance = 220;

    scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.2));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(80, 110, 105);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x67e8f9, 1.15);
    rim.position.set(-90, 25, -90);
    scene.add(rim);
    const copperFill = new THREE.DirectionalLight(0xf59e0b, 0.72);
    copperFill.position.set(60, -40, 70);
    scene.add(copperFill);

    const model = new THREE.Group();
    model.rotation.x = -0.05;
    scene.add(model);

    const steelMaterial = new THREE.MeshStandardMaterial({
      color: 0x64748b,
      metalness: 0.58,
      roughness: 0.34,
    });
    const toothMaterial = new THREE.MeshStandardMaterial({
      color: saturated ? 0xb4534b : 0x94a3b8,
      emissive: saturated ? 0x7f1d1d : 0x0f172a,
      emissiveIntensity: saturated ? 0.2 : 0.04,
      metalness: 0.5,
      roughness: 0.3,
    });
    const rotorMaterial = new THREE.MeshStandardMaterial({
      color: 0x475569,
      metalness: 0.62,
      roughness: 0.32,
    });
    const magnetMaterial = new THREE.MeshStandardMaterial({
      color: 0xef4444,
      emissive: 0x7f1d1d,
      emissiveIntensity: 0.14,
      metalness: 0.42,
      roughness: 0.28,
    });

    const steelParts = [
      extrudedPart(curvedBandShape(32, 16, 26, 1.8), steelMaterial),
      extrudedPart(roundedRectShape(-32, -8, 8, 24, 0.8), steelMaterial),
      extrudedPart(roundedRectShape(24, -8, 8, 24, 0.8), steelMaterial),
      extrudedPart(roundedRectShape(-6, -8, 12, 24, 1.1), toothMaterial),
      extrudedPart(
        rotorMode === 'spm'
          ? curvedBandShape(34, -23, -15, 1.6)
          : curvedBandShape(34, -20, -10, 1.6),
        rotorMaterial,
      ),
    ];
    steelParts.forEach((part) => {
      model.add(part);
      addEdges(model, part);
    });
    if (rotorMode === 'spm') {
      const magnet = extrudedPart(
        curvedBandShape(9, -15, -10, 1.6 * (9 / 34) ** 2),
        magnetMaterial,
      );
      model.add(magnet);
      addEdges(model, magnet, 0xfca5a5);
    }

    const copperColor = saturated ? 0xf59e0b : 0xd97706;
    [
      windingLoop(0.5, 12.8, copperColor),
      windingLoop(4.2, 14.1, copperColor),
      windingLoop(7.9, 15.4, copperColor),
    ].forEach((coil) => model.add(coil));

    model.add(fluxLoop(-1));
    model.add(fluxLoop(1));

    const airgap = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(-6, -9, 23.2),
        new THREE.Vector3(6, -9, 23.2),
      ]),
      new THREE.LineBasicMaterial({ color: 0x67e8f9, transparent: true, opacity: 0.95 }),
    );
    model.add(airgap);

    const grid = new THREE.GridHelper(100, 20, 0x334155, 0x1e293b);
    grid.position.y = -23;
    const gridMaterial = grid.material as THREE.Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = 0.32;
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
          || object instanceof THREE.LineSegments
        ) {
          object.geometry?.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => {
            material.dispose();
          });
        }
      });
      environmentTarget.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [currentA, rotorMode, saturated]);

  return (
    <div className="iron-tooth-three">
      <div className="iron-tooth-three-legend" aria-hidden="true">
        <span className="is-steel">M350-50A steel</span>
        {rotorMode === 'spm' ? <span className="is-magnet">N42 surface magnet · N faces stator</span> : null}
        <span className="is-copper">Copper winding · ⊙ out / ⊗ in</span>
        <span className="is-flux">Flux path</span>
        <span className={saturated ? 'is-saturated' : 'is-tooth'}>
          {currentA.toFixed(0)} A · {saturated ? 'tooth saturated' : 'tooth below knee'}
        </span>
        <em>Illustrative extrusion · 2D nonlinear FEM</em>
      </div>
      <div className="iron-tooth-three-hint">Drag to orbit · Scroll to zoom · copper closes around both stack ends</div>
      <div
        ref={containerRef}
        className="iron-tooth-three-canvas"
        role="img"
        aria-label={`Interactive three-dimensional motor segment showing copper turns wrapping around an energized M350-50A stator tooth, the curved yoke, airgap, and ${rotorMode === 'spm' ? 'an N42 surface magnet on curved rotor back iron' : 'curved rotor return'}`}
      />
    </div>
  );
};
