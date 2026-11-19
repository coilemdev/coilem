import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { createPortal } from 'react-dom';
import { useMagnifierCanvas, ViewportMagnifier } from './ViewportMagnifier';

import {
  airgapHarmonic,
  strongestAirgapPolePairs,
} from '../components/tutorials/fieldPolarityCues';
import type { AirgapBrBtProfile } from '../components/tutorials/lessonSolveTypes';
import type {
  GeometryPreview,
  PublicFieldLinePlot,
  PublicFieldVectorCue,
} from './model';
import {
  buildFieldArrowMesh,
  drawFieldArrows,
  FIELD_ARROW_COLORS,
  FIELD_ARROW_LENGTH_FRACTION,
  FIELD_ARROW_RING_OFFSET,
  fieldArrowSpacingMm,
  sampleFieldArrows,
  tintFieldArrowImage,
  visibleFieldArrowRect,
  type FieldArrowDensity,
  type FieldArrowMesh,
  type FieldArrowTone,
} from './fieldArrows';
import {
  coilMarksFromGeometry,
  coilSideMark,
  coilSidesFromGeometry,
  phaseCycleSampler,
  recordedPhaseHistory,
  statorTeethFromGeometry,
  type CoilMark,
  type CoilSide,
  type FieldPhaseView,
} from './fieldPhases';
import { PUBLIC_MOTOR_COLORS, PUBLIC_PHASE_COLORS } from './motorPalette';
import { phaseDriveFrame, phaseStrips, scopeWindowElecDeg, toothPoleFillOpacity, toothPoleLabelOpacity, toothPoleLabelSize, type PhaseCurrentSampler } from './phaseDrive';
import { drawCurrentMarker, drawPhaseDriveWired } from './phaseDrivePanel';
import {
  buildTriangleGrid,
  triangleGridCell,
  triangleGridItemsInRect,
  type TriangleGrid,
} from './triangleGrid';
import {
  useViewportNavigation,
  ViewportNavigationControls,
} from './ViewportNavigation';
import { currentAngleNote, fieldAxisArrowPaths, leadAngleExplanation, qAxisOffsetDeg, rotorNorthAxisDeg, statorLeadElecDeg } from './fieldAxes';
import { motorFitWidthBesideLegend } from './fieldLegendFit';
import { ringKey, sectorView, type RingMm } from './sectorFraming';
import { fieldStrokeScale } from './fieldStrokeWidth';
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
/** Magnification relative to the main view. */
const LOUPE_MAGNIFICATION = 3;
/**
 * The fit that draws the motor the size the geometry and mesh canvases draw it,
 * so it does not jump between the Solve tabs: they give the motor 85% of the
 * view's smaller side (viewportTransform.ts), this plot 1 / 1.05 of it.
 */
export const FIELD_FIT_LIKE_MOTOR_CANVAS = 0.85 * 1.05;
const DETAIL_RENDER_SCALE = 1.08;
const VIEWPORT_SCALE_SETTLE_MS = 140;

/** How closely the field arrows are spaced (the Low / Med / High control). */
export type FieldLineDensity = FieldArrowDensity;
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
  saturationTone: 'neutral' | 'good' | 'warning' | 'danger';
}

interface RenderedFieldLayers {
  base: HTMLCanvasElement | null;
  heat: HTMLCanvasElement;
  mesh: HTMLCanvasElement;
}

