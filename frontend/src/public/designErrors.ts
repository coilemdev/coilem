import type { PublicApiError } from './api';
import type { PublicParameterSection } from './CoilEmWorkspace';
import type { MotorConfig } from './model';
import type { DesignIssue } from './progressiveDesign';
import { coilsPerPhase, concentratedUsesToothCoils, windingLayerOptions } from './toothCoils';

// backend/models/config.py WindingConfig.parallel_paths le=32 (#91).
const MAX_PARALLEL_PATHS = 32;

/** "1", "1 or 2", "1, 2 or 4". */
function joinChoices(values: number[]): string {
  if (values.length <= 1) return values.map(String).join('');
  return `${values.slice(0, -1).join(', ')} or ${values[values.length - 1]}`;
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/**
 * Plain wording for a parallel-paths error, built from the design itself.
 *
 * backend/geometry.py words this check with the field name and a Python list
 * ("parallel_paths=2 does not evenly divide the 1 coils per phase ... Use one
 * of: [1]"), and that file is hash-guarded physics source, so the wording is
 * replaced here. Null when the design does not show the fault (it was edited
 * since the request), so the backend's text is shown instead.
 */
export function parallelPathsMessage(config: MotorConfig): string | null {
  const paths = config.winding.parallel_paths;
  const slots = config.stator.slot_count;
  const poles = config.rotor.pole_count;
  const windingType = config.winding.type;
  const layers = config.winding.layers === 2 ? 2 : 1;
  const coils = coilsPerPhase(slots, poles, windingType, layers);
  if (paths <= 1 || coils <= 0 || coils % paths === 0) return null;

  const toothCoils = windingType !== 'distributed' && concentratedUsesToothCoils(slots, poles);
  const layout = windingType === 'distributed'
    ? `${slots} slots, distributed`
    : toothCoils && layers < 2
      ? `${slots} slots, coils on alternate teeth`
      : `${slots} slots, a coil on every tooth`;
  const choices = Array.from({ length: Math.min(MAX_PARALLEL_PATHS, coils) }, (_, index) => index + 1)
    .filter((candidate) => coils % candidate === 0);
  const fixes = [`use ${joinChoices(choices)} parallel ${choices.length === 1 && choices[0] === 1 ? 'path' : 'paths'}`];
  if (toothCoils && layers < 2) {
    const allTeethCoils = coilsPerPhase(slots, poles, windingType, 2);
    const allTeethAvailable = windingLayerOptions(slots, poles, windingType)
      .some((option) => option.layers === 2 && option.available);
    if (allTeethAvailable && allTeethCoils % paths === 0) {
      fixes.push(`set Wound teeth to All, which gives ${plural(allTeethCoils, 'coil')} per phase`);
    }
  }
  const fix = fixes.join(', or ');
  return `${plural(paths, 'parallel path')} can't split this winding evenly: it has ${plural(coils, 'coil')} per phase `
    + `(${layout}), and each path needs the same number of coils in series. `
    + `${fix.charAt(0).toUpperCase()}${fix.slice(1)}.`;
}

// /solve/validate reports the check without its field, flattened to this text.
const PARALLEL_PATHS_FAULT = /^parallel_paths=\d+ does not evenly divide /;

function isParallelPathsFault(error: PublicApiError): boolean {
  return error.field === 'winding.parallel_paths' || PARALLEL_PATHS_FAULT.test(error.message);
}

/** The text shown for a request error, with parallel-paths faults in plain words. */
export function designErrorText(error: PublicApiError, config: MotorConfig): string {
  if (isParallelPathsFault(error)) {
    const message = parallelPathsMessage(config);
    if (message) return message;
  }
  if (config.topology === 'IPM' && config.rotor.ipm_topology === 'v_shape') {
    const correction = error.suggestion?.match(/For these dimensions, try V Depth [\d.]+ mm\./)?.[0];
    if (/does not fit below the outer bridge|violates the outer bridge/.test(error.message)) {
      return 'The requested magnets extend beyond the rotor’s outer bridge. Increase V Depth to move the V apex inward, reduce Magnet Width to shorten the magnets, or reduce V Angle.' + (correction ? ` ${correction}` : '');
    }
    if (/overlaps the shaft\/inner-rotor margin/.test(error.message)) {
      return 'The requested magnet pockets enter the shaft clearance. Reduce V Depth to move the V apex outward, or reduce Magnet Width.' + (correction ? ` ${correction}` : '');
    }
  }
  return humanizeGeometryMessage([error.message, error.suggestion ?? ''].filter(Boolean).join(' '));
}

/** Keep request/schema identifiers out of field guidance and Design Health. */
export function humanizeGeometryMessage(message: string): string {
  const labels: Record<string, string> = {
    magnet_embrace: 'Saved magnet coverage', v_depth_mm: 'V Depth', v_angle_deg: 'V Angle', magnet_width_mm: 'Magnet Width',
    magnet_thickness_mm: 'Magnet Thick.', inner_web_thickness_mm: 'Inner Web',
    outer_bridge_thickness_mm: 'Outer Bridge', bridge_thickness_mm: 'Outer Bridge',
    pocket_clearance_mm: 'Pocket Clearance', side_bridge_thickness_mm: 'Side Bridge',
    tooth_width_mm: 'Yoke Tooth Width', slot_opening_mm: 'Tooth Body Opening',
    yoke_thickness_mm: 'Yoke Thickness', pole_count: 'Pole Count', slot_count: 'Slot Count',
  };
  message = message.replace(/\b(stator|rotor|winding|Geometry)\.([A-Za-z0-9_]+)/g, (_token, group: string, field: string) => {
    const names: Record<string, string> = { 'stator.ID_mm': 'Bore Diameter', 'stator.OD_mm': 'Outer Diameter',
      'rotor.ID_mm': 'Shaft Bore', 'rotor.OD_mm': 'Rotor OD', stack_length_mm: 'Stack Length',
      Segment_count: 'Segment Count', Outer_radius: 'Outer Radius', Inner_radius: 'Bore Radius', Segment_gap_angle: 'Segment Gap Angle' };
    return names[`${group}.${field}`] ?? names[field] ?? labels[field] ?? field.replace(/_/g, ' ');
  });
  return message.replace(/\b(?:rotor\.|stator\.)?([a-z]+(?:_[a-z0-9]+)+)\b/g, (token, key: string) => labels[key] ?? token)
    .replace(/\brotor ID_mm\b/g, 'Shaft Bore').replace(/\brotor OD_mm\b/g, 'Rotor OD')
    .replace(/\bstator ID_mm\b/g, 'Bore Diameter').replace(/\bstator OD_mm\b/g, 'Outer Diameter')
    .replace(/ID_mm/g, 'Bore Diameter').replace(/OD_mm/g, 'Outer Diameter')
    .replace(/: Input should be greater than or equal to /g, ' must be at least ')
    .replace(/: Input should be less than or equal to /g, ' must be at most ')
    .replace(/\{'A': (\d+), 'B': (\d+), 'C': (\d+)\}/g, '$1 / $2 / $3 coils in phases A / B / C');
}

// Fields whose control sits outside the section their config group suggests.
const SECTION_BY_FIELD: Record<string, PublicParameterSection> = {
  'stator.slot_opening_mm': 'advanced',
  'stator.tooth_shoe_enabled': 'advanced',
  'stator.tooth_shoe_height_mm': 'advanced',
  'stator.tooth_shoe_overhang_mm': 'advanced',
  'stator.tooth_width_mm': 'advanced',
  'stator.yoke_thickness_mm': 'advanced',
  'solve_params.current_amplitude_A': 'winding',
};

/** Associate a backend fault with the progressive field that the user entered. */
export function enteredGeometryError(field: string | null | undefined, message: string): DesignIssue | null {
  const controls: Record<string, [PublicParameterSection, string]> = {
    'stator.OD_mm': ['stator', 'Outer Diameter'],
    'stator.ID_mm': ['stator', 'Bore Diameter (ID)'],
    // Backend slot-count faults describe winding balance, not invalid iron.
    'stator.yoke_thickness_mm': ['stator', 'Yoke Thickness'],
    'stator.slot_opening_mm': ['advanced', 'Bore Tooth Width'],
    'stator.tooth_width_mm': ['advanced', 'Yoke Tooth Width'],
    'stator.tooth_shoe_height_mm': ['advanced', 'Shoe Height'],
    'stator.tooth_shoe_overhang_mm': ['advanced', 'Shoe Overhang'],
    'rotor.OD_mm': ['rotor', 'Rotor OD'],
    'rotor.magnet_thickness_mm': ['rotor', 'Magnet Thick.'],
    'rotor.magnet_width_mm': ['rotor', 'Magnet Width'],
    'rotor.v_depth_mm': ['rotor', 'V Depth'],
    'rotor.v_angle_deg': ['rotor', 'V Angle'],
    'rotor.outer_bridge_thickness_mm': ['rotor', 'Outer Bridge'],
    'rotor.bridge_thickness_mm': ['rotor', 'Outer Bridge'],
  };
  const control = field ? controls[field] : null;
  return control ? { section: control[0], label: control[1], message } : null;
}

/** The Design section holding the field an error names, or null when it names none. */
export function designErrorSection(error: PublicApiError | null | undefined): PublicParameterSection | null {
  if (!error) return null;
  if (isParallelPathsFault(error)) return 'winding';
  const field = error.field;
  if (!field) return null;
  const mapped = SECTION_BY_FIELD[field];
  if (mapped) return mapped;
  const group = field.split('.')[0];
  if (group === 'stator' || group === 'rotor' || group === 'winding' || group === 'materials') return group;
  return null;
}
