import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// Every rotor position of a sector solve is cut where a tooth and a pole gap are nearest
// each other, so the solved sector steps round as the rotor turns. The Mesh view looks up
// the cut for the angle it shows in the table the backend sends with the mesh.
const { sectorCutAt } = await importTypeScriptModule(new URL('../src/public/sectorCuts.ts', import.meta.url));

// The 14p/12s drone outrunner, a half sector: the cut steps every 360/lcm(12, 14) = 4.29 degrees
// (first two and last two of its 84 entries, from backend/sector_geometry.py sector_cuts_by_turn).
const cuts = [
  { turn_from_deg: 0, stator_cut_deg: 15, rotor_cut_deg: 12.857142857 },
  { turn_from_deg: 4.285714286, stator_cut_deg: 45, rotor_cut_deg: 38.571428571 },
  { turn_from_deg: 351.428571429, stator_cut_deg: 315, rotor_cut_deg: 321.428571429 },
  { turn_from_deg: 355.714285714, stator_cut_deg: 345, rotor_cut_deg: 347.142857143 },
];

// At the meshed angle: the mesh's own cut.
assert.equal(sectorCutAt(cuts, 0).stator_cut_deg, 15);
// A positive view angle turns the rotor clockwise, as a sweep does: 2.14 degrees on, the
// stator is cut one tooth back (345) and the rotor cut, turned with it, meets it there.
const first = sectorCutAt(cuts, 2.142857143);
assert.equal(first.stator_cut_deg, 345);
assert.ok(Math.abs(first.rotor_cut_deg - 2.142857143 - 345) < 1e-6);
// Exactly where the cut steps (sweeps stop there), the new cut applies.
assert.equal(sectorCutAt(cuts, 4.285714286).stator_cut_deg, 345);
assert.equal(sectorCutAt(cuts, 6.428571429).stator_cut_deg, 315);
// Turned the other way, and a whole turn on, the table wraps.
assert.equal(sectorCutAt(cuts, -5).stator_cut_deg, 45);
assert.equal(sectorCutAt(cuts, 360 + 2.142857143).stator_cut_deg, 345);
// No table (a full-motor mesh, or an older backend): nothing to show.
assert.equal(sectorCutAt(undefined, 10), null);
assert.equal(sectorCutAt([], 10), null);

console.log('sector cut tests passed');
