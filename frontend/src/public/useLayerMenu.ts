import { useEffect, useRef, type SyntheticEvent } from 'react';

/** Place the panel directly above its own More button, including inside a scrolling dock. */
function positionLayerMenu(menu: HTMLDetailsElement): void {
  if (!menu.open) return;
  const button = menu.querySelector('summary');
  const panel = menu.querySelector<HTMLElement>('.public-field-layer-controls');
  const anchor = panel?.offsetParent;
  if (!button || !panel || !(anchor instanceof HTMLElement)) return;
  const buttonBox = button.getBoundingClientRect();
  const anchorBox = anchor.getBoundingClientRect();
  panel.style.left = `${buttonBox.left - anchorBox.left + anchor.scrollLeft - anchor.clientLeft}px`;
  panel.style.bottom = `${anchorBox.bottom - buttonBox.top - anchor.scrollTop + 8}px`;
}

/** Native details toggling, plus outside-click and Escape dismissal. */
export function useLayerMenu() {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const dismissOutside = (event: PointerEvent) => {
      const menu = ref.current;
      if (menu?.open && event.target instanceof Node && !menu.contains(event.target)) menu.open = false;
    };
    const dismissEscape = (event: KeyboardEvent) => {
      const menu = ref.current;
      if (event.key !== 'Escape' || !menu?.open) return;
      menu.open = false;
      menu.querySelector('summary')?.focus();
    };
    const reposition = () => { if (ref.current) positionLayerMenu(ref.current); };
    document.addEventListener('pointerdown', dismissOutside, true);
    document.addEventListener('keydown', dismissEscape);
    document.addEventListener('scroll', reposition, true);
    window.addEventListener('resize', reposition);
    return () => {
      document.removeEventListener('pointerdown', dismissOutside, true);
      document.removeEventListener('keydown', dismissEscape);
      document.removeEventListener('scroll', reposition, true);
      window.removeEventListener('resize', reposition);
    };
  }, []);
  return { ref, onToggle: (event: SyntheticEvent<HTMLDetailsElement>) => positionLayerMenu(event.currentTarget) };
}
