import type { PublicApiError } from './api';
import type { PublicParameterSection } from './CoilEmWorkspace';
import type { MotorConfig } from './model';
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
  return [error.message, error.suggestion ?? ''].filter(Boolean).join(' ');
}

// Fields whose control sits outside the section their config group suggests.
const SECTION_BY_FIELD: Record<string, PublicParameterSection> = {
  'rotor.v_angle_deg': 'advanced',
  'rotor.v_depth_mm': 'advanced',
  'stator.slot_opening_mm': 'advanced',
  'stator.tooth_shoe_enabled': 'advanced',
  'stator.tooth_shoe_height_mm': 'advanced',
  'stator.tooth_shoe_overhang_mm': 'advanced',
  'stator.tooth_width_mm': 'advanced',
  'stator.yoke_thickness_mm': 'advanced',
  'solve_params.current_amplitude_A': 'winding',
};

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
