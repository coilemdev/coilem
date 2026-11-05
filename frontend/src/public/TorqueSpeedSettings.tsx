import { useId, useState } from 'react';
import type { MotorConfig } from './model';
import type { DriveLimits, TorqueSpeedAnalysisSettings } from './performance';
import { currentUnits } from './performanceView';
import { InfoTip } from './Popover';
import { torqueSpeedSettings } from './torqueSpeedAnalysis';

export function TorqueSpeedSettings({ config, busy, onChange }: {
  config: MotorConfig;
  busy: boolean;
  onChange: (settings: TorqueSpeedAnalysisSettings) => void;
}) {
  const id = useId();
  const settings = torqueSpeedSettings(config);
  const { limits } = settings;
  const units = currentUnits(config.solve_params.current_amplitude_convention);
  const [error, setError] = useState<string | null>(null);
  const setLimit = (key: keyof DriveLimits, input: HTMLInputElement, isCurrent = false) => {
    const value = key === 'continuous_current_A' && input.value.trim() === '' ? null : Number(input.value);
    const next = value === null ? null : isCurrent ? units.toPeak(value) : value;
    const updated = { ...limits, [key]: next };
    if ((next !== null && (!Number.isFinite(next) || next <= 0))
      || (key === 'dc_bus_V' && (next! < 1 || next! > 2000))
      || (isCurrent && next !== null && next > 5000)
      || (key === 'max_speed_rpm' && next! > 100000)
      || (updated.continuous_current_A != null && updated.continuous_current_A > updated.peak_current_A)) {
      const previous = limits[key];
      input.value = previous == null ? '' : String(isCurrent ? units.fromPeak(previous) : previous);
      setError('Enter positive limits; Continuous current must not exceed Peak current.');
      return;
    }
    setError(null);
    onChange({ ...settings, limits: updated });
  };
  const fields: Array<{ key: 'peak_current_A' | 'continuous_current_A' | 'dc_bus_V' | 'max_speed_rpm'; label: string; unit: string; help: string; current?: boolean }> = [
    { key: 'peak_current_A', label: 'Peak current', unit: units.unit, current: true, help: 'Short-term phase-current limit. The map solves currents up to this limit.' },
    { key: 'continuous_current_A', label: 'Continuous current', unit: units.unit, current: true, help: 'The current your cooling can sustain. Leave empty for a peak curve only.' },
    { key: 'dc_bus_V', label: 'DC bus', unit: 'V', help: 'Enter your supply voltage. The initial value is the design voltage, or 48 V when no supply is specified.' },
    { key: 'max_speed_rpm', label: 'Top speed', unit: 'rpm', help: 'The highest shaft speed covered by the curves and efficiency map.' },
  ];
  return (
    <section className="public-map-settings" aria-label="Torque–speed map settings">
      {fields.map((field) => {
        const value = limits[field.key];
        const shown = value == null ? '' : field.current ? Number(units.fromPeak(value).toFixed(2)) : value;
        return (
          <div className="public-map-setting" key={field.key}>
            <label htmlFor={`${id}-${field.key}`}>{field.label}</label>
            <InfoTip label={`${field.label} help`}>{field.help}</InfoTip>
            <div className="public-map-setting-input">
              <input id={`${id}-${field.key}`} key={shown} type="number" step="any" min={field.key === 'dc_bus_V' ? 1 : 0.1}
                disabled={busy} defaultValue={shown} onBlur={(event) => setLimit(field.key, event.currentTarget, field.current)} />
              <span>{field.unit}</span>
            </div>
          </div>
        );
      })}
      <label className="public-map-setting-select">Drive control
        <select aria-label="Drive control" disabled={busy} value={settings.control} onChange={(event) => onChange({ ...settings, control: event.target.value as TorqueSpeedAnalysisSettings['control'] })}>
          <option value="mtpa">MTPA, then field weakening</option>
          <option value="least_loss">Least loss</option>
        </select>
      </label>
      <label className="public-map-setting-select">Map grid
        <select aria-label="Map grid" disabled={busy} value={settings.preset} onChange={(event) => onChange({ ...settings, preset: event.target.value as TorqueSpeedAnalysisSettings['preset'] })}>
          <option value="preview">Preview · 5 currents × 7 angles · 29 solves</option>
          <option value="standard">Standard · 7 currents × 10 angles · 61 solves</option>
        </select>
      </label>
      <p className="public-map-settings-note">Uses its own sinusoidal current and angle grid, including torque, flux linkage and losses. Accuracy plan controls the mesh. Finished points are kept for resume.</p>
      {error && <p role="alert" className="public-map-settings-note">{error}</p>}
    </section>
  );
}
