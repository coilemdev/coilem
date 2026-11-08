export interface FieldViewportTriangle {
  points: readonly [
    readonly [number, number],
    readonly [number, number],
    readonly [number, number],
  ];
  value: number | null;
}

export interface FieldViewportTransform {
  scale: number;
  translateX: number;
  translateY: number;
  canvasWidth: number;
  canvasHeight: number;
  /** The view turned by this angle about (pivotX, pivotY) on the canvas (the sector turntable). */
  rotationRad?: number;
  pivotX?: number;
  pivotY?: number;
}

export interface FieldViewportRange {
  minB: number;
  maxB: number;
  elementCount: number;
}

export function fieldRangeForViewport(
  triangles: readonly FieldViewportTriangle[],
  transform: FieldViewportTransform,
): FieldViewportRange | null {
  const {
    scale,
    translateX,
    translateY,
    canvasWidth,
    canvasHeight,
  } = transform;
  if (
    !Number.isFinite(scale)
    || scale <= 0
    || !Number.isFinite(translateX)
    || !Number.isFinite(translateY)
    || !Number.isFinite(canvasWidth)
    || !Number.isFinite(canvasHeight)
    || canvasWidth <= 0
    || canvasHeight <= 0
  ) return null;

  // A turned view covers a turned rectangle; bound the canvas corners turned back,
  // which keeps every visible element and a few at the corners.
  const turn = -(transform.rotationRad ?? 0);
  const pivotX = transform.pivotX ?? canvasWidth / 2;
  const pivotY = transform.pivotY ?? canvasHeight / 2;
  const corners = ([[0, 0], [canvasWidth, 0], [0, canvasHeight], [canvasWidth, canvasHeight]] as const).map(([x, y]) => {
    if (!turn) return [x, y];
    const dx = x - pivotX;
    const dy = y - pivotY;
    return [pivotX + dx * Math.cos(turn) - dy * Math.sin(turn), pivotY + dx * Math.sin(turn) + dy * Math.cos(turn)];
  });
  const viewport = {
    minX: (Math.min(...corners.map(([x]) => x)) - translateX) / scale,
    maxX: (Math.max(...corners.map(([x]) => x)) - translateX) / scale,
    minY: (Math.min(...corners.map(([, y]) => y)) - translateY) / scale,
    maxY: (Math.max(...corners.map(([, y]) => y)) - translateY) / scale,
  };
  let minB = Number.POSITIVE_INFINITY;
  let maxB = Number.NEGATIVE_INFINITY;
  let elementCount = 0;

  triangles.forEach(({ points, value }) => {
    if (!Number.isFinite(value)) return;
    const xs = points.map((point) => point[0]);
    const ys = points.map((point) => -point[1]);
    const triangleMinX = Math.min(...xs);
    const triangleMaxX = Math.max(...xs);
    const triangleMinY = Math.min(...ys);
    const triangleMaxY = Math.max(...ys);
    const intersects = triangleMaxX >= viewport.minX
      && triangleMinX <= viewport.maxX
      && triangleMaxY >= viewport.minY
      && triangleMinY <= viewport.maxY;
    if (!intersects) return;
    minB = Math.min(minB, value ?? 0);
    maxB = Math.max(maxB, value ?? 0);
    elementCount += 1;
  });

  return elementCount > 0 ? { minB, maxB, elementCount } : null;
}
