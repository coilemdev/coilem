import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// Value axes for result charts (chartAxis.ts): round ticks, distinct labels.
const { displayUnitScale, formatValueTick, valueAxis } = await importTypeScriptModule(
  new URL('../src/public/chartAxis.ts', import.meta.url),
);
const labels = (min, max, intervals) => {
  const axis = valueAxis(min, max, intervals);
  return axis.ticks.map((tick) => formatValueTick(tick, axis.decimals));
};
const distinct = (items) => new Set(items).size === items.length;

// The 40p/36s robot-joint cogging sweep: -0.96 to 3.19 mN·m. In N·m the old
// fixed two decimals printed 0.01 | 0.01 | 0.00 | -0.00 | -0.01.
const cogging = displayUnitScale('N·m', 0.003188);
assert.deepEqual(cogging, { unit: 'mN·m', factor: 1000 });
assert.deepEqual(labels(-0.9636, 3.1879), ['-2', '-1', '0', '1', '2', '3', '4']);
// Unscaled, the same data still gets distinct labels.
assert.ok(distinct(labels(-0.0009636, 0.0031879)));

// A drone motor's torque ripple around 0.2 N·m keeps its unit and resolves.
assert.deepEqual(displayUnitScale('N·m', 0.21), { unit: 'N·m', factor: 1 });
assert.deepEqual(labels(0.1947, 0.2081), ['0.190', '0.195', '0.200', '0.205', '0.210']);

// Every axis spans its data and labels stay distinct, small or large.
for (const [min, max] of [[-5.2, 5.2], [0.05, 0.95], [180, 260], [-74.3, 74.3], [-1e-4, 2.5e-4], [12.3, 12.3], [0, 0]]) {
  const axis = valueAxis(min, max);
  assert.ok(axis.min <= min && axis.max >= max, `[${min}, ${max}] inside [${axis.min}, ${axis.max}]`);
  assert.ok(axis.max > axis.min, 'a flat trace still gets a band');
  assert.ok(axis.ticks.length >= 3 && axis.ticks.length <= 7, `${axis.ticks.length} ticks for [${min}, ${max}]`);
  assert.ok(distinct(labels(min, max)), `distinct labels for [${min}, ${max}]`);
}
// No negative zero.
assert.equal(formatValueTick(-0.0001, 2), '0.00');
assert.equal(formatValueTick(-0, 1), '0.0');
// Large readings and other units keep theirs.
assert.deepEqual(displayUnitScale('V', 48), { unit: 'V', factor: 1 });
assert.deepEqual(displayUnitScale('rpm', 0.05), { unit: 'rpm', factor: 1 });
assert.deepEqual(displayUnitScale('N·m', 0), { unit: 'N·m', factor: 1 });

console.log('value axis checks passed');
