import type { SolveResult } from './model';

export const REMOVED_PLAYBACK_REASON = 'Field playback was removed to save disk space. Solve again to see it.';

/** A pruned run retains its summary and static field, but none of its frame references can be fetched. */
export function savedResultPlayback(result: SolveResult, availability: unknown, removedAt?: unknown): SolveResult {
  const state = availability as { available?: unknown } | null | undefined;
  if (state?.available !== false && !removedAt) return result;
  return { ...result, field_line_frames: [], field_playback: null, field_playback_unavailable_reason: REMOVED_PLAYBACK_REASON };
}
