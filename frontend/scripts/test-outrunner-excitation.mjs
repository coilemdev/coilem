import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { importTypeScriptModule } from './import-typescript-module.mjs';
const { currentsAtCW } = await importTypeScriptModule(new URL('../src/public/outrunner/excitation.ts', import.meta.url));
const original = JSON.parse(await readFile(new URL('../src/public/outrunner/lrk_12s14p.coilem', import.meta.url), 'utf8'));
const fixture = JSON.parse(await readFile(new URL('../../tests/fixtures/outrunner_current_vectors.json', import.meta.url), 'utf8'));
for (const vector of fixture.vectors) {
  const actual = currentsAtCW({ ...original.analysis, ...vector.settings }, vector.angle_clockwise_electrical_deg);
  actual.forEach((value, i) => assert.ok(Math.abs(value-vector.currents_A[i]) < 1e-11, `current mismatch for ${JSON.stringify(vector)}`));
}
console.log(`Outrunner preview matches ${fixture.vectors.length} backend current vectors, including sector boundaries and RMS/peak conventions`);
