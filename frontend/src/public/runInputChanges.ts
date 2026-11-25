import { meshDensityLabel } from './meshLabels';
import { OPERATING_KEYS, canonical as stable, record } from './solveProfiles';

/** Stored inputs only: never merge these records with the open design or defaults. */
export interface ComparisonInputs {
  config?: Record<string, unknown> | null;
  solver?: string | null;
  solver_name?: string | null;
  run_setup?: { id?: string; name?: string; version?: number; kind?: string; includes_numerics?: boolean } | null;
}

export const INPUT_GROUPS = ['Geometry', 'Winding', 'Materials', 'Operating point', 'Accuracy and solver', 'Analyses', 'Saved setup', 'Other inputs'] as const;
type InputGroup = typeof INPUT_GROUPS[number];
export interface InputChange {
  path: string;
  group: InputGroup;
  label: string;
  before: string;
  after: string;
  missing: boolean;
}

const OPERATING = new Set<string>(OPERATING_KEYS);
/** An entry that one recorded run has and the other does not: unset, not unrecorded. */
const ABSENT = Symbol('absent');
/** Maps keyed by the user's own names: a missing key is an entry the run did not have. */
const NAMED_MAPS = new Set(['config.materials.custom_steels']);
/** Fields a saved config leaves out at their default (backend/models/config.py), so a run that
 * lacks one solved with that default, including runs saved before the field existed. A request
 * leaves rotor_iron_loss out whenever it is off (publicRequest.ts), so absent reads as Off (#333). */
const OMITTED_DEFAULTS: Record<string, string | boolean> = {
  'config.solve_params.symmetry': 'full', 'config.rotor_layout': 'inner', 'config.solve_options.rotor_iron_loss': false,
};
const LABELS: Record<string, string> = {
  'config.topology': 'Motor topology', 'config.rotor_layout': 'Rotor arrangement',
  'config.geometry_reference': 'Reference model', 'config.reference_case': 'Reference case',
  'config.stator.OD_mm': 'Stator outer diameter', 'config.stator.ID_mm': 'Stator bore diameter',
  'config.rotor.OD_mm': 'Rotor outer diameter', 'config.rotor.ID_mm': 'Shaft diameter',
  'config.rotor.magnet_thickness_mm': 'Magnet thickness',
  'config.solve_params.rated_speed_rpm': 'Speed', 'config.solve_params.current_amplitude_A': 'Phase current',
  'config.solve_params.current_amplitude_convention': 'Current convention',
  'config.solve_params.current_angle_deg': 'Current angle', 'config.solve_params.magnet_temperature_C': 'Magnet temperature',
  'config.solve_params.winding_temperature_C': 'Winding temperature',
  'config.solve_params.solve_quality': 'Effective accuracy plan', 'config.solve_params.mesh_density': 'Mesh density',
  'config.solve_params.rotor_step_deg': 'Electrical-angle step', 'config.solve_params.rotor_sweep_range_deg': 'Electrical-angle sweep',
  'config.solve_params.max_nonlinear_iterations': 'Maximum nonlinear iterations',
  'config.solve_params.nonlinear_solver': 'Nonlinear solver',
  'config.solve_params.linear_solver_preconditioner': 'Linear solver',
  'config.solve_params.corner_refinement': 'Corner refinement',
  'config.solve_params.mesh_build': 'Mesh build', 'config.solve_params.symmetry': 'Solved region',
  'config.solve_options.torque_sweep': 'Torque', 'config.solve_options.back_emf': 'Back EMF',
  'config.solve_options.flux_density': 'Field maps', 'config.solve_options.cogging_torque': 'Cogging torque',
  'config.solve_options.losses_efficiency': 'Losses and efficiency',
  'config.solve_options.rotor_iron_loss': 'Rotor iron loss',
  'config.solve_options.torque_speed_envelope': 'Torque–speed map', 'config.solve_options.thd_analysis': 'Harmonic analysis',
  solver: 'Selected solver', solver_name: 'Solver version', 'run_setup.name': 'Setup name',
  'run_setup.id': 'Setup identity', 'run_setup.version': 'Setup version', 'run_setup.kind': 'Setup kind',
  'run_setup.includes_numerics': 'Includes accuracy and solver settings',
};
const UNITS: Record<string, string> = { mm: 'mm', mm2: 'mm²', mm3: 'mm³', rpm: 'rpm', deg: '°',
  A: 'A', V: 'V', W: 'W', C: '°C', T: 'T', ohm: 'Ω', m: 'm', kg: 'kg', pct: '%' };
