import { createPublicExampleDesign } from './exampleDesigns';
import { cloneDefaultConfig, type GeometryPreview, type MotorConfig, type PreviewRegion, type RotorLayout } from './model';
import { concentratedLayoutIsBalanced, concentratedUsesToothCoils } from './toothCoils';

export const DESIGN_PARTS = [
  { id: 'stator', label: 'Stator yoke' }, { id: 'slots', label: 'Slots' },
  { id: 'teeth', label: 'Tooth profile' }, { id: 'rotor', label: 'Rotor' },
  { id: 'magnets', label: 'Magnets' }, { id: 'winding', label: 'Winding' },
] as const;
export type BuiltParts = Partial<Record<typeof DESIGN_PARTS[number]['id'], boolean>>;
export interface DesignIssue {
  label: string;
  message: string;
  section?: string;
}
export function designPartsComplete(parts?: BuiltParts | null): boolean {
  return !parts || DESIGN_PARTS.every(({ id }) => parts[id]);
}

export function maximumShoeOverhangMm(config: MotorConfig): number {
  return Math.max(0, Math.min(15, Math.floor(((config.stator.slot_opening_mm - 0.1) / 2) * 10) / 10));
}

export function shoeOverhangLimitNotice(config: MotorConfig): string | null {
  if (!config.stator.tooth_shoe_enabled) return null;
  const limit = maximumShoeOverhangMm(config);
  if ((config.stator.tooth_shoe_overhang_mm ?? 0) < limit - 1e-6) return null;
  const gap = Math.max(0, config.stator.slot_opening_mm - 2 * limit);
  const value = Number(limit.toFixed(2));
  return limit < 15
    ? `Maximum ${value} mm per side: ${gap.toFixed(2)} mm of slot mouth remains. More overhang would bring adjacent tooth shoes together. Increase the tooth-body opening to allow more.`
    : 'Maximum supported shoe overhang is 15 mm per side.';
}

export function revealEditedPart(parts: BuiltParts, section: string, field: string): BuiltParts {
  if (section === 'stator') {
    if (field === 'slot_count') return { ...parts, stator: true, slots: true };
    if (/tooth|slot_opening/.test(field)) return { ...parts, stator: true, slots: true, teeth: true };
    return { ...parts, stator: true };
  }
  // Choosing an IPM layout doesn't confirm its hidden rotor dimensions.
  if (section === 'rotor' && field === 'ipm_topology') return parts;
  if (section === 'rotor') return { ...parts, rotor: true, ...(/pole_count|magnet|bridge|pocket|v_angle|v_depth/.test(field) ? { magnets: true } : {}) };
  if (section === 'winding') return { ...parts, winding: true };
  return parts;
}

export function acceptDesignSection(parts: BuiltParts, section: string): BuiltParts {
  if (section === 'stator') return { ...parts, stator: true, slots: true };
  if (section === 'advanced') return { ...parts, stator: true, slots: true, teeth: true };
  if (section === 'rotor') return { ...parts, rotor: true, magnets: true };
  if (section === 'winding') return { ...parts, winding: true };
  return parts;
}

export function newBuildConfig(layout: RotorLayout): MotorConfig {
  if (layout === 'outer') return createPublicExampleDesign('spm-outrunner-14p12s').config;
  const config = cloneDefaultConfig();
  config.rotor_layout = 'inner';
  config.stator = { OD_mm: 100, ID_mm: 60, slot_count: 12, stack_length_mm: 50,
    slot_opening_mm: 2, tooth_width_mm: 9, yoke_thickness_mm: 8,
    tooth_shoe_enabled: false, tooth_shoe_height_mm: 1, tooth_shoe_overhang_mm: 0.75 };
  config.rotor = { ...config.rotor, OD_mm: 50, ID_mm: 20, pole_count: 8,
    magnet_thickness_mm: 4, magnet_embrace: 0.75, magnet_width_mm: 15.904312808798327 };
  config.winding = { type: 'concentrated', layers: 1, turns_per_coil: 10, parallel_paths: 1 };
  config.solve_params = { ...config.solve_params, current_amplitude_A: 24.3,
    current_amplitude_convention: 'peak', rated_speed_rpm: 7000,
    motor_input_dc_bus_V: 96, magnet_temperature_C: 60, winding_temperature_C: 100 };
  return config;
}

