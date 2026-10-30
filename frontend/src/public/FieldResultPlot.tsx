import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { createPortal } from 'react-dom';

import {
  airgapHarmonic,
  deriveMagneticPolarityCues,
  strongestAirgapPolePairs,
} from '../components/tutorials/fieldPolarityCues';
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
import { currentAngleNote, fieldAxisArrowPaths, leadAngleExplanation, qAxisOffsetDeg, rotorNorthAxisDeg, statorLeadElecDeg } from './fieldAxes';
import { motorFitWidthBesideLegend } from './fieldLegendFit';
import {
  fieldRangeForViewport,
  type FieldViewportRange,
} from './fieldViewportRange';
import {
  FIXED_FLUX_SCALE,
  FLUX_OVER_RANGE_INDEX,
  fittedFluxScale,
  fluxColor,
  fluxColorIndex,
  type FluxColorScale,
  type SaturationTick,
} from './fluxColorScale';
const FIELD_RASTER_SIZE = 900;
const FIELD_DIRECTION_CUE_TARGET = 32;
const DETAIL_RENDER_SCALE = 1.08;
const VIEWPORT_SCALE_SETTLE_MS = 140;
// The second field of the Stator + PM view (#120) is drawn in cyan with a dark
// halo, apart from the orange stator lines and the red and blue magnets.
const OVERLAY_LINE_COLOR = '#5ed3f3';
const OVERLAY_HALO_COLOR = 'rgba(3,10,20,.92)';
const OVERLAY_LINE_ALPHA = 0.85;

export type FieldLineDensity = 'low' | 'medium' | 'high';
/** Fixed: one 0–2.0 T scale everywhere. Viewport ("Fit view"): fitted to the zoomed area, never past 2.0 T. */
export type FieldColorRangeMode = 'fixed' | 'viewport';

export interface FieldProbe {
  elementIndex: number;
  region: string;
  bMagT: number;
  bxT: number | null;
  byT: number | null;
  /** The element's distance from the axis (its centroid), in mm. */
  radiusMm?: number | null;
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
  /** The scale the image was drawn with; null for images drawn before the fixed scale (their minB–maxB). */
  colorScale?: FluxColorScale | null;
  triangleCount: number;
  contourLevelCount: number;
  contourSegmentCount: number;
  vectorCues: PublicFieldVectorCue[];
}

/** Draw each field's working-harmonic axes; playback turns in this direction. */
export interface FieldAxesOptions {
  rotation: 'clockwise' | 'counterclockwise';
  /** The run's current angle γ, for the "90° + γ" note; null when the excitation has none (six-step). */
  currentAngleDeg?: number | null;
}

