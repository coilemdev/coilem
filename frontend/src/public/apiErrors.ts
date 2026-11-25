/**
 * The local API reports a request it will not accept as a list of
 * `{ loc, msg }` entries, one per rejected field. Turn that list into one
 * readable sentence that names each field, so a person can see what to change.
 * `label` may give a field's path a plainer name; other shapes return null.
 */
export function validationErrorMessage(detail: unknown, label: (path: string[]) => string | null = () => null): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const parts = detail.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const { loc, msg } = item as { loc?: unknown; msg?: unknown };
    if (typeof msg !== 'string' || !msg) return [];
    const path = Array.isArray(loc) ? loc.filter((part) => part !== 'body').map(String) : [];
    const name = label(path) ?? path.join(' → ');
    return [name ? `${name}: ${msg}` : msg];
  });
  if (parts.length === 0) return null;
  const shown = parts.slice(0, 3).join('; ');
  return `The request was not accepted. ${shown}${parts.length > 3 ? `; and ${parts.length - 3} more` : ''}.`;
}
