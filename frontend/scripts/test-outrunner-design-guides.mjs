import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));
const { parseDesignFile } = await importTypeScriptModule(new URL('../src/public/designFile.ts', import.meta.url));
const { buildIssues, enteredRotorRegions, withEnteredRotor, signedBuildAirgap } = await importTypeScriptModule(new URL('../src/public/progressiveDesign.ts', import.meta.url));
const { buildDimensionAnnotations, designFieldDimension } = await importTypeScriptModule(new URL('../src/public/dimensionAnnotations.ts', import.meta.url));

const all = { stator: true, slots: true, teeth: true, rotor: true, magnets: true, winding: true };
const radii = (points) => points.map(([x, y]) => Math.hypot(x, y));
const outrunnerFile = await readFile(new URL('../src/public/examples/spm_outrunner_14p12s.coilem', import.meta.url), 'utf8');
const outer = parseDesignFile(outrunnerFile).config;
// The reported outrunner: a 119.4 mm stator with the rotor's inner face (Magnet Seat) inside it.
Object.assign(outer.stator, { OD_mm: 119.4 });
Object.assign(outer.rotor, { OD_mm: 119.4, ID_mm: 102.6, magnet_thickness_mm: 4, pole_count: 24, magnet_width_mm: 10 });
const seatIssue = buildIssues(outer, all).find((issue) => issue.label === 'Magnet Seat');
assert.ok(seatIssue, 'an overlapping outrunner rotor names the Magnet Seat');
for (const text of ["rotor's inner diameter", 'stator OD (119.4 mm)', 'with 4 mm magnets and a 1 mm air gap', 'use 129.4 mm or more', 'now 102.6 mm']) {
  assert.ok(seatIssue.message.includes(text), `${text} in: ${seatIssue.message}`);
}
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
console.log('Outrunner design guides: specific overlap messages, Magnet Seat guide and the entered rotor drawing passed.');
