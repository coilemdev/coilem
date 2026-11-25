import { useCallback, useId, useSyncExternalStore } from 'react';
import { TemperatureInput } from './TemperatureInput';
import { TEMPERATURE_UNITS, differenceIn, temperatureIn, unitSymbol, type TemperatureUnit } from './thermalUnits';
import { useTemperatureUnit } from './useTemperatureUnit';
import type { MotorConfig } from './model';
import { InfoTip } from './Popover';
import { COOLING_MODES, INSULATION_CLASSES, THERMAL_FIELDS, THERMAL_MODEL_DEFAULTS, THERMAL_STARTER, changeThermalValue, readThermalValues, thermalDesignKey, thermalFieldMeta, thermalInputs, windingLimitC, type RotorLayout } from './thermal';

// Both Solve and Results read the same design-scoped draft. Writes happen only
// on edits, so switching designs cannot copy a previous design's inputs across.
const drafts = new Map<string, string>();
const changed = 'coilem-thermal-setup-updated';
function subscribe(listener: () => void) {
  window.addEventListener(changed, listener);
  window.addEventListener('storage', listener);
  return () => { window.removeEventListener(changed, listener); window.removeEventListener('storage', listener); };
}
export function useThermalSetup(config: MotorConfig): [Record<string, string>, (values: Record<string, string>) => void] {
  const key = thermalDesignKey(config);
  const read = useCallback(() => {
    try { return drafts.get(key) ?? localStorage.getItem(key) ?? null; } catch { return drafts.get(key) ?? null; }
  }, [key]);
  const saved = useSyncExternalStore(subscribe, read, () => null);
  const write = useCallback((values: Record<string, string>) => {
    const serialized = JSON.stringify(values);
    try { localStorage.setItem(key, serialized); drafts.delete(key); } catch { drafts.set(key, serialized); }
    window.dispatchEvent(new Event(changed));
  }, [key]);
  return [readThermalValues(saved), write];
}

interface GroupProps { values: Record<string, string>; onChange: (values: Record<string, string>) => void; mechanicalW?: number; layout?: RotorLayout }

// The full names with units stay the fields' accessible names; the visible label is shorter.
const ACCESSIBLE_NAMES: Record<string, string> = Object.fromEntries(THERMAL_FIELDS);

function Help({ name, label, layout }: { name: string; label: string; layout?: RotorLayout }) {
  const meta = thermalFieldMeta(name, layout);
  return <InfoTip label={`${label} help`} align="end">
    <div className="public-analysis-help"><p>{meta.help}</p>{meta.typical && <p className="popover-note">{meta.typical}</p>}</div>
  </InfoTip>;
}

const TEMPERATURE_INPUTS: Record<string, 'temperature' | 'difference'> = { ambient_C: 'temperature', hotspot_allowance_K: 'difference' };
/** A stored whole-number temperature in the chosen unit, without conversion noise. */
const shownTemperature = (celsius: number, unit: TemperatureUnit) => Number(temperatureIn(celsius, unit).toFixed(2));

/** Chooses the unit every thermal temperature is shown and typed in. */
export function TemperatureUnitPicker() {
  const [unit, setUnit] = useTemperatureUnit();
  return <div className="thermal-unit-picker">
    <span id="thermal-unit-label">Temperatures in</span>
    <div className="thermal-unit-options" role="radiogroup" aria-labelledby="thermal-unit-label">
      {TEMPERATURE_UNITS.map((option) => <button key={option.value} type="button" role="radio" aria-checked={unit === option.value} title={option.name}
        className={unit === option.value ? 'active' : ''} onClick={() => setUnit(option.value)}>{option.symbol}</button>)}
    </div>
    {unit !== 'C' && <small>Reports and solver messages stay in °C.</small>}
  </div>;
}

/** One input laid out like the electromagnetic setup rows, with an explanation beside its name. */
function Field({ name, values, onChange, layout, type = 'number' }: GroupProps & { name: string; type?: 'number' | 'text' }) {
  const id = useId();
  const meta = thermalFieldMeta(name, layout);
  const [temperatureUnit] = useTemperatureUnit();
  // Temperatures and temperature differences are kept in °C and K and shown in the chosen unit.
  const kind = TEMPERATURE_INPUTS[name];
  const unit = kind ? unitSymbol(temperatureUnit) : meta.unit;
  const plain = `${meta.label}${unit ? ` (${unit})` : ''}`;
  // An outer rotor gives some inputs another meaning; their accessible name follows the label shown.
  const named = kind ? ACCESSIBLE_NAMES[name]?.replace(/\((°C|K)\)$/, `(${unit})`) : ACCESSIBLE_NAMES[name];
  const accessible = layout === 'outer' ? plain : named ?? plain;
  return <div className={`param-row public-param-row thermal-param-row${type === 'text' ? ' is-text' : ''}`}>
    <span className="param-label"><label htmlFor={id}>{meta.label}</label>{unit && <small>{unit}</small>}<Help name={name} label={meta.label} layout={layout} /></span>
    <span className="param-control">
      {kind
        ? <TemperatureInput id={id} ariaLabel={accessible} unit={temperatureUnit} kind={kind} value={values[name] ?? ''} onChange={(kept) => onChange(changeThermalValue(values, name, kept))} />
        : <input id={id} className={type === 'text' ? 'param-text-input' : 'param-number-input'} aria-label={accessible} type={type} step="any"
          placeholder={THERMAL_MODEL_DEFAULTS[name]} value={values[name] ?? ''} onChange={(event) => onChange(changeThermalValue(values, name, event.target.value))} />}
    </span>
  </div>;
}

