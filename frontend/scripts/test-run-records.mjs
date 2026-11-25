import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const {
  formatBytes, runClock, runDayLabel, runDesigns, runDuration, runOperatingPoint, runResults, runSetupLine, runsByDay, unfinishedRunLabel,
} = await importTypeScriptModule(new URL('../src/public/runRecords.ts', import.meta.url));

// Times are built and read in this machine's own time zone.
const at = (day, hour, minute) => new Date(2026, 10, day, hour, minute, 3);
const now = at(14, 16, 59);
const run = (overrides) => ({ project_slug: 'alpha', run_id: 'r', path: '/r', status: 'complete', project_name: 'Alpha motor', ...overrides });

// Days read as people say them; an older year is spelled out.
assert.equal(runDayLabel(at(14, 0, 1), now), 'Today');
assert.equal(runDayLabel(at(13, 23, 59), now), 'Yesterday');
assert.equal(runDayLabel(at(10, 9, 0), now), 'Tue, Nov 10');
assert.equal(runDayLabel(new Date(2025, 11, 31, 9, 0), now), 'Dec 31, 2025');
assert.equal(runDayLabel(null, now), 'Date not recorded');

// Runs stay in the order given and split where the day changes.
const listed = [
  run({ run_id: 'c', completed_at: at(14, 12, 10).toISOString() }),
  run({ run_id: 'b', status: 'cancelled', started_at: at(14, 12, 5).toISOString() }),
  run({ run_id: 'a', project_slug: 'beta', project_name: 'Beta outrunner', completed_at: at(13, 1, 47).toISOString() }),
];
assert.deepEqual(runsByDay(listed, now).map((day) => [day.label, day.runs.map((row) => row.run_id)]), [['Today', ['c', 'b']], ['Yesterday', ['a']]]);
assert.deepEqual(runDesigns(listed), [{ key: 'alpha', name: 'Alpha motor', count: 2 }, { key: 'beta', name: 'Beta outrunner', count: 1 }]);
assert.equal(runClock(listed[0]), '12:10');
assert.equal(runClock(listed[1]), '12:05', 'a run that did not finish shows when it started');
assert.equal(runClock(run({})), '—');

// Only a run that did not finish carries a label.
assert.equal(unfinishedRunLabel(run({})), null);
assert.equal(unfinishedRunLabel(run({ status: 'cancelled' })), 'Cancelled');
assert.equal(unfinishedRunLabel(run({ status: 'failed' })), 'Did not finish');
assert.equal(unfinishedRunLabel(run({ status: 'running' })), 'Running');

// The drive is shown as it was entered.
assert.equal(runOperatingPoint(run({ operating_point: { current_A: 30, current_convention: 'rms', speed_rpm: 2400, current_angle_deg: 0, excitation_mode: 'sinusoidal' } })), '30.0 A rms · 2,400 rpm');
assert.equal(runOperatingPoint(run({ operating_point: { current_A: 10, current_convention: 'plateau', speed_rpm: 8000, excitation_mode: 'ideal_six_step_120' } })), '10.0 A plateau · 8,000 rpm · six-step');
assert.equal(runOperatingPoint(run({ operating_point: { current_A: 0, current_convention: 'rms', speed_rpm: 3000 } })), 'No current · 3,000 rpm');
assert.equal(runOperatingPoint(run({ operating_point: { current_A: 50, current_convention: 'peak', speed_rpm: 6000, current_angle_deg: 30 } })), '50.0 A peak · 6,000 rpm · γ 30.0°');
assert.equal(runOperatingPoint(run({})), null);
assert.equal(runOperatingPoint(run({ operating_point: {} })), null);

// Each result has its own column, empty where the run did not compute it.
assert.deepEqual(runResults(run({ headline: { mean_torque_Nm: 11.164, efficiency_pct: 95.24, back_emf_fundamental_V: 31.19 } })),
  { torque: '11.16 N·m', efficiency: '95.2%', backEmf: '31.2 V' });
assert.deepEqual(runResults(run({ headline: { mean_torque_Nm: 0.064 } })), { torque: '0.0640 N·m', efficiency: null, backEmf: null });
assert.deepEqual(runResults(run({})), { torque: null, efficiency: null, backEmf: null });
assert.equal(runSetupLine(run({ operating_point: { current_A: 0, speed_rpm: 3000 }, headline: { cogging_peak_to_peak_Nm: 0.004 } })), 'No current · 3,000 rpm · cogging 0.00400 N·m p-p');
assert.equal(runSetupLine(run({})), null);

// The solve's own time when recorded, else the run's timestamps; nothing for a run that did not finish.
assert.equal(runDuration(run({ headline: { solve_time_s: 9.61 } })), '9.61 s');
assert.equal(runDuration(run({ started_at: at(14, 12, 9).toISOString(), completed_at: at(14, 12, 10).toISOString() })), '60.0 s');
assert.equal(runDuration(run({ status: 'cancelled', started_at: at(14, 12, 9).toISOString() })), null);

assert.equal(formatBytes(236_000_000), '225 MB');
assert.equal(formatBytes(null), '—');

console.log('run record list helpers passed');
