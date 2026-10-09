/**
 * The Dims layer's single definition: one list that both the readout overlay and
 * the canvas draw from, so a value and its line can never disagree.
 *
 * Angles are chosen per dimension to keep the annotations off each other. Radial
 * and arc dimensions are anchored to the drawn geometry where the drawing is the
 * authority — a tooth's angular centre comes from its own polygon rather than from
 * recomputed slot pitch, so the line lands on the tooth that is actually on screen.
 */
import type { GeometryPreview, MotorConfig } from './model';

export type DimensionId =
  | 'stator-od'
  | 'rotor-od'
  | 'bore'
  | 'airgap'
  | 'magnet-thickness'
  | 'magnet-width'
  | 'bore-tooth-width'
  | 'tooth-width-at-yoke'
  | 'bore-slot-opening'
  | 'slot-width-at-yoke'
  | 'yoke-thickness'
  | 'stack-length';

/** A straight measured span, in model mm. */
export interface DimensionSegment {
  kind: 'segment';
  from: [number, number];
  to: [number, number];
}

/** An arc measured along a radius, angles in radians. */
export interface DimensionArc {
  kind: 'arc';
  radiusMm: number;
  startRad: number;
  endRad: number;
}

export type DimensionShape = DimensionSegment | DimensionArc;

export interface DimensionAnnotation {
  id: DimensionId;
  label: string;
  value: string;
  /** Dash rhythm, mirrored by the readout swatch so a row points at one line. */
  dash: number[];
  /** Empty for dimensions a cross-section cannot show, i.e. stack length. */
  shapes: DimensionShape[];
  /** Said in the readout when there is no line to point at. */
  note?: string;
}

/**
 * Drawn when nothing is picked: the two that orient you in the cross-section.
 * The other seven appear on demand — nine lines at once buried the motor they
 * measure, and a click that only brightened an already-drawn line read as nothing
 * having happened.
 */
export const RESTING_DIMENSIONS: DimensionId[] = ['stator-od', 'rotor-od'];

const polar = (radiusMm: number, angleRad: number): [number, number] => [
  radiusMm * Math.cos(angleRad),
  radiusMm * Math.sin(angleRad),
];

const diameter = (radiusMm: number, angleRad: number): DimensionSegment => ({
  kind: 'segment',
  from: polar(radiusMm, angleRad + Math.PI),
  to: polar(radiusMm, angleRad),
});

const radialSpan = (
  innerMm: number,
  outerMm: number,
  angleRad: number,
): DimensionSegment => ({
  kind: 'segment',
  from: polar(innerMm, angleRad),
  to: polar(outerMm, angleRad),
});

/** A chord of `lengthMm` centred on `angleRad`, laid across the radius. */
const tangentialSpan = (
  radiusMm: number,
  angleRad: number,
  lengthMm: number,
): DimensionSegment => {
  const halfRad = lengthMm / 2 / Math.max(radiusMm, 1e-6);
  return {
    kind: 'segment',
    from: polar(radiusMm, angleRad - halfRad),
    to: polar(radiusMm, angleRad + halfRad),
  };
};

interface RegionAngles {
  centreRad: number;
  halfWidthRad: number;
  innerMm: number;
  outerMm: number;
}

/** Angular centre, angular half-width and radial extent of a drawn region. */
function regionAngles(points: Array<[number, number]>): RegionAngles | null {
  if (!points.length) return null;
  let sumX = 0;
  let sumY = 0;
  let innerMm = Infinity;
  let outerMm = 0;
  for (const [x, y] of points) {
    sumX += x;
    sumY += y;
    const r = Math.hypot(x, y);
    if (r < innerMm) innerMm = r;
    if (r > outerMm) outerMm = r;
  }
  const centreRad = Math.atan2(sumY / points.length, sumX / points.length);
  // Widest angular offset from the centroid direction, unwrapped so a region
  // straddling the +/-pi seam does not read as nearly a full turn.
  let halfWidthRad = 0;
  for (const [x, y] of points) {
    let delta = Math.atan2(y, x) - centreRad;
    while (delta > Math.PI) delta -= 2 * Math.PI;
    while (delta < -Math.PI) delta += 2 * Math.PI;
    halfWidthRad = Math.max(halfWidthRad, Math.abs(delta));
  }
  return { centreRad, halfWidthRad, innerMm, outerMm };
}

