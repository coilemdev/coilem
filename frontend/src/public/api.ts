import type { SolveResult } from './model';
import type { CustomSteel } from './customSteel';
import type { DrivePerformance, FluxLinkageMapPayload, MapSettings, PerformanceMapProgress, PerformanceMapStatus, PerformanceReportKind } from './performance';

export function importPublicSteel(body: { name: string; source: string; csv_text: string; lamination_thickness_mm: number | null }): Promise<{ material: CustomSteel; warnings: string[] }> {
  return requestJson('/materials/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) as Promise<{ material: CustomSteel; warnings: string[] }>;
}

export type PublicMotorConfig = Record<string, unknown>;
export type PublicJson = Record<string, unknown>;
export type PublicSolverId = 'magneto2d' | 'elmer';
export type PublicSolveRequest = PublicMotorConfig | {
  config: PublicMotorConfig;
  project_name?: string;
  solve_mesh_key?: string;
  solver?: PublicSolverId;
};

export interface PublicApiError {
  error_code: string;
  message: string;
  field?: string | null;
  suggestion?: string | null;
}

export interface PublicSolveProgress {
  position: number;
  total: number;
  elapsed_s: number;
  stage: string;
  torque_Nm?: number;
  angle_deg?: number;
  phase_a_V?: number;
  phase_b_V?: number;
  phase_c_V?: number;
  field_frame?: PublicJson;
  field_line_frame?: PublicJson;
  solver_detail?: PublicJson;
}

export interface PublicSolveStreamHandlers {
  onProgress: (progress: PublicSolveProgress) => void;
  onComplete: (result: PublicJson) => void;
  onError: (error: PublicApiError) => void;
}

export type PublicRunExportKind = 'pdf' | 'csv' | 'package';

export interface PublicRunListRecord {
  project_slug: string;
  run_id: string;
  path: string;
  size_bytes?: number | null;
  status: string;
  project_name?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  solver_name?: string | null;
}

export interface PublicRunStoragePolicy {
  max_bytes: number;
  used_bytes: number;
  available_bytes: number;
  accepting_new_runs: boolean;
  automatic_durable_run_deletion: boolean;
  recommended_keep_latest_per_project: number;
}

export interface PublicRunListPayload extends PublicJson {
  storage: PublicRunStoragePolicy;
  runs: PublicRunListRecord[];
}

export interface PublicRunDeletionPayload extends PublicJson {
  status: 'deleted';
  run_id: string;
  storage: PublicRunStoragePolicy;
}

export interface PublicRunComparisonPayload extends PublicJson {
  result: SolveResult;
}

const LOCAL_API_HOSTS = new Set(['127.0.0.1', 'localhost', '::1']);

export function resolvePublicApiBase(configured?: string): string {
  const candidate = (configured || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const parsed = new URL(candidate);
  if (!LOCAL_API_HOSTS.has(parsed.hostname)) {
    throw new Error('The public coilEM client accepts only a loopback API endpoint.');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('The public coilEM client requires an HTTP loopback API endpoint.');
  }
  return parsed.toString().replace(/\/$/, '');
}

// The Vite dev server runs apart from the API (`npm run dev` next to uvicorn on
// 8000). A production bundle is served by the `coilem` launcher's API process,
// so it calls its own origin, whatever port the launcher bound.
export const PUBLIC_API_BASE = resolvePublicApiBase(
  import.meta.env.DEV ? import.meta.env.VITE_COILEM_LOCAL_API_BASE : globalThis.location.origin,
);

async function parseApiError(response: Response): Promise<PublicApiError> {
  const fallback: PublicApiError = {
    error_code: 'REQUEST_FAILED',
    message: `Local API request failed with HTTP ${response.status}.`,
  };
  try {
    const payload = await response.json() as PublicJson;
    const detail = payload.detail;
    if (detail && typeof detail === 'object') {
      return { ...fallback, ...(detail as PublicApiError) };
    }
    return { ...fallback, ...(payload as unknown as PublicApiError) };
  } catch {
    return fallback;
  }
}

async function requestJson(
  path: string,
  init?: RequestInit,
): Promise<PublicJson> {
  const response = await fetch(`${PUBLIC_API_BASE}${path}`, init);
  if (!response.ok) {
    throw await parseApiError(response);
  }
  return response.json() as Promise<PublicJson>;
}

function postConfig(path: string, config: PublicMotorConfig): Promise<PublicJson> {
  return requestJson(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

export function getPublicHealth(): Promise<PublicJson> {
  return requestJson('/health');
}

export function getPublicMaterials(): Promise<PublicJson> {
  return requestJson('/materials');
}

export function generatePublicPreview(config: PublicMotorConfig): Promise<PublicJson> {
  return postConfig('/preview', config);
}

export function generatePublicMesh(config: PublicMotorConfig): Promise<PublicJson> {
  return postConfig('/solver/mesh-preview', config);
}

export function validatePublicSolve(request: PublicSolveRequest): Promise<PublicJson> {
  return postConfig('/solve/validate', request as PublicMotorConfig);
}

export function runPublicSolve(request: PublicSolveRequest): Promise<PublicJson> {
  return postConfig('/solve', request as PublicMotorConfig);
}

export function loadPublicRun(projectSlug: string, runId: string): Promise<PublicJson> {
  return requestJson(
    `/runs/${encodeURIComponent(projectSlug)}/${encodeURIComponent(runId)}`,
  );
}

export function loadPublicRunComparison(projectSlug: string, runId: string): Promise<PublicRunComparisonPayload> {
  return requestJson(
    `/runs/${encodeURIComponent(projectSlug)}/${encodeURIComponent(runId)}/comparison`,
  ) as Promise<PublicRunComparisonPayload>;
}

export function listPublicRuns(): Promise<PublicRunListPayload> {
  return requestJson('/runs') as Promise<PublicRunListPayload>;
}

export function deletePublicRun(projectSlug: string, runId: string): Promise<PublicRunDeletionPayload> {
  return requestJson(
    `/runs/${encodeURIComponent(projectSlug)}/${encodeURIComponent(runId)}`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm_run_id: runId }),
    },
  ) as Promise<PublicRunDeletionPayload>;
}

export function openPublicRunFolder(projectSlug: string, runId: string): Promise<PublicJson> {
  return requestJson(
    `/runs/${encodeURIComponent(projectSlug)}/${encodeURIComponent(runId)}/open-folder`,
    { method: 'POST' },
  );
}

export async function downloadPublicRunExport(
  projectSlug: string,
  runId: string,
  exportKind: PublicRunExportKind,
): Promise<void> {
  const suffix = exportKind === 'package' ? 'package.zip' : `report.${exportKind}`;
  const response = await fetch(
    `${PUBLIC_API_BASE}/runs/${encodeURIComponent(projectSlug)}/${encodeURIComponent(runId)}/${suffix}`,
  );
  if (!response.ok) {
    throw await parseApiError(response);
  }
  const extension = exportKind === 'package' ? 'zip' : exportKind;
  await saveDownload(response, `coilem-${projectSlug}-${runId}.${extension}`);
}

/** Save a download response under the server's file name, else the default. */
async function saveDownload(response: Response, defaultName: string): Promise<void> {
  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  const filename = encodedName
    ? decodeURIComponent(encodedName)
    : plainName || defaultName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function getPublicFieldFrame(artifactId: string): Promise<PublicJson> {
  return requestJson(`/solve/field-frame/${encodeURIComponent(artifactId)}`);
}

export function runPublicArmatureField(request: PublicSolveRequest): Promise<PublicJson> {
  return postConfig('/solve/field-composition/armature', request as PublicMotorConfig);
}

export function streamPublicArmatureField(
  request: PublicSolveRequest,
  handlers: PublicSolveStreamHandlers,
): AbortController {
  return streamPublicRequest(
    '/solve/field-composition/armature/stream',
    'The local API returned no stator-field stream.',
    request,
    handlers,
  );
}

export async function cancelPublicSolve(): Promise<PublicJson> {
  return requestJson('/solve/cancel', { method: 'POST' });
}

export function streamPublicSolve(
  request: PublicSolveRequest,
  handlers: PublicSolveStreamHandlers,
): AbortController {
  return streamPublicRequest(
    '/solve/stream',
    'The local API returned no solve stream.',
    request,
    handlers,
  );
}

/** The design's stored flux-linkage map, if any, and the solves a new one needs (#139). */
export function getPerformanceMapStatus(request: PublicSolveRequest, map: MapSettings): Promise<PerformanceMapStatus> {
  return postConfig('/performance/map/status', { request, map } as PublicMotorConfig) as unknown as Promise<PerformanceMapStatus>;
}

/** Solve the map on the local solve lane; /solve/cancel stops it and finished points are kept. */
export function streamPerformanceMap(
  request: PublicSolveRequest,
  map: MapSettings,
  handlers: {
    onProgress: (progress: PerformanceMapProgress) => void;
    onComplete: (payload: FluxLinkageMapPayload) => void;
    onError: (error: PublicApiError) => void;
  },
): AbortController {
  return streamPublicRequest('/performance/map/stream', 'The local API returned no map stream.', { request, map } as PublicMotorConfig, {
    onProgress: (progress) => handlers.onProgress(progress as unknown as PerformanceMapProgress),
    onComplete: (payload) => handlers.onComplete(payload as unknown as FluxLinkageMapPayload),
    onError: handlers.onError,
  });
}

/** Torque–speed envelope and efficiency map from a finished map under the drive limits (#140, #141). */
export function computeDrivePerformance(body: Record<string, unknown>): Promise<DrivePerformance> {
  return postConfig('/performance/drive', body as PublicMotorConfig) as unknown as Promise<DrivePerformance>;
}

/** The Torque–speed tab's results as a PDF, the performance CSV or the id/iq table (#142), built from the drive request. */
export async function downloadPerformanceReport(kind: PerformanceReportKind, body: Record<string, unknown>): Promise<void> {
  const response = await fetch(`${PUBLIC_API_BASE}/performance/report/${kind}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await parseApiError(response);
  }
  await saveDownload(response, kind === 'pdf' ? 'coilem-performance.pdf' : `coilem-${kind === 'idiq' ? 'idiq-table' : 'performance'}.csv`);
}

function streamPublicRequest(
  path: string,
  unavailableMessage: string,
  request: PublicSolveRequest,
  handlers: PublicSolveStreamHandlers,
): AbortController {
  const controller = new AbortController();

  void fetch(`${PUBLIC_API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) {
      handlers.onError(await parseApiError(response));
      return;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      handlers.onError({
        error_code: 'STREAM_UNAVAILABLE',
        message: unavailableMessage,
      });
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let eventType = '';
    let terminalEvent = false;
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        if (!terminalEvent) handlers.onError({
          error_code: 'STREAM_INTERRUPTED',
          message: 'The local solve stream ended before completion. Finished map points are kept; retry to resume.',
        });
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
          continue;
        }
        if (!line.startsWith('data: ') || !eventType) continue;

        try {
          const payload = JSON.parse(line.slice(6)) as PublicJson;
          if (eventType === 'progress') {
            handlers.onProgress(payload as unknown as PublicSolveProgress);
          } else if (eventType === 'complete') {
            terminalEvent = true;
            handlers.onComplete(payload);
          } else if (eventType === 'error') {
            terminalEvent = true;
            handlers.onError(payload as unknown as PublicApiError);
          }
        } catch {
          terminalEvent = true;
          handlers.onError({
            error_code: 'STREAM_PARSE_FAILED',
            message: 'The local solve stream returned invalid JSON.',
          });
        }
        eventType = '';
      }
    }
  }).catch((error: unknown) => {
    if (error instanceof DOMException && error.name === 'AbortError') return;
    handlers.onError({
      error_code: 'LOCAL_API_UNREACHABLE',
      message: 'The local coilEM API is unreachable.',
    });
  });

  return controller;
}
