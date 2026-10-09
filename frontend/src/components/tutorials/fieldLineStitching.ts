/**
 * Marching-triangles contour stitching, shared by the 2D SVG field renderer
 * (MotorViewport) and the 3D field shell (Motor3DViewer). Both renderers work
 * from the same solved A_z contour segments: this module chains those loose
 * segments into connected, smoothed polylines so neither view draws the raw
 * "dashed" marching-triangles output.
 */

export type FieldLinePathSegment = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  bMagT?: number | null;
};

export type FieldLinePathPoint = [number, number];

type FieldLineEndpoint = {
  atStart: boolean;
  segmentIndex: number;
  x: number;
  y: number;
};

export type FieldLinePolyline = {
  /** Chaikin-smoothed points; closed loops repeat their first point at the end. */
  points: FieldLinePathPoint[];
  /** Arc length of the raw (pre-smoothing) polyline in mm. */
  lengthMm: number;
  maxRadiusMm: number;
  closed: boolean;
  /** p82 of the stitched segments' |B| in tesla, null when unsampled. */
  strengthT: number | null;
  /** Ranking score used to pick representative suppressed core loops. */
  score: number;
};

export type StitchedFieldLines = {
  /** Renderable polylines in discovery order. */
  polylines: FieldLinePolyline[];
  /** Small closed loops suppressed inside the core radius (unsorted). */
  coreLoops: FieldLinePolyline[];
};

// Stitching tolerance for chaining marching-triangle segments into one
// polyline. 1 µm was tight enough that endpoints landing on opposite sides of
// a region boundary (slot↔airgap, magnet↔airgap) — where gmsh sometimes
// duplicates nodes and the solver A_z differs by sub-µm — failed to merge,
// leaving visible "broken" hooks at the boundary. 0.1 mm is well below mesh
// element size on every fixture and reliably connects same-level fragments.
// Gmsh may duplicate material-boundary nodes, so A_z contours can end on
// opposite sides of the same physical interface with a roughly millimeter gap.
// Stitch only within the same contour level, so this closes those display gaps
// without merging different isolines.
export const FIELD_LINE_JOIN_TOLERANCE_MM = 1.5;
// Chaikin's corner-cutting passes. 3 passes ≈ 8× point count and gives a
// visibly rounded curve even on the choppy gmsh-Delaunay output. Cheap; the
// per-frame work stays well under 1 ms even on the 200 mm fixtures. Drop to
// 2 if perf ever becomes a concern; 1 is barely distinguishable from raw.
export const FIELD_LINE_SMOOTH_PASSES = 3;
// Drop polylines whose total length (in mm) is below this threshold. Marching-
// triangles emits a lot of small fragments where a contour grazes one or two
// triangles in a low-flux region or at a saddle point — they render as visible
// stubs/hooks and carry no real signal. 1.5 mm hides those reliably without
// touching real flux paths, which on these motors are tens of mm long.
export const FIELD_LINE_MIN_POLYLINE_MM = 1.5;

function formatFieldLineCoord(value: number): string {
  const fixed = value.toFixed(3);
  return fixed === '-0.000' ? '0.000' : fixed;
}

function percentileSorted(sortedValues: number[], fraction: number): number {
  if (sortedValues.length === 0) return 0;
  const index = Math.min(
    sortedValues.length - 1,
    Math.max(0, Math.floor((sortedValues.length - 1) * fraction)),
  );
  return sortedValues[index];
}

function fieldLineEndpointBucket(value: number): number {
  return Math.round(value / FIELD_LINE_JOIN_TOLERANCE_MM);
}

function addFieldLineEndpoint(
  endpointsByKey: Map<string, FieldLineEndpoint[]>,
  endpoint: FieldLineEndpoint,
) {
  const xKey = fieldLineEndpointBucket(endpoint.x);
  const yKey = fieldLineEndpointBucket(endpoint.y);
  const key = `${xKey}:${yKey}`;
  const bucket = endpointsByKey.get(key);
  if (bucket) {
    bucket.push(endpoint);
  } else {
    endpointsByKey.set(key, [endpoint]);
  }
}

