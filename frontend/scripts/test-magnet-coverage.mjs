import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// Pole coverage as the geometry builds the magnets. An SPM magnet's width is an
// arc at its radial centre (rotor radius + half the thickness), so coverage
// follows the width; magnet_embrace does not shape an SPM rotor.
const { magnetPoleCoverage, magnetPoleCoveragePct } = await importTypeScriptModule(
  new URL('../src/public/magnetCoverage.ts', import.meta.url),
);

const { DEFAULT_CONFIG } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));
const spm = (rotor) => ({ topology: 'SPM', rotor: { ...DEFAULT_CONFIG.rotor, ...rotor } });
const close = (actual, expected, label) => assert.ok(Math.abs(actual - expected) < 1e-4, `${label}: ${actual} != ${expected}`);

// The example 8p/12s: 31.8 mm at the 57 mm centre radius of a 44.77 mm pitch
// reads 71%, not its stored 70%; the former 31.4 mm read 70%.
assert.equal(DEFAULT_CONFIG.topology, 'SPM');
assert.equal(DEFAULT_CONFIG.rotor.magnet_width_mm, 31.8);
close(magnetPoleCoverage(spm({})), 31.8 / (2 * Math.PI * 57 / 8), 'example');
assert.equal(magnetPoleCoveragePct(spm({})), 71);
assert.equal(magnetPoleCoveragePct(spm({ magnet_width_mm: 31.4 })), 70);
// A thicker magnet moves the centre radius out, so the same width covers less.
assert.ok(magnetPoleCoverage(spm({ magnet_thickness_mm: 4.5 })) < magnetPoleCoverage(spm({})));
// The stored magnet_embrace no longer matters for SPM.
assert.equal(magnetPoleCoveragePct(spm({ magnet_embrace: 0.9 })), 71);
// The tutorial's width formula for a 2-pole rotor round-trips to its arc.
const lessonWidth = Math.PI * (60 + 6) * 0.74 / 2;
close(magnetPoleCoverage(spm({ OD_mm: 60, magnet_thickness_mm: 6, pole_count: 2, magnet_width_mm: lessonWidth })), 0.74, 'tutorial');
// IPM rotors keep their stored coverage; no poles means no coverage.
assert.equal(magnetPoleCoverage({ topology: 'IPM', rotor: spm({}).rotor }), 0.7);
assert.equal(magnetPoleCoverage(spm({ pole_count: 0 })), 0);

console.log('magnet coverage checks passed');
