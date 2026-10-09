/// <reference lib="webworker" />

type RasterSource = 'resultant' | 'pm' | 'armature';

interface RasterRequest {
  requestId: number;
  apiBase: string;
  artifactId: string;
  source: RasterSource;
}

interface FieldPlotPayload {
  nodes_mm: number[][];
  triangles: number[][];
  element_b_mag_t: number[];
  contour_levels: Array<{
    segments_mm: number[][];
    segment_b_mag_t?: number[];
    segment_bx_t?: number[];
    segment_by_t?: number[];
  }>;
  noload_plot?: FieldPlotPayload | null;
}

const RASTER_SIZE = 768;
const DIRECTION_CUE_TARGET = 32;
const MEDIUM_CONTOUR_LEVEL_STRIDE = 2;
const HEAT_COLORS = ['#142a61', '#1855a7', '#1b8eb7', '#2ab673', '#a7c83a', '#f1c232', '#f58b24', '#dc3d3d'];

function validTriangle(plot: FieldPlotPayload, triangle: number[]): number[][] | null {
  if (!Array.isArray(triangle) || triangle.length !== 3) return null;
  const points = triangle.map((nodeIndex) => plot.nodes_mm[nodeIndex]);
  return points.every((point) => Array.isArray(point) && point.length >= 2 && point.slice(0, 2).every(Number.isFinite))
    ? points
    : null;
}

function addTriangle(context: OffscreenCanvasRenderingContext2D, points: number[][]): void {
  context.moveTo(points[0][0], -points[0][1]);
  context.lineTo(points[1][0], -points[1][1]);
  context.lineTo(points[2][0], -points[2][1]);
  context.closePath();
}

function configuredCanvas(
  viewBox: [number, number, number, number],
): { canvas: OffscreenCanvas; context: OffscreenCanvasRenderingContext2D } {
  const canvas = new OffscreenCanvas(RASTER_SIZE, RASTER_SIZE);
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Offscreen canvas rendering is unavailable.');
  const [viewX, viewY, viewWidth, viewHeight] = viewBox;
  const scale = Math.min(RASTER_SIZE / viewWidth, RASTER_SIZE / viewHeight);
  const offsetX = (RASTER_SIZE - viewWidth * scale) / 2;
  const offsetY = (RASTER_SIZE - viewHeight * scale) / 2;
  context.setTransform(scale, 0, 0, scale, offsetX - viewX * scale, offsetY - viewY * scale);
  return { canvas, context };
}

