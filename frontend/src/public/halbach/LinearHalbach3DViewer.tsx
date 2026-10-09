import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import { ViewportNavigationControls } from '../ViewportNavigation';
import type {
  LinearHalbachResultView,
  LinearHalbachViewportMode,
} from './LinearHalbach2DViewport';
import {
  HALBACH_POLE_NORTH_FALLBACK,
  HALBACH_POLE_SOUTH_FALLBACK,
  clipHalbachPoleHalf,
  type HalbachPolePoint,
} from './poleRendering';
import type {
  HalbachContourLevel,
  LinearHalbachArrayConfig,
  LinearHalbachMeshPreview,
  LinearHalbachReport,
} from './types';

interface LinearHalbach3DViewerProps {
  config: LinearHalbachArrayConfig;
  mesh: LinearHalbachMeshPreview | null;
  report: LinearHalbachReport | null;
  resultView: LinearHalbachResultView;
  viewportMode: LinearHalbachViewportMode;
  selectedMagnet: number | null;
  onSelectMagnet: (index: number | null) => void;
  showHeatmap?: boolean;
  showMeshOverlay?: boolean;
  showFieldLines?: boolean;
  fieldLineDensity?: 'low' | 'medium' | 'high';
  showMagnetization?: boolean;
  showProbeOverlays?: boolean;
  presentation?: 'workspace' | 'hero';
}

interface SceneHandles {
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  modelGroup: THREE.Group;
  magnetGroup: THREE.Group;
  arrowGroup: THREE.Group;
  sheetGroup: THREE.Group;
  overlayGroup: THREE.Group;
  raycaster: THREE.Raycaster;
  pointer: THREE.Vector2;
  grid: THREE.GridHelper;
}

interface FieldLegend {
  label: string;
  symbol: string;
  minimum: number;
  midpoint: number;
  maximum: number;
  diverging: boolean;
}

const HEAT_COLORS = [
  [20, 42, 97],
  [24, 85, 167],
  [27, 142, 183],
  [42, 182, 115],
  [167, 200, 58],
  [241, 194, 50],
  [245, 139, 36],
  [220, 61, 61],
] as const;

function heatColor(value: number): THREE.Color {
  const clamped = Math.max(0, Math.min(1, value));
  const scaled = clamped * (HEAT_COLORS.length - 1);
  const lower = Math.floor(scaled);
  const upper = Math.min(HEAT_COLORS.length - 1, lower + 1);
  const mix = scaled - lower;
  const rgb = [0, 1, 2].map((channel) => (
    HEAT_COLORS[lower][channel]
    + (HEAT_COLORS[upper][channel] - HEAT_COLORS[lower][channel]) * mix
  ));
  return new THREE.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255);
}

function divergingColor(value: number): THREE.Color {
  const clamped = Math.max(-1, Math.min(1, value));
  const neutral = new THREE.Color(0x18212d);
  const target = new THREE.Color(clamped >= 0 ? 0xfacc15 : 0x38bdf8);
  return neutral.lerp(target, Math.abs(clamped));
}

function formatLegendValue(value: number): string {
  const absolute = Math.abs(value);
  return absolute > 0 && absolute < 0.001 ? value.toExponential(2) : value.toFixed(3);
}

function maximumAbsolute(values: readonly number[]): number {
  let maximum = 1e-12;
  for (const value of values) maximum = Math.max(maximum, Math.abs(value));
  return maximum;
}

function maximumFieldMagnitude(
  fields: readonly { b_mag: number }[],
): number {
  let maximum = 1e-12;
  for (const field of fields) maximum = Math.max(maximum, field.b_mag);
  return maximum;
}

function sampledDirectionCues(
  contours: HalbachContourLevel[],
  target: number,
): Array<{ x: number; y: number; dx: number; dy: number }> {
  const candidates = contours.flatMap((level) => level.segments_mm.flatMap((segment, index) => {
    const bx = level.segment_bx_t?.[index];
    const by = level.segment_by_t?.[index];
    if (!Number.isFinite(bx) || !Number.isFinite(by)) return [];
    const magnitude = Math.hypot(bx ?? 0, by ?? 0);
    if (magnitude <= 1e-12) return [];
    return [{
      x: (segment[0] + segment[2]) / 2,
      y: (segment[1] + segment[3]) / 2,
      dx: (bx ?? 0) / magnitude,
      dy: (by ?? 0) / magnitude,
    }];
  }));
  if (candidates.length <= target) return candidates;
  return Array.from({ length: target }, (_, index) => (
    candidates[Math.round(index * (candidates.length - 1) / Math.max(1, target - 1))]
  ));
}

