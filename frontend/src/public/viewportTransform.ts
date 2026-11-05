/** Shared drawing and interaction coordinates for full or shifted viewports. */
export interface ViewportFrame { x: number; y: number; width: number; height: number }
export interface ViewportPoint { x: number; y: number }

export function viewportTransformOrigin(width: number, height: number, frame?: ViewportFrame): ViewportPoint {
  const box = frame ?? { x: 0, y: 0, width, height };
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

/** Pan that leaves the point beneath the pointer fixed as the scale changes. */
export function anchoredZoomPan(pan: ViewportPoint, scale: number, nextScale: number, anchor: ViewportPoint): ViewportPoint {
  const ratio = nextScale / scale;
  return { x: anchor.x - (anchor.x - pan.x) * ratio, y: anchor.y - (anchor.y - pan.y) * ratio };
}

export function fitTransform(
  points: Array<[number, number]>,
  width: number,
  height: number,
  viewportScale = 1,
  pan: [number, number] = [0, 0],
  /** Part of the canvas to fit into; the whole canvas by default. */
  frame?: ViewportFrame,
): { map: (point: [number, number]) => [number, number]; scale: number } {
  const box = frame ?? { x: 0, y: 0, width, height };
  // Fine meshes exceed the browser's function-argument limit. Accumulate
  // bounds instead of spreading every mesh node into Math.min / Math.max.
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const [x, y] of points) {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const padding = Math.min(box.width, box.height) * 0.075;
  const scale = Math.min((box.width - padding * 2) / spanX, (box.height - padding * 2) / spanY);
  const offsetX = box.x + (box.width - spanX * scale) / 2 - minX * scale;
  const offsetY = box.y + (box.height - spanY * scale) / 2 + maxY * scale;
  const { x: centerX, y: centerY } = viewportTransformOrigin(width, height, frame);
  return {
    scale: scale * viewportScale,
    map: ([x, y]) => {
      const fittedX = offsetX + x * scale;
      const fittedY = offsetY - y * scale;
      return [
        centerX + (fittedX - centerX) * viewportScale + pan[0],
        centerY + (fittedY - centerY) * viewportScale + pan[1],
      ];
    },
  };
}