const words = (key: string) => key.replace(/_/g, ' ').replace(/\b(?:rpm|rms|thd|spm|ipm|dc)\b/gi, part => part.toUpperCase());
function groupFor(path: string): InputGroup {
  if (path === 'run_setup' || path.startsWith('run_setup.')) return 'Saved setup';
  const [, section, field] = path.split('.');
  if (['stator', 'rotor', 'topology', 'rotor_layout', 'geometry_reference', 'reference_case'].includes(section)) return 'Geometry';
  if (section === 'winding') return 'Winding';
  if (section === 'materials' || section === 'custom_steels') return 'Materials';
  if (section === 'solve_params') return OPERATING.has(field) ? 'Operating point' : 'Accuracy and solver';
  if (path === 'solver' || path === 'solver_name') return 'Accuracy and solver';
  if (section === 'solve_options' || section === 'torque_speed_analysis') return 'Analyses';
  return 'Other inputs';
}
function describe(path: string): { label: string; unit: string } {
  const parts = path.split('.');
  const field = parts[parts.length - 1];
  const suffix = field.slice(field.lastIndexOf('_') + 1);
  const unit = UNITS[suffix] ?? '';
  const skip = parts[0] === 'config' ? ['solve_params', 'solve_options'].includes(parts[1]) ? 2 : 1 : 0;
  const label = LABELS[path] ?? parts.slice(skip)
    .map((part, index, all) => words(index === all.length - 1 && unit ? part.slice(0, -suffix.length - 1) : part))
    .join(' · ').replace(/^./, letter => letter.toUpperCase());
  return { label, unit };
}
function format(value: unknown, path: string, unit: string): string {
  if (value === undefined) return 'Not recorded';
  if (value === null || value === ABSENT) return 'Not set';
  if (typeof value === 'boolean') return value ? 'On' : 'Off';
  if (typeof value === 'number') return `${value}${unit ? ` ${unit}` : ''}`;
  if (typeof value === 'string') {
    if (path === 'config.solve_params.solve_quality') return ({ quick: 'Preview', standard: 'Standard', fine: 'High accuracy', custom: 'Custom' })[value] ?? value;
    if (path === 'config.solve_params.symmetry') return ({ full: 'Full motor', auto: 'One sector' })[value] ?? value;
    if (path === 'config.solve_params.mesh_density') return meshDensityLabel(value) ?? value;
    return value || 'Empty';
  }
  return JSON.stringify(value);
}

/** Resolve a union-table cell from that run alone, including its own current convention. */
export function recordedInputValue(inputs: ComparisonInputs | null | undefined, path: string): string {
  let value: unknown = inputs ?? undefined;
  let parentPath = '';
  for (const key of path.split('.')) {
    if (Array.isArray(value)) value = Number(key) <= value.length ? value[Number(key) - 1] : ABSENT;
    else if (record(value) && key in value) value = value[key];
    else if (record(value) && `${parentPath}.${key}` in OMITTED_DEFAULTS) value = OMITTED_DEFAULTS[`${parentPath}.${key}`];
    else value = value === undefined || (record(value) && !NAMED_MAPS.has(parentPath) && !NAMED_MAPS.has(`${parentPath}.${key}`)) ? undefined : ABSENT;
    parentPath = parentPath ? `${parentPath}.${key}` : key;
    if (['config', 'run_setup'].includes(parentPath) && value === null) value = undefined;
  }
  let { unit } = describe(path);
  if (path === 'config.solve_params.current_amplitude_A') {
    const params = inputs?.config?.solve_params;
    const convention = record(params) ? params.current_amplitude_convention : undefined;
    unit = convention === 'rms' ? 'A rms' : convention === 'peak' ? 'A peak' : convention === 'plateau' ? 'A plateau' : unit;
  }
  return format(value, path, unit);
}