function polygonShape(points: HalbachPolePoint[]): THREE.Shape {
  const shape = new THREE.Shape();
  points.forEach(([x, y], index) => {
    if (index === 0) shape.moveTo(x, y);
    else shape.lineTo(x, y);
  });
  if (points.length > 0) shape.lineTo(points[0][0], points[0][1]);
  shape.closePath();
  return shape;
}

function disposeObject(object: THREE.Object3D): void {
  object.traverse((child) => {
    if (child instanceof THREE.Mesh || child instanceof THREE.Line) {
      child.geometry.dispose();
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      materials.forEach((material) => material.dispose());
    }
  });
  object.removeFromParent();
}

function clearGroup(group: THREE.Group): void {
  [...group.children].forEach(disposeObject);
}

function addLineSegments(
  group: THREE.Group,
  positions: number[],
  color: THREE.ColorRepresentation,
  opacity = 1,
): void {
  if (positions.length === 0) return;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: opacity < 1,
    opacity,
    depthWrite: opacity >= 1,
  });
  group.add(new THREE.LineSegments(geometry, material));
}

export function linearHalbachMagnetizationAngleDeg(
  config: LinearHalbachArrayConfig,
  index: number,
): number {
  const rotationSign = config.array.strong_side === 'positive_y' ? 1 : -1;
  return (config.array.phase_deg + rotationSign * 90 * index) % 360;
}

function fieldValues(
  report: LinearHalbachReport,
  resultView: LinearHalbachResultView,
): number[] {
  const { field_data: fieldData } = report;
  return fieldData.triangles.map((triangle, index) => {
    const field = fieldData.element_fields_t[index];
    if (resultView === 'bx') return field.bx;
    if (resultView === 'by') return field.by;
    if (resultView === 'az') {
      return triangle.reduce(
        (sum, nodeIndex) => sum + (fieldData.az_nodal_t_m[nodeIndex] ?? 0),
        0,
      ) / 3;
    }
    return field.b_mag;
  });
}

function fieldLegend(
  report: LinearHalbachReport | null,
  resultView: LinearHalbachResultView,
  showHeatmap: boolean,
): FieldLegend | null {
  if (!report || !showHeatmap) return null;
  const values = fieldValues(report, resultView);
  if (resultView === 'bx' || resultView === 'by' || resultView === 'az') {
    const limit = maximumAbsolute(values);
    return {
      label: resultView === 'bx'
        ? 'Along-array field'
        : resultView === 'by'
          ? 'Normal field'
          : 'Vector potential',
      symbol: resultView === 'bx'
        ? 'B_x (T)'
        : resultView === 'by'
          ? 'B_y (T)'
          : 'A_z (T m)',
      minimum: -limit,
      midpoint: 0,
      maximum: limit,
      diverging: true,
    };
  }
  const maximum = maximumAbsolute(values);
  return {
    label: 'Flux density',
    symbol: '|B| (T)',
    minimum: 0,
    midpoint: maximum / 2,
    maximum,
    diverging: false,
  };
}

