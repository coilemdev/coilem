import type { MotorConfig, SolveResult } from './model';
import { temperatureIn, unitSymbol, type TemperatureUnit } from './thermalUnits';

export interface ThermalNode {
  temperature_C: number | null; heat_W: number; status: 'experimental' | 'unavailable'; status_reason: string;
  limit_C: number | null; margin_K: number | null;
}
export interface CopperFeedback {
  method: 'linear_equilibrium_v1'; status: 'experimental'; status_reason: string;
  reference_temperature_C: number; reference_copper_loss_W: number; copper_loss_W: number;
  copper_active_loss_W: number; copper_end_winding_loss_W: number;
  phase_current_rms_A: number; phase_resistance_ohm: number; temperature_residual_K: number;
  wire_source: 'specified' | 'derived';
}
export interface ThermalEstimate {
  kind: 'steady_state_thermal'; status: 'experimental' | 'unavailable'; status_reason: string;
  nodes: Record<string, ThermalNode>; hottest_node: string | null; inputs: Record<string, unknown>;
  copper_feedback?: CopperFeedback | null;
  rotor_heating?: {basis: 'heat_transfer_only' | 'heat_transfer_plus_supplied_heat'; additional_heat_W: number;
    mechanical_heat_to_rotor_W: number; internal_loss_status: 'not_modelled'; status_reason: string} | null;
  calibrated: boolean; notes: string[]; baseline_without_extra_rotor_C: Record<string, number> | null;
}
export interface CoupledThermalPoint {
  status: string; status_reason: string; speed_rpm: number; current_peak_A: number; gamma_deg: number;
  torque_Nm: number | null; phase_voltage_peak_V: number | null; winding_temperature_C: number | null;
  magnet_temperature_C: number | null; thermal: ThermalEstimate | null; iterations: number;
  temperature_residual_K: number | null; verification_status: string; verification_reason: string;
}
export interface ThermalRating {
  kind: 'thermally_limited_rating'; status: 'experimental'; status_reason: string; inputs: Record<string, unknown>;
  limits: import('./performance').DriveLimits; control: string; acceptance_status: string; cancelled: boolean; notes: string[];
  points: Array<{speed_rpm: number; status: string; status_reason: string; limiting_constraint: string;
    point: CoupledThermalPoint | null; user_magnet_case: CoupledThermalPoint | null}>;
}
export interface ThermalAnalysis {
  id: string; kind: 'point' | 'rating'; result: ThermalEstimate | ThermalRating; design_name: string;
  /** The inputs as the API recorded them, its defaults filled in. */
  inputs?: Record<string, unknown>;
  curve_options?: {lowC: number; highC: number; userMagnetC: number | null};
  bracket?: {low: {magnet_temperature_C: number}; high: {magnet_temperature_C: number}};
}

type RatingRow = ThermalRating['points'][number];

// Every saved version starts the verification reason of a direct solve that ran to the comparison with
// these words, whether it passed or missed a band. A FAIL without them is a direct solve that raised.
// The status_reason sentence added for that case changed between versions, so it is not used.
// backend/thermal_reporting.py reads the reports with the same rule.
const DIRECT_COMPARISON = 'Direct limiting-point comparison';

/** Whether the direct solve of a limiting point raised instead of reaching its comparison. */
export const directSolveFailed = (point: CoupledThermalPoint | null | undefined): boolean =>
  point?.verification_status === 'FAIL' && !(point.verification_reason ?? '').startsWith(DIRECT_COMPARISON);

/**
 * A speed of a torque curve as this version records it. Earlier builds left a speed whose direct solve
 * raised as experimental, so it counted as held; it is read as a new run saves it: unavailable, with the
 * reason new runs give. Any other row comes back as it is, including a completed direct solve that only
 * missed a comparison band.
 */
