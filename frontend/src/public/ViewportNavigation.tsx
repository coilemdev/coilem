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

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export function useViewportNavigation(
  maxScale = MAX_SCALE,
  frameForSize?: (width: number, height: number) => ViewportFrame | null,
  /** A thin-ring motor's sector view for a viewport of this size (sectorFraming.ts). */
  sectorForSize?: (width: number, height: number, angleDeg: number) => SectorView | null,
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
  // Where on the ring the sector view looks: 0 at the top, clockwise on screen.
  const sectorAngleRef = useRef(0);
  const panEnabled = scale >= PAN_UNLOCK_SCALE;
  const sectorAvailable = sectorKey !== null && Boolean(sectorForSize);

  const leaveSector = useCallback(() => {
    sectorActiveRef.current = false;
    setSectorActive(false);
  }, []);

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
    setScale(DEFAULT_SCALE);
    setPan({ x: 0, y: 0 });
  }, [leaveSector]);

  const applySector = useCallback((angleDeg = sectorAngleRef.current) => {
    const rect = viewportRef.current?.getBoundingClientRect();
    const target = rect && sectorForSize ? sectorForSize(rect.width, rect.height, angleDeg) : null;
    if (!target) return false;
    sectorAngleRef.current = angleDeg;
    const nextScale = clamp(target.scale, MIN_SCALE, maxScale);
    sectorActiveRef.current = true;
    setSectorActive(true);
    setScale(nextScale);
    setPan(clampPan(target.pan, nextScale));
    return true;
  }, [clampPan, maxScale, sectorForSize]);
  const applySectorRef = useRef(applySector);
  applySectorRef.current = applySector;

  /** Turn the sector view one step round the ring; ``direction`` +1 is clockwise on screen. */
  const stepSector = useCallback((direction: 1 | -1) => {
    const rect = viewportRef.current?.getBoundingClientRect();
    const here = rect && sectorForSize ? sectorForSize(rect.width, rect.height, sectorAngleRef.current) : null;
    if (!here) return;
    const start = sectorActiveRef.current ? sectorAngleRef.current : 0;
    applySector((((start + direction * here.stepDeg) % 360) + 360) % 360);
  }, [applySector, sectorForSize]);
  const stepSectorRef = useRef(stepSector);
  stepSectorRef.current = stepSector;

  // Left and right arrows turn the sector round the ring while the pointer is over
  // the view or focus is inside it; they stay with any field being typed in.
  useEffect(() => {
    const element = viewportRef.current;
    if (!sectorAvailable || !element) return undefined;
    let hovered = false;
    const enter = () => { hovered = true; };
    const leave = () => { hovered = false; };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (!hovered && !element.contains(document.activeElement)) return;
      event.preventDefault();
      stepSectorRef.current(event.key === 'ArrowRight' ? 1 : -1);
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
      if (sectorActiveRef.current) reset();
      return undefined;
    }
    const frame = window.requestAnimationFrame(() => {
      applySectorRef.current(0);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [reset, sectorKey]);

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
    transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${scale})`,
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
    sectorActive,
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
  sectorActive = false,
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
      {onSectorStep && <button type="button" className="is-sector-step" aria-label="Previous sector" title="Turn the view anticlockwise round the ring (←)" onClick={() => onSectorStep(-1)}>‹</button>}
      {onSector && <button type="button" className="is-sector" aria-label="Zoom to a sector of the ring" title="Zoom to a sector of the ring" aria-pressed={sectorActive} disabled={sectorActive} onClick={onSector}>Sector</button>}
      {onSectorStep && <button type="button" className="is-sector-step" aria-label="Next sector" title="Turn the view clockwise round the ring (→)" onClick={() => onSectorStep(1)}>›</button>}
      <button type="button" className="is-fit" aria-label={`Fit ${fitSubject} to view`} title={`Fit ${fitSubject} to view`} disabled={Math.abs(scale - DEFAULT_SCALE) <= 1e-3} onClick={onReset}>Fit</button>
    </div>
  );
}
