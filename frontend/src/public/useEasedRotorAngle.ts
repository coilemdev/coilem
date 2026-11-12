import { useEffect, useRef, useState } from 'react';

import { publicSolvePulseLevel } from './solveProgress';

const SETTLE_SECONDS = 0.45;
const SNAP_DEG = 0.02;

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Follows `targetDeg` smoothly, redrawing at most `updatesPerSecond` times a
 * second so the picture stays cheap while a solve is using the processor.
 * Null while there is no target; a new target after null starts from zero.
 */
export function useEasedRotorAngle(targetDeg: number | null, updatesPerSecond: number): number | null {
  const [shownDeg, setShownDeg] = useState<number | null>(null);
  const targetRef = useRef<number | null>(targetDeg);
  targetRef.current = targetDeg;
  const active = targetDeg !== null;

  useEffect(() => {
    if (!active) {
      setShownDeg(null);
      return undefined;
    }
    if (prefersReducedMotion()) {
      setShownDeg(targetRef.current);
      const id = window.setInterval(() => setShownDeg(targetRef.current), 1_000);
      return () => window.clearInterval(id);
    }
    const stepSeconds = 1 / Math.max(1, updatesPerSecond);
    const blend = 1 - Math.exp(-stepSeconds / SETTLE_SECONDS);
    setShownDeg((current) => current ?? 0);
    const id = window.setInterval(() => {
      const target = targetRef.current;
      if (target === null) return;
      setShownDeg((current) => {
        const from = current ?? 0;
        const gap = target - from;
        if (Math.abs(gap) <= SNAP_DEG) return from === target ? current : target;
        return from + gap * blend;
      });
    }, stepSeconds * 1_000);
    return () => window.clearInterval(id);
  }, [active, updatesPerSecond]);

  return active ? shownDeg : null;
}

/**
 * The level (0..1) of the field-solve beat while `active`, updated at most
 * `updatesPerSecond` times a second; null otherwise. Under reduced-motion
 * settings it holds the middle of the beat.
 */
export function useSolvePulseLevel(active: boolean, updatesPerSecond: number): number | null {
  const [level, setLevel] = useState<number | null>(null);
  useEffect(() => {
    if (!active) {
      setLevel(null);
      return undefined;
    }
    if (prefersReducedMotion()) {
      setLevel(0.5);
      return undefined;
    }
    const startedAt = performance.now();
    setLevel(0);
    const id = window.setInterval(() => {
      setLevel(publicSolvePulseLevel((performance.now() - startedAt) / 1_000));
    }, 1_000 / Math.max(1, updatesPerSecond));
    return () => window.clearInterval(id);
  }, [active, updatesPerSecond]);
  return active ? level : null;
}