function rasterize(plot: FieldPlotPayload) {
  const xValues = plot.nodes_mm.map((node) => node[0]).filter(Number.isFinite);
  const yValues = plot.nodes_mm.map((node) => node[1]).filter(Number.isFinite);
  if (xValues.length === 0 || yValues.length === 0) throw new Error('The solved field frame has no drawable nodes.');
  const minX = Math.min(...xValues);
  const maxX = Math.max(...xValues);
  const minY = Math.min(...yValues);
  const maxY = Math.max(...yValues);
  const width = Math.max(maxX - minX, 1);
  const height = Math.max(maxY - minY, 1);
  const padding = Math.max(width, height) * 0.025;
  const viewBox: [number, number, number, number] = [
    minX - padding,
    -maxY - padding,
    width + padding * 2,
    height + padding * 2,
  ];
  const values = plot.element_b_mag_t.filter(Number.isFinite);
  const minB = values.length ? Math.min(...values) : 0;
  const maxB = values.length ? Math.max(...values) : 0;
  const span = Math.max(maxB - minB, Number.EPSILON);
  const buckets = Array.from({ length: HEAT_COLORS.length }, () => [] as number[]);
  let triangleCount = 0;
  plot.triangles.forEach((triangle, index) => {
    if (!validTriangle(plot, triangle)) return;
    triangleCount += 1;
    const value = plot.element_b_mag_t[index];
    if (!Number.isFinite(value)) return;
    const bucket = Math.min(HEAT_COLORS.length - 1, Math.floor(((value - minB) / span) * HEAT_COLORS.length));
    buckets[bucket].push(index);
  });

  const baseLayer = configuredCanvas(viewBox);
  baseLayer.context.beginPath();
  plot.triangles.forEach((triangle) => {
    const points = validTriangle(plot, triangle);
    if (points) addTriangle(baseLayer.context, points);
  });
  baseLayer.context.fillStyle = '#202733';
  baseLayer.context.fill();
  baseLayer.context.strokeStyle = 'rgba(255,255,255,.03)';
  baseLayer.context.lineWidth = 0.08;
  baseLayer.context.stroke();

  const meshLayer = configuredCanvas(viewBox);
  meshLayer.context.beginPath();
  plot.triangles.forEach((triangle) => {
    const points = validTriangle(plot, triangle);
    if (points) addTriangle(meshLayer.context, points);
  });
  meshLayer.context.strokeStyle = 'rgba(203,213,225,.42)';
  meshLayer.context.lineWidth = 0.11;
  meshLayer.context.lineJoin = 'round';
  meshLayer.context.stroke();

  const heatLayer = configuredCanvas(viewBox);
  buckets.forEach((triangleIndices, bucket) => {
    heatLayer.context.beginPath();
    triangleIndices.forEach((triangleIndex) => {
      const points = validTriangle(plot, plot.triangles[triangleIndex]);
      if (points) addTriangle(heatLayer.context, points);
    });
    heatLayer.context.fillStyle = HEAT_COLORS[bucket];
    heatLayer.context.fill();
  });

  const playbackContourLevels = plot.contour_levels.filter(
    (_, index) => index % MEDIUM_CONTOUR_LEVEL_STRIDE === 0,
  );
  const lineLayer = configuredCanvas(viewBox);
  lineLayer.context.beginPath();
  let contourSegmentCount = 0;
  playbackContourLevels.forEach((level) => {
    level.segments_mm.forEach((segment) => {
      if (segment.length < 4 || !segment.slice(0, 4).every(Number.isFinite)) return;
      lineLayer.context.moveTo(segment[0], -segment[1]);
      lineLayer.context.lineTo(segment[2], -segment[3]);
      contourSegmentCount += 1;
    });
  });
  lineLayer.context.strokeStyle = '#ffd166';
  lineLayer.context.lineWidth = 0.28;
  lineLayer.context.lineCap = 'round';
  lineLayer.context.shadowColor = 'rgba(255,145,0,.9)';
  lineLayer.context.shadowBlur = 0.45;
  lineLayer.context.stroke();

  const vectorCandidates = playbackContourLevels.flatMap((level) => (
    level.segments_mm.flatMap((segment, index) => {
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
    })
  ));
  const vectorCues = vectorCandidates.length <= DIRECTION_CUE_TARGET
    ? vectorCandidates
    : Array.from({ length: DIRECTION_CUE_TARGET }, (_, index) => (
      vectorCandidates[Math.round(index * (vectorCandidates.length - 1) / (DIRECTION_CUE_TARGET - 1))]
    ));

  return {
    base: baseLayer.canvas.transferToImageBitmap(),
    heat: heatLayer.canvas.transferToImageBitmap(),
    mesh: meshLayer.canvas.transferToImageBitmap(),
    lines: lineLayer.canvas.transferToImageBitmap(),
    viewBox: viewBox.join(' '),
    minB,
    maxB,
    triangleCount,
    contourLevelCount: playbackContourLevels.length,
    contourSegmentCount,
    vectorCues,
  };
}

self.onmessage = async (event: MessageEvent<RasterRequest>) => {
  const request = event.data;
  try {
    const response = await fetch(`${request.apiBase}/solve/field-frame/${encodeURIComponent(request.artifactId)}`);
    if (!response.ok) throw new Error(`Field frame request failed with HTTP ${response.status}.`);
    const payload = await response.json() as { field_line_frame?: FieldPlotPayload };
    const outerPlot = payload.field_line_frame;
    if (!outerPlot) throw new Error('The field frame payload is missing.');
    const selectedPlot = request.source === 'pm' ? outerPlot.noload_plot : outerPlot;
    if (!selectedPlot) throw new Error('The requested field composition is unavailable.');
    const raster = rasterize(selectedPlot);
    self.postMessage(
      { requestId: request.requestId, ok: true, raster },
      { transfer: [raster.base, raster.heat, raster.mesh, raster.lines] },
    );
  } catch (error) {
    self.postMessage({
      requestId: request.requestId,
      ok: false,
      error: error instanceof Error ? error.message : 'Field frame rasterization failed.',
    });
  }
};

export {};
