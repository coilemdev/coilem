import { newProfileDocument, parseProfileDocument, type SolveProfileDocument } from './solveProfiles';
const key = (scope: string) => `coilem.run-setups.v1:${scope}`;
/** The original file can be reopened without first exporting its setup metadata. */
export async function profileScopeForFile(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return `file:${Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')}`;
}
export function loadProfileDocument(scope: string): SolveProfileDocument {
  try {
    const saved = localStorage.getItem(key(scope));
    const parsed = saved ? parseProfileDocument(JSON.parse(saved)) : undefined;
    if (parsed?.scope === scope) return parsed;
  } catch { /* A design file remains the portable copy if browser storage is unavailable. */ }
  return newProfileDocument(scope);
}
export function storeProfileDocument(document: SolveProfileDocument): boolean {
  try { localStorage.setItem(key(document.scope), JSON.stringify(document)); return true; } catch { return false; }
}
