/**
 * Keep the motor clear of a legend drawn over the right edge of the field view.
 * The motor is a circle fitted in a square (the smaller of the box's width and
 * height) centred in its box, so the box narrows from the right until the circle
 * clears every legend label at that label's height: first the motor moves left
 * at full size, and only when it already sits at the left edge does it shrink.
 * A label up in a corner, beside the circle's narrow top, costs no room.
 */

/** Space kept between the motor and the legend's nearest label. */
export const FIELD_LEGEND_GAP_PX = 8;

/** One legend label, in px from the view's left and top edges. */
export interface FieldLegendPart {
  left: number;
  top: number;
  bottom: number;
}

/**
 * Width of the box to fit the motor in so that it clears every legend part by
 * `gap` px; null when the centred motor already clears them.
 */
export function motorFitWidthBesideLegend(
  width: number,
  height: number,
  parts: readonly FieldLegendPart[],
  gap = FIELD_LEGEND_GAP_PX,
): number | null {
  if (!(width > 0) || !(height > 0) || parts.length === 0) return null;
  const clears = (boxWidth: number) => {
    const radius = Math.min(boxWidth, height) / 2;
    const centreX = boxWidth / 2;
    const centreY = height / 2;
    return parts.every((part) => {
      const dy = centreY < part.top ? part.top - centreY : centreY > part.bottom ? centreY - part.bottom : 0;
      if (dy >= radius) return true;
      return centreX + Math.sqrt(radius * radius - dy * dy) + gap <= part.left;
    });
  };
  if (clears(width)) return null;
  // Narrowing the box only moves the circle left or shrinks it, so the widest
  // box that clears is found by bisection.
  let low = 0;
  let high = width;
  while (high - low > 0.25) {
    const middle = (low + high) / 2;
    if (clears(middle)) low = middle;
    else high = middle;
  }
  return low > 0 ? Math.floor(low * 2) / 2 : null;
}
