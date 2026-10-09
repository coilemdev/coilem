import { useEffect, useMemo, useRef } from 'react';

import {
  useViewportNavigation,
  ViewportNavigationControls,
} from '../ViewportNavigation';
import type {
  HalbachArrayConfig,
  HalbachContourLevel,
  HalbachMeshPreview,
  HalbachReport,
  HalbachResultView,
  HalbachViewportMode,
} from './types';
import { halbachDisplaySegments } from './geometry';
import {
  HALBACH_POLE_NORTH_FALLBACK,
  HALBACH_POLE_SOUTH_FALLBACK,
  halbachWedgeCentroid,
} from './poleRendering';

interface Halbach2DViewportProps {
  config: HalbachArrayConfig;
  mesh: HalbachMeshPreview | null;
  report: HalbachReport | null;
  resultView: HalbachResultView;
  viewportMode: HalbachViewportMode;
  selectedSegment: number | null;
  onSelectSegment: (index: number | null) => void;
  showHeatmap?: boolean;
  showMeshOverlay?: boolean;
  showFieldLines?: boolean;
  fieldLineDensity?: 'low' | 'medium' | 'high';
  showMagnetization?: boolean;
  showSamplingOverlays?: boolean;
}

const HEAT_COLORS = ['#142a61', '#1855a7', '#1b8eb7', '#2ab673', '#a7c83a', '#f1c232', '#f58b24', '#dc3d3d'];

function palette(value: number): string {
  const clamped = Math.max(0, Math.min(1, value));
  const scaled = clamped * (HEAT_COLORS.length - 1);
  const lower = Math.floor(scaled);
  const upper = Math.min(HEAT_COLORS.length - 1, lower + 1);
  const mix = scaled - lower;
  const parse = (color: string) => [
    Number.parseInt(color.slice(1, 3), 16),
    Number.parseInt(color.slice(3, 5), 16),
    Number.parseInt(color.slice(5, 7), 16),
  ];
  const first = parse(HEAT_COLORS[lower]);
  const second = parse(HEAT_COLORS[upper]);
  const channel = (index: number) => Math.round(first[index] + (second[index] - first[index]) * mix);
  return `rgb(${channel(0)} ${channel(1)} ${channel(2)})`;
}

function diverging(value: number): string {
  const clamped = Math.max(-1, Math.min(1, value));
  if (clamped >= 0) return `hsl(${42 - clamped * 35} 85% ${45 + clamped * 8}%)`;
  return `hsl(${205 + (-clamped) * 25} 78% ${48 + (-clamped) * 5}%)`;
}

function formatLegendValue(value: number): string {
  const absolute = Math.abs(value);
  if (absolute > 0 && absolute < 0.001) return value.toExponential(2);
  return value.toFixed(3);
}

function drawArrow(
  context: CanvasRenderingContext2D,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  color: string,
  width = 2,
): void {
  const angle = Math.atan2(y1 - y0, x1 - x0);
  const head = Math.max(5, width * 3.5);
  context.beginPath();
  context.moveTo(x0, y0);
  context.lineTo(x1, y1);
  context.strokeStyle = color;
  context.lineWidth = width;
  context.stroke();
  context.beginPath();
  context.moveTo(x1, y1);
  context.lineTo(x1 - head * Math.cos(angle - Math.PI / 6), y1 - head * Math.sin(angle - Math.PI / 6));
  context.lineTo(x1 - head * Math.cos(angle + Math.PI / 6), y1 - head * Math.sin(angle + Math.PI / 6));
  context.closePath();
  context.fillStyle = color;
  context.fill();
}

function pathAnnularWedge(
  context: CanvasRenderingContext2D,
  centerX: number,
  centerY: number,
  scale: number,
  innerRadius: number,
  outerRadius: number,
  startDeg: number,
  endDeg: number,
): void {
  const start = -startDeg * Math.PI / 180;
  const end = -endDeg * Math.PI / 180;
  context.beginPath();
  context.arc(centerX, centerY, outerRadius * scale, start, end, true);
  context.arc(centerX, centerY, innerRadius * scale, end, start, false);
  context.closePath();
}

