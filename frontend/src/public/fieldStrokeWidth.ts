/**
 * Field-view strokes (field lines, mesh edges) are drawn in model millimetres, so
 * a fixed width looks several times heavier on a 30 mm outrunner than on a
 * 200 mm motor. The widths were tuned on the 200 mm example; smaller views thin
 * them in proportion and larger views keep them as they are.
 */

/** View size (mm) the stroke widths were tuned on: the 200 mm example with its 2.5 % padding. */
export const FIELD_STROKE_REFERENCE_VIEW_MM = 210;

/** Factor (at most 1) for the field view's stroke widths in a view of this size, mm. */
export function fieldStrokeScale(viewWidthMm: number, viewHeightMm: number): number {
  const size = Math.max(viewWidthMm, viewHeightMm);
  if (!Number.isFinite(size) || size <= 0) return 1;
  return Math.min(1, size / FIELD_STROKE_REFERENCE_VIEW_MM);
}