export function readRatingRow(row: RatingRow): RatingRow {
  const point = row.point;
  if (!point || !directSolveFailed(point) || row.status === 'unavailable' || point.status === 'unavailable') return row;
  const detail = (point.verification_reason ?? '').trim() || 'no reason was saved';
  const reason = `A direct solve at this point could not run (${detail}), so the value read from the maps is not reported.`;
  return { ...row, status: 'unavailable', status_reason: reason,
    point: { ...point, status: 'unavailable', status_reason: reason, verification_reason: `Direct limiting-point solve failed: ${detail}` } };
}

/**
 * Whether a speed of a torque curve holds a torque. A speed rejected by its search, or by its direct
 * solve (a limit crossed, or the solve could not run), keeps its map point for the record, but it is not a result.
 */
export const isHeldSpeed = (saved: RatingRow): boolean => {
  const row = readRatingRow(saved);
  return row.status !== 'unavailable' && row.point?.status !== 'unavailable' && row.point?.torque_Nm != null;
};
/**
 * A short fixed-length name for a long text (cyrb53, 53 bits, as 11 base-36 characters). Browser storage
 * is a few megabytes in all, and a design is kilobytes of JSON: used as a key it would fill the storage
 * after a few hundred runs, and a result that cannot be remembered is not shown.
 */
function shortName(text: string): string {
  let a = 0xdeadbeef; let b = 0x41c6ce57;
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    a = Math.imul(a ^ code, 2654435761); b = Math.imul(b ^ code, 1597334677);
  }
  a = Math.imul(a ^ (a >>> 16), 2246822507) ^ Math.imul(b ^ (b >>> 13), 3266489909);
  b = Math.imul(b ^ (b >>> 16), 2246822507) ^ Math.imul(a ^ (a >>> 13), 3266489909);
  return (4294967296 * (2097151 & b) + (a >>> 0)).toString(36).padStart(11, '0');
}
/** Where a design's thermal setup is kept: the same for every operating point of one motor. */
export const thermalDesignKey = (config: MotorConfig) => `coilem.thermal.inputs.${shortName(JSON.stringify([config.topology, config.stator, config.rotor, config.winding, config.materials]))}`;
/** Where a solved run's latest thermal results are kept: one name per design and run. */
export const legacyThermalKey = (config: MotorConfig, result: SolveResult) => `coilem.thermal.run.${shortName(JSON.stringify(config))}.${shortName((result.solve_metadata as typeof result.solve_metadata & {timestamp?: string}).timestamp ?? JSON.stringify(result.summary))}`;

export const thermalKey = (config: MotorConfig, result: SolveResult) => result.saved_run
  ? `coilem.thermal.saved.${result.saved_run.project_slug}/${result.saved_run.run_id}`
  : legacyThermalKey(config, result);

export const THERMAL_FIELDS = [
  ['ambient_C', 'Ambient / coolant temperature (°C)'],
  ['housing_h_W_m2K', 'Housing heat transfer (W/m²K)'],
  ['end_space_h_W_m2K', 'End-space heat transfer (W/m²K)'],
  ['airgap_h_W_m2K', 'Air-gap heat transfer, per surface (W/m²K)'],
  ['housing_thickness_mm', 'Housing thickness (mm)'],
  ['slot_liner_mm', 'Slot liner thickness (mm)'],
  ['contact_m2K_W', 'Stator contact resistance (m²K/W)'],
  ['bearing_to_housing_K_W', 'Bearing to housing (K/W)'],
  ['rotor_to_bearing_K_W', 'Rotor to bearing (K/W)'],
  ['hotspot_allowance_K', 'Winding hotspot allowance (K)'],
] as const;

/** What the model uses for an optional input left empty. The form shows these values, so no box is blank. */
export const THERMAL_MODEL_DEFAULTS: Readonly<Record<string, string>> = {
  extra_rotor_heat_W: '0', extra_rotor_heat_to_magnets_fraction: '0', steel_k_W_mK: '20', calibration_multiplier: '1',
};

