import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import { ViewportNavigationControls } from '../ViewportNavigation';
import type { HalbachArrayConfig, HalbachReport } from './types';
import { halbachDisplaySegments } from './geometry';
import {
  HALBACH_POLE_NORTH_FALLBACK,
  HALBACH_POLE_SOUTH_FALLBACK,
  clipHalbachPoleHalf,
  halbachWedgeCentroid,
  halbachWedgePolygon,
  type HalbachPolePoint,
} from './poleRendering';

interface Halbach3DViewerProps {
  config: HalbachArrayConfig;
  report: HalbachReport | null;
  axialOutputsStale?: boolean;
  selectedSegment: number | null;
  onSelectSegment: (index: number | null) => void;
}

interface SceneHandles {
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  segmentGroup: THREE.Group;
  arrowGroup: THREE.Group;
  raycaster: THREE.Raycaster;
  pointer: THREE.Vector2;
}

function polygonShape(points: HalbachPolePoint[]): THREE.Shape {
  const shape = new THREE.Shape();
  points.forEach(([x, y], index) => {
    if (index === 0) shape.moveTo(x, y);
    else shape.lineTo(x, y);
  });
  if (points.length > 0) {
    shape.lineTo(points[0][0], points[0][1]);
  }
  shape.closePath();
  return shape;
}