/** Interactive extrusion of the planar linear-Halbach model, never a 3D FEM result. */
export function LinearHalbach3DViewer({
  config,
  mesh,
  report,
  resultView,
  viewportMode,
  selectedMagnet,
  onSelectMagnet,
  showHeatmap = true,
  showMeshOverlay = false,
  showFieldLines = true,
  fieldLineDensity = 'medium',
  showMagnetization = true,
  showProbeOverlays = true,
  presentation = 'workspace',
}: LinearHalbach3DViewerProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const handlesRef = useRef<SceneHandles | null>(null);
  const animationRef = useRef<number | null>(null);
  const fittedDistanceRef = useRef(1);
  const selectedMagnetRef = useRef(selectedMagnet);
  const selectMagnetRef = useRef(onSelectMagnet);
  selectedMagnetRef.current = selectedMagnet;
  selectMagnetRef.current = onSelectMagnet;
  const [sectioned, setSectioned] = useState(false);
  const [fitNonce, setFitNonce] = useState(0);
  const [zoomScale, setZoomScale] = useState(1);
  const magnetCount = 4 * config.geometry.period_count;
  const pitch = config.geometry.block_width + config.geometry.block_gap;
  const wavelength = 4 * pitch;
  const activeLength = magnetCount * config.geometry.block_width
    + Math.max(0, magnetCount - 1) * config.geometry.block_gap;
  const legend = useMemo(
    () => fieldLegend(
      viewportMode === 'field' ? report : null,
      resultView,
      showHeatmap,
    ),
    [report, resultView, showHeatmap, viewportMode],
  );

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const heroPresentation = presentation === 'hero';
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: heroPresentation });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setClearColor(0x101014, heroPresentation ? 0 : 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.localClippingEnabled = true;
    host.replaceChildren(renderer.domElement);
    renderer.domElement.setAttribute('role', 'img');
    renderer.domElement.tabIndex = 0;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 10000);
    camera.up.set(0, 1, 0);
    const controls = new OrbitControls(camera, renderer.domElement);
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    controls.enableDamping = !reducedMotion;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;
    controls.target.set(0, 0, 0);
    const updateZoomScale = () => {
      const distance = camera.position.distanceTo(controls.target);
      setZoomScale(fittedDistanceRef.current / Math.max(distance, Number.EPSILON));
    };
    controls.addEventListener('change', updateZoomScale);

    scene.add(new THREE.HemisphereLight(0xe5e7eb, 0x15161b, 2.15));
    const key = new THREE.DirectionalLight(0xffffff, 3.1);
    key.position.set(100, 150, 190);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xf59e0b, 1.25);
    rim.position.set(-120, 60, -80);
    scene.add(rim);

    const grid = new THREE.GridHelper(100, 20, 0x3a3f49, 0x24272e);
    grid.visible = !heroPresentation;
    scene.add(grid);
    const magnetGroup = new THREE.Group();
    const arrowGroup = new THREE.Group();
    const sheetGroup = new THREE.Group();
    const overlayGroup = new THREE.Group();
    const modelGroup = new THREE.Group();
    // Rotate the solve plane onto the tabletop while keeping the enhanced
    // +Y side toward the back/top of the default camera view.
    modelGroup.rotation.x = -Math.PI / 2;
    modelGroup.add(magnetGroup, arrowGroup, sheetGroup, overlayGroup);
    scene.add(modelGroup);
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    handlesRef.current = {
      camera,
      controls,
      renderer,
      scene,
      modelGroup,
      magnetGroup,
      arrowGroup,
      sheetGroup,
      overlayGroup,
      raycaster,
      pointer,
      grid,
    };

    const resize = () => {
      const width = host.clientWidth;
      const height = host.clientHeight;
      if (width <= 0 || height <= 0) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    renderer.domElement.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        selectMagnetRef.current(null);
      } else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
        event.preventDefault();
        selectMagnetRef.current(((selectedMagnetRef.current ?? -1) + 1) % magnetCount);
      } else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
        event.preventDefault();
        selectMagnetRef.current(
          ((selectedMagnetRef.current ?? 0) - 1 + magnetCount) % magnetCount,
        );
      }
    });

    let pointerDown: [number, number] | null = null;
    const rememberPointer = (event: PointerEvent) => {
      pointerDown = [event.clientX, event.clientY];
    };
    const selectAtPointer = (event: PointerEvent) => {
      const start = pointerDown;
      pointerDown = null;
      if (!start || Math.hypot(
        event.clientX - start[0],
        event.clientY - start[1],
      ) > 5) return;
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(magnetGroup.children, false)[0];
      selectMagnetRef.current(hit ? Number(hit.object.userData.magnetIndex) : null);
    };
    renderer.domElement.addEventListener('pointerdown', rememberPointer);
    renderer.domElement.addEventListener('pointerup', selectAtPointer);

    const animate = () => {
      controls.update();
      renderer.render(scene, camera);
      animationRef.current = window.requestAnimationFrame(animate);
    };
    animate();

    return () => {
      if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
      renderer.domElement.removeEventListener('pointerdown', rememberPointer);
      renderer.domElement.removeEventListener('pointerup', selectAtPointer);
      observer.disconnect();
      controls.removeEventListener('change', updateZoomScale);
      controls.dispose();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
          object.geometry.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => material.dispose());
        }
      });
      renderer.dispose();
      handlesRef.current = null;
    };
  }, [magnetCount, presentation]);

  useEffect(() => {
    const handles = handlesRef.current;
    const host = hostRef.current;
    if (!handles || !host) return;
    const {
      modelGroup,
      magnetGroup,
      arrowGroup,
      sheetGroup,
      overlayGroup,
      renderer,
    } = handles;
    clearGroup(magnetGroup);
    clearGroup(arrowGroup);
    clearGroup(sheetGroup);
    clearGroup(overlayGroup);
    modelGroup.position.y = config.geometry.out_of_plane_depth / 2;

    const hostStyle = window.getComputedStyle(host);
    const northPoleColor = hostStyle.getPropertyValue('--halbach-pole-north').trim()
      || HALBACH_POLE_NORTH_FALLBACK;
    const southPoleColor = hostStyle.getPropertyValue('--halbach-pole-south').trim()
      || HALBACH_POLE_SOUTH_FALLBACK;
    const depth = sectioned
      ? config.geometry.out_of_plane_depth / 2
      : config.geometry.out_of_plane_depth;
    const depthCenter = sectioned ? -config.geometry.out_of_plane_depth / 4 : 0;
    const sheetZ = sectioned ? 0.18 : config.geometry.out_of_plane_depth / 2 + 0.45;
    const blockYMin = -config.geometry.magnet_height / 2;
    const blockYMax = config.geometry.magnet_height / 2;

    for (let index = 0; index < magnetCount; index += 1) {
      const xMin = -activeLength / 2 + index * pitch;
      const xMax = xMin + config.geometry.block_width;
      const centroid: HalbachPolePoint = [
        (xMin + xMax) / 2,
        (blockYMin + blockYMax) / 2,
      ];
      const rectangle: HalbachPolePoint[] = [
        [xMin, blockYMin],
        [xMax, blockYMin],
        [xMax, blockYMax],
        [xMin, blockYMax],
      ];
      const alpha = THREE.MathUtils.degToRad(
        linearHalbachMagnetizationAngleDeg(config, index),
      );
      const northNormal: HalbachPolePoint = [Math.cos(alpha), Math.sin(alpha)];
      const selected = selectedMagnet === index;
      const halves = [
        {
          color: northPoleColor,
          name: 'N',
          points: clipHalbachPoleHalf(rectangle, northNormal, centroid),
        },
        {
          color: southPoleColor,
          name: 'S',
          points: clipHalbachPoleHalf(
            rectangle,
            [-northNormal[0], -northNormal[1]],
            centroid,
          ),
        },
      ];
      halves.forEach((half) => {
        if (half.points.length < 3) return;
        const geometry = new THREE.ExtrudeGeometry(polygonShape(half.points), {
          depth,
          bevelEnabled: false,
          steps: 1,
        });
        geometry.translate(0, 0, depthCenter - depth / 2);
        geometry.computeVertexNormals();
        const material = new THREE.MeshStandardMaterial({
          color: new THREE.Color(selected ? 0xf59e0b : half.color),
          emissive: selected ? new THREE.Color(0x4a2d05) : new THREE.Color(0x000000),
          metalness: 0.16,
          roughness: 0.55,
          side: THREE.DoubleSide,
        });
        const magnet = new THREE.Mesh(geometry, material);
        magnet.name = `Linear Halbach magnet ${index + 1} ${half.name} half`;
        magnet.userData.magnetIndex = index;
        magnet.userData.poleFace = half.name;
        magnetGroup.add(magnet);
      });

      if (showMagnetization) {
        const direction = new THREE.Vector3(Math.cos(alpha), Math.sin(alpha), 0).normalize();
        const arrowLength = Math.max(
          3,
          Math.min(config.geometry.block_width, config.geometry.magnet_height) * 0.48,
        );
        const origin = new THREE.Vector3(
          centroid[0],
          centroid[1],
          sheetZ + 0.5,
        ).addScaledVector(direction, -arrowLength / 2);
        arrowGroup.add(new THREE.ArrowHelper(
          direction,
          origin,
          arrowLength,
          selected ? 0xffd166 : 0xffffff,
          Math.max(0.8, arrowLength * 0.22),
          Math.max(0.45, arrowLength * 0.1),
        ));
      }
    }

    const sourceMesh = viewportMode === 'field' ? report?.field_data : mesh;
    const drawMeshSheet = viewportMode === 'mesh'
      || (viewportMode === 'field' && showMeshOverlay);
    if (sourceMesh && drawMeshSheet) {
      const positions: number[] = [];
      const meshStride = Math.max(1, Math.ceil(sourceMesh.triangles.length / 30_000));
      sourceMesh.triangles.forEach((triangle, triangleIndex) => {
        if (triangleIndex % meshStride !== 0) return;
        const points = triangle.map((nodeIndex) => sourceMesh.nodes_mm[nodeIndex]);
        [[0, 1], [1, 2], [2, 0]].forEach(([start, end]) => {
          positions.push(
            points[start][0], points[start][1], sheetZ + 0.1,
            points[end][0], points[end][1], sheetZ + 0.1,
          );
        });
      });
      addLineSegments(sheetGroup, positions, 0xcbd5e1, viewportMode === 'mesh' ? 0.62 : 0.28);
    }

    if (viewportMode === 'field' && report) {
      const { field_data: fieldData } = report;
      const values = fieldValues(report, resultView);
      const absolute = resultView === 'magnitude' || resultView === 'vectors';
      const limit = maximumAbsolute(values);
      if (showHeatmap) {
        const positions: number[] = [];
        const colors: number[] = [];
        fieldData.triangles.forEach((triangle, index) => {
          const color = absolute
            ? heatColor(values[index] / limit)
            : divergingColor(values[index] / limit);
          triangle.forEach((nodeIndex) => {
            const [x, y] = fieldData.nodes_mm[nodeIndex];
            positions.push(x, y, sheetZ);
            colors.push(color.r, color.g, color.b);
          });
        });
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
        geometry.computeVertexNormals();
        const material = new THREE.MeshBasicMaterial({
          vertexColors: true,
          transparent: true,
          opacity: 0.78,
          side: THREE.DoubleSide,
          depthWrite: false,
        });
        const sheet = new THREE.Mesh(geometry, material);
        sheet.name = `Solved 2D ${resultView} field sheet`;
        sheet.userData.source = 'report.field_data';
        sheetGroup.add(sheet);
      }

      if (showFieldLines && fieldData.contours) {
        const positions: number[] = [];
        const stride = fieldLineDensity === 'low' ? 3 : fieldLineDensity === 'medium' ? 2 : 1;
        fieldData.contours.forEach((level, levelIndex) => level.segments_mm.forEach((segment) => {
          if (levelIndex % stride !== 0) return;
          if (!segment.slice(0, 4).every(Number.isFinite)) return;
          positions.push(
            segment[0], segment[1], sheetZ + 0.28,
            segment[2], segment[3], sheetZ + 0.28,
          );
        }));
        addLineSegments(sheetGroup, positions, 0xffd166, 0.96);

        const target = fieldLineDensity === 'low' ? 12 : fieldLineDensity === 'medium' ? 20 : 32;
        const cues = sampledDirectionCues(fieldData.contours, target);
        const arrowLength = Math.max(
          1.25,
          Math.min(config.geometry.block_width, config.geometry.magnet_height) * 0.24,
        );
        cues.forEach((cue) => {
          const direction = new THREE.Vector3(cue.dx, cue.dy, 0).normalize();
          const origin = new THREE.Vector3(
            cue.x,
            cue.y,
            sheetZ + 0.62,
          ).addScaledVector(direction, -arrowLength / 2);
          sheetGroup.add(new THREE.ArrowHelper(
            direction,
            origin,
            arrowLength,
            0xfff3c4,
            Math.max(0.32, arrowLength * 0.2),
            Math.max(0.18, arrowLength * 0.1),
          ));
        });
      }

      if (resultView === 'vectors') {
        const stride = Math.max(1, Math.ceil(fieldData.triangles.length / 180));
        const maxB = maximumFieldMagnitude(fieldData.element_fields_t);
        for (let index = 0; index < fieldData.triangles.length; index += stride) {
          const triangle = fieldData.triangles[index];
          const field = fieldData.element_fields_t[index];
          if (field.b_mag <= 1e-12) continue;
          const centroid = new THREE.Vector3(
            triangle.reduce((sum, node) => sum + fieldData.nodes_mm[node][0], 0) / 3,
            triangle.reduce((sum, node) => sum + fieldData.nodes_mm[node][1], 0) / 3,
            sheetZ + 0.55,
          );
          const direction = new THREE.Vector3(field.bx, field.by, 0).normalize();
          const length = Math.max(
            1.5,
            Math.min(config.geometry.block_width, config.geometry.magnet_height)
              * (0.2 + 0.38 * Math.min(1, field.b_mag / maxB)),
          );
          const origin = centroid.addScaledVector(direction, -length / 2);
          sheetGroup.add(new THREE.ArrowHelper(
            direction,
            origin,
            length,
            0xffffff,
            Math.max(0.35, length * 0.2),
            Math.max(0.2, length * 0.1),
          ));
        }
      }
    }

    if (showProbeOverlays) {
      const strongSign = config.array.strong_side === 'positive_y' ? 1 : -1;
      const retainedPeriods = Math.max(
        1,
        config.geometry.period_count - 2 * config.sample_region.edge_exclusion_periods,
      );
      const defaultHalfWidth = Math.max(
        config.geometry.block_width / 2,
        retainedPeriods * wavelength / 2,
      );
      const workingY = report?.working_field.line_y_mm
        ?? strongSign * (config.geometry.magnet_height / 2 + config.sample_region.probe_offset);
      const leakageY = report?.leakage_field.line_y_mm ?? -workingY;
      const workingStart = report?.working_field.x_start_mm ?? -defaultHalfWidth;
      const workingEnd = report?.working_field.x_end_mm ?? defaultHalfWidth;
      const leakageStart = report?.leakage_field.x_start_mm ?? -defaultHalfWidth;
      const leakageEnd = report?.leakage_field.x_end_mm ?? defaultHalfWidth;
      addLineSegments(
        overlayGroup,
        [workingStart, workingY, sheetZ + 0.65, workingEnd, workingY, sheetZ + 0.65],
        0x67e8f9,
      );
      addLineSegments(
        overlayGroup,
        [leakageStart, leakageY, sheetZ + 0.65, leakageEnd, leakageY, sheetZ + 0.65],
        0xf0a35b,
      );
    }

    const strongDirection = new THREE.Vector3(
      0,
      config.array.strong_side === 'positive_y' ? 1 : -1,
      0,
    );
    const strongArrowLength = Math.max(4, config.geometry.magnet_height * 0.65);
    const strongOrigin = new THREE.Vector3(
      0,
      (config.array.strong_side === 'positive_y' ? 1 : -1)
        * config.geometry.magnet_height * 0.7,
      sectioned ? 0.9 : config.geometry.out_of_plane_depth / 2 + 1,
    );
    overlayGroup.add(new THREE.ArrowHelper(
      strongDirection,
      strongOrigin,
      strongArrowLength,
      0xf59e0b,
      Math.max(1, strongArrowLength * 0.22),
      Math.max(0.6, strongArrowLength * 0.1),
    ));

    renderer.domElement.setAttribute(
      'aria-label',
      `Extruded linear Halbach ${viewportMode} view with ${magnetCount} selectable magnets. ${
        viewportMode === 'field'
          ? `${resultView} is shown from solved two-dimensional field data, repeated conceptually through depth; B z and out-of-plane end effects were not solved.`
          : viewportMode === 'mesh'
            ? 'The displayed triangles are the solved two-dimensional mesh sheet.'
            : 'Geometry is extruded through the configured out-of-plane depth.'
      }`,
    );
  }, [
    activeLength,
    config,
    fieldLineDensity,
    magnetCount,
    mesh,
    pitch,
    report,
    resultView,
    sectioned,
    selectedMagnet,
    showFieldLines,
    showHeatmap,
    showMagnetization,
    showMeshOverlay,
    showProbeOverlays,
    viewportMode,
    wavelength,
  ]);

  useEffect(() => {
    const handles = handlesRef.current;
    if (!handles) return;
    const verticalExtent = Math.max(
      config.geometry.magnet_height * 2,
      config.geometry.magnet_height / 2 + config.sample_region.probe_offset,
    );
    const radius = Math.max(
      1,
      Math.hypot(
        activeLength / 2,
        verticalExtent,
        config.geometry.out_of_plane_depth / 2,
      ),
    );
    const modelCenterY = config.geometry.out_of_plane_depth / 2;
    // The displayed model is rotated -90° about X: solve X/Y lie on the table,
    // and solve Z (out-of-plane depth) becomes the vertical display thickness.
    handles.camera.position.set(
      radius * 0.45,
      modelCenterY + radius * 1.75,
      radius * 0.9,
    );
    handles.controls.target.set(0, modelCenterY, 0);
    handles.controls.minDistance = Math.max(radius * 0.25, 1);
    handles.controls.maxDistance = radius * 10;
    handles.camera.near = Math.max(0.05, radius / 300);
    handles.camera.far = Math.max(2000, radius * 30);
    handles.camera.updateProjectionMatrix();
    handles.controls.update();
    fittedDistanceRef.current = handles.camera.position.distanceTo(handles.controls.target);
    setZoomScale(1);

    const gridSize = Math.max(activeLength * 1.4, config.geometry.out_of_plane_depth * 2.2, 20);
    handles.grid.scale.setScalar(gridSize / 100);
    handles.grid.position.y = -Math.max(0.35, gridSize * 0.004);
  }, [
    activeLength,
    config.geometry.magnet_height,
    config.geometry.out_of_plane_depth,
    config.sample_region.probe_offset,
    fitNonce,
  ]);

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
    <figure
      className={`halbach-viewport halbach-viewport-3d linear-halbach-3d-viewer${presentation === 'hero' ? ' is-hero-presentation' : ''}`}
      data-testid="linear-halbach-3d-viewer"
      data-viewport-mode={viewportMode}
      data-magnet-count={magnetCount}
      data-field-source={viewportMode === 'field' && report ? 'report-2d' : undefined}
      data-solve-dimensionality="2d"
      data-extrusion-axis="z"
      data-default-orientation="tabletop"
      data-display-rotation-x-deg="-90"
      data-field-triangle-count={report?.field_data.triangles.length ?? 0}
      data-field-node-count={report?.field_data.nodes_mm.length ?? 0}
    >
      {presentation === 'workspace' && (
        <div
          className="halbach-3d-toolbar linear-halbach-3d-toolbar"
          aria-label="Linear Halbach 3D view controls"
          data-testid="linear-halbach-3d-controls"
        >
          <label>
            <input
              type="checkbox"
              checked={sectioned}
              onChange={(event) => setSectioned(event.target.checked)}
            />
            Section at XY solve plane
          </label>
          <span className="linear-halbach-3d-inplane-note">
            Tabletop · X array · Y field normal · Z depth vertical
          </span>
        </div>
      )}
      <div
        ref={hostRef}
        className="halbach-3d-canvas linear-halbach-3d-canvas"
        data-testid="linear-halbach-3d-canvas"
      />
      {presentation === 'workspace' && <div className="linear-halbach-3d-side-label" aria-hidden="true">
        Enhanced side · {config.array.strong_side === 'positive_y' ? '+Y' : '−Y'}
      </div>}
      {presentation === 'workspace' && legend && (
        <div
          className={`halbach-field-legend linear-halbach-3d-field-legend${legend.diverging ? ' is-diverging' : ''}`}
          aria-label={`${legend.label} legend`}
        >
          <strong>{legend.label} <span>{legend.symbol}</span></strong>
          <span className="is-min">{formatLegendValue(legend.minimum)}</span>
          <i aria-hidden="true" />
          <span className="is-mid">{formatLegendValue(legend.midpoint)}</span>
          <span className="is-max">{formatLegendValue(legend.maximum)}</span>
        </div>
      )}
      {presentation === 'workspace' && showMagnetization && (!showHeatmap || viewportMode !== 'field') && (
        <div className="halbach-pole-legend" aria-label="Linear Halbach pole color legend">
          <span><i className="is-north" aria-hidden="true" />red = N face</span>
          <span><i className="is-south" aria-hidden="true" />blue = S face</span>
        </div>
      )}
      {presentation === 'workspace' && <ViewportNavigationControls
          scale={zoomScale}
          onZoomIn={() => zoomBy(1.25)}
          onZoomOut={() => zoomBy(0.8)}
          onReset={() => setFitNonce((value) => value + 1)}
          fitSubject="Linear Halbach array"
        />}
    </figure>
  );
}