// An illustrative starting point, not a measured motor or a cooling correlation.
// Values are sent explicitly and retained in the result/report provenance.
export const THERMAL_STARTER: Readonly<Record<string, string>> = {
  cooling: 'still_air', ambient_C: '25', insulation_class: 'F',
  housing_h_W_m2K: '10', end_space_h_W_m2K: '10', airgap_h_W_m2K: '20',
  housing_thickness_mm: '3', slot_liner_mm: '0.1', contact_m2K_W: '0.001',
  bearing_to_housing_K_W: '2', rotor_to_bearing_K_W: '3', hotspot_allowance_K: '15',
  // Outer-rotor motors only: hub, mount and airframe together.
  mount_to_ambient_K_W: '10',
  coefficient_source: 'coilEM still-air starter v1: illustrative cooling, construction and hotspot assumptions; uncalibrated, not measured.',
  ...THERMAL_MODEL_DEFAULTS,
};

const LATER_INPUTS = ['mount_to_ambient_K_W', ...Object.keys(THERMAL_MODEL_DEFAULTS)] as const;
/** Conductor-grade aluminium, W/(m·K). The API's default is copper's, and it refuses an aluminium winding that names none. */
export const ALUMINIUM_CONDUCTOR_K_W_MK = 235;
// Inputs the form no longer offers: each moves the result by about 1 K at most. A value typed into an
// earlier draft is dropped rather than applied out of sight. The model, the CLI and Python still take them.
const RETIRED_INPUTS = ['conductor_k_W_mK', 'housing_k_W_mK', 'magnet_k_W_mK', 'end_winding_exposed_fraction'] as const;

export function readThermalValues(saved: string | null): Record<string, string> {
  if (saved !== null) {
    try {
      const parsed: unknown = JSON.parse(saved);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        && Object.values(parsed).every((value) => typeof value === 'string')) {
        const values = parsed as Record<string, string>;
        // A draft saved before an input existed gets that input's starter value. A value the
        // person cleared stays cleared: only a missing key is filled.
        for (const key of LATER_INPUTS) if (!(key in values)) values[key] = THERMAL_STARTER[key];
        for (const key of RETIRED_INPUTS) delete values[key];
        return values;
      }
    } catch { /* Corrupt browser preferences fall back to the labelled starter. */ }
  }
  return {...THERMAL_STARTER};
}

export function changeThermalValue(values: Record<string, string>, name: string, value: string): Record<string, string> {
  if (name === 'cooling' && value !== values.cooling) {
    // A mode name cannot establish coefficients for a different installation.
    return {...values, cooling: value, housing_h_W_m2K: '', end_space_h_W_m2K: '', airgap_h_W_m2K: '', coefficient_source: ''};
  }
  return {...values, [name]: value};
}

/** A stored °C input as text in the chosen unit, or the text itself when it is not a number yet. */
function shownTemperature(text: string, unit: TemperatureUnit): string {
  const value = Number(text);
  return text.trim() === '' || !Number.isFinite(value) ? text : `${Number(temperatureIn(value, unit).toFixed(2))}`;
}

export function thermalSetupSummary(values: Record<string, string>, unit: TemperatureUnit = 'C'): string {
  const cooling = {still_air: 'Still air', forced_air: 'Forced air', liquid_jacket: 'Liquid jacket'}[values.cooling];
  return `${cooling ?? 'Choose cooling'} · ${values.ambient_C ? shownTemperature(values.ambient_C, unit) : '—'} ${unitSymbol(unit)} · ${values.insulation_class || '—'} · Experimental`;
}

/** The API's limits for the optional inputs, checked here so a bad value is named before it is sent. */
function optionalRangeProblem(key: string, value: number): string | null {
  if (key === 'extra_rotor_heat_W') return value < 0 ? 'cannot be negative' : null;
  if (key === 'extra_rotor_heat_to_magnets_fraction') return value < 0 || value > 1 ? 'must be between 0 and 1' : null;
  return value <= 0 ? 'must be above 0' : null;
}

export type RotorLayout = 'inner' | 'outer';
export const rotorLayoutOf = (config: { rotor_layout?: string | null }): RotorLayout => config.rotor_layout === 'outer' ? 'outer' : 'inner';

