/**
 * Losses and efficiency of a completed run (#138), as rows, bar segments and
 * a density color scale for the Results card.
 *
 * The backend (backend/loss_breakdown.py) keeps the solved torque unchanged:
 * iron and mechanical loss act as a drag, so the shaft delivers
 * P_shaft = T·ω − P_iron − P_mech and the input is P_in = T·ω + P_copper.
 */

import { formatSignificant } from './numberFormat';
import { PHASE_RESISTANCE_UNRECORDED_STATUS_REASON, recordStatus, type NamedOutputStatus } from './outputStatus';
import type { IronLoss, LossBreakdown, PerformanceOutputStatus, RotorIronLoss } from './performance';
import type { WindingResistance } from './windingResistance';

/** The loss rows the bar's segments belong to: where the loss is. */
export type LossGroup = 'copper' | 'iron' | 'rotor_iron' | 'mechanical';

export interface LossSegment {
  key: 'copper_stack' | 'copper_end' | 'iron_hysteresis' | 'iron_eddy' | 'rotor_hysteresis' | 'rotor_eddy' | 'mechanical';
  /** The loss row this segment is part of. */
  group: LossGroup;
  /** Full name, for the bar readout: "Stator iron, lamination eddy". */
  label: string;
  /** Name under its loss row: "Lamination eddy". */
  shortLabel: string;
  watts: number;
  share: number;
  /** Rounded share of the bar's total, "85%"; shares of a loss row's segments add up to the row's. */
  shareText: string;
  /** What the segment is, in words. */
  about: string;
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
  /** On a loss row: the bar segments' group it heads. */
  group?: LossGroup;
  /** On a segment row: the loss row it is part of. Its key is the segment's key. */
  parent?: LossGroup;
  /** The bar segments the row stands for: its own, or its components'. */
  segments?: LossSegment['key'][];
  /** Rounded share of the bar's total, on rows the bar shows. */
  share?: string;
  /** Series color of the row's own segment: a segment row, or a loss row with only one. */
  color?: string;
  /** On a loss row with segment rows: whether they show before the user opens or closes them. */
  expanded?: boolean;
}

export interface LossesView {
  /** `text` with its % sign, `value` without it for a table cell. */
  efficiency: { text: string; value: string; status: PerformanceOutputStatus; reason: string };
  /** Loss rows, each followed by its segment rows: the table is the bar's legend. */
  rows: LossRow[];
  /** Efficiency, iron loss and copper loss, each with its status and reason in words. */
  statuses: NamedOutputStatus[];
  segments: LossSegment[];
  totalW: number;
}

const HYSTERESIS = 'Energy spent re-magnetising the steel every cycle; it grows in proportion to frequency.';
const LAMINATION_EDDY = 'Currents induced inside each steel sheet; they grow with frequency squared. Eddy loss in the magnets is a different loss and is not modelled.';

const SEGMENTS: Array<{ key: LossSegment['key']; group: LossGroup; label: string; shortLabel: string; about: string; field: keyof LossBreakdown }> = [
  { key: 'copper_stack', group: 'copper', label: 'Copper, stack', shortLabel: 'Stack', about: 'Copper loss in the coil sides along the stack.', field: 'copper_active_loss_W' },
  { key: 'copper_end', group: 'copper', label: 'Copper, end turns', shortLabel: 'End turns', about: 'Copper loss in the end turns, outside the 2D cross-section.', field: 'copper_end_winding_loss_W' },
  { key: 'iron_hysteresis', group: 'iron', label: 'Stator iron, hysteresis', shortLabel: 'Hysteresis', about: HYSTERESIS, field: 'iron_hysteresis_loss_W' },
  { key: 'iron_eddy', group: 'iron', label: 'Stator iron, lamination eddy', shortLabel: 'Lamination eddy', about: LAMINATION_EDDY, field: 'iron_eddy_loss_W' },
  { key: 'rotor_hysteresis', group: 'rotor_iron', label: 'Rotor iron, hysteresis', shortLabel: 'Hysteresis', about: HYSTERESIS, field: 'rotor_hysteresis_loss_W' },
  { key: 'rotor_eddy', group: 'rotor_iron', label: 'Rotor iron, lamination eddy', shortLabel: 'Lamination eddy', about: LAMINATION_EDDY, field: 'rotor_lamination_eddy_loss_W' },
  { key: 'mechanical', group: 'mechanical', label: 'Mechanical', shortLabel: 'Mechanical', about: 'Friction and windage as entered under Operating point.', field: 'mechanical_loss_W' },
];


