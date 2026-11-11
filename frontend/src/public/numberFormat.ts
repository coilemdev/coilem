/**
 * Numbers for the Results tables, tiles and readouts: a fixed count of
 * significant figures that keeps its trailing zeros, so 1.40 kW and 0.140 mH
 * read with the same precision as 2.81 kW and 0.139 mH beside them.
 */

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** A value to `digits` significant figures with locale grouping; '—' when it is not a number. */
export function formatSignificant(value: number | null | undefined, digits = 3): string {
  if (!finite(value)) return '—';
  const rounded = Number(value.toPrecision(digits));
  if (rounded === 0) return '0';
  const decimals = Math.max(0, digits - 1 - Math.floor(Math.log10(Math.abs(rounded))));
  return rounded.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/**
 * Decimal places for a torque in N·m: two, as the cards have always shown
 * (12.23), and more for a small motor so the number keeps three significant
 * figures (0.241, 0.0612) instead of collapsing to one (#270).
 */
export function torqueDecimals(...references: Array<number | null | undefined>): number {
  const magnitudes = references.filter(finite).map(Math.abs).filter((value) => value > 0);
  if (magnitudes.length === 0) return 2;
  const largest = Math.max(...magnitudes);
  return Math.min(6, Math.max(2, 2 - Math.floor(Math.log10(largest))));
}

/** A torque in N·m at `decimals` places (default: its own {@link torqueDecimals}); '—' when it is not a number. */
export function formatTorqueNm(value: number | null | undefined, decimals?: number): string {
  if (!finite(value)) return '—';
  const text = value.toFixed(decimals ?? torqueDecimals(value));
  // A reading that rounds to zero reads 0.00, not -0.00.
  return Number(text) === 0 ? text.replace('-', '') : text;
}
