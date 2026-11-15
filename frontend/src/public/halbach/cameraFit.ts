/**
 * Default framing for the Halbach 3D viewers: how far back the camera has to
 * sit, along its fixed viewing direction, for the whole array to land inside
 * the view with a margin, whatever the viewer's width and height. Plain math
 * (no three.js) so it can be unit-tested under node.
 */

export type HalbachVec3 = readonly [number, number, number];

/**
 * Share of the half-view the array may fill on its tighter axis. 0.8 leaves a
 * tenth of the view clear on each side, so the array stays clear of the edges
 * and mostly clear of the legend and zoom chips in the corners.
 */
export const HALBACH_3D_FRAME_FILL = 0.8;

/** The landing page preview has no chips over it, so it keeps a slimmer margin. */
export const HALBACH_3D_HERO_FRAME_FILL = 0.92;

export interface HalbachCameraFrame {
  /** From the camera target towards the camera; any length. */
  direction: HalbachVec3;
  /** The camera's up vector. */
  up: HalbachVec3;
  /** Vertical field of view in degrees, as three.js PerspectiveCamera.fov. */
  fovDeg: number;
  /** Canvas width / height. */
  aspect: number;
  /** Share of the half-view the points may fill, in (0, 1]. */
  fill?: number;
}

function dot(a: HalbachVec3, b: HalbachVec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function cross(a: HalbachVec3, b: HalbachVec3): HalbachVec3 {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function normalize(a: HalbachVec3): HalbachVec3 {
  const length = Math.hypot(a[0], a[1], a[2]);
  return length > 0 ? [a[0] / length, a[1] / length, a[2] / length] : a;
}

/**
 * Smallest distance from the target, along `direction`, at which every point
 * (given relative to the camera target) projects inside the view. A point p is
 * at depth d - p·back from a camera d away, so it fits across the view when
 * |p·right| <= fill · tan(horizontal half-angle) · (d - p·back), and likewise
 * up the view; the tighter of the two sets the distance. A narrow viewer has
 * the smaller horizontal half-angle, so it pulls the camera further back.
 */
export function halbachCameraFitDistance(
  points: readonly HalbachVec3[],
  frame: HalbachCameraFrame,
): number {
  const back = normalize(frame.direction);
  const right = normalize(cross(frame.up, back));
  const up = cross(back, right);
  const fill = Math.min(1, Math.max(0.05, frame.fill ?? HALBACH_3D_FRAME_FILL));
  const aspect = Number.isFinite(frame.aspect) && frame.aspect > 0 ? frame.aspect : 1;
  const verticalTan = Math.tan((frame.fovDeg * Math.PI) / 360) * fill;
  const horizontalTan = verticalTan * aspect;
  let distance = 0;
  for (const point of points) {
    distance = Math.max(
      distance,
      dot(point, back) + Math.max(
        Math.abs(dot(point, right)) / horizontalTan,
        Math.abs(dot(point, up)) / verticalTan,
      ),
    );
  }
  return distance;
}

/**
 * Points round both end rims of a cylinder on the Z axis. The polygon is
 * circumscribed, so its outline never falls inside the true rim.
 */
export function halbachCylinderFramePoints(
  radius: number,
  zMin: number,
  zMax: number,
  steps = 48,
): HalbachVec3[] {
  const rimRadius = radius / Math.cos(Math.PI / steps);
  const points: HalbachVec3[] = [];
  for (let index = 0; index < steps; index += 1) {
    const angle = (2 * Math.PI * index) / steps;
    const x = rimRadius * Math.cos(angle);
    const y = rimRadius * Math.sin(angle);
    points.push([x, y, zMin], [x, y, zMax]);
  }
  return points;
}

/** The eight corners of an axis-aligned box. */
export function halbachBoxFramePoints(min: HalbachVec3, max: HalbachVec3): HalbachVec3[] {
  const points: HalbachVec3[] = [];
  for (const x of [min[0], max[0]]) {
    for (const y of [min[1], max[1]]) {
      for (const z of [min[2], max[2]]) points.push([x, y, z]);
    }
  }
  return points;
}
