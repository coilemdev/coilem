import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// Stator + PM axes (#120): where each field's working harmonic carries flux
// outward across the gap, and how far the stator field leads the magnets.
const { fieldAxisArrowPaths, leadAngleExplanation, rotorNorthAxisDeg, statorLeadElecDeg } = await importTypeScriptModule(
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

// The stator centre line sits at the rotor axis plus the lead turned into
// mechanical degrees (signed by rotation), which is always one of the stator
// arrows: rotor + span equals the stator axis modulo one pole-pair pitch.
for (const rotation of ['clockwise', 'counterclockwise']) {
  for (const [statorDeg, rotorDeg, polePairs] of [[-22.5, 0, 4], [10, 37, 12], [200, 3, 2]]) {
    const span = (rotation === 'clockwise' ? -1 : 1) * statorLeadElecDeg(statorDeg, rotorDeg, polePairs, rotation) / polePairs;
    const pitch = 360 / polePairs;
    const offset = (((rotorDeg + span - statorDeg) % pitch) + pitch) % pitch;
    assert.ok(offset < 1e-9 || pitch - offset < 1e-9, `${rotation} ${statorDeg}/${rotorDeg}/${polePairs}: ${offset}`);
  }
}

// Axis arrows: a straight (dashed) shaft and a fine solid chevron head, the same shape on the
// rotor and on the larger stator ring (the head used to be a fixed +-4 degrees,
// wider than long on the stator).
const arrowPoints = (path) => {
  const numbers = path.match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g).map(Number);
  return Array.from({ length: numbers.length / 2 }, (_, index) => [numbers[2 * index], numbers[2 * index + 1]]);
};
for (const [from, to, angle] of [[20, 31, 90], [52, 66, 37.5], [52, 66, -150]]) {
  const label = `arrow ${from}->${to} at ${angle} deg`;
  const { shaft, head: headPath } = fieldAxisArrowPaths(from, to, angle);
  const [tail, tip] = arrowPoints(shaft);
  const [sideA, tipAgain, sideB] = arrowPoints(headPath);
  const rad = (angle * Math.PI) / 180;
  close(tail[0], from * Math.cos(rad), `${label} tail x`);
  close(tail[1], -from * Math.sin(rad), `${label} tail y`);
  close(tip[0], to * Math.cos(rad), `${label} tip x`);
  close(tip[1], -to * Math.sin(rad), `${label} tip y`);
  assert.deepEqual(tipAgain, tip, label);
  const head = (to - from) * 0.24;
  for (const side of [sideA, sideB]) {
    close(Math.hypot(side[0] - tip[0], side[1] - tip[1]), Math.hypot(head, head * 0.42), `${label} head edge`);
  }
  // Narrower than long: the two barbs sit 0.84 head lengths apart.
  close(Math.hypot(sideA[0] - sideB[0], sideA[1] - sideB[1]), head * 0.84, `${label} head width`);
}

// The "?" on the lead label says why 90 deg elec is not a right angle on screen.
assert.equal(
  leadAngleExplanation(90, 12),
  'Why 90° elec when the lines are only 7.5° apart? With 12 pole pairs the field pattern repeats every 30° '
    + 'around the motor, so 360° elec is 30° of rotation and 7.5° × 12 = 90° elec. Electrical degrees measure '
    + 'position within one N–S pole pair: at 90° elec the stator field sits halfway between magnet poles, where '
    + 'the magnet torque per amp is largest.',
);
assert.match(leadAngleExplanation(89.6, 4), /only 22\.5° apart\? With 4 pole pairs the field pattern repeats every 90° /);
assert.match(leadAngleExplanation(89, 4), /22\.3° × 4 ≈ 89° elec/);
assert.match(leadAngleExplanation(-60, 4), /holds them back\.$/);
assert.match(leadAngleExplanation(90, 1), /^On a 2-pole motor one turn is 360° elec, so the two lines are 90° apart\./);

console.log('field axes: magnet north axis, stator lead, working harmonic and strongest pattern, axis arrow shape pass');