function findConnectedFieldLineEndpoint(
  x: number,
  y: number,
  endpointsByKey: Map<string, FieldLineEndpoint[]>,
  visited: boolean[],
): FieldLineEndpoint | null {
  const xKey = fieldLineEndpointBucket(x);
  const yKey = fieldLineEndpointBucket(y);
  const maxDistanceSq = FIELD_LINE_JOIN_TOLERANCE_MM * FIELD_LINE_JOIN_TOLERANCE_MM;
  let best: FieldLineEndpoint | null = null;
  let bestDistanceSq = Number.POSITIVE_INFINITY;

  for (let dx = -1; dx <= 1; dx += 1) {
    for (let dy = -1; dy <= 1; dy += 1) {
      const endpoints = endpointsByKey.get(`${xKey + dx}:${yKey + dy}`);
      if (!endpoints) continue;

      for (const endpoint of endpoints) {
        if (visited[endpoint.segmentIndex]) continue;
        const distanceSq = (endpoint.x - x) ** 2 + (endpoint.y - y) ** 2;
        if (distanceSq <= maxDistanceSq && distanceSq < bestDistanceSq) {
          best = endpoint;
          bestDistanceSq = distanceSq;
        }
      }
    }
  }

  return best;
}

function extendFieldLinePolyline(
  points: FieldLinePathPoint[],
  side: 'start' | 'end',
  segments: FieldLinePathSegment[],
  endpointsByKey: Map<string, FieldLineEndpoint[]>,
  visited: boolean[],
  usedSegmentIndexes?: number[],
) {
  for (let guard = 0; guard < segments.length; guard += 1) {
    const edgePoint = side === 'start' ? points[0] : points[points.length - 1];
    const endpoint = findConnectedFieldLineEndpoint(edgePoint[0], edgePoint[1], endpointsByKey, visited);
    if (!endpoint) {
      return;
    }

    visited[endpoint.segmentIndex] = true;
    usedSegmentIndexes?.push(endpoint.segmentIndex);
    const segment = segments[endpoint.segmentIndex];
    const nextPoint: FieldLinePathPoint = endpoint.atStart
      ? [segment.x2, segment.y2]
      : [segment.x1, segment.y1];
    if (side === 'start') {
      points.unshift(nextPoint);
    } else {
      points.push(nextPoint);
    }
  }
}

// Chaikin's corner-cutting: each edge (P_i → P_{i+1}) becomes two interior
// points at 1/4 and 3/4. Closed loops stay closed; open polylines keep their
// original endpoints so flux lines that terminate at a boundary don't recede
// from it visibly. Returns the input unchanged when there's nothing to smooth.
function smoothFieldLinePolyline(
  points: FieldLinePathPoint[],
  smoothPasses: number = FIELD_LINE_SMOOTH_PASSES,
): FieldLinePathPoint[] {
  if (points.length < 3 || smoothPasses <= 0) return points;
  const first = points[0];
  const last = points[points.length - 1];
  const isClosed = Math.hypot(first[0] - last[0], first[1] - last[1]) <= FIELD_LINE_JOIN_TOLERANCE_MM;

  let current = points;
  for (let pass = 0; pass < smoothPasses; pass += 1) {
    if (current.length < 3) break;
    const next: FieldLinePathPoint[] = [];
    if (!isClosed) next.push(current[0]);
    const edges = isClosed ? current.length : current.length - 1;
    for (let i = 0; i < edges; i += 1) {
      const [x1, y1] = current[i];
      const [x2, y2] = current[(i + 1) % current.length];
      next.push([x1 * 0.75 + x2 * 0.25, y1 * 0.75 + y2 * 0.25]);
      next.push([x1 * 0.25 + x2 * 0.75, y1 * 0.25 + y2 * 0.75]);
    }
    if (isClosed) {
      next.push(next[0]);
    } else {
      next.push(current[current.length - 1]);
    }
    current = next;
  }
  return current;
}

/**
 * Chain same-level contour segments into connected polylines. Segments are
 * linked greedily by endpoint proximity (both directions from each seed),
 * tiny fragments are dropped, and small closed loops deep inside the core —
 * mesh noise around the shaft, not real flux paths — are split out into
 * `coreLoops` so callers can keep only a few representatives.
 */