function firstRegionAngles(
  geometry: GeometryPreview | null,
  matches: (regionType: string) => boolean,
): RegionAngles | null {
  for (const region of geometry?.regions ?? []) {
    if (!matches(region.region_type)) continue;
    const angles = regionAngles(region.points as Array<[number, number]>);
    if (angles) return angles;
  }
  return null;
}

function firstRegionPoints(
  geometry: GeometryPreview | null,
  matches: (regionType: string) => boolean,
): Array<[number, number]> | null {
  for (const region of geometry?.regions ?? []) {
    if (matches(region.region_type)) return region.points as Array<[number, number]>;
  }
  return null;
}

/**
 * Angles at which a region's outline crosses `radiusMm`, sorted.
 *
 * This is how a tangential dimension gets its ends from the shape itself: a tooth
 * is a tapered wedge, so its width is only defined at a stated radius, and taking
 * the crossings there puts the line's ticks on the flanks that are drawn.
 */
function radiusCrossings(points: Array<[number, number]>, radiusMm: number): number[] {
  const polarPoints = points.map(([x, y]) => ({ r: Math.hypot(x, y), a: Math.atan2(y, x) }));
  const crossings: number[] = [];
  for (let i = 0; i < polarPoints.length; i += 1) {
    const start = polarPoints[i];
    const end = polarPoints[(i + 1) % polarPoints.length];
    if ((start.r - radiusMm) * (end.r - radiusMm) >= 0) continue;
    // Unwrap the step so an edge crossing the +/-pi seam interpolates the short way.
    let delta = end.a - start.a;
    while (delta > Math.PI) delta -= 2 * Math.PI;
    while (delta < -Math.PI) delta += 2 * Math.PI;
    const t = (radiusMm - start.r) / (end.r - start.r);
    crossings.push(start.a + delta * t);
  }
  return crossings.sort((a, b) => a - b);
}

const deg = (value: number) => (value * Math.PI) / 180;

interface ToothMeasurement {
  /** Tangential width of the drawn tooth at the sampled radius, in mm. */
  widthMm: number;
  radiusMm: number;
  /** Angles of the two flanks at that radius. */
  flanks: [number, number];
}

export interface StatorSectionWidths {
  borePitchMm: number;
  yokePitchMm: number;
  boreToothWidthMm: number;
  toothWidthAtYokeMm: number;
  slotWidthAtYokeMm: number;
  narrowestToothWidthMm: number;
}

const metadataWidth = (
  geometry: GeometryPreview | null,
  key: string,
  fallback: number,
): number => {
  const value = geometry?.metadata?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
};

/**
 * The two stator sections users reason about, derived from the existing schema.
 *
 * No derived value here is persisted: the UI converts its bore-tooth control to
 * the existing slot_opening_mm field, tooth_width_mm remains the tooth body beside
 * the yoke, and these values expose both complementary widths.
 */
