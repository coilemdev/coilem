/**
 * Losses and efficiency of a completed run (#138), as rows, bar segments and
 * a density color scale for the Results card.
 *
 * The backend (backend/loss_breakdown.py) keeps the solved torque unchanged:
 * iron and mechanical loss act as a drag, so the shaft delivers
 * P_shaft = T·ω − P_iron − P_mech and the input is P_in = T·ω + P_copper.
 */

import type { IronLoss, LossBreakdown, PerformanceOutputStatus } from './performance';
import type { WindingResistance } from './windingResistance';

export interface LossSegment {
  key: 'copper_stack' | 'copper_end' | 'iron_hysteresis' | 'iron_eddy' | 'mechanical';
  label: string;
  watts: number;
  share: number;
  /** CSS custom property holding the segment's series color. */
  color: string;
}

export interface LossRow {
  key: string;
  label: string;
  value: string;
  unit: string;
  hint?: string;
  status?: PerformanceOutputStatus;
}

export interface LossesView {
  efficiency: { text: string; status: PerformanceOutputStatus; reason: string };
  rows: LossRow[];
  segments: LossSegment[];
  totalW: number;
}

const SEGMENTS: Array<{ key: LossSegment['key']; label: string; field: keyof LossBreakdown }> = [
  { key: 'copper_stack', label: 'Copper, stack', field: 'copper_active_loss_W' },
  { key: 'copper_end', label: 'Copper, end turns', field: 'copper_end_winding_loss_W' },
  { key: 'iron_hysteresis', label: 'Iron, hysteresis', field: 'iron_hysteresis_loss_W' },
  { key: 'iron_eddy', label: 'Iron, eddy current', field: 'iron_eddy_loss_W' },
  { key: 'mechanical', label: 'Mechanical', field: 'mechanical_loss_W' },
];

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const significant = (value: number, digits = 3) => Number(value.toPrecision(digits)).toString().replace('-', '−');

/** Watts with three significant figures, in kW from 1 kW. */
export function formatPower(watts: number): { value: string; unit: string } {
  if (!finite(watts)) return { value: '—', unit: '' };
  return Math.abs(watts) >= 1000 ? { value: significant(watts / 1000), unit: 'kW' } : { value: significant(watts), unit: 'W' };
}

export function lossSegments(loss: LossBreakdown): { segments: LossSegment[]; totalW: number } {
  const parts = SEGMENTS
    .map(({ key, label, field }) => ({ key, label, watts: loss[field] as number | null | undefined }))
    .filter((part): part is { key: LossSegment['key']; label: string; watts: number } => finite(part.watts) && part.watts > 0);
  const totalW = parts.reduce((sum, part) => sum + part.watts, 0);
  return {
    totalW,
    segments: parts.map((part) => ({ ...part, share: totalW > 0 ? part.watts / totalW : 0, color: `var(--loss-${part.key.replace('_', '-')})` })),
  };
}

function powerRow(key: string, label: string, watts: number, hint?: string, status?: PerformanceOutputStatus): LossRow {
  const { value, unit } = formatPower(watts);
  return { key, label, value, unit, hint, status };
}

