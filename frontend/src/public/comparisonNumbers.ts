/**
 * Percentage change from the baseline. A baseline whose magnitude is at most
 * `floor` gives "—" (or 0.0% when nothing changed): a percentage of a zero or
 * near-zero baseline, such as the d-axis current of an all-q-axis run, says nothing.
 */
export function comparisonPercentDelta(left: number | null | undefined, right: number | null | undefined, floor = 1e-12): string {
  if (typeof left !== 'number' || typeof right !== 'number' || !Number.isFinite(left) || !Number.isFinite(right)) return '—';
  const difference = right - left;
  if (Math.abs(left) <= Math.max(floor, 1e-12)) return Math.abs(difference) <= 1e-12 ? '0.0%' : '—';
  const percentage = difference / Math.abs(left) * 100;
  const rounded = Number(percentage.toFixed(1));
  return `${rounded > 0 ? '+' : ''}${rounded.toFixed(1)}%`;
}

/** A delta never implies finer precision than the three-significant-figure values beside it. */
export function comparisonSignificantDelta(before: number | null, after: number | null, unit = ''): string {
  if (before === null || after === null || !Number.isFinite(before) || !Number.isFinite(after)) return '—';
  if (unit === '%') {
    const rounded = Number((after - before).toFixed(1));
    return `${rounded > 0 ? '+' : ''}${rounded.toFixed(1)}`;
  }
  const precisions = [before, after].filter(value => value !== 0)
    .map(value => 2 - Math.floor(Math.log10(Math.abs(Number(value.toPrecision(3))))));
  const digits = Math.min(12, precisions.length ? Math.min(...precisions) : 0);
  const fractionDigits = Math.max(0, digits);
  const scale = 10 ** -digits;
  const difference = Number((Math.round((after - before) / scale) * scale).toFixed(fractionDigits));
  const text = Math.abs(difference).toLocaleString(undefined, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
  return `${difference > 0 ? '+' : difference < 0 ? '−' : ''}${text}`;
}
