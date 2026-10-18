import assert from 'node:assert/strict';
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
assert.deepEqual([tooth.regionLabel, tooth.materialLabel, tooth.saturationLabel], ['Stator tooth', 'M350-50A', 'Above the 1.4–1.6 T reference knee']);
assert.equal(describeFieldProbe(probe('stator_yoke', 90, 0.8), spm).saturationTone, 'good');

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
