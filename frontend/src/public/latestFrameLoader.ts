/**
 * Loads the frame the position slider is on, newest request first (#59).
 *
 * Dragging the slider passes many positions faster than their layers decode.
 * Loading every one queued up work for positions already left behind, so the
 * frame on screen fell behind the slider and then jumped. This loader keeps
 * at most `maxInFlight` loads running. A request made while they run replaces
 * the pending one, whose promise resolves with null, and the newest request
 * starts as soon as a running load finishes. Two in flight let one frame
 * decode while the next one downloads.
 */
export class LatestFrameLoader<T> {
  private running = 0;

  constructor(private readonly maxInFlight = 2) {}

  private pending: {
    load: () => Promise<T>;
    resolve: (value: T | null) => void;
    reject: (error: unknown) => void;
  } | null = null;

  request(load: () => Promise<T>): Promise<T | null> {
    return new Promise((resolve, reject) => {
      this.pending?.resolve(null);
      this.pending = { load, resolve, reject };
      this.pump();
    });
  }

  /** Drop the pending request, for example when the slider stops being dragged. */
  clear(): void {
    this.pending?.resolve(null);
    this.pending = null;
  }

  private pump(): void {
    if (this.running >= this.maxInFlight || !this.pending) return;
    const next = this.pending;
    this.pending = null;
    this.running += 1;
    next.load()
      .then(next.resolve, next.reject)
      .finally(() => {
        this.running -= 1;
        this.pump();
      });
  }
}
