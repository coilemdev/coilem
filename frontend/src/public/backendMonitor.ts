export const PUBLIC_BACKEND_POLL_INTERVAL_MS = 3_000;

type SchedulePoll = (callback: () => void, delayMs: number) => number;
type CancelPoll = (timerId: number) => void;

export interface PublicBackendMonitorOptions<T> {
  probe: () => Promise<T>;
  onOnline: (payload: T) => void;
  onOffline: (error: unknown) => void;
  onReconnect?: () => void;
  intervalMs?: number;
  schedule?: SchedulePoll;
  cancel?: CancelPoll;
}

/**
 * Poll the loopback backend for the lifetime of the public client.
 *
 * The frontend and backend are commonly started in separate terminals. A
 * one-shot probe leaves the UI permanently offline when the frontend wins
 * that startup race, so every probe schedules the next one whether it succeeds
 * or fails. The returned cleanup also suppresses an in-flight probe result.
 */
export function startPublicBackendMonitor<T>(
  options: PublicBackendMonitorOptions<T>,
): () => void {
  const intervalMs = options.intervalMs ?? PUBLIC_BACKEND_POLL_INTERVAL_MS;
  const schedule = options.schedule
    ?? ((callback: () => void, delayMs: number) => window.setTimeout(callback, delayMs));
  const cancel = options.cancel
    ?? ((timerId: number) => window.clearTimeout(timerId));

  let active = true;
  let timerId: number | null = null;
  let wasOffline = false;

  const poll = async (): Promise<void> => {
    try {
      const payload = await options.probe();
      if (active) {
        options.onOnline(payload);
        if (wasOffline) options.onReconnect?.();
        wasOffline = false;
      }
    } catch (error) {
      if (active) {
        wasOffline = true;
        options.onOffline(error);
      }
    } finally {
      if (active) {
        timerId = schedule(() => {
          timerId = null;
          void poll();
        }, intervalMs);
      }
    }
  };

  void poll();

  return () => {
    active = false;
    if (timerId !== null) cancel(timerId);
  };
}
