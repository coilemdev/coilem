import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';

const GUTTER = 12;
const OFFSET = 6;
// Long enough to move the pointer across the gap from the trigger onto the panel.
const HOVER_CLOSE_MS = 150;

interface TriggerProps {
  'aria-describedby': string;
  'aria-expanded': boolean;
  onClick: () => void;
}

/**
 * Text that opens beside its trigger on hover, keyboard focus or a tap, and
 * closes on Escape, a tap elsewhere or leaving it. Unlike a title attribute it
 * reaches keyboard and touch users, so explanations and status reasons can move
 * off the page without becoming unreachable. The panel is fixed to the window
 * and kept inside it, so it never widens a narrow page.
 */
export function Popover({ trigger, children, align = 'start', className }: {
  trigger: (props: TriggerProps) => ReactNode;
  children: ReactNode;
  align?: 'start' | 'end';
  className?: string;
}) {
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const hoverTimer = useRef<number | null>(null);
  const open = hovered || focused || pinned;
  // Opened by keyboard focus alone, the panel lets clicks through to what it covers.
  const interactive = hovered || pinned;

  useLayoutEffect(() => {
    if (!open) return undefined;
    const place = () => {
      const anchor = rootRef.current?.getBoundingClientRect();
      const panel = panelRef.current;
      if (!anchor || !panel) return;
      const width = panel.offsetWidth;
      const height = panel.offsetHeight;
      const preferred = align === 'end' ? anchor.right - width : anchor.left;
      const left = Math.max(GUTTER, Math.min(preferred, window.innerWidth - width - GUTTER));
      const below = anchor.bottom + OFFSET;
      const above = anchor.top - OFFSET - height;
      const top = below + height > window.innerHeight - GUTTER && above > GUTTER ? above : below;
      setPosition({ left, top });
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open, align]);

  const dismiss = () => {
    if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
    setHovered(false);
    setFocused(false);
    setPinned(false);
  };

  // A press anywhere else closes it, however it was opened.
  useEffect(() => {
    if (!open) return undefined;
    const close = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) dismiss();
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [open]);

  useEffect(() => () => { if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current); }, []);

  return (
    <div
      ref={rootRef}
      className={`popover${className ? ` ${className}` : ''}`}
      onMouseEnter={() => {
        if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
        setHovered(true);
      }}
      onMouseLeave={() => {
        hoverTimer.current = window.setTimeout(() => setHovered(false), HOVER_CLOSE_MS);
      }}
      onFocus={() => setFocused(true)}
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false); }}
      onKeyDown={(event) => { if (event.key === 'Escape' && open) { event.stopPropagation(); dismiss(); } }}
    >
      {trigger({ 'aria-describedby': id, 'aria-expanded': open, onClick: () => { if (pinned) dismiss(); else setPinned(true); } })}
      <div
        ref={panelRef}
        id={id}
        role="tooltip"
        className={`popover-panel${interactive ? ' is-interactive' : ''}`}
        hidden={!open}
        style={position ? { left: position.left, top: position.top } : { left: -9999, top: 0 }}
      >
        {children}
      </div>
    </div>
  );
}

/** A small "i" that explains the thing beside it; `label` names the button for screen readers. */
export function InfoTip({ label, children, align }: { label: string; children: ReactNode; align?: 'start' | 'end' }) {
  return (
    <Popover
      align={align}
      trigger={(props) => <button type="button" className="info-tip" aria-label={label} {...props}>i</button>}
    >
      {children}
    </Popover>
  );
}
