/**
 * The flux-linkage map run (#139), kept outside React so it carries on while
 * the Torque–speed panel is closed: switching plot tabs or going back to
 * Solve no longer stops it. One map runs at a time, on the local solve lane;
 * /solve/cancel stops it, and finished points are kept for a resume.
 */

import { streamPerformanceMap, type PublicApiError, type PublicSolveRequest } from './api';
import type { DriveLimits, FluxLinkageMapPayload, MapSettings, PerformanceMapProgress } from './performance';

export interface MapJob {
  /** The design and grid the map is for; see mapJobKey. */
  key: string;
  settings: MapSettings;
  phase: 'solving' | 'done' | 'cancelled' | 'error';
  progress: PerformanceMapProgress | null;
  payload: FluxLinkageMapPayload | null;
  error: PublicApiError | null;
}

type Listener = (job: MapJob | null) => void;

let job: MapJob | null = null;
const listeners = new Set<Listener>();

function publish(next: MapJob | null): void {
  job = next;
  listeners.forEach((listener) => listener(job));
}

/** Identifies a map run by the request's design and the map settings. */
export function mapJobKey(request: PublicSolveRequest, settings: MapSettings): string {
  return JSON.stringify([request, settings]);
}

export function currentMapJob(): MapJob | null {
  return job;
}

export function subscribeMapJob(listener: Listener): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** Start a map unless one is already solving; returns whether it started. */
export function startMapJob(request: PublicSolveRequest, settings: MapSettings, progress: PerformanceMapProgress | null): boolean {
  if (job?.phase === 'solving') return false;
  const key = mapJobKey(request, settings);
  const update = (change: Partial<MapJob>) => {
    if (job?.key === key) publish({ ...job, ...change });
  };
  publish({ key, settings, phase: 'solving', progress, payload: null, error: null });
  streamPerformanceMap(request, settings, {
    onProgress: (next) => { if (next.done) update({ progress: next }); },
    onComplete: (payload) => update({ phase: 'done', payload }),
    onError: (error) => update({ phase: error.error_code === 'SOLVER_CANCELLED' ? 'cancelled' : 'error', error }),
  });
  return true;
}

/** The Torque–speed panel's inputs for a design, kept while the panel is closed. */
export interface PanelInputs {
  limits: DriveLimits;
  preset: MapSettings['preset'];
  /** The DC bus was typed in, so it is no longer the back-EMF estimate. */
  busEdited?: boolean;
}

const panelInputs = new Map<string, PanelInputs>();

export function recallPanelInputs(designKey: string): PanelInputs | undefined {
  return panelInputs.get(designKey);
}

export function rememberPanelInputs(designKey: string, inputs: PanelInputs): void {
  panelInputs.set(designKey, inputs);
}