export function deriveStatorSectionWidths(
  config: MotorConfig,
  geometry: GeometryPreview | null = null,
): StatorSectionWidths {
  const slots = Math.max(1, config.stator.slot_count);
  const boreRadiusMm = config.stator.ID_mm / 2;
  const yokeRadiusMm = Math.max(
    boreRadiusMm,
    config.stator.OD_mm / 2 - config.stator.yoke_thickness_mm,
  );
  const borePitchMm = (2 * Math.PI * boreRadiusMm) / slots;
  const yokePitchMm = (2 * Math.PI * yokeRadiusMm) / slots;
  const boreOpeningMm = Math.max(
    0.5,
    Math.min(config.stator.slot_opening_mm, borePitchMm * 0.998),
  );
  const toothShoeAdditionMm = config.stator.tooth_shoe_enabled
    ? 2 * Math.max(0, config.stator.tooth_shoe_overhang_mm ?? 0)
    : 0;
  const fallbackBoreToothMm = Math.max(
    0,
    Math.min(borePitchMm, borePitchMm - boreOpeningMm + toothShoeAdditionMm),
  );
  const fallbackSlotAtYokeMm = Math.max(
    0.5,
    yokePitchMm - config.stator.tooth_width_mm,
  );
  const fallbackToothAtYokeMm = Math.max(0, yokePitchMm - fallbackSlotAtYokeMm);
  const boreToothWidthMm = metadataWidth(
    geometry,
    'bore_tooth_width_mm',
    fallbackBoreToothMm,
  );
  const toothWidthAtYokeMm = metadataWidth(
    geometry,
    'tooth_width_at_yoke_mm',
    fallbackToothAtYokeMm,
  );
  const slotWidthAtYokeMm = metadataWidth(
    geometry,
    'slot_width_at_yoke_mm',
    fallbackSlotAtYokeMm,
  );
  return {
    borePitchMm,
    yokePitchMm,
    boreToothWidthMm,
    toothWidthAtYokeMm,
    slotWidthAtYokeMm,
    narrowestToothWidthMm: metadataWidth(
      geometry,
      'narrowest_tooth_width_mm',
      Math.min(boreToothWidthMm, toothWidthAtYokeMm),
    ),
  };
}

function measureToothAtFraction(
  geometry: GeometryPreview | null,
  fraction: number,
): ToothMeasurement | null {
  const points = firstRegionPoints(geometry, (t) => t.includes('tooth'));
  const angles = points ? regionAngles(points) : null;
  if (!points || !angles) return null;
  const span = angles.outerMm - angles.innerMm;
  if (span <= 0) return null;
  const boundedFraction = Math.max(0, Math.min(1, fraction));
  const radiusMm = angles.innerMm + span * (0.001 + 0.998 * boundedFraction);
  const crossings = radiusCrossings(points, radiusMm);
  if (crossings.length < 2) return null;
  const first = crossings[0];
  const last = crossings[crossings.length - 1];
  return {
    widthMm: (last - first) * radiusMm,
    radiusMm,
    flanks: [first, last],
  };
}

