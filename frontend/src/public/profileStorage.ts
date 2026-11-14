import { newProfileDocument, readProfileDocument, type SolveProfileDocument } from './solveProfiles';
const key = (scope: string) => `coilem.run-setups.v1:${scope}`;
/** The browser library of the starter motor, which is also the gallery's SPM 8p/12s example. */
export const STARTER_SETUP_SCOPE = 'example:spm-8p12s';
/** The original file can be reopened without first exporting its setup metadata. */
export async function profileScopeForFile(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return `file:${Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')}`;
}
export function loadProfileDocument(scope: string): SolveProfileDocument {
  let saved: string | null = null;
  try { saved = localStorage.getItem(key(scope)); } catch { /* A design file remains the portable copy if browser storage is unavailable. */ }
  if (!saved) return newProfileDocument(scope);
  let read: ReturnType<typeof readProfileDocument>;
  try { read = readProfileDocument(JSON.parse(saved)); } catch { read = { skipped: 0, error: 'unreadable' }; }
  const document = read.document?.scope === scope ? read.document : undefined;
  if (!document || read.error || read.skipped) {
    // Keep what this version cannot read (for example setups saved by a newer coilEM)
    // before the library is next stored, so it is never silently lost.
    try { localStorage.setItem(`${key(scope)}:unreadable`, saved); } catch { /* Storage is full or unavailable. */ }
  }
  return document ?? newProfileDocument(scope);
}
export function storeProfileDocument(document: SolveProfileDocument): boolean {
  try {
    // An empty library with nothing selected is the default, so it leaves no entry behind
    // for every new design or run opened. A selected reference setup is still remembered.
    if (document.profiles.length || document.activeId) localStorage.setItem(key(document.scope), JSON.stringify(document));
    else localStorage.removeItem(key(document.scope));
    return true;
  } catch { return false; }
}