/** A second field drawn as lines over the first, as in the Stator + PM view (#120). */
export interface FieldLineOverlay {
  /** Playback raster of the second field; only its lines layer and direction cues are drawn. */
  raster: FieldResultRaster | null;
  /** Exact solver frame of the second field, drawn as vector lines when available. */
  plot: PublicFieldLinePlot | null;
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

// Close each triangle with an explicit edge back to its first vertex, never
// closePath(). Chromium's Path2D closePath() costs time proportional to the
// path built so far, so a 33k-triangle solver mesh took ~1.6 s to prepare on
// every new rotor position. The explicit edge fills and strokes identically.
function addTrianglePath(
  path: Path2D,
  [first, second, third]: [[number, number], [number, number], [number, number]],
): void {
  path.moveTo(first[0], -first[1]);
  path.lineTo(second[0], -second[1]);
  path.lineTo(third[0], -third[1]);
  path.lineTo(first[0], -first[1]);
}

function heatPathsForScale(
  records: PreparedFieldPlot['triangleRecords'],
  scale: FluxColorScale,
): { paths: Path2D[]; counts: number[] } {
  const paths = Array.from({ length: FLUX_OVER_RANGE_INDEX + 1 }, () => new Path2D());
  const counts = Array.from({ length: FLUX_OVER_RANGE_INDEX + 1 }, () => 0);
  records.forEach(({ points, value }) => {
    if (!Number.isFinite(value)) return;
    const bucket = fluxColorIndex(value ?? 0, scale);
    addTrianglePath(paths[bucket], points);
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
    const trianglePoints = points as [[number, number], [number, number], [number, number]];
    addTrianglePath(basePath, trianglePoints);
    triangleCount += 1;
    const value = plot.element_b_mag_t[index];
    triangleRecords.push({
      index,
      points: trianglePoints,
      value: Number.isFinite(value) ? value : null,
    });
  });
  const { paths: heatPaths, counts: heatBucketCounts } = heatPathsForScale(
    triangleRecords,
    FIXED_FLUX_SCALE,
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
  scale: FluxColorScale = FIXED_FLUX_SCALE,
): void {
  let paths = prepared.heatPaths;
  let counts = prepared.heatBucketCounts;
  if (!scale.fixed) {
    const key = `${scale.minB.toFixed(6)}:${scale.maxB.toFixed(6)}`;
    let cached = prepared.heatPathCache.get(key);
    if (!cached) {
      cached = heatPathsForScale(prepared.triangleRecords, scale);
      prepared.heatPathCache.set(key, cached);
    }
    paths = cached.paths;
    counts = cached.counts;
  }
  paths.forEach((path, index) => {
    if (counts[index] === 0) return;
    context.fillStyle = fluxColor(index);
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
  overlay = false,
): void {
  context.strokeStyle = overlay ? OVERLAY_LINE_COLOR : '#ffd166';
  context.lineWidth = 0.28;
  context.lineCap = 'round';
  context.shadowColor = overlay ? OVERLAY_HALO_COLOR : 'rgba(255,145,0,.9)';
  context.shadowBlur = overlay ? 2 : 0.45;
  const stride = lineDensityStride(density);
  prepared.contourPaths.forEach((path, index) => {
    if (index % stride !== 0) return;
    context.stroke(path);
  });
}

/** The square of SVG-space coordinates that a square raster with this view box covers. */
function rasterWorldSquare(viewBox: string): { left: number; top: number; size: number } | null {
  const [x, y, width, height] = viewBox.split(/\s+/).map(Number);
  if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null;
  const size = Math.max(width, height);
  return { left: x - (size - width) / 2, top: y - (size - height) / 2, size };
}

const overlayLineLayers = new WeakMap<ImageBitmap | HTMLCanvasElement, HTMLCanvasElement>();

/** A field-line raster recoloured to the overlay colour, with its dark halo, made once per raster. */
function overlayLineLayer(lines: ImageBitmap | HTMLCanvasElement): HTMLCanvasElement {
  const cached = overlayLineLayers.get(lines);
  if (cached) return cached;
  const tint = document.createElement('canvas');
  const layer = document.createElement('canvas');
  tint.width = layer.width = lines.width;
  tint.height = layer.height = lines.height;
  const tintContext = tint.getContext('2d');
  const context = layer.getContext('2d');
  if (tintContext && context) {
    tintContext.drawImage(lines, 0, 0);
    // Keep each pixel's coverage; replace its colour.
    tintContext.globalCompositeOperation = 'source-in';
    tintContext.fillStyle = OVERLAY_LINE_COLOR;
    tintContext.fillRect(0, 0, tint.width, tint.height);
    context.shadowColor = OVERLAY_HALO_COLOR;
    context.shadowBlur = Math.max(2, lines.width / 450);
    context.drawImage(tint, 0, 0);
  }
  overlayLineLayers.set(lines, layer);
  return layer;
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
  colorRangeMode = 'fixed',
  saturationTicks = [],
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
  overlay = null,
  fieldAxes = null,
  pmLines = false,
  navigationSlot = null,
}: {
  plot?: PublicFieldLinePlot | null;
  raster?: FieldResultRaster | null;
  highResolutionPlot?: PublicFieldLinePlot | null;
  showHeatmap?: boolean;
  showMesh?: boolean;
  showFieldLines?: boolean;
  fieldLineDensity?: FieldLineDensity;
  colorRangeMode?: FieldColorRangeMode;
  /** The stator steel's knee and saturation, marked on the fixed scale. */
  saturationTicks?: SaturationTick[];
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
  overlay?: FieldLineOverlay | null;
  /** Draw the field's own lines and arrows in the PM colour (the PM-only view). */
  pmLines?: boolean;
  fieldAxes?: FieldAxesOptions | null;
  /** Render the zoom controls here instead of over the plot (the solved-field viewer's control dock). */
  navigationSlot?: HTMLElement | null;
}) {
  const navigation = useViewportNavigation();
  const sourcePlot = highResolutionPlot ?? plot;
  const prepared = useMemo(() => {
    if (!sourcePlot) return null;
    const value = cachedFieldPlot(sourcePlot);
    if (!raster) warmPreparedFieldPlot(value);
    return value;
  }, [sourcePlot, raster]);
  const overlayPrepared = useMemo(
    () => (overlay?.plot ? cachedFieldPlot(overlay.plot) : null),
    [overlay?.plot],
  );
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
  const axisPolePairs = Math.max(1, Math.round(poles / 2));
  const statorAxisDeg = useMemo(() => {
    if (!fieldAxes) return null;
    const harmonic = airgapHarmonic(statorPolarityProfile, axisPolePairs);
    return harmonic ? harmonic.peakDeg + statorPolarityRotationDeg : null;
  }, [axisPolePairs, fieldAxes, statorPolarityProfile, statorPolarityRotationDeg]);
  const rotorAxisDeg = useMemo(
    () => (fieldAxes ? rotorNorthAxisDeg(magnetOverlay, axisPolePairs) : null),
    [axisPolePairs, fieldAxes, magnetOverlay],
  );
  const statorStrongestPolePairs = useMemo(
    () => (fieldAxes ? strongestAirgapPolePairs(statorPolarityProfile, axisPolePairs * 4) : null),
    [axisPolePairs, fieldAxes, statorPolarityProfile],
  );
  const leadElecDeg = fieldAxes && statorAxisDeg !== null && rotorAxisDeg !== null
    ? statorLeadElecDeg(statorAxisDeg, rotorAxisDeg, axisPolePairs, fieldAxes.rotation)
    : null;
  const [internalShowHeatmap, setInternalShowHeatmap] = useState(true);
  const [internalShowMesh, setInternalShowMesh] = useState(false);
  const [internalShowFieldLines, setInternalShowFieldLines] = useState(true);
  const [probe, setProbe] = useState<FieldProbe | null>(null);
  const [viewportRange, setViewportRange] = useState<FieldViewportRange | null>(null);
  const viewportRangeRef = useRef<FieldViewportRange | null>(null);
  // Whether the canvas shows exact vectors (drawn here, on the chosen scale) or a
  // playback image (drawn on the scale it carries); the legend follows it.
  const [vectorDetailShown, setVectorDetailShown] = useState(false);
  const vectorDetailShownRef = useRef(false);
  const showHeatmap = controlledShowHeatmap ?? internalShowHeatmap;
  const showMesh = controlledShowMesh ?? internalShowMesh;
  const showFieldLines = controlledShowFieldLines ?? internalShowFieldLines;

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
    const publishVectorDetail = (shown: boolean) => {
      if (vectorDetailShownRef.current === shown) return;
      vectorDetailShownRef.current = shown;
      setVectorDetailShown(shown);
    };
    // Call with the canvas transform mapping SVG-space world coordinates. Exact
    // overlay vectors go with exact primary vectors; otherwise its playback raster.
    const drawOverlayLines = (context: CanvasRenderingContext2D, vectorPrimary: boolean) => {
      if (!showFieldLines || !overlay) return;
      const overlayRaster = overlay.raster;
      if (overlayPrepared && (vectorPrimary || !overlayRaster)) {
        context.save();
        drawFieldLines(context, overlayPrepared, fieldLineDensity, true);
        context.restore();
        return;
      }
      const square = overlayRaster ? rasterWorldSquare(overlayRaster.viewBox) : null;
      if (!overlayRaster || !square) return;
      context.save();
      context.globalAlpha = OVERLAY_LINE_ALPHA;
      context.drawImage(overlayLineLayer(overlayRaster.lines), square.left, square.top, square.size, square.size);
      context.restore();
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
          // Fit view needs the exact values to fit, even before zooming.
          || (colorRangeMode === 'viewport' && highResolutionPlot)
        )
        && (!raster || highResolutionPlot),
      );
      publishVectorDetail(useVectorDetail);
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
        if (showHeatmap) drawHeat(context, prepared, visibleRange ? fittedFluxScale(visibleRange.minB, visibleRange.maxB) : FIXED_FLUX_SCALE);
        if (showMesh) drawMeshEdges(context, prepared, navigation.scale);
        if (showFieldLines) drawFieldLines(context, prepared, fieldLineDensity, pmLines);
        drawOverlayLines(context, true);
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
          drawFieldLines(context, prepared, fieldLineDensity, pmLines);
          context.restore();
        } else {
          context.save();
          // Playback rasters are authored with the medium contour stride. Do
          // not imply low/high density by changing only the image opacity.
          // PM-only lines take the PM colour, as in the Stator + PM view.
          if (pmLines) {
            context.globalAlpha = OVERLAY_LINE_ALPHA;
            context.drawImage(overlayLineLayer(layers.lines), x, y, drawSize, drawSize);
          } else {
            context.globalAlpha = 0.68;
            context.drawImage(layers.lines, x, y, drawSize, drawSize);
          }
          context.restore();
        }
        const primarySquare = rasterWorldSquare(raster?.viewBox ?? prepared?.viewBox ?? '');
        if (overlay && primarySquare) {
          const worldScale = drawSize / primarySquare.size;
          context.save();
          context.setTransform(
            worldScale,
            0,
            0,
            worldScale,
            x - primarySquare.left * worldScale,
            y - primarySquare.top * worldScale,
          );
          drawOverlayLines(context, Boolean(prepared && highResolutionPlot));
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
    navigation.pan.x,
    navigation.pan.y,
    navigation.scale,
    overlay,
    overlayPrepared,
    pmLines,
    prepared,
    raster,
    showFieldLines,
    showHeatmap,
    showMesh,
  ]);