export function multipleInputChanges(inputs: Array<ComparisonInputs | null | undefined>) {
  const rows = new Map<string, InputChange>();
  const knownChanged = new Set<string>();
  for (const candidate of inputs.slice(1)) {
    for (const row of inputChanges(inputs[0], candidate)) {
      rows.set(row.path, row);
      if (!row.missing) knownChanged.add(row.path);
    }
  }
  return [...rows.values()].map(row => {
    const values = inputs.map(input => recordedInputValue(input, row.path));
    return { ...row, values, missing: values.includes('Not recorded'), knownChanged: knownChanged.has(row.path) };
  });
}

export function inputChanges(before?: ComparisonInputs | null, after?: ComparisonInputs | null): InputChange[] {
  const changes: InputChange[] = [];
  function add(left: unknown, right: unknown, path: string) {
    const { label, unit } = describe(path);
    const unitFor = (inputs?: ComparisonInputs | null) => {
      if (path !== 'config.solve_params.current_amplitude_A') return unit;
      const parameters = inputs?.config?.solve_params;
      const convention = record(parameters) ? parameters.current_amplitude_convention : undefined;
      return convention === 'rms' ? 'A rms' : convention === 'peak' ? 'A peak' : convention === 'plateau' ? 'A plateau' : unit;
    };
    changes.push({ path, label, group: groupFor(path), before: format(left, path, unitFor(before)), after: format(right, path, unitFor(after)),
      missing: left === undefined || right === undefined });
  }
  // Unset (null) and absent containers compare as empty, so a recorded value on one side reads
  // 'Not set' on the other, as do extra list entries and named-map entries. A schema field an
  // older snapshot lacks (undefined) reads 'Not recorded'.
  const empty = (value: unknown) => value === undefined || value === null || value === ABSENT;
  const field = (parent: unknown, key: string, path: string) => {
    if (record(parent) && key in parent) return parent[key];
    if (record(parent) && `${path}.${key}` in OMITTED_DEFAULTS) return OMITTED_DEFAULTS[`${path}.${key}`];
    if (parent === undefined || (record(parent) && !NAMED_MAPS.has(path) && !NAMED_MAPS.has(`${path}.${key}`))) return undefined;
    return ABSENT;
  };
  const entry = (parent: unknown, index: number) => parent === undefined ? undefined
    : Array.isArray(parent) && index < parent.length ? parent[index] : ABSENT;
  function visit(left: unknown, right: unknown, path: string) {
    if (stable(left) === stable(right)) return;
    if ((record(left) || empty(left)) && (record(right) || empty(right)) && (record(left) || record(right))) {
      const keys = [...new Set([...Object.keys(record(left) ? left : {}), ...Object.keys(record(right) ? right : {})])].sort();
      if (!keys.length) add(left, right, path);
      for (const key of keys) {
        if (path === 'config' && key === 'schema_version') continue;
        visit(field(left, key, path), field(right, key, path), `${path}.${key}`);
      }
    } else if ((Array.isArray(left) || empty(left)) && (Array.isArray(right) || empty(right)) && (Array.isArray(left) || Array.isArray(right))) {
      const length = Math.max(Array.isArray(left) ? left.length : 0, Array.isArray(right) ? right.length : 0);
      if (!length) add(left, right, path);
      for (let index = 0; index < length; index++) visit(entry(left, index), entry(right, index), `${path}.${index + 1}`);
    } else {
      add(left, right, path);
    }
  }
  // A run without a config snapshot is reported once by the table's notice, not field by field.
  if (before?.config && after?.config) visit(before.config, after.config, 'config');
  for (const key of ['solver', 'solver_name', 'run_setup'] as const) visit(before?.[key] ?? undefined, after?.[key] ?? undefined, key);
  return changes;
}
