import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// Stator + PM axes (#120): where each field's working harmonic carries flux
// outward across the gap, and how far the stator field leads the magnets.
const { rotorNorthAxisDeg, statorLeadElecDeg } = await importTypeScriptModule(
  new URL('../src/public/fieldAxes.ts', import.meta.url),
);
const { airgapHarmonic, deriveMagneticPolarityCues, strongestAirgapPolePairs } = await importTypeScriptModule(
  new URL('../src/components/tutorials/fieldPolarityCues.ts', import.meta.url),
);

const close = (actual, expected, label, tolerance = 1e-6) => {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} != ${expected}`);
};

// Eight surface magnets alternating north/south, a north pole centred at `rotationDeg`.
const magnets = (rotationDeg) => Array.from({ length: 8 }, (_, index) => {
  const angle = ((rotationDeg + index * 45) * Math.PI) / 180;
  return { center: [50 * Math.cos(angle), 50 * Math.sin(angle)], polarity: index % 2 === 0 ? 'north' : 'south' };
});
close(rotorNorthAxisDeg(magnets(0), 4), 0, 'north magnet at 0°');
close(rotorNorthAxisDeg(magnets(-1.875), 4), 88.125, 'one clockwise step, within one pole-pair pitch');
assert.equal(rotorNorthAxisDeg([], 4), null);

// The stator axis 22.5° mech clockwise of the magnets' leads them by 90° elec
// when the rotor turns clockwise, and lags by 90° when it turns counterclockwise.
close(statorLeadElecDeg(-22.5, 0, 4, 'clockwise'), 90, 'clockwise lead');
close(statorLeadElecDeg(-22.5, 0, 4, 'counterclockwise'), -90, 'counterclockwise lag');
close(statorLeadElecDeg(67.5, 0, 4, 'clockwise'), 90, 'the same lead one pole pair over');

// A 4-pole-pair Br peak at 10° plus a stronger 2-pole-pair pattern, as a
// single-layer 12-slot/8-pole tooth-coil winding has.
const bins = Array.from({ length: 360 }, (_, index) => {
  const angle = index + 0.5;
  const radians = (angle * Math.PI) / 180;
  return {
    mech_angle_deg: angle,
    br_t: 0.03 * Math.cos(4 * (radians - (10 * Math.PI) / 180)) + 0.036 * Math.cos(2 * radians),
    bt_t: 0,
    br_bt_t2: 0,
    samples: 4,
  };
});
const profile = { span_deg: 360, bin_count: 360, sample_count: 1440, bins };
const working = airgapHarmonic(profile, 4);
close(working.peakDeg, 10, 'working-harmonic peak', 1e-3);
close(working.amplitudeT, 0.03, 'working-harmonic amplitude', 1e-4);
assert.equal(strongestAirgapPolePairs(profile, 16), 2);
assert.equal(strongestAirgapPolePairs({ ...profile, span_deg: 180 }, 16), null);

// The stator pole labels keep their placement: S where Br is most positive.
const cues = deriveMagneticPolarityCues(profile, 8, 'stator');
assert.equal(cues.length, 8);
close(cues[0].angleDeg, 10, 'first stator cue', 1e-3);
assert.equal(cues[0].label, 'S');
assert.equal(cues[1].label, 'N');

console.log('field axes: magnet north axis, stator lead, working harmonic and strongest pattern pass');
