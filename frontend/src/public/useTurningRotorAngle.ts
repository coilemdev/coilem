import { useEffect, useState } from 'react';

/** Mechanical degrees a second: slow enough to read as work in progress, quick enough to be seen at once. */
const TURN_DEG_PER_SECOND = 9;

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * The rotor angle to draw while a solve runs: it advances steadily while
 * `turning` is true, holds while it is false, and is null while it is null.
 * It redraws at most `updatesPerSecond` times a second so the picture stays
 * cheap while a solve is using the processor.
 *
 * The pace is fixed, not taken from mesh progress: a sweep can cover only a
 * few mechanical degrees over minutes, which does not read as motion.
 */
export function useTurningRotorAngle(turning: boolean | null, updatesPerSecond: number): number | null {
  const [shownDeg, setShownDeg] = useState<number | null>(null);
  const shown = turning !== null;

  useEffect(() => {
    if (!shown) {
      setShownDeg(null);
      return undefined;
    }
    setShownDeg((current) => current ?? 0);
    if (!turning || prefersReducedMotion()) return undefined;
    const stepSeconds = 1 / Math.max(1, updatesPerSecond);
    const id = window.setInterval(() => {
      setShownDeg((current) => ((current ?? 0) + TURN_DEG_PER_SECOND * stepSeconds) % 360);
    }, stepSeconds * 1_000);
    return () => window.clearInterval(id);
  }, [shown, turning, updatesPerSecond]);

  return shown ? shownDeg : null;
}
