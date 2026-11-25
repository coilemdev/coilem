import { streamThermalRating, type PublicSolveProgress } from './api';
import type { ThermalAnalysis } from './thermal';

interface ThermalJob { key: string; phase: 'running' | 'done' | 'error'; stage: string; done?: number; total?: number; analysis?: ThermalAnalysis; error?: string }
let job: ThermalJob | null = null;
const listeners = new Set<(value: ThermalJob | null) => void>();
const emit = () => listeners.forEach((listener) => listener(job));
export const currentThermalJob = () => job;
export function subscribeThermalJob(listener: (value: ThermalJob | null) => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
/** Where a run's latest result of each kind is remembered: the estimate and the torque curve do not replace each other. */
export const thermalSlot = (key: string, kind: ThermalAnalysis['kind']) => (kind === 'rating' ? `${key}.rating` : key);
export function rememberThermal(key: string, analysis: ThermalAnalysis) {
  try { localStorage.setItem(thermalSlot(key, analysis.kind), analysis.id); } catch { /* Storage can be disabled; the in-memory job still works. */ }
  window.dispatchEvent(new Event('coilem-thermal-updated'));
}
export function startThermalJob(key: string, body: Record<string, unknown>): boolean {
  if (job?.phase === 'running') return false;
  job = {key, phase: 'running', stage: 'Starting'}; emit();
  streamThermalRating(body, {
    onProgress: (progress: PublicSolveProgress) => {
      // The thermal stream counts its own steps: `done` of `total` within the stage it names.
      const { done, total } = progress as unknown as { done?: number; total?: number };
      job = {key, phase: 'running', stage: progress.stage, done, total}; emit();
    },
    onComplete: (value) => { const analysis = value as unknown as ThermalAnalysis; job = {key, phase: 'done', stage: 'Complete', analysis}; rememberThermal(key, analysis); emit(); },
    onError: (error) => { job = {key, phase: 'error', stage: 'Stopped', error: error.message}; emit(); },
  });
  return true;
}
