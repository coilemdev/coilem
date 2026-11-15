import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The Halbach 3D viewers open with the whole array in view (#265): the camera
// pulls back along its default direction until every framing point projects
// inside the canvas, with a margin, at the canvas's own aspect ratio.
const {
  HALBACH_3D_FRAME_FILL,
  halbachBoxFramePoints,
  halbachCameraFitDistance,
  halbachCylinderFramePoints,
} = await importTypeScriptModule(new URL('../src/public/halbach/cameraFit.ts', import.meta.url));

const close = (actual, expected, tolerance = 1e-9) => assert.ok(
  Math.abs(actual - expected) <= tolerance,
  `expected ${expected}, got ${actual}`,
);

// Straight on, a 90 degree view and no margin: a point h above the target fits
// at distance h; one w to the side fits at w / aspect; depth adds directly.
const straight = { direction: [0, 0, 1], up: [0, 1, 0], fovDeg: 90, aspect: 1, fill: 1 };
close(halbachCameraFitDistance([[0, 20, 0]], straight), 20);
close(halbachCameraFitDistance([[40, 0, 0]], { ...straight, aspect: 2 }), 20);
close(halbachCameraFitDistance([[0, 20, 5]], straight), 25);
// The margin pulls back in proportion: filling 80% of the half-view needs 1/0.8 the distance.
close(halbachCameraFitDistance([[0, 20, 0]], { ...straight, fill: 0.8 }), 25);
assert.equal(HALBACH_3D_FRAME_FILL, 0.8);

// Where each framing point lands, as a share of the half-view (1 = the edge).
function projectedExtent(points, frame, distance) {
  const norm = (v) => v.map((value) => value / Math.hypot(...v));
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const back = norm(frame.direction);
  const right = norm(cross(frame.up, back));
  const up = cross(back, right);
  const tan = Math.tan((frame.fovDeg * Math.PI) / 360);
  let horizontal = 0;
  let vertical = 0;
  for (const point of points) {
    const depth = distance - dot(point, back);
    assert.ok(depth > 0, 'every point is in front of the camera');
    horizontal = Math.max(horizontal, Math.abs(dot(point, right)) / (depth * tan * frame.aspect));
    vertical = Math.max(vertical, Math.abs(dot(point, up)) / (depth * tan));
  }
  return { horizontal, vertical };
}

// The default cylindrical array (25 / 50 mm radii, 100 mm long) in the viewer's
// three-quarter view. A 1500 x 900 window gives a wide viewer, where the height
// sets the distance: the ring fills 80% of the half-height and none of it is cut
// off. The old fixed offset (2.15, -2.15, 1.55) x 50 mm put the camera 171 mm away.
const cylinder = halbachCylinderFramePoints(50, -50, 51);
const cylinderView = { direction: [2.15, -2.15, 1.55], up: [0, 0, 1], fovDeg: 38 };
for (const aspect of [0.5, 0.8, 1, 1.6, 2.4]) {
  const frame = { ...cylinderView, aspect };
  const distance = halbachCameraFitDistance(cylinder, frame);
  const extent = projectedExtent(cylinder, frame, distance);
  close(Math.max(extent.horizontal, extent.vertical), HALBACH_3D_FRAME_FILL, 1e-6);
  assert.ok(distance > 171, `cylinder at aspect ${aspect} sits further back than the old 171 mm`);
}
const wideCylinder = halbachCameraFitDistance(cylinder, { ...cylinderView, aspect: 1.6 });
const narrowCylinder = halbachCameraFitDistance(cylinder, { ...cylinderView, aspect: 0.5 });
assert.ok(narrowCylinder > wideCylinder * 1.3, 'a narrow viewer pulls the camera further back');
// The rim polygon is circumscribed: no point of the true rim lies outside it.
assert.ok(cylinder.every(([x, y]) => Math.hypot(x, y) >= 50));
assert.equal(cylinder.length, 96);

// The default linear array (16 blocks of 10 mm: 160 mm long, 100 mm deep, probes
// 5 mm off a 10 mm row) on the tabletop view. Long and thin, it is set by the
// width in a narrow viewer and both ends stay inside the view at every aspect.
const linear = halbachBoxFramePoints([-80, -50, -20], [80, 51.5, 20]);
assert.equal(linear.length, 8);
const linearView = { direction: [0.45, 1.75, 0.9], up: [0, 1, 0], fovDeg: 38 };
for (const aspect of [0.5, 1, 1.6, 2.4]) {
  const frame = { ...linearView, aspect };
  const distance = halbachCameraFitDistance(linear, frame);
  const extent = projectedExtent(linear, frame, distance);
  close(Math.max(extent.horizontal, extent.vertical), HALBACH_3D_FRAME_FILL, 1e-6);
  assert.ok(extent.horizontal <= HALBACH_3D_FRAME_FILL + 1e-9);
  assert.ok(extent.vertical <= HALBACH_3D_FRAME_FILL + 1e-9);
}
const narrowLinear = halbachCameraFitDistance(linear, { ...linearView, aspect: 0.5 });
const wideLinear = halbachCameraFitDistance(linear, { ...linearView, aspect: 1.6 });
assert.ok(narrowLinear > wideLinear);
assert.equal(
  projectedExtent(linear, { ...linearView, aspect: 0.5 }, narrowLinear).horizontal.toFixed(6),
  HALBACH_3D_FRAME_FILL.toFixed(6),
);

console.log('halbach camera fit tests passed');