function fieldValue(
  view: HalbachResultView,
  field: { bx: number; by: number; b_mag: number },
  az: number,
  targetRad: number,
): number {
  if (view === 'az') return az;
  if (view === 'parallel') return field.bx * Math.cos(targetRad) + field.by * Math.sin(targetRad);
  if (view === 'perpendicular') return -field.bx * Math.sin(targetRad) + field.by * Math.cos(targetRad);
  return field.b_mag;
}

function directionCues(contours: HalbachContourLevel[]): Array<{
  x: number;
  y: number;
  dx: number;
  dy: number;
}> {
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
  return candidates;
}

function sampledDirectionCues(
  contours: HalbachContourLevel[],
  target: number,
): ReturnType<typeof directionCues> {
  const candidates = directionCues(contours);
  if (candidates.length <= target) return candidates;
  return Array.from({ length: target }, (_, index) => (
    candidates[Math.round(index * (candidates.length - 1) / Math.max(1, target - 1))]
  ));
}

export function Halbach2DViewport({
  config,
  mesh,
  report,
  resultView,
  viewportMode,
  selectedSegment,
  onSelectSegment,
  showHeatmap = true,
  showMeshOverlay = false,
  showFieldLines = true,
  fieldLineDensity = 'medium',
  showMagnetization = true,
  showSamplingOverlays = true,
}: Halbach2DViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const fieldLineCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const fieldArrowCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const navigation = useViewportNavigation();
  const maximumRadius = useMemo(() => (
    // A solved field includes the far Dirichlet boundary. Keep that numerical
    // domain off-canvas in both mesh and result views so the useful
    // magnet/bore/leakage region fills the viewport, matching the motor view.
    Math.max(
      config.geometry.outer_radius * 1.25,
      config.sample_region.leakage_probe_radius * 1.08,
    )
  ), [config]);
  const showTwoTonePoles = showMagnetization
    && (viewportMode !== 'field' || !showHeatmap);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const draw = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      // Re-rasterize at the displayed size and active zoom. The previous
      // fixed 720 px source was visibly soft on large/high-DPI workspaces.
      const pixelRatio = Math.max(
        1,
        Math.min(4, (window.devicePixelRatio || 1) * navigation.scale),
      );
      const pixelWidth = Math.max(1, Math.round(width * pixelRatio));
      const pixelHeight = Math.max(1, Math.round(height * pixelRatio));
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth;
        canvas.height = pixelHeight;
      }
      const context = canvas.getContext('2d');
      if (!context) return;
      const canvasStyle = window.getComputedStyle(canvas);
      const northPoleColor = canvasStyle.getPropertyValue('--halbach-pole-north').trim()
        || HALBACH_POLE_NORTH_FALLBACK;
      const southPoleColor = canvasStyle.getPropertyValue('--halbach-pole-south').trim()
        || HALBACH_POLE_SOUTH_FALLBACK;
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      context.clearRect(0, 0, width, height);
      context.fillStyle = '#101014';
      context.fillRect(0, 0, width, height);

      const centerX = width / 2;
      const centerY = height / 2;
      const scale = (Math.min(width, height) * 0.44) / maximumRadius;
      const toCanvas = ([x, y]: [number, number]): [number, number] => [
        centerX + x * scale,
        centerY - y * scale,
      ];

      const fieldData = viewportMode === 'field' ? report?.field_data : undefined;
      if (fieldData && fieldData.element_fields_t.length === fieldData.triangles.length) {
        const target = config.array.field_direction * Math.PI / 180;
        const values = fieldData.triangles.map((triangle, index) => {
          const az = triangle.reduce(
            (sum, nodeIndex) => sum + (fieldData.az_nodal_t_m[nodeIndex] ?? 0),
            0,
          ) / 3;
          return fieldValue(resultView, fieldData.element_fields_t[index], az, target);
        });
        const nodeSums = Array.from({ length: fieldData.nodes_mm.length }, () => 0);
        const nodeCounts = Array.from({ length: fieldData.nodes_mm.length }, () => 0);
        fieldData.triangles.forEach((triangle, index) => {
          triangle.forEach((nodeIndex) => {
            nodeSums[nodeIndex] += values[index] ?? 0;
            nodeCounts[nodeIndex] += 1;
          });
        });
        const smoothedValues = fieldData.triangles.map((triangle, index) => (
          triangle.reduce(
            (sum, nodeIndex) => sum + (
              nodeCounts[nodeIndex] > 0
                ? nodeSums[nodeIndex] / nodeCounts[nodeIndex]
                : values[index]
            ),
            0,
          ) / 3
        ));
        const absolute = resultView === 'magnitude' || resultView === 'vectors';
        const limit = Math.max(...values.map((value) => Math.abs(value)), 1e-12);
        if (showHeatmap) {
          for (let index = 0; index < fieldData.triangles.length; index += 1) {
            const points = fieldData.triangles[index].map(
              (nodeIndex) => toCanvas(fieldData.nodes_mm[nodeIndex]),
            );
            context.beginPath();
            context.moveTo(points[0][0], points[0][1]);
            context.lineTo(points[1][0], points[1][1]);
            context.lineTo(points[2][0], points[2][1]);
            context.closePath();
            context.fillStyle = absolute
              ? palette(smoothedValues[index] / limit)
              : diverging(smoothedValues[index] / limit);
            context.fill();
          }
        }

        if (showMeshOverlay) {
          context.save();
          context.beginPath();
          for (const triangle of fieldData.triangles) {
            const points = triangle.map((nodeIndex) => toCanvas(fieldData.nodes_mm[nodeIndex]));
            context.moveTo(points[0][0], points[0][1]);
            context.lineTo(points[1][0], points[1][1]);
            context.lineTo(points[2][0], points[2][1]);
            context.closePath();
          }
          context.strokeStyle = 'rgba(203, 213, 225, .28)';
          context.lineWidth = 0.5 / Math.max(1, navigation.scale);
          context.stroke();
          context.restore();
        }

        if (resultView === 'vectors') {
          const strideVectors = Math.max(1, Math.ceil(fieldData.triangles.length / 420));
          const maxB = Math.max(
            ...fieldData.element_fields_t.map((field) => field.b_mag),
            1e-12,
          );
          for (let index = 0; index < fieldData.triangles.length; index += strideVectors) {
            const triangle = fieldData.triangles[index];
            const centroid: [number, number] = [
              triangle.reduce((sum, node) => sum + fieldData.nodes_mm[node][0], 0) / 3,
              triangle.reduce((sum, node) => sum + fieldData.nodes_mm[node][1], 0) / 3,
            ];
            const field = fieldData.element_fields_t[index];
            const origin = toCanvas(centroid);
            const length = 4 + 12 * Math.min(1, field.b_mag / maxB);
            const angle = Math.atan2(-field.by, field.bx);
            drawArrow(
              context,
              origin[0] - Math.cos(angle) * length / 2,
              origin[1] - Math.sin(angle) * length / 2,
              origin[0] + Math.cos(angle) * length / 2,
              origin[1] + Math.sin(angle) * length / 2,
              'rgba(255,255,255,.9)',
              1 / Math.max(1, navigation.scale),
            );
          }
        }
      }

      const { inner_radius: inner, outer_radius: outer } = config.geometry;
      for (const segment of halbachDisplaySegments(config)) {
        const { index, centerDeg: theta } = segment;
        const selected = selectedSegment === index;
        if (selected) {
          pathAnnularWedge(
            context,
            centerX,
            centerY,
            scale,
            inner,
            outer,
            segment.startDeg,
            segment.endDeg,
          );
          context.fillStyle = `hsla(38 92% 54% / ${viewportMode === 'field' ? 0.58 : 0.96})`;
          context.fill();
        } else if (showTwoTonePoles) {
          const [centroidX, centroidY] = halbachWedgeCentroid(
            inner,
            outer,
            segment.startDeg,
            segment.endDeg,
          );
          const alpha = segment.magnetizationDeg * Math.PI / 180;
          const extent = Math.max(width, height) * 2;
          context.save();
          pathAnnularWedge(
            context,
            centerX,
            centerY,
            scale,
            inner,
            outer,
            segment.startDeg,
            segment.endDeg,
          );
          context.clip();
          context.translate(
            centerX + centroidX * scale,
            centerY - centroidY * scale,
          );
          context.rotate(-alpha);
          context.fillStyle = northPoleColor;
          context.fillRect(0, -extent, extent, extent * 2);
          context.fillStyle = southPoleColor;
          context.fillRect(-extent, -extent, extent, extent * 2);
          context.restore();
        } else if (viewportMode !== 'field' || !showHeatmap) {
          pathAnnularWedge(
            context,
            centerX,
            centerY,
            scale,
            inner,
            outer,
            segment.startDeg,
            segment.endDeg,
          );
          const segmentLightness = 43 + (index % 2) * 5;
          context.fillStyle = `hsla(216 12% ${segmentLightness}% / ${
            viewportMode === 'mesh' ? 0.78 : 0.96
          })`;
          context.fill();
        }
        pathAnnularWedge(
          context,
          centerX,
          centerY,
          scale,
          inner,
          outer,
          segment.startDeg,
          segment.endDeg,
        );
        context.lineWidth = (selectedSegment === index ? 3 : 1) / Math.max(1, navigation.scale);
        context.strokeStyle = selectedSegment === index
          ? '#f59e0b'
          : viewportMode === 'field'
            ? 'rgba(229,231,235,.48)'
            : 'rgba(229,231,235,.62)';
        context.stroke();

        if (showMagnetization && viewportMode !== 'mesh') {
          const alpha = segment.magnetizationDeg * Math.PI / 180;
          const thetaRad = theta * Math.PI / 180;
          const radius = 0.5 * (inner + outer) * scale;
          const originX = centerX + radius * Math.cos(thetaRad);
          const originY = centerY - radius * Math.sin(thetaRad);
          const length = Math.max(10, (outer - inner) * scale * 0.32);
          drawArrow(
            context,
            originX - Math.cos(alpha) * length / 2,
            originY + Math.sin(alpha) * length / 2,
            originX + Math.cos(alpha) * length / 2,
            originY - Math.sin(alpha) * length / 2,
            '#ffffff',
            1.6 / Math.max(1, navigation.scale),
          );
        }
      }

      if (viewportMode === 'mesh' && mesh) {
        // Draw every visible element into one connected path. Sampling whole
        // triangles made fine meshes look like disconnected fragments even
        // though the underlying Gmsh topology was valid.
        context.save();
        context.beginPath();
        for (const triangle of mesh.triangles) {
          const points = triangle.map((nodeIndex) => toCanvas(mesh.nodes_mm[nodeIndex]));
          const xValues = points.map(([x]) => x);
          const yValues = points.map(([, y]) => y);
          if (
            Math.max(...xValues) < -2
            || Math.min(...xValues) > width + 2
            || Math.max(...yValues) < -2
            || Math.min(...yValues) > height + 2
          ) continue;
          context.moveTo(points[0][0], points[0][1]);
          context.lineTo(points[1][0], points[1][1]);
          context.lineTo(points[2][0], points[2][1]);
          context.closePath();
        }
        context.strokeStyle = 'rgba(197, 218, 212, .36)';
        context.lineWidth = 0.5 / Math.max(1, navigation.scale);
        context.stroke();
        context.restore();
      }

      if (showMagnetization && viewportMode === 'mesh') {
        for (const segment of halbachDisplaySegments(config)) {
          const alpha = segment.magnetizationDeg * Math.PI / 180;
          const thetaRad = segment.centerDeg * Math.PI / 180;
          const radius = 0.5 * (inner + outer) * scale;
          const originX = centerX + radius * Math.cos(thetaRad);
          const originY = centerY - radius * Math.sin(thetaRad);
          const length = Math.max(10, (outer - inner) * scale * 0.32);
          drawArrow(
            context,
            originX - Math.cos(alpha) * length / 2,
            originY + Math.sin(alpha) * length / 2,
            originX + Math.cos(alpha) * length / 2,
            originY - Math.sin(alpha) * length / 2,
            '#ffffff',
            1.6 / Math.max(1, navigation.scale),
          );
        }
      }

      const drawCircle = (radius: number, color: string, dash: number[]) => {
        context.beginPath();
        context.arc(centerX, centerY, radius * scale, 0, Math.PI * 2);
        context.setLineDash(dash);
        context.strokeStyle = color;
        context.lineWidth = 1.6 / Math.max(1, navigation.scale);
        context.stroke();
        context.setLineDash([]);
      };
      if (showSamplingOverlays) {
        drawCircle(config.sample_region.radius, '#67e8f9', [6, 4]);
        drawCircle(config.sample_region.leakage_probe_radius, '#f0a35b', [3, 5]);
      }

    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [
    config,
    maximumRadius,
    mesh,
    navigation.scale,
    report,
    resultView,
    selectedSegment,
    showHeatmap,
    showMagnetization,
    showMeshOverlay,
    showSamplingOverlays,
    showTwoTonePoles,
    viewportMode,
  ]);

  useEffect(() => {
    const canvas = fieldLineCanvasRef.current;
    if (!canvas) return;
    const draw = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const pixelRatio = Math.max(
        1,
        Math.min(4, (window.devicePixelRatio || 1) * navigation.scale),
      );
      const pixelWidth = Math.max(1, Math.round(width * pixelRatio));
      const pixelHeight = Math.max(1, Math.round(height * pixelRatio));
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth;
        canvas.height = pixelHeight;
      }
      const context = canvas.getContext('2d');
      if (!context) return;
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      context.clearRect(0, 0, width, height);
      if (viewportMode !== 'field' || !showFieldLines || !report?.field_data.contours) return;

      const centerX = width / 2;
      const centerY = height / 2;
      const scale = (Math.min(width, height) * 0.44) / maximumRadius;
      const stride = fieldLineDensity === 'low' ? 3 : fieldLineDensity === 'medium' ? 2 : 1;
      context.save();
      context.beginPath();
      report.field_data.contours.forEach((level, levelIndex) => {
        if (levelIndex % stride !== 0) return;
        for (const segment of level.segments_mm) {
          if (segment.length < 4 || !segment.slice(0, 4).every(Number.isFinite)) continue;
          context.moveTo(centerX + segment[0] * scale, centerY - segment[1] * scale);
          context.lineTo(centerX + segment[2] * scale, centerY - segment[3] * scale);
        }
      });
      context.strokeStyle = '#ffd166';
      context.lineWidth = 1.45 / Math.max(1, navigation.scale);
      context.lineCap = 'round';
      context.lineJoin = 'round';
      context.shadowColor = 'rgba(255, 145, 0, .85)';
      context.shadowBlur = 2.1 / Math.max(1, navigation.scale);
      context.stroke();
      context.restore();
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [
    fieldLineDensity,
    maximumRadius,
    navigation.scale,
    report,
    showFieldLines,
    viewportMode,
  ]);

  useEffect(() => {
    const canvas = fieldArrowCanvasRef.current;
    if (!canvas) return;
    let animationFrame = 0;
    let lastDrawAt = Number.NEGATIVE_INFINITY;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const target = fieldLineDensity === 'low' ? 12 : fieldLineDensity === 'medium' ? 20 : 32;
    const cues = sampledDirectionCues(report?.field_data.contours ?? [], target);

    const draw = (timestamp: number) => {
      if (!reducedMotion && timestamp - lastDrawAt < 1000 / 30) {
        animationFrame = window.requestAnimationFrame(draw);
        return;
      }
      lastDrawAt = timestamp;
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const pixelRatio = Math.max(
        1,
        Math.min(4, (window.devicePixelRatio || 1) * navigation.scale),
      );
      const pixelWidth = Math.max(1, Math.round(width * pixelRatio));
      const pixelHeight = Math.max(1, Math.round(height * pixelRatio));
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth;
        canvas.height = pixelHeight;
      }
      const context = canvas.getContext('2d');
      if (!context) return;
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      context.clearRect(0, 0, width, height);
      if (viewportMode !== 'field' || !showFieldLines || cues.length === 0) {
        canvas.dataset.animationState = 'disabled';
        return;
      }
      const centerX = width / 2;
      const centerY = height / 2;
      const scale = (Math.min(width, height) * 0.44) / maximumRadius;
      cues.forEach((cue, index) => {
        const travel = reducedMotion
          ? 0
          : (((timestamp / 1900) + index / Math.max(1, cues.length)) % 1 - 0.5) * 18;
        const originX = centerX + cue.x * scale + cue.dx * travel;
        const originY = centerY - cue.y * scale - cue.dy * travel;
        const halfLength = 5.8 / Math.max(1, navigation.scale);
        drawArrow(
          context,
          originX - cue.dx * halfLength,
          originY + cue.dy * halfLength,
          originX + cue.dx * halfLength,
          originY - cue.dy * halfLength,
          '#fff3c4',
          1.2 / Math.max(1, navigation.scale),
        );
      });
      canvas.dataset.animationState = reducedMotion ? 'reduced-motion' : 'running';
      if (!reducedMotion) animationFrame = window.requestAnimationFrame(draw);
    };

    animationFrame = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [
    fieldLineDensity,
    maximumRadius,
    navigation.scale,
    report,
    showFieldLines,
    viewportMode,
  ]);

  const fieldLegend = useMemo(() => {
    const fieldData = viewportMode === 'field' ? report?.field_data : undefined;
    if (!fieldData || !showHeatmap) return null;
    if (resultView === 'az') {
      const limit = Math.max(
        ...fieldData.az_nodal_t_m.map((value) => Math.abs(value)),
        1e-12,
      );
      return {
        label: 'Vector potential',
        symbol: 'A_z (T m)',
        minimum: -limit,
        midpoint: 0,
        maximum: limit,
        diverging: true,
      };
    }
    if (resultView === 'parallel' || resultView === 'perpendicular') {
      const target = config.array.field_direction * Math.PI / 180;
      const values = fieldData.element_fields_t.map((field) => (
        resultView === 'parallel'
          ? field.bx * Math.cos(target) + field.by * Math.sin(target)
          : -field.bx * Math.sin(target) + field.by * Math.cos(target)
      ));
      const limit = Math.max(...values.map((value) => Math.abs(value)), 1e-12);
      return {
        label: resultView === 'parallel' ? 'Parallel field' : 'Perpendicular field',
        symbol: 'B (T)',
        minimum: -limit,
        midpoint: 0,
        maximum: limit,
        diverging: true,
      };
    }
    const values = fieldData.element_fields_t.map((field) => field.b_mag);
    const maximum = Math.max(...values, 1e-12);
    return {
      label: 'Flux density',
      symbol: '|B| (T)',
      minimum: 0,
      midpoint: maximum / 2,
      maximum,
      diverging: false,
    };
  }, [config.array.field_direction, report, resultView, showHeatmap, viewportMode]);

  const requestedFieldDirectionDeg = (
    (config.array.field_direction % 360) + 360
  ) % 360;
  const requestedFieldScreenRotationDeg = -requestedFieldDirectionDeg;
  let requestedLabelRotationDeg = (
    (requestedFieldScreenRotationDeg + 180) % 360 + 360
  ) % 360 - 180;
  if (requestedLabelRotationDeg > 90) requestedLabelRotationDeg -= 180;
  if (requestedLabelRotationDeg < -90) requestedLabelRotationDeg += 180;
  const requestedArrowLength = Math.max(
    8.5,
    Math.min(14, 25 * config.sample_region.radius / maximumRadius),
  );
  const requestedDirectionRad = requestedFieldDirectionDeg * Math.PI / 180;
  const requestedLabelX = 50 + Math.cos(requestedDirectionRad) * requestedArrowLength * 0.52;
  const requestedLabelY = 50 - Math.sin(requestedDirectionRad) * requestedArrowLength * 0.52;

  const handlePointer = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const width = event.currentTarget.clientWidth;
    const height = event.currentTarget.clientHeight;
    const x = (event.clientX - rect.left) * width / rect.width - width / 2;
    const y = height / 2 - (event.clientY - rect.top) * height / rect.height;
    const scale = (Math.min(width, height) * 0.44) / maximumRadius;
    const radius = Math.hypot(x, y) / scale;
    if (radius < config.geometry.inner_radius || radius > config.geometry.outer_radius) {
      onSelectSegment(null);
      return;
    }
    const angle = ((Math.atan2(y, x) * 180 / Math.PI - config.geometry.segment_start_angle) % 360 + 360) % 360;
    const pitch = 360 / config.geometry.segment_count;
    onSelectSegment(Math.min(config.geometry.segment_count - 1, Math.floor(angle / pitch)));
  };

  return (
    <figure
      className={`halbach-viewport halbach-viewport-2d public-viewport-navigation${navigation.panEnabled ? ' is-pannable' : ''}${navigation.isDragging ? ' is-dragging' : ''}`}
      ref={navigation.viewportRef}
      title="Use the mouse wheel to zoom; drag to pan when zoomed"
      {...navigation.bind}
    >
      <div
        className="public-viewport-navigation-content halbach-viewport-navigation-content"
        style={navigation.contentStyle}
      >
        <canvas
          className="halbach-field-base-canvas"
          ref={canvasRef}
          role="img"
          aria-label={`Halbach array 2D ${
            viewportMode === 'field'
              ? `${resultView}${showHeatmap ? ' heatmap' : ''}${
                showMeshOverlay ? ', mesh overlay' : ''
              }${showFieldLines ? ', animated field lines and arrows' : ''}`
              : viewportMode === 'mesh'
                ? 'mesh overlay'
                : 'geometry'
          }; ${config.geometry.segment_count} selectable magnet segments`}
          tabIndex={0}
          onClick={handlePointer}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              onSelectSegment(null);
            } else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
              event.preventDefault();
              onSelectSegment(((selectedSegment ?? -1) + 1) % config.geometry.segment_count);
            } else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
              event.preventDefault();
              onSelectSegment(
                ((selectedSegment ?? 0) - 1 + config.geometry.segment_count)
                  % config.geometry.segment_count,
              );
            }
          }}
        />
        <canvas
          className="halbach-field-line-canvas"
          ref={fieldLineCanvasRef}
          aria-hidden="true"
        />
        <canvas
          className="halbach-field-arrow-canvas"
          ref={fieldArrowCanvasRef}
          aria-hidden="true"
        />
        <svg
          className="halbach-requested-field-overlay"
          viewBox="0 0 100 100"
          preserveAspectRatio="xMidYMid meet"
          aria-hidden="true"
        >
          <g
            className="halbach-requested-field-arrow"
            transform={`rotate(${requestedFieldScreenRotationDeg} 50 50)`}
          >
            <path
              className="is-glow"
              d={`M 50 50 H ${50 + requestedArrowLength}`}
            />
            <path
              className="is-core"
              d={`M 50 50 H ${50 + requestedArrowLength - 0.35}`}
            />
            <path
              className="is-head"
              d={`M ${50 + requestedArrowLength} 50 L ${
                50 + requestedArrowLength - 2.15
              } 48.65 L ${
                50 + requestedArrowLength - 2.15
              } 51.35 Z`}
            />
          </g>
        </svg>
        <span
          className="halbach-requested-field-label"
          aria-hidden="true"
          style={{
            left: `${requestedLabelX}%`,
            top: `${requestedLabelY}%`,
            transform: `translate(-50%, -50%) rotate(${requestedLabelRotationDeg}deg) translateY(-13px)`,
          }}
        >
          requested B
        </span>
      </div>
      {fieldLegend && (
        <div
          className={`halbach-field-legend${fieldLegend.diverging ? ' is-diverging' : ''}`}
          aria-label={`${fieldLegend.label} legend`}
        >
          <strong>{fieldLegend.label} <span>{fieldLegend.symbol}</span></strong>
          <span className="is-min">{formatLegendValue(fieldLegend.minimum)}</span>
          <i aria-hidden="true" />
          <span className="is-mid">{formatLegendValue(fieldLegend.midpoint)}</span>
          <span className="is-max">{formatLegendValue(fieldLegend.maximum)}</span>
        </div>
      )}
      {showTwoTonePoles && (
        <div className="halbach-pole-legend" aria-label="Halbach pole color legend">
          <span><i className="is-north" aria-hidden="true" />red = N face</span>
          <span><i className="is-south" aria-hidden="true" />blue = S face</span>
        </div>
      )}
      <ViewportNavigationControls
        scale={navigation.scale}
        onZoomIn={navigation.zoomIn}
        onZoomOut={navigation.zoomOut}
        onReset={navigation.reset}
        fitSubject="Halbach array"
      />
    </figure>
  );
}
