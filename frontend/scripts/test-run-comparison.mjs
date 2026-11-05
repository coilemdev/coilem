import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { normalizeComparisonResult } = await importTypeScriptModule(new URL('../src/public/runComparison.ts', import.meta.url));
const emptyTorque = { electrical_angle_deg: [], torque_Nm: [] };
const emptyEmf = { electrical_angle_deg: [], phase_a_V: [], phase_b_V: [], phase_c_V: [] };

// The old comparison route emits {} for analyses with no CSV rows. Opening
// Previous runs must not hand undefined angle arrays to the comparison view.
for (const missing of [undefined, null, {}]) {
  const source = { summary: {}, solve_metadata: {}, torque_waveform: missing, back_emf_waveform: missing };
  const normalized = normalizeComparisonResult(source);
  assert.deepEqual(normalized.torque_waveform, emptyTorque);
  assert.deepEqual(normalized.back_emf_waveform, emptyEmf);
  assert.equal(source.torque_waveform, missing, 'normalization must not change stored input');
}
const torqueOnly = { summary: {}, solve_metadata: {}, torque_waveform: { electrical_angle_deg: [0, 30], torque_Nm: [4.2, 4.3] }, back_emf_waveform: {} };
assert.deepEqual(normalizeComparisonResult(torqueOnly).torque_waveform, torqueOnly.torque_waveform);
assert.deepEqual(normalizeComparisonResult(torqueOnly).back_emf_waveform, emptyEmf);
assert.deepEqual(normalizeComparisonResult({ ...torqueOnly, torque_waveform: emptyTorque, back_emf_waveform: emptyEmf }).torque_waveform, emptyTorque);
console.log('Saved-run comparison preserves samples and handles unrequested/legacy waveforms.');
