import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';

/** Measure the magnifier's actual canvas so a wider rail shows more area without stretching it. */
export function useMagnifierCanvas(enabled: boolean, slot: HTMLElement | null) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ width: 240, height: 240 });
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!enabled || !canvas) return undefined;
    const measure = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      setSize((current) => current.width === width && current.height === height ? current : { width, height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [enabled, slot]);
  return { canvasRef, ...size };
}

export function ViewportMagnifier({ slot, canvasRef, hasPoint, magnification, label }: {
  slot: HTMLElement | null;
  canvasRef: RefObject<HTMLCanvasElement>;
  hasPoint: boolean;
  magnification: number;
  label: string;
}) {
  const panel = <div className={`public-field-loupe${slot ? ' is-docked' : ''}`} role="region" aria-label={label}>
    <canvas ref={canvasRef} aria-hidden="true" />
    {!hasPoint && <p>Hover over the view to magnify it.</p>}
    <span>{magnification}×</span>
  </div>;
  return slot ? createPortal(panel, slot) : panel;
}
