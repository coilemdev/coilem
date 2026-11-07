import { useRef, useState } from 'react';
import { clampRpm, formatRpm, nativeRpmStep, shiftSteppedRpm, snapRpm, steppedRpm } from './rpmSteps';

/**
 * A small speed field: type the RPM, or use the arrow keys or the field's
 * up/down buttons (Shift+arrow steps by 10). Below 1 RPM it steps in tenths
 * (rpmSteps). A typed value outside the range is clamped when it is committed
 * (Enter or leaving the field); Escape puts back the speed from before the edit.
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
  const commit = (text: string) => {
    const parsed = Number(text);
    if (text.trim() !== '' && Number.isFinite(parsed)) onChange(clampRpm(parsed, min, max));
    setDraft(null);
  };
  return (
    <label className="public-rpm-field" title={title}>
      <span>{label}</span>
      <input
        type="number"
        inputMode={min < 1 ? 'decimal' : 'numeric'}
        min={min}
        max={max}
        step={nativeRpmStep(min)}
        value={draft ?? formatRpm(value)}
        aria-label={ariaLabel}
        onChange={(event) => {
          const text = event.target.value;
          setDraft(text);
          const parsed = Number(text);
          // Arrow keys and the up/down buttons give in-range numbers: apply them at once.
          if (text.trim() !== '' && Number.isFinite(parsed) && parsed >= min && parsed <= max) {
            const next = steppedRpm(value, parsed, min, max);
            onChange(next);
            // A step carried on to the next whole RPM (18.1 → 19) shows where it
            // landed, so the following step starts from there.
            if (next !== snapRpm(parsed)) setDraft(null);
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
            onChange(shiftSteppedRpm(value, event.key === 'ArrowUp', min, max));
            setDraft(null);
          }
        }}
      />
      <em>RPM</em>
    </label>
  );
}