/** Adapt unentered defaults; touching one field does not confirm its siblings. */
export function fitUnbuiltParts(config: MotorConfig, built: BuiltParts, fields?: Record<string, boolean>): MotorConfig {
  const next = structuredClone(config);
  const s = next.stator;
  const r = next.rotor;
  const outer = next.rotor_layout === 'outer';
  if (!built.teeth) {
    const bodyRadius = outer ? s.ID_mm / 2 + s.yoke_thickness_mm : s.OD_mm / 2 - s.yoke_thickness_mm;
    const pitch = 2 * Math.PI * bodyRadius / s.slot_count;
    s.tooth_width_mm = Number(Math.max(outer ? 0.5 : 2, Math.min(pitch - 0.5, pitch * (outer ? 0.28 : 0.41))).toFixed(2));
    const facePitch = Math.PI * (outer ? s.OD_mm : s.ID_mm) / s.slot_count;
    s.slot_opening_mm = Number(Math.max(outer ? 0.5 : 2, Math.min(outer ? 4 : 2, facePitch - 0.5)).toFixed(2));
  }
  if (!built.rotor) {
    if (outer) {
      r.ID_mm = s.OD_mm + 2 * (r.magnet_thickness_mm + 0.4);
      r.OD_mm = r.ID_mm + 3.2;
    } else {
      r.OD_mm = Math.max(15, s.ID_mm - 2 * ((next.topology === 'SPM' ? r.magnet_thickness_mm : 0) + 1));
      r.ID_mm = Math.min(20, r.OD_mm - 5);
    }
    const candidates = [r.pole_count, 8, 14, 10, 6, 4, 12, 16, 20, 28, 32];
    r.pole_count = candidates.find((p) => concentratedLayoutIsBalanced(s.slot_count, p, outer ? 2 : 1)) ?? r.pole_count;
  }
  // The new-design UI has no shaft-bore input yet. Keep that hidden default
  // inside a small inner rotor rather than blocking an otherwise valid OD.
  if (fields && !outer) r.ID_mm = Math.min(20, r.OD_mm - 5);
  const thicknessEntered = fields ? Boolean(fields['rotor:Magnet Thick.']) : Boolean(built.magnets);
  const widthEntered = fields ? Boolean(fields['rotor:Magnet Width']) : Boolean(built.magnets);
  if (!thicknessEntered) {
    const room = outer ? ((r.ID_mm ?? 0) - s.OD_mm) / 2 : next.topology === 'IPM' ? r.OD_mm / 4 : (s.ID_mm - r.OD_mm) / 2;
    r.magnet_thickness_mm = Math.max(outer ? 0.1 : 2, Math.min(r.magnet_thickness_mm, room - (outer ? 0.15 : 0.5), outer ? Infinity : r.OD_mm / 4));
  }
  if (!widthEntered) {
    const radius = outer ? (r.ID_mm ?? 0) / 2 - r.magnet_thickness_mm / 2 : next.topology === 'IPM'
      ? r.OD_mm / 2 - r.bridge_thickness_mm - (r.pocket_clearance_mm ?? 0) - r.magnet_thickness_mm / 2
      : r.OD_mm / 2 + r.magnet_thickness_mm / 2;
    r.magnet_width_mm = 2 * Math.PI * radius / r.pole_count * r.magnet_embrace;
  }
  if (!built.winding) {
    next.winding.parallel_paths = 1;
    const layers = [next.winding.layers, 1, 2].find((n) => (
      (n === 1 || concentratedUsesToothCoils(s.slot_count, r.pole_count))
      && concentratedLayoutIsBalanced(s.slot_count, r.pole_count, n)
    ));
    next.winding.type = layers ? 'concentrated' : 'distributed';
    next.winding.layers = layers ?? 2;
    next.winding.coil_span = null;
  }
  return next;
}

/** A new pole count keeps the current coverage and thickness where they fit. */
export function fitPoleMagnets(previous: MotorConfig, next: MotorConfig, built: BuiltParts, fields?: Record<string, boolean>): MotorConfig {
  const config = structuredClone(next);
  if (built.magnets && previous.topology === 'SPM') {
    const radius = previous.rotor_layout === 'outer'
      ? (previous.rotor.ID_mm ?? 0) / 2 - previous.rotor.magnet_thickness_mm / 2
      : previous.rotor.OD_mm / 2 + previous.rotor.magnet_thickness_mm / 2;
    const pitch = 2 * Math.PI * radius / previous.rotor.pole_count;
    if (pitch > 0) config.rotor.magnet_embrace = Math.max(0.1, Math.min(0.95, previous.rotor.magnet_width_mm / pitch));
  }
  return fitUnbuiltParts(config, { ...built, rotor: true, magnets: false }, fields && { ...fields, 'rotor:Magnet Width': false });
}

export function signedBuildAirgap(config: MotorConfig): number {
  return config.rotor_layout === 'outer'
    ? ((config.rotor.ID_mm ?? 0) - config.stator.OD_mm) / 2 - config.rotor.magnet_thickness_mm
    : (config.stator.ID_mm - config.rotor.OD_mm) / 2 - (config.topology === 'SPM' ? config.rotor.magnet_thickness_mm : 0);
}

