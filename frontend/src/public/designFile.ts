import { migrateProjectFile, COILEM_SCHEMA_VERSION } from '../api/projectSchema';
import { applyPublicSolverSettings, cloneDefaultConfig, HOLEM50_FIELDS, PUBLIC_MAGNETO2D_SETTINGS } from './model';
import type { MotorConfig } from './model';
import { parseCustomSteels } from './customSteel';
import { PYLEECAN_REFERENCE_NOTICE } from './pyleecanReferenceNotice';

/**
 * Local `.coilem` design files, with legacy `.openem` import compatibility.
 *
 * The payload is the same plain JSON the desktop workflow writes:
 * `{ openem_schema_version, openem_version, name, ...config }`. Loading is
 * shape-tolerant on purpose: unknown keys are ignored, missing sections fall
 * back to the example design, a stator without tooth-shoe settings loads
 * without shoes (`LOADED_STATOR_FALLBACKS`), legacy solver choices normalize
 * to the supported Gmsh-native path, and files stamped by a newer schema
 * still load with their unknown settings dropped.
 *
 * It is the *same* format the desktop workflow reads, so the version and the
 * migrations come from `api/projectSchema` rather than being restated here.
 * They diverged once: this module declared 2 while the desktop app moved to 3,
 * so a design saved here was re-migrated on the way in (the v3 default's
 * 25.6mm tooth became 37.1mm) and an old v2 file opened here was never
 * migrated at all.
 */

export const DESIGN_FILE_EXTENSION = '.coilem';
export const DESIGN_FILE_ACCEPT = `${DESIGN_FILE_EXTENSION},.openem,.json,application/json`;
export const DESIGN_FILE_SCHEMA_VERSION = COILEM_SCHEMA_VERSION;
/** Application version stamped into saved designs; tests/test_public_candidate.py keeps it in sync. */
export const COILEM_APP_VERSION = '0.4.0';