  const hasHeatmap = raster ? true : prepared?.heatBucketCounts.some((count) => count > 0) ?? false;
  const hasMesh = Boolean(raster?.mesh || (prepared?.triangleCount ?? 0) > 0);
  const hasFieldLines = raster ? raster.contourSegmentCount > 0 : (prepared?.contourCount ?? 0) > 0;
  const viewBox = raster?.viewBox ?? prepared?.viewBox ?? '0 0 1 1';
  const minB = raster?.minB ?? prepared?.minB ?? 0;
  const maxB = raster?.maxB ?? prepared?.maxB ?? 0;
  // The legend describes what is on screen: exact vectors on the fixed or fitted
  // scale, or a playback image on the scale it was drawn with. Images from before
  // the fixed scale carry none and spanned their own minimum to maximum.
  const legendScale: FluxColorScale = vectorDetailShown || !raster
    ? (colorRangeMode === 'viewport' && viewportRange
      ? fittedFluxScale(viewportRange.minB, viewportRange.maxB)
      : FIXED_FLUX_SCALE)
    : raster.colorScale ?? { minB, maxB, overAboveT: null, fixed: false };
  const legendLabel = (value: number) => (legendScale.fixed ? value.toFixed(1) : value.toFixed(3));
  const legendTicks = saturationTicks.filter((tick) => (
    legendScale.overAboveT !== null && tick.bT > legendScale.minB && tick.bT < legendScale.maxB
  ));
  // Where the flux legend is drawn over the view (the Solve tab), the motor is
  // fitted beside it, never under its labels; the canvas, its overlays and the
  // probe all live in the narrowed box. Below the plot (Results) nothing moves.
  const plotRootRef = useRef<HTMLElement>(null);
  const legendRef = useRef<HTMLDivElement>(null);
  const [motorFitWidth, setMotorFitWidth] = useState<number | null>(null);
  const legendShown = !overlay;
  useLayoutEffect(() => {
    const root = plotRootRef.current;
    const box = navigation.viewportRef.current;
    const legend = legendRef.current;
    if (!root || !box || !legend) {
      setMotorFitWidth(null);
      return undefined;
    }
    const measure = () => {
      const boxRect = box.getBoundingClientRect();
      // Every label, which sit outside the legend's own box (the colour bar),
      // in px from the view's left and top edges.
      const parts = [legend, ...legend.querySelectorAll<HTMLElement>('*')]
        .filter((element) => !element.classList.contains('public-visually-hidden'))
        .map((element) => element.getBoundingClientRect())
        .filter((rect) => rect.width > 0 && rect.height > 0)
        .map((rect) => ({
          left: rect.left - boxRect.left,
          top: rect.top - boxRect.top,
          bottom: rect.bottom - boxRect.top,
        }));
      const next = motorFitWidthBesideLegend(root.clientWidth, box.clientHeight, parts);
      setMotorFitWidth((current) => (
        current === next || (current !== null && next !== null && Math.abs(current - next) < 0.5) ? current : next
      ));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    observer.observe(legend);
    return () => observer.disconnect();
  }, [legendShown, legendTicks.length, legendScale.fixed, legendScale.overAboveT, showRangeControl]);

  // Every hook is above this line, so a plot that has no data yet keeps the same hooks.
  if (!prepared && !raster) return null;
  const triangleCount = raster?.triangleCount ?? prepared?.triangleCount ?? 0;
  const contourLevelCount = raster?.contourLevelCount ?? plot?.contour_levels.length ?? 0;
  const availableDirectionCues = raster?.vectorCues ?? prepared?.vectorCues ?? [];
  const directionCueTarget = fieldLineDensity === 'low' ? 12 : fieldLineDensity === 'medium' ? 20 : 32;
  const sampleCues = (cues: PublicFieldVectorCue[]) => (cues.length <= directionCueTarget
    ? cues
    : Array.from({ length: directionCueTarget }, (_, index) => (
      cues[Math.round(index * (cues.length - 1) / (directionCueTarget - 1))]
    )));
  const directionCues = sampleCues(availableDirectionCues);
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
  const overlayDirectionCues = overlay && showFieldLines
    ? sampleCues(overlay.raster?.vectorCues ?? overlayPrepared?.vectorCues ?? [])
    : [];
  const hasDirectionCues = showFieldLines && (directionCues.length > 0 || overlayDirectionCues.length > 0);
  const statorPoleLabelRadius = Number.isFinite(statorInnerRadiusMm)
    ? (statorInnerRadiusMm ?? 0) + Math.max(3.2, Math.min(5, (statorInnerRadiusMm ?? 0) * 0.075))
    : null;
  const hasStatorPolarityCues = statorPoleLabelRadius !== null && statorPolarityCues.length > 0;
  const hasAirgapOverlay = showAirgap
    && Number.isFinite(airgapInnerRadiusMm)
    && Number.isFinite(statorInnerRadiusMm)
    && (airgapInnerRadiusMm ?? 0) > 0
    && (statorInnerRadiusMm ?? 0) > (airgapInnerRadiusMm ?? 0);
  const axisRotorRadius = airgapInnerRadiusMm ?? 0;
  const axisStatorRadius = statorInnerRadiusMm ?? 0;
  const hasFieldAxes = fieldAxes !== null
    && leadElecDeg !== null
    && axisRotorRadius > 0
    && axisStatorRadius > axisRotorRadius;
  const polar = (radius: number, angleDeg: number) => {
    const angleRad = (angleDeg * Math.PI) / 180;
    return [radius * Math.cos(angleRad), -radius * Math.sin(angleRad)] as const;
  };
  const axisPitchDeg = 360 / axisPolePairs;
  const axisAngles = (startDeg: number) => Array.from(
    { length: axisPolePairs },
    (_, index) => startDeg + index * axisPitchDeg,
  );
  // The arc marks one rotor pole nearest the top of the view and the stator
  // axis just ahead of it in the direction of rotation.
  const arcRotorDeg = hasFieldAxes && rotorAxisDeg !== null
    ? axisAngles(rotorAxisDeg).reduce((best, angle) => (
      Math.abs(((angle - 90) % 360 + 540) % 360 - 180) < Math.abs(((best - 90) % 360 + 540) % 360 - 180) ? angle : best
    ))
    : 0;
  const arcSpanDeg = hasFieldAxes && leadElecDeg !== null
    ? (fieldAxes?.rotation === 'clockwise' ? -1 : 1) * leadElecDeg / axisPolePairs
    : 0;
  const arcRadius = axisRotorRadius * 0.5;
  const [arcX1, arcY1] = polar(arcRadius, arcRotorDeg);
  const [arcX2, arcY2] = polar(arcRadius, arcRotorDeg + arcSpanDeg);
  const [arcLabelX, arcLabelY] = polar(arcRadius * 0.8, arcRotorDeg + arcSpanDeg / 2);
  // Two lines from the centre to the marked rotor arrow and the stator arrow
  // ahead of it, so the lead angle reads as an angle at the shaft.
  const [rayRotorX, rayRotorY] = polar(axisRotorRadius * 0.62, arcRotorDeg);
  const [rayStatorX, rayStatorY] = polar(axisStatorRadius * 1.04, arcRotorDeg + arcSpanDeg);
  const axisFontSize = Math.max(1.2, axisRotorRadius * 0.07);
  const leadLabel = `${Math.round(Math.abs(leadElecDeg ?? 0))}° elec`;
  const gammaNote = leadElecDeg !== null && leadElecDeg > 0 ? currentAngleNote(fieldAxes?.currentAngleDeg) : null;
  // The marked pole's d-axis (its magnet arrow) and the q-axis 90° elec ahead of it.
  const qAxisDeg = arcRotorDeg + qAxisOffsetDeg(axisPolePairs, fieldAxes?.rotation ?? 'clockwise');
  const [qEndX, qEndY] = polar(axisRotorRadius * 0.96, qAxisDeg);
  const [qLabelX, qLabelY] = polar(axisRotorRadius * 1.0 + axisFontSize * 0.9, qAxisDeg);
  const [dLabelX, dLabelY] = polar(axisRotorRadius * 0.62 - axisFontSize * 0.9, arcRotorDeg);
  const visibleLayerLabel = [
    showHeatmap && hasHeatmap ? 'flux-density heatmap' : null,
    showMesh && hasMesh ? 'solver mesh edges' : null,
    showFieldLines && hasFieldLines ? (overlay ? 'stator field lines in orange and PM field lines in cyan' : 'magnetic field lines') : null,
    hasDirectionCues ? 'field-direction arrows' : null,
    showMagnets && magnetOverlay.length > 0
      ? magnetReference ? 'dimmed permanent-magnet reference geometry' : 'permanent magnets'
      : null,
    hasAirgapOverlay ? 'airgap boundary contour' : null,
    hasStatorPolarityCues ? 'current-induced stator pole labels' : null,
    hasFieldAxes ? 'stator and magnet field-axis arrows with the d and q axes' : null,
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
    const [[ax, ay], [bx, by], [cx, cy]] = record.points;
    setProbe({
      elementIndex: record.index,
      region: sourcePlot.regions[record.index] ?? 'unclassified',
      bMagT: record.value ?? 0,
      bxT: Number.isFinite(bxT) ? bxT ?? null : null,
      byT: Number.isFinite(byT) ? byT ?? null : null,
      radiusMm: Math.hypot((ax + bx + cx) / 3, (ay + by + cy) / 3),
    });
  };
  const probeDescription = probe ? describeProbe(probe) : null;
  const linesLegendNote = [
    'Separate solves: in saturated steel the resultant is not their sum.',
    hasFieldAxes && leadElecDeg !== null
      ? `Arrows: each field's ${axisPolePairs}-pole-pair flux pointing outward. ${leadElecDeg >= 0 ? 'The magnets are pulled after the stator field.' : 'The stator field holds the magnets back.'}`
      : null,
    hasFieldAxes && leadElecDeg !== null ? leadAngleExplanation(leadElecDeg, axisPolePairs) : null,
    hasFieldAxes && leadElecDeg !== null && statorStrongestPolePairs !== null && statorStrongestPolePairs !== axisPolePairs
      ? `The stator's stronger ${statorStrongestPolePairs}-pole-pair part gives no steady torque and can make its lines seem to turn the other way.`
      : null,
  ].filter(Boolean).join(' ');

  return (
    <section className={`public-field-result${overlay ? ' has-lines-legend' : ''}`} aria-label="Solved magnetic field map" ref={plotRootRef}>
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
        style={motorFitWidth === null ? undefined : { flex: `0 0 ${motorFitWidth.toFixed(1)}px` }}
        title="Use the mouse wheel to zoom; drag to pan when zoomed"
        {...navigation.bind}
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setProbe(null)}
      >
        <canvas ref={canvasRef} role="img" aria-label={`Solved ${visibleLayerLabel}`} />
        <div className="public-viewport-navigation-content public-field-overlay-navigation" style={navigation.contentStyle}>
          {(hasDirectionCues || (showMagnets && magnetOverlay.length > 0) || hasAirgapOverlay || hasStatorPolarityCues || hasFieldAxes) && <svg viewBox={`0 0 ${FIELD_RASTER_SIZE} ${FIELD_RASTER_SIZE}`} className="public-field-result-overlay" aria-hidden="true">
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
                    className={`public-field-direction-cue${pmLines ? ' is-overlay' : ''}`}
                    key={`field-direction-${index}`}
                  >
                    <path d={arrowPath} style={style} />
                  </g>
                );
              })}
              {hasDirectionCues && overlayDirectionCues.map((cue, index) => {
                const screenAngleDeg = Math.atan2(-cue.dy, cue.dx) * 180 / Math.PI;
                const style = {
                  '--public-field-arrow-delay': `${-(index % 12) * 0.14}s`,
                } as CSSProperties;
                return (
                  <g
                    transform={`translate(${cue.x} ${-cue.y}) rotate(${screenAngleDeg})`}
                    className="public-field-direction-cue is-overlay"
                    key={`overlay-direction-${index}`}
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
              {hasFieldAxes && statorAxisDeg !== null && rotorAxisDeg !== null && (
                <g className="public-field-axes">
                  <path className="public-field-axis-ray is-pm" d={`M 0 0 L ${rayRotorX} ${rayRotorY}`} />
                  <path className="public-field-axis-q" d={`M 0 0 L ${qEndX} ${qEndY}`} />
                  <text className="public-field-axis-label is-dq" x={qLabelX} y={qLabelY} style={{ fontSize: axisFontSize }}>q</text>
                  <text className="public-field-axis-label is-dq is-d" x={dLabelX} y={dLabelY} style={{ fontSize: axisFontSize }}>d</text>
                  <path className="public-field-axis-ray is-stator" d={`M 0 0 L ${rayStatorX} ${rayStatorY}`} />
                  {axisAngles(rotorAxisDeg).map((angle) => {
                    const arrow = fieldAxisArrowPaths(axisRotorRadius * 0.62, axisRotorRadius * 0.96, angle);
                    return (
                      <g className="public-field-axis is-pm" key={`pm-axis-${angle}`}>
                        <path className="public-field-axis-shaft" d={arrow.shaft} />
                        <path d={arrow.head} />
                      </g>
                    );
                  })}
                  {axisAngles(statorAxisDeg).map((angle) => {
                    const arrow = fieldAxisArrowPaths(axisStatorRadius * 1.04, axisStatorRadius * 1.32, angle);
                    return (
                      <g className="public-field-axis is-stator" key={`stator-axis-${angle}`}>
                        <path className="public-field-axis-shaft" d={arrow.shaft} />
                        <path d={arrow.head} />
                      </g>
                    );
                  })}
                  <path
                    className="public-field-axis-arc"
                    d={`M ${arcX1} ${arcY1} A ${arcRadius} ${arcRadius} 0 0 ${arcSpanDeg > 0 ? 0 : 1} ${arcX2} ${arcY2}`}
                  />
                  <g className="public-field-axis-help">
                    <title>{leadAngleExplanation(leadElecDeg ?? 0, axisPolePairs)}</title>
                    <text className="public-field-axis-label" x={arcLabelX} y={arcLabelY} style={{ fontSize: axisFontSize }}>
                      {leadLabel}
                    </text>
                    {gammaNote && (
                      <text className="public-field-axis-label is-note" x={arcLabelX} y={arcLabelY + axisFontSize * 1.15} style={{ fontSize: axisFontSize * 0.72 }}>
                        {gammaNote}
                      </text>
                    )}
                    <g className="public-field-axis-help-badge" transform={`translate(${arcLabelX + axisFontSize * (leadLabel.length * 0.3 + 0.9)} ${arcLabelY})`}>
                      <circle r={axisFontSize * 0.62} />
                      <text style={{ fontSize: axisFontSize * 0.85 }}>?</text>
                    </g>
                  </g>
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
        {(() => {
          const zoomControls = (
            <ViewportNavigationControls
              scale={navigation.scale}
              onZoomIn={navigation.zoomIn}
              onZoomOut={navigation.zoomOut}
              onReset={navigation.reset}
            />
          );
          return navigationSlot ? createPortal(zoomControls, navigationSlot) : zoomControls;
        })()}
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
      {overlay ? (
        // One line above the view: the two line colours and the stator lead.
        // The longer notes are its tooltip, not text over the motor.
        <div className="public-field-lines-legend" aria-label="Field-line colours" title={linesLegendNote}>
          <span><i className="is-stator" aria-hidden="true" />Stator</span>
          <span><i className="is-pm" aria-hidden="true" />PM</span>
          {hasFieldAxes && leadElecDeg !== null && (
            <strong className="public-field-lead">
              <span className="public-field-lead-long">Stator {leadElecDeg >= 0 ? 'leads' : 'lags'} magnets by {Math.round(Math.abs(leadElecDeg))}° elec</span>
              <span className="public-field-lead-short" aria-hidden="true">Stator {leadElecDeg >= 0 ? 'leads' : 'lags'} {Math.round(Math.abs(leadElecDeg))}°</span>
            </strong>
          )}
        </div>
      ) : <div className={`public-field-result-legend${legendScale.fixed ? ' is-fixed' : ''}`} ref={legendRef}>
        <strong>Flux density <span>|B| (T)</span></strong>
        <span className="is-min">{legendLabel(legendScale.minB)}</span>
        <i aria-hidden="true">
          {legendTicks.map((tick) => (
            <b
              className={`public-field-legend-tick is-${tick.label}`}
              key={tick.label}
              style={{ ['--tick-at' as never]: `${(((tick.bT - legendScale.minB) / (legendScale.maxB - legendScale.minB)) * 100).toFixed(2)}%` }}
            >
              <em>{tick.bT.toFixed(2)} {tick.label === 'knee' ? 'knee' : 'sat.'}</em>
            </b>
          ))}
        </i>
        {legendScale.overAboveT !== null && (
          <span
            className="is-over"
            title="Elements above 2.0 T. Sharp corners can show local peaks this high; the probe gives the exact value."
          >
            <b aria-hidden="true" />&gt; {legendScale.overAboveT.toFixed(1)} T
          </span>
        )}
        <span className="is-mid">{legendLabel((legendScale.minB + legendScale.maxB) / 2)}</span>
        <span className="is-max">{legendLabel(legendScale.maxB)}</span>
        {legendTicks.length > 0 && (
          <span className="public-visually-hidden">
            {legendTicks.map((tick) => `${tick.steelName} ${tick.label} at ${tick.bT.toFixed(2)} T, where its relative permeability falls to ${tick.relativePermeability}.`).join(' ')}
          </span>
        )}
        {showRangeControl && onColorRangeModeChange && (
          <div className="public-field-range-control" role="group" aria-label="Flux-density color range">
            <button
              type="button"
              aria-pressed={colorRangeMode === 'fixed'}
              aria-label="Fixed range: one 0 to 2.0 T scale for every position and design"
              title="One 0–2.0 T scale everywhere · above 2.0 T in magenta"
              onClick={() => onColorRangeModeChange('fixed')}
            >
              Fixed
            </button>
            <button
              type="button"
              aria-pressed={colorRangeMode === 'viewport'}
              aria-label="Fit view: rescale colors to the visible zoomed area, never past 2.0 T"
              title="Fit the visible zoomed area · never past 2.0 T · a stopped frame only"
              onClick={() => onColorRangeModeChange('viewport')}
            >
              Fit view
            </button>
          </div>
        )}
        <small>{triangleCount.toLocaleString()} solved elements · {contourLevelCount} contour levels</small>
      </div>}
    </section>
  );
}
