import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { importTypeScriptModule } from './import-typescript-module.mjs';

const { advancedGeometrySummary, deriveStatorSectionWidths, shownWidthMm } = await importTypeScriptModule(
  new URL('../src/public/dimensionAnnotations.ts', import.meta.url),
);

// #154: the pinned Pyleecan Prius keeps its SlotW11 tooth width at full precision;
// Advanced Geometry rounds it for display only.
const prius = JSON.parse(await readFile(new URL('../src/public/examples/prius-2004-loaded-torque-v1.coilem', import.meta.url), 'utf8'));
const config = prius.config ?? prius;
const stored = structuredClone(config);
assert.equal(config.stator.tooth_width_mm, 7.086189721925985);

const summary = advancedGeometrySummary(config, deriveStatorSectionWidths(config));
assert.match(summary, /^bore tooth \d+\.\d · yoke tooth 7\.1 · yoke 19\.4$/);
assert.equal(shownWidthMm(config.stator.tooth_width_mm), 7.09, 'the input shows two decimals');
assert.deepEqual(config, stored, 'display rounding leaves the stored design unchanged');

// Short stored values read as entered; a width typed to 0.05 mm keeps both decimals in the input.
assert.equal(advancedGeometrySummary({ stator: { tooth_width_mm: 26.2, yoke_thickness_mm: 18 } }, { boreToothWidthMm: 28.43 }),
  'bore tooth 28.4 · yoke tooth 26.2 · yoke 18.0');
assert.equal(shownWidthMm(6.25), 6.25);
assert.ok(Number.isNaN(shownWidthMm(Number.NaN)));

console.log('Advanced Geometry display tests passed');
