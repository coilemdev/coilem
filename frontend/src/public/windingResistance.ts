/**
 * Winding resistance and slot fill from the design preview (#136).
 *
 * The backend (backend/winding_resistance.py) returns the phase resistance at
 * 20 °C with the conductor's temperature coefficient, so the Design panel can
 * show it at the current winding temperature without asking for a new preview:
 * R(T) = R20 · (1 + coefficient · (T − 20)).
 */

import { PHASE_RESISTANCE_UNRECORDED_STATUS_REASON, STATUS_LABEL, recordStatus, type OutputStatus } from './outputStatus';
import type { PerformanceOutputStatus } from './performance';

export interface WindingResistance {
  wire_source: 'specified' | 'derived';
  conductor: 'copper' | 'aluminum';
  strand_diameter_mm: number;
  strands_in_hand: number;
  turn_copper_area_mm2: number;
  conductors_per_slot: number;
  series_turns_per_phase: number;
  parallel_paths: number;
  slot_area_mm2: number;
  copper_fill: number;
  copper_fill_limit: number;
  wire_fill?: number | null;
  fits: boolean;
  stack_length_mm: number;
  end_turn_length_mm: number;
  mean_turn_length_mm: number;
  active_fraction: number;
  phase_resistance_20C_ohm: number;
  temperature_coefficient_per_K: number;
  winding_temperature_C: number;
  phase_resistance_ohm: number;
  notes: string[];
  /** Absent on previews and runs from before the record carried it (outputStatus.ts). */
  status?: PerformanceOutputStatus;
  status_reason?: string | null;
}

export interface WindingReadoutRow {
  key: 'fill' | 'resistance' | 'turn';
  label: string;
  /** The small tag beside the label, such as the temperature the value is at. */
  tag: string;
  text: string;
  hint: string;
  warning: boolean;
  /** The phase resistance's status (public issue 143); its reason ends the hint. */
  status?: OutputStatus;
}

const REFERENCE_TEMPERATURE_C = 20;
const NUMBER_FIELDS: Array<keyof WindingResistance> = [
  'strand_diameter_mm',
  'copper_fill',
  'copper_fill_limit',
  'end_turn_length_mm',
  'mean_turn_length_mm',
  'active_fraction',
  'phase_resistance_20C_ohm',
  'temperature_coefficient_per_K',
];

/** The preview's record, or null when it is missing or malformed. */
export function readWindingResistance(raw: unknown): WindingResistance | null {
  if (!raw || typeof raw !== 'object') return null;
  const record = raw as Record<string, unknown>;
  for (const field of NUMBER_FIELDS) {
    if (typeof record[field] !== 'number' || !Number.isFinite(record[field] as number)) return null;
  }
  if (record.wire_source !== 'specified' && record.wire_source !== 'derived') return null;
  return {
    ...(record as unknown as WindingResistance),
    notes: Array.isArray(record.notes) ? record.notes.filter((note): note is string => typeof note === 'string') : [],
  };
}

export function resistanceAt(record: WindingResistance, temperatureC: number): number {
  return record.phase_resistance_20C_ohm * (1 + record.temperature_coefficient_per_K * (temperatureC - REFERENCE_TEMPERATURE_C));
}

/** Ohms with three significant figures, in mΩ below one ohm. */
export function formatResistance(ohm: number): string {
  if (!Number.isFinite(ohm)) return '—';
  const [value, unit] = Math.abs(ohm) < 1 ? [ohm * 1000, 'mΩ'] : [ohm, 'Ω'];
  return `${Number(value.toPrecision(3)).toString()} ${unit}`;
}

const percent = (fraction: number) => `${Math.round(fraction * 100)}%`;

export function windingReadout(record: WindingResistance, temperatureC: number): WindingReadoutRow[] {
  const atTemperature = resistanceAt(record, temperatureC);
  const showsHot = Math.abs(temperatureC - REFERENCE_TEMPERATURE_C) > 1e-9;
  const status = recordStatus(record, PHASE_RESISTANCE_UNRECORDED_STATUS_REASON);
  const wire = record.wire_source === 'derived'
    ? `Derived ${record.strand_diameter_mm.toFixed(2)} mm wire.`
    : `${record.strands_in_hand} × ${record.strand_diameter_mm} mm wire.`;
  return [
    {
      key: 'fill',
      label: 'Slot Fill',
      tag: 'calc',
      text: `${percent(record.copper_fill)} Cu`,
      hint: `Bare copper over the ${Math.round(record.slot_area_mm2)} mm² slot; limit ${percent(record.copper_fill_limit)}.`
        + (record.wire_fill != null ? ` Insulated wire ${percent(record.wire_fill)}.` : ''),
      warning: !record.fits,
    },
    {
      key: 'resistance',
      label: 'Phase R',
      tag: `${Math.round(showsHot ? temperatureC : REFERENCE_TEMPERATURE_C)} °C`,
      text: formatResistance(showsHot ? atTemperature : record.phase_resistance_20C_ohm),
      hint: `${wire} ${formatResistance(record.phase_resistance_20C_ohm)} at 20 °C, ${record.series_turns_per_phase} turns per phase in ${record.parallel_paths} path${record.parallel_paths === 1 ? '' : 's'}. `
        + `${STATUS_LABEL[status.status]}: ${status.reason}`,
      warning: false,
      status,
    },
    {
      key: 'turn',
      label: 'Mean Turn',
      tag: 'calc',
      text: `${Math.round(record.mean_turn_length_mm)} mm`,
      hint: `${percent(record.active_fraction)} of each turn is in the stack; each end turn is ${Math.round(record.end_turn_length_mm)} mm.`,
      warning: false,
    },
  ];
}
