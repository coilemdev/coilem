import { newProfileDocument, parseProfileDocument, type SolveProfileDocument } from './solveProfiles';
const key = (scope: string) => `coilem.run-setups.v1:${scope}`;
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
