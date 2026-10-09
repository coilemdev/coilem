import { useEffect, useMemo, useRef } from 'react';

import {
  useViewportNavigation,
  ViewportNavigationControls,
} from '../ViewportNavigation';
import type {
  HalbachContourLevel,
  LinearHalbachArrayConfig,
  LinearHalbachMeshPreview,
  LinearHalbachReport,
} from './types';
import {
  HALBACH_POLE_NORTH_FALLBACK,
  HALBACH_POLE_SOUTH_FALLBACK,
} from './poleRendering';

export type LinearHalbachResultView = 'magnitude' | 'bx' | 'by' | 'az' | 'vectors';
export type LinearHalbachViewportMode = 'geometry' | 'mesh' | 'field';

interface LinearHalbach2DViewportProps {
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
}

interface LinearFieldData {
  nodes_mm: Array<[number, number]>;
  triangles: Array<[number, number, number]>;
  element_fields_t: Array<{ bx: number; by: number; b_mag: number }>;
  az_nodal_t_m: number[];
  contours?: HalbachContourLevel[];
}

interface LinearViewportBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

function expandBoundsForZoomOut(
  fitted: LinearViewportBounds,
  available: LinearViewportBounds | null,
  navigationScale: number,
): LinearViewportBounds {
  if (navigationScale >= 1) return fitted;
  const centerX = (fitted.minX + fitted.maxX) / 2;
  const centerY = (fitted.minY + fitted.maxY) / 2;
  const halfWidth = (fitted.maxX - fitted.minX) / (2 * navigationScale);
  const halfHeight = (fitted.maxY - fitted.minY) / (2 * navigationScale);
  return {
    minX: Math.max(available?.minX ?? Number.NEGATIVE_INFINITY, centerX - halfWidth),
    maxX: Math.min(available?.maxX ?? Number.POSITIVE_INFINITY, centerX + halfWidth),
    minY: Math.max(available?.minY ?? Number.NEGATIVE_INFINITY, centerY - halfHeight),
    maxY: Math.min(available?.maxY ?? Number.POSITIVE_INFINITY, centerY + halfHeight),
  };
}

const HEAT_COLORS = [
  '#142a61',
  '#1855a7',
  '#1b8eb7',
  '#2ab673',
  '#a7c83a',
  '#f1c232',
  '#f58b24',
  '#dc3d3d',
];

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
  return absolute > 0 && absolute < 0.001 ? value.toExponential(2) : value.toFixed(3);
}

