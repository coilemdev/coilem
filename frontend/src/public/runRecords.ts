import type { PublicRunListRecord } from './api';
import { formatSignificant, formatTorqueNm } from './numberFormat';
import { formatSeconds } from './solveTime';

/** Fired on window when a saved run is deleted, so an open Compare view lists the runs again. */
export const RUNS_CHANGED_EVENT = 'coilem-runs-changed';

export function runKey(run: Pick<PublicRunListRecord, 'project_slug' | 'run_id'>): string {
  return `${run.project_slug}/${run.run_id}`;
}

const runDateTime = new Intl.DateTimeFormat('en-US', {
  month: '2-digit', day: '2-digit', year: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});

export function formatRunTime(timestamp: string | null | undefined, fallback: string): string {
  const date = timestamp ? new Date(timestamp) : null;
  return date && Number.isFinite(date.getTime()) ? runDateTime.format(date).replace(',', '') : fallback;
}

export function formatBytes(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '—';
  if (value < 1024) return `${value.toFixed(0)} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let scaled = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && scaled >= 1024; index += 1) {
    scaled /= 1024;
    unit = units[index];
  }
  return `${scaled.toFixed(scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2)} ${unit}`;
}

export function runName(run: PublicRunListRecord): string {
  return run.project_name || run.project_slug;
}

/** A run that did not finish says so; a finished one needs no label. */
export function unfinishedRunLabel(run: PublicRunListRecord): string | null {
  if (run.status === 'complete') return null;
  if (run.status === 'cancelled') return 'Cancelled';
  if (run.status === 'failed') return 'Did not finish';
  if (run.status === 'running') return 'Running';
  return run.status || 'Unknown';
}

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function moment(run: PublicRunListRecord): Date | null {
  const date = new Date(run.completed_at || run.started_at || '');
  return Number.isFinite(date.getTime()) ? date : null;
}

const dayFormat = new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
const dayWithYear = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
const clockFormat = new Intl.DateTimeFormat('en-US', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

/** 'Today', 'Yesterday' or the date, in the viewer's own time zone. */
export function runDayLabel(date: Date | null, now = new Date()): string {
  if (!date) return 'Date not recorded';
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  return date.getFullYear() === now.getFullYear() ? dayFormat.format(date) : dayWithYear.format(date);
}

/** The time of day a run finished, or started when it did not finish. */
export function runClock(run: PublicRunListRecord): string {
  const date = moment(run);
  return date ? clockFormat.format(date) : '—';
}

/** How long the solve took, from the result when it has it, else from the run's own timestamps. */
export function runDuration(run: PublicRunListRecord): string | null {
  const recorded = run.headline?.solve_time_s;
  if (finite(recorded) && recorded > 0) return formatSeconds(recorded);
  const started = new Date(run.started_at || '').getTime();
  const completed = new Date(run.completed_at || '').getTime();
  return run.status === 'complete' && Number.isFinite(started) && Number.isFinite(completed) && completed > started
    ? formatSeconds((completed - started) / 1000) : null;
}

const CONVENTIONS: Record<string, string> = { rms: 'A rms', peak: 'A peak', plateau: 'A plateau' };

/** Current, speed and drive as the run was set up: '30 A rms · 2,400 rpm'. */
export function runOperatingPoint(run: PublicRunListRecord): string | null {
  const point = run.operating_point;
  if (!point) return null;
  const parts: string[] = [];
  if (finite(point.current_A)) {
    parts.push(point.current_A === 0 ? 'No current' : `${formatSignificant(point.current_A)} ${CONVENTIONS[point.current_convention ?? ''] ?? 'A'}`);
  }
  if (finite(point.speed_rpm)) parts.push(`${Math.round(point.speed_rpm).toLocaleString('en-US')} rpm`);
  if (point.excitation_mode === 'ideal_six_step_120') parts.push('six-step');
  if (finite(point.current_angle_deg) && point.current_angle_deg !== 0 && point.excitation_mode !== 'ideal_six_step_120') {
    parts.push(`γ ${formatSignificant(point.current_angle_deg)}°`);
  }
  return parts.length ? parts.join(' · ') : null;
}

export interface RunResults { torque: string | null; efficiency: string | null; backEmf: string | null }

/** The results a list row shows, each in its own column; null where the run did not compute one. */
export function runResults(run: PublicRunListRecord): RunResults {
  const headline = run.headline;
  return {
    torque: finite(headline?.mean_torque_Nm) ? `${formatTorqueNm(headline.mean_torque_Nm)} N·m` : null,
    efficiency: finite(headline?.efficiency_pct) ? `${headline.efficiency_pct.toFixed(1)}%` : null,
    backEmf: finite(headline?.back_emf_fundamental_V) ? `${formatSignificant(headline.back_emf_fundamental_V)} V` : null,
  };
}

/** The line under a run's name: how it was driven, and its cogging swing when that was computed. */
export function runSetupLine(run: PublicRunListRecord): string | null {
  const parts = [runOperatingPoint(run)];
  const cogging = run.headline?.cogging_peak_to_peak_Nm;
  if (finite(cogging)) parts.push(`cogging ${formatSignificant(cogging)} N·m p-p`);
  return parts.filter(Boolean).join(' · ') || null;
}

export interface RunDesign { key: string; name: string; count: number }

/** The designs that have runs, newest first, for the filter above the list. */
export function runDesigns(records: PublicRunListRecord[]): RunDesign[] {
  const designs = new Map<string, RunDesign>();
  for (const record of records) {
    const existing = designs.get(record.project_slug);
    if (existing) existing.count += 1;
    else designs.set(record.project_slug, { key: record.project_slug, name: runName(record), count: 1 });
  }
  return [...designs.values()];
}

export interface RunDay { label: string; runs: PublicRunListRecord[] }

/** Runs in the order given (newest first), split where the day changes. */
export function runsByDay(records: PublicRunListRecord[], now = new Date()): RunDay[] {
  const days: RunDay[] = [];
  for (const record of records) {
    const label = runDayLabel(moment(record), now);
    const last = days[days.length - 1];
    if (last?.label === label) last.runs.push(record);
    else days.push({ label, runs: [record] });
  }
  return days;
}