export interface ParsedDesignFile {
  name: string | null;
  config: MotorConfig;
  declaredSchemaVersion: number;
  fromFuture: boolean;
  solverSettingsNotice: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

const WINDING_TYPES = new Set(['concentrated', 'distributed']);
const IPM_TOPOLOGIES = new Set(['flat_buried', 'v_shape', 'pyleecan_holem50']);
const FLAT_BURIED_MAGNET_SHAPES = new Set(['straight', 'legacy_arc']);
const SOLVE_QUALITIES = new Set(['quick', 'standard', 'fine', 'custom']);
const MESH_DENSITIES = new Set(['coarse', 'normal', 'fine', 'very_fine']);
const NONLINEAR_SOLVERS = new Set(['picard', 'newton']);
const CURRENT_CONVENTIONS = new Set(['rms', 'peak', 'plateau']);
const EXCITATION_MODES = new Set(['sinusoidal', 'ideal_six_step_120']);

/**
 * Backend defaults for stator fields that the starter motor sets differently.
 * A loaded file means what the backend reads from it, so a field the file
 * leaves out takes the backend default rather than the starter motor's value.
 * Bundled examples and designs saved before tooth shoes existed carry no shoe
 * settings and describe stators without shoes; inheriting the starter motor's
 * shoes narrowed their slot mouths, or closed them, as in the SPM 24p example.
 * tests/test_public_validation_fixtures.py keeps them equal to the backend's.
 */
export const LOADED_STATOR_FALLBACKS = {
  tooth_shoe_enabled: false,
  tooth_shoe_height_mm: 1.5,
  tooth_shoe_overhang_mm: 1.5,
};

/** Merge one config section onto its defaults, keeping only known keys whose
 * incoming value matches the default's primitive type. */
function mergeSection<T extends Record<string, unknown>>(defaults: T, incoming: unknown): T {
  if (!isRecord(incoming)) return defaults;
  const merged: Record<string, unknown> = { ...defaults };
  for (const key of Object.keys(defaults)) {
    if (!(key in incoming)) continue;
    const fallback = defaults[key];
    const value = incoming[key];
    if (typeof fallback === 'number') {
      if (typeof value === 'number' && Number.isFinite(value)) merged[key] = value;
    } else if (typeof fallback === 'boolean') {
      if (typeof value === 'boolean') merged[key] = value;
    } else if (typeof fallback === 'string') {
      if (typeof value === 'string' && value) merged[key] = value;
    } else if (fallback === null) {
      if (value === null || (typeof value === 'number' && Number.isFinite(value))) merged[key] = value;
    }
  }
  return merged as T;
}

export function parseDesignFile(text: string): ParsedDesignFile {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new Error('the file is not readable JSON');
  }
  if (!isRecord(raw)) throw new Error('expected a JSON design object');
  const declared = typeof raw.openem_schema_version === 'number'
    && Number.isInteger(raw.openem_schema_version)
    && raw.openem_schema_version >= 0
    ? raw.openem_schema_version
    : 0;
  // Upgrade before reading any field: v2 and older stored tooth_width_mm against
  // the bore pitch, so merging it straight onto the v3 defaults would silently
  // reinterpret the saved tooth as a much thinner one.
  const migrated = migrateProjectFile(raw);
  const upgraded = isRecord(migrated.data) ? migrated.data : raw;
  const source = isRecord(upgraded.openem_config) ? upgraded.openem_config : upgraded;
  if (!['topology', 'stator', 'rotor', 'winding'].some((key) => key in source)) {
    throw new Error('no motor definition found in the file');
  }
  const defaults = cloneDefaultConfig();
  const config: MotorConfig = {
    ...defaults,
    topology: source.topology === 'IPM' ? 'IPM' : 'SPM',
    stator: mergeSection(
      isRecord(source.stator) ? { ...defaults.stator, ...LOADED_STATOR_FALLBACKS } : defaults.stator,
      source.stator,
    ),
    rotor: mergeSection(defaults.rotor, source.rotor),
    winding: mergeSection(defaults.winding, source.winding),
    materials: mergeSection(defaults.materials, source.materials),
    solve_params: mergeSection(defaults.solve_params, source.solve_params),
    solve_options: mergeSection(defaults.solve_options, source.solve_options),
  };
  config.schema_version = '1.0';
  // A null rotor bore uses the backend's inferred shaft geometry. The starter
  // has a numeric bore, so primitive-type merging would replace an explicit
  // null with 30 mm (larger than some imported micro rotors).
  if (isRecord(source.rotor) && source.rotor.ID_mm === null) config.rotor.ID_mm = null;
  if (isRecord(source.winding) && typeof source.winding.coil_span === 'number' && Number.isInteger(source.winding.coil_span)) {
    config.winding.coil_span = source.winding.coil_span;
  }
  if (source.geometry_reference !== undefined && source.geometry_reference !== null) {
    if (source.geometry_reference !== 'pyleecan_prius_2004') throw new Error('Unknown published geometry reference.');
    config.geometry_reference = source.geometry_reference;
    const caseId = source.reference_case;
    const temperature = caseId === 'prius-2004-tutorial-bemf-v1' ? 20 : caseId === 'prius-2004-loaded-torque-v1' ? 60 : null;
    if (temperature === null || !isRecord(source.solve_params) || source.solve_params.magnet_temperature_C !== temperature) {
      throw new Error('The published Pyleecan reference requires a registered case and its fixed magnet temperature.');
    }
    config.reference_case = caseId as MotorConfig['reference_case'];
    config.solve_params.magnet_temperature_C = temperature;
    if (typeof source.solve_params.magneto2d_workers === 'number') config.solve_params.magneto2d_workers = source.solve_params.magneto2d_workers;
    if (typeof source.solve_params.motor_input_dc_bus_V === 'number') config.solve_params.motor_input_dc_bus_V = source.solve_params.motor_input_dc_bus_V;
    config.solve_params.max_nonlinear_iterations = typeof source.solve_params.max_nonlinear_iterations === "number" ? source.solve_params.max_nonlinear_iterations : 200;
  }
  const customSteels = parseCustomSteels(isRecord(source.materials) ? source.materials.custom_steels : undefined);
  if (Object.keys(customSteels).length) config.materials.custom_steels = customSteels;
  for (const id of [config.materials.stator_steel, config.materials.rotor_steel]) {
    if (id.startsWith('custom:') && !customSteels[id]) throw new Error('The design is missing its custom steel curve. Reimport the CSV.');
  }
  if (!WINDING_TYPES.has(config.winding.type)) config.winding.type = defaults.winding.type;
  if (!IPM_TOPOLOGIES.has(config.rotor.ipm_topology)) config.rotor.ipm_topology = defaults.rotor.ipm_topology;
  // HoleM50 pocket parameters are not part of the default design, so the
  // section merge above drops them; carry them over for HoleM50 rotors only.
  if (config.rotor.ipm_topology === 'pyleecan_holem50' && isRecord(source.rotor)) {
    for (const field of HOLEM50_FIELDS) {
      const value = source.rotor[field];
      if (typeof value === 'number' && Number.isFinite(value)) config.rotor[field] = value;
    }
  }
  if (!FLAT_BURIED_MAGNET_SHAPES.has(config.rotor.flat_buried_magnet_shape)) {
    config.rotor.flat_buried_magnet_shape = defaults.rotor.flat_buried_magnet_shape;
  }
  const solve = config.solve_params;
  if (!SOLVE_QUALITIES.has(solve.solve_quality)) solve.solve_quality = defaults.solve_params.solve_quality;
  if (solve.solve_quality === 'custom') {
    // The public UI intentionally offers no partial-range control. A custom
    // grid covers one full electrical cycle for consistent waveform sampling,
    // including when an older public design is reloaded.
    solve.rotor_sweep_range_deg = 360;
    solve.rotor_step_deg = Math.min(30, Math.max(0.5, solve.rotor_step_deg));
  }
  if (!MESH_DENSITIES.has(solve.mesh_density)) solve.mesh_density = defaults.solve_params.mesh_density;
  const solverSettingsChanged = solve.torque_method !== PUBLIC_MAGNETO2D_SETTINGS.torque_method
    || solve.linear_solver_preconditioner !== PUBLIC_MAGNETO2D_SETTINGS.linear_solver_preconditioner;
  Object.assign(solve, PUBLIC_MAGNETO2D_SETTINGS);
  if (!NONLINEAR_SOLVERS.has(solve.nonlinear_solver)) solve.nonlinear_solver = defaults.solve_params.nonlinear_solver;
  if (!CURRENT_CONVENTIONS.has(solve.current_amplitude_convention)) {
    solve.current_amplitude_convention = defaults.solve_params.current_amplitude_convention;
  }
  if (!EXCITATION_MODES.has(solve.excitation_mode)) {
    solve.excitation_mode = defaults.solve_params.excitation_mode;
  }
  if (solve.excitation_mode === 'ideal_six_step_120' && config.topology !== 'SPM') {
    solve.excitation_mode = 'sinusoidal';
  }
  if (solve.excitation_mode === 'ideal_six_step_120') {
    solve.current_amplitude_convention = 'plateau';
  } else if (solve.current_amplitude_convention === 'plateau') {
    solve.current_amplitude_convention = defaults.solve_params.current_amplitude_convention;
  }
  solve.phase_connection = 'wye';
  solve.mesh_source = 'native';
  solve.mesher = 'gmsh';
  solve.rotor_rotation_model = 'remesh_per_step';
  config.solve_options.torque_speed_envelope = false;
  config.solve_options.cogging_torque = false;
  // Public presets own the spectrum bandwidth: Standard reports H1-H12 and
  // Fine reports H1-H24. Quick and Custom remain waveform-only.
  config.solve_options.thd_analysis = solve.solve_quality === 'standard'
    || solve.solve_quality === 'fine';
  const name = typeof raw.name === 'string' && raw.name.trim() ? raw.name.trim() : null;
  return {
    name, config, declaredSchemaVersion: declared, fromFuture: migrated.fromFuture,
    solverSettingsNotice: solverSettingsChanged
      ? 'Solver settings changed to WST torque and Direct Cholesky for the public app. Other methods are available in the dev build.'
      : null,
  };
}

