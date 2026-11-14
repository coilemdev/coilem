import type { MotorConfig, PublicSolverId } from './model';
import { asPublicConfig } from './publicRequest';
import { parseTorqueSpeedSettings } from './torqueSpeedAnalysis';

const OPERATING_KEYS = ['rated_speed_rpm', 'current_amplitude_A', 'current_amplitude_convention',
  'current_angle_deg', 'magnet_temperature_C', 'winding_temperature_C', 'mechanical_loss_W',
  'excitation_mode', 'phase_connection', 'commutation_advance_deg', 'motor_input_dc_bus_V'] as const;
const NUMERICAL_KEYS = ['solve_quality', 'rotor_sweep_range_deg', 'rotor_step_deg', 'mesh_density',
  'mesh_source', 'mesher', 'corner_refinement', 'mesh_build', 'rotor_rotation_model', 'torque_method',
  'nonlinear_solver', 'linear_solver_preconditioner', 'max_nonlinear_iterations', 'magneto2d_workers'] as const;
const OUTPUT_KEYS = ['torque_sweep', 'back_emf', 'flux_density', 'cogging_torque', 'losses_efficiency',
  'torque_speed_envelope', 'thd_analysis'] as const;
type Parameters = MotorConfig['solve_params'];
export type SolveProfile = {
  id: string; version: number; name: string; builtin?: boolean;
  angleConvention: 'pyleecan_d_axis' | 'q_axis';
  referenceModel: MotorConfig['geometry_reference'] | null;
  referenceCase?: MotorConfig['reference_case'];
  referenceRevision?: string;
  physicalModel?: string;
  includesNumerics: boolean;
  solver?: PublicSolverId;
  parameters: Partial<Parameters>;
  outputs: MotorConfig['solve_options'];
  map: MotorConfig['torque_speed_analysis'];
};
export type SolveProfileDocument = { schema: 1; scope: string; profiles: SolveProfile[]; activeId: string | null; activeVersion: number | null };
export type RunSetupProvenance = { id: string; version: number; name: string; kind: 'reference' | 'user'; includes_numerics: boolean };
const copy = <T,>(v: T): T => v == null ? v : JSON.parse(JSON.stringify(v));
const record = (v: unknown): v is Record<string, unknown> => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  if (record(v)) return `{${Object.keys(v).sort().filter(k => v[k] !== undefined).map(k => `${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}`;
  return JSON.stringify(v);
}
function physicalModel(config: MotorConfig): string {
  return canonical({ topology: config.topology, rotor_layout: config.rotor_layout ?? 'inner',
    geometry_reference: config.geometry_reference ?? null, stator: config.stator, rotor: config.rotor,
    winding: config.winding, materials: config.materials });
}
export function newProfileDocument(scope: string = crypto.randomUUID()): SolveProfileDocument {
  return { schema: 1, scope, profiles: [], activeId: null, activeVersion: null };
}
export function captureProfile(config: MotorConfig, name: string, includesNumerics: boolean,
  solver: PublicSolverId, id: string = crypto.randomUUID(), version = 1): SolveProfile {
  config = asPublicConfig(config, solver) as unknown as MotorConfig;
  const parameters: Partial<Parameters> = {};
  for (const key of [...OPERATING_KEYS, ...(includesNumerics ? NUMERICAL_KEYS : [])]) {
    if (config.solve_params[key] !== undefined) Object.assign(parameters, { [key]: config.solve_params[key] });
  }
  parameters.magnet_temperature_C = config.solve_params.magnet_temperature_C ?? 20;
  parameters.winding_temperature_C = config.solve_params.winding_temperature_C ?? 20;
  parameters.mechanical_loss_W = config.solve_params.mechanical_loss_W ?? 0;
  if (includesNumerics) parameters.max_nonlinear_iterations = config.solve_params.max_nonlinear_iterations ?? 200;
  const cleanName = name.trim();
  if (!cleanName || cleanName.length > 100) throw new Error('Give the setup a name of 1–100 characters.');
  return { id, version, name: cleanName, includesNumerics, parameters, outputs: { ...copy(config.solve_options), ...(!includesNumerics ? { thd_analysis: false } : {}) },
    map: copy(config.torque_speed_analysis ?? null),
    angleConvention: config.geometry_reference === 'pyleecan_prius_2004' ? 'pyleecan_d_axis' : 'q_axis',
    referenceModel: config.geometry_reference ?? null,
    ...(config.geometry_reference ? { referenceCase: config.reference_case } : {}),
    ...(includesNumerics ? { solver } : {}) };
}
export function profileCompatible(profile: SolveProfile, config: MotorConfig): boolean {
  if (profile.referenceModel !== (config.geometry_reference ?? null)) return false;
  if (profile.angleConvention !== (config.geometry_reference === 'pyleecan_prius_2004' ? 'pyleecan_d_axis' : 'q_axis')) return false;
  if (profile.builtin && (profile.referenceRevision !== 'prius-2004-v1' || profile.physicalModel !== physicalModel(config))) return false;
  return true;
}
export function applyProfile(config: MotorConfig, profile: SolveProfile): MotorConfig {
  if (!profileCompatible(profile, config)) throw new Error('This setup uses a different reference model, revision or current-angle convention.');
  const parameters = { ...config.solve_params, ...copy(profile.parameters) };
  return { ...config, solve_params: parameters,
    solve_options: { ...copy(profile.outputs), thd_analysis: profile.outputs.back_emf && ['standard', 'fine'].includes(parameters.solve_quality) }, torque_speed_analysis: profile.map ? { ...copy(profile.map),
      preset: profile.includesNumerics ? profile.map.preset : config.torque_speed_analysis?.preset ?? 'preview' } : null,
    ...(profile.referenceModel ? { reference_case: profile.referenceCase } : {}) };
}
export function profileMatches(profile: SolveProfile, config: MotorConfig, solver: PublicSolverId): boolean {
  if (!profileCompatible(profile, config)) return false;
  const actual = captureProfile(config, profile.name, profile.includesNumerics, solver, profile.id, profile.version);
  return canonical(actual.parameters) === canonical(profile.parameters)
    && canonical(actual.outputs) === canonical(profile.outputs)
    && canonical(actual.map ? { ...actual.map, ...(!profile.includesNumerics ? { preset: null } : {}) } : null)
      === canonical(profile.map ? { ...profile.map, ...(!profile.includesNumerics ? { preset: null } : {}) } : null)
    && (!profile.includesNumerics || profile.solver === solver) && actual.referenceCase === profile.referenceCase;
}
export function profileProvenance(profile: SolveProfile | undefined, config: MotorConfig, solver: PublicSolverId): RunSetupProvenance | null {
  return profile && profileMatches(profile, config, solver) ? {
    id: profile.id, version: profile.version, name: profile.name, kind: profile.builtin ? 'reference' : 'user',
    includes_numerics: profile.includesNumerics,
  } : null;
}
export function builtinProfiles(noLoad: MotorConfig, loaded: MotorConfig): SolveProfile[] {
  return [[noLoad, 'Prius · no-load BEMF reference'], [loaded, 'Prius · loaded torque reference']].map(([value, name]) => {
    const config = value as MotorConfig;
    return { ...captureProfile(config, name as string, true, 'magneto2d', `builtin:${config.reference_case}`, 1),
      builtin: true, physicalModel: physicalModel(config), referenceRevision: 'prius-2004-v1' };
  });
}
export function saveProfile(doc: SolveProfileDocument, profile: SolveProfile): SolveProfileDocument {
  if (profile.builtin || profile.id.startsWith('builtin:')) throw new Error('Reference setups cannot be overwritten. Save a user copy instead.');
  const old = doc.profiles.find(p => p.id === profile.id);
  if (!old && doc.profiles.length >= 100) throw new Error('A design can hold up to 100 saved setups.');
  if (old && profile.version <= old.version) throw new Error('Updating a setup requires a new version.');
  if (doc.profiles.some(p => p.id !== profile.id && p.name.toLocaleLowerCase() === profile.name.toLocaleLowerCase())) throw new Error('A setup with that name already exists.');
  return { ...doc, profiles: [...doc.profiles.filter(p => p.id !== profile.id), copy(profile)], activeId: profile.id, activeVersion: profile.version };
}
export function parseProfileDocument(value: unknown): SolveProfileDocument | undefined {
  if (value == null) return undefined;
  if (!record(value) || value.schema !== 1 || typeof value.scope !== 'string' || value.scope.length > 200
    || !value.scope || !Array.isArray(value.profiles) || value.profiles.length > 100
    || !(value.activeId === null || typeof value.activeId === 'string')
    || !(value.activeVersion === null || (Number.isInteger(value.activeVersion) && (value.activeVersion as number) > 0))) throw new Error('This file has an unsupported run-setup format.');
  const profiles: SolveProfile[] = [];
  for (const raw of value.profiles) {
    if (!record(raw) || typeof raw.id !== 'string' || !raw.id || raw.id.length > 200 || raw.id.startsWith('builtin:')
      || raw.builtin || typeof raw.name !== 'string' || !raw.name.trim() || raw.name.length > 100
      || !Number.isInteger(raw.version) || (raw.version as number) < 1
      || typeof raw.includesNumerics !== 'boolean' || !record(raw.parameters) || !record(raw.outputs)
      || !['q_axis', 'pyleecan_d_axis'].includes(String(raw.angleConvention))
      || !new Set<unknown>([null, 'pyleecan_prius_2004', 'lrk_12s14p']).has(raw.referenceModel)
      || (raw.includesNumerics && !['magneto2d', 'elmer'].includes(String(raw.solver)))) throw new Error('This file has an invalid saved run setup.');
    const allowed = new Set<string>([...OPERATING_KEYS, ...(raw.includesNumerics ? NUMERICAL_KEYS : [])]);
    if (Object.entries(raw.parameters).some(([k, v]) => !allowed.has(k) || !(v === null || typeof v === 'boolean' || typeof v === 'string' || (typeof v === 'number' && Number.isFinite(v))))
      || OUTPUT_KEYS.some(k => typeof (raw.outputs as Record<string, unknown>)[k] !== 'boolean')
      || Object.keys(raw.outputs).some(k => !OUTPUT_KEYS.includes(k as typeof OUTPUT_KEYS[number]))) throw new Error('This file has invalid run-setup settings.');
    const enums: Record<string, readonly unknown[]> = {
      current_amplitude_convention: ['rms', 'peak', 'plateau'], excitation_mode: ['sinusoidal', 'ideal_six_step_120'],
      phase_connection: ['wye'], solve_quality: ['quick', 'standard', 'fine', 'custom'],
      mesh_density: ['coarse', 'normal', 'fine', 'very_fine'], mesh_source: ['native'], mesher: ['gmsh'],
      mesh_build: ['precise', 'fast'], rotor_rotation_model: ['remesh_per_step'], torque_method: ['contour', 'arkkio', 'weighted_stress'],
      nonlinear_solver: ['picard', 'newton'], linear_solver_preconditioner: ['direct', 'ic0', 'jacobi'],
    };
    const nullable = new Set(['magnet_temperature_C', 'winding_temperature_C', 'mechanical_loss_W']);
    for (const [key, v] of Object.entries(raw.parameters)) {
      const valid = enums[key] ? enums[key].includes(v)
        : key === 'corner_refinement' ? typeof v === 'boolean'
        : (nullable.has(key) && v === null) || (typeof v === 'number' && Number.isFinite(v));
      if (!valid) throw new Error('This file has invalid run-setup values.');
    }
    for (const key of ['rated_speed_rpm', 'current_amplitude_A', 'current_amplitude_convention', 'current_angle_deg', 'excitation_mode', 'phase_connection', 'commutation_advance_deg']) {
      if (!(key in raw.parameters)) throw new Error('This file has an incomplete run setup.');
    }
    const profile: SolveProfile = {
      id: raw.id, version: raw.version as number, name: raw.name.trim(), includesNumerics: raw.includesNumerics,
      angleConvention: raw.angleConvention as SolveProfile['angleConvention'], referenceModel: raw.referenceModel as SolveProfile['referenceModel'],
      parameters: copy(raw.parameters) as Partial<Parameters>, outputs: copy(raw.outputs) as MotorConfig['solve_options'],
      map: raw.map == null ? null : parseTorqueSpeedSettings(raw.map),
      ...(raw.includesNumerics ? { solver: raw.solver as PublicSolverId } : {}),
    };
    if (profile.referenceModel) {
      const cases = profile.referenceModel === 'pyleecan_prius_2004'
        ? ['prius-2004-tutorial-bemf-v1', 'prius-2004-loaded-torque-v1'] : [null, 'lrk-12s14p-fixed-current-v1'];
      if (!cases.includes(raw.referenceCase as string)) throw new Error('This setup names an incompatible reference case.');
      profile.referenceCase = raw.referenceCase as SolveProfile['referenceCase'];
    }
    if (profiles.some(p => p.id === profile.id || p.name.toLocaleLowerCase() === profile.name.toLocaleLowerCase())) throw new Error('This file has duplicate run setups.');
    profiles.push(profile);
  }
  return { schema: 1, scope: value.scope, profiles, activeId: value.activeId as string | null, activeVersion: value.activeVersion as number | null };
}
