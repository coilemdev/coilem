/**
 * Speed steps for the RPM fields (the Design preview and the solved-field
 * playback): tenths below 1 RPM, whole RPM from 1 up. A field whose minimum is
 * 1 or more never reaches the tenths, so it behaves as a whole-RPM field.
 */

/** The nearest speed on the steps: 0.34 → 0.3, 17.6 → 18. */
export function snapRpm(rpm: number): number {
  return rpm < 1 ? Math.round(rpm * 10) / 10 : Math.round(rpm);
}

export function clampRpm(rpm: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, snapRpm(rpm)));
}

/** The input's native step: tenths when the field reaches below 1 RPM. */
export function nativeRpmStep(min: number): number {
  return min < 1 ? 0.1 : 1;
}

/**
 * A new value from the input. The arrow keys and the up/down buttons move by the
 * native step (a tenth); from 1 RPM up a step is a whole RPM, so a tenth off a
 * whole number goes on to the next one in that direction: 18 → 18.1 becomes 19.
 */
export function steppedRpm(previous: number, next: number, min: number, max: number): number {
  const oneNativeStep = Math.abs(Math.abs(next - previous) - 0.1) < 1e-6;
  if (oneNativeStep && previous >= 1 && next >= 1 && !Number.isInteger(next)) {
    return clampRpm(next > previous ? Math.ceil(next) : Math.floor(next), min, max);
  }
  return clampRpm(next, min, max);
}

/** Shift+arrow: ten RPM at a time, stopping at 1 on the way down before the tenths. */
export function shiftSteppedRpm(value: number, up: boolean, min: number, max: number): number {
  if (up) return clampRpm(value < 1 ? 10 : value + 10, min, max);
  return clampRpm(value > 1 ? Math.max(1, value - 10) : min, min, max);
}

/** "0.3", "18". */
export function formatRpm(rpm: number): string {
  return rpm < 1 ? rpm.toFixed(1) : String(Math.round(rpm));
}