/** Stage-local checks do not flag components that the user has not added yet. */
export function buildIssues(config: MotorConfig, built: BuiltParts): DesignIssue[] {
  const s = config.stator;
  const r = config.rotor;
  const outer = config.rotor_layout === 'outer';
  const issues: DesignIssue[] = [];
  const add = (section: string, label: string, message: string) => issues.push({ section, label, message });
  if (built.stator) {
    if (s.OD_mm < 10 || s.OD_mm > 500) add('stator', 'Outer Diameter', 'Stator outer diameter must be between 10 and 500 mm.');
    if (s.ID_mm < 2 || s.ID_mm >= s.OD_mm) add('stator', outer ? 'Hub Bore (ID)' : 'Bore Diameter (ID)', 'The bore / hub diameter must be at least 2 mm and smaller than the stator outer diameter.');
    if (s.yoke_thickness_mm < 0.5 || s.yoke_thickness_mm >= (s.OD_mm - s.ID_mm) / 2) add('stator', 'Yoke Thickness', 'The yoke must leave radial space for the slots. Reduce yoke thickness or bore diameter, or increase the outer diameter.');
    if (s.stack_length_mm < 2 || s.stack_length_mm > 300) add('stator', 'Stack Length', 'Stack length must be between 2 and 300 mm.');
  }
  if (built.slots && (!Number.isInteger(s.slot_count) || s.slot_count < 6 || s.slot_count > 96 || s.slot_count % 3 !== 0)) add('stator', 'Slot Count', 'Use a whole slot count from 6 to 96, divisible by three for this three-phase builder (for example, 12, 15 or 18).');
  if (built.slots) {
    const bodyRadius = outer ? s.ID_mm / 2 + s.yoke_thickness_mm : s.OD_mm / 2 - s.yoke_thickness_mm;
    if (s.tooth_width_mm >= 2 * Math.PI * bodyRadius / s.slot_count - 0.3) add('advanced', 'Yoke Tooth Width', 'The tooth is too wide to leave a winding pocket. Reduce tooth width or slot count.');
    if (s.slot_opening_mm >= Math.PI * (outer ? s.OD_mm : s.ID_mm) / s.slot_count) add('advanced', outer ? 'Slot Opening' : 'Bore Tooth Width', 'The slot opening exceeds the available tooth pitch.');
  }
  if (built.teeth) {
    if (s.slot_opening_mm < (outer ? 0.5 : 2)) add('advanced', outer ? 'Slot Opening' : 'Bore Tooth Width', `The tooth-body opening must be at least ${outer ? '0.5' : '2'} mm.`);
    if (s.tooth_shoe_enabled && 2 * (s.tooth_shoe_overhang_mm ?? 0) >= s.slot_opening_mm) add('advanced', 'Shoe Overhang', 'Adjacent tooth shoes overlap. Reduce the overhang or widen the body opening.');
    if (s.tooth_shoe_enabled && (s.tooth_shoe_height_mm ?? 0) > (s.OD_mm - s.ID_mm) / 2 - s.yoke_thickness_mm - 0.5) add('advanced', 'Shoe Height', 'The tooth shoe is too deep for the available slot depth.');
  }
  if (built.rotor) {
    if ((r.ID_mm ?? 0) >= r.OD_mm || (r.ID_mm ?? 0) < 0 || r.OD_mm < 15 || r.OD_mm > 450) add('rotor', 'Rotor OD', 'Rotor OD must exceed its inner diameter, within 15–450 mm.');
    if (r.pole_count < 2 || r.pole_count > 64 || r.pole_count % 2 !== 0) add('rotor', 'Pole Count', 'Use an even pole count from 2 to 64.');
    if (outer ? (r.ID_mm ?? 0) <= s.OD_mm : r.OD_mm >= s.ID_mm) add('rotor', outer ? 'Magnet Seat' : 'Rotor OD', 'The rotor steel overlaps the stator. Review the rotor diameters.');
  }
  if (built.magnets) {
    const min = outer ? 0.1 : 2;
    if (r.magnet_thickness_mm < min || r.magnet_thickness_mm > 50) add('rotor', 'Magnet Thick.', `Magnet thickness must be between ${min} and 50 mm.`);
    const gap = signedBuildAirgap(config);
    if (gap < (outer ? 0.1 : 0.3)) add('rotor', 'Magnet Thick.', gap <= 0 ? `Magnets intersect the stator by ${Math.abs(gap).toFixed(2)} mm. Reduce thickness or change rotor size.` : `Only ${gap.toFixed(2)} mm of airgap remains; increase the clearance.`);
    if (config.topology === 'SPM') {
      const radius = outer ? (r.ID_mm ?? 0) / 2 - r.magnet_thickness_mm / 2 : r.OD_mm / 2 + r.magnet_thickness_mm / 2;
      const pitch = 2 * Math.PI * radius / r.pole_count;
      if (r.magnet_width_mm > pitch + 1e-9) add('rotor', 'Magnet Width', `The entered magnet width exceeds the ${pitch.toFixed(2)} mm pole pitch at this rotor size. Reduce magnet width or increase the rotor size to avoid overlapping magnets.`);
    }
    if (r.magnet_embrace <= 0 || r.magnet_embrace >= 1) add('rotor', 'Magnet Width', 'Magnet coverage must be greater than 0% and less than 100%.');
  }
  if (built.winding) {
    if (!Number.isInteger(config.winding.turns_per_coil) || config.winding.turns_per_coil < 1) add('winding', 'Turns / Coil', 'Turns per coil must be a positive whole number.');
    if (!Number.isInteger(config.winding.parallel_paths) || config.winding.parallel_paths < 1) add('winding', 'Parallel Paths', 'Parallel paths must be a positive whole number.');
  }
  return issues;
}

