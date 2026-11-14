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
  | 'v-angle'
  | 'v-depth'
  | 'outer-bridge'
  | 'bore-tooth-width'
  | 'tooth-width-at-yoke'
  | 'bore-slot-opening'
  | 'slot-width-at-yoke'
  | 'yoke-thickness'
  | 'shoe-height'
  | 'shoe-overhang'
  | 'rotor-back-iron'
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
  centerMm?: [number, number];
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

/** Parameter names share the same measurements as the Dims overlay. */
export function designFieldDimension(section: string, label: string): DimensionId | null {
  if (!['stator', 'advanced', 'rotor'].includes(section)) return null;
  const fields: Record<string, DimensionId> = {
    'Outer Diameter': 'stator-od', 'Bore Diameter (ID)': 'bore', 'Hub Bore (ID)': 'bore',
    'Yoke Thickness': 'yoke-thickness', 'Yoke Thick.': 'yoke-thickness', 'Stack Length': 'stack-length',
    'Rotor OD': 'rotor-od', 'Magnet Thick.': 'magnet-thickness', 'Magnet Width': 'magnet-width',
    'V Angle': 'v-angle', 'V Depth': 'v-depth', 'Outer Bridge': 'outer-bridge', 'Minimum Outer Bridge': 'outer-bridge',
    'Bore Tooth Width': 'bore-tooth-width', 'Yoke Tooth Width': 'tooth-width-at-yoke', 'Slot Opening': 'bore-slot-opening',
    'Back Iron': 'rotor-back-iron',
    'Shoe Height': 'shoe-height', 'Shoe Overhang': 'shoe-overhang',
  };
  return fields[label] ?? null;
}

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

/** Tooth widths follow an arc at the exact section used by the field. */
const toothWidthArc = (radiusMm: number, centreRad: number, widthMm: number): DimensionArc => ({
  kind: 'arc', radiusMm,
  startRad: centreRad - widthMm / (2 * Math.max(radiusMm, 1e-6)),
  endRad: centreRad + widthMm / (2 * Math.max(radiusMm, 1e-6)),
});

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