const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const significant = (value: number, digits = 3) => Number(value.toPrecision(digits)).toString().replace('-', '−');

/** Watts with three significant figures, trailing zeros kept, in kW from 1 kW. */
export function formatPower(watts: number): { value: string; unit: string } {
  if (!finite(watts)) return { value: '—', unit: '' };
  const shown = (value: number) => formatSignificant(value).replace('-', '−');
  return Math.abs(watts) >= 1000 ? { value: shown(watts / 1000), unit: 'kW' } : { value: shown(watts), unit: 'W' };
}

/** What the loss breakdown leaves out, in words. */
export function notModelledText(loss: LossBreakdown): string {
  return 'Not modelled: ' + (finite(loss.rotor_iron_loss_W) ? '' : 'rotor iron loss, ')
    + 'magnet/component eddy-current loss, AC copper loss (skin and proximity effects), inverter loss'
    + (loss.mechanical_loss_W > 0 ? '.' : ', and mechanical loss unless entered under Operating point.');
}

/**
 * Whole percents that add up to `total` (largest remainder), so rounded shares
 * never disagree with the sum they are part of.
 */
export function roundShares(values: readonly number[], total: number): number[] {
  const sum = values.reduce((acc, value) => acc + value, 0);
  if (!(sum > 0)) return values.map(() => 0);
  const exact = values.map((value) => (value / sum) * total);
  const rounded = exact.map(Math.floor);
  const order = exact.map((value, index) => ({ index, rest: value - Math.floor(value) })).sort((a, b) => b.rest - a.rest || a.index - b.index);
  for (let left = total - rounded.reduce((acc, value) => acc + value, 0), i = 0; left > 0 && i < order.length; left -= 1, i += 1) rounded[order[i].index] += 1;
  return rounded;
}

/** A rounded percent, or "<1%" for a share too small to round to one. */
export function shareText(percent: number, share: number): string {
  return percent === 0 && share > 0 ? '<1%' : `${percent}%`;
}

const GROUPS: LossGroup[] = ['copper', 'iron', 'rotor_iron', 'mechanical'];

export function lossSegments(loss: LossBreakdown): { segments: LossSegment[]; totalW: number; groupShares: Record<LossGroup, { share: number; percent: number }> } {
  const parts = SEGMENTS
    .map((part) => ({ ...part, watts: loss[part.field] as number | null | undefined }))
    .filter((part): part is (typeof SEGMENTS)[number] & { watts: number } => finite(part.watts) && part.watts > 0);
  const totalW = parts.reduce((sum, part) => sum + part.watts, 0);
  // Round each loss row's share of 100, then split that among its segments.
  const groupWatts = GROUPS.map((group) => parts.filter((part) => part.group === group).reduce((sum, part) => sum + part.watts, 0));
  const groupPercents = roundShares(groupWatts, 100);
  const percents = new Map<LossSegment['key'], number>();
  GROUPS.forEach((group, index) => {
    const members = parts.filter((part) => part.group === group);
    roundShares(members.map((part) => part.watts), groupPercents[index]).forEach((percent, member) => percents.set(members[member].key, percent));
  });
  const groupShares = Object.fromEntries(GROUPS.map((group, index) => [group, {
    share: totalW > 0 ? groupWatts[index] / totalW : 0, percent: groupPercents[index],
  }])) as Record<LossGroup, { share: number; percent: number }>;
  return {
    totalW,
    groupShares,
    segments: parts.map(({ field: _field, ...part }) => {
      const share = totalW > 0 ? part.watts / totalW : 0;
      return { ...part, share, shareText: shareText(percents.get(part.key) ?? 0, share), color: `var(--loss-${part.key.replace('_', '-')})` };
    }),
  };
}

