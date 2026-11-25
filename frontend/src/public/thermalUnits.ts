/**
 * The unit every temperature in the thermal setup and results is shown in.
 *
 * The estimate itself always works in °C; this is how its numbers are read
 * and typed. Differences (a margin to a limit, an allowance) use the same
 * unit as temperatures, so a card never mixes °C and K.
 */
export type TemperatureUnit = 'C' | 'F' | 'K';

export const TEMPERATURE_UNITS: ReadonlyArray<{ value: TemperatureUnit; symbol: string; name: string }> = [
  { value: 'C', symbol: '°C', name: 'Celsius' },
  { value: 'F', symbol: '°F', name: 'Fahrenheit' },
  { value: 'K', symbol: 'K', name: 'Kelvin' },
];

export const unitSymbol = (unit: TemperatureUnit): string => (unit === 'K' ? 'K' : `°${unit}`);

/** A temperature in °C, in the chosen unit. */
export const temperatureIn = (celsius: number, unit: TemperatureUnit): number => (
  unit === 'F' ? celsius * 9 / 5 + 32 : unit === 'K' ? celsius + 273.15 : celsius);
/** A temperature in the chosen unit, in °C. */
export const temperatureFrom = (value: number, unit: TemperatureUnit): number => (
  unit === 'F' ? (value - 32) * 5 / 9 : unit === 'K' ? value - 273.15 : value);
/** A temperature difference in K, in the chosen unit. A kelvin and a degree Celsius are the same step. */
export const differenceIn = (kelvin: number, unit: TemperatureUnit): number => (unit === 'F' ? kelvin * 9 / 5 : kelvin);
/** A temperature difference in the chosen unit, in K. */
export const differenceFrom = (value: number, unit: TemperatureUnit): number => (unit === 'F' ? value * 5 / 9 : value);

const KEY = 'coilem.thermal.temperatureUnit';
const CHANGED = 'coilem-thermal-unit';
// Where storage is unavailable the choice still holds for the session.
let fallback: TemperatureUnit = 'C';
const isUnit = (value: unknown): value is TemperatureUnit => value === 'C' || value === 'F' || value === 'K';

export function readTemperatureUnit(): TemperatureUnit {
  try {
    const saved = localStorage.getItem(KEY);
    return isUnit(saved) ? saved : fallback;
  } catch { return fallback; }
}

export function writeTemperatureUnit(unit: TemperatureUnit): void {
  fallback = unit;
  try { localStorage.setItem(KEY, unit); } catch { /* Optional browser persistence. */ }
  window.dispatchEvent(new Event(CHANGED));
}

/** Call `listener` whenever the chosen unit changes, here or in another tab. Returns the unsubscribe. */
export function subscribeTemperatureUnit(listener: () => void): () => void {
  window.addEventListener(CHANGED, listener);
  window.addEventListener('storage', listener);
  return () => { window.removeEventListener(CHANGED, listener); window.removeEventListener('storage', listener); };
}