/** A label inside a sentence: its first letter in lower case, its units as written (W/m²K, °C). */
const lowerFirst = (label: string) => label.charAt(0).toLowerCase() + label.slice(1);

export function thermalInputs(values: Record<string, string>, mechanicalW = 0, layout: RotorLayout = 'inner', unit: TemperatureUnit = 'C', conductor: string | null = null): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  // The form does not offer the conductor's conductivity, so an aluminium winding sends aluminium's.
  if (conductor === 'aluminum') result.conductor_k_W_mK = ALUMINIUM_CONDUCTOR_K_W_MK;
  for (const [key, label] of THERMAL_FIELDS) {
    const value = Number(values[key]);
    if (!values[key]?.trim() || !Number.isFinite(value)) throw new Error(`Enter ${lowerFirst(label)}.`);
    if (key !== 'ambient_C' && (key === 'hotspot_allowance_K' ? value < 0 : value <= 0)) throw new Error(`Check ${lowerFirst(label)}.`);
    if (key === 'ambient_C' && (value <= -273.15 || value > 200)) throw new Error(`Ambient or coolant temperature must be between ${Math.round(temperatureIn(-273.15, unit))} and ${Math.round(temperatureIn(200, unit))} ${unitSymbol(unit)}.`);
    result[key] = value;
  }
  if (!values.cooling || !values.insulation_class || !values.coefficient_source?.trim()) throw new Error('Select cooling and insulation, and give the heat-transfer source.');
  if (layout === 'outer') {
    // An outer-rotor stator sits on a hub: its heat reaches the surroundings through the mount.
    const mount = Number(values.mount_to_ambient_K_W);
    if (!values.mount_to_ambient_K_W?.trim() || !Number.isFinite(mount)) throw new Error('Enter mount to surroundings (K/W).');
    if (mount <= 0) throw new Error('Check mount to surroundings (K/W).');
    result.mount_to_ambient_K_W = mount;
  }
  Object.assign(result, { cooling: values.cooling, insulation_class: values.insulation_class, coefficient_source: values.coefficient_source });
  for (const key of ['extra_rotor_heat_W', 'extra_rotor_heat_to_magnets_fraction', 'calibration_multiplier', 'slot_k_W_mK', 'steel_k_W_mK']) {
    // A conductivity typed for 'My own value' and then abandoned is not sent.
    if (key === 'slot_k_W_mK' && (values.slot_k_model || 'series_lower_bound') !== 'user') continue;
    if (values[key]?.trim()) {
      const value = Number(values[key]);
      if (!Number.isFinite(value)) throw new Error(`Invalid ${key}.`);
      const problem = optionalRangeProblem(key, value);
      if (problem) throw new Error(`${THERMAL_FIELD_META[key]?.label ?? key} ${problem}.`);
      result[key] = value;
    }
  }
  result.slot_k_model = values.slot_k_model || 'series_lower_bound';
  if (result.slot_k_model === 'user') {
    if (result.slot_k_W_mK === undefined || !values.slot_k_source?.trim()) throw new Error('Slot conductivity needs its value and its source.');
    result.slot_k_source = values.slot_k_source;
  }
  // The split is asked for, and sent, only when the run has a mechanical loss to place.
  if (mechanicalW > 0) {
    const split = Object.fromEntries(['bearings', 'housing', 'rotor'].map((name) => {
      if (!values[`mechanical_${name}`]?.trim()) throw new Error('Assign every mechanical-loss fraction explicitly.');
      return [name, Number(values[`mechanical_${name}`]) / 100];
    }));
    if (Object.values(split).some((v) => !Number.isFinite(v) || v < 0) || Math.abs(Object.values(split).reduce((a, b) => a + b, 0) - 1) > 1e-8) throw new Error('Mechanical-loss percentages must sum to 100.');
    result.mechanical_split = split;
  }
  if (Number(result.calibration_multiplier ?? 1) !== 1) {
    if (!values.cal_measurement || !values.cal_operating_point || !values.cal_cooling) throw new Error('Calibration needs the measurement, operating point and cooling.');
    result.calibration_source = {measurement: values.cal_measurement, operating_point: values.cal_operating_point, cooling: values.cal_cooling};
  }
  return result;
}

