import { PUBLIC_API_BASE } from '../api';
import type {
  HalbachArrayConfig,
  HalbachMeshPreview,
  HalbachPreview,
  HalbachReport,
  HalbachSolveProgress,
  HalbachValidationIssue,
  LinearHalbachArrayConfig,
  LinearHalbachPreview,
  LinearHalbachReport,
} from './types';

interface ValidationResponse {
  valid: boolean;
  errors: HalbachValidationIssue[];
  warnings: HalbachValidationIssue[];
  design_health?: HalbachPreview['design_health'];
  solver_lane?: string;
}

async function readError(response: Response): Promise<Error> {
  let message = `${response.status} ${response.statusText}`;
  try {
    const payload = await response.json() as { detail?: unknown };
    if (typeof payload.detail === 'string') message = payload.detail;
    else if (payload.detail) message = JSON.stringify(payload.detail);
  } catch {
    // Preserve the HTTP status when an upstream proxy returned non-JSON.
  }
  return new Error(message);
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${PUBLIC_API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await readError(response);
  return response.json() as Promise<T>;
}

export function fetchHalbachPreview(config: HalbachArrayConfig): Promise<HalbachPreview> {
  return postJson('/halbach/preview', config);
}

export function fetchHalbachMesh(config: HalbachArrayConfig): Promise<HalbachMeshPreview> {
  return postJson('/halbach/mesh-preview', config);
}

export function validateHalbach(config: HalbachArrayConfig): Promise<ValidationResponse> {
  return postJson('/halbach/solve/validate', config);
}

export function fetchLinearHalbachPreview(
  config: LinearHalbachArrayConfig,
): Promise<LinearHalbachPreview> {
  return postJson('/halbach/linear/preview', config);
}

export function fetchLinearHalbachMesh(
  config: LinearHalbachArrayConfig,
): Promise<HalbachMeshPreview> {
  return postJson('/halbach/linear/mesh-preview', config);
}

export function validateLinearHalbach(
  config: LinearHalbachArrayConfig,
): Promise<ValidationResponse> {
  return postJson('/halbach/linear/solve/validate', config);
}

interface SseFrame {
  event: string;
  data: string;
}

function framesFromBuffer(buffer: string): { frames: SseFrame[]; remainder: string } {
  const normalized = buffer.replace(/\r\n/g, '\n');
  const chunks = normalized.split('\n\n');
  const remainder = chunks.pop() ?? '';
  return {
    frames: chunks
      .map((chunk) => {
        let event = 'message';
        const data: string[] = [];
        for (const line of chunk.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
        }
        return { event, data: data.join('\n') };
      })
      .filter((frame) => frame.data.length > 0),
    remainder,
  };
}

export async function streamHalbachSolve(
  config: HalbachArrayConfig,
  onProgress: (progress: HalbachSolveProgress) => void,
  signal?: AbortSignal,
): Promise<HalbachReport> {
  const response = await fetch(`${PUBLIC_API_BASE}/halbach/solve/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
    signal,
  });
  if (!response.ok) throw await readError(response);
  if (!response.body) throw new Error('The solve stream did not include a response body.');

  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const parsed = framesFromBuffer(buffer);
    buffer = parsed.remainder;
    for (const frame of parsed.frames) {
      const payload = JSON.parse(frame.data) as Record<string, unknown>;
      if (frame.event === 'progress') {
        onProgress(payload as unknown as HalbachSolveProgress);
      } else if (frame.event === 'complete') {
        return payload as unknown as HalbachReport;
      } else if (frame.event === 'error') {
        throw new Error(String(payload.message ?? 'Halbach solve failed.'));
      }
    }
    if (done) break;
  }
  throw new Error('The Halbach solve stream ended before a result was produced.');
}

export async function streamLinearHalbachSolve(
  config: LinearHalbachArrayConfig,
  onProgress: (progress: HalbachSolveProgress) => void,
  signal?: AbortSignal,
): Promise<LinearHalbachReport> {
  const response = await fetch(`${PUBLIC_API_BASE}/halbach/linear/solve/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
    signal,
  });
  if (!response.ok) throw await readError(response);
  if (!response.body) throw new Error('The solve stream did not include a response body.');

  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const parsed = framesFromBuffer(buffer);
    buffer = parsed.remainder;
    for (const frame of parsed.frames) {
      const payload = JSON.parse(frame.data) as Record<string, unknown>;
      if (frame.event === 'progress') {
        onProgress(payload as unknown as HalbachSolveProgress);
      } else if (frame.event === 'complete') {
        return payload as unknown as LinearHalbachReport;
      } else if (frame.event === 'error') {
        throw new Error(String(payload.message ?? 'Linear Halbach solve failed.'));
      }
    }
    if (done) break;
  }
  throw new Error('The linear Halbach solve stream ended before a result was produced.');
}

export type HalbachExportKind = 'report' | 'problem' | 'field' | 'csv' | 'svg' | 'png' | 'pdf';

export async function downloadHalbachExport(
  kind: HalbachExportKind,
  report: HalbachReport,
): Promise<void> {
  const response = await fetch(`${PUBLIC_API_BASE}/halbach/export/${kind}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ report }),
  });
  if (!response.ok) throw await readError(response);
  const contentDisposition = response.headers.get('Content-Disposition') ?? '';
  const match = contentDisposition.match(/filename="([^"]+)"/);
  const extension = kind === 'report' || kind === 'field' || kind === 'problem' ? 'json' : kind;
  const filename = match?.[1] ?? `halbach-export.${extension}`;
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
