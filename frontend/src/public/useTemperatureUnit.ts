import { useSyncExternalStore } from 'react';
import { readTemperatureUnit, subscribeTemperatureUnit, writeTemperatureUnit, type TemperatureUnit } from './thermalUnits';

/** The chosen temperature unit, shared by every thermal view on the page. */
export function useTemperatureUnit(): [TemperatureUnit, (unit: TemperatureUnit) => void] {
  return [useSyncExternalStore(subscribeTemperatureUnit, readTemperatureUnit, () => 'C' as TemperatureUnit), writeTemperatureUnit];
}