const deg = (value: number) => (value * Math.PI) / 180;

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
 * A stored stator width as Advanced Geometry shows it (#154). Widths derived
 * from a reference geometry, such as the pinned Pyleecan Prius tooth from its
 * SlotW11 slot, keep full float precision; only the display rounds them, and
 * the design and the solve request keep the exact value. Inputs keep two
 * decimals so a width typed to 0.05 mm still reads as typed.
 */
export const SHOWN_WIDTH_INPUT_DECIMALS = 2;

export function shownWidthMm(valueMm: number, decimals = SHOWN_WIDTH_INPUT_DECIMALS): number {
  return Number.isFinite(valueMm) ? Number(valueMm.toFixed(decimals)) : valueMm;
}

/** The collapsed Advanced Geometry summary: every width to one decimal, as the bore tooth. */
export function advancedGeometrySummary(config: MotorConfig, widths: Pick<StatorSectionWidths, 'boreToothWidthMm'>): string {
  const mm = (value: number) => shownWidthMm(value, 1).toFixed(1);
  return `bore tooth ${mm(widths.boreToothWidthMm)} · yoke tooth ${mm(config.stator.tooth_width_mm)} · yoke ${mm(config.stator.yoke_thickness_mm)}`;
}

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
  // "Bore" is the stator's air-gap face: its OD on an outer rotor, where the
  // teeth point outward and the yoke sits on the hub (backend geometry_drawer).
  const outerRotor = config.rotor_layout === 'outer';
  const boreRadiusMm = outerRotor ? config.stator.OD_mm / 2 : config.stator.ID_mm / 2;
  const yokeRadiusMm = outerRotor
    ? Math.min(boreRadiusMm, config.stator.ID_mm / 2 + config.stator.yoke_thickness_mm)
    : Math.max(
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

export function buildDimensionAnnotations(
  config: MotorConfig,
  geometry: GeometryPreview | null,
): DimensionAnnotation[] {
  if (config.rotor_layout === 'outer') return addShoeDimensions(buildOuterRotorDimensionAnnotations(config, geometry), config, geometry);
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

  if (!isSpm) addIpmMagnetDimensions(annotations, config, geometry);

  if (tooth) {
    const yokeRadiusMm = statorOuterMm - config.stator.yoke_thickness_mm;
    const slotPitchRad = (2 * Math.PI) / Math.max(1, config.stator.slot_count);
    const slotCentreRad = tooth.centreRad + slotPitchRad / 2;
    annotations.push({
      id: 'bore-tooth-width',
      label: 'Bore tooth',
      value: mm(statorWidths.boreToothWidthMm),
      dash: [4, 3],
      shapes: [toothWidthArc(boreMm, tooth.centreRad, statorWidths.boreToothWidthMm)],
      note: 'controlled by Bore Tooth Width',
    });
    annotations.push({
      id: 'tooth-width-at-yoke',
      label: 'Yoke tooth',
      value: mm(statorWidths.toothWidthAtYokeMm, 2),
      dash: [7, 3],
      shapes: [toothWidthArc(yokeRadiusMm, tooth.centreRad, statorWidths.toothWidthAtYokeMm)],
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

  return addShoeDimensions(annotations, config, geometry);
}

/** Measure the actual rectangular slab, along and normal to its long axis. */
function addIpmMagnetDimensions(annotations: DimensionAnnotation[], config: MotorConfig, geometry: GeometryPreview | null): void {
  if (!['flat_buried', 'v_shape'].includes(config.rotor.ipm_topology)
    || config.rotor.ipm_topology === 'flat_buried' && config.rotor.flat_buried_magnet_shape === 'legacy_arc') return;
  const points = firstRegionPoints(geometry, (type) => type.startsWith('magnet_'));
  if (!points || points.length < 4) return;
  const edges = points.map((point, index) => {
    const next = points[(index + 1) % points.length];
    return { x: next[0] - point[0], y: next[1] - point[1], length: Math.hypot(next[0] - point[0], next[1] - point[1]) };
  }).filter((edge) => edge.length > 1e-6);
  const edge = edges.sort((a, b) => Math.abs(a.length - config.rotor.magnet_width_mm) - Math.abs(b.length - config.rotor.magnet_width_mm))[0];
  if (!edge) return;
  const axis: [number, number] = [edge.x / edge.length, edge.y / edge.length];
  const normal: [number, number] = [-axis[1], axis[0]];
  const along = points.map(([x, y]) => x * axis[0] + y * axis[1]);
  const across = points.map(([x, y]) => x * normal[0] + y * normal[1]);
  const lo = Math.min(...along), hi = Math.max(...along), bottom = Math.min(...across), top = Math.max(...across);
  const at = (a: number, n: number): [number, number] => [a * axis[0] + n * normal[0], a * axis[1] + n * normal[1]];
  annotations.push({ id: 'magnet-width', label: 'Magnet Width', value: `${(hi - lo).toFixed(1)} mm`, dash: [6, 3],
    shapes: [{ kind: 'segment', from: at(lo, (bottom + top) / 2), to: at(hi, (bottom + top) / 2) }] });
  annotations.push({ id: 'magnet-thickness', label: 'Magnet Thick.', value: `${(top - bottom).toFixed(1)} mm`, dash: [3, 2],
    shapes: [{ kind: 'segment', from: at((lo + hi) / 2, bottom), to: at((lo + hi) / 2, top) }] });
  const rotorRadius = config.rotor.OD_mm / 2;
  if (config.rotor.ipm_topology === 'v_shape') {
    const poleAngle = deg(config.rotor.magnet_angle_deg);
    const apexRadius = rotorRadius - config.rotor.v_depth_mm;
    const apex = polar(apexRadius, poleAngle);
    const half = deg(config.rotor.v_angle_deg / 2);
    const radius = Math.max(1, Math.min(config.rotor.magnet_width_mm * 0.6, rotorRadius * 0.3));
    annotations.push({ id: 'v-depth', label: 'V Depth', value: `${config.rotor.v_depth_mm.toFixed(1)} mm`, dash: [5, 3],
      shapes: [radialSpan(apexRadius, rotorRadius, poleAngle)] });
    annotations.push({ id: 'v-angle', label: 'V Angle', value: `${config.rotor.v_angle_deg.toFixed(1)}°`, dash: [4, 3],
      shapes: [{ kind: 'arc', centerMm: apex, radiusMm: radius, startRad: poleAngle - half, endRad: poleAngle + half },
        ...[-half, half].map((angle): DimensionSegment => ({ kind: 'segment', from: apex,
          to: [apex[0] + radius * Math.cos(poleAngle + angle), apex[1] + radius * Math.sin(poleAngle + angle)] }))] });
  }
  if (['v_shape', 'flat_buried'].includes(config.rotor.ipm_topology)) {
    // Outer Bridge is steel outside the pocket, including its air clearance;
    // measuring from the magnet would incorrectly add that clearance to it.
    const pocket = firstRegionPoints(geometry, (type) => type.includes('pocket')) ?? points;
    const corner = pocket.reduce((furthest, point) => Math.hypot(...point) > Math.hypot(...furthest) ? point : furthest);
    const radius = Math.hypot(...corner);
    annotations.push({ id: 'outer-bridge', label: config.rotor.ipm_topology === 'v_shape' ? 'Actual Outer Bridge' : 'Outer Bridge', value: `${(rotorRadius - radius).toFixed(2)} mm`, dash: [4, 3],
      shapes: [radialSpan(radius, rotorRadius, Math.atan2(corner[1], corner[0]))] });
  }
}

/** The IR defines shoe height radially and overhang as an arc at the gap face. */
function addShoeDimensions(annotations: DimensionAnnotation[], config: MotorConfig, geometry: GeometryPreview | null): DimensionAnnotation[] {
  if (!config.stator.tooth_shoe_enabled) return annotations;
  const tooth = firstRegionAngles(geometry, (t) => t.includes('tooth'));
  if (!tooth) return annotations;
  const s = config.stator;
  const outer = config.rotor_layout === 'outer';
  const gapRadius = (outer ? s.OD_mm : s.ID_mm) / 2;
  const bodyRadius = outer ? s.ID_mm / 2 + s.yoke_thickness_mm : s.OD_mm / 2 - s.yoke_thickness_mm;
  const height = Math.min(s.tooth_shoe_height_mm ?? 0, Math.abs(bodyRadius - gapRadius) - 1e-6);
  if (gapRadius <= 0 || height <= 0) return annotations;
  const shoulderRadius = gapRadius + (outer ? -height : height);
  const bodyHalf = Math.PI / s.slot_count - s.slot_opening_mm / (2 * gapRadius);
  const tipHalf = Math.min(bodyHalf + (s.tooth_shoe_overhang_mm ?? 0) / gapRadius, Math.PI / s.slot_count - 1e-9);
  annotations.push({
    id: 'shoe-height', label: 'Shoe height', value: `${height.toFixed(1)} mm`, dash: [3, 2],
    shapes: [radialSpan(gapRadius, shoulderRadius, tooth.centreRad)],
  }, {
    id: 'shoe-overhang', label: 'Shoe overhang / side', value: `${(s.tooth_shoe_overhang_mm ?? 0).toFixed(2)} mm`, dash: [3, 2],
    shapes: [{ kind: 'arc', radiusMm: gapRadius, startRad: tooth.centreRad + bodyHalf, endRad: tooth.centreRad + tipHalf }],
  });
  return annotations;
}

/**
 * The same callouts for an outer rotor (#257). The stator sits inside: its OD
 * is the air-gap face and its ID the hub bore, with the yoke on the hub and the
 * teeth pointing outward. The magnets sit on the rotor's inner face (rotor ID).
 */
function buildOuterRotorDimensionAnnotations(
  config: MotorConfig,
  geometry: GeometryPreview | null,
): DimensionAnnotation[] {
  const metadata = (geometry?.metadata ?? {}) as Record<string, unknown>;
  const gapFaceMm = config.stator.OD_mm / 2;
  const hubBoreMm = config.stator.ID_mm / 2;
  const rotorOuterMm = config.rotor.OD_mm / 2;
  const magnetSeatMm = (config.rotor.ID_mm ?? 0) / 2;
  const magnetFaceMm = magnetSeatMm - config.rotor.magnet_thickness_mm;
  const yokeRadiusMm = Math.min(gapFaceMm, hubBoreMm + config.stator.yoke_thickness_mm);
  const airgapMm = typeof metadata.airgap_mm === 'number'
    ? metadata.airgap_mm
    : Math.max(0, magnetFaceMm - gapFaceMm);

  const tooth = firstRegionAngles(geometry, (t) => t.includes('tooth'));
  const magnet = firstRegionAngles(geometry, (t) => t.startsWith('magnet_'));
  const statorWidths = deriveStatorSectionWidths(config, geometry);

  const mm = (value: number, digits = 1) => `${value.toFixed(digits)} mm`;
  const annotations: DimensionAnnotation[] = [
    {
      id: 'rotor-od',
      label: 'Rotor Ø',
      value: mm(config.rotor.OD_mm),
      dash: [2, 3],
      shapes: [diameter(rotorOuterMm, Math.PI / 2)],
    },
    {
      id: 'stator-od',
      label: 'Stator Ø',
      value: mm(config.stator.OD_mm),
      dash: [7, 4],
      shapes: [diameter(gapFaceMm, 0)],
    },
    {
      id: 'bore',
      label: 'Hub bore Ø',
      value: mm(config.stator.ID_mm),
      dash: [5, 3],
      shapes: [diameter(hubBoreMm, deg(-45))],
    },
    {
      id: 'airgap',
      label: 'Airgap',
      value: mm(airgapMm, 2),
      dash: [1, 2],
      shapes: [radialSpan(gapFaceMm, magnetFaceMm, deg(20))],
    },
  ];

  if (magnet && magnetSeatMm > 0) {
    annotations.push({
      id: 'magnet-thickness',
      label: 'Magnet t',
      value: mm(config.rotor.magnet_thickness_mm),
      dash: [3, 2],
      shapes: [radialSpan(magnetFaceMm, magnetSeatMm, magnet.centreRad)],
    });
    annotations.push({
      id: 'magnet-width',
      label: 'Magnet w',
      value: mm(config.rotor.magnet_width_mm),
      dash: [6, 3],
      shapes: [{
        kind: 'arc',
        radiusMm: magnetFaceMm,
        startRad: magnet.centreRad - magnet.halfWidthRad,
        endRad: magnet.centreRad + magnet.halfWidthRad,
      }],
    });
  }

  if (tooth) {
    // The tooth region runs outward from the yoke, so its far end is the air gap.
    const slotPitchRad = (2 * Math.PI) / Math.max(1, config.stator.slot_count);
    const slotCentreRad = tooth.centreRad + slotPitchRad / 2;
    annotations.push({
      id: 'bore-tooth-width',
      label: 'Gap tooth',
      value: mm(statorWidths.boreToothWidthMm, 2),
      dash: [4, 3],
      shapes: [toothWidthArc(gapFaceMm, tooth.centreRad, statorWidths.boreToothWidthMm)],
      note: 'the tooth tip at the air gap',
    });
    annotations.push({
      id: 'tooth-width-at-yoke',
      label: 'Yoke tooth',
      value: mm(statorWidths.toothWidthAtYokeMm, 2),
      dash: [7, 3],
      shapes: [toothWidthArc(yokeRadiusMm, tooth.centreRad, statorWidths.toothWidthAtYokeMm)],
      note: 'the tooth body where it meets the yoke',
    });
    annotations.push({
      id: 'bore-slot-opening',
      label: 'Slot opening',
      value: mm(config.stator.slot_opening_mm),
      dash: [2, 2],
      shapes: [tangentialSpan(gapFaceMm, slotCentreRad, config.stator.slot_opening_mm)],
      note: 'the gap between tooth tips at the air gap',
    });
  }

  annotations.push({
    id: 'yoke-thickness',
    label: 'Yoke thickness',
    value: mm(config.stator.yoke_thickness_mm),
    dash: [5, 4],
    shapes: [radialSpan(hubBoreMm, yokeRadiusMm, deg(200))],
  });

  if (magnetSeatMm > 0 && rotorOuterMm > magnetSeatMm) {
    annotations.push({
      id: 'rotor-back-iron',
      label: 'Rotor back iron',
      value: mm(rotorOuterMm - magnetSeatMm),
      dash: [3, 4],
      shapes: [radialSpan(magnetSeatMm, rotorOuterMm, deg(160))],
    });
  }

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
