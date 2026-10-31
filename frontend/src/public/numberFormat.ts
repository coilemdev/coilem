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
