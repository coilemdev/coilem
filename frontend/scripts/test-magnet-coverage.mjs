import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// Pole coverage as the geometry builds the magnets. An SPM magnet's width is an
// arc at its radial centre (rotor radius + half the thickness), so coverage
// follows the width; magnet_embrace does not shape an SPM rotor.
const { hasPoleCoverageEstimate, magnetPoleCoverage, magnetPoleCoveragePct } = await importTypeScriptModule(
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
// V-shape and HoleM50 rotors keep their stored coverage; no poles means no coverage.
assert.equal(magnetPoleCoverage({ topology: 'IPM', rotor: { ...spm({}).rotor, ipm_topology: 'v_shape' } }), 0.7);
assert.equal(magnetPoleCoverage({ topology: 'IPM', rotor: { ...spm({}).rotor, ipm_topology: 'pyleecan_holem50' } }), 0.7);
// A straight flat-buried magnet is measured at its pocket centreline, as the backend draws it
// (geometry_drawer.magnet_radial_center_mm): the Honda Accord example draws 85%, not its saved 80%.
const accord = { OD_mm: 230, magnet_width_mm: 36.9, magnet_thickness_mm: 4.46, pole_count: 16, bridge_thickness_mm: 1,
  pocket_clearance_mm: 0.25, magnet_embrace: 0.8, ipm_topology: 'flat_buried', flat_buried_magnet_shape: 'straight' };
const centre = Math.sqrt((115 - 1) ** 2 - (18.45 + 0.25) ** 2) - (2.23 + 0.25);
close(magnetPoleCoverage({ topology: 'IPM', rotor: accord }), 36.9 / (2 * Math.PI * centre / 16), 'flat IPM');
assert.equal(magnetPoleCoveragePct({ topology: 'IPM', rotor: accord }), 85);
assert.equal(magnetPoleCoveragePct({ topology: 'IPM', rotor: { ...accord, magnet_embrace: 0.5 } }),
  magnetPoleCoveragePct({ topology: 'IPM', rotor: accord }), 'the saved coverage does not shape a flat IPM rotor');
assert.equal(magnetPoleCoverage(spm({ pole_count: 0 })), 0);

console.log('magnet coverage checks passed');

// An outer rotor's magnets sit inside the seat (rotor ID): 5.78 mm at a 15.15 mm centre radius over 14 poles.
const outerCoverage = magnetPoleCoverage({
  topology: 'SPM', rotor_layout: 'outer',
  rotor: { OD_mm: 35, ID_mm: 31.8, magnet_thickness_mm: 1.5, magnet_width_mm: 5.78, pole_count: 14, magnet_embrace: 0.85 },
});
assert.ok(Math.abs(outerCoverage - 0.85) < 0.005, `outer coverage ${outerCoverage}`);
console.log('outer-rotor magnet coverage checks passed');

assert.equal(hasPoleCoverageEstimate({ topology: 'IPM', rotor: { ...spm({}).rotor, ipm_topology: 'v_shape' } }), false);
assert.equal(hasPoleCoverageEstimate(spm({})), true);