/** The first thing still missing or invalid in the setup, in plain words; empty when it is complete. */
export function thermalValidation(values: Record<string, string>, mechanicalW = 0, layout: RotorLayout = 'inner', unit: TemperatureUnit = 'C'): string {
  try { thermalInputs(values, mechanicalW, layout, unit); return ''; } catch (error) { return error instanceof Error ? error.message : 'Review the thermal inputs.'; }
}

const COOLING_KEYS = ['cooling', 'housing_h_W_m2K', 'end_space_h_W_m2K', 'airgap_h_W_m2K', 'coefficient_source'] as const;

export function ThermalCoolingFields({ values, onChange, mechanicalW, layout }: GroupProps) {
  const custom = values.cooling && values.cooling !== 'still_air';
  const missing = ['housing_h_W_m2K', 'end_space_h_W_m2K', 'airgap_h_W_m2K'].some((name) => !values[name]?.trim());
  return <div className="thermal-fields">
    <div className="public-excitation-selector thermal-cooling-selector" role="radiogroup" aria-label="Thermal cooling">
      {COOLING_MODES.map((mode) => <button key={mode.value} type="button" role="radio" aria-checked={values.cooling === mode.value}
        className={values.cooling === mode.value ? 'active' : ''} onClick={() => onChange(changeThermalValue(values, 'cooling', mode.value))}>
        <strong>{mode.label}</strong><small>{mode.hint}</small>
      </button>)}
    </div>
    <Field name="ambient_C" values={values} onChange={onChange} layout={layout} />
    <p className="thermal-group-title">How fast heat leaves
      <InfoTip label="Heat transfer values help" align="end"><div className="public-analysis-help">
        <p>Each value is in W/m²K: the watts that cross one square metre of surface for every degree of temperature difference. A higher number means better cooling.</p>
        <p className="popover-note">These three values set most of the result. They are assumptions about your installation until you measure them.</p>
      </div></InfoTip>
    </p>
    {custom && missing && <p className="thermal-setup-hint" role="note">Enter the three values for your {values.cooling === 'forced_air' ? 'airflow' : 'coolant'}. Each one&apos;s <b>i</b> gives typical ranges.</p>}
    <Field name="housing_h_W_m2K" values={values} onChange={onChange} layout={layout} />
    <Field name="end_space_h_W_m2K" values={values} onChange={onChange} layout={layout} />
    <Field name="airgap_h_W_m2K" values={values} onChange={onChange} layout={layout} />
    <Field name="coefficient_source" type="text" values={values} onChange={onChange} layout={layout} />
    <button type="button" className="thermal-starter-button" onClick={() => onChange({ ...values, ...Object.fromEntries(COOLING_KEYS.map((key) => [key, THERMAL_STARTER[key]])) })}>Use still-air starter values</button>
  </div>;
}

export function ThermalInsulationFields({ values, onChange, layout }: GroupProps) {
  const id = useId();
  const rating = INSULATION_CLASSES.find((row) => row.value === values.insulation_class)?.limit_C;
  const limit = windingLimitC(values);
  const [unit] = useTemperatureUnit();
  const symbol = unitSymbol(unit);
  const allowance = Number(values.hotspot_allowance_K);
  return <div className="thermal-fields">
    <div className="param-row public-param-row thermal-param-row">
      <span className="param-label"><label htmlFor={id}>Insulation class</label>
        <InfoTip label="Insulation class help" align="end"><div className="public-analysis-help">
          <p>The thermal class of the winding wire and slot insulation: the highest temperature they are rated to run at continuously. It is printed on the wire or motor datasheet.</p>
          <p className="popover-note">{INSULATION_CLASSES.map((row, index) => `${index ? '' : 'Class '}${row.value} ${shownTemperature(row.limit_C, unit)} ${symbol}`).join(' · ')}.</p>
        </div></InfoTip>
      </span>
      <span className="param-control">
        <select id={id} className="param-select" aria-label="Thermal insulation class" value={values.insulation_class ?? ''} onChange={(event) => onChange(changeThermalValue(values, 'insulation_class', event.target.value))}>
          <option value="">Select class</option>
          {INSULATION_CLASSES.map((row) => <option key={row.value} value={row.value}>Class {row.value} · {shownTemperature(row.limit_C, unit)} {symbol}</option>)}
        </select>
      </span>
    </div>
    <Field name="hotspot_allowance_K" values={values} onChange={onChange} layout={layout} />
    {limit !== null && rating !== undefined && <p className="thermal-limit-line" role="note">Winding limit used: <strong>{shownTemperature(limit, unit)} {symbol}</strong>. That is the {shownTemperature(rating, unit)} {symbol} rating less the {Number.isFinite(allowance) ? Number(differenceIn(allowance, unit).toFixed(2)) : values.hotspot_allowance_K} {symbol} allowance.</p>}
  </div>;
}