export interface FieldResultRaster {
  base: ImageBitmap | null;
  heat: ImageBitmap | null;
  mesh?: ImageBitmap | null;
  /** The field-arrow layer: light arrows with a dark rim (older images: flux lines). */
  lines: ImageBitmap | null;
  /** The PM playback worker has already coloured this image cyan. */
  pmArrowsTinted?: boolean;
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

/** The PM field's arrows drawn over the stator's, as in the Stator + PM view (#120). */
export interface FieldLineOverlay {
  /** Playback raster of the second field; only its arrow layer is drawn. */
  raster: FieldResultRaster | null;
  /** Exact solver frame of the second field, its arrows drawn from it when available. */
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
  viewBox: string;
  /** The view box's larger side, mm: the arrow spacing is a share of it. */
  viewSize: number;
  /** Stroke-width factor for this view's size (fieldStrokeWidth). */
  strokeScale: number;
  minB: number;
  maxB: number;
  triangleCount: number;
  /** Whether the plot carries each element's B, which the arrows need. */
  hasArrows: boolean;
  /** The elements indexed for the arrows, built when first drawn. */
  arrowMesh: FieldArrowMesh | null | undefined;
  /** triangleRecords indexed by bounding box (magnifier, probe), built when first needed. */
  recordGrid: TriangleGrid | null | undefined;
  plot: PublicFieldLinePlot;
  renderedLayers: RenderedFieldLayers | null;
}

interface PreparedMagnetOverlay {
  path: string;
  center: [number, number];
  polarity: 'north' | 'south';
}

const preparedFieldPlotCache = new WeakMap<PublicFieldLinePlot, PreparedFieldPlot | null>();

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

function polygonPath(points: Array<[number, number]>): string {
  return `M ${points.map(([x, y]) => `${x} ${-y}`).join(' L ')} Z`;
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
        path: polygonPath(points),
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

  return {
    basePath,
    heatPaths,
    heatBucketCounts,
    heatPathCache: new Map(),
    triangleRecords,
    viewBox: `${minX - padding} ${-maxY - padding} ${width + padding * 2} ${height + padding * 2}`,
    viewSize: Math.max(width, height) + padding * 2,
    strokeScale: fieldStrokeScale(width + padding * 2, height + padding * 2),
    minB,
    maxB,
    triangleCount,
    hasArrows: (plot.element_bx_t?.length ?? 0) > 0 && (plot.element_by_t?.length ?? 0) > 0,
    arrowMesh: undefined,
    recordGrid: undefined,
    plot,
    renderedLayers: null,
  };
}

/** The plot's elements indexed by bounding box, built when first needed. */
function fieldRecordGrid(prepared: PreparedFieldPlot): TriangleGrid | null {
  if (prepared.recordGrid === undefined) {
    const records = prepared.triangleRecords;
    const boxes = new Float64Array(records.length * 4);
    records.forEach(({ points: [[ax, ay], [bx, by], [cx, cy]] }, item) => {
      boxes.set([Math.min(ax, bx, cx), Math.min(ay, by, cy), Math.max(ax, bx, cx), Math.max(ay, by, cy)], item * 4);
    });
    prepared.recordGrid = buildTriangleGrid(boxes, records.length);
  }
  return prepared.recordGrid;
}

/** The element under a model-space point, from the cell it falls in rather than every element. */
function locateFieldRecord(prepared: PreparedFieldPlot, x: number, y: number): PreparedFieldPlot['triangleRecords'][number] | null {
  const grid = fieldRecordGrid(prepared);
  const cell = grid ? triangleGridCell(grid, x, y) : -1;
  if (!grid || cell < 0) return null;
  for (let entry = grid.cellStart[cell]; entry < grid.cellStart[cell + 1]; entry += 1) {
    const record = prepared.triangleRecords[grid.cellItems[entry]];
    if (pointInTriangle(x, y, record.points)) return record;
  }
  return null;
}

/**
 * The base, flux colours and mesh edges of only the elements the canvas shows
 * through its current transform. The magnifier sees a few percent of the
 * motor; filling every element on each pointer move made it trail the pointer.
 */
function drawFieldRegion(
  context: CanvasRenderingContext2D,
  prepared: PreparedFieldPlot,
  heatScale: FluxColorScale | null,
  meshViewportScale: number | null,
): void {
  const rect = visibleFieldArrowRect(context);
  const grid = fieldRecordGrid(prepared);
  if (!rect || !grid) {
    drawBase(context, prepared);
    if (heatScale) drawHeat(context, prepared, heatScale);
    if (meshViewportScale !== null) drawMeshEdges(context, prepared, meshViewportScale);
    return;
  }
  const base = new Path2D();
  const heat = heatScale ? Array.from({ length: FLUX_OVER_RANGE_INDEX + 1 }, () => new Path2D()) : null;
  const filled = new Uint8Array(FLUX_OVER_RANGE_INDEX + 1);
  triangleGridItemsInRect(grid, rect).forEach((item) => {
    const { points, value } = prepared.triangleRecords[item];
    addTrianglePath(base, points);
    if (!heat || !heatScale || value === null || !Number.isFinite(value)) return;
    const bucket = fluxColorIndex(value, heatScale);
    addTrianglePath(heat[bucket], points);
    filled[bucket] = 1;
  });
  context.fillStyle = '#202733';
  context.fill(base);
  heat?.forEach((path, bucket) => {
    if (!filled[bucket]) return;
    context.fillStyle = fluxColor(bucket);
    context.fill(path);
  });
  if (meshViewportScale !== null) {
    context.save();
    context.strokeStyle = 'rgba(203,213,225,.42)';
    context.lineWidth = (0.11 * prepared.strokeScale) / Math.max(meshViewportScale, Number.EPSILON);
    context.lineJoin = 'round';
    context.stroke(base);
    context.restore();
  }
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
  context.lineWidth = (0.11 * prepared.strokeScale) / Math.max(viewportScale, Number.EPSILON);
  context.lineJoin = 'round';
  context.stroke(prepared.basePath);
  context.restore();
}

/**
 * Draw the field's B arrows through the context's world transform, over the
 * part of the plot the canvas shows. Zooming in adds arrows in half-octave
 * steps, so they stay small on screen (fieldArrows.ts).
 */
function drawFieldArrowLayer(
  context: CanvasRenderingContext2D,
  prepared: PreparedFieldPlot,
  density: FieldLineDensity,
  tone: FieldArrowTone,
  zoom: number,
): void {
  if (!prepared.hasArrows) return;
  if (prepared.arrowMesh === undefined) {
    const { plot } = prepared;
    prepared.arrowMesh = buildFieldArrowMesh(plot.nodes_mm, plot.triangles, plot.element_bx_t, plot.element_by_t);
  }
  if (!prepared.arrowMesh) return;
  const spacing = fieldArrowSpacingMm(prepared.viewSize, density, zoom);
  const arrows = sampleFieldArrows(
    prepared.arrowMesh,
    spacing,
    tone === 'pm' ? FIELD_ARROW_RING_OFFSET.pm : FIELD_ARROW_RING_OFFSET.primary,
    visibleFieldArrowRect(context),
  );
  drawFieldArrows(context, arrows, spacing * FIELD_ARROW_LENGTH_FRACTION, FIELD_ARROW_COLORS[tone]);
}

/**
 * Phases on a canvas: each coil outlined in its phase colour and, where its
 * phase carries current, the Geometry view's ⊙ / ⊗ at its glyph. `toCanvas`
 * maps the plot's drawing space (x, -y in mm) to canvas pixels. Drawn at screen
 * size, not scaled with the view, so the marks stay crisp and readable at any
 * zoom (an SVG overlay is stretched as one image while zooming).
 */
function drawCoilPhases(
  context: CanvasRenderingContext2D,
  toCanvas: DOMMatrix,
  pixelRatio: number,
  coilOutlines: ReadonlyMap<CoilSide['phase'], Path2D>,
  coilMarks: readonly CoilMark[],
  phases: FieldPhaseView,
): void {
  const pixelsPerMm = Math.hypot(toCanvas.a, toCanvas.b);
  if (!(pixelsPerMm > 0)) return;
  context.save();
  context.setTransform(toCanvas);
  context.lineWidth = (1.3 * pixelRatio) / pixelsPerMm;
  context.lineJoin = 'round';
  context.globalAlpha = 0.95;
  coilOutlines.forEach((path, phase) => {
    context.strokeStyle = PUBLIC_PHASE_COLORS[phase];
    context.stroke(path);
  });
  context.globalAlpha = 1;
  context.setTransform(1, 0, 0, 1, 0, 0);
  if (phases.currentsA) {
    coilMarks.forEach((mark) => {
      const outOfPage = coilSideMark(mark, phases.currentsA ?? [0, 0, 0], phases.cycle.peakA);
      if (outOfPage === null) return;
      const { x, y } = toCanvas.transformPoint({ x: mark.centre[0], y: -mark.centre[1] });
      // The glyph's size, as the Geometry view draws it, but never smaller than
      // a readable mark nor so large it hides the slot when zoomed in.
      const radius = Math.min(10 * pixelRatio, Math.max(4 * pixelRatio, mark.radiusMm * 1.1 * pixelsPerMm));
      drawCurrentMarker(context, x, y, radius, outOfPage, PUBLIC_PHASE_COLORS[mark.phase]);
    });
  }
  context.restore();
}

/** The square of SVG-space coordinates that a square raster with this view box covers. */
function rasterWorldSquare(viewBox: string): { left: number; top: number; size: number } | null {
  const [x, y, width, height] = viewBox.split(/\s+/).map(Number);
  if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null;
  const size = Math.max(width, height);
  return { left: x - (size - width) / 2, top: y - (size - height) / 2, size };
}

const tintedArrowLayers = new WeakMap<ImageBitmap | HTMLCanvasElement, Map<string, HTMLCanvasElement>>();

/**
 * A playback arrow layer (light arrows, dark rim) in another field's colour:
 * multiplying by the colour turns the light bodies to it and leaves the rims
 * dark. Made once per image and colour.
 */
function tintedArrowLayer(lines: ImageBitmap | HTMLCanvasElement, tone: FieldArrowTone): ImageBitmap | HTMLCanvasElement {
  if (tone === 'field') return lines;
  const color = FIELD_ARROW_COLORS[tone];
  const byColor = tintedArrowLayers.get(lines) ?? new Map<string, HTMLCanvasElement>();
  tintedArrowLayers.set(lines, byColor);
  const cached = byColor.get(color);
  if (cached) return cached;
  const layer = document.createElement('canvas');
  layer.width = lines.width;
  layer.height = lines.height;
  const context = layer.getContext('2d');
  if (context) tintFieldArrowImage(context, lines, color);
  byColor.set(color, layer);
  return layer;
}

function warmPreparedFieldPlot(prepared: PreparedFieldPlot | null): void {
  if (!prepared || prepared.renderedLayers || typeof document === 'undefined') return;
  const heat = renderPathLayer(prepared, (context) => {
    drawBase(context, prepared);
    drawHeat(context, prepared);
  });
  const mesh = renderPathLayer(prepared, (context) => {
    drawMeshEdges(context, prepared);
  });
  prepared.renderedLayers = { base: null, heat, mesh };
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
  airgapRingMm,
  showMagnetPolarityLabels = true,
  magnetReference = false,
  toothPoleStrengths = null,
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
  showStatistics = true,
  probeEnabled = true,
  magnifier = false,
  magnifierSlot = null,
  probeSlot = null,
  fitScale = 1,
  rotorMarkDeg = null,
  describeProbe = defaultProbeDescription,
  onViewportScaleSettled,
  overlay = null,
  fieldAxes = null,
  pmLines = false,
  navigationSlot = null,
  ring = null,
  phases = null,
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
  /** The air gap's two edges, inner then outer, where they are not the rotor surface and the stator bore: an outer rotor. */
  airgapRingMm?: readonly [number, number];
  showMagnetPolarityLabels?: boolean;
  magnetReference?: boolean;
  /** Winding polarity at each stationary tooth, N positive, for the displayed frame. */
  toothPoleStrengths?: number[] | null;
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
  showStatistics?: boolean;
  probeEnabled?: boolean;
  /** Show the area under the pointer enlarged in a corner of the view. */
  magnifier?: boolean;
  magnifierSlot?: HTMLElement | null;
  /** Render the element readout beneath the magnifier in the analysis rail. */
  probeSlot?: HTMLElement | null;
  /** The share of the usual fit to draw the motor at; below 1 leaves a wider margin. */
  fitScale?: number;
  /** The rotor's mechanical angle: draws the 0° tick and the dot that goes round with the rotor. Null hides them. */
  rotorMarkDeg?: number | null;
  describeProbe?: (probe: FieldProbe) => FieldProbeDescription;
  onViewportScaleSettled?: (scale: number) => void;
  overlay?: FieldLineOverlay | null;
  /** Draw the field's own arrows in the PM colour (the PM-only view). */
  pmLines?: boolean;
  fieldAxes?: FieldAxesOptions | null;
  /** Render the zoom controls here instead of over the plot (the solved-field viewer's control dock). */
  navigationSlot?: HTMLElement | null;
  /** An outrunner's active ring: a thin one opens on its sector (sectorFraming.ts). */
  ring?: RingMm | null;
  /** The Phases layer: the coils by phase, their current now and an A / B / C readout (fieldPhases.ts). */
  phases?: FieldPhaseView | null;
}) {
  const ringInnerMm = ring?.innerMm;
  const ringOuterMm = ring?.outerMm;
  // The plot fits the motor's extents plus 2.5% padding per side into the smaller side of the view.
  const sectorForSize = useCallback((width: number, height: number) => sectorView(
    ringInnerMm !== undefined && ringOuterMm !== undefined ? { innerMm: ringInnerMm, outerMm: ringOuterMm } : null,
    width,
    height,
    (Math.min(width, height) * fitScale) / (2 * 1.05),
  ), [fitScale, ringInnerMm, ringOuterMm]);
  const navigation = useViewportNavigation(
    undefined,
    undefined,
    sectorForSize,
    ringKey(ringInnerMm !== undefined && ringOuterMm !== undefined ? { innerMm: ringInnerMm, outerMm: ringOuterMm } : null),
  );
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
  const hasField = Boolean(prepared || raster);
  const [canvasSize, setCanvasSize] = useState<{ width: number; height: number } | null>(null);
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const measure = () => {
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      setCanvasSize((previous) => previous?.width === width && previous.height === height ? previous : { width, height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [hasField]);
  const magnetOverlay = useMemo(
    () => prepareMagnetOverlay(geometry, magnetRotationDeg),
    [geometry, magnetRotationDeg],
  );
  // The stator's coil sides and their ⊙ / ⊗ places do not turn with the rotor.
  const coilOutlines = useMemo(() => {
    const paths = new Map<CoilSide['phase'], Path2D>();
    for (const { phase, points } of coilSidesFromGeometry(geometry)) {
      const path = paths.get(phase) ?? new Path2D();
      path.addPath(new Path2D(polygonPath(points)));
      paths.set(phase, path);
    }
    return paths;
  }, [geometry]);
  const coilMarks = useMemo(() => coilMarksFromGeometry(geometry), [geometry]);
  const phasesShown = phases !== null && coilOutlines.size > 0;
  const phaseCycle = phases?.cycle ?? null;
  const phaseSampler = useMemo(() => (phaseCycle ? phaseCycleSampler(phaseCycle) : null), [phaseCycle]);
  const sample: PhaseCurrentSampler | null = useMemo(() => phaseSampler && phases?.pmOnly
    ? (angle: number) => phaseSampler(angle) ? [0, 0, 0] : null
    : phaseSampler, [phaseSampler, phases?.pmOnly]);
  const phaseHistory = useMemo(() => phases && sample && !phases.cycle.complete ? recordedPhaseHistory(
    phases.cycle, sample, phases.angleDeg, scopeWindowElecDeg(phases.rpm, phases.drive.poleCount),
  ) : undefined, [phases, sample]);
  const toothCount = toothPoleStrengths?.length ?? 0;
  const toothShapes = useMemo(() => {
    if (!toothCount) return [];
    return statorTeethFromGeometry(geometry).map(({ points, center, index }) => {
      const path = polygonPath(points);
      return {
        index, x: center[0], y: -center[1], path, canvasPath: new Path2D(path),
        fontSize: toothPoleLabelSize(Math.hypot(...center), toothCount),
      };
    });
  }, [geometry, toothCount]);
  const toothOverlay = useMemo(() => toothShapes.flatMap((shape) => {
    const strength = toothPoleStrengths?.[shape.index] ?? 0;
    const opacity = toothPoleFillOpacity(strength);
    if (!opacity) return [];
    return [{
      ...shape, opacity, labelOpacity: toothPoleLabelOpacity(strength),
      label: strength > 0 ? 'N' : 'S',
      color: strength > 0 ? PUBLIC_MOTOR_COLORS.magnetNorth : PUBLIC_MOTOR_COLORS.magnetSouth,
    }];
  }), [toothShapes, toothPoleStrengths]);
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
  // The plot the shown probe was read from, so a move within the same element is not a new state.
  const probePlotRef = useRef<PublicFieldLinePlot | null>(null);
  // The magnifier follows the pointer outside React: a pointer move records the
  // point and asks for one redraw in the next frame, of the newest point. Only
  // whether there is a point at all (the panel's hint) is state.
  const loupePointRef = useRef<{ x: number; y: number } | null>(null);
  const [hasLoupePoint, setHasLoupePoint] = useState(false);
  const loupeFrameRef = useRef<number | null>(null);
  const drawLoupeRef = useRef<() => void>(() => undefined);
  const { canvasRef: loupeCanvasRef, width: loupeWidth, height: loupeHeight } = useMagnifierCanvas(magnifier, magnifierSlot);
  const [viewportRange, setViewportRange] = useState<FieldViewportRange | null>(null);
  const viewportRangeRef = useRef<FieldViewportRange | null>(null);
  // Whether the canvas shows exact vectors (drawn here, on the chosen scale) or a
  // playback image (drawn on the scale it carries); the legend follows it.
  const [vectorDetailShown, setVectorDetailShown] = useState(false);
  const vectorDetailShownRef = useRef(false);
  const showHeatmap = controlledShowHeatmap ?? internalShowHeatmap;
  const showMesh = controlledShowMesh ?? internalShowMesh;
  const showFieldLines = controlledShowFieldLines ?? internalShowFieldLines;
  // The PM-only view draws its arrows in the PM colour; the Stator + PM view the
  // stator's in amber under the PM's in cyan; any other field's are light.
  const primaryTone: FieldArrowTone = pmLines ? 'pm' : overlay ? 'stator' : 'field';
  // Inner-rotor gap edges, or the explicit stator-OD/magnet edges of an outer rotor.
  const airgapEdges: readonly [number, number] = airgapRingMm ?? [airgapInnerRadiusMm ?? NaN, statorInnerRadiusMm ?? NaN];
  const hasAirgapOverlay = showAirgap
    && Number.isFinite(airgapEdges[0]) && Number.isFinite(airgapEdges[1])
    && airgapEdges[0] > 0 && airgapEdges[1] > airgapEdges[0];

  useEffect(() => {
    if (!probeEnabled || !sourcePlot) setProbe(null);
  }, [probeEnabled, sourcePlot]);
  useEffect(() => {
    if (magnifier) return;
    loupePointRef.current = null;
    setHasLoupePoint(false);
  }, [magnifier]);
  const scheduleLoupeDraw = useCallback(() => {
    // One redraw per frame, of whatever is newest when it runs. Cancelling and
    // asking again on every pointer move put it off for as long as the pointer
    // moved faster than the screen refreshed.
    if (loupeFrameRef.current !== null) return;
    loupeFrameRef.current = window.requestAnimationFrame(() => {
      loupeFrameRef.current = null;
      drawLoupeRef.current();
    });
  }, []);
  useEffect(() => () => {
    if (loupeFrameRef.current !== null) window.cancelAnimationFrame(loupeFrameRef.current);
  }, []);

  // The magnifier panel: the picture around the pointer, redrawn from the solved
  // elements at a higher zoom when they are loaded, so it is sharp and not a
  // stretched copy; otherwise an enlarged copy of the view. Only the elements
  // inside the panel are drawn (drawFieldRegion).
  drawLoupeRef.current = () => {
    const loupe = loupeCanvasRef.current;
    const canvas = canvasRef.current;
    const point = loupePointRef.current;
    if (!magnifier || !point || !loupe || !canvas) return;
    const { x: loupeX, y: loupeY } = point;
    {
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      const pixelWidth = Math.round(loupeWidth * pixelRatio);
      const pixelHeight = Math.round(loupeHeight * pixelRatio);
      if (loupe.width !== pixelWidth || loupe.height !== pixelHeight) {
        loupe.width = pixelWidth;
        loupe.height = pixelHeight;
      }
      const context = loupe.getContext('2d');
      if (!context) return;
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.fillStyle = '#0b0d12';
      context.fillRect(0, 0, pixelWidth, pixelHeight);
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const pivotX = width / 2 + navigation.pan.x;
      const pivotY = height / 2 + navigation.pan.y;
      const intoLoupe = new DOMMatrix()
        .scaleSelf(pixelRatio)
        .translateSelf(loupeWidth / 2, loupeHeight / 2)
        .scaleSelf(LOUPE_MAGNIFICATION)
        .translateSelf(-loupeX, -loupeY)
        .translateSelf(pivotX, pivotY)
        .rotateSelf(navigation.rotationDeg)
        .translateSelf(-pivotX, -pivotY);
      let worldTransform: DOMMatrix | null = null;
      if (prepared) {
        const [viewX, viewY, viewWidth, viewHeight] = prepared.viewBox.split(' ').map(Number);
        const size = Math.min(width, height) * fitScale;
        const baseScale = Math.min(size / viewWidth, size / viewHeight);
        const baseOffsetX = (width - viewWidth * baseScale) / 2;
        const baseOffsetY = (height - viewHeight * baseScale) / 2;
        const scale = baseScale * navigation.scale;
        const translateX = width / 2 + (baseOffsetX - viewX * baseScale - width / 2) * navigation.scale + navigation.pan.x;
        const translateY = height / 2 + (baseOffsetY - viewY * baseScale - height / 2) * navigation.scale + navigation.pan.y;
        worldTransform = intoLoupe.multiply(new DOMMatrix([scale, 0, 0, scale, translateX, translateY]));
        context.setTransform(worldTransform);
        drawFieldRegion(
          context,
          prepared,
          showHeatmap
            ? (colorRangeMode === 'viewport' && viewportRange
              ? fittedFluxScale(viewportRange.minB, viewportRange.maxB)
              : FIXED_FLUX_SCALE)
            : null,
          showMesh ? navigation.scale * LOUPE_MAGNIFICATION : null,
        );
        if (showFieldLines) {
          drawFieldArrowLayer(context, prepared, fieldLineDensity, primaryTone, navigation.scale * LOUPE_MAGNIFICATION);
          if (overlayPrepared) {
            drawFieldArrowLayer(context, overlayPrepared, fieldLineDensity, 'pm', navigation.scale * LOUPE_MAGNIFICATION);
          }
        }
      } else {
        const sourceScale = canvas.width / width;
        const spanX = loupeWidth / LOUPE_MAGNIFICATION;
        const spanY = loupeHeight / LOUPE_MAGNIFICATION;
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = 'high';
        context.drawImage(
          canvas,
          (loupeX - spanX / 2) * sourceScale,
          (loupeY - spanY / 2) * sourceScale,
          spanX * sourceScale,
          spanY * sourceScale,
          0,
          0,
          pixelWidth,
          pixelHeight,
        );
        const square = rasterWorldSquare(raster?.viewBox ?? '');
        if (square) {
          const drawSize = Math.min(width, height) * fitScale * navigation.scale;
          const scale = drawSize / square.size;
          const x = (width - drawSize) / 2 + navigation.pan.x - square.left * scale;
          const y = (height - drawSize) / 2 + navigation.pan.y - square.top * scale;
          worldTransform = intoLoupe.multiply(new DOMMatrix([scale, 0, 0, scale, x, y]));
        }
      }
      // Tooth poles are an SVG overlay in the main view. Include them in both
      // the magnified playback image and the magnified numerical field.
      if (worldTransform && toothOverlay.length) {
        context.save();
        for (const tooth of toothOverlay) {
          context.setTransform(worldTransform);
          context.globalAlpha = tooth.opacity;
          context.fillStyle = tooth.color;
          context.fill(tooth.canvasPath);
          if (!tooth.labelOpacity) continue;
          context.translate(tooth.x, tooth.y);
          context.rotate(-navigation.rotationDeg * Math.PI / 180);
          context.globalAlpha = tooth.labelOpacity;
          context.fillStyle = '#f8fafc';
          context.textAlign = 'center';
          context.textBaseline = 'middle';
          context.font = `800 ${tooth.fontSize}px ui-monospace, monospace`;
          context.fillText(tooth.label, 0, 0);
        }
        context.restore();
      }
      // The main view's airgap rings are an SVG overlay, so neither its canvas
      // nor a fresh vector redraw contains them. Draw both edges here as well.
      if (hasAirgapOverlay && worldTransform) {
        context.setTransform(worldTransform);
        const strokeScale = pixelRatio * LOUPE_MAGNIFICATION / Math.hypot(worldTransform.a, worldTransform.b);
        for (const [color, strokeWidth] of [['rgba(8,47,73,.85)', 1.5], ['rgba(103,232,249,.92)', 0.575]] as const) {
          context.strokeStyle = color;
          context.lineWidth = strokeWidth * strokeScale;
          for (const radius of airgapEdges) {
            context.beginPath();
            context.arc(0, 0, radius, 0, 2 * Math.PI);
            context.stroke();
          }
        }
      }
      // The sampled main canvas already includes its coils and current marks.
      if (prepared && phasesShown && phases && worldTransform) {
        drawCoilPhases(context, worldTransform, pixelRatio, coilOutlines, coilMarks, phases);
      }
      // A small cross marks the point under the pointer.
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      context.strokeStyle = 'rgba(255, 255, 255, 0.85)';
      context.lineWidth = 1;
      const centreX = loupeWidth / 2;
      const centreY = loupeHeight / 2;
      context.beginPath();
      context.moveTo(centreX - 7, centreY);
      context.lineTo(centreX + 7, centreY);
      context.moveTo(centreX, centreY - 7);
      context.lineTo(centreX, centreY + 7);
      context.stroke();
    }
  };
  // Anything else the panel shows changed: draw it again at the last point.
  useEffect(() => {
    scheduleLoupeDraw();
  }, [
    airgapEdges[0],
    airgapEdges[1],
    canvasSize,
    coilOutlines,
    coilMarks,
    colorRangeMode,
    fieldLineDensity,
    fitScale,
    hasAirgapOverlay,
    loupeWidth,
    loupeHeight,
    magnifierSlot,
    magnifier,
    navigation.pan.x,
    navigation.pan.y,
    navigation.rotationDeg,
    navigation.scale,
    overlayPrepared,
    prepared,
    primaryTone,
    raster,
    phases,
    scheduleLoupeDraw,
    toothOverlay,
    showFieldLines,
    showHeatmap,
    showMesh,
    viewportRange,
  ]);

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
    if (!canvas || !layers || !canvasSize) return;
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
    // overlay arrows go with exact primary arrows; otherwise its playback raster.
    const drawOverlayLines = (context: CanvasRenderingContext2D, vectorPrimary: boolean) => {
      if (!showFieldLines || !overlay) return;
      const overlayRaster = overlay.raster;
      if (overlayPrepared && (vectorPrimary || !overlayRaster)) {
        drawFieldArrowLayer(context, overlayPrepared, fieldLineDensity, 'pm', navigation.scale);
        return;
      }
      const square = overlayRaster ? rasterWorldSquare(overlayRaster.viewBox) : null;
      if (!overlayRaster?.lines || !square) return;
      const lines = overlayRaster.pmArrowsTinted ? overlayRaster.lines : tintedArrowLayer(overlayRaster.lines, 'pm');
      context.drawImage(lines, square.left, square.top, square.size, square.size);
    };
    const draw = () => {
      const width = Math.max(1, canvasSize.width);
      const height = Math.max(1, canvasSize.height);
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
      const pixelWidth = Math.max(1, Math.round(width * pixelRatio));
      const pixelHeight = Math.max(1, Math.round(height * pixelRatio));
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth;
        canvas.height = pixelHeight;
      }
      const context = canvas.getContext('2d');
      if (!context) return;
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.clearRect(0, 0, pixelWidth, pixelHeight);
      const size = Math.min(pixelWidth, pixelHeight) * fitScale;
      const panX = navigation.pan.x * pixelRatio;
      const panY = navigation.pan.y * pixelRatio;
      // The sector turntable turns the whole picture about the motor centre, which the
      // pan carries from the canvas centre; every layer below is drawn through it.
      const rotationRad = (navigation.rotationDeg * Math.PI) / 180;
      const pivotX = pixelWidth / 2 + panX;
      const pivotY = pixelHeight / 2 + panY;
      const viewMatrix = new DOMMatrix()
        .translateSelf(pivotX, pivotY)
        .rotateSelf(navigation.rotationDeg)
        .translateSelf(-pivotX, -pivotY);
      const setWorldTransform = (a: number, b: number, c: number, d: number, e: number, f: number) => {
        context.setTransform(viewMatrix.multiply(new DOMMatrix([a, b, c, d, e, f])));
      };
      context.setTransform(viewMatrix);
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
            rotationRad,
            pivotX,
            pivotY,
          })
          : null;
        publishViewportRange(visibleRange);
        context.save();
        setWorldTransform(
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
        if (showFieldLines) drawFieldArrowLayer(context, prepared, fieldLineDensity, primaryTone, navigation.scale);
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
      if (raster?.base) {
        canvas.dataset.renderMode = raster.base.width > FIELD_RASTER_SIZE
          ? 'detail-raster'
          : 'playback-raster';
        canvas.dataset.sourceResolution = `${raster.base.width}x${raster.base.height}`;
        context.drawImage(raster.base, x, y, drawSize, drawSize);
        if (showHeatmap && raster.heat) context.drawImage(raster.heat, x, y, drawSize, drawSize);
      } else if (prepared && layers.heat) {
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
          setWorldTransform(
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
      // Arrows come from the exact frame when there is one, else from the
      // playback image, which carries them at the medium spacing.
      const vectorArrows = Boolean(prepared && (highResolutionPlot || !raster));
      if (showFieldLines) {
        if (prepared && vectorArrows) {
          const [viewX, viewY, viewWidth, viewHeight] = prepared.viewBox.split(' ').map(Number);
          const baseScale = Math.min(size / viewWidth, size / viewHeight);
          const baseOffsetX = (pixelWidth - viewWidth * baseScale) / 2;
          const baseOffsetY = (pixelHeight - viewHeight * baseScale) / 2;
          const centerX = pixelWidth / 2;
          const centerY = pixelHeight / 2;
          context.save();
          setWorldTransform(
            baseScale * navigation.scale,
            0,
            0,
            baseScale * navigation.scale,
            centerX + (baseOffsetX - viewX * baseScale - centerX) * navigation.scale + panX,
            centerY + (baseOffsetY - viewY * baseScale - centerY) * navigation.scale + panY,
          );
          drawFieldArrowLayer(context, prepared, fieldLineDensity, primaryTone, navigation.scale);
          context.restore();
        } else if (raster?.lines) {
          // The image's light arrows, in the PM colour in the PM-only view and
          // in the stator's under the PM's in the Stator + PM view.
          const lines = raster.pmArrowsTinted ? raster.lines : tintedArrowLayer(raster.lines, primaryTone);
          context.drawImage(lines, x, y, drawSize, drawSize);
        }
        const primarySquare = rasterWorldSquare(raster?.viewBox ?? prepared?.viewBox ?? '');
        if (overlay && primarySquare) {
          const worldScale = drawSize / primarySquare.size;
          context.save();
          setWorldTransform(
            worldScale,
            0,
            0,
            worldScale,
            x - primarySquare.left * worldScale,
            y - primarySquare.top * worldScale,
          );
          drawOverlayLines(context, vectorArrows);
          context.restore();
        }
      }
    };
    // Where the rotor is: a tick fixed at 0° just outside the motor and a dot that
    // goes round with the rotor, as on the geometry and mesh views.
    const drawRotorMark = () => {
      const square = rasterWorldSquare(raster?.viewBox ?? prepared?.viewBox ?? '');
      const context = canvas.getContext('2d');
      if (rotorMarkDeg === null || !square || !context) return;
      const pixelRatio = canvas.width / Math.max(1, canvasSize.width);
      const drawSize = Math.min(canvas.width, canvas.height) * fitScale * navigation.scale;
      const worldScale = drawSize / square.size;
      const originX = (canvas.width - drawSize) / 2 + navigation.pan.x * pixelRatio - square.left * worldScale;
      const originY = (canvas.height - drawSize) / 2 + navigation.pan.y * pixelRatio - square.top * worldScale;
      // The plot pads the motor by 2.5% of its size on each side.
      const radius = (square.size / 1.05 / 2) * worldScale;
      const at = (distance: number, angleDeg: number): [number, number] => {
        const angle = ((angleDeg + navigation.rotationDeg) * Math.PI) / 180;
        return [originX + distance * Math.cos(angle), originY + distance * Math.sin(angle)];
      };
      context.save();
      context.setTransform(1, 0, 0, 1, 0, 0);
      const [tickFromX, tickFromY] = at(radius + 5 * pixelRatio, 0);
      const [tickToX, tickToY] = at(radius + 19 * pixelRatio, 0);
      context.beginPath();
      context.moveTo(tickFromX, tickFromY);
      context.lineTo(tickToX, tickToY);
      context.strokeStyle = 'rgba(148, 163, 184, 0.7)';
      context.lineWidth = 1.5 * pixelRatio;
      context.lineCap = 'round';
      context.stroke();
      const [dotX, dotY] = at(radius + 12 * pixelRatio, rotorMarkDeg);
      context.beginPath();
      context.arc(dotX, dotY, 4 * pixelRatio, 0, Math.PI * 2);
      context.fillStyle = '#fbbf24';
      context.shadowColor = 'rgba(251, 191, 36, 0.8)';
      context.shadowBlur = 6 * pixelRatio;
      context.fill();
      context.shadowBlur = 0;
      context.strokeStyle = 'rgba(8, 10, 14, 0.9)';
      context.lineWidth = pixelRatio;
      context.stroke();
      context.restore();
    };
    // Phases: the coils and their ⊙ / ⊗ over the field, through the same
    // transform the field is drawn with, at screen size.
    const drawPhases = () => {
      const context = canvas.getContext('2d');
      const square = rasterWorldSquare(raster?.viewBox ?? prepared?.viewBox ?? '');
      if (!phasesShown || !phases || !context || !square) return;
      const pixelRatio = canvas.width / Math.max(1, canvasSize.width);
      const drawSize = Math.min(canvas.width, canvas.height) * fitScale * navigation.scale;
      const worldScale = drawSize / square.size;
      const panX = navigation.pan.x * pixelRatio;
      const panY = navigation.pan.y * pixelRatio;
      const pivotX = canvas.width / 2 + panX;
      const pivotY = canvas.height / 2 + panY;
      const toCanvas = new DOMMatrix()
        .translateSelf(pivotX, pivotY)
        .rotateSelf(navigation.rotationDeg)
        .translateSelf(-pivotX, -pivotY)
        .multiply(new DOMMatrix([
          worldScale,
          0,
          0,
          worldScale,
          (canvas.width - drawSize) / 2 + panX - square.left * worldScale,
          (canvas.height - drawSize) / 2 + panY - square.top * worldScale,
        ]));
      drawCoilPhases(context, toCanvas, pixelRatio, coilOutlines, coilMarks, phases);
    };
    draw();
    drawPhases();
    drawRotorMark();
  }, [
    canvasSize,
    colorRangeMode,
    highResolutionPlot,
    fieldLineDensity,
    fitScale,
    navigation.pan.x,
    navigation.pan.y,
    navigation.scale,
    navigation.rotationDeg,
    overlay,
    overlayPrepared,
    phases,
    phasesShown,
    coilMarks,
    coilOutlines,
    prepared,
    primaryTone,
    raster,
    rotorMarkDeg,
    showFieldLines,
    showHeatmap,
    showMesh,
  ]);

  const hasHeatmap = raster ? true : prepared?.heatBucketCounts.some((count) => count > 0) ?? false;
  const hasMesh = Boolean(raster?.mesh || (prepared?.triangleCount ?? 0) > 0);
  const hasFieldLines = raster ? raster.contourSegmentCount > 0 : prepared?.hasArrows ?? false;
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

  // Phases: the Geometry view's drive panel on the left, wired into the motor,
  // which is fitted in what is left on the right (phaseDriveFrame). The field
  // box itself narrows, so the view's zoom, probe and magnifier are unchanged.
  const driveCanvasRef = useRef<HTMLCanvasElement>(null);
  const [plotSize, setPlotSize] = useState<{ width: number; height: number } | null>(null);
  useLayoutEffect(() => {
    const root = plotRootRef.current;
    if (!phasesShown || !root) {
      setPlotSize(null);
      return undefined;
    }
    const measure = () => setPlotSize((current) => (
      current?.width === root.clientWidth && current?.height === root.clientHeight
        ? current
        : { width: root.clientWidth, height: root.clientHeight }
    ));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    return () => observer.disconnect();
  }, [phasesShown]);
  const driveFrame = useMemo(() => (
    phasesShown && plotSize ? phaseDriveFrame(plotSize.width, plotSize.height) : null
  ), [phasesShown, plotSize]);
  const driveMarginPx = driveFrame && plotSize
    ? Math.round(driveFrame.panel.x + driveFrame.panel.width + Math.max(36, plotSize.width * 0.05))
    : 0;
  useEffect(() => {
    const overlay = driveCanvasRef.current;
    const root = plotRootRef.current;
    const box = navigation.viewportRef.current;
    if (!overlay || !root || !box || !phases || !driveFrame || !sample) return;
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    const width = root.clientWidth;
    const height = root.clientHeight;
    if (overlay.width !== Math.round(width * pixelRatio) || overlay.height !== Math.round(height * pixelRatio)) {
      overlay.width = Math.round(width * pixelRatio);
      overlay.height = Math.round(height * pixelRatio);
    }
    const context = overlay.getContext('2d');
    if (!context) return;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);
    // The motor's centre and outer edge in the plot, as the field box draws them.
    const rootBounds = root.getBoundingClientRect();
    const boxBounds = box.getBoundingClientRect();
    const boxLeft = boxBounds.left - rootBounds.left;
    const boxTop = boxBounds.top - rootBounds.top;
    const drawSize = Math.min(box.clientWidth, box.clientHeight) * fitScale * navigation.scale;
    const origin: [number, number] = [boxLeft + box.clientWidth / 2 + navigation.pan.x, boxTop + box.clientHeight / 2 + navigation.pan.y];
    // The plot pads the motor by 2.5% of its size on each side.
    const radius = drawSize / 2.1;
    // As in the Geometry view: A enters above the centre, C below, each wire with
    // one right-angle turn, staggered so that no two cross.
    const strips = phaseStrips(driveFrame.panel);
    const stripRight = driveFrame.panel.x + driveFrame.panel.width;
    const entryStep = radius * Math.sin((16 * Math.PI) / 180);
    const motorLeft = Math.max(boxLeft, origin[0] - radius);
    const lane = Math.max(6, Math.min(16, (motorLeft - stripRight) / 5));
    const wiresDrop = strips[1].y + strips[1].height / 2 <= origin[1];
    const leads = [-1, 0, 1].map((side, index) => {
      const y = origin[1] + side * entryStep;
      return {
        motor: [Math.max(boxLeft, origin[0] - Math.sqrt(Math.max(0, radius ** 2 - (side * entryStep) ** 2))), y] as [number, number],
        terminal: [motorLeft - lane * (wiresDrop ? index + 1 : 3 - index), y] as [number, number],
      };
    });
    drawPhaseDriveWired(context, driveFrame.panel, phases.drive, phases.angleDeg, sample(phases.angleDeg), leads, phases.rpm, {
      sample, history: phaseHistory,
      title: phases.pmOnly ? 'PM ONLY · NO STATOR CURRENT' : undefined,
    });
  }, [
    driveFrame, phases, sample, phaseHistory, fitScale, canvasSize, motorFitWidth,
    navigation.viewportRef, navigation.pan.x, navigation.pan.y, navigation.scale,
  ]);

  // Every hook is above this line, so a plot that has no data yet keeps the same hooks.
  if (!prepared && !raster) return null;
  const triangleCount = raster?.triangleCount ?? prepared?.triangleCount ?? 0;
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
  // Text in the turned overlay is turned back about its own anchor, so it reads level.
  const upright = (x: number, y: number) => (navigation.rotationDeg ? `rotate(${-navigation.rotationDeg} ${x} ${y})` : undefined);
  const overlayTransform = [
    overlayScale,
    0,
    0,
    overlayScale,
    overlayOffsetX,
    overlayOffsetY,
  ].join(' ');
  const axisRotorRadius = airgapInnerRadiusMm ?? 0;
  const axisStatorRadius = statorInnerRadiusMm ?? 0;
  const hasPhaseOverlay = phasesShown;
  const hasFieldAxes = fieldAxes !== null
    && leadElecDeg !== null
    && axisRotorRadius > 0
    && axisStatorRadius > axisRotorRadius;
  const polar = (radius: number, angleDeg: number) => {
    const angleRad = (angleDeg * Math.PI) / 180;
    return [radius * Math.cos(angleRad), -radius * Math.sin(angleRad)] as const;
  };
  const axisPitchDeg = 360 / axisPolePairs;
  // Use the north pole nearest the top and the stator axis paired with it.
  const arcRotorDeg = hasFieldAxes && rotorAxisDeg !== null
    ? rotorAxisDeg - Math.round((rotorAxisDeg - 90) / axisPitchDeg) * axisPitchDeg
    : 0;
  const arcSpanDeg = hasFieldAxes && leadElecDeg !== null
    ? (fieldAxes?.rotation === 'clockwise' ? -1 : 1) * leadElecDeg / axisPolePairs
    : 0;
  const arcStatorDeg = arcRotorDeg + arcSpanDeg;
  const axisArrows = hasFieldAxes ? {
    pm: fieldAxisArrowPaths(axisRotorRadius * 0.62, axisRotorRadius * 0.96, arcRotorDeg),
    stator: fieldAxisArrowPaths(axisStatorRadius * 1.04, axisStatorRadius * 1.32, arcStatorDeg),
  } : null;
  const arcRadius = axisRotorRadius * 0.5;
  const [arcX1, arcY1] = polar(arcRadius, arcRotorDeg);
  const [arcX2, arcY2] = polar(arcRadius, arcStatorDeg);
  const [arcLabelX, arcLabelY] = polar(arcRadius * 0.8, arcRotorDeg + arcSpanDeg / 2);
  // Two lines from the centre to the marked rotor arrow and the stator arrow
  // ahead of it, so the lead angle reads as an angle at the shaft.
  const [rayRotorX, rayRotorY] = polar(axisRotorRadius * 0.62, arcRotorDeg);
  const [rayStatorX, rayStatorY] = polar(axisStatorRadius * 1.04, arcStatorDeg);
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
    showFieldLines && hasFieldLines ? (overlay ? 'stator field arrows in amber and PM field arrows in cyan' : 'field-direction arrows') : null,
    showMagnets && magnetOverlay.length > 0
      ? magnetReference ? 'dimmed permanent-magnet reference geometry' : 'permanent magnets'
      : null,
    hasAirgapOverlay ? 'airgap boundary contour' : null,
    toothOverlay.length ? 'stator tooth poles in red for north and blue for south' : null,
    hasPhaseOverlay ? 'stator coils coloured by phase with the way their current flows' : null,
    hasFieldAxes ? 'stator and magnet field-axis arrows with the d and q axes' : null,
  ].filter(Boolean).join(' and ') || 'magnetic field geometry';
  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    navigation.bind.onPointerMove(event);
    if (magnifier) {
      const bounds = event.currentTarget.getBoundingClientRect();
      const x = event.clientX - bounds.left;
      const y = event.clientY - bounds.top;
      loupePointRef.current = { x, y };
      if (!hasLoupePoint) setHasLoupePoint(true);
      scheduleLoupeDraw();
    }
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
    const size = Math.min(rect.width, rect.height) * fitScale;
    const drawSize = size * navigation.scale;
    const drawX = (rect.width - drawSize) / 2 + navigation.pan.x;
    const drawY = (rect.height - drawSize) / 2 + navigation.pan.y;
    // Undo the sector turntable's rotation about the motor centre before reading the field.
    const pivotX = rect.width / 2 + navigation.pan.x;
    const pivotY = rect.height / 2 + navigation.pan.y;
    const turn = (-navigation.rotationDeg * Math.PI) / 180;
    const offsetX = event.clientX - rect.left - pivotX;
    const offsetY = event.clientY - rect.top - pivotY;
    const pointerX = pivotX + offsetX * Math.cos(turn) - offsetY * Math.sin(turn);
    const pointerY = pivotY + offsetX * Math.sin(turn) + offsetY * Math.cos(turn);
    const rasterX = ((pointerX - drawX) / drawSize) * FIELD_RASTER_SIZE;
    const rasterY = ((pointerY - drawY) / drawSize) * FIELD_RASTER_SIZE;
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
    const record = locateFieldRecord(prepared, worldX, worldY);
    if (!record || !Number.isFinite(record.value)) {
      setProbe(null);
      return;
    }
    // Still over the same element of the same frame: nothing new to show.
    if (probe?.elementIndex === record.index && probePlotRef.current === sourcePlot) return;
    probePlotRef.current = sourcePlot;
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
  const probeReadout = probe && probeDescription ? (
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
  ) : probeSlot && probeEnabled ? (
    <div className="public-field-probe is-empty" role="status">
      <strong>Field data</strong>
      <p>Hover over an element to inspect its field.</p>
    </div>
  ) : null;
  const linesLegendNote = [
    'Separate solves: in saturated steel the resultant is not their sum.',
    hasFieldAxes && leadElecDeg !== null
      ? `The two arrows from the center mark the outward flux axes of the ${axisPolePairs}-pole-pair stator and magnet fields. ${leadElecDeg >= 0 ? 'The magnets are pulled after the stator field.' : 'The stator field holds the magnets back.'}`
      : null,
    hasFieldAxes && leadElecDeg !== null ? leadAngleExplanation(leadElecDeg, axisPolePairs) : null,
    hasFieldAxes && leadElecDeg !== null && statorStrongestPolePairs !== null && statorStrongestPolePairs !== axisPolePairs
      ? `The stator's stronger ${statorStrongestPolePairs}-pole-pair part gives no steady torque and can make its arrows seem to turn the other way.`
      : null,
  ].filter(Boolean).join(' ');

  return (
    <section className={`public-field-result${overlay ? ' has-lines-legend' : ''}`} aria-label="Solved magnetic field map" ref={plotRootRef}>
      {showHeading && <div className="public-field-result-heading">
        <div>
          <strong>{title}</strong>
          <span>{subtitle}</span>
        </div>
        {showControls && <div className="public-field-result-controls" aria-label="Field map layers">
          {hasHeatmap && <button type="button" aria-pressed={showHeatmap} onClick={() => setInternalShowHeatmap((value) => !value)}>Heatmap</button>}
          {hasMesh && <button type="button" aria-pressed={showMesh} onClick={() => setInternalShowMesh((value) => !value)}>Mesh</button>}
          {hasFieldLines && <button type="button" aria-pressed={showFieldLines} onClick={() => setInternalShowFieldLines((value) => !value)}>Field arrows</button>}
        </div>}
      </div>}
      <div
        className={`public-field-result-canvas public-viewport-navigation${navigation.panEnabled ? ' is-pannable' : ''}${navigation.isDragging ? ' is-dragging' : ''}`}
        ref={navigation.viewportRef}
        style={motorFitWidth === null && !driveMarginPx
          ? undefined
          : {
            ...(motorFitWidth === null ? {} : { flex: `0 0 ${motorFitWidth.toFixed(1)}px` }),
            ...(driveMarginPx ? { marginLeft: driveMarginPx } : {}),
          }}
        {...navigation.bind}
        onPointerMove={handlePointerMove}
        onPointerLeave={() => { if (!probeSlot) setProbe(null); }}
      >
        <canvas ref={canvasRef} role="img" aria-label={`Solved ${visibleLayerLabel}`} />
        <div className="public-viewport-navigation-content public-field-overlay-navigation" style={navigation.contentStyle}>
          {((showMagnets && magnetOverlay.length > 0) || hasAirgapOverlay || toothOverlay.length > 0 || hasFieldAxes) && <svg viewBox={`0 0 ${FIELD_RASTER_SIZE} ${FIELD_RASTER_SIZE}`} className="public-field-result-overlay" style={fitScale === 1 ? undefined : { transform: `scale(${fitScale})` }} aria-hidden="true">
            <g className="public-field-result-overlay-world" transform={`matrix(${overlayTransform})`}>
              {toothOverlay.map((tooth) => (
                <g className="public-field-tooth-pole" key={tooth.index}>
                  <path d={tooth.path} fill={tooth.color} fillOpacity={tooth.opacity} />
                  {tooth.labelOpacity > 0 && (
                    <text x={tooth.x} y={tooth.y} transform={upright(tooth.x, tooth.y)} fontSize={tooth.fontSize} opacity={tooth.labelOpacity}>{tooth.label}</text>
                  )}
                </g>
              ))}
              {hasAirgapOverlay && (
                <g className="public-field-result-airgap-overlay">
                  <circle className="is-halo" cx="0" cy="0" r={airgapEdges[0]} />
                  <circle className="is-halo" cx="0" cy="0" r={airgapEdges[1]} />
                  <circle cx="0" cy="0" r={airgapEdges[0]} />
                  <circle cx="0" cy="0" r={airgapEdges[1]} />
                </g>
              )}
              {showMagnets && (
                <g className={`public-field-result-pm-overlay${magnetReference ? ' is-reference' : ''}`}>
                  {magnetOverlay.map((magnet, index) => <path d={magnet.path} className={`public-field-result-magnet is-${magnet.polarity}`} key={`magnet-${index}`} />)}
                  {showMagnetPolarityLabels && magnetOverlay.map((magnet, index) => <text x={magnet.center[0]} y={-magnet.center[1]} transform={upright(magnet.center[0], -magnet.center[1])} className="public-field-result-magnet-label" key={`magnet-label-${index}`}>{magnet.polarity === 'north' ? 'N' : 'S'}</text>)}
                </g>
              )}
              {axisArrows && (
                <g className="public-field-axes">
                  <path className="public-field-axis-ray is-pm" d={`M 0 0 L ${rayRotorX} ${rayRotorY}`} />
                  <path className="public-field-axis-q" d={`M 0 0 L ${qEndX} ${qEndY}`} />
                  <text className="public-field-axis-label is-dq" x={qLabelX} y={qLabelY} transform={upright(qLabelX, qLabelY)} style={{ fontSize: axisFontSize }}>q</text>
                  <text className="public-field-axis-label is-dq is-d" x={dLabelX} y={dLabelY} transform={upright(dLabelX, dLabelY)} style={{ fontSize: axisFontSize }}>d</text>
                  <path className="public-field-axis-ray is-stator" d={`M 0 0 L ${rayStatorX} ${rayStatorY}`} />
                  <g className="public-field-axis is-pm">
                    <path className="public-field-axis-shaft" d={axisArrows.pm.shaft} />
                    <path d={axisArrows.pm.head} />
                  </g>
                  <g className="public-field-axis is-stator">
                    <path className="public-field-axis-shaft" d={axisArrows.stator.shaft} />
                    <path d={axisArrows.stator.head} />
                  </g>
                  <path
                    className="public-field-axis-arc"
                    d={`M ${arcX1} ${arcY1} A ${arcRadius} ${arcRadius} 0 0 ${arcSpanDeg > 0 ? 0 : 1} ${arcX2} ${arcY2}`}
                  />
                  <g className="public-field-axis-help" transform={upright(arcLabelX, arcLabelY)}>
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
              onSector={navigation.sector}
              onSectorStep={navigation.sectorStep}
              onSectorGoTo={navigation.sectorGoTo}
              sectorActive={navigation.sectorActive}
              sectorAngleDeg={navigation.sectorAngleDeg}
              sectorSpanDeg={navigation.sectorSpanDeg}
            />
          );
          return navigationSlot ? createPortal(zoomControls, navigationSlot) : zoomControls;
        })()}
        {hasPhaseOverlay && (
          <div className="public-winding-key public-field-phase-key" aria-label="Winding phase and current direction legend">
            <span><i className="phase-a" />A</span>
            <span><i className="phase-b" />B</span>
            <span><i className="phase-c" />C</span>
            <span className="direction-key">⊙ out · ⊗ in</span>
          </div>
        )}
        {magnifier && (
          <ViewportMagnifier slot={magnifierSlot} canvasRef={loupeCanvasRef} hasPoint={hasLoupePoint} magnification={LOUPE_MAGNIFICATION} label="Field magnifier" />
        )}
        {!probeSlot && probeReadout}
      </div>
      {driveFrame && <canvas ref={driveCanvasRef} className="public-field-drive-panel" role="img"
        aria-label={`Recorded phase currents${phaseHistory?.gaps.length ? '. Gaps: Outside solved sweep' : ''}`} />}
      {probeSlot && createPortal(probeReadout, probeSlot)}
      {overlay ? (
        // One line above the view: the two arrow colours and the stator lead.
        // The longer notes are its tooltip, not text over the motor.
        <div className="public-field-lines-legend" aria-label="Field-arrow colours" title={linesLegendNote}>
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
        <div className="public-field-scale">
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
          <div className="public-field-scale-values">
            <span className="is-min">{legendLabel(legendScale.minB)}</span>
            <span className="is-mid">{legendLabel((legendScale.minB + legendScale.maxB) / 2)}</span>
            <span className="is-max">{legendLabel(legendScale.maxB)}</span>
          </div>
        </div>
        {legendScale.overAboveT !== null && (
          <span
            className="is-over"
            title="Elements above 2.0 T. Sharp corners can show local peaks this high; the probe gives the exact value."
          >
            <b aria-hidden="true" />&gt; {legendScale.overAboveT.toFixed(1)} T
          </span>
        )}
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
        {showStatistics && <small>{triangleCount.toLocaleString()} solved elements</small>}
      </div>}
    </section>
  );
}