function powerRow(key: string, label: string, watts: number, hint?: string, status?: PerformanceOutputStatus): LossRow {
  const { value, unit } = formatPower(watts);
  return { key, label, value, unit, hint, status };
}

/** How the rotor iron loss was sampled, and how much of it lies outside the material model's range. */
export function rotorSamplingText(rotor: RotorIronLoss | null | undefined): string {
  if (!rotor || rotor.status === 'unavailable') return '';
  const outside = rotor.share_above_validated_frequency;
  return `Rotor iron: ${rotor.steel}, ${rotor.samples_per_mechanical_turn} positions over a full mechanical turn.`
    + (finite(outside) && outside > 0 ? ` ${(100 * outside).toFixed(1)}% of the estimate is above the material model’s ${rotor.validated_max_frequency_Hz} Hz range.` : '');
}

/** The card's content, or null for a run without a loss breakdown. */
export function lossesView(
  loss: LossBreakdown | null | undefined,
  iron: IronLoss | null | undefined,
  winding: WindingResistance | null = null,
  rotor: RotorIronLoss | null = null,
): LossesView | null {
  if (!loss) return null;
  const efficiencyAvailable = finite(loss.efficiency_pct);
  const efficiencyValue = efficiencyAvailable ? (loss.efficiency_pct as number).toFixed(1) : '—';
  const efficiency = {
    text: efficiencyAvailable ? `${efficiencyValue}%` : '—',
    value: efficiencyValue,
    status: efficiencyAvailable ? loss.efficiency_status : 'unavailable' as PerformanceOutputStatus,
    reason: loss.efficiency_status_reason ?? '',
  };
  const ironAvailable = finite(loss.iron_loss_W);
  const rotorAvailable = finite(loss.rotor_iron_loss_W) && loss.rotor_iron_loss_status !== 'unavailable';
  const rotorRequested = loss.rotor_iron_loss_status != null;
  const ironParts: string[] = [];
  if (ironAvailable) {
    ironParts.push(`Hysteresis ${formatPower(loss.iron_hysteresis_loss_W ?? NaN).value} W, lamination eddy ${formatPower(loss.iron_eddy_loss_W ?? NaN).value} W.`);
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
  const { segments, totalW, groupShares } = lossSegments(loss);
  const resistance = loss.phase_resistance_ohm < 1
    ? `${significant(loss.phase_resistance_ohm * 1000)} mΩ`
    : `${significant(loss.phase_resistance_ohm)} Ω`;
  const copperStatus = recordStatus(winding, PHASE_RESISTANCE_UNRECORDED_STATUS_REASON);
  const rotorNote = rotorSamplingText(rotor);
  const statuses: NamedOutputStatus[] = [];
  statuses.push({ key: 'efficiency', label: 'Efficiency', ...efficiency });
  statuses.push({ key: 'iron', label: 'Stator iron loss and its map', status: loss.iron_loss_status, reason: iron?.status_reason ?? loss.iron_loss_status_reason ?? '' });
  if (rotorRequested) statuses.push({ key: 'rotor_iron', label: 'Rotor iron loss',
    status: loss.rotor_iron_loss_status ?? 'unavailable', reason: [loss.rotor_iron_loss_status_reason, rotorNote].filter(Boolean).join(' ') });
  statuses.push({ key: 'copper', label: 'Copper loss, from the phase resistance', ...copperStatus });
  // A loss row is followed by one row per bar segment it holds, so the table is the bar's legend.
  const withSegments = (row: LossRow, group: LossGroup): LossRow[] => {
    const members = segments.filter((segment) => segment.group === group);
    if (!members.length) return [{ ...row, group }];
    const { share, percent } = groupShares[group];
    const parent: LossRow = { ...row, group, segments: members.map((member) => member.key), share: shareText(percent, share) };
    if (members.length === 1) return [{ ...parent, color: members[0].color }];
    return [
      // Every breakdown starts closed: the card opens on its totals, and a row is opened to see its parts.
      { ...parent, expanded: false },
      ...members.map((member): LossRow => ({
        key: member.key, label: member.shortLabel, ...formatPower(member.watts), hint: `${member.label}: ${member.about}`,
        parent: group, segments: [member.key], share: member.shareText, color: member.color,
      })),
    ];
  };
  const rotorShown = rotorRequested || segments.some((segment) => segment.group === 'rotor_iron');
  const rows: LossRow[] = [
    powerRow('input', 'Input power', loss.input_power_W, 'Electrical input: the solved torque times speed, plus copper loss.'),
    powerRow('shaft', 'Shaft power', loss.shaft_power_W, 'Solved torque times speed, less iron and mechanical loss.'),
    { key: 'torque', label: 'Shaft torque', value: formatSignificant(loss.shaft_torque_Nm).replace('-', '−'), unit: 'N·m',
      hint: `The solved torque, ${significant(loss.electromagnetic_torque_Nm, 4)} N·m, less the iron and mechanical loss torque. The solved torque is unchanged.` },
    ...withSegments(powerRow('copper', 'Copper loss', loss.copper_loss_W,
      `3 × (${significant(loss.phase_current_rms_A)} A rms)² × ${resistance} at ${significant(loss.winding_temperature_C)} °C. `
      + `Stack ${formatPower(loss.copper_active_loss_W).value} W, end turns ${formatPower(loss.copper_end_winding_loss_W).value} W.`,
      copperStatus.status), 'copper'),
    ...withSegments(ironAvailable
      ? powerRow('iron', 'Stator iron loss', loss.iron_loss_W as number, ironParts.join(' '), loss.iron_loss_status)
      : { key: 'iron', label: 'Stator iron loss', value: '—', unit: '', hint: ironParts.join(' '), status: 'unavailable' }, 'iron'),
    ...(rotorShown ? withSegments(rotorAvailable
      ? powerRow('rotor_iron', 'Rotor iron loss', loss.rotor_iron_loss_W as number,
        `Hysteresis ${formatPower(loss.rotor_hysteresis_loss_W ?? NaN).value} W, lamination eddy ${formatPower(loss.rotor_lamination_eddy_loss_W ?? NaN).value} W. `
          + (rotorNote ? `${rotorNote} ` : '') + (loss.rotor_iron_loss_status_reason ?? ''), loss.rotor_iron_loss_status ?? 'experimental')
      : { key: 'rotor_iron', label: 'Rotor iron loss', value: '—', unit: '',
        hint: loss.rotor_iron_loss_status_reason ?? 'Rotor iron loss is unavailable.', status: 'unavailable' as PerformanceOutputStatus }, 'rotor_iron') : []),
    ...withSegments(powerRow('mechanical', 'Mechanical loss', loss.mechanical_loss_W, 'Friction and windage as entered under Operating point; 0 when not set.'), 'mechanical'),
    powerRow('total', ironAvailable && (!rotorRequested || rotorAvailable) ? 'Total loss' : 'Known loss subtotal', loss.total_loss_W, notModelledText(loss)),
  ];
  return { efficiency, rows, statuses, segments, totalW };
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
/** Magnets on the map: a flat colour off the steel ramp, because no magnet loss is calculated. */
export const MAGNET_FILL = '#7a4b58';

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
