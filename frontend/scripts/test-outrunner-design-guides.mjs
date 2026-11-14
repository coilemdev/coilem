import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));
const { parseDesignFile } = await importTypeScriptModule(new URL('../src/public/designFile.ts', import.meta.url));
const { buildIssues, enteredRotorRegions, withEnteredRotor, signedBuildAirgap, designSectionOrder, designPartsOrder, fitUnbuiltParts, newBuildConfig, windingFits, fittingSlotCounts } = await importTypeScriptModule(new URL('../src/public/progressiveDesign.ts', import.meta.url));
const { buildDimensionAnnotations, designFieldDimension } = await importTypeScriptModule(new URL('../src/public/dimensionAnnotations.ts', import.meta.url));

const all = { stator: true, slots: true, teeth: true, rotor: true, magnets: true, winding: true };
const radii = (points) => points.map(([x, y]) => Math.hypot(x, y));
const outrunnerFile = await readFile(new URL('../src/public/examples/spm_outrunner_14p12s.coilem', import.meta.url), 'utf8');
const outer = parseDesignFile(outrunnerFile).config;
// The reported outrunner: a 119.4 mm stator with the rotor's inner face (Magnet Seat) inside it.
Object.assign(outer.stator, { OD_mm: 119.4 });
Object.assign(outer.rotor, { OD_mm: 119.4, ID_mm: 102.6, magnet_thickness_mm: 4, pole_count: 24, magnet_width_mm: 10 });
// An outrunner is entered rotor first, so the stator, fitted inside it, is the part to correct.
const statorIssue = buildIssues(outer, all).find((issue) => issue.label === 'Outer Diameter');
assert.equal(statorIssue?.section, 'stator', 'an overlapping outrunner names the stator Outer Diameter');
for (const text of ['The stator overlaps the rotor', "magnets' inner face is 94.6 mm across (Magnet Seat 102.6 mm minus two 4 mm magnets)", 'at most 92.6 mm (now 119.4 mm)']) {
  assert.ok(statorIssue.message.includes(text), `${text} in: ${statorIssue.message}`);
}
assert.equal(buildIssues(outer, { ...all, stator: false }).filter((issue) => issue.label === 'Outer Diameter').length, 0, 'an unentered stator is not blamed for the overlap');
const statorAt = (od) => buildIssues({ ...outer, stator: { ...outer.stator, OD_mm: od } }, all).find((issue) => issue.label === 'Outer Diameter')?.message;
assert.match(statorAt(94.5), /^Only 0\.05 mm of air gap remains\. .*at most 92\.6 mm \(now 94\.5 mm\)\.$/);
assert.match(statorAt(100), /^The stator reaches 2\.70 mm into the magnets\. /);
assert.equal(statorAt(92.6), undefined, 'the suggested size fits');
assert.ok(signedBuildAirgap(outer) < 0, 'the signed gap reports the overlap');
const ring = { ...outer, rotor: { ...outer.rotor, OD_mm: 100, ID_mm: 130 } };
assert.match(buildIssues(ring, all).find((issue) => issue.label === 'Rotor OD').message,
  /Rotor OD \(100 mm\) is the outside of the rotor ring, so it must be larger than the Magnet Seat \(130 mm\)/);
const inner = cloneDefaultConfig();
inner.rotor.OD_mm = inner.stator.ID_mm + 2;
const innerIssue = buildIssues(inner, all).find((issue) => issue.label === 'Rotor OD');
assert.match(innerIssue.message, new RegExp(`smaller than the stator bore \\(${inner.stator.ID_mm} mm\\)`));
assert.match(innerIssue.message, /or less\.$/);

// The Magnet Seat field has its own guide: the rotor's inner face.
assert.equal(designFieldDimension('rotor', 'Magnet Seat'), 'magnet-seat');
const seatGuide = buildDimensionAnnotations(outer, null).find(({ id }) => id === 'magnet-seat');
assert.equal(seatGuide.value, '102.6 mm');
assert.deepEqual(radii(seatGuide.shapes[0].kind === 'segment' ? [seatGuide.shapes[0].from, seatGuide.shapes[0].to] : []).map((r) => Number(r.toFixed(6))), [51.3, 51.3]);