/** The card's content, or null for a run without a loss breakdown. */
export function lossesView(loss: LossBreakdown | null | undefined, iron: IronLoss | null | undefined): LossesView | null {
  if (!loss) return null;
  const efficiencyAvailable = finite(loss.efficiency_pct);
  const efficiency = {
    text: efficiencyAvailable ? `${(loss.efficiency_pct as number).toFixed(1)}%` : '—',
    status: efficiencyAvailable ? loss.efficiency_status : 'unavailable' as PerformanceOutputStatus,
    reason: loss.efficiency_status_reason ?? '',
  };
  const ironAvailable = finite(loss.iron_loss_W);
  const ironParts: string[] = [];
  if (ironAvailable) {
    ironParts.push(`Hysteresis ${formatPower(loss.iron_hysteresis_loss_W ?? NaN).value} W, eddy current ${formatPower(loss.iron_eddy_loss_W ?? NaN).value} W.`);
    if (iron && finite(iron.iron_teeth_loss_W) && finite(iron.iron_yoke_loss_W)) {
      ironParts.push(`Teeth ${formatPower(iron.iron_teeth_loss_W).value} W, yoke ${formatPower(iron.iron_yoke_loss_W).value} W.`);
    }
    if (iron && finite(iron.share_above_validated_flux_density) && finite(iron.share_above_validated_frequency)) {
      ironParts.push(
        `${Math.round(iron.share_above_validated_flux_density * 100)}% comes from flux densities above ${iron.validated_max_flux_density_T} T `
        + `and ${Math.round(iron.share_above_validated_frequency * 100)}% from harmonics above ${iron.validated_max_frequency_Hz} Hz, outside the checked range.`,
      );
    }
  } else {
    ironParts.push(loss.iron_loss_status_reason || 'Iron loss is unavailable for this run.');
  }
  const { segments, totalW } = lossSegments(loss);
  const resistance = loss.phase_resistance_ohm < 1
    ? `${significant(loss.phase_resistance_ohm * 1000)} mΩ`
    : `${significant(loss.phase_resistance_ohm)} Ω`;
  const rows: LossRow[] = [
    powerRow('input', 'Input power', loss.input_power_W, 'Electrical input: the solved torque times speed, plus copper loss.'),
    powerRow('shaft', 'Shaft power', loss.shaft_power_W, 'Solved torque times speed, less iron and mechanical loss.'),
    { key: 'torque', label: 'Shaft torque', value: significant(loss.shaft_torque_Nm, 4), unit: 'N·m',
      hint: `The solved torque, ${significant(loss.electromagnetic_torque_Nm, 4)} N·m, less the iron and mechanical loss torque. The solved torque is unchanged.` },
    powerRow('copper', 'Copper loss', loss.copper_loss_W,
      `3 × (${significant(loss.phase_current_rms_A)} A rms)² × ${resistance} at ${significant(loss.winding_temperature_C)} °C. `
      + `Stack ${formatPower(loss.copper_active_loss_W).value} W, end turns ${formatPower(loss.copper_end_winding_loss_W).value} W.`),
    ironAvailable
      ? powerRow('iron', 'Iron loss', loss.iron_loss_W as number, ironParts.join(' '), loss.iron_loss_status)
      : { key: 'iron', label: 'Iron loss', value: '—', unit: '', hint: ironParts.join(' '), status: 'unavailable' },
    powerRow('mechanical', 'Mechanical loss', loss.mechanical_loss_W, 'Friction and windage as entered under Operating point; 0 when not set.'),
    powerRow('total', 'Total loss', loss.total_loss_W),
  ];
  return { efficiency, rows, segments, totalW };
}

type Rgb = [number, number, number];

const hexRgb = (hex: string): Rgb => [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16)) as Rgb;

/** Colour at a fraction of a ramp listed from the low end to the high end, interpolated between its steps. */
export function rampColor(stops: readonly string[], fraction: number): string {
  const ramp = stops.map(hexRgb);
  const t = Math.min(1, Math.max(0, finite(fraction) ? fraction : 0)) * (ramp.length - 1);
  const index = Math.min(ramp.length - 2, Math.floor(t));
  const local = t - index;
  const [a, b] = [ramp[index], ramp[index + 1]];
  const channel = (i: number) => Math.round(a[i] + (b[i] - a[i]) * local);
  return `rgb(${channel(0)}, ${channel(1)}, ${channel(2)})`;
}

// Iron-loss map: slate to pale steel, one hue, low to high, validated on the
// dark surface (ordinal: monotone lightness, the low end clears 2:1).
export const STEEL_RAMP = ['#415263', '#5d748b', '#7c99b2', '#a5c2d9', '#daebf7'] as const;
/** Copper loss in the map: the light copper of the loss bar. */
export const COPPER_FILL = '#c88335';
/** Stator parts drawn for context only, behind the loss being shown. */
export const CONTEXT_FILL = '#2a2e36';

/** Steel colour for a value as a fraction of the map's scale: lighter is more loss. */
export function densityColor(fraction: number): string {
  return rampColor(STEEL_RAMP, fraction);
}

export type LossMapMode = 'iron' | 'hysteresis' | 'eddy' | 'copper';

const CONDUCTOR_DENSITY_KG_M3: Record<WindingResistance['conductor'], number> = { copper: 8960, aluminum: 2700 };

/**
 * Copper loss per kilogram of the copper in the stack. The 2D model carries a
 * uniform current density in every coil side, so this one value holds in all
 * of them; the end turns' share lies outside the cross-section.
 */
export function stackCopperWPerKg(loss: LossBreakdown | null | undefined, winding: WindingResistance | null | undefined, slotCount: number): number | null {
  if (!loss || !winding || !(slotCount > 0) || !finite(loss.copper_active_loss_W)) return null;
  const copperM3 = slotCount * winding.copper_fill * winding.slot_area_mm2 * 1e-6 * winding.stack_length_mm * 1e-3;
  const kg = copperM3 * CONDUCTOR_DENSITY_KG_M3[winding.conductor];
  return kg > 0 ? loss.copper_active_loss_W / kg : null;
}
