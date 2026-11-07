import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The parametric 3D view's stator radii (stator3dRadii.ts), checked against the
// geometry the backend draws.
const { shoeShoulderFraction, stator3dRadii } = await importTypeScriptModule(
  new URL('../src/public/stator3dRadii.ts', import.meta.url),
);

const outer = (stator, rotorOd = 35) => ({
  rotor_layout: 'outer',
  stator: { OD_mm: 28, ID_mm: 10, yoke_thickness_mm: 2, ...stator },
  rotor: { OD_mm: rotorOd },
});

// The starter outrunner: 28 mm OD, 10 mm hub bore, 2 mm yoke.
const starter = stator3dRadii(outer({}));
assert.deepEqual(
  [starter.statorInnerRadius, starter.yokeInnerRadius, starter.yokeOuterRadius, starter.outerRadius],
  [14, 7, 5, 17.5],
);
assert.equal(starter.coilRootRadius, 7, 'a deep slot winds its coil from the slot bottom');

// Review on #217: a 24 mm hub bore with a 1 mm yoke puts the yoke between 12 and
// 13 mm and leaves 1 mm slots. The 2 mm tooth floor used to put the slot bottom
// at 12 mm, on the hub, so the yoke was drawn as a zero-width ring.
const shallow = stator3dRadii(outer({ ID_mm: 24, yoke_thickness_mm: 1 }));
assert.equal(shallow.yokeOuterRadius, 12);
assert.equal(shallow.yokeInnerRadius, 13, 'the yoke keeps its configured 1 mm');
assert.equal(shallow.statorInnerRadius, 14);
// The drawn coil still gets 2 mm of tooth, reaching back into the yoke.
assert.equal(shallow.coilRootRadius, 12);

// Inner rotors keep the values they always had, floor included.
const inner = stator3dRadii({ rotor_layout: 'inner', stator: { OD_mm: 100, ID_mm: 60, yoke_thickness_mm: 8 }, rotor: { OD_mm: 58 } });
assert.deepEqual(
  [inner.outerRadius, inner.statorInnerRadius, inner.yokeInnerRadius, inner.yokeOuterRadius, inner.coilRootRadius],
  [50, 30, 42, 50, 42],
);
const innerShallow = stator3dRadii({ stator: { OD_mm: 64, ID_mm: 60, yoke_thickness_mm: 1.5 }, rotor: { OD_mm: 58 } });
assert.equal(innerShallow.yokeInnerRadius, 32);

// Review on #217: the shoe shoulder's place along the tooth, 0 at the gap face and
// 1 at the yoke. An outer stator's radii fall from the gap to the yoke; a 1.5 mm
// shoe on the starter's 7 mm tooth sits 1.5/7 of the way, not at 0.
assert.ok(Math.abs(shoeShoulderFraction(14, 12.5, 7) - 1.5 / 7) < 1e-12);
// Inner stators are unchanged: the same 1.5 mm shoe on a 12 mm tooth.
assert.ok(Math.abs(shoeShoulderFraction(30, 31.5, 42) - 1.5 / 12) < 1e-12);
assert.equal(shoeShoulderFraction(14, 14, 7), 0);
assert.equal(shoeShoulderFraction(14, 6, 7), 1);

console.log('stator 3D radii checks passed');