// A refused preview draws the rotor and magnets as entered, over the stator they overlap.
const regions = enteredRotorRegions(outer);
const core = regions.find(({ region_type }) => region_type === 'rotor_core');
assert.deepEqual([Math.max(...radii(core.loops[0])), Math.max(...radii(core.loops[1]))].map((r) => Number(r.toFixed(6))), [59.7, 51.3]);
const magnets = regions.filter(({ region_type }) => region_type.startsWith('magnet_'));
assert.equal(magnets.length, 24);
assert.equal(magnets.filter(({ region_type }) => region_type.startsWith('magnet_n_')).length, 12);
const magnetRadii = radii(magnets[0].points);
assert.ok(Math.abs(Math.min(...magnetRadii) - 47.3) < 1e-6 && Math.abs(Math.max(...magnetRadii) - 51.3) < 1e-6, 'outer magnets sit inside the seat');
const innerMagnets = enteredRotorRegions(cloneDefaultConfig()).filter(({ region_type }) => region_type.startsWith('magnet_'));
const innerRadii = radii(innerMagnets[0].points);
const starter = cloneDefaultConfig();
assert.ok(Math.abs(Math.min(...innerRadii) - starter.rotor.OD_mm / 2) < 1e-6, 'inner magnets sit on the rotor OD');
assert.equal(enteredRotorRegions(outer, false).filter(({ region_type }) => region_type.startsWith('magnet_')).length, 0);
const stale = { regions: [
  { region_type: 'stator_tooth', points: [[0, 0]] }, { region_type: 'slot_1_(a+)', points: [[0, 0]] },
  { region_type: 'rotor_core', points: [[0, 0]] }, { region_type: 'magnet_n_0', points: [[0, 0]] },
  { region_type: 'ipm_pocket_0', points: [[0, 0]] }, { region_type: 'spm_inter_pole_air_0', points: [[0, 0]] },
  { region_type: 'airgap', points: [[0, 0]] }, { region_type: 'shaft', points: [[0, 0]] },
], metadata: {}, validation_errors: [], generation_time_ms: 0 };
const redrawn = withEnteredRotor(stale, outer);
assert.deepEqual(redrawn.regions.slice(0, 2).map(({ region_type }) => region_type), ['stator_tooth', 'slot_1_(a+)'], 'the stator stays');
assert.equal(redrawn.regions.filter(({ points }) => points.length === 1).length, 2, 'every stale rotor part is replaced');
// Design builds from the outside inward: an outrunner from its rotor.
assert.deepEqual([...designSectionOrder('outer')], ['rotor', 'stator', 'advanced', 'winding', 'materials']);
assert.deepEqual([...designSectionOrder('inner')], ['stator', 'advanced', 'rotor', 'winding', 'materials']);
assert.deepEqual(designPartsOrder('outer').map(({ id }) => id), ['rotor', 'magnets', 'stator', 'slots', 'teeth', 'winding']);
assert.deepEqual(designPartsOrder('inner').map(({ id }) => id), ['stator', 'slots', 'teeth', 'rotor', 'magnets', 'winding']);
// Until it is entered, an outrunner's stator follows the entered rotor and fits inside its magnets.
const start = newBuildConfig('outer');
start.rotor.OD_mm = 150;
const fitted = fitUnbuiltParts(start, { rotor: true }, { 'rotor:Rotor OD': true });
assert.equal(fitted.rotor.ID_mm, 136.2, 'the unentered Magnet Seat leaves a thin back-iron ring');
assert.ok(Math.abs(signedBuildAirgap(fitted) - 0.4) < 1e-9, 'the fitted stator leaves a small air gap');
assert.ok(fitted.stator.ID_mm > 0 && fitted.stator.ID_mm / 2 + fitted.stator.yoke_thickness_mm < fitted.stator.OD_mm / 2, 'hub and yoke sit inside the stator OD');
assert.equal(buildIssues(fitted, { rotor: true, magnets: true }).length, 0);
const seated = fitUnbuiltParts({ ...fitted, rotor: { ...fitted.rotor, ID_mm: 120 } }, { rotor: true, magnets: true },
  { 'rotor:Rotor OD': true, 'rotor:Magnet Seat': true, 'stator:Outer Diameter': true });
assert.equal(seated.stator.OD_mm, fitted.stator.OD_mm, 'an entered stator OD is kept');
assert.equal(seated.rotor.ID_mm, 120, 'an entered Magnet Seat is kept');
const inrunner = fitUnbuiltParts(newBuildConfig('inner'), { stator: true }, { 'stator:Outer Diameter': true });
assert.equal(inrunner.stator.OD_mm, 100, 'an inrunner still fits its rotor to the stator');
// A slot and pole count without a balanced three-phase winding is named where the second count is
// entered, with counts that work, and an outrunner is still drawn with tooth coils.
assert.equal(windingFits(42, 24), false);
assert.equal(windingFits(15, 24), false);
assert.equal(windingFits(36, 24), true);
assert.equal(windingFits(45, 24), true);
assert.deepEqual(fittingSlotCounts(24).slice(0, 5), [9, 18, 27, 36, 45]);
const unwound = structuredClone(outer);
Object.assign(unwound.stator, { OD_mm: 92, slot_count: 42 });
const slotIssue = buildIssues(unwound, all).find((issue) => issue.label === 'Slot Count');
assert.equal(slotIssue?.section, 'stator');
assert.equal(slotIssue.message, "42 slots can't carry a balanced three-phase winding with 24 poles. With 24 poles, try 27, 36, 45 or 54 slots.");
assert.equal(buildIssues({ ...unwound, stator: { ...unwound.stator, slot_count: 45 } }, all).some((issue) => issue.label === 'Slot Count'), false);
const innerUnwound = cloneDefaultConfig();
Object.assign(innerUnwound.stator, { slot_count: 42 }); innerUnwound.rotor.pole_count = 24;
assert.match(buildIssues(innerUnwound, all).find((issue) => issue.label === 'Pole Count')?.message ?? '',
  /^24 poles can't carry a balanced three-phase winding with 42 slots\. With 42 slots, try \d+(, \d+)* or \d+ poles\.$/);
const drawnWinding = fitUnbuiltParts(unwound, { stator: true, slots: true, rotor: true, magnets: true });
assert.deepEqual([drawnWinding.winding.type, drawnWinding.winding.layers], ['concentrated', 2], 'an outrunner placeholder winding is one it can draw');
assert.equal(fitUnbuiltParts(innerUnwound, { stator: true, slots: true, rotor: true, magnets: true }).winding.type, 'distributed', 'an inrunner keeps its distributed placeholder');
console.log('Outrunner design guides: specific overlap messages, Magnet Seat guide and the entered rotor drawing passed.');
