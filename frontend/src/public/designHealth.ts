/** Invalid draft inputs cannot produce a passing winding check or a derived pitch. */
export function validSlotCount(slots: number): boolean {
  return Number.isInteger(slots) && slots >= 6 && slots <= 96;
}

export function slotPitchText(slots: number, diameterMm: number, outer: boolean): string {
  if (!validSlotCount(slots) || !Number.isFinite(diameterMm) || diameterMm <= 0) return 'Enter valid stator dimensions to calculate slot pitch.';
  return `slot pitch ${(360 / slots).toFixed(1)}° · ${outer ? 'tip' : 'bore'} pitch ${(Math.PI * diameterMm / slots).toFixed(1)} mm`;
}
