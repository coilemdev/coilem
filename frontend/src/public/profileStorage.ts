import { newProfileDocument, readProfileDocument, type SolveProfileDocument } from './solveProfiles';
const key = (scope: string) => `coilem.run-setups.v1:${scope}`;
/** The browser library of the starter motor, which is also the gallery's SPM 8p/12s example. */
export const STARTER_SETUP_SCOPE = 'example:spm-8p12s';
/** Libraries this version cannot fully read, for example one saved by a newer coilEM. Their key is
 * left as it is for that version; this version keeps its own copy beside it. */
const readOnlyScopes = new Set<string>();
/** Libraries of designs that exist only in this window: a new design, or an edited example, not
 * yet saved to a file. Nothing could load them after a reload, so they are stored from the first
 * save of the design file, which carries their scope. */
const sessionScopes = new Set<string>();
/** The key this version reads and writes for a library. */
export function profileStorageKey(scope: string): string {
  return readOnlyScopes.has(scope) ? `${key(scope)}:this-version` : key(scope);
}
/** The original file can be reopened without first exporting its setup metadata. */
export async function profileScopeForFile(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return `file:${Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')}`;
}
function readLibrary(scope: string, saved: string | null): { document?: SolveProfileDocument; complete: boolean } {
  if (!saved) return { document: newProfileDocument(scope), complete: true };
  let read: ReturnType<typeof readProfileDocument>;
  try { read = readProfileDocument(JSON.parse(saved)); } catch { return { complete: false }; }
  const document = read.document?.scope === scope ? read.document : undefined;
  return { document, complete: Boolean(document) && !read.error && !read.skipped };
}
/** A stored library, or undefined when it holds anything this version cannot read. */
export function readStoredProfileDocument(scope: string, saved: string | null): SolveProfileDocument | undefined {
  const library = readLibrary(scope, saved);
  return library.complete ? library.document : undefined;
}
export function loadProfileDocument(scope: string): SolveProfileDocument {
  const get = (name: string) => {
    try { return localStorage.getItem(name); } catch { return null; } // A design file remains the portable copy if browser storage is unavailable.
  };
  const stored = readLibrary(scope, get(key(scope)));
  if (stored.complete) {
    readOnlyScopes.delete(scope);
    return stored.document ?? newProfileDocument(scope);
  }
  // Never write over setups this version cannot read: work on this version's own copy, or
  // start one from the part it can read.
  readOnlyScopes.add(scope);
  const own = readStoredProfileDocument(scope, get(profileStorageKey(scope)));
  return own?.profiles.length || own?.activeId ? own : stored.document ?? newProfileDocument(scope);
}
/** A library for a design that exists only in this window; `from` gives its starting setups. */
export function newSessionProfileDocument(from?: SolveProfileDocument): SolveProfileDocument {
  const document = { ...(from ?? newProfileDocument()), scope: crypto.randomUUID() };
  sessionScopes.add(document.scope);
  return document;
}
/** Store a session library from now on, once a saved design file can reopen it. */
export function keepProfileScope(scope: string): void {
  sessionScopes.delete(scope);
}
export function storeProfileDocument(document: SolveProfileDocument): boolean {
  if (sessionScopes.has(document.scope)) return true;
  try {
    // An empty library with nothing selected is the default, so it leaves no entry behind
    // for every new design or run opened. A selected reference setup is still remembered.
    const name = profileStorageKey(document.scope);
    if (document.profiles.length || document.activeId) localStorage.setItem(name, JSON.stringify(document));
    else localStorage.removeItem(name);
    return true;
  } catch { return false; }
}
