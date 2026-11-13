import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { validSlotCount, slotPitchText } = await importTypeScriptModule(new URL('../src/public/designHealth.ts', import.meta.url));
const { humanizeGeometryMessage } = await importTypeScriptModule(new URL('../src/public/designErrors.ts', import.meta.url));
const { savedResultPlayback, REMOVED_PLAYBACK_REASON } = await importTypeScriptModule(new URL('../src/public/savedRunPlayback.ts', import.meta.url));
for (const slots of [0, -3, 2, 12.5, Infinity, NaN, 99]) {
  assert.equal(validSlotCount(slots), false);
  assert.doesNotMatch(slotPitchText(slots, 60, false), /Infinity|NaN/);
  assert.match(slotPitchText(slots, 60, false), /Enter valid/);
}
assert.equal(validSlotCount(12), true);
assert.match(slotPitchText(12, 60, false), /slot pitch 30.0° · bore pitch 15.7 mm/);
assert.equal(humanizeGeometryMessage('stator.slot_count: Input should be greater than or equal to 6'), 'Slot Count must be at least 6');
assert.equal(humanizeGeometryMessage('stator.ID_mm: ID_mm must be less than OD_mm'), 'Bore Diameter: Bore Diameter must be less than Outer Diameter');
assert.equal(humanizeGeometryMessage('Geometry.Segment_count'), 'Segment Count');
assert.equal(humanizeGeometryMessage("{'A': 5, 'B': 4, 'C': 4}"), '5 / 4 / 4 coils in phases A / B / C');

const result = { summary: { avg_torque_Nm: 1 }, field_line_plot: { lines: [] },
  field_line_frames: [{ angle_deg: 0, field_frame_artifact: { artifact_id: 'gone' } }], field_playback: { frames: ['gone'] } };
assert.equal(savedResultPlayback(result, { available: true }), result);
assert.equal(savedResultPlayback(result, undefined), result);
for (const [availability, removed] of [[{ available: false }, undefined], [undefined, '2026-11-13']]) {
  const retained = savedResultPlayback(result, availability, removed);
  assert.deepEqual(retained.field_line_frames, []);
  assert.equal(retained.field_playback, null);
  assert.equal(retained.summary, result.summary);
  assert.equal(retained.field_line_plot, result.field_line_plot);
  assert.equal(retained.field_playback_unavailable_reason, REMOVED_PLAYBACK_REASON);
  assert.equal(result.field_line_frames.length, 1);
}
console.log('release priority: invalid drafts, readable errors and pruned playback pass');
