import { useEffect, useId, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';

export interface RunSetupOption { value: string; label: string; group?: string; disabled?: boolean; }

/** A select-only combobox. Focus stays on its trigger while the listbox is open. */
export function RunSetupMenu({ options, value, disabled, triggerRef, onChange }: {
  options: RunSetupOption[]; value: string; disabled: boolean;
  triggerRef: RefObject<HTMLButtonElement>; onChange: (value: string, focusName?: boolean) => void;
}) {
  const id = useId();
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(value);
  const [position, setPosition] = useState<{ left: number; top: number; width: number; maxHeight: number } | null>(null);
  const typed = useRef({ text: '', time: 0 });
  const enabled = options.filter(option => !option.disabled);
  const openMenu = () => { setHighlight(enabled.find(option => option.value === value)?.value ?? enabled[0]?.value ?? ''); setOpen(true); };
  const choose = (next: string, keepFocus = true) => {
    if (!enabled.some(option => option.value === next)) return;
    setOpen(false); if (keepFocus) triggerRef.current?.focus(); onChange(next, keepFocus);
  };
  const optionId = (index: number) => `${id}-option-${index}`;
  useEffect(() => { if (!open) typed.current = { text: '', time: 0 }; }, [open]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  useEffect(() => {
    if (open && !enabled.some(option => option.value === highlight)) setHighlight(enabled[0]?.value ?? '');
  }, [open, options, highlight]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node) && !triggerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', outside, true);
    return () => document.removeEventListener('pointerdown', outside, true);
  }, [open, triggerRef]);
  useLayoutEffect(() => {
    if (!open) { setPosition(null); return; }
    const place = () => {
      const anchor = triggerRef.current?.parentElement?.getBoundingClientRect();
      if (!anchor) return;
      if (anchor.bottom < 12 || anchor.top > window.innerHeight - 12) { setOpen(false); return; }
      const gap = 6, margin = 12;
      const width = Math.min(Math.max(anchor.width, 240), window.innerWidth - margin * 2);
      const below = window.innerHeight - anchor.bottom - gap - margin;
      const above = anchor.top - gap - margin;
      const height = Math.min(menuRef.current?.scrollHeight ?? 320, 320);
      const upwards = below < height && above > below;
      const maxHeight = Math.max(60, Math.min(320, upwards ? above : below));
      setPosition({ left: Math.max(margin, Math.min(anchor.left, window.innerWidth - margin - width)),
        top: upwards ? Math.max(margin, anchor.top - gap - Math.min(height, maxHeight)) : anchor.bottom + gap, width, maxHeight });
    };
    const scroll = (event: Event) => { if (!menuRef.current?.contains(event.target as Node)) place(); };
    place(); window.addEventListener('resize', place); window.addEventListener('scroll', scroll, true);
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', scroll, true); };
  }, [open, triggerRef, options.length]);
  useLayoutEffect(() => {
    const menu = menuRef.current;
    const option = menu?.querySelector<HTMLElement>('[data-highlighted="true"]');
    if (!open || !position || !menu || !option) return;
    // Scroll just the list: scrollIntoView can also move the surrounding Solve panel.
    const box = menu.getBoundingClientRect(), item = option.getBoundingClientRect();
    if (item.top < box.top + 5) menu.scrollTop -= box.top + 5 - item.top;
    else if (item.bottom > box.bottom - 5) menu.scrollTop += item.bottom - box.bottom + 5;
  }, [open, highlight, position]);
  const groups = [...new Set(options.map(option => option.group ?? ''))];
  const activeIndex = options.findIndex(option => option.value === highlight && !option.disabled);
  return <>
    <button ref={triggerRef} type="button" role="combobox" className="public-run-setup-menu-trigger"
      aria-label="Run setup" aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? id : undefined}
      aria-activedescendant={open && activeIndex >= 0 ? optionId(activeIndex) : undefined}
      data-value={value} disabled={disabled} title="Choose a run setup"
      onBlur={event => { if (!menuRef.current?.contains(event.relatedTarget as Node)) setOpen(false); }}
      onClick={() => open ? setOpen(false) : openMenu()}
      onKeyDown={event => {
        if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); setOpen(false); return; }
        if (event.key === 'Tab') { if (open) choose(highlight, false); return; }
        if (event.altKey && event.key === 'ArrowUp' && open) { event.preventDefault(); choose(highlight); return; }
        if (event.altKey && event.key === 'ArrowDown') { event.preventDefault(); if (!open) openMenu(); return; }
        if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'PageUp', 'PageDown'].includes(event.key)) {
          event.preventDefault();
          if (!open && event.key === 'ArrowDown') { openMenu(); return; }
          setOpen(true);
          const current = enabled.findIndex(option => option.value === highlight);
          const index = event.key === 'Home' || !open && event.key === 'ArrowUp' ? 0 : event.key === 'End' ? enabled.length - 1
            : Math.max(0, Math.min(enabled.length - 1, current + (event.key === 'PageDown' ? 10 : event.key === 'PageUp' ? -10 : event.key === 'ArrowDown' ? 1 : -1)));
          setHighlight(enabled[index]?.value ?? ''); return;
        }
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault(); if (open) choose(highlight); else openMenu(); return;
        }
        if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
          event.preventDefault();
          const now = Date.now();
          const text = now - typed.current.time < 700 ? typed.current.text + event.key.toLowerCase() : event.key.toLowerCase();
          typed.current = { text, time: now };
          const repeated = [...text].every(character => character === event.key.toLowerCase());
          const matches = enabled.filter(option => option.label.toLowerCase().startsWith(repeated ? event.key.toLowerCase() : text));
          const next = repeated && text.length > 1 ? matches.findIndex(option => option.value === highlight) + 1 : 0;
          const match = matches[next % matches.length];
          if (match) { setOpen(true); setHighlight(match.value); }
        }
      }}>
      <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
      <span className="public-visually-hidden">{options.find(option => option.value === value)?.label ?? 'New setup…'}</span>
    </button>
    {open && createPortal(<div ref={menuRef} id={id} role="listbox" aria-label="Run setup choices" className="public-run-setup-menu"
      style={{ ...position, visibility: position ? 'visible' : 'hidden' }}>
      {groups.map(group => <div key={group} role={group ? 'group' : undefined} aria-label={group || undefined}>
        {group && <div className="public-run-setup-menu-group" aria-hidden="true">{group}</div>}
        {options.filter(option => (option.group ?? '') === group).map(option => <button key={option.value} type="button" role="option"
          id={optionId(options.indexOf(option))} data-value={option.value} aria-selected={option.value === value}
          data-highlighted={option.value === highlight ? 'true' : undefined} disabled={option.disabled} aria-disabled={option.disabled || undefined}
          tabIndex={-1} onMouseDown={event => event.preventDefault()} onMouseMove={() => !option.disabled && setHighlight(option.value)} onClick={() => choose(option.value)}>
          <span className="public-run-setup-menu-mark" aria-hidden="true">{option.value === '' ? '+' : option.value === value ? '✓' : ''}</span>
          <span>{option.label}</span>
        </button>)}
      </div>)}
    </div>, triggerRef.current?.closest('.public-coilem-shell') ?? document.body)}
  </>;
}