export function buildDimensionAnnotations(
  config: MotorConfig,
  geometry: GeometryPreview | null,
): DimensionAnnotation[] {
  const metadata = (geometry?.metadata ?? {}) as Record<string, unknown>;
  const statorOuterMm = config.stator.OD_mm / 2;
  const boreMm = config.stator.ID_mm / 2;
  const rotorMm = config.rotor.OD_mm / 2;
  const isSpm = config.topology === 'SPM';
  const magnetOuterMm = isSpm ? rotorMm + config.rotor.magnet_thickness_mm : rotorMm;
  const airgapMm = typeof metadata.airgap_mm === 'number'
    ? metadata.airgap_mm
    : Math.max(0, boreMm - magnetOuterMm);

  const tooth = firstRegionAngles(geometry, (t) => t.includes('tooth'));
  const magnet = firstRegionAngles(geometry, (t) => t.startsWith('magnet_'));
  const statorWidths = deriveStatorSectionWidths(config, geometry);

  const mm = (value: number, digits = 1) => `${value.toFixed(digits)} mm`;
  const annotations: DimensionAnnotation[] = [
    {
      id: 'stator-od',
      label: 'Stator Ø',
      value: mm(config.stator.OD_mm),
      dash: [7, 4],
      shapes: [diameter(statorOuterMm, 0)],
    },
    {
      id: 'rotor-od',
      label: 'Rotor Ø',
      value: mm(config.rotor.OD_mm),
      dash: [2, 3],
      shapes: [diameter(rotorMm, Math.PI / 2)],
    },
    {
      id: 'bore',
      label: 'Bore Ø',
      value: mm(config.stator.ID_mm),
      dash: [5, 3],
      shapes: [diameter(boreMm, deg(-45))],
    },
    {
      id: 'airgap',
      label: 'Airgap',
      value: mm(airgapMm, 2),
      dash: [1, 2],
      // Radially between the magnet face and the bore. About a millimetre, so it
      // is a couple of pixels until zoomed — the highlight is what finds it.
      shapes: [radialSpan(magnetOuterMm, boreMm, deg(20))],
    },
  ];

  if (isSpm && magnet) {
    annotations.push({
      id: 'magnet-thickness',
      label: 'Magnet t',
      value: mm(config.rotor.magnet_thickness_mm),
      dash: [3, 2],
      shapes: [radialSpan(rotorMm, magnetOuterMm, magnet.centreRad)],
    });
    annotations.push({
      id: 'magnet-width',
      label: 'Magnet w',
      value: mm(config.rotor.magnet_width_mm),
      dash: [6, 3],
      shapes: [{
        kind: 'arc',
        radiusMm: magnetOuterMm,
        startRad: magnet.centreRad - magnet.halfWidthRad,
        endRad: magnet.centreRad + magnet.halfWidthRad,
      }],
    });
  }

  if (tooth) {
    const boreTooth = measureToothAtFraction(geometry, 0);
    const yokeTooth = measureToothAtFraction(geometry, 1);
    const yokeRadiusMm = statorOuterMm - config.stator.yoke_thickness_mm;
    const slotPitchRad = (2 * Math.PI) / Math.max(1, config.stator.slot_count);
    const slotCentreRad = tooth.centreRad + slotPitchRad / 2;
    annotations.push({
      id: 'bore-tooth-width',
      label: 'Bore tooth',
      value: mm(boreTooth?.widthMm ?? statorWidths.boreToothWidthMm),
      dash: [4, 3],
      shapes: [boreTooth
        ? {
          kind: 'segment',
          from: polar(boreTooth.radiusMm, boreTooth.flanks[0]),
          to: polar(boreTooth.radiusMm, boreTooth.flanks[1]),
        }
        : tangentialSpan(boreMm, tooth.centreRad, statorWidths.boreToothWidthMm)],
      note: 'controlled by Bore Tooth Width',
    });
    annotations.push({
      id: 'tooth-width-at-yoke',
      label: 'Yoke tooth',
      value: mm(yokeTooth?.widthMm ?? statorWidths.toothWidthAtYokeMm),
      dash: [7, 3],
      shapes: [yokeTooth
        ? {
          kind: 'segment',
          from: polar(yokeTooth.radiusMm, yokeTooth.flanks[0]),
          to: polar(yokeTooth.radiusMm, yokeTooth.flanks[1]),
        }
        : tangentialSpan(yokeRadiusMm, tooth.centreRad, statorWidths.toothWidthAtYokeMm)],
      note: 'controlled by Yoke Tooth Width',
    });
    annotations.push({
      id: 'bore-slot-opening',
      label: 'Bore opening',
      value: mm(config.stator.slot_opening_mm),
      dash: [2, 2],
      shapes: [tangentialSpan(boreMm, slotCentreRad, config.stator.slot_opening_mm)],
      note: 'calculated from bore pitch minus the bore tooth width',
    });
    annotations.push({
      id: 'slot-width-at-yoke',
      label: 'Slot at yoke',
      value: mm(statorWidths.slotWidthAtYokeMm),
      dash: [1, 3],
      shapes: [tangentialSpan(yokeRadiusMm, slotCentreRad, statorWidths.slotWidthAtYokeMm)],
      note: 'calculated from yoke pitch minus the yoke-side tooth width',
    });
  }

  annotations.push({
    id: 'yoke-thickness',
    label: 'Yoke thickness',
    value: mm(config.stator.yoke_thickness_mm),
    dash: [5, 4],
    shapes: [radialSpan(
      statorOuterMm - config.stator.yoke_thickness_mm,
      statorOuterMm,
      deg(200),
    )],
  });

  annotations.push({
    id: 'stack-length',
    label: 'Stack length',
    value: mm(config.stator.stack_length_mm, 0),
    dash: [],
    // Axial: there is nothing to point at in a cross-section.
    shapes: [],
    note: 'along the axis',
  });

  return annotations;
}
