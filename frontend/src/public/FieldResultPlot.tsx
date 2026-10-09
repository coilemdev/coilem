import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from 'react';

import { deriveMagneticPolarityCues } from '../components/tutorials/fieldPolarityCues';
import type { AirgapBrBtProfile } from '../components/tutorials/lessonSolveTypes';
import type {
  FieldLineContourLevel,
  GeometryPreview,
  PublicFieldLinePlot,
  PublicFieldVectorCue,
} from './model';
import {
  useViewportNavigation,
  ViewportNavigationControls,
} from './ViewportNavigation';
import {
  fieldRangeForViewport,
  type FieldViewportRange,
} from './fieldViewportRange';

const HEAT_COLORS = ['#142a61', '#1855a7', '#1b8eb7', '#2ab673', '#a7c83a', '#f1c232', '#f58b24', '#dc3d3d'];
const FIELD_RASTER_SIZE = 900;
const FIELD_DIRECTION_CUE_TARGET = 32;
const DETAIL_RENDER_SCALE = 1.08;
const VIEWPORT_SCALE_SETTLE_MS = 140;

export type FieldLineDensity = 'low' | 'medium' | 'high';
export type FieldColorRangeMode = 'viewport' | 'sweep';

export interface FieldProbe {
  elementIndex: number;
  region: string;
  bMagT: number;
  bxT: number | null;
  byT: number | null;
}

export interface FieldProbeDescription {
  regionLabel: string;
  materialLabel: string;
  saturationLabel: string;
  saturationTone: 'neutral' | 'good' | 'warning';
}

interface RenderedFieldLayers {
  base: HTMLCanvasElement | null;
  heat: HTMLCanvasElement;
  mesh: HTMLCanvasElement;
  lines: HTMLCanvasElement;
}

export interface FieldResultRaster {
  base: ImageBitmap;
  heat: ImageBitmap;
  mesh?: ImageBitmap | null;
  lines: ImageBitmap;
  viewBox: string;
  minB: number;
  maxB: number;
  triangleCount: number;
  contourLevelCount: number;
  contourSegmentCount: number;
  vectorCues: PublicFieldVectorCue[];
}

interface PreparedFieldPlot {
  basePath: Path2D;
  heatPaths: Path2D[];
  heatBucketCounts: number[];
  heatPathCache: Map<string, { paths: Path2D[]; counts: number[] }>;
  triangleRecords: Array<{
    index: number;
    points: [[number, number], [number, number], [number, number]];
    value: number | null;
  }>;
  contourPaths: Path2D[];
  viewBox: string;
  minB: number;
  maxB: number;
  triangleCount: number;
  contourCount: number;
  vectorCues: PublicFieldVectorCue[];
  renderedLayers: RenderedFieldLayers | null;
}

interface PreparedMagnetOverlay {
  path: string;
  center: [number, number];
  polarity: 'north' | 'south';
}

const preparedFieldPlotCache = new WeakMap<PublicFieldLinePlot, PreparedFieldPlot | null>();

function lineDensityStride(density: FieldLineDensity): number {
  if (density === 'low') return 3;
  if (density === 'medium') return 2;
  return 1;
}

function heatPathsForRange(
  records: PreparedFieldPlot['triangleRecords'],
  minB: number,
  maxB: number,
): { paths: Path2D[]; counts: number[] } {
  const paths = Array.from({ length: HEAT_COLORS.length }, () => new Path2D());
  const counts = Array.from({ length: HEAT_COLORS.length }, () => 0);
  const span = Math.max(maxB - minB, Number.EPSILON);
  records.forEach(({ points, value }) => {
    if (!Number.isFinite(value)) return;
    const bucket = Math.min(
      HEAT_COLORS.length - 1,
      Math.max(0, Math.floor((((value ?? 0) - minB) / span) * HEAT_COLORS.length)),
    );
    const [first, second, third] = points;
    paths[bucket].moveTo(first[0], -first[1]);
    paths[bucket].lineTo(second[0], -second[1]);
    paths[bucket].lineTo(third[0], -third[1]);
    paths[bucket].closePath();
    counts[bucket] += 1;
  });
  return { paths, counts };
}

function sampleDirectionCues(levels: FieldLineContourLevel[]): PublicFieldVectorCue[] {
  const candidates = levels.flatMap((level) => level.segments_mm.flatMap((segment, index) => {
    const bx = level.segment_bx_t?.[index];
    const by = level.segment_by_t?.[index];
    if (
      segment.length < 4
      || !segment.slice(0, 4).every(Number.isFinite)
      || !Number.isFinite(bx)
      || !Number.isFinite(by)
    ) return [];
    const length = Math.hypot(bx ?? 0, by ?? 0);
    if (length <= 1e-12) return [];
    const magnitude = level.segment_b_mag_t?.[index];
    return [{
      x: (segment[0] + segment[2]) / 2,
      y: (segment[1] + segment[3]) / 2,
      dx: (bx ?? 0) / length,
      dy: (by ?? 0) / length,
      ...(Number.isFinite(magnitude) ? { magnitude } : {}),
    }];
  }));
  if (candidates.length <= FIELD_DIRECTION_CUE_TARGET) return candidates;
  return Array.from({ length: FIELD_DIRECTION_CUE_TARGET }, (_, index) => (
    candidates[Math.round(index * (candidates.length - 1) / (FIELD_DIRECTION_CUE_TARGET - 1))]
  ));
}

