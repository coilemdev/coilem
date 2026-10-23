/**
 * Magnet temperature (#137): what the Solve page shows next to the input.
 *
 * Mirrors backend/magnet_temperature.py, which the solve uses; a Python test
 * checks the coefficients match. They are the reversible temperature
 * coefficients in Arnold's NdFeB grade table, in %/°C from 20 °C. Br scales
 * the magnet flux in the solve; HcJ is for the demagnetisation margin, which
 * is not evaluated yet.
 */

import { MAGNET_TEMPERATURE_STATUS_REASON, type OutputStatus } from './outputStatus';

export interface GradeTemperature {
  alphaBr: number;
  alphaHcj: number;
  /** Arnold's minimum HcJ at 20 °C, kA/m. */
  hcj20: number;
  maxOperating: number;
}

export const GRADE_TEMPERATURE: Record<string, GradeTemperature> = {
  N35: { alphaBr: -0.12, alphaHcj: -0.618, hcj20: 955, maxOperating: 80 },
  N42: { alphaBr: -0.12, alphaHcj: -0.75, hcj20: 955, maxOperating: 80 },
  N48: { alphaBr: -0.12, alphaHcj: -0.75, hcj20: 955, maxOperating: 80 },
  N52: { alphaBr: -0.12, alphaHcj: -0.75, hcj20: 876, maxOperating: 60 },
  N48SH: { alphaBr: -0.12, alphaHcj: -0.535, hcj20: 1512, maxOperating: 150 },
};

export const REFERENCE_TEMP_C = 20;
const MIN_TEMP_C = -40;
const MAX_TEMP_C = 200;
const MIN_HCJ_SHARE = 0.25;

/** Where a grade's linear coefficients are used, or null for a grade without cited coefficients. */
export function magnetTemperatureRange(grade: string): [number, number] | null {
  const row = GRADE_TEMPERATURE[grade];
  if (!row) return null;
  return [MIN_TEMP_C, Math.min(MAX_TEMP_C, REFERENCE_TEMP_C + (MIN_HCJ_SHARE - 1) / (row.alphaHcj / 100))];
}

export interface MagnetTemperatureView {
  available: boolean;
  /** The range the input accepts; null without coefficients. */
  range: [number, number] | null;
  /** One line under the input: the derated Br and HcJ, or why there is no temperature input. */
  note: string;
  /** Above the grade's rated temperature. */
  warning: string | null;
  /** The derating's status, when the temperature derates the magnet (public issue 143). */
  status: OutputStatus | null;
}

const signed = (value: number, digits = 1) => `${value < 0 ? '−' : '+'}${Math.abs(value).toFixed(digits)}`;

/** The line under the Magnet temperature input for a grade, its 20 °C Br and the chosen temperature. */
export function magnetTemperatureView(grade: string, br20T: number | null | undefined, temperatureC: number): MagnetTemperatureView {
  const row = GRADE_TEMPERATURE[grade];
  const range = magnetTemperatureRange(grade);
  if (!row || !range) {
    return {
      available: false,
      range: null,
      note: `No cited temperature coefficients for ${grade}: the solve uses its 20 °C values.`,
      warning: null,
      status: null,
    };
  }
  const delta = temperatureC - REFERENCE_TEMP_C;
  const brChange = row.alphaBr * delta;
  const hcj = row.hcj20 * (1 + (row.alphaHcj / 100) * delta);
  const brText = typeof br20T === 'number' && Number.isFinite(br20T)
    ? `Br ${(br20T * (1 + brChange / 100)).toFixed(3)} T`
    : 'Br';
  const note = delta === 0
    ? `20 °C: the catalogue values (${row.alphaBr} %/°C Br, ${row.alphaHcj} %/°C HcJ from 20 °C; Arnold).`
    : `${brText} (${signed(brChange)}%), HcJ about ${Math.round(hcj)} kA/m at ${temperatureC} °C. Range ${range[0]} to ${Math.round(range[1])} °C.`;
  const warning = temperatureC > row.maxOperating
    ? `${grade} is rated to ${row.maxOperating} °C: above it the magnet risks irreversible demagnetisation, which coilEM does not model.`
    : null;
  const status: OutputStatus | null = delta === 0 ? null : { status: 'experimental', reason: MAGNET_TEMPERATURE_STATUS_REASON };
  return { available: true, range, note, warning, status };
}