export function stitchFieldLineSegments(
  segments: FieldLinePathSegment[],
  options: {
    coreLoopKeepPerLevel: number;
    suppressClosedLoopsInsideRadiusMm: number;
    smoothPasses?: number;
  },
): StitchedFieldLines {
  const usableSegments = segments.filter((segment) => (
    Number.isFinite(segment.x1)
    && Number.isFinite(segment.y1)
    && Number.isFinite(segment.x2)
    && Number.isFinite(segment.y2)
    && Math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1) > 1e-9
  ));
  if (!usableSegments.length) return { polylines: [], coreLoops: [] };

  const endpointsByKey = new Map<string, FieldLineEndpoint[]>();
  usableSegments.forEach((segment, segmentIndex) => {
    addFieldLineEndpoint(endpointsByKey, {
      atStart: true,
      segmentIndex,
      x: segment.x1,
      y: segment.y1,
    });
    addFieldLineEndpoint(endpointsByKey, {
      atStart: false,
      segmentIndex,
      x: segment.x2,
      y: segment.y2,
    });
  });

  const visited = new Array(usableSegments.length).fill(false);
  const polylines: FieldLinePolyline[] = [];
  const coreLoops: FieldLinePolyline[] = [];
  usableSegments.forEach((segment, segmentIndex) => {
    if (visited[segmentIndex]) return;

    visited[segmentIndex] = true;
    const usedSegmentIndexes = [segmentIndex];
    const points: FieldLinePathPoint[] = [
      [segment.x1, segment.y1],
      [segment.x2, segment.y2],
    ];
    extendFieldLinePolyline(points, 'end', usableSegments, endpointsByKey, visited, usedSegmentIndexes);
    extendFieldLinePolyline(points, 'start', usableSegments, endpointsByKey, visited, usedSegmentIndexes);
    if (points.length < 2) return;

    let polylineLengthMm = 0;
    let maxRadiusMm = 0;
    for (let i = 0; i < points.length; i += 1) {
      maxRadiusMm = Math.max(maxRadiusMm, Math.hypot(points[i][0], points[i][1]));
      if (i > 0) {
        polylineLengthMm += Math.hypot(
          points[i][0] - points[i - 1][0],
          points[i][1] - points[i - 1][1],
        );
      }
    }
    if (polylineLengthMm < FIELD_LINE_MIN_POLYLINE_MM) return;

    const first = points[0];
    const last = points[points.length - 1];
    const isClosed = Math.hypot(first[0] - last[0], first[1] - last[1]) <= FIELD_LINE_JOIN_TOLERANCE_MM;
    const smoothed = smoothFieldLinePolyline(points, options.smoothPasses ?? FIELD_LINE_SMOOTH_PASSES);

    const strengths: number[] = [];
    let peakBMagT = 0;
    let bMagSumT = 0;
    let bMagCount = 0;
    usedSegmentIndexes.forEach((usedIndex) => {
      const bMagT = usableSegments[usedIndex]?.bMagT;
      if (typeof bMagT === 'number' && Number.isFinite(bMagT) && bMagT > 0) {
        strengths.push(bMagT);
        peakBMagT = Math.max(peakBMagT, bMagT);
        bMagSumT += bMagT;
        bMagCount += 1;
      }
    });
    strengths.sort((a, b) => a - b);
    const avgBMagT = bMagCount > 0 ? bMagSumT / bMagCount : 0;

    const polyline: FieldLinePolyline = {
      points: smoothed,
      lengthMm: polylineLengthMm,
      maxRadiusMm,
      closed: isClosed,
      strengthT: strengths.length ? percentileSorted(strengths, 0.82) : null,
      score: polylineLengthMm * Math.max(peakBMagT, avgBMagT, 1e-6) * Math.max(maxRadiusMm, 1),
    };

    if (isClosed && maxRadiusMm < options.suppressClosedLoopsInsideRadiusMm) {
      coreLoops.push(polyline);
      return;
    }

    polylines.push(polyline);
  });

  return { polylines, coreLoops };
}

/** Polylines to actually draw: all non-suppressed paths plus the top-scored
 * core-loop representatives, in the same order the SVG renderer uses. */
export function selectRenderableFieldLinePolylines(
  stitched: StitchedFieldLines,
  coreLoopKeepPerLevel: number,
): FieldLinePolyline[] {
  const keptCoreLoops = [...stitched.coreLoops]
    .sort((a, b) => (
      b.score - a.score
      || b.lengthMm - a.lengthMm
      || b.maxRadiusMm - a.maxRadiusMm
    ))
    .slice(0, Math.max(0, coreLoopKeepPerLevel));
  return [...stitched.polylines, ...keptCoreLoops];
}

function fieldLinePolylineToPathD(points: FieldLinePathPoint[]): string {
  return (
    `M${formatFieldLineCoord(points[0][0])},${formatFieldLineCoord(points[0][1])}`
    + points
      .slice(1)
      .map(([x, y]) => `L${formatFieldLineCoord(x)},${formatFieldLineCoord(y)}`)
      .join('')
  );
}

/** SVG path wrapper over the stitcher — the 2D renderer's entry point. */
export function buildDominantFieldLinePath(
  segments: FieldLinePathSegment[],
  options: {
    coreLoopKeepPerLevel: number;
    suppressClosedLoopsInsideRadiusMm: number;
  },
): string {
  const stitched = stitchFieldLineSegments(segments, options);
  return selectRenderableFieldLinePolylines(stitched, options.coreLoopKeepPerLevel)
    .map((polyline) => fieldLinePolylineToPathD(polyline.points))
    .join('');
}