export function designFileBaseName(name: string, fallback = 'coilem-design'): string {
  return name.trim().replace(/\.(?:coilem|openem|json)$/i, '').trim() || fallback;
}

export function serializeDesignFile(config: MotorConfig, name: string): string {
  return `${JSON.stringify(
    {
      openem_schema_version: DESIGN_FILE_SCHEMA_VERSION,
      openem_version: COILEM_APP_VERSION,
      name: designFileBaseName(name),
      ...(config.geometry_reference === 'pyleecan_prius_2004'
        ? { reference_notice: PYLEECAN_REFERENCE_NOTICE } : {}),
      ...applyPublicSolverSettings(config),
    },
    null,
    2,
  )}\n`;
}

/** Save via the browser's file picker when available, else download. */
export async function saveDesignFileAs(config: MotorConfig, name: string): Promise<boolean> {
  const filename = `${designFileBaseName(name)}${DESIGN_FILE_EXTENSION}`;
  const blob = new Blob([serializeDesignFile(config, name)], { type: 'application/json' });
  const picker = (window as { showSaveFilePicker?: (options: unknown) => Promise<any> }).showSaveFilePicker;
  if (typeof picker === 'function') {
    try {
      const handle = await picker.call(window, {
        suggestedName: filename,
        types: [{ description: 'coilEM design file', accept: { 'application/json': [DESIGN_FILE_EXTENSION] } }],
      });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return true;
    } catch (error) {
      if ((error as { name?: string })?.name === 'AbortError') return false;
    }
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
  return true;
}