/**
 * What the API fills in for each input a request leaves out: the defaults of its ThermalInputs model,
 * which a Python test holds this list to. A saved result records every input, these included.
 */
export const THERMAL_REQUEST_DEFAULTS: Readonly<Record<string, number | string | null>> = {
  mount_to_ambient_K_W: null, steel_k_W_mK: 20, conductor_k_W_mK: 385, housing_k_W_mK: 205, magnet_k_W_mK: 8,
  impregnation_k_W_mK: 0.2, liner_k_W_mK: 0.2, slot_k_model: 'series_lower_bound', slot_k_W_mK: null, slot_k_source: null,
  end_winding_exposed_fraction: 1, extra_rotor_heat_to_magnets_fraction: 0, mechanical_split: null, extra_rotor_heat_W: 0,
  calibration_multiplier: 1, calibration_source: null, magnet_frequency_limit_Hz: null,
};

function sameInputValue(a: unknown, b: unknown): boolean {
  if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const left = a as Record<string, unknown>; const right = b as Record<string, unknown>;
    return [...new Set([...Object.keys(left), ...Object.keys(right)])].every((key) => sameInputValue(left[key] ?? null, right[key] ?? null));
  }
  return (a ?? null) === (b ?? null);
}

/**
 * Whether a saved result was computed with these inputs (the request {@link thermalInputs} builds, in °C).
 * Both sides are compared as the API records them, its defaults filled in, so an edit that changes
 * nothing it would compute with (25 typed as 25.0, a unit switch, an emptied box that takes its default)
 * still matches. An input the app does not know is left out of the comparison.
 */
export function sameThermalInputs(request: Record<string, unknown>, recorded: Record<string, unknown> | null | undefined): boolean {
  if (!recorded) return true;
  const keys = new Set([...Object.keys(THERMAL_REQUEST_DEFAULTS), ...Object.keys(request)]);
  return [...keys].every((key) => sameInputValue(request[key] ?? THERMAL_REQUEST_DEFAULTS[key] ?? null, recorded[key] ?? THERMAL_REQUEST_DEFAULTS[key] ?? null));
}

/** The inputs a saved estimate or torque curve was computed with. */
export const recordedThermalInputs = (analysis: ThermalAnalysis | null): Record<string, unknown> | null =>
  analysis ? analysis.inputs ?? analysis.result.inputs ?? null : null;

export function thermalCurvePath(rating: ThermalRating, x: (v: number) => number, y: (v: number) => number): string {
  let previous = false;
  return rating.points.map((row) => {
    if (!isHeldSpeed(row)) { previous = false; return ''; }
    const command = previous ? 'L' : 'M'; previous = true;
    return `${command}${x(row.speed_rpm)},${y(row.point!.torque_Nm!)}`;
  }).join(' ');
}

// ---- Setup presentation: plain names, units and help for each input ----

export const COOLING_MODES = [
  { value: 'still_air', label: 'Still air', hint: 'No fan or airflow' },
  { value: 'forced_air', label: 'Forced air', hint: 'Fan, prop wash or airflow' },
  { value: 'liquid_jacket', label: 'Liquid jacket', hint: 'Coolant in the housing' },
] as const;

/** Thermal class of the winding insulation and the temperature it is rated for. */
export const INSULATION_CLASSES = [
  { value: 'A', limit_C: 105 }, { value: 'B', limit_C: 130 }, { value: 'F', limit_C: 155 }, { value: 'H', limit_C: 180 },
] as const;

export interface ThermalFieldMeta { label: string; unit?: string; help: string; typical?: string }

