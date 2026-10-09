import type { SolveResult } from './model';
import type { CustomSteel } from './customSteel';

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

export const PUBLIC_API_BASE = resolvePublicApiBase(
  import.meta.env.VITE_COILEM_LOCAL_API_BASE,
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
  const blob = await response.blob();
  const extension = exportKind === 'package' ? 'zip' : exportKind;
  const defaultName = `coilem-${projectSlug}-${runId}.${extension}`;
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
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

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
            handlers.onComplete(payload);
          } else if (eventType === 'error') {
            handlers.onError(payload as unknown as PublicApiError);
          }
        } catch {
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
