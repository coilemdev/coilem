import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from 'react';
import type { SectorView } from './sectorFraming';
import { anchoredZoomPan, viewportTransformOrigin, type ViewportFrame } from './viewportTransform';

interface Point {
  x: number;
  y: number;
}

interface PointerStart {
  pointerId: number;
  clientX: number;
  clientY: number;
  pan: Point;
}

const MIN_SCALE = 0.5;
const DEFAULT_SCALE = 1;
const MAX_SCALE = 8;
const PAN_UNLOCK_SCALE = 1.02;
/** How long a sector turn takes; prefers-reduced-motion makes it instant. */
const SECTOR_TURN_MS = 260;
/** One arrow-key step of a zoomed view; Shift takes four. */
const ARROW_PAN_PX = 48;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export function useViewportNavigation(
  maxScale = MAX_SCALE,
  frameForSize?: (width: number, height: number) => ViewportFrame | null,
  /** A thin-ring motor's sector view for a viewport of this size (sectorFraming.ts). */
  sectorForSize?: (width: number, height: number) => SectorView | null,
  /** Changes when the motor's ring does; the view opens on its sector, or on the whole motor when null. */
  sectorKey: string | null = null,
) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const pointerStartRef = useRef<PointerStart | null>(null);
  const didDragRef = useRef(false);
  const [scale, setScale] = useState(DEFAULT_SCALE);
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [sectorActive, setSectorActive] = useState(false);
  const sectorActiveRef = useRef(false);
  // The turntable: the sector view keeps its camera on the top of the ring and turns
  // the motor under it, so every sector reads the same way up. sectorAngle is the
  // ring angle shown at the top (clockwise on screen, unwrapped so a turn takes the
  // short way); the view's rotation is its negative.
  const sectorAngleRef = useRef(0);
  const [sectorAngleDeg, setSectorAngleDeg] = useState(0);
  const [sectorSpanDeg, setSectorSpanDeg] = useState(0);
  const [rotationDeg, setRotationDeg] = useState(0);
  const rotationRef = useRef(0);
  const rotationFrameRef = useRef<number | null>(null);
  const panEnabled = scale >= PAN_UNLOCK_SCALE;
  const sectorAvailable = sectorKey !== null && Boolean(sectorForSize);

  const leaveSector = useCallback(() => {
    sectorActiveRef.current = false;
    setSectorActive(false);
  }, []);

  const stopRotation = useCallback(() => {
    if (rotationFrameRef.current !== null) window.cancelAnimationFrame(rotationFrameRef.current);
    rotationFrameRef.current = null;
  }, []);

  /** Ease the view's rotation to ``targetDeg`` from wherever it is now, mid-turn included. */
  const turnTo = useCallback((targetDeg: number) => {
    stopRotation();
    const from = rotationRef.current;
    const delta = targetDeg - from;
    const instant = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (Math.abs(delta) < 1e-6 || instant) {
      rotationRef.current = targetDeg;
      setRotationDeg(targetDeg);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / SECTOR_TURN_MS);
      const eased = t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;
      rotationRef.current = from + delta * eased;
      setRotationDeg(rotationRef.current);
      rotationFrameRef.current = t < 1 ? window.requestAnimationFrame(tick) : null;
    };
    rotationFrameRef.current = window.requestAnimationFrame(tick);
  }, [stopRotation]);
  useEffect(() => stopRotation, [stopRotation]);

  const resetTurntable = useCallback(() => {
    stopRotation();
    rotationRef.current = 0;
    setRotationDeg(0);
    sectorAngleRef.current = 0;
    setSectorAngleDeg(0);
  }, [stopRotation]);

  const clampPan = useCallback((candidate: Point, candidateScale: number): Point => {
    const rect = viewportRef.current?.getBoundingClientRect();
    if (!rect || candidateScale < PAN_UNLOCK_SCALE) return { x: 0, y: 0 };
    // A thin ring's sides lie at the motor's edge: let the pan go half a view
    // further so any part of the ring can sit in the middle.
    const reach = sectorAvailable ? 0.5 : 0;
    const maximumX = Math.max(0, rect.width * (candidateScale - 1 + 2 * reach) / 2);
    const maximumY = Math.max(0, rect.height * (candidateScale - 1 + 2 * reach) / 2);
    return {
      x: clamp(candidate.x, -maximumX, maximumX),
      y: clamp(candidate.y, -maximumY, maximumY),
    };
  }, [sectorAvailable]);

  const setScaleAt = useCallback((
    requestedScale: number,
    anchor: Point = { x: 0, y: 0 },
  ) => {
    const nextScale = clamp(requestedScale, MIN_SCALE, maxScale);
    if (Math.abs(nextScale - scale) < 1e-6) return;
    leaveSector();
    setPan((current) => clampPan(anchoredZoomPan(current, scale, nextScale, anchor), nextScale));
    setScale(nextScale);
  }, [clampPan, leaveSector, maxScale, scale]);

  const reset = useCallback(() => {
    pointerStartRef.current = null;
    didDragRef.current = false;
    setIsDragging(false);
    leaveSector();
    resetTurntable();
    setScale(DEFAULT_SCALE);
    setPan({ x: 0, y: 0 });
  }, [leaveSector, resetTurntable]);

  const sectorTarget = useCallback(() => {
    const rect = viewportRef.current?.getBoundingClientRect();
    return rect && sectorForSize ? sectorForSize(rect.width, rect.height) : null;
  }, [sectorForSize]);

  /** Frame the top of the ring; the turntable keeps its angle. */
  const applySector = useCallback(() => {
    const target = sectorTarget();
    if (!target) return false;
    const nextScale = clamp(target.scale, MIN_SCALE, maxScale);
    sectorActiveRef.current = true;
    setSectorActive(true);
    setSectorSpanDeg(target.stepDeg / 0.75);
    setScale(nextScale);
    setPan(clampPan(target.pan, nextScale));
    return true;
  }, [clampPan, maxScale, sectorTarget]);
  const applySectorRef = useRef(applySector);
  applySectorRef.current = applySector;

  /** Turn the turntable so the ring at ``angleDeg`` (unwrapped) comes to the top. */
  const turnSectorTo = useCallback((angleDeg: number) => {
    if (!sectorActiveRef.current && !applySector()) return;
    sectorAngleRef.current = angleDeg;
    setSectorAngleDeg(angleDeg);
    turnTo(-angleDeg);
  }, [applySector, turnTo]);

  /** Turn one step round the ring; ``direction`` +1 brings the ring clockwise of the view to the top. */
  const stepSector = useCallback((direction: 1 | -1) => {
    const here = sectorTarget();
    if (here) turnSectorTo(sectorAngleRef.current + direction * here.stepDeg);
  }, [sectorTarget, turnSectorTo]);

  /** Turn the short way to the ring at ``angleDeg`` (0 at the top, clockwise), as the position dial asks. */
  const goToSector = useCallback((angleDeg: number) => {
    const current = sectorAngleRef.current;
    turnSectorTo(current + ((((angleDeg - current) % 360) + 540) % 360) - 180);
  }, [turnSectorTo]);
  const stepSectorRef = useRef(stepSector);
  stepSectorRef.current = stepSector;

  /** Move a zoomed view by this many px; false when the view is fitted and has nowhere to go. */
  const panByRef = useRef<(deltaX: number, deltaY: number) => boolean>(() => false);
  panByRef.current = (deltaX, deltaY) => {
    if (!panEnabled) return false;
    if (sectorActiveRef.current) leaveSector();
    setPan((current) => clampPan({ x: current.x + deltaX, y: current.y + deltaY }, scale));
    return true;
  };

  // The arrow keys move a zoomed view while the pointer is over it or focus is
  // inside it; on a thin-ring motor left and right turn the sector round the
  // ring instead. They stay with any field being typed in.
  useEffect(() => {
    const element = viewportRef.current;
    if (!element) return undefined;
    let hovered = false;
    const enter = () => { hovered = true; };
    const leave = () => { hovered = false; };
    const onKeyDown = (event: KeyboardEvent) => {
      const sideways = event.key === 'ArrowLeft' || event.key === 'ArrowRight';
      if (!sideways && event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (!hovered && !element.contains(document.activeElement)) return;
      if (sideways && sectorAvailable) {
        event.preventDefault();
        stepSectorRef.current(event.key === 'ArrowRight' ? 1 : -1);
        return;
      }
      // The key names where the view goes, so the picture slides the other way.
      const step = event.shiftKey ? ARROW_PAN_PX * 4 : ARROW_PAN_PX;
      const moved = sideways
        ? panByRef.current(event.key === 'ArrowRight' ? -step : step, 0)
        : panByRef.current(0, event.key === 'ArrowDown' ? -step : step);
      if (moved) event.preventDefault();
    };
    element.addEventListener('pointerenter', enter);
    element.addEventListener('pointerleave', leave);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      element.removeEventListener('pointerenter', enter);
      element.removeEventListener('pointerleave', leave);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [sectorAvailable]);

  // A thin-ring motor opens on its sector, and a new ring re-frames; without one the view stays fitted.
  useEffect(() => {
    if (sectorKey === null) {
      if (sectorActiveRef.current || rotationRef.current !== 0) reset();
      return undefined;
    }
    resetTurntable();
    const frame = window.requestAnimationFrame(() => {
      applySectorRef.current();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [reset, resetTurntable, sectorKey]);

  const zoomIn = useCallback(() => setScaleAt(scale * 1.25), [scale, setScaleAt]);
  const zoomOut = useCallback(() => setScaleAt(scale / 1.25), [scale, setScaleAt]);

  const onWheel = useCallback((event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const origin = viewportTransformOrigin(rect.width, rect.height, frameForSize?.(rect.width, rect.height) ?? undefined);
    const anchor = {
      x: event.clientX - rect.left - origin.x,
      y: event.clientY - rect.top - origin.y,
    };
    const factor = Math.exp(-event.deltaY * 0.0012);
    setScaleAt(scale * factor, anchor);
  }, [frameForSize, scale, setScaleAt]);

  const onPointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (
      !panEnabled
      || (event.pointerType === 'mouse' && event.button !== 0)
      || (event.target as HTMLElement).closest('button, input, select, a')
    ) return;
    event.preventDefault();
    didDragRef.current = false;
    pointerStartRef.current = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      pan,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsDragging(true);
  }, [pan, panEnabled]);

  const onPointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const start = pointerStartRef.current;
    if (!start || start.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - start.clientX;
    const deltaY = event.clientY - start.clientY;
    if (Math.hypot(deltaX, deltaY) >= 3) {
      didDragRef.current = true;
      if (sectorActiveRef.current) leaveSector();
    }
    setPan(clampPan({
      x: start.pan.x + deltaX,
      y: start.pan.y + deltaY,
    }, scale));
  }, [clampPan, leaveSector, scale]);

  const finishPointer = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const start = pointerStartRef.current;
    if (!start || start.pointerId !== event.pointerId) return;
    pointerStartRef.current = null;
    setIsDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  const onClickCapture = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    if (!didDragRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    didDragRef.current = false;
  }, []);

  useEffect(() => {
    const element = viewportRef.current;
    if (!element) return undefined;
    const observer = new ResizeObserver(() => {
      // A resized view keeps its sector framed; any other view keeps its pan in bounds.
      if (sectorActiveRef.current && applySectorRef.current()) return;
      setPan((current) => clampPan(current, scale));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [clampPan, scale]);

  const contentStyle = {
    transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${scale})${rotationDeg ? ` rotate(${rotationDeg}deg)` : ''}`,
  } as CSSProperties;

  return {
    viewportRef,
    scale,
    pan,
    panEnabled,
    isDragging,
    didDragRef,
    contentStyle,
    zoomIn,
    zoomOut,
    reset,
    /** Frame the ring's sector; null when the motor has no thin ring. */
    sector: sectorAvailable ? () => applySector() : null,
    /** Step the sector view round the ring (+1 clockwise on screen); the arrow keys do the same. */
    sectorStep: sectorAvailable ? stepSector : null,
    /** Turn to a ring angle (the position dial). */
    sectorGoTo: sectorAvailable ? goToSector : null,
    sectorActive,
    /** The view's rotation about the motor centre, clockwise on screen: draw everything turned by it. */
    rotationDeg,
    /** The ring angle at the top of the sector view, 0–360 clockwise, and the arc the view spans. */
    sectorAngleDeg: ((sectorAngleDeg % 360) + 360) % 360,
    sectorSpanDeg,
    bind: {
      onWheel,
      onPointerDown,
      onPointerMove,
      onPointerUp: finishPointer,
      onPointerCancel: finishPointer,
      onClickCapture,
    },
  };
}

export function ViewportNavigationControls({
  scale,
  onZoomIn,
  onZoomOut,
  onReset,
  fitSubject = 'motor',
  onSector = null,
  onSectorStep = null,
  onSectorGoTo = null,
  sectorActive = false,
  sectorAngleDeg = 0,
  sectorSpanDeg = 0,
}: {
  scale: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onReset: () => void;
  fitSubject?: string;
  /** Zoom to the ring's sector (thin-ring motors); no button when null. */
  onSector?: (() => void) | null;
  /** Step the sector round the ring; no buttons when null. */
  onSectorStep?: ((direction: 1 | -1) => void) | null;
  /** Turn to a ring angle from the position dial; no dial when null. */
  onSectorGoTo?: ((angleDeg: number) => void) | null;
  sectorAngleDeg?: number;
  sectorSpanDeg?: number;
  sectorActive?: boolean;
}) {
  const formattedScale = scale.toFixed(1).replace(/\.0$/, '');
  return (
    <div
      className="public-viewport-nav-controls"
      aria-label="Viewport zoom controls"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <button type="button" aria-label="Zoom out" title="Zoom out" disabled={scale <= MIN_SCALE + 1e-3} onClick={onZoomOut}>-</button>
      <span aria-live="polite">{formattedScale}x</span>
      <button type="button" aria-label="Zoom in" title="Zoom in" disabled={scale >= MAX_SCALE - 1e-3} onClick={onZoomIn}>+</button>
      {onSectorGoTo && sectorActive && <SectorDial angleDeg={sectorAngleDeg} spanDeg={sectorSpanDeg} onGoTo={onSectorGoTo} />}
      {onSectorStep && <button type="button" className="is-sector-step" aria-label="Previous sector" title="Turn the view anticlockwise round the ring (←)" onClick={() => onSectorStep(-1)}>‹</button>}
      {onSector && <button type="button" className="is-sector" aria-label="Zoom to a sector of the ring" title="Zoom to a sector of the ring" aria-pressed={sectorActive} disabled={sectorActive} onClick={onSector}>Sector</button>}
      {onSectorStep && <button type="button" className="is-sector-step" aria-label="Next sector" title="Turn the view clockwise round the ring (→)" onClick={() => onSectorStep(1)}>›</button>}
      <button type="button" className="is-fit" aria-label={`Fit ${fitSubject} to view`} title={`Fit ${fitSubject} to view`} disabled={Math.abs(scale - DEFAULT_SCALE) <= 1e-3} onClick={onReset}>Fit</button>
    </div>
  );
}

/**
 * Where the sector view is on the ring: the motor as a circle, the visible arc
 * lit, 0 at the top. Clicking a point on it turns the ring there.
 */
function SectorDial({ angleDeg, spanDeg, onGoTo }: { angleDeg: number; spanDeg: number; onGoTo: (angleDeg: number) => void }) {
  const radius = 10;
  const point = (deg: number) => {
    const angle = (deg * Math.PI) / 180;
    return `${(radius * Math.sin(angle)).toFixed(2)} ${(-radius * Math.cos(angle)).toFixed(2)}`;
  };
  const half = Math.min(179, Math.max(4, spanDeg / 2));
  const arc = `M ${point(angleDeg - half)} A ${radius} ${radius} 0 ${half * 2 > 180 ? 1 : 0} 1 ${point(angleDeg + half)}`;
  const label = `Position on the ring: ${Math.round(angleDeg)}° clockwise from the top. Click the dial to turn there.`;
  return (
    <svg
      className="public-sector-dial"
      viewBox="-14 -14 28 28"
      role="img"
      aria-label={label}
      onClick={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        const x = event.clientX - rect.left - rect.width / 2;
        const y = event.clientY - rect.top - rect.height / 2;
        if (Math.hypot(x, y) < 2) return;
        onGoTo(((Math.atan2(x, -y) * 180) / Math.PI + 360) % 360);
      }}
    >
      <title>{label}</title>
      <circle r={radius} />
      <path d={arc} />
    </svg>
  );
}