export function ThermalConstructionFields({ values, onChange, layout }: GroupProps) {
  return <div className="thermal-fields">
    {(layout === 'outer'
      ? ['mount_to_ambient_K_W', 'contact_m2K_W', 'slot_liner_mm', 'bearing_to_housing_K_W', 'rotor_to_bearing_K_W']
      : ['housing_thickness_mm', 'slot_liner_mm', 'contact_m2K_W', 'bearing_to_housing_K_W', 'rotor_to_bearing_K_W']).map((name) => <Field key={name} name={name} values={values} onChange={onChange} layout={layout} />)}
  </div>;
}

export function ThermalRotorFields({ values, onChange, layout }: GroupProps) {
  return <div className="thermal-fields">
    <p className="thermal-setup-hint" role="note">The rotor and magnets are warmed by heat from the stator{layout === 'outer' ? ' and cooled by the air over the rotor shell' : ''}. Their own eddy-current heat is not calculated yet, so their temperatures are a lower estimate.</p>
    <Field name="extra_rotor_heat_W" values={values} onChange={onChange} layout={layout} />
    <Field name="extra_rotor_heat_to_magnets_fraction" values={values} onChange={onChange} layout={layout} />
  </div>;
}

export function ThermalAdvancedFields({ values, onChange, mechanicalW = 0, layout }: GroupProps) {
  const id = useId();
  const userSlot = values.slot_k_model === 'user';
  const calibrated = Boolean(values.calibration_multiplier?.trim()) && Number(values.calibration_multiplier) !== 1;
  return <div className="thermal-fields">
    {/* Where friction and windage heat goes is asked only when the operating point has such a loss. */}
    {mechanicalW > 0 && <>
      <p className="thermal-group-title">Mechanical loss</p>
      <p className="thermal-setup-hint" role="note">This run has {mechanicalW} W of mechanical loss. Say where it turns into heat; the three shares must total 100.</p>
      {['mechanical_bearings', 'mechanical_housing', 'mechanical_rotor'].map((name) => <Field key={name} name={name} values={values} onChange={onChange} layout={layout} />)}
    </>}
    <p className="thermal-group-title">Heat conduction in the stator</p>
    <div className="param-row public-param-row thermal-param-row">
      <span className="param-label"><label htmlFor={id}>Slot conductivity</label>
        <InfoTip label="Slot conductivity model help" align="end"><div className="public-analysis-help">
          <p>How well heat crosses the wound slot. The default treats copper and resin as layers in series, which is the lowest it can be, so it reads hot. Choose your own value if you have a measured or published one.</p>
        </div></InfoTip>
      </span>
      <span className="param-control">
        <select id={id} className="param-select" aria-label="Slot conductivity model" value={values.slot_k_model ?? 'series_lower_bound'} onChange={(event) => onChange(changeThermalValue(values, 'slot_k_model', event.target.value))}>
          <option value="series_lower_bound">Lowest bound</option><option value="user">My own value</option>
        </select>
      </span>
    </div>
    {userSlot && <><Field name="slot_k_W_mK" values={values} onChange={onChange} layout={layout} /><Field name="slot_k_source" type="text" values={values} onChange={onChange} layout={layout} /></>}
    <Field name="steel_k_W_mK" values={values} onChange={onChange} layout={layout} />
    <p className="thermal-group-title">Calibration to a measurement</p>
    <Field name="calibration_multiplier" values={values} onChange={onChange} layout={layout} />
    {calibrated && ['cal_measurement', 'cal_operating_point', 'cal_cooling'].map((name) => <Field key={name} name={name} type="text" values={values} onChange={onChange} layout={layout} />)}
    <button type="button" className="thermal-starter-button" onClick={() => onChange({ ...THERMAL_STARTER })}>Reset all thermal inputs</button>
  </div>;
}

/** Every thermal input on one page, for editing beside a result. Solve shows the same groups as separate sections. */
export function ThermalSetup({ values, onChange, mechanicalW = 0, layout = 'inner' }: GroupProps) {
  const [unit] = useTemperatureUnit();
  const validation = thermalValidation(values, mechanicalW, layout, unit);
  const group = { values, onChange, mechanicalW, layout };
  return <div className="thermal-setup-form">
    <h4>Cooling</h4><ThermalCoolingFields {...group} />
    <h4>Winding insulation</h4><ThermalInsulationFields {...group} />
    <h4>Construction</h4><ThermalConstructionFields {...group} />
    <h4>Rotor and magnets</h4><ThermalRotorFields {...group} />
    <details><summary>Advanced</summary><ThermalAdvancedFields {...group} /></details>
    {validation && <p className="thermal-setup-validation" role="status">{validation}</p>}
    <p className="thermal-setup-note">Saved for this design in this browser.</p>
  </div>;
}
