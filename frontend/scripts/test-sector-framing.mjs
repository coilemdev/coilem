import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// Thin-ring motors (outrunners whose active ring is the outer band of the circle)
// open zoomed on the top of the ring; everything else keeps the whole-motor fit.
const { THIN_RING_MAX_FRACTION, isThinRing, outerRotorRing, ringKey, sectorView } = await importTypeScriptModule(
  new URL('../src/public/sectorFraming.ts', import.meta.url),
);

const outer = (statorId, rotorOd) => ({ rotor_layout: 'outer', stator: { ID_mm: statorId }, rotor: { OD_mm: rotorOd } });

// The 36s/40p robot-joint outrunner: 58.5 mm hub bore, 84 mm rotor OD, a 30% ring.
const joint = outerRotorRing(outer(58.5, 84));
assert.deepEqual(joint, { innerMm: 29.25, outerMm: 42 });
assert.ok(isThinRing(joint));
assert.equal(ringKey(joint), '29.250:42.000');
// The starter outrunner (10 mm hub, 35 mm rotor) is a thick ring: the whole motor already reads well.
assert.equal(isThinRing(outerRotorRing(outer(10, 35))), false);
assert.equal(ringKey(outerRotorRing(outer(10, 35))), null);
assert.equal(THIN_RING_MAX_FRACTION, 0.5);
// Inner rotors have no ring to frame.
assert.equal(outerRotorRing({ rotor_layout: 'inner', stator: { ID_mm: 60 }, rotor: { OD_mm: 54 } }), null);
assert.equal(outerRotorRing({ stator: { ID_mm: 60 }, rotor: { OD_mm: 54 } }), null);

// A 400 px square view fitting the 42 mm ring radius at 190 px: the 12.75 mm
// thickness is 57.7 px, so 70% of the height needs about 4.85x, and the pan brings
// the ring's top (35.6 mm, 161 px above the origin) to the middle.
const midPx = 35.625 * 190 / 42;
const view = sectorView(joint, 400, 400, 190);
assert.ok(Math.abs(view.scale - (0.7 * 400) / (12.75 * 190 / 42)) < 1e-9);
assert.ok(Math.abs(view.pan.x) < 1e-9);
assert.ok(Math.abs(view.pan.y - view.scale * midPx) < 1e-9);
// Each step turns about three quarters of the visible arc, so neighbouring views overlap.
assert.ok(Math.abs(view.stepDeg - (0.75 * (400 / view.scale / midPx) * 180) / Math.PI) < 1e-9);
// A quarter turn clockwise looks at the ring's right-hand side: the content pans left.
const right = sectorView(joint, 400, 400, 190, 90);
assert.equal(right.scale, view.scale);
assert.ok(Math.abs(right.pan.x + view.scale * midPx) < 1e-9 && Math.abs(right.pan.y) < 1e-9);
const bottom = sectorView(joint, 400, 400, 190, 180);
assert.ok(Math.abs(bottom.pan.y + view.scale * midPx) < 1e-9);
// The zoom stays between 1.5x and 6x, and a step between 5 and 90 degrees.
assert.equal(sectorView(joint, 400, 4000, 190).scale, 6);
assert.equal(sectorView({ innerMm: 21, outerMm: 42 }, 100, 100, 190).scale, 1.5);
assert.equal(sectorView({ innerMm: 21, outerMm: 42 }, 4000, 100, 190).stepDeg, 90);
assert.equal(sectorView(joint, 1, 4000, 190).stepDeg, 5);
// No sector for a thick ring, an empty view or no ring.
assert.equal(sectorView(outerRotorRing(outer(10, 35)), 400, 400, 190), null);
assert.equal(sectorView(joint, 400, 0, 190), null);
assert.equal(sectorView(null, 400, 400, 190), null);

console.log('sector framing tests passed');