const lowerIsEasier = 'A lower number means heat moves more easily.';
// The ranges quoted below are the textbook ones for a surface in a gas or a liquid: free convection in gases
// 2-25, forced convection in gases 25-250, forced convection in liquids 100-20,000 W/m2K (Incropera et al.,
// Fundamentals of Heat and Mass Transfer, Table 1.1). They bound a guess; they do not replace a measurement.
export const THERMAL_FIELD_META: Record<string, ThermalFieldMeta> = {
  ambient_C: { label: 'Ambient or coolant temperature', unit: '°C',
    help: 'Temperature of the air or coolant that carries the heat away. Every estimated temperature sits above it.' },
  housing_h_W_m2K: { label: 'Housing to surroundings', unit: 'W/m²K',
    help: 'How well the outside of the housing sheds heat: the watts leaving each square metre for every degree it is hotter than the surroundings. A higher number means better cooling.',
    typical: 'Textbook ranges: 2–25 in still air, 25–250 with a fan or airflow, 100–20,000 with a liquid jacket.' },
  end_space_h_W_m2K: { label: 'End windings to inside air', unit: 'W/m²K',
    help: 'The same measure for the air inside the motor, around the end windings. A higher number means better cooling.',
    typical: 'Textbook range: 2–25 when the inside air barely moves, 25–250 when the rotor or a fan stirs it.' },
  airgap_h_W_m2K: { label: 'Across the air gap', unit: 'W/m²K',
    help: 'Heat transfer between the stator bore and the rotor, applied at both surfaces. It rises with speed. coilEM does not change it with speed, so enter the value for the speed you solved.',
    typical: 'It depends strongly on speed and gap size, so no typical range is given. The starter value is a placeholder.' },
  coefficient_source: { label: 'Where these values come from',
    help: 'A short note saved with the result and its reports, for example a measurement, a datasheet or "estimate". It keeps the assumption traceable.' },
  housing_thickness_mm: { label: 'Housing wall thickness', unit: 'mm',
    help: 'Wall of the housing around the stator. Heat conducts through it to the outside surface.' },
  slot_liner_mm: { label: 'Slot liner thickness', unit: 'mm',
    help: 'Insulation paper between the winding and the slot wall. It is thin but conducts heat poorly, so it matters.' },
  contact_m2K_W: { label: 'Stator-to-housing contact', unit: 'm²K/W',
    help: `How much the joint between the stator stack and the housing resists heat, for each square metre of joint. A tight press fit is low; a loose or glued fit is higher. ${lowerIsEasier}` },
  bearing_to_housing_K_W: { label: 'Bearings to housing', unit: 'K/W',
    help: `Temperature difference needed to push one watt from the bearings into the housing. ${lowerIsEasier}` },
  rotor_to_bearing_K_W: { label: 'Rotor to bearings', unit: 'K/W',
    help: `Temperature difference needed to push one watt from the rotor, along the shaft, into the bearings. ${lowerIsEasier}` },
  mount_to_ambient_K_W: { label: 'Mount to surroundings', unit: 'K/W',
    help: `Temperature difference needed to push one watt from the stator hub, through the mount, into the airframe and the air. A motor bolted to a metal arm is low; one on a thin plate or a plastic mount is high. ${lowerIsEasier}`,
    typical: 'It depends on what the motor is bolted to, so no typical range is given. The starter value is a placeholder.' },
  hotspot_allowance_K: { label: 'Hotspot allowance', unit: 'K',
    help: 'The estimate gives one average temperature for the winding, and the hottest spot inside a coil runs hotter. This allowance is taken off the insulation limit to cover the difference.' },
  extra_rotor_heat_W: { label: 'Added rotor and magnet heat', unit: 'W',
    help: 'coilEM does not calculate eddy-current heat in the magnets and rotor. Enter an estimate to see its effect, or leave it at 0 to see the case without it.' },
  extra_rotor_heat_to_magnets_fraction: { label: 'Share of that heat in the magnets', unit: '0–1',
    help: 'How the added heat is split: 1 puts all of it in the magnets, 0 puts all of it in the rotor iron.' },
  slot_k_W_mK: { label: 'Slot conductivity', unit: 'W/mK',
    help: 'Effective heat conduction across the wound slot: copper, enamel, resin and voids together.' },
  slot_k_source: { label: 'Slot conductivity source', help: 'Where the slot conductivity comes from. Saved with the result.' },
  steel_k_W_mK: { label: 'Steel conductivity', unit: 'W/mK',
    help: 'Heat conduction of the lamination steel, which carries the heat from the slots to the housing. It matters most when the housing is cooled strongly. The default is 20.' },
  calibration_multiplier: { label: 'Thermal resistance multiplier',
    help: 'Scales every thermal resistance to match a measurement. 1 leaves the estimate as it is. One number cannot identify several uncertain heat paths, and a fitted result stays experimental.' },
  cal_measurement: { label: 'Calibration measurement', help: 'The measurement the multiplier was fitted to.' },
  cal_operating_point: { label: 'Calibration operating point', help: 'Current and speed of that measurement.' },
  cal_cooling: { label: 'Calibration cooling', help: 'Cooling during that measurement.' },
  mechanical_bearings: { label: 'Mechanical loss to bearings', unit: '%', help: 'Share of the entered mechanical loss that heats the bearings. The three shares must total 100.' },
  mechanical_housing: { label: 'Mechanical loss to housing', unit: '%', help: 'Share of the entered mechanical loss that heats the housing.' },
  mechanical_rotor: { label: 'Mechanical loss to rotor', unit: '%', help: 'Share of the entered mechanical loss that heats the rotor.' },
};

