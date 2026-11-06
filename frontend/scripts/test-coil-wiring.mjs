import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import typescript from 'typescript';

// The 3D view's tooth coils and phase wiring (coil3d.ts). It imports three by
// package name, which a data: module cannot resolve, so point it at the
// installed files.
const source = await readFile(new URL('../src/public/coil3d.ts', import.meta.url), 'utf8');
let output = typescript.transpileModule(source, {
  compilerOptions: { module: typescript.ModuleKind.ESNext, target: typescript.ScriptTarget.ES2022 },
}).outputText;
for (const specifier of ['three/examples/jsm/utils/BufferGeometryUtils.js', 'three']) {
  const resolved = import.meta.resolve(specifier);
  output = output.split(`'${specifier}'`).join(`'${resolved}'`).split(`"${specifier}"`).join(`"${resolved}"`);
}
const THREE = await import('three');
const { buildConcentratedCoil, buildWindingHarness } = await import(
  `data:text/javascript;base64,${Buffer.from(output, 'utf8').toString('base64')}`
);

// A tooth of the 14-pole / 12-slot outrunner example, wound from its root out.
const stackLength = 8;
const slotPitch = Math.PI / 6;
const coil = buildConcentratedCoil({
  boreRadius: 6.5,
  yokeInnerRadius: 12.5,
  toothHalfAngleInnerRad: 0.16,
  toothHalfAngleOuterRad: 0.13,
  slotPitchRad: slotPitch,
  stackLength,
  turnsPerCoil: 12,
});

// A coil has two leads, where the wire enters and leaves, not one shared point.
assert.ok(coil.startLead.distanceTo(coil.finishLead) > 2 * coil.wireRadius, 'start and finish leads are apart');
assert.ok(coil.startLead.z < -stackLength / 2 && coil.finishLead.z < -stackLength / 2, 'both leads leave the rear end turn');
assert.ok(coil.startLead.y < 0 && coil.finishLead.y > 0, 'the leads sit on opposite sides of the tooth');
assert.ok(coil.startLead.x < coil.finishLead.x, 'the first turn is at the inner end, the last at the outer');

// 12 slots / 14 poles, double layer: each phase is two neighbouring teeth and
// the mirror pair half a turn away.
const phases = ['A', 'A', 'B', 'B', 'C', 'C', 'A', 'A', 'B', 'B', 'C', 'C'];
const harness = buildWindingHarness({
  slotCount: 12,
  slotPitchRad: slotPitch,
  toothAngleOffsetRad: slotPitch / 2,
  phaseOfSlot: (slot) => phases[slot],
  bundleCenterRadius: coil.bundleCenterRadius,
  coilLeads: { start: coil.startLead, finish: coil.finishLead },
  stackHalf: stackLength / 2,
  axialOverhang: coil.axialOverhang,
  wireRadius: coil.wireRadius,
  yokeInnerRadius: 5,
  outerRadius: 6.5,
  blockScale: 0.35,
});

const vertices = (geometry) => {
  const position = geometry.getAttribute('position');
  return Array.from({ length: position.count }, (_, index) => new THREE.Vector3().fromBufferAttribute(position, index));
};
const nearest = (points, target) => Math.min(...points.map((point) => point.distanceTo(target)));
const leadAt = (local, tooth) => local.clone().applyAxisAngle(new THREE.Vector3(0, 0, 1), slotPitch / 2 + tooth * slotPitch);
// A tube's surface sits one wire radius off the path it follows.
const touches = (points, target) => nearest(points, target) <= harness.leadRadius * 1.1;

for (const phase of ['A', 'B', 'C']) {
  const wire = vertices(harness.phaseGeometries[phase]);
  const teeth = phases.flatMap((name, tooth) => (name === phase ? [tooth] : []));
  // One continuous wire: it reaches every coil's start and finish.
  for (const tooth of teeth) {
    assert.ok(touches(wire, leadAt(coil.startLead, tooth)), `phase ${phase} wire reaches the start of tooth ${tooth}`);
    assert.ok(touches(wire, leadAt(coil.finishLead, tooth)), `phase ${phase} wire reaches the finish of tooth ${tooth}`);
  }
  // It touches no other phase's coils.
  for (const tooth of phases.flatMap((name, index) => (name !== phase ? [index] : []))) {
    assert.ok(!touches(wire, leadAt(coil.startLead, tooth)), `phase ${phase} wire stays off tooth ${tooth}`);
  }
}
assert.ok(harness.neutralGeometry, 'the three phase ends meet at a star point');
assert.ok(harness.terminalGeometry, 'the drive leads land on a terminal block');

console.log('coil wiring checks passed');
