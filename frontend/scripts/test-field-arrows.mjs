import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The Field solution view draws small B arrows on rings about the motor axis
// (fieldArrows.ts). The server draws the same ones into the playback images;
// tests/test_public_field_playback.py checks its sampler on the same discs.
const {
  buildFieldArrowMesh,
  fieldArrowOpacity,
  fieldArrowOutline,
  fieldArrowSpacingMm,
  fieldArrowZoomStep,
  FIELD_ARROW_RING_OFFSET,
  FIELD_ARROW_SPACING_FRACTION,
  locateFieldArrowElement,
  offsetFieldArrowOutline,
  sampleFieldArrows,
} = await importTypeScriptModule(new URL('../src/public/fieldArrows.ts', import.meta.url));

/** A 64-gon disc of radius 10.2 mm as a fan about its centre, B from each element's centroid. */
function disc(bAt) {
  const sides = 64;
  const radius = 10.2;
  const nodes = [[0, 0]];
  for (let index = 0; index < sides; index += 1) {
    const angle = (2 * Math.PI * index) / sides;
    nodes.push([radius * Math.cos(angle), radius * Math.sin(angle)]);
  }
  const triangles = [];
  const bx = [];
  const by = [];
  for (let index = 0; index < sides; index += 1) {
    const triangle = [0, 1 + index, 1 + ((index + 1) % sides)];
    triangles.push(triangle);
    const cx = triangle.reduce((sum, node) => sum + nodes[node][0], 0) / 3;
    const cy = triangle.reduce((sum, node) => sum + nodes[node][1], 0) / 3;
    const [x, y] = bAt(cx, cy);
    bx.push(x);
    by.push(y);
  }
  return { nodes, triangles, bx, by };
}

const uniform = disc(() => [0.8, 0]);
const mesh = buildFieldArrowMesh(uniform.nodes, uniform.triangles, uniform.bx, uniform.by);
assert.ok(mesh, 'a disc with B indexes');
assert.equal(locateFieldArrowElement(mesh, 0.5, 0.1) >= 0, true);
assert.equal(locateFieldArrowElement(mesh, 11, 0), -1, 'outside the disc there is no element');

// Rings at 0.5, 1.5 … 9.5 mm hold round(2πr) arrows each: 314 in all. The PM
// field's rings sit at 1, 2 … 10 mm, between them: 346.
const primary = sampleFieldArrows(mesh, 1, FIELD_ARROW_RING_OFFSET.primary);
assert.equal(primary.length, 314);
assert.equal(sampleFieldArrows(mesh, 1, FIELD_ARROW_RING_OFFSET.pm).length, 346);
assert.ok(primary.every((arrow) => Math.abs(arrow.ux - 1) < 1e-12 && Math.abs(arrow.uy) < 1e-12 && Math.abs(arrow.magnitude - 0.8) < 1e-12 && arrow.opacity === 1));
assert.equal(mesh.referenceT, 0.8);
// The first ring's three arrows, and the second ring turned half a step.
assert.deepEqual(
  primary.slice(0, 3).map((arrow) => [arrow.x, arrow.y].map((value) => Number(value.toFixed(6)))),
  [[0.5, 0], [-0.25, 0.433013], [-0.25, -0.433013]],
);
assert.ok(Math.abs(Math.atan2(primary[3].y, primary[3].x) - Math.PI / 9) < 1e-9, 'ring 1 starts half a step round');
// Rings stop at the mesh's outermost node.
assert.ok(primary.every((arrow) => Math.hypot(arrow.x, arrow.y) <= 9.5 + 1e-9));

// Each arrow points along its element's B: a field circulating about the axis
// gives arrows across the radius.
const circulating = disc((x, y) => [-y * 0.2, x * 0.2]);
const circulatingMesh = buildFieldArrowMesh(circulating.nodes, circulating.triangles, circulating.bx, circulating.by);
const across = sampleFieldArrows(circulatingMesh, 1, 0.5);
assert.equal(across.length, 314);
assert.ok(across.every((arrow) => Math.abs(arrow.ux * arrow.x + arrow.uy * arrow.y) / Math.hypot(arrow.x, arrow.y) < 0.06));
assert.ok(across.every((arrow) => arrow.ux * -arrow.y + arrow.uy * arrow.x > 0), 'counter-clockwise, as B is');