/** What the same inputs mean on an outer-rotor motor, whose stator sits on a hub inside a spinning shell. */
const OUTER_ROTOR_META: Record<string, ThermalFieldMeta> = {
  housing_h_W_m2K: { label: 'Rotor shell to surroundings', unit: 'W/m²K',
    help: 'How well the outside of the spinning rotor shell sheds heat: the watts leaving each square metre for every degree it is hotter than the surroundings. A higher number means better cooling. A propeller\'s airflow raises it a lot.',
    typical: 'Textbook ranges: 2–25 in still air, 25–250 in a propeller\'s airflow.' },
  end_space_h_W_m2K: { label: 'End windings to air inside the rotor', unit: 'W/m²K',
    help: 'The same measure for the air inside the rotor shell, around the end windings. The estimate treats the shell as closed, so a rotor with open spokes runs cooler than it says.',
    typical: 'Textbook range: 2–25 when that air barely moves, 25–250 when the rotor stirs it.' },
  airgap_h_W_m2K: { label: 'Across the air gap', unit: 'W/m²K',
    help: 'Heat transfer between the stator teeth and the magnets on the rotor shell, applied at both surfaces. It rises with speed. coilEM does not change it with speed, so enter the value for the speed you solved.',
    typical: 'It depends strongly on speed and gap size, so no typical range is given. The starter value is a placeholder.' },
  contact_m2K_W: { label: 'Stator-to-hub contact', unit: 'm²K/W',
    help: `How much the joint between the stator stack and its hub resists heat, for each square metre of joint. A tight press fit or a thermal adhesive is low; a loose fit is higher. ${lowerIsEasier}` },
  bearing_to_housing_K_W: { label: 'Bearings to mount', unit: 'K/W',
    help: `Temperature difference needed to push one watt from the bearings into the stator hub and mount. ${lowerIsEasier}` },
  rotor_to_bearing_K_W: { label: 'Rotor to bearings', unit: 'K/W',
    help: `Temperature difference needed to push one watt from the rotor shell, along the shaft, into the bearings. ${lowerIsEasier}` },
  mechanical_housing: { label: 'Mechanical loss to mount', unit: '%', help: 'Share of the entered mechanical loss that heats the stator hub and mount.' },
};

/** A field's name, unit and explanation for this rotor layout. */
export function thermalFieldMeta(name: string, layout: RotorLayout = 'inner'): ThermalFieldMeta {
  return (layout === 'outer' ? OUTER_ROTOR_META[name] : undefined) ?? THERMAL_FIELD_META[name];
}

const filled = (value: string | undefined) => Boolean(value?.trim());