function drawArrow(
  context: CanvasRenderingContext2D,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  color: string,
  width = 1.5,
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

function reportFieldData(report: LinearHalbachReport | null): LinearFieldData | null {
  if (!report) return null;
  const candidate = (report as unknown as { field_data?: LinearFieldData }).field_data;
  if (
    !candidate
    || !Array.isArray(candidate.nodes_mm)
    || !Array.isArray(candidate.triangles)
    || !Array.isArray(candidate.element_fields_t)
    || !Array.isArray(candidate.az_nodal_t_m)
  ) return null;
  return candidate;
}

function fieldValue(
  view: LinearHalbachResultView,
  field: { bx: number; by: number; b_mag: number },
  az: number,
): number {
  if (view === 'az') return az;
  if (view === 'bx') return field.bx;
  if (view === 'by') return field.by;
  return field.b_mag;
}

function magnetAngleDeg(config: LinearHalbachArrayConfig, index: number): number {
  const rotation = config.array.strong_side === 'positive_y' ? 90 : -90;
  return config.array.phase_deg + index * rotation;
}

function directionCues(contours: HalbachContourLevel[]): Array<{
  x: number;
  y: number;
  dx: number;
  dy: number;
}> {
  return contours.flatMap((level) => level.segments_mm.flatMap((segment, index) => {
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

export function LinearHalbach2DViewport({
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
}: LinearHalbach2DViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const fieldArrowCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const navigation = useViewportNavigation();
  const magnetCount = 4 * config.geometry.period_count;
  const pitch = config.geometry.block_width + config.geometry.block_gap;
  const wavelength = 4 * pitch;
  const activeLength = magnetCount * config.geometry.block_width
    + Math.max(0, magnetCount - 1) * config.geometry.block_gap;
  const workingY = (
    config.array.strong_side === 'positive_y' ? 1 : -1
  ) * (config.geometry.magnet_height / 2 + config.sample_region.probe_offset);
  const leakageY = -workingY;
  const retainedPeriods = Math.max(
    1,
    config.geometry.period_count - 2 * config.sample_region.edge_exclusion_periods,
  );
  const evaluationHalfWidth = Math.max(
    config.geometry.block_width / 2,
    retainedPeriods * wavelength / 2,
  );
  const fieldData = useMemo(() => reportFieldData(report), [report]);
  const showTwoTonePoles = showMagnetization
    && (viewportMode !== 'field' || !showHeatmap);

  const visibleBounds = useMemo(() => {
    const meshNodes = viewportMode === 'mesh' ? mesh?.nodes_mm : undefined;
    const fieldNodes = viewportMode === 'field' ? fieldData?.nodes_mm : undefined;
    const nodes = fieldNodes ?? meshNodes;
    if (nodes && nodes.length > 0) {
      const xs = nodes.map(([x]) => x);
      const ys = nodes.map(([, y]) => y);
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      const dataWidth = Math.max(1, maxX - minX);
      const dataHeight = Math.max(1, maxY - minY);
      // Avoid fitting the far boundary so tightly that the magnets become a
      // thin unreadable strip. The useful field and both probes remain visible.
      const usefulHalfWidth = Math.max(activeLength * 0.63, wavelength * 0.85);
      const usefulHalfHeight = Math.max(
        config.geometry.magnet_height * 2.4,
        Math.abs(workingY) * 1.35,
      );
      const availableBounds = { minX, maxX, minY, maxY };
      const fittedBounds = {
        minX: Math.max(minX, -Math.min(dataWidth / 2, usefulHalfWidth)),
        maxX: Math.min(maxX, Math.min(dataWidth / 2, usefulHalfWidth)),
        minY: Math.max(minY, -Math.min(dataHeight / 2, usefulHalfHeight)),
        maxY: Math.min(maxY, Math.min(dataHeight / 2, usefulHalfHeight)),
      };
      // Zooming out should reveal more of the already-solved air domain. A
      // CSS-scaled snapshot only exposes the canvas edge and makes otherwise
      // available field contours look clipped.
      return expandBoundsForZoomOut(
        fittedBounds,
        availableBounds,
        navigation.scale,
      );
    }
    const halfWidth = Math.max(activeLength * 0.63, wavelength * 0.85);
    const halfHeight = Math.max(
      config.geometry.magnet_height * 2.4,
      Math.abs(workingY) * 1.35,
    );
    return expandBoundsForZoomOut(
      { minX: -halfWidth, maxX: halfWidth, minY: -halfHeight, maxY: halfHeight },
      null,
      navigation.scale,
    );
  }, [
    activeLength,
    config.geometry.magnet_height,
    fieldData,
    mesh,
    navigation.scale,
    viewportMode,
    wavelength,
    workingY,
  ]);
  const semanticZoomOut = navigation.scale < 1;
  const navigationContentStyle = semanticZoomOut
    ? { transform: 'translate3d(0, 0, 0) scale(1)' }
    : navigation.contentStyle;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const draw = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const pixelRatio = Math.max(
        1,
        Math.min(4, (window.devicePixelRatio || 1) * Math.max(1, navigation.scale)),
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

      const dataWidth = Math.max(1, visibleBounds.maxX - visibleBounds.minX);
      const dataHeight = Math.max(1, visibleBounds.maxY - visibleBounds.minY);
      const scale = Math.min(width * 0.9 / dataWidth, height * 0.82 / dataHeight);
      const centerDataX = (visibleBounds.minX + visibleBounds.maxX) / 2;
      const centerDataY = (visibleBounds.minY + visibleBounds.maxY) / 2;
      const toCanvas = ([x, y]: [number, number]): [number, number] => [
        width / 2 + (x - centerDataX) * scale,
        height / 2 - (y - centerDataY) * scale,
      ];

      if (
        viewportMode === 'field'
        && fieldData
        && fieldData.element_fields_t.length === fieldData.triangles.length
      ) {
        const values = fieldData.triangles.map((triangle, index) => {
          const az = triangle.reduce(
            (sum, nodeIndex) => sum + (fieldData.az_nodal_t_m[nodeIndex] ?? 0),
            0,
          ) / 3;
          return fieldValue(resultView, fieldData.element_fields_t[index], az);
        });
        const absolute = resultView === 'magnitude' || resultView === 'vectors';
        const limit = Math.max(...values.map((value) => Math.abs(value)), 1e-12);
        if (showHeatmap) {
          fieldData.triangles.forEach((triangle, index) => {
            const points = triangle.map((nodeIndex) => toCanvas(fieldData.nodes_mm[nodeIndex]));
            context.beginPath();
            context.moveTo(points[0][0], points[0][1]);
            context.lineTo(points[1][0], points[1][1]);
            context.lineTo(points[2][0], points[2][1]);
            context.closePath();
            context.fillStyle = absolute
              ? palette(values[index] / limit)
              : diverging(values[index] / limit);
            context.fill();
          });
        }
        if (showMeshOverlay) {
          context.save();
          context.beginPath();
          fieldData.triangles.forEach((triangle) => {
            const points = triangle.map((nodeIndex) => toCanvas(fieldData.nodes_mm[nodeIndex]));
            context.moveTo(points[0][0], points[0][1]);
            context.lineTo(points[1][0], points[1][1]);
            context.lineTo(points[2][0], points[2][1]);
            context.closePath();
          });
          context.strokeStyle = 'rgba(203, 213, 225, .27)';
          context.lineWidth = 0.5 / Math.max(1, navigation.scale);
          context.stroke();
          context.restore();
        }
        if (showFieldLines && fieldData.contours) {
          const stride = fieldLineDensity === 'low' ? 3 : fieldLineDensity === 'medium' ? 2 : 1;
          context.save();
          context.beginPath();
          fieldData.contours.forEach((level, levelIndex) => level.segments_mm.forEach((segment) => {
            if (levelIndex % stride !== 0) return;
            if (!segment.slice(0, 4).every(Number.isFinite)) return;
            const start = toCanvas([segment[0], segment[1]]);
            const end = toCanvas([segment[2], segment[3]]);
            context.moveTo(start[0], start[1]);
            context.lineTo(end[0], end[1]);
          }));
          context.strokeStyle = '#ffd166';
          context.lineWidth = 1.35 / Math.max(1, navigation.scale);
          context.lineCap = 'round';
          context.lineJoin = 'round';
          context.shadowColor = 'rgba(255, 145, 0, .7)';
          context.shadowBlur = 2 / Math.max(1, navigation.scale);
          context.stroke();
          context.restore();
        }
        if (resultView === 'vectors') {
          const stride = Math.max(1, Math.ceil(fieldData.triangles.length / 380));
          const maxB = Math.max(...fieldData.element_fields_t.map((field) => field.b_mag), 1e-12);
          for (let index = 0; index < fieldData.triangles.length; index += stride) {
            const triangle = fieldData.triangles[index];
            const centroid: [number, number] = [
              triangle.reduce((sum, node) => sum + fieldData.nodes_mm[node][0], 0) / 3,
              triangle.reduce((sum, node) => sum + fieldData.nodes_mm[node][1], 0) / 3,
            ];
            const field = fieldData.element_fields_t[index];
            const origin = toCanvas(centroid);
            const length = 4 + 11 * Math.min(1, field.b_mag / maxB);
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

      if (viewportMode === 'mesh' && mesh) {
        context.save();
        context.beginPath();
        mesh.triangles.forEach((triangle) => {
          const points = triangle.map((nodeIndex) => toCanvas(mesh.nodes_mm[nodeIndex]));
          context.moveTo(points[0][0], points[0][1]);
          context.lineTo(points[1][0], points[1][1]);
          context.lineTo(points[2][0], points[2][1]);
          context.closePath();
        });
        context.strokeStyle = 'rgba(197, 218, 212, .38)';
        context.lineWidth = 0.5 / Math.max(1, navigation.scale);
        context.stroke();
        context.restore();
      }

      const topLeft = toCanvas([-activeLength / 2, config.geometry.magnet_height / 2]);
      const magnetPixelWidth = config.geometry.block_width * scale;
      const magnetPixelHeight = config.geometry.magnet_height * scale;
      for (let index = 0; index < magnetCount; index += 1) {
        const xMin = -activeLength / 2 + index * pitch;
        const upperLeft = toCanvas([xMin, config.geometry.magnet_height / 2]);
        const selected = selectedMagnet === index;
        const alpha = magnetAngleDeg(config, index) * Math.PI / 180;
        const center = toCanvas([
          xMin + config.geometry.block_width / 2,
          0,
        ]);
        if (selected) {
          context.fillStyle = 'rgba(245, 158, 11, .9)';
          context.fillRect(upperLeft[0], upperLeft[1], magnetPixelWidth, magnetPixelHeight);
        } else if (showTwoTonePoles) {
          const extent = Math.max(width, height) * 2;
          context.save();
          context.beginPath();
          context.rect(upperLeft[0], upperLeft[1], magnetPixelWidth, magnetPixelHeight);
          context.clip();
          context.translate(center[0], center[1]);
          context.rotate(-alpha);
          context.fillStyle = northPoleColor;
          context.fillRect(0, -extent, extent, extent * 2);
          context.fillStyle = southPoleColor;
          context.fillRect(-extent, -extent, extent, extent * 2);
          context.restore();
        } else if (viewportMode !== 'field' || !showHeatmap) {
          context.fillStyle = `hsla(216 12% ${43 + (index % 2) * 5}% / .94)`;
          context.fillRect(upperLeft[0], upperLeft[1], magnetPixelWidth, magnetPixelHeight);
        }
        context.strokeStyle = selected ? '#f59e0b' : 'rgba(229,231,235,.68)';
        context.lineWidth = (selected ? 2.5 : 1) / Math.max(1, navigation.scale);
        context.strokeRect(upperLeft[0], upperLeft[1], magnetPixelWidth, magnetPixelHeight);

        if (showMagnetization && viewportMode !== 'mesh') {
          const length = Math.max(
            9,
            Math.min(magnetPixelWidth, magnetPixelHeight) * 0.48,
          );
          drawArrow(
            context,
            center[0] - Math.cos(alpha) * length / 2,
            center[1] + Math.sin(alpha) * length / 2,
            center[0] + Math.cos(alpha) * length / 2,
            center[1] - Math.sin(alpha) * length / 2,
            '#fff',
            1.55 / Math.max(1, navigation.scale),
          );
        }
      }

      if (showMagnetization && viewportMode === 'mesh') {
        for (let index = 0; index < magnetCount; index += 1) {
          const alpha = magnetAngleDeg(config, index) * Math.PI / 180;
          const center = toCanvas([
            -activeLength / 2 + index * pitch + config.geometry.block_width / 2,
            0,
          ]);
          const length = Math.max(
            9,
            Math.min(magnetPixelWidth, magnetPixelHeight) * 0.48,
          );
          drawArrow(
            context,
            center[0] - Math.cos(alpha) * length / 2,
            center[1] + Math.sin(alpha) * length / 2,
            center[0] + Math.cos(alpha) * length / 2,
            center[1] - Math.sin(alpha) * length / 2,
            '#fff',
            1.55 / Math.max(1, navigation.scale),
          );
        }
      }

      if (showProbeOverlays) {
        const drawProbe = (y: number, color: string, label: string) => {
          const start = toCanvas([-evaluationHalfWidth, y]);
          const end = toCanvas([evaluationHalfWidth, y]);
          context.beginPath();
          context.moveTo(start[0], start[1]);
          context.lineTo(end[0], end[1]);
          context.setLineDash([7, 5]);
          context.strokeStyle = color;
          context.lineWidth = 1.6 / Math.max(1, navigation.scale);
          context.stroke();
          context.setLineDash([]);
          context.fillStyle = color;
          context.font = '700 10px ui-monospace, monospace';
          context.textAlign = 'left';
          const labelIsAbove = y > 0;
          context.textBaseline = labelIsAbove ? 'bottom' : 'top';
          context.fillText(label, start[0] + 5, start[1] + (labelIsAbove ? -8 : 8));
          context.textBaseline = 'alphabetic';
        };
        drawProbe(workingY, '#67e8f9', 'working line');
        drawProbe(leakageY, '#f0a35b', 'weak-side line');
      }

      if (viewportMode === 'geometry') {
        const strongSign = config.array.strong_side === 'positive_y' ? 1 : -1;
        const arrowOrigin = toCanvas([0, strongSign * config.geometry.magnet_height * 0.95]);
        const arrowEnd = toCanvas([0, strongSign * config.geometry.magnet_height * 1.55]);
        drawArrow(
          context,
          arrowOrigin[0],
          arrowOrigin[1],
          arrowEnd[0],
          arrowEnd[1],
          '#f59e0b',
          2,
        );
        context.fillStyle = '#fbbf24';
        context.font = '700 11px ui-monospace, monospace';
        context.textAlign = 'center';
        context.fillText(
          `enhanced side ${strongSign > 0 ? '+Y' : '−Y'}`,
          arrowEnd[0],
          arrowEnd[1] + (strongSign > 0 ? -9 : 16),
        );

        const bracketY = -config.geometry.magnet_height * 1.28;
        const bracketStart = toCanvas([-wavelength / 2, bracketY]);
        const bracketEnd = toCanvas([wavelength / 2, bracketY]);
        context.beginPath();
        context.moveTo(bracketStart[0], bracketStart[1] - 5);
        context.lineTo(bracketStart[0], bracketStart[1] + 5);
        context.moveTo(bracketStart[0], bracketStart[1]);
        context.lineTo(bracketEnd[0], bracketEnd[1]);
        context.moveTo(bracketEnd[0], bracketEnd[1] - 5);
        context.lineTo(bracketEnd[0], bracketEnd[1] + 5);
        context.strokeStyle = 'rgba(251, 191, 36, .85)';
        context.lineWidth = 1 / Math.max(1, navigation.scale);
        context.stroke();
        context.fillStyle = '#fbbf24';
        context.textAlign = 'center';
        context.fillText(`λ ${wavelength.toFixed(1)} mm`, width / 2, bracketStart[1] + 18);
      }

      // Keep the row silhouette crisp if the first block is clipped at a
      // viewport edge; this also provides a stable baseline for sparse meshes.
      context.beginPath();
      context.moveTo(topLeft[0], topLeft[1]);
      const bottomRight = toCanvas([activeLength / 2, -config.geometry.magnet_height / 2]);
      context.lineTo(bottomRight[0], topLeft[1]);
      context.strokeStyle = 'rgba(255,255,255,.18)';
      context.lineWidth = 0.6 / Math.max(1, navigation.scale);
      context.stroke();
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [
    activeLength,
    config,
    evaluationHalfWidth,
    fieldData,
    leakageY,
    magnetCount,
    mesh,
    navigation.scale,
    pitch,
    report,
    resultView,
    selectedMagnet,
    showFieldLines,
    fieldLineDensity,
    showHeatmap,
    showMagnetization,
    showMeshOverlay,
    showProbeOverlays,
    showTwoTonePoles,
    viewportMode,
    visibleBounds,
    wavelength,
    workingY,
  ]);

  useEffect(() => {
    const canvas = fieldArrowCanvasRef.current;
    if (!canvas) return;
    let animationFrame = 0;
    let lastDrawAt = Number.NEGATIVE_INFINITY;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const target = fieldLineDensity === 'low' ? 12 : fieldLineDensity === 'medium' ? 20 : 32;
    const cues = sampledDirectionCues(fieldData?.contours ?? [], target);

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
        Math.min(4, (window.devicePixelRatio || 1) * Math.max(1, navigation.scale)),
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

      const dataWidth = Math.max(1, visibleBounds.maxX - visibleBounds.minX);
      const dataHeight = Math.max(1, visibleBounds.maxY - visibleBounds.minY);
      const scale = Math.min(width * 0.9 / dataWidth, height * 0.82 / dataHeight);
      const centerDataX = (visibleBounds.minX + visibleBounds.maxX) / 2;
      const centerDataY = (visibleBounds.minY + visibleBounds.maxY) / 2;
      const toCanvas = ([x, y]: [number, number]): [number, number] => [
        width / 2 + (x - centerDataX) * scale,
        height / 2 - (y - centerDataY) * scale,
      ];
      cues.forEach((cue, index) => {
        const travel = reducedMotion
          ? 0
          : (((timestamp / 1900) + index / Math.max(1, cues.length)) % 1 - 0.5) * 18;
        const center = toCanvas([cue.x, cue.y]);
        const originX = center[0] + cue.dx * travel;
        const originY = center[1] - cue.dy * travel;
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
    fieldData,
    fieldLineDensity,
    navigation.scale,
    showFieldLines,
    viewportMode,
    visibleBounds,
  ]);

  const fieldLegend = useMemo(() => {
    if (!fieldData || viewportMode !== 'field' || !showHeatmap) return null;
    if (resultView === 'az') {
      const limit = Math.max(...fieldData.az_nodal_t_m.map((value) => Math.abs(value)), 1e-12);
      return {
        label: 'Vector potential',
        symbol: 'A_z (T m)',
        minimum: -limit,
        midpoint: 0,
        maximum: limit,
        diverging: true,
      };
    }
    if (resultView === 'bx' || resultView === 'by') {
      const key = resultView;
      const values = fieldData.element_fields_t.map((field) => field[key]);
      const limit = Math.max(...values.map((value) => Math.abs(value)), 1e-12);
      return {
        label: resultView === 'bx' ? 'Along-array field' : 'Normal field',
        symbol: resultView === 'bx' ? 'B_x (T)' : 'B_y (T)',
        minimum: -limit,
        midpoint: 0,
        maximum: limit,
        diverging: true,
      };
    }
    const maximum = Math.max(...fieldData.element_fields_t.map((field) => field.b_mag), 1e-12);
    return {
      label: 'Flux density',
      symbol: '|B| (T)',
      minimum: 0,
      midpoint: maximum / 2,
      maximum,
      diverging: false,
    };
  }, [fieldData, resultView, showHeatmap, viewportMode]);

  const handlePointer = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const width = event.currentTarget.clientWidth;
    const height = event.currentTarget.clientHeight;
    const dataWidth = Math.max(1, visibleBounds.maxX - visibleBounds.minX);
    const dataHeight = Math.max(1, visibleBounds.maxY - visibleBounds.minY);
    const scale = Math.min(width * 0.9 / dataWidth, height * 0.82 / dataHeight);
    const centerDataX = (visibleBounds.minX + visibleBounds.maxX) / 2;
    const centerDataY = (visibleBounds.minY + visibleBounds.maxY) / 2;
    const x = centerDataX + (
      (event.clientX - rect.left) * width / rect.width - width / 2
    ) / scale;
    const y = centerDataY - (
      (event.clientY - rect.top) * height / rect.height - height / 2
    ) / scale;
    if (Math.abs(y) > config.geometry.magnet_height / 2 || Math.abs(x) > activeLength / 2) {
      onSelectMagnet(null);
      return;
    }
    const index = Math.floor((x + activeLength / 2) / pitch);
    const localX = x + activeLength / 2 - index * pitch;
    if (index < 0 || index >= magnetCount || localX > config.geometry.block_width) {
      onSelectMagnet(null);
      return;
    }
    onSelectMagnet(index);
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
        style={navigationContentStyle}
      >
        <canvas
          className="halbach-field-base-canvas"
          ref={canvasRef}
          data-zoom-rendering={semanticZoomOut ? 'expanded-domain' : 'transform'}
          data-view-width-mm={(visibleBounds.maxX - visibleBounds.minX).toFixed(4)}
          data-view-height-mm={(visibleBounds.maxY - visibleBounds.minY).toFixed(4)}
          role="img"
          aria-label={`Linear Halbach array 2D ${viewportMode}; ${magnetCount} selectable magnets; enhanced field on ${
            config.array.strong_side === 'positive_y' ? 'positive Y above' : 'negative Y below'
          }${viewportMode === 'field' ? `; ${resultView} field view${
            showFieldLines ? '; animated field lines and arrows' : ''
          }` : ''}`}
          tabIndex={0}
          onClick={handlePointer}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              onSelectMagnet(null);
            } else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
              event.preventDefault();
              onSelectMagnet(((selectedMagnet ?? -1) + 1) % magnetCount);
            } else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
              event.preventDefault();
              onSelectMagnet(((selectedMagnet ?? 0) - 1 + magnetCount) % magnetCount);
            }
          }}
        />
        <canvas
          className="halbach-field-arrow-canvas"
          ref={fieldArrowCanvasRef}
          aria-hidden="true"
        />
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
        <div className="halbach-pole-legend" aria-label="Linear Halbach pole color legend">
          <span><i className="is-north" aria-hidden="true" />red = N face</span>
          <span><i className="is-south" aria-hidden="true" />blue = S face</span>
        </div>
      )}
      <ViewportNavigationControls
        scale={navigation.scale}
        onZoomIn={navigation.zoomIn}
        onZoomOut={navigation.zoomOut}
        onReset={navigation.reset}
        fitSubject="Linear Halbach array"
      />
    </figure>
  );
}
