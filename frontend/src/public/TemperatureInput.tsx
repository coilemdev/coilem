import { useEffect, useState } from 'react';
import { differenceFrom, differenceIn, temperatureFrom, temperatureIn, type TemperatureUnit } from './thermalUnits';

/** Trim conversion noise: 37.777778 °C is shown as 100 °F, not 100.0000004. */
const tidy = (value: number) => String(Number(value.toFixed(4)));

/**
 * A number field for a temperature kept in °C (or a difference kept in K) and typed in the chosen unit.
 *
 * While the field has focus it shows exactly what was typed and the kept value
 * follows it, so a half-typed number is never rewritten under the cursor.
 */
export function TemperatureInput({ id, value, onChange, unit, kind = 'temperature', ariaLabel }: {
  id?: string;
  /** The kept value: °C for a temperature, K for a difference. */
  value: string;
  onChange: (kept: string) => void;
  unit: TemperatureUnit;
  kind?: 'temperature' | 'difference';
  ariaLabel: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  // A draft belongs to the unit it was typed in.
  useEffect(() => setDraft(null), [unit]);
  // A kelvin and a degree Celsius are the same step, so only Fahrenheit rescales a difference.
  const converts = unit === 'F' || (unit === 'K' && kind === 'temperature');
  const toShown = kind === 'temperature' ? temperatureIn : differenceIn;
  const toKept = kind === 'temperature' ? temperatureFrom : differenceFrom;
  const kept = Number(value);
  const shown = draft ?? (!converts || value.trim() === '' || !Number.isFinite(kept) ? value : tidy(toShown(kept, unit)));
  return <input id={id} className="param-number-input" aria-label={ariaLabel} type="number" step="any" value={shown}
    onChange={(event) => {
      const text = event.target.value;
      if (!converts) { onChange(text); return; }
      setDraft(text);
      const typed = Number(text);
      onChange(text.trim() === '' || !Number.isFinite(typed) ? text : String(Number(toKept(typed, unit).toFixed(6))));
    }}
    onBlur={() => setDraft(null)} />;
}