function rotatePoint([x, y]: [number, number], angleDeg: number): [number, number] {
  if (!angleDeg) return [x, y];
  const angle = angleDeg * Math.PI / 180;
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return [x * cosine - y * sine, x * sine + y * cosine];
}

function polygonCentroid(points: Array<[number, number]>): [number, number] {
  let signedAreaTwice = 0;
  let weightedX = 0;
  let weightedY = 0;
  points.forEach((point, index) => {
    const next = points[(index + 1) % points.length];
    const cross = point[0] * next[1] - next[0] * point[1];
    signedAreaTwice += cross;
    weightedX += (point[0] + next[0]) * cross;
    weightedY += (point[1] + next[1]) * cross;
  });
  if (Math.abs(signedAreaTwice) > 1e-9) {
    return [
      weightedX / (3 * signedAreaTwice),
      weightedY / (3 * signedAreaTwice),
    ];
  }
  const center = points.reduce<[number, number]>(
    (sum, point) => [sum[0] + point[0], sum[1] + point[1]],
    [0, 0],
  );
  return [center[0] / points.length, center[1] / points.length];
}

function prepareMagnetOverlay(
  geometry: GeometryPreview | null | undefined,
  rotorAngleDeg: number,
): PreparedMagnetOverlay[] {
  if (!geometry) return [];
  return geometry.regions
    .filter((region) => /magnet/i.test(region.region_type) && region.points.length >= 3)
    .map((region, index) => {
      const points = region.points.map((point) => rotatePoint(point, -rotorAngleDeg));
      const poleMatch = region.region_type.match(/magnet[^0-9]*(\d+)/i);
      const poleIndex = poleMatch ? Number(poleMatch[1]) : index;
      const explicitlyNorth = /magnet.*(?:north|[_-]n(?:[^a-z]|$))/i.test(region.region_type);
      const explicitlySouth = /magnet.*(?:south|[_-]s(?:[^a-z]|$))/i.test(region.region_type);
      const polarity = explicitlyNorth || (!explicitlySouth && poleIndex % 2 === 0) ? 'north' : 'south';
      return {
        center: polygonCentroid(points),
        polarity,
        path: `${points.map((point, pointIndex) => `${pointIndex === 0 ? 'M' : 'L'} ${point[0]} ${-point[1]}`).join(' ')} Z`,
      };
    });
}

function prepareFieldPlot(plot: PublicFieldLinePlot): PreparedFieldPlot | null {
  const nodes = plot.nodes_mm;
  const triangles = plot.triangles;
  if (nodes.length === 0 || triangles.length === 0) return null;

  const xValues = nodes.map((node) => node[0]).filter(Number.isFinite);
  const yValues = nodes.map((node) => node[1]).filter(Number.isFinite);
  if (xValues.length === 0 || yValues.length === 0) return null;

  const minX = xValues.reduce((minimum, value) => Math.min(minimum, value), Number.POSITIVE_INFINITY);
  const maxX = xValues.reduce((maximum, value) => Math.max(maximum, value), Number.NEGATIVE_INFINITY);
  const minY = yValues.reduce((minimum, value) => Math.min(minimum, value), Number.POSITIVE_INFINITY);
  const maxY = yValues.reduce((maximum, value) => Math.max(maximum, value), Number.NEGATIVE_INFINITY);
  const width = Math.max(maxX - minX, 1);
  const height = Math.max(maxY - minY, 1);
  const padding = Math.max(width, height) * 0.025;
  const validValues: number[] = [];

  triangles.forEach((triangle, index) => {
    const points = triangle.map((nodeIndex) => nodes[nodeIndex]);
    if (points.length !== 3 || points.some((point) => !point || !Number.isFinite(point[0]) || !Number.isFinite(point[1]))) return;
    const value = plot.element_b_mag_t[index];
    if (Number.isFinite(value)) validValues.push(value);
  });

  const minB = validValues.length
    ? validValues.reduce((minimum, value) => Math.min(minimum, value), Number.POSITIVE_INFINITY)
    : 0;
  const maxB = validValues.reduce((maximum, value) => Math.max(maximum, value), 0);
  const basePath = new Path2D();
  const triangleRecords: PreparedFieldPlot['triangleRecords'] = [];
  let triangleCount = 0;
  triangles.forEach((triangle, index) => {
    const points = triangle.map((nodeIndex) => nodes[nodeIndex]);
    if (points.length !== 3 || points.some((point) => !point || !Number.isFinite(point[0]) || !Number.isFinite(point[1]))) return;
    const [first, second, third] = points as [[number, number], [number, number], [number, number]];
    basePath.moveTo(first[0], -first[1]);
    basePath.lineTo(second[0], -second[1]);
    basePath.lineTo(third[0], -third[1]);
    basePath.closePath();
    triangleCount += 1;
    const value = plot.element_b_mag_t[index];
    triangleRecords.push({
      index,
      points: [first, second, third],
      value: Number.isFinite(value) ? value : null,
    });
  });
  const { paths: heatPaths, counts: heatBucketCounts } = heatPathsForRange(
    triangleRecords,
    minB,
    maxB,
  );

  let contourCount = 0;
  const contourPaths = plot.contour_levels.map((level) => {
    const path = new Path2D();
    level.segments_mm.forEach((segment) => {
      if (segment.length < 4 || !segment.slice(0, 4).every(Number.isFinite)) return;
      path.moveTo(segment[0], -segment[1]);
      path.lineTo(segment[2], -segment[3]);
      contourCount += 1;
    });
    return path;
  });

  return {
    basePath,
    heatPaths,
    heatBucketCounts,
    heatPathCache: new Map(),
    triangleRecords,
    contourPaths,
    viewBox: `${minX - padding} ${-maxY - padding} ${width + padding * 2} ${height + padding * 2}`,
    minB,
    maxB,
    triangleCount,
    contourCount,
    vectorCues: sampleDirectionCues(plot.contour_levels),
    renderedLayers: null,
  };
}

