/**
 * Where a letter goes on a drawn region, such as a magnet's N / S, in canvas px.
 */

type Point = [number, number];

function pointInPolygon([x, y]: Point, points: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/**
 * A point inside the region to centre a letter on, how thick the region is there
 * (2 x area / perimeter, which is the thickness of a thin band or block) and how
 * long (half the perimeter: a band's length plus its thickness).
 *
 * The area centroid, when it falls inside the region; a wide arc (a 2-pole
 * magnet) has its centroid off the band, so then the polar mean about `center`:
 * the arc's bisector at its mid radius.
 */
export function polygonLabelSpot(points: Point[], center: Point): { x: number; y: number; thickness: number; span: number } {
  if (points.length < 3) return { x: center[0], y: center[1], thickness: 0, span: 0 };
  let twiceArea = 0;
  let perimeter = 0;
  let cx = 0;
  let cy = 0;
  points.forEach(([x0, y0], index) => {
    const [x1, y1] = points[(index + 1) % points.length];
    const cross = x0 * y1 - x1 * y0;
    twiceArea += cross;
    cx += (x0 + x1) * cross;
    cy += (y0 + y1) * cross;
    perimeter += Math.hypot(x1 - x0, y1 - y0);
  });
  const thickness = perimeter > 0 ? Math.abs(twiceArea) / perimeter : 0;
  const span = perimeter / 2;
  if (Math.abs(twiceArea) > 1e-9) {
    const centroid: Point = [cx / (3 * twiceArea), cy / (3 * twiceArea)];
    if (pointInPolygon(centroid, points)) return { x: centroid[0], y: centroid[1], thickness, span };
  }
  let sumX = 0;
  let sumY = 0;
  let sumRadius = 0;
  for (const [x, y] of points) {
    sumX += x - center[0];
    sumY += y - center[1];
    sumRadius += Math.hypot(x - center[0], y - center[1]);
  }
  const reach = Math.hypot(sumX, sumY);
  if (reach < 1e-9) return { x: center[0], y: center[1], thickness, span };
  const radius = sumRadius / points.length;
  return { x: center[0] + (sumX / reach) * radius, y: center[1] + (sumY / reach) * radius, thickness, span };
}