/** The winding temperature limit the estimate compares against: class limit less the hotspot allowance. */
export function windingLimitC(values: Record<string, string>): number | null {
  const limit = INSULATION_CLASSES.find((row) => row.value === values.insulation_class)?.limit_C;
  const allowance = Number(values.hotspot_allowance_K);
  return limit === undefined || !filled(values.hotspot_allowance_K) || !Number.isFinite(allowance) ? null : limit - allowance;
}

export type ThermalSetupSection = 'cooling' | 'insulation' | 'construction' | 'rotor' | 'advanced';

/** One line per setup section, shown while the section is closed. */
export function thermalSectionSummary(section: ThermalSetupSection, values: Record<string, string>, layout: RotorLayout = 'inner', unit: TemperatureUnit = 'C'): string {
  if (section === 'cooling') {
    const mode = COOLING_MODES.find((row) => row.value === values.cooling)?.label ?? 'Choose cooling';
    return `${mode} · ${filled(values.ambient_C) ? `${shownTemperature(values.ambient_C, unit)} ${unitSymbol(unit)}` : 'no temperature'}`;
  }
  if (section === 'insulation') {
    const limit = windingLimitC(values);
    return `${values.insulation_class ? `Class ${values.insulation_class}` : 'Choose class'}${limit === null ? '' : ` · winding limit ${Number(temperatureIn(limit, unit).toFixed(2))} ${unitSymbol(unit)}`}`;
  }
  if (section === 'construction') {
    return layout === 'outer'
      ? `${values.mount_to_ambient_K_W || '—'} K/W mount · ${values.slot_liner_mm || '—'} mm liner`
      : `${values.housing_thickness_mm || '—'} mm housing · ${values.slot_liner_mm || '—'} mm liner`;
  }
  if (section === 'rotor') {
    const heat = Number(values.extra_rotor_heat_W);
    return filled(values.extra_rotor_heat_W) && heat > 0 ? `${values.extra_rotor_heat_W} W added` : 'Heat from the stator only';
  }
  // A box showing its default, or emptied so the default applies, is not an edit.
  const changed = (name: string) => filled(values[name]) && Number(values[name]) !== Number(THERMAL_MODEL_DEFAULTS[name]);
  const edited = ['mechanical_bearings', 'mechanical_housing', 'mechanical_rotor'].some((name) => filled(values[name]))
    || changed('steel_k_W_mK') || changed('calibration_multiplier')
    || (values.slot_k_model ?? 'series_lower_bound') !== 'series_lower_bound';
  return edited ? 'Edited' : 'Defaults';
}

/** Which setup section holds the first problem, so the panel can open it. */
export function thermalProblemSection(values: Record<string, string>, mechanicalW = 0, layout: RotorLayout = 'inner'): ThermalSetupSection | null {
  if (!values.cooling || !filled(values.ambient_C) || ['housing_h_W_m2K', 'end_space_h_W_m2K', 'airgap_h_W_m2K', 'coefficient_source'].some((name) => !filled(values[name]))) return 'cooling';
  if (!values.insulation_class || !filled(values.hotspot_allowance_K)) return 'insulation';
  if (['housing_thickness_mm', 'slot_liner_mm', 'contact_m2K_W', 'bearing_to_housing_K_W', 'rotor_to_bearing_K_W', ...(layout === 'outer' ? ['mount_to_ambient_K_W'] : [])].some((name) => !filled(values[name]))) return 'construction';
  for (const key of ['extra_rotor_heat_W', 'extra_rotor_heat_to_magnets_fraction']) {
    if (filled(values[key]) && (!Number.isFinite(Number(values[key])) || optionalRangeProblem(key, Number(values[key])))) return 'rotor';
  }
  try { thermalInputs(values, mechanicalW, layout); } catch { return 'advanced'; }
  return null;
}

/** Why a saved point estimate has no temperatures, or null when it has them. */
export function unavailableEstimateReason(analysis: ThermalAnalysis | null): string | null {
  if (analysis?.result.kind !== 'steady_state_thermal') return null;
  const result = analysis.result;
  return result.status === 'unavailable' || Object.keys(result.nodes).length === 0 ? result.status_reason : null;
}