function cachedFieldPlot(plot: PublicFieldLinePlot): PreparedFieldPlot | null {
  if (preparedFieldPlotCache.has(plot)) return preparedFieldPlotCache.get(plot) ?? null;
  const prepared = prepareFieldPlot(plot);
  preparedFieldPlotCache.set(plot, prepared);
  return prepared;
}

function renderPathLayer(
  prepared: PreparedFieldPlot,
  draw: (context: CanvasRenderingContext2D) => void,
): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = FIELD_RASTER_SIZE;
  canvas.height = FIELD_RASTER_SIZE;
  const context = canvas.getContext('2d');
  if (!context) return canvas;
  const [viewX, viewY, viewWidth, viewHeight] = prepared.viewBox.split(' ').map(Number);
  const scale = Math.min(FIELD_RASTER_SIZE / viewWidth, FIELD_RASTER_SIZE / viewHeight);
  const offsetX = (FIELD_RASTER_SIZE - viewWidth * scale) / 2;
  const offsetY = (FIELD_RASTER_SIZE - viewHeight * scale) / 2;
  context.setTransform(scale, 0, 0, scale, offsetX - viewX * scale, offsetY - viewY * scale);
  draw(context);
  return canvas;
}

function drawBase(context: CanvasRenderingContext2D, prepared: PreparedFieldPlot): void {
  context.fillStyle = '#202733';
  context.fill(prepared.basePath);
}

function drawHeat(
  context: CanvasRenderingContext2D,
  prepared: PreparedFieldPlot,
  range?: { minB: number; maxB: number },
): void {
  let paths = prepared.heatPaths;
  let counts = prepared.heatBucketCounts;
  if (range) {
    const key = `${range.minB.toFixed(6)}:${range.maxB.toFixed(6)}`;
    let cached = prepared.heatPathCache.get(key);
    if (!cached) {
      cached = heatPathsForRange(prepared.triangleRecords, range.minB, range.maxB);
      prepared.heatPathCache.set(key, cached);
    }
    paths = cached.paths;
    counts = cached.counts;
  }
  paths.forEach((path, index) => {
    if (counts[index] === 0) return;
    context.fillStyle = HEAT_COLORS[index];
    context.fill(path);
  });
}

function drawMeshEdges(
  context: CanvasRenderingContext2D,
  prepared: PreparedFieldPlot,
  viewportScale = 1,
): void {
  context.save();
  context.strokeStyle = 'rgba(203,213,225,.42)';
  context.lineWidth = 0.11 / Math.max(viewportScale, Number.EPSILON);
  context.lineJoin = 'round';
  context.stroke(prepared.basePath);
  context.restore();
}

function drawFieldLines(
  context: CanvasRenderingContext2D,
  prepared: PreparedFieldPlot,
  density: FieldLineDensity = 'high',
): void {
  context.strokeStyle = '#ffd166';
  context.lineWidth = 0.28;
  context.lineCap = 'round';
  context.shadowColor = 'rgba(255,145,0,.9)';
  context.shadowBlur = 0.45;
  const stride = lineDensityStride(density);
  prepared.contourPaths.forEach((path, index) => {
    if (index % stride !== 0) return;
    context.stroke(path);
  });
}

function warmPreparedFieldPlot(prepared: PreparedFieldPlot | null): void {
  if (!prepared || prepared.renderedLayers || typeof document === 'undefined') return;
  const heat = renderPathLayer(prepared, (context) => {
    drawBase(context, prepared);
    drawHeat(context, prepared);
  });
  const lines = renderPathLayer(prepared, (context) => {
    drawFieldLines(context, prepared);
  });
  const mesh = renderPathLayer(prepared, (context) => {
    drawMeshEdges(context, prepared);
  });
  prepared.renderedLayers = { base: null, heat, mesh, lines };
}

function baseFieldLayer(prepared: PreparedFieldPlot): HTMLCanvasElement {
  warmPreparedFieldPlot(prepared);
  if (!prepared.renderedLayers) return document.createElement('canvas');
  if (!prepared.renderedLayers.base) {
    prepared.renderedLayers.base = renderPathLayer(prepared, (context) => drawBase(context, prepared));
  }
  return prepared.renderedLayers.base;
}

