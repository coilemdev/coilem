/**
 * Sector framing for thin-ring motors. An outrunner's active parts (stator
 * teeth, air gap, magnets, rotor ring) are the outer band of its circle; inside
 * is the unmodelled hub. Fitting the whole circle leaves that band small, so the
 * views open zoomed on the top of the ring instead, with Fit for the whole motor.
 */
import type { MotorConfig } from './model';

export interface RingMm {
  innerMm: number;
  outerMm: number;
}

export interface SectorView {
  scale: number;
  /** Pan in px from the view's transform origin, as useViewportNavigation applies it. */
  pan: { x: number; y: number };
  /** The turn, in degrees, from one sector to the next: about three quarters of the visible arc. */
  stepDeg: number;
}

/** A ring this thin (radial thickness over outer radius) wastes most of a full view on the hub. */
export const THIN_RING_MAX_FRACTION = 0.5;
/** The share of the view height the ring's thickness fills in the sector view. */
const RING_VIEW_FRACTION = 0.7;
const MIN_SECTOR_SCALE = 1.5;
const MAX_SECTOR_SCALE = 6;

/** The active ring of an outer-rotor design: hub bore to rotor OD. Null for inner rotors. */
export function outerRotorRing(config: MotorConfig | null | undefined): RingMm | null {
  if (!config || config.rotor_layout !== 'outer') return null;
  const innerMm = config.stator.ID_mm / 2;
  const outerMm = config.rotor.OD_mm / 2;
  return Number.isFinite(innerMm) && Number.isFinite(outerMm) && outerMm > innerMm && innerMm > 0
    ? { innerMm, outerMm }
    : null;
}

export function isThinRing(ring: RingMm | null): ring is RingMm {
  return ring !== null && (ring.outerMm - ring.innerMm) / ring.outerMm <= THIN_RING_MAX_FRACTION;
}

/**
 * Zoom and pan that put the ring at ``angleDeg`` (0 at the top, clockwise on
 * screen) in the middle of a view of this size, its thickness filling most of the
 * height. ``fittedOuterRadiusPx`` is the ring's outer radius in px at the view's
 * full-motor fit.
 */
export function sectorView(
  ring: RingMm | null,
  viewWidthPx: number,
  viewHeightPx: number,
  fittedOuterRadiusPx: number,
  angleDeg = 0,
): SectorView | null {
  if (!isThinRing(ring) || !(viewWidthPx > 0) || !(viewHeightPx > 0) || !(fittedOuterRadiusPx > 0)) return null;
  const pxPerMm = fittedOuterRadiusPx / ring.outerMm;
  const thicknessPx = (ring.outerMm - ring.innerMm) * pxPerMm;
  const midRadiusPx = 0.5 * (ring.outerMm + ring.innerMm) * pxPerMm;
  const scale = Math.min(MAX_SECTOR_SCALE, Math.max(MIN_SECTOR_SCALE, (RING_VIEW_FRACTION * viewHeightPx) / thicknessPx));
  // The ring point at this angle sits midRadiusPx from the origin; scaled about the
  // origin it moves scale times further out, and this pan brings it to the middle.
  const angle = (angleDeg * Math.PI) / 180;
  const pan = { x: -scale * midRadiusPx * Math.sin(angle), y: scale * midRadiusPx * Math.cos(angle) };
  const visibleArcRad = viewWidthPx / scale / midRadiusPx;
  const stepDeg = Math.min(90, Math.max(5, (0.75 * visibleArcRad * 180) / Math.PI));
  return { scale, pan, stepDeg };
}

/** A key that changes when the ring does, so a view re-frames for a new design. */
export function ringKey(ring: RingMm | null): string | null {
  return isThinRing(ring) ? `${ring.innerMm.toFixed(3)}:${ring.outerMm.toFixed(3)}` : null;
}