export function Halbach3DViewer({
  config,
  report,
  axialOutputsStale = false,
  selectedSegment,
  onSelectSegment,
}: Halbach3DViewerProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const handlesRef = useRef<SceneHandles | null>(null);
  const animationRef = useRef<number | null>(null);
  const fittedDistanceRef = useRef(1);
  const selectedSegmentRef = useRef(selectedSegment);
  selectedSegmentRef.current = selectedSegment;
  const [cutaway, setCutaway] = useState(false);
  const [explode, setExplode] = useState(0);
  const [fitNonce, setFitNonce] = useState(0);
  const [zoomScale, setZoomScale] = useState(1);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setClearColor(0x101014, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.replaceChildren(renderer.domElement);
    renderer.domElement.setAttribute(
      'aria-label',
      `Extruded Halbach assembly with ${config.geometry.segment_count} selectable magnet segments`,
    );
    renderer.domElement.setAttribute('role', 'img');
    renderer.domElement.tabIndex = 0;
    renderer.domElement.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        onSelectSegment(null);
      } else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
        event.preventDefault();
        onSelectSegment(((selectedSegmentRef.current ?? -1) + 1) % config.geometry.segment_count);
      } else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
        event.preventDefault();
        onSelectSegment(
          ((selectedSegmentRef.current ?? 0) - 1 + config.geometry.segment_count)
            % config.geometry.segment_count,
        );
      }
    });

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 10000);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;
    controls.target.set(0, 0, 0);
    const updateZoomScale = () => {
      const distance = camera.position.distanceTo(controls.target);
      setZoomScale(fittedDistanceRef.current / Math.max(distance, Number.EPSILON));
    };
    controls.addEventListener('change', updateZoomScale);

    scene.add(new THREE.HemisphereLight(0xe5e7eb, 0x15161b, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 3.2);
    key.position.set(100, -140, 190);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xf59e0b, 1.35);
    rim.position.set(-120, 80, 40);
    scene.add(rim);

    const ground = new THREE.GridHelper(
      Math.max(300, config.geometry.outer_radius * 7),
      18,
      0x3a3f49,
      0x24272e,
    );
    ground.rotation.x = Math.PI / 2;
    ground.position.z = -config.geometry.axial_length / 2 - 1;
    scene.add(ground);

    const segmentGroup = new THREE.Group();
    const arrowGroup = new THREE.Group();
    scene.add(segmentGroup, arrowGroup);
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    handlesRef.current = {
      camera,
      controls,
      renderer,
      scene,
      segmentGroup,
      arrowGroup,
      raycaster,
      pointer,
    };

    const resize = () => {
      const width = Math.max(320, host.clientWidth);
      const height = Math.max(320, host.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    const selectAtPointer = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(segmentGroup.children, false)[0];
      onSelectSegment(hit ? Number(hit.object.userData.segmentIndex) : null);
    };
    renderer.domElement.addEventListener('pointerdown', selectAtPointer);

    const animate = () => {
      controls.update();
      renderer.render(scene, camera);
      animationRef.current = requestAnimationFrame(animate);
    };
    animate();

    return () => {
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      renderer.domElement.removeEventListener('pointerdown', selectAtPointer);
      observer.disconnect();
      controls.removeEventListener('change', updateZoomScale);
      controls.dispose();
      renderer.dispose();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => material.dispose());
        }
      });
      handlesRef.current = null;
    };
  }, [config.geometry.axial_length, config.geometry.outer_radius, config.geometry.segment_count, onSelectSegment]);

  useEffect(() => {
    const handles = handlesRef.current;
    const host = hostRef.current;
    if (!handles || !host) return;
    const { segmentGroup, arrowGroup } = handles;
    for (const child of [...segmentGroup.children, ...arrowGroup.children]) {
      child.removeFromParent();
      if (child instanceof THREE.Mesh) {
        child.geometry.dispose();
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.forEach((material) => material.dispose());
      }
    }

    const midRadius = (config.geometry.inner_radius + config.geometry.outer_radius) / 2;
    const arrowLength = Math.max(5, (config.geometry.outer_radius - config.geometry.inner_radius) * 0.38);
    const hostStyle = window.getComputedStyle(host);
    const northPoleColor = hostStyle.getPropertyValue('--halbach-pole-north').trim()
      || HALBACH_POLE_NORTH_FALLBACK;
    const southPoleColor = hostStyle.getPropertyValue('--halbach-pole-south').trim()
      || HALBACH_POLE_SOUTH_FALLBACK;
    for (const segment of halbachDisplaySegments(config)) {
      const { index, centerDeg: theta } = segment;
      const hiddenByCutaway = cutaway && Math.cos(THREE.MathUtils.degToRad(theta - 315)) > Math.cos(Math.PI / 4);
      if (hiddenByCutaway) continue;
      const wedgePoints = halbachWedgePolygon(
        config.geometry.inner_radius,
        config.geometry.outer_radius,
        segment.startDeg,
        segment.endDeg,
      );
      const centroid = halbachWedgeCentroid(
        config.geometry.inner_radius,
        config.geometry.outer_radius,
        segment.startDeg,
        segment.endDeg,
      );
      const alpha = THREE.MathUtils.degToRad(segment.magnetizationDeg);
      const northNormal: HalbachPolePoint = [Math.cos(alpha), Math.sin(alpha)];
      const poleHalves = [
        {
          name: 'N',
          color: northPoleColor,
          points: clipHalbachPoleHalf(wedgePoints, northNormal, centroid),
        },
        {
          name: 'S',
          color: southPoleColor,
          points: clipHalbachPoleHalf(
            wedgePoints,
            [-northNormal[0], -northNormal[1]],
            centroid,
          ),
        },
      ] as const;
      const selected = selectedSegment === index;
      const thetaRad = THREE.MathUtils.degToRad(theta);
      poleHalves.forEach((half) => {
        if (half.points.length < 3) return;
        const geometry = new THREE.ExtrudeGeometry(
          polygonShape(half.points),
          {
            depth: config.geometry.axial_length,
            bevelEnabled: false,
            curveSegments: 2,
            steps: 1,
          },
        );
        geometry.translate(0, 0, -config.geometry.axial_length / 2);
        geometry.computeVertexNormals();
        const material = new THREE.MeshStandardMaterial({
          color: new THREE.Color(selected ? 0xf59e0b : half.color),
          metalness: 0.18,
          roughness: 0.54,
          emissive: selected ? new THREE.Color(0x4a2d05) : new THREE.Color(0x000000),
          side: THREE.DoubleSide,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.set(
          Math.cos(thetaRad) * explode,
          Math.sin(thetaRad) * explode,
          0,
        );
        mesh.userData.segmentIndex = index;
        mesh.userData.poleFace = half.name;
        mesh.name = `Halbach segment ${index + 1} ${half.name} half`;
        segmentGroup.add(mesh);
      });

      const direction = new THREE.Vector3(Math.cos(alpha), Math.sin(alpha), 0).normalize();
      const origin = new THREE.Vector3(
        Math.cos(thetaRad) * (midRadius + explode),
        Math.sin(thetaRad) * (midRadius + explode),
        config.geometry.axial_length / 2 + 0.7,
      ).addScaledVector(direction, -arrowLength / 2);
      const arrow = new THREE.ArrowHelper(
        direction,
        origin,
        arrowLength,
        selectedSegment === index ? 0xffd166 : 0xffffff,
        Math.max(1.5, arrowLength * 0.22),
        Math.max(0.9, arrowLength * 0.1),
      );
      arrowGroup.add(arrow);
    }
  }, [config, cutaway, explode, selectedSegment]);

  useEffect(() => {
    const handles = handlesRef.current;
    if (!handles) return;
    const radius = Math.max(config.geometry.outer_radius, config.geometry.axial_length / 2);
    handles.camera.position.set(radius * 2.15, -radius * 2.15, radius * 1.55);
    fittedDistanceRef.current = handles.camera.position.distanceTo(handles.controls.target);
    handles.controls.minDistance = Math.max(radius * 0.35, 1);
    handles.controls.maxDistance = radius * 9;
    handles.camera.near = Math.max(0.1, radius / 200);
    handles.camera.far = Math.max(2000, radius * 30);
    handles.camera.updateProjectionMatrix();
    handles.controls.target.set(0, 0, 0);
    handles.controls.update();
    setZoomScale(1);
  }, [config.geometry.axial_length, config.geometry.outer_radius, fitNonce]);

  const zoomBy = (factor: number) => {
    const handles = handlesRef.current;
    if (!handles) return;
    const offset = handles.camera.position.clone().sub(handles.controls.target);
    const currentDistance = offset.length();
    const nextDistance = THREE.MathUtils.clamp(
      currentDistance / factor,
      handles.controls.minDistance,
      handles.controls.maxDistance,
    );
    handles.camera.position.copy(
      handles.controls.target.clone().add(offset.setLength(nextDistance)),
    );
    handles.controls.update();
    setZoomScale(fittedDistanceRef.current / Math.max(nextDistance, Number.EPSILON));
  };

  return (
    <figure className="halbach-viewport halbach-viewport-3d">
      <div className="halbach-3d-toolbar" aria-label="3D view controls">
        <label>
          <input type="checkbox" checked={cutaway} onChange={(event) => setCutaway(event.target.checked)} />
          Cutaway
        </label>
        <label className="explode-control">
          Radial explode
          <input
            aria-label="Radial explode distance"
            type="range"
            min={0}
            max={Math.max(5, config.geometry.outer_radius * 0.6)}
            step={0.5}
            value={explode}
            onChange={(event) => setExplode(Number(event.target.value))}
          />
        </label>
      </div>
      <div ref={hostRef} className="halbach-3d-canvas" />
      <div className="halbach-pole-legend" aria-label="Halbach pole color legend">
        <span><i className="is-north" aria-hidden="true" />red = N face</span>
        <span><i className="is-south" aria-hidden="true" />blue = S face</span>
      </div>
      <ViewportNavigationControls
        scale={zoomScale}
        onZoomIn={() => zoomBy(1.25)}
        onZoomOut={() => zoomBy(0.8)}
        onReset={() => setFitNonce((value) => value + 1)}
        fitSubject="Halbach array"
      />
      {report && (
        <div className="field-extrusion-badge">
          2D field extrusion{axialOutputsStale ? ' · axial scaling stale' : ''}
        </div>
      )}
    </figure>
  );
}
