import { useRef, useState } from 'react';

/**
 * A small speed field: type the RPM, or use the arrow keys or the field's
 * up/down buttons (Shift+arrow steps by 10). A typed value outside the range
 * is clamped when it is committed (Enter or leaving the field); Escape puts
 * back the speed from before the edit.
 */
export function RpmField({
  value,
  min,
  max,
  label,
  ariaLabel,
  title,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  label: string;
  ariaLabel: string;
  title: string;
  onChange: (rpm: number) => void;
}) {
  // What is typed, until it is committed; null shows the current value.
  const [draft, setDraft] = useState<string | null>(null);
  const valueBeforeEditRef = useRef(value);
  const cancelledRef = useRef(false);
  const clamp = (rpm: number) => Math.min(max, Math.max(min, Math.round(rpm)));
  const commit = (text: string) => {
    const parsed = Number(text);
    if (text.trim() !== '' && Number.isFinite(parsed)) onChange(clamp(parsed));
    setDraft(null);
  };
  return (
    <label className="public-rpm-field" title={title}>
      <span>{label}</span>
      <input
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        step={1}
        value={draft ?? String(Math.round(value))}
        aria-label={ariaLabel}
        onChange={(event) => {
          const text = event.target.value;
          setDraft(text);
          const parsed = Number(text);
          // Arrow keys and the up/down buttons give in-range numbers: apply them at once.
          if (text.trim() !== '' && Number.isFinite(parsed) && parsed >= min && parsed <= max) {
            onChange(Math.round(parsed));
          }
        }}
        onFocus={() => {
          valueBeforeEditRef.current = value;
        }}
        onBlur={(event) => {
          if (cancelledRef.current) {
            cancelledRef.current = false;
            return;
          }
          commit(event.currentTarget.value);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            commit(event.currentTarget.value);
            event.currentTarget.blur();
          } else if (event.key === 'Escape') {
            cancelledRef.current = true;
            onChange(valueBeforeEditRef.current);
            setDraft(null);
            event.currentTarget.blur();
          } else if ((event.key === 'ArrowUp' || event.key === 'ArrowDown') && event.shiftKey) {
            event.preventDefault();
            onChange(clamp(value + (event.key === 'ArrowUp' ? 10 : -10)));
            setDraft(null);
          }
        }}
      />
      <em>RPM</em>
    </label>
  );
}
