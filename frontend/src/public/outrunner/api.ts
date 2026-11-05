import { PUBLIC_API_BASE } from '../api';

export const OUTRUNNER_API = `${PUBLIC_API_BASE}/experimental/outrunner`;

export async function outrunnerRequest<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(OUTRUNNER_API+path, body === undefined ? { signal } : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  });
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail?.message;
    throw new Error(String(message || `Local request failed (${response.status}).`).slice(0, 500));
  }
  return data as T;
}
