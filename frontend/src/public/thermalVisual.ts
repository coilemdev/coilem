import type { ThermalEstimate, ThermalNode } from './thermal';
import { differenceIn, temperatureIn, unitSymbol, type TemperatureUnit } from './thermalUnits';

export const THERMAL_NODE_LABELS: Record<string, string> = {
  ambient: 'Ambient / coolant', housing: 'Housing', mount: 'Stator mount', yoke: 'Stator yoke', teeth: 'Stator teeth',
  winding: 'Slot winding', end_winding: 'End winding', rotor: 'Rotor', magnets: 'Magnets',
  airgap: 'Air gap', end_air: 'End-space air', bearings: 'Bearings',
};
export const thermalNodeLabel = (name: string) => THERMAL_NODE_LABELS[name] ?? name.replace(/_/g, ' ');
export const thermalNumber = (value: number) => value.toLocaleString(undefined, { maximumSignificantDigits: 4 });
export function nodeTemperature(node: ThermalNode | undefined): number | null {
  return node?.status === 'experimental' && node.temperature_C != null && Number.isFinite(node.temperature_C) ? node.temperature_C : null;
}
export function thermalRange(nodes: ThermalEstimate['nodes']): [number, number] | null {
  const values = Object.values(nodes).flatMap((node) => { const t = nodeTemperature(node); return t === null ? [] : [t]; });
  return values.length ? [Math.min(...values), Math.max(...values)] : null;
}
// Temperature scale only: colour does not encode safety or a qualified limit.
export function thermalColour(temperature: number, range: [number, number]): string {
  const t = range[1] === range[0] ? .5 : Math.max(0, Math.min(1, (temperature - range[0]) / (range[1] - range[0])));
  const stops = [[75, 147, 224], [238, 185, 82], [238, 102, 69]];
  const [a, b] = t < .5 ? [stops[0], stops[1]] : [stops[1], stops[2]];
  const f = t < .5 ? t * 2 : (t - .5) * 2;
  return `rgb(${a.map((channel, i) => Math.round(channel + (b[i] - channel) * f)).join(', ')})`;
}
/** A temperature given in °C, as a number in the chosen unit. */
export const temperatureNumber = (celsius: number, unit: TemperatureUnit = 'C') => thermalNumber(temperatureIn(celsius, unit));
/** A temperature given in °C, with its unit: "164.1 °C". */
export const temperatureText = (celsius: number, unit: TemperatureUnit = 'C') => `${temperatureNumber(celsius, unit)} ${unitSymbol(unit)}`;
/** A temperature difference given in K, as a number in the chosen unit. */
export const differenceNumber = (kelvin: number, unit: TemperatureUnit = 'C') => thermalNumber(differenceIn(kelvin, unit));
/** A temperature difference given in K, with the unit temperatures are shown in: "24.1 °C". */
export const differenceText = (kelvin: number, unit: TemperatureUnit = 'C') => `${differenceNumber(kelvin, unit)} ${unitSymbol(unit)}`;

export function thermalMargin(node: ThermalNode | undefined, unit: TemperatureUnit = 'C'): string {
  if (!node || nodeTemperature(node) === null || node.margin_K == null || !Number.isFinite(node.margin_K)) return 'No margin available';
  if (node.margin_K < 0) return `${differenceText(-node.margin_K, unit)} above limit`;
  if (node.margin_K === 0) return 'At recorded limit';
  return `${differenceText(node.margin_K, unit)} below limit`;
}

/** The winding node closest to, or furthest past, its limit. */
export function tightestWinding(result: ThermalEstimate): ThermalNode | undefined {
  return [result.nodes.end_winding, result.nodes.winding]
    .filter((node): node is ThermalNode => nodeTemperature(node) !== null && node?.margin_K != null)
    .sort((a, b) => a.margin_K! - b.margin_K!)[0];
}

/** All the heat the estimate places in the motor's parts. */
export const thermalTotalHeat = (result: ThermalEstimate) => Object.values(result.nodes).reduce((sum, node) => sum + (node.heat_W || 0), 0);
