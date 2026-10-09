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

export function useViewportNavigation(maxScale = MAX_SCALE) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const pointerStartRef = useRef<PointerStart | null>(null);
  const didDragRef = useRef(false);
  const [scale, setScale] = useState(DEFAULT_SCALE);
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const panEnabled = scale >= PAN_UNLOCK_SCALE;

  const clampPan = useCallback((candidate: Point, candidateScale: number): Point => {
    const rect = viewportRef.current?.getBoundingClientRect();
    if (!rect || candidateScale < PAN_UNLOCK_SCALE) return { x: 0, y: 0 };
    const maximumX = Math.max(0, rect.width * (candidateScale - 1) / 2);
    const maximumY = Math.max(0, rect.height * (candidateScale - 1) / 2);
    return {
      x: clamp(candidate.x, -maximumX, maximumX),
      y: clamp(candidate.y, -maximumY, maximumY),
    };
  }, []);

  const setScaleAt = useCallback((
    requestedScale: number,
    anchor: Point = { x: 0, y: 0 },
  ) => {
    const nextScale = clamp(requestedScale, MIN_SCALE, maxScale);
    if (Math.abs(nextScale - scale) < 1e-6) return;
    const ratio = nextScale / scale;
    setPan((current) => clampPan({
      x: anchor.x - (anchor.x - current.x) * ratio,
      y: anchor.y - (anchor.y - current.y) * ratio,
    }, nextScale));
    setScale(nextScale);
  }, [clampPan, maxScale, scale]);

  const reset = useCallback(() => {
    pointerStartRef.current = null;
    didDragRef.current = false;
    setIsDragging(false);
    setScale(DEFAULT_SCALE);
    setPan({ x: 0, y: 0 });
  }, []);

  const zoomIn = useCallback(() => setScaleAt(scale * 1.25), [scale, setScaleAt]);
  const zoomOut = useCallback(() => setScaleAt(scale / 1.25), [scale, setScaleAt]);

  const onWheel = useCallback((event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const anchor = {
      x: event.clientX - rect.left - rect.width / 2,
      y: event.clientY - rect.top - rect.height / 2,
    };
    const factor = Math.exp(-event.deltaY * 0.0012);
    setScaleAt(scale * factor, anchor);
  }, [scale, setScaleAt]);

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
    if (Math.hypot(deltaX, deltaY) >= 3) didDragRef.current = true;
    setPan(clampPan({
      x: start.pan.x + deltaX,
      y: start.pan.y + deltaY,
    }, scale));
  }, [clampPan, scale]);

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
}: {
  scale: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onReset: () => void;
  fitSubject?: string;
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
      <button type="button" className="is-fit" aria-label={`Fit ${fitSubject} to view`} title={`Fit ${fitSubject} to view`} disabled={Math.abs(scale - DEFAULT_SCALE) <= 1e-3} onClick={onReset}>Fit</button>
    </div>
  );
}