// Weak field, as a share of the field's own strong |B| (its 95th-percentile
// element): no arrow below 1.5 % of it, fainter arrows below 7 % and 20 %.
assert.equal(fieldArrowOpacity(0.01, 1), 0);
assert.equal(fieldArrowOpacity(Number.NaN, 1), 0);
assert.equal(fieldArrowOpacity(0.05, 1), 0.35);
assert.equal(fieldArrowOpacity(0.15, 1), 0.65);
assert.equal(fieldArrowOpacity(1.4, 1), 1);
// The stator's field alone is weaker; it fades by its own scale, so it reads too.
assert.equal(fieldArrowOpacity(0.03, 0.2), 0.65);
assert.equal(fieldArrowOpacity(0.2, 0.2), 1);
// A field with no current or magnets shows nothing, whatever its scale.
assert.equal(fieldArrowOpacity(5e-5, 1e-3), 0);
const quiet = disc((x) => [x > 0 ? 0.01 : 1, 0]);
const quietArrows = sampleFieldArrows(buildFieldArrowMesh(quiet.nodes, quiet.triangles, quiet.bx, quiet.by), 1, 0.5);
assert.ok(quietArrows.length > 100 && quietArrows.length < 220, `only the strong half keeps arrows (${quietArrows.length})`);
assert.ok(quietArrows.every((arrow) => arrow.x < 0.6));

// Without B per element there are no arrows.
assert.equal(buildFieldArrowMesh(uniform.nodes, uniform.triangles, undefined, undefined), null);

// A visible rectangle keeps exactly the full set's arrows inside it, whether
// or not it holds the axis (the ring's angular window).
const inside = (arrow, rect) => arrow.x >= rect.minX && arrow.x <= rect.maxX && arrow.y >= rect.minY && arrow.y <= rect.maxY;
const key = (arrow) => `${arrow.x.toFixed(9)},${arrow.y.toFixed(9)}`;
for (const rect of [
  { minX: -3, maxX: 4, minY: -2, maxY: 5 },
  { minX: 2, maxX: 7, minY: 1, maxY: 4 },
  { minX: -9, maxX: -6, minY: -1, maxY: 1.5 },
  { minX: -2, maxX: 2, minY: -9.6, maxY: -7 },
  { minX: 12, maxX: 14, minY: 0, maxY: 1 },
]) {
  const expected = primary.filter((arrow) => inside(arrow, rect)).map(key).sort();
  const actual = sampleFieldArrows(mesh, 1, 0.5, rect).map(key).sort();
  assert.deepEqual(actual, expected, `rect ${JSON.stringify(rect)}`);
}

// Spacing: a share of the view, finer in half-octave steps when zoomed in.
assert.equal(FIELD_ARROW_SPACING_FRACTION.low > FIELD_ARROW_SPACING_FRACTION.medium, true);
assert.equal(FIELD_ARROW_SPACING_FRACTION.medium > FIELD_ARROW_SPACING_FRACTION.high, true);
assert.equal(fieldArrowZoomStep(0.8), 1);
assert.equal(fieldArrowZoomStep(1.2), 1);
assert.equal(fieldArrowZoomStep(Math.SQRT2), Math.SQRT2);
assert.equal(fieldArrowZoomStep(2), 2);
assert.equal(fieldArrowZoomStep(3), 2 ** 1.5);
assert.equal(fieldArrowSpacingMm(210, 'medium'), 210 / 34);
assert.equal(fieldArrowSpacingMm(210, 'medium', 2.5), 210 / 34 / 2);

// The outline points along B in drawing space (y down), its tip half a length
// ahead; the dark rim's outline encloses it with the tip pushed forward.
const outline = fieldArrowOutline({ x: 1, y: 2, ux: 0, uy: 1 }, 2);
const tip = outline[3];
assert.deepEqual(tip.map((value) => Number(value.toFixed(9))), [1, -3]);
assert.equal(outline.length, 7);
const rim = offsetFieldArrowOutline(outline, 0.1);
const area = (points) => Math.abs(points.reduce((sum, [x, y], index) => {
  const [nextX, nextY] = points[(index + 1) % points.length];
  return sum + x * nextY - nextX * y;
}, 0)) / 2;
assert.ok(area(rim) > area(outline));
assert.ok(rim[3][1] < tip[1] - 0.1, 'the rim runs past the tip');
assert.ok(Math.abs(rim[0][1] - (outline[0][1] + 0.1)) < 1e-9, 'and behind the tail');

console.log('field arrows: ring sampling, direction, fading, culling and outlines ok');
