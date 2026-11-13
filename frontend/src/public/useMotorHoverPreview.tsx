import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

const OPEN_EVENT = 'coilem:motor-hover-preview';

/** An explanatory card beside a choice group; opening it never selects a choice. */
export function useMotorHoverPreview<Choice extends string>(disabled = false) {
  const id = useId();
  const groupRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<number | null>(null);
  const keyboardRef = useRef(false);
  const [preview, setPreview] = useState<Choice | null>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const clearTimer = () => { if (timerRef.current !== null) window.clearTimeout(timerRef.current); timerRef.current = null; };
  const dismiss = () => { clearTimer(); setPreview(null); setPosition(null); };
  const show = (choice: Choice, delay = 0) => {
    clearTimer();
    if (disabled) return;
    const open = () => {
      document.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: id }));
      setPreview(choice);
    };
    if (delay) timerRef.current = window.setTimeout(open, delay);
    else open();
  };
  const leave = () => { clearTimer(); timerRef.current = window.setTimeout(dismiss, 200); };

  useEffect(() => {
    // Enter selects a card and may focus the next setup control. Only deliberate
    // tab navigation should open a preview on that new control.
    const keyboard = (event: KeyboardEvent) => { keyboardRef.current = event.key === 'Tab'; };
    const pointer = (event: PointerEvent) => {
      keyboardRef.current = false;
      if (!groupRef.current?.contains(event.target as Node) && !panelRef.current?.contains(event.target as Node)) dismiss();
    };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') dismiss(); };
    const otherPreview = (event: Event) => { if ((event as CustomEvent<string>).detail !== id) dismiss(); };
    document.addEventListener('keydown', keyboard, true);
    document.addEventListener('keydown', escape);
    document.addEventListener('pointerdown', pointer, true);
    document.addEventListener(OPEN_EVENT, otherPreview);
    return () => {
      clearTimer();
      document.removeEventListener('keydown', keyboard, true);
      document.removeEventListener('keydown', escape);
      document.removeEventListener('pointerdown', pointer, true);
      document.removeEventListener(OPEN_EVENT, otherPreview);
    };
  }, [id]);

  useEffect(() => { if (disabled) dismiss(); }, [disabled]);

  useLayoutEffect(() => {
    if (!preview) return;
    const place = () => {
      const anchor = groupRef.current?.getBoundingClientRect();
      const panel = panelRef.current?.getBoundingClientRect();
      if (!anchor || !panel) return;
      if (anchor.bottom < 0 || anchor.top > window.innerHeight) { dismiss(); return; }
      const margin = 12;
      const right = anchor.right + margin;
      const leftSide = anchor.left - panel.width - margin;
      const beside = right + panel.width <= window.innerWidth - margin || leftSide >= margin;
      const left = right + panel.width <= window.innerWidth - margin ? right : leftSide >= margin ? leftSide
        : Math.max(margin, Math.min(anchor.left, window.innerWidth - panel.width - margin));
      const top = beside ? anchor.top
        : anchor.bottom + margin + panel.height <= window.innerHeight - margin ? anchor.bottom + margin : anchor.top - panel.height - margin;
      setPosition({ left, top: Math.max(margin, Math.min(top, window.innerHeight - panel.height - margin)) });
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); };
  }, [preview]);

  return {
    groupRef,
    dismiss,
    triggerProps: (choice: Choice, unavailable = false) => ({
      'aria-describedby': preview === choice ? id : undefined,
      onMouseEnter: () => { if (!unavailable) show(choice, 180); },
      onMouseLeave: leave,
      onFocus: () => { if (!unavailable && keyboardRef.current) show(choice); },
      onBlur: leave,
    }),
    renderPreview: (render: (choice: Choice) => ReactNode) => preview && !disabled
      ? createPortal(<div ref={panelRef} id={id} role="tooltip" className="public-arrangement-preview"
        style={{ left: position?.left ?? 0, top: position?.top ?? 0, visibility: position ? 'visible' : 'hidden' }}
        onMouseEnter={clearTimer} onMouseLeave={leave}>
        {render(preview)}
      </div>, document.body) : null,
  };
}
