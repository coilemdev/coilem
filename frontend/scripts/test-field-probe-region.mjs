import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// What the field probe calls the element under the cursor. The solver's
// magnet_pocket_air tag is air: the shaft bore at the centre of the example SPM
// (radius 1–15 mm, inside its 30 mm rotor ID) and the gaps between its surface
// magnets (55–59 mm). It used to read "Permanent magnet".
const { describeFieldProbe, fieldRegionKind } = await importTypeScriptModule(
  new URL('../src/public/fieldProbeRegion.ts', import.meta.url),
);

const spm = {
  topology: 'SPM',
  rotor: { ID_mm: 30 },
  materials: { stator_steel: 'M350-50A', rotor_steel: 'M270-35A', magnet_grade: 'N42SH', conductor: 'Copper' },
};
const ipm = { ...spm, topology: 'IPM' };
const solidRotor = { ...spm, rotor: { ID_mm: null } };
const probe = (region, radiusMm, bMagT = 0) => ({ elementIndex: 0, region, bMagT, bxT: null, byT: null, radiusMm });

// The shaft bore and the gaps between magnets are air.
const bore = describeFieldProbe(probe('magnet_pocket_air', 1.04), spm);
assert.equal(bore.regionLabel, 'Shaft bore (air)');
assert.equal(bore.materialLabel, 'Air');
assert.equal(describeFieldProbe(probe('magnet_pocket_air', 14.9), spm).regionLabel, 'Shaft bore (air)');
const gap = describeFieldProbe(probe('magnet_pocket_air', 57), spm);
assert.equal(gap.regionLabel, 'Air between magnets');
assert.equal(gap.materialLabel, 'Air');
assert.equal(describeFieldProbe(probe('magnet_pocket_air', 40), ipm).regionLabel, 'Magnet pocket (air)');
// A solid rotor has no bore; without a radius the tag is still air.
assert.equal(fieldRegionKind('magnet_pocket_air', 5, null), 'magnet_pocket');
assert.equal(describeFieldProbe(probe('magnet_pocket_air', null), solidRotor).materialLabel, 'Air');

// Magnets are still magnets, with their grade.
const magnet = describeFieldProbe(probe('magnet', 57, 1.2), spm);
assert.equal(magnet.regionLabel, 'Permanent magnet');
assert.equal(magnet.materialLabel, 'N42SH');

// Steel keeps its material and knee assessment.
const rotor = describeFieldProbe(probe('rotor_core', 40, 1.5), spm);
assert.deepEqual([rotor.regionLabel, rotor.materialLabel, rotor.saturationTone], ['Rotor steel', 'M270-35A', 'warning']);
const tooth = describeFieldProbe(probe('stator_tooth', 70, 1.7), spm);
assert.deepEqual([tooth.regionLabel, tooth.materialLabel, tooth.saturationLabel], ['Stator tooth', 'M350-50A', 'Above the 1.50 T reference knee']);
assert.equal(describeFieldProbe(probe('stator_yoke', 90, 0.8), spm).saturationTone, 'good');

// Use the same B-H curve as the legend: heavy saturation is distinct from the knee warning.
const csv = await readFile(new URL('../../materials/electrical-steel/M350-50A.csv', import.meta.url), 'utf8');
const points = csv.split('\n').filter((line) => line && !line.startsWith('#') && !line.startsWith('B_T'))
  .map((line) => line.split(',').map(Number)).map(([b, h]) => [h, b]);
const catalog = { models: { 'M350-50A': { curve: { points } } } };
const { materialSteelSaturationTicks } = await importTypeScriptModule(new URL('../src/public/fluxColorScale.ts', import.meta.url));
const [knee, heavy] = materialSteelSaturationTicks('M350-50A', spm, catalog);
assert.equal(describeFieldProbe(probe('stator_tooth', 70, knee.bT - 1e-6), spm, catalog).saturationTone, 'good');
assert.equal(describeFieldProbe(probe('stator_tooth', 70, knee.bT), spm, catalog).saturationTone, 'warning');
assert.equal(describeFieldProbe(probe('stator_tooth', 70, heavy.bT - 1e-6), spm, catalog).saturationTone, 'warning');
assert.equal(describeFieldProbe(probe('stator_tooth', 70, heavy.bT), spm, catalog).saturationTone, 'danger');
const saturated = describeFieldProbe(probe('stator_tooth', 70, 2.133), spm, catalog);
assert.equal(saturated.saturationTone, 'danger');
assert.match(saturated.saturationLabel, /1\.78 T heavy-saturation/);
for (const region of ['airgap', 'slot_winding', 'magnet_pocket_air', 'magnet']) {
  assert.equal(describeFieldProbe(probe(region, 60, 3), spm, catalog).saturationTone, 'neutral');
}

// The rotor's own custom steel controls its warning, rather than the stator's threshold.
const custom = { id: 'custom:0123456789abcdef', name: 'High-field sample', source: 'Test curve',
  lamination_thickness_mm: null, curve_sha256: '0'.repeat(64),
  bh_curve: [[0, 0], [1.8, 1000], [2.3, 15000], [2.4, 50000]] };
const differentSteels = { ...spm, materials: { ...spm.materials, rotor_steel: custom.id, custom_steels: { [custom.id]: custom } } };
assert.equal(describeFieldProbe(probe('stator_tooth', 70, 2), differentSteels, catalog).saturationTone, 'danger');
assert.equal(describeFieldProbe(probe('rotor_core', 40, 2), differentSteels, catalog).saturationTone, 'warning');
assert.equal(describeFieldProbe(probe('rotor_core', 40, 2.4), differentSteels, catalog).saturationTone, 'danger');

// The other solver regions read in plain words.
assert.deepEqual(
  ['slot_winding', 'airgap', 'flux_barrier', 'unknown'].map((region) => {
    const card = describeFieldProbe(probe(region, 60), spm);
    return [card.regionLabel, card.materialLabel];
  }),
  [['Winding region', 'Copper'], ['Air gap', 'Air'], ['Flux barrier (air)', 'Air'], ['unknown', 'Solver region']],
);

// Of every tag the solver emits, only "magnet" reads as a magnet.
const solverRegions = ['rotor_core', 'magnet', 'airgap', 'stator_tooth', 'stator_yoke', 'slot_winding', 'flux_barrier', 'magnet_pocket_air', 'unknown'];
for (const region of solverRegions) {
  for (const radiusMm of [5, 57]) {
    const label = describeFieldProbe(probe(region, radiusMm), spm).regionLabel;
    assert.equal(/magnet/i.test(label) && !/between magnets|pocket/i.test(label), region === 'magnet', `${region} at ${radiusMm} mm: ${label}`);
  }
}

console.log('field probe region checks passed');
