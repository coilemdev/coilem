import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// N / S letters on magnets: a spot inside the magnet, and its thickness, for the
// thin arcs of an SPM rotor, a 2-pole arc and a tilted IPM block.
const { polygonLabelSpot } = await importTypeScriptModule(new URL('../src/public/canvasLabels.ts', import.meta.url));

const center = [400, 300];
const arc = (inner, outer, fromDeg, toDeg, steps = 24) => {
  const at = (radius, deg) => [center[0] + radius * Math.cos((deg * Math.PI) / 180), center[1] - radius * Math.sin((deg * Math.PI) / 180)];
  const out = Array.from({ length: steps + 1 }, (_, i) => at(outer, fromDeg + ((toDeg - fromDeg) * i) / steps));
  const back = Array.from({ length: steps + 1 }, (_, i) => at(inner, toDeg - ((toDeg - fromDeg) * i) / steps));
  return [...out, ...back];
};
const polar = ({ x, y }) => ({ radius: Math.hypot(x - center[0], y - center[1]), deg: (Math.atan2(center[1] - y, x - center[0]) * 180) / Math.PI });

// An 8-pole SPM magnet: 32 degrees of a 51-55 px band.
const spm = polygonLabelSpot(arc(51 * 4, 55 * 4, 29, 61), center);
assert.ok(polar(spm).radius > 51 * 4 && polar(spm).radius < 55 * 4, `inside the band: ${polar(spm).radius}`);
assert.ok(Math.abs(polar(spm).deg - 45) < 0.5, 'on the bisector');
// 2 x area / perimeter is t * L / (L + t): a little under the 16 px band for a short arc.
assert.ok(spm.thickness > 0.85 * 16 && spm.thickness <= 16, `band thickness: ${spm.thickness}`);

// A 2-pole magnet's arc is so wide its centroid leaves the band: the polar mean holds.
const wide = polygonLabelSpot(arc(150, 166, 15, 165), center);
assert.ok(polar(wide).radius > 150 && polar(wide).radius < 166, `wide arc: inside the band (${polar(wide).radius})`);
assert.ok(Math.abs(polar(wide).deg - 90) < 0.5, 'wide arc: on the bisector');

// A tilted IPM block, off centre: its centre, and its short side as the thickness.
const block = (cx, cy, length, width, deg) => {
  const c = Math.cos((deg * Math.PI) / 180);
  const s = Math.sin((deg * Math.PI) / 180);
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([u, v]) => [cx + (u * length * c) / 2 - (v * width * s) / 2, cy + (u * length * s) / 2 + (v * width * c) / 2]);
};
const v = polygonLabelSpot(block(520, 220, 90, 14, 35), center);
assert.ok(Math.abs(v.x - 520) < 1e-6 && Math.abs(v.y - 220) < 1e-6, 'block: its centre');
assert.ok(Math.abs(v.thickness - (90 * 14) / (90 + 14)) < 1e-6, 'block: 2 x area / perimeter');
assert.ok(Math.abs(v.span - (90 + 14)) < 1e-6, 'block: half the perimeter');

// Degenerate input stays finite.
assert.deepEqual(polygonLabelSpot([[1, 1], [2, 2]], center), { x: 400, y: 300, thickness: 0, span: 0 });

console.log('canvas label checks passed');