export function warmFieldResultPlot(plot: PublicFieldLinePlot): void {
  warmPreparedFieldPlot(cachedFieldPlot(plot));
  if (plot.noload_plot) warmPreparedFieldPlot(cachedFieldPlot(plot.noload_plot));
}

function pointInTriangle(
  x: number,
  y: number,
  [[ax, ay], [bx, by], [cx, cy]]: [[number, number], [number, number], [number, number]],
): boolean {
  const denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
  if (Math.abs(denominator) <= Number.EPSILON) return false;
  const first = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / denominator;
  const second = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / denominator;
  const third = 1 - first - second;
  return first >= 0 && second >= 0 && third >= 0;
}

function defaultProbeDescription(probe: FieldProbe): FieldProbeDescription {
  return {
    regionLabel: probe.region.replace(/[_-]+/g, ' '),
    materialLabel: 'Solver region',
    saturationLabel: 'Not assessed',
    saturationTone: 'neutral',
  };
}

export function FieldResultPlot({
  plot,
  raster,
  highResolutionPlot,
  showHeatmap: controlledShowHeatmap,
  showMesh: controlledShowMesh,
  showFieldLines: controlledShowFieldLines,
  fieldLineDensity = 'medium',
  colorRangeMode = 'viewport',
  sweepScaleMaxT,
  showRangeControl = false,
  onColorRangeModeChange,
  showMagnets = false,
  showAirgap = false,
  airgapInnerRadiusMm,
  showMagnetPolarityLabels = true,
  magnetReference = false,
  showStatorPolarity = false,
  showPolarityLegend = false,
  statorPolarityProfile,
  statorPolarityRotationDeg = 0,
  statorInnerRadiusMm,
  poles = 2,
  geometry,
  magnetRotationDeg = 0,
  showControls = true,
  title = 'Flux-density field map',
  subtitle = 'Completed Magneto2D solution',
  showHeading = true,
  probeEnabled = true,
  describeProbe = defaultProbeDescription,
  onViewportScaleSettled,
}: {
  plot?: PublicFieldLinePlot | null;
  raster?: FieldResultRaster | null;
  highResolutionPlot?: PublicFieldLinePlot | null;
  showHeatmap?: boolean;
  showMesh?: boolean;
  showFieldLines?: boolean;
  fieldLineDensity?: FieldLineDensity;
  colorRangeMode?: FieldColorRangeMode;
  sweepScaleMaxT?: number | null;
  showRangeControl?: boolean;
  onColorRangeModeChange?: (mode: FieldColorRangeMode) => void;
  showMagnets?: boolean;
  showAirgap?: boolean;
  airgapInnerRadiusMm?: number;
  showMagnetPolarityLabels?: boolean;
  magnetReference?: boolean;
  showStatorPolarity?: boolean;
  showPolarityLegend?: boolean;
  statorPolarityProfile?: AirgapBrBtProfile | null;
  statorPolarityRotationDeg?: number;
  statorInnerRadiusMm?: number;
  poles?: number;
  geometry?: GeometryPreview | null;
  magnetRotationDeg?: number;
  showControls?: boolean;
  title?: string;
  subtitle?: string;
  showHeading?: boolean;
  probeEnabled?: boolean;
  describeProbe?: (probe: FieldProbe) => FieldProbeDescription;
  onViewportScaleSettled?: (scale: number) => void;
}) {
  const navigation = useViewportNavigation();
  const sourcePlot = highResolutionPlot ?? plot;
  const prepared = useMemo(() => {
    if (!sourcePlot) return null;
    const value = cachedFieldPlot(sourcePlot);
    if (!raster) warmPreparedFieldPlot(value);
    return value;
  }, [sourcePlot, raster]);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const magnetOverlay = useMemo(
    () => prepareMagnetOverlay(geometry, magnetRotationDeg),
    [geometry, magnetRotationDeg],
  );
  const statorPolarityCues = useMemo(
    () => showStatorPolarity
      ? deriveMagneticPolarityCues(statorPolarityProfile, poles, 'stator')
      : [],
    [poles, showStatorPolarity, statorPolarityProfile],
  );
  const [internalShowHeatmap, setInternalShowHeatmap] = useState(true);
  const [internalShowMesh, setInternalShowMesh] = useState(false);
  const [internalShowFieldLines, setInternalShowFieldLines] = useState(true);
  const [probe, setProbe] = useState<FieldProbe | null>(null);
  const [viewportRange, setViewportRange] = useState<FieldViewportRange | null>(null);
  const viewportRangeRef = useRef<FieldViewportRange | null>(null);
  const showHeatmap = controlledShowHeatmap ?? internalShowHeatmap;
  const showMesh = controlledShowMesh ?? internalShowMesh;
  const showFieldLines = controlledShowFieldLines ?? internalShowFieldLines;
  const sweepRange = useMemo(
    () => colorRangeMode === 'sweep' && Number.isFinite(sweepScaleMaxT)
      ? { minB: 0, maxB: Math.max(Number.EPSILON, sweepScaleMaxT ?? 0) }
      : null,
    [colorRangeMode, sweepScaleMaxT],
  );

  useEffect(() => {
    if (!probeEnabled || !sourcePlot) setProbe(null);
  }, [probeEnabled, sourcePlot]);

  useEffect(() => {
    if (!onViewportScaleSettled) return undefined;
    const timeout = window.setTimeout(
      () => onViewportScaleSettled(navigation.scale),
      VIEWPORT_SCALE_SETTLE_MS,
    );
    return () => window.clearTimeout(timeout);
  }, [navigation.scale, onViewportScaleSettled]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const layers = raster ?? prepared?.renderedLayers;
    if (!canvas || !layers) return undefined;
    const publishViewportRange = (nextRange: FieldViewportRange | null) => {
      const currentRange = viewportRangeRef.current;
      const unchanged = currentRange === nextRange
        || (
          currentRange !== null
          && nextRange !== null
          && currentRange.elementCount === nextRange.elementCount
          && Math.abs(currentRange.minB - nextRange.minB) < 1e-9
          && Math.abs(currentRange.maxB - nextRange.maxB) < 1e-9
        );
      if (unchanged) return;
      viewportRangeRef.current = nextRange;
      setViewportRange(nextRange);
    };
    const draw = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
      const pixelWidth = Math.max(1, Math.round(width * pixelRatio));
      const pixelHeight = Math.max(1, Math.round(height * pixelRatio));
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth;
        canvas.height = pixelHeight;
      }
      const context = canvas.getContext('2d');
      if (!context) return;
      context.clearRect(0, 0, pixelWidth, pixelHeight);
      const size = Math.min(pixelWidth, pixelHeight);
      const panX = navigation.pan.x * pixelRatio;
      const panY = navigation.pan.y * pixelRatio;
      const useVectorDetail = Boolean(
        prepared
        && (
          navigation.scale >= DETAIL_RENDER_SCALE
          || (sweepRange && highResolutionPlot)
        )
        && (!raster || highResolutionPlot),
      );
      if (useVectorDetail && prepared) {
        canvas.dataset.renderMode = 'vector-detail';
        canvas.dataset.sourceResolution = 'solver-vector';
        const [viewX, viewY, viewWidth, viewHeight] = prepared.viewBox.split(' ').map(Number);
        const baseScale = Math.min(size / viewWidth, size / viewHeight);
        const baseOffsetX = (pixelWidth - viewWidth * baseScale) / 2;
        const baseOffsetY = (pixelHeight - viewHeight * baseScale) / 2;
        const centerX = pixelWidth / 2;
        const centerY = pixelHeight / 2;
        const scale = baseScale * navigation.scale;
        const translateX = centerX
          + (baseOffsetX - viewX * baseScale - centerX) * navigation.scale
          + panX;
        const translateY = centerY
          + (baseOffsetY - viewY * baseScale - centerY) * navigation.scale
          + panY;
        const visibleRange = colorRangeMode === 'viewport'
          ? fieldRangeForViewport(prepared.triangleRecords, {
            scale,
            translateX,
            translateY,
            canvasWidth: pixelWidth,
            canvasHeight: pixelHeight,
          })
          : null;
        publishViewportRange(visibleRange);
        context.save();
        context.setTransform(
          scale,
          0,
          0,
          scale,
          translateX,
          translateY,
        );
        drawBase(context, prepared);
        if (showHeatmap) drawHeat(context, prepared, sweepRange ?? visibleRange ?? undefined);
        if (showMesh) drawMeshEdges(context, prepared, navigation.scale);
        if (showFieldLines) drawFieldLines(context, prepared, fieldLineDensity);
        context.restore();
        return;
      }

      publishViewportRange(null);
      const drawSize = size * navigation.scale;
      const x = (pixelWidth - drawSize) / 2 + panX;
      const y = (pixelHeight - drawSize) / 2 + panY;
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = 'high';
      if (raster) {
        canvas.dataset.renderMode = raster.base.width > FIELD_RASTER_SIZE
          ? 'detail-raster'
          : 'playback-raster';
        canvas.dataset.sourceResolution = `${raster.base.width}x${raster.base.height}`;
        context.drawImage(raster.base, x, y, drawSize, drawSize);
        if (showHeatmap) context.drawImage(raster.heat, x, y, drawSize, drawSize);
      } else if (prepared && layers) {
        canvas.dataset.renderMode = 'prepared-raster';
        canvas.dataset.sourceResolution = `${layers.heat.width}x${layers.heat.height}`;
        context.drawImage(showHeatmap ? layers.heat : baseFieldLayer(prepared), x, y, drawSize, drawSize);
      }
      if (showMesh) {
        if (raster?.mesh) {
          context.drawImage(raster.mesh, x, y, drawSize, drawSize);
        } else if (prepared && highResolutionPlot) {
          const [viewX, viewY, viewWidth, viewHeight] = prepared.viewBox.split(' ').map(Number);
          const baseScale = Math.min(size / viewWidth, size / viewHeight);
          const baseOffsetX = (pixelWidth - viewWidth * baseScale) / 2;
          const baseOffsetY = (pixelHeight - viewHeight * baseScale) / 2;
          const centerX = pixelWidth / 2;
          const centerY = pixelHeight / 2;
          context.save();
          context.setTransform(
            baseScale * navigation.scale,
            0,
            0,
            baseScale * navigation.scale,
            centerX + (baseOffsetX - viewX * baseScale - centerX) * navigation.scale + panX,
            centerY + (baseOffsetY - viewY * baseScale - centerY) * navigation.scale + panY,
          );
          drawMeshEdges(context, prepared, navigation.scale);
          context.restore();
        } else if (prepared?.renderedLayers?.mesh) {
          context.drawImage(prepared.renderedLayers.mesh, x, y, drawSize, drawSize);
        }
      }
      if (showFieldLines) {
        if (prepared && highResolutionPlot) {
          const [viewX, viewY, viewWidth, viewHeight] = prepared.viewBox.split(' ').map(Number);
          const baseScale = Math.min(size / viewWidth, size / viewHeight);
          const baseOffsetX = (pixelWidth - viewWidth * baseScale) / 2;
          const baseOffsetY = (pixelHeight - viewHeight * baseScale) / 2;
          const centerX = pixelWidth / 2;
          const centerY = pixelHeight / 2;
          context.save();
          context.setTransform(
            baseScale * navigation.scale,
            0,
            0,
            baseScale * navigation.scale,
            centerX + (baseOffsetX - viewX * baseScale - centerX) * navigation.scale + panX,
            centerY + (baseOffsetY - viewY * baseScale - centerY) * navigation.scale + panY,
          );
          drawFieldLines(context, prepared, fieldLineDensity);
          context.restore();
        } else {
          context.save();
          // Playback rasters are authored with the medium contour stride. Do
          // not imply low/high density by changing only the image opacity.
          context.globalAlpha = 0.68;
          context.drawImage(layers.lines, x, y, drawSize, drawSize);
          context.restore();
        }
      }
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [
    colorRangeMode,
    highResolutionPlot,
    fieldLineDensity,
    sweepRange,
    navigation.pan.x,
    navigation.pan.y,
    navigation.scale,
    prepared,
    raster,
    showFieldLines,
    showHeatmap,
    showMesh,
  ]);

  if (!prepared && !raster) return null;
  const hasHeatmap = raster ? true : prepared?.heatBucketCounts.some((count) => count > 0) ?? false;
  const hasMesh = Boolean(raster?.mesh || (prepared?.triangleCount ?? 0) > 0);
  const hasFieldLines = raster ? raster.contourSegmentCount > 0 : (prepared?.contourCount ?? 0) > 0;
  const viewBox = raster?.viewBox ?? prepared?.viewBox ?? '0 0 1 1';
  const minB = raster?.minB ?? prepared?.minB ?? 0;
  const maxB = raster?.maxB ?? prepared?.maxB ?? 0;
  const activeViewportRange = colorRangeMode === 'viewport' ? viewportRange : null;
  const displayMinB = sweepRange?.minB ?? activeViewportRange?.minB ?? minB;
  const displayMaxB = sweepRange?.maxB ?? activeViewportRange?.maxB ?? maxB;
  const triangleCount = raster?.triangleCount ?? prepared?.triangleCount ?? 0;
  const contourLevelCount = raster?.contourLevelCount ?? plot?.contour_levels.length ?? 0;
  const availableDirectionCues = raster?.vectorCues ?? prepared?.vectorCues ?? [];
  const directionCueTarget = fieldLineDensity === 'low' ? 12 : fieldLineDensity === 'medium' ? 20 : 32;
  const directionCues = availableDirectionCues.length <= directionCueTarget
    ? availableDirectionCues
    : Array.from({ length: directionCueTarget }, (_, index) => (
      availableDirectionCues[
        Math.round(index * (availableDirectionCues.length - 1) / (directionCueTarget - 1))
      ]
    ));
  const viewBoxValues = viewBox.split(/\s+/).map(Number);
  const [viewX, viewY, viewWidth, viewHeight] = viewBoxValues;
  const hasValidOverlayViewBox = viewBoxValues.length === 4
    && viewBoxValues.every(Number.isFinite)
    && viewWidth > 0
    && viewHeight > 0;
  const overlayScale = hasValidOverlayViewBox
    ? Math.min(FIELD_RASTER_SIZE / viewWidth, FIELD_RASTER_SIZE / viewHeight)
    : 1;
  const overlayOffsetX = hasValidOverlayViewBox
    ? (FIELD_RASTER_SIZE - viewWidth * overlayScale) / 2 - viewX * overlayScale
    : 0;
  const overlayOffsetY = hasValidOverlayViewBox
    ? (FIELD_RASTER_SIZE - viewHeight * overlayScale) / 2 - viewY * overlayScale
    : 0;
  const overlayTransform = [
    overlayScale,
    0,
    0,
    overlayScale,
    overlayOffsetX,
    overlayOffsetY,
  ].join(' ');
  const arrowSize = viewBoxValues.length === 4 && viewBoxValues.every(Number.isFinite)
    ? Math.max(0.8, Math.min(Math.abs(viewBoxValues[2]), Math.abs(viewBoxValues[3])) * 0.014)
    : 1;
  const arrowPath = `M ${-arrowSize * 0.58} 0 L ${arrowSize * 0.35} 0 M ${arrowSize * 0.05} ${-arrowSize * 0.3} L ${arrowSize * 0.52} 0 L ${arrowSize * 0.05} ${arrowSize * 0.3}`;
  const hasDirectionCues = showFieldLines && directionCues.length > 0;
  const statorPoleLabelRadius = Number.isFinite(statorInnerRadiusMm)
    ? (statorInnerRadiusMm ?? 0) + Math.max(3.2, Math.min(5, (statorInnerRadiusMm ?? 0) * 0.075))
    : null;
  const hasStatorPolarityCues = statorPoleLabelRadius !== null && statorPolarityCues.length > 0;
  const hasAirgapOverlay = showAirgap
    && Number.isFinite(airgapInnerRadiusMm)
    && Number.isFinite(statorInnerRadiusMm)
    && (airgapInnerRadiusMm ?? 0) > 0
    && (statorInnerRadiusMm ?? 0) > (airgapInnerRadiusMm ?? 0);
  const visibleLayerLabel = [
    showHeatmap && hasHeatmap ? 'flux-density heatmap' : null,
    showMesh && hasMesh ? 'solver mesh edges' : null,
    showFieldLines && hasFieldLines ? 'magnetic field lines' : null,
    hasDirectionCues ? 'field-direction arrows' : null,
    showMagnets && magnetOverlay.length > 0
      ? magnetReference ? 'dimmed permanent-magnet reference geometry' : 'permanent magnets'
      : null,
    hasAirgapOverlay ? 'airgap boundary contour' : null,
    hasStatorPolarityCues ? 'current-induced stator pole labels' : null,
  ].filter(Boolean).join(' and ') || 'magnetic field geometry';
  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    navigation.bind.onPointerMove(event);
    if (
      navigation.isDragging
      || event.buttons !== 0
      || !probeEnabled
      || !prepared
      || !sourcePlot
      || !hasValidOverlayViewBox
    ) {
      setProbe(null);
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const size = Math.min(rect.width, rect.height);
    const drawSize = size * navigation.scale;
    const drawX = (rect.width - drawSize) / 2 + navigation.pan.x;
    const drawY = (rect.height - drawSize) / 2 + navigation.pan.y;
    const rasterX = ((event.clientX - rect.left - drawX) / drawSize) * FIELD_RASTER_SIZE;
    const rasterY = ((event.clientY - rect.top - drawY) / drawSize) * FIELD_RASTER_SIZE;
    if (
      rasterX < 0
      || rasterY < 0
      || rasterX > FIELD_RASTER_SIZE
      || rasterY > FIELD_RASTER_SIZE
    ) {
      setProbe(null);
      return;
    }
    const worldX = (rasterX - overlayOffsetX) / overlayScale;
    const worldY = -(rasterY - overlayOffsetY) / overlayScale;
    const record = prepared.triangleRecords.find(({ points }) => (
      pointInTriangle(worldX, worldY, points)
    ));
    if (!record || !Number.isFinite(record.value)) {
      setProbe(null);
      return;
    }
    const bxT = sourcePlot.element_bx_t?.[record.index];
    const byT = sourcePlot.element_by_t?.[record.index];
    setProbe({
      elementIndex: record.index,
      region: sourcePlot.regions[record.index] ?? 'unclassified',
      bMagT: record.value ?? 0,
      bxT: Number.isFinite(bxT) ? bxT ?? null : null,
      byT: Number.isFinite(byT) ? byT ?? null : null,
    });
  };
  const probeDescription = probe ? describeProbe(probe) : null;

  return (
    <section className="public-field-result" aria-label="Solved magnetic field map">
      {showHeading && <div className="public-field-result-heading">
        <div>
          <strong>{title}</strong>
          <span>{subtitle}</span>
          {showPolarityLegend && showMagnets && hasStatorPolarityCues && (
            <div className="public-field-pole-legend" aria-label="Magnetic pole label legend">
              <span><i className="is-pm" aria-hidden="true" />Letter inside magnet · inactive PM</span>
              <span><i className="is-stator" aria-hidden="true">Nₛ</i>Color badge · stator pole</span>
            </div>
          )}
        </div>
        {showControls && <div className="public-field-result-controls" aria-label="Field map layers">
          {hasHeatmap && <button type="button" aria-pressed={showHeatmap} onClick={() => setInternalShowHeatmap((value) => !value)}>Heatmap</button>}
          {hasMesh && <button type="button" aria-pressed={showMesh} onClick={() => setInternalShowMesh((value) => !value)}>Mesh</button>}
          {hasFieldLines && <button type="button" aria-pressed={showFieldLines} onClick={() => setInternalShowFieldLines((value) => !value)}>Field lines</button>}
        </div>}
      </div>}
      <div
        className={`public-field-result-canvas public-viewport-navigation${navigation.panEnabled ? ' is-pannable' : ''}${navigation.isDragging ? ' is-dragging' : ''}`}
        ref={navigation.viewportRef}
        title="Use the mouse wheel to zoom; drag to pan when zoomed"
        {...navigation.bind}
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setProbe(null)}
      >
        <canvas ref={canvasRef} role="img" aria-label={`Solved ${visibleLayerLabel}`} />
        <div className="public-viewport-navigation-content public-field-overlay-navigation" style={navigation.contentStyle}>
          {(hasDirectionCues || (showMagnets && magnetOverlay.length > 0) || hasAirgapOverlay || hasStatorPolarityCues) && <svg viewBox={`0 0 ${FIELD_RASTER_SIZE} ${FIELD_RASTER_SIZE}`} className="public-field-result-overlay" aria-hidden="true">
            <g className="public-field-result-overlay-world" transform={`matrix(${overlayTransform})`}>
              {hasAirgapOverlay && (
                <g className="public-field-result-airgap-overlay">
                  <circle cx="0" cy="0" r={airgapInnerRadiusMm} />
                  <circle cx="0" cy="0" r={statorInnerRadiusMm} />
                </g>
              )}
              {hasDirectionCues && directionCues.map((cue, index) => {
                const screenAngleDeg = Math.atan2(-cue.dy, cue.dx) * 180 / Math.PI;
                const style = {
                  '--public-field-arrow-delay': `${-(index % 12) * 0.14}s`,
                } as CSSProperties;
                return (
                  <g
                    transform={`translate(${cue.x} ${-cue.y}) rotate(${screenAngleDeg})`}
                    className="public-field-direction-cue"
                    key={`field-direction-${index}`}
                  >
                    <path d={arrowPath} style={style} />
                  </g>
                );
              })}
              {showMagnets && (
                <g className={`public-field-result-pm-overlay${magnetReference ? ' is-reference' : ''}`}>
                  {magnetOverlay.map((magnet, index) => <path d={magnet.path} className={`public-field-result-magnet is-${magnet.polarity}`} key={`magnet-${index}`} />)}
                  {showMagnetPolarityLabels && magnetOverlay.map((magnet, index) => <text x={magnet.center[0]} y={-magnet.center[1]} className="public-field-result-magnet-label" key={`magnet-label-${index}`}>{magnet.polarity === 'north' ? 'N' : 'S'}</text>)}
                </g>
              )}
              {hasStatorPolarityCues && statorPolarityCues.map((cue, index) => {
                const angleRad = (cue.angleDeg + statorPolarityRotationDeg) * Math.PI / 180;
                const x = statorPoleLabelRadius * Math.cos(angleRad);
                const y = -statorPoleLabelRadius * Math.sin(angleRad);
                return (
                  <g className={`public-field-result-stator-pole is-${cue.label === 'N' ? 'north' : 'south'}`} key={`stator-pole-${index}`}>
                    <rect x={x - 2.2} y={y - 1.45} width="4.4" height="2.9" rx="1.1" />
                    <text x={x} y={y}>{cue.label}ₛ</text>
                  </g>
                );
              })}
            </g>
          </svg>}
        </div>
        <ViewportNavigationControls
          scale={navigation.scale}
          onZoomIn={navigation.zoomIn}
          onZoomOut={navigation.zoomOut}
          onReset={navigation.reset}
        />
        {probe && probeDescription && (
          <div className={`public-field-probe is-${probeDescription.saturationTone}`} role="status">
            <header>
              <span>{probeDescription.regionLabel}</span>
              <small>Element {probe.elementIndex + 1}</small>
            </header>
            <strong>{probe.bMagT.toFixed(3)} T <em>|B|</em></strong>
            <dl>
              <div><dt>Bx</dt><dd>{probe.bxT === null ? '—' : `${probe.bxT.toFixed(3)} T`}</dd></div>
              <div><dt>By</dt><dd>{probe.byT === null ? '—' : `${probe.byT.toFixed(3)} T`}</dd></div>
              <div><dt>Material</dt><dd>{probeDescription.materialLabel}</dd></div>
            </dl>
            <p>{probeDescription.saturationLabel}</p>
          </div>
        )}
      </div>
      <div className="public-field-result-legend">
        <strong>Flux density <span>|B| (T)</span></strong>
        <span className="is-min">{displayMinB.toFixed(3)}</span>
        <i aria-hidden="true" />
        <span className="is-mid">{((displayMinB + displayMaxB) / 2).toFixed(3)}</span>
        <span className="is-max">{displayMaxB.toFixed(3)}</span>
        {showRangeControl && onColorRangeModeChange && (
          <div className="public-field-range-control" role="group" aria-label="Flux-density color range">
            <button
              type="button"
              aria-pressed={colorRangeMode === 'viewport'}
              aria-label="View range: rescale colors to the visible zoomed viewport"
              title="Visible zoomed viewport · updates after zoom or pan"
              onClick={() => onColorRangeModeChange('viewport')}
            >
              View
            </button>
            <button
              type="button"
              aria-pressed={colorRangeMode === 'sweep'}
              aria-label="Sweep range: keep one color scale across every solved rotor position"
              title={`All solved rotor positions · 0–${(sweepScaleMaxT ?? maxB).toFixed(3)} T`}
              onClick={() => onColorRangeModeChange('sweep')}
            >
              Sweep
            </button>
          </div>
        )}
        <small>{triangleCount.toLocaleString()} solved elements · {contourLevelCount} contour levels</small>
      </div>
    </section>
  );
}