function circle(radius: number): Array<[number, number]> {
  return Array.from({ length: 181 }, (_, i) => [radius * Math.cos(i * Math.PI / 90), radius * Math.sin(i * Math.PI / 90)]);
}

/** The yoke and bare rotor are exact annuli; slotted steel and magnets use the backend preview. */
export function progressiveGeometry(config: MotorConfig, built: BuiltParts, preview: GeometryPreview | null, fields?: Record<string, boolean>): GeometryPreview {
  const outer = config.rotor_layout === 'outer';
  const visibleMagnets = Boolean(built.magnets || built.rotor && preview?.metadata?.diagnostic_rotor);
  const bareRotor = built.rotor && !visibleMagnets;
  let regions: PreviewRegion[] = [];
  const enteredOd = Boolean(fields?.['stator:Outer Diameter']);
  if (enteredOd && !built.stator) regions.push({ region_type: 'construction_outline', points: circle(config.stator.OD_mm / 2) });
  if (built.stator) {
    const inner = outer ? config.stator.ID_mm / 2 : config.stator.OD_mm / 2 - config.stator.yoke_thickness_mm;
    const radius = outer ? inner + config.stator.yoke_thickness_mm : config.stator.OD_mm / 2;
    if (inner > 0 && radius > inner) regions.push({ region_type: 'stator_yoke', points: circle(radius), loops: [circle(radius), circle(inner)], fill: '#8A9BAD' });
  }
  if (preview) {
    regions = [
      ...(built.slots ? preview.regions.filter((r) => /stator/i.test(r.region_type)) : regions),
      ...preview.regions.filter((r) => {
        const type = r.region_type;
        if (/stator/i.test(type)) return false;
        if (/magnet/i.test(type)) return visibleMagnets;
        if (/pocket/i.test(type)) return visibleMagnets;
        if (/rotor|shaft/i.test(type)) return Boolean(built.rotor) && !bareRotor;
        if (/^airgap$/i.test(type)) return Boolean(built.magnets);
        if (/slot|winding|coil/i.test(type)) return Boolean(built.winding);
        return false;
      }),
    ];
  }
  // Until magnets are entered this part is just an exact iron annulus. Draw it
  // from the current OD so it and its dimension agree during a debounced preview.
  if (bareRotor) {
    const radius = config.rotor.OD_mm / 2;
    const inner = (config.rotor.ID_mm ?? 0) / 2;
    if (radius > inner && inner >= 0) {
      regions.push({ region_type: 'rotor_core', points: circle(radius), loops: inner > 0 ? [circle(radius), circle(inner)] : [circle(radius)], fill: '#536174' });
      if (!outer && inner > 0) regions.push({ region_type: 'shaft', points: circle(inner), fill: '#303846' });
    }
  }
  return { regions,
    stator_guide: (built.stator || enteredOd) && !built.slots ? {
      outerDiameterMm: config.stator.OD_mm, innerDiameterMm: config.stator.ID_mm,
      yokeThicknessMm: config.stator.yoke_thickness_mm, outerRotor: outer,
      boreConfigured: !fields || Boolean(fields[outer ? 'stator:Hub Bore (ID)' : 'stator:Bore Diameter (ID)']),
      yokeConfigured: !fields || Boolean(fields['stator:Yoke Thickness']),
    } : undefined,
    winding_layout: built.winding ? preview?.winding_layout : [],
    metadata: { ...preview?.metadata, topology: config.topology, rotor_layout: config.rotor_layout,
      stator_od_mm: config.stator.OD_mm, slot_count: config.stator.slot_count },
    validation_errors: [], generation_time_ms: 0 };
}
