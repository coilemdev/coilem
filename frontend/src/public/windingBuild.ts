/**
 * Can this winding be made? Checks on the wire the preview reports
 * (windingResistance.ts): whether it fits the slot, passes through the slot
 * mouth, and can be formed. The limits are winders' rules of thumb for round
 * enamelled wire, stated in each check; they say when a winding will not go in,
 * and only that one should, never that it will.
 */

import { AWG_SIZES } from './wireGauge';
import type { WindingResistance } from './windingResistance';

export interface WindingBuildCheck {
  severity: 'positive' | 'warning';
  title: string;
  copy: string;
}

export interface WindingBuildInput {
  record: WindingResistance;
  /** Clear width of the slot mouth, after any tooth shoes, in millimetres. */
  slotMouthMm: number;
  windingType: 'concentrated' | 'distributed';
  /** Narrowest tooth width, which a tooth coil's wire has to bend round, in millimetres. */
  toothWidthMm: number;
}

/** Insulated wire takes this share of the slot before winding gets tight, and this much before it will not go in. */
export const WIRE_FILL_COMFORTABLE = 0.55;
export const WIRE_FILL_LIMIT = 0.7;
/** Slot liner and working clearance the wire needs on top of its own diameter to pass the slot mouth. */
export const SLOT_MOUTH_CLEARANCE_MM = 0.3;
/** Single strands thicker than this are hard to form by hand. */
export const STIFF_STRAND_MM = 1.6;

/** Grade 2 enamelled wire's outside diameter from its bare one, to within a few hundredths of a millimetre. */
export function insulatedDiameterMm(bareDiameterMm: number): number {
  return bareDiameterMm * 1.07 + 0.02;
}

/** The share of the slot the insulated wire takes: the preview's own figure where it has one. */
export function insulatedWireFill(record: WindingResistance): number {
  if (typeof record.wire_fill === 'number' && Number.isFinite(record.wire_fill)) return record.wire_fill;
  const insulated = insulatedDiameterMm(record.strand_diameter_mm);
  return record.conductors_per_slot * record.strands_in_hand * Math.PI * insulated ** 2 / 4 / Math.max(1e-9, record.slot_area_mm2);
}

/** How far the end turns stand past each end of the stack, taking each as a half circle of its length. */
export function endTurnOverhangMm(record: WindingResistance): number {
  return record.end_turn_length_mm / Math.PI;
}

/** A suggested wire is split into strands in hand no thicker than this, so it lays easily. */
export const SUGGESTED_STRAND_MM = 1.25;
// As many as the Winding section's Strands in Hand accepts.
const MOST_STRANDS_IN_HAND = 200;

/**
 * The derived wire as something that can be bought and wound: a standard gauge,
 * in the fewest strands in hand that carry the same copper, each passing the slot
 * mouth and thin enough to lay. Null when no gauge gets through the mouth within
 * the strand limit.
 */
export function suggestedStrands(turnDiameterMm: number, slotMouthMm: number): { strands: number; strandDiameterMm: number; gauge: number } | null {
  // One wire where the whole turn is thin enough to form; otherwise strands no thicker than lays easily.
  const thickest = turnDiameterMm <= STIFF_STRAND_MM ? turnDiameterMm : SUGGESTED_STRAND_MM;
  for (const { gauge, diameterMm } of AWG_SIZES) {
    if (diameterMm > thickest + 1e-9) continue;
    if (insulatedDiameterMm(diameterMm) + SLOT_MOUTH_CLEARANCE_MM > slotMouthMm) continue;
    const strands = Math.max(1, Math.round((turnDiameterMm / diameterMm) ** 2));
    if (strands > MOST_STRANDS_IN_HAND) return null;
    return { strands, strandDiameterMm: diameterMm, gauge };
  }
  return null;
}

const mm = (value: number) => `${Number(value.toFixed(2))} mm`;
const percent = (fraction: number) => `${Math.round(fraction * 100)}%`;

export function windingBuildChecks({ record, slotMouthMm, windingType, toothWidthMm }: WindingBuildInput): WindingBuildCheck[] {
  const checks: WindingBuildCheck[] = [];
  const insulated = insulatedDiameterMm(record.strand_diameter_mm);
  const fill = insulatedWireFill(record);
  const wire = `${record.strands_in_hand} × ${mm(record.strand_diameter_mm)}`;
  const overhang = `End turns stand about ${Math.round(endTurnOverhangMm(record))} mm past each end of the stack.`;

  if (record.wire_source === 'derived') {
    // A suggestion, not a wire anyone chose: offer it as strands that can actually be wound in.
    const split = suggestedStrands(record.strand_diameter_mm, slotMouthMm);
    if (split) {
      checks.push({
        severity: 'positive',
        title: `Suggested wire: ${split.strands} × AWG ${split.gauge} (${mm(split.strandDiameterMm)})`,
        copy: `${percent(record.copper_fill)} copper fill for ${record.conductors_per_slot} conductors a slot${split.strands > 1 ? `, as strands in hand that pass the ${mm(slotMouthMm)} slot mouth` : ''}. Set the wire in Winding to check a real one. ${overhang}`,
      });
    } else {
      checks.push({
        severity: 'warning',
        title: 'No wire passes the slot mouth',
        copy: `The slot mouth is ${mm(slotMouthMm)}, too narrow for strands of the ${mm(record.strand_diameter_mm)} wire this slot would take. Open the slot or shorten the tooth shoes.`,
      });
    }
    return checks;
  } else if (fill > WIRE_FILL_LIMIT) {
    checks.push({
      severity: 'warning',
      title: 'Too much wire for the slot',
      copy: `${record.conductors_per_slot} conductors of ${wire} take ${percent(fill)} of the slot with their enamel. Round wire rarely goes in past about ${percent(WIRE_FILL_LIMIT)}: use thinner wire, fewer turns or a deeper slot.`,
    });
  } else if (fill > WIRE_FILL_COMFORTABLE) {
    checks.push({
      severity: 'warning',
      title: 'Slot is tight to wind',
      copy: `The insulated wire takes ${percent(fill)} of the slot. Above about ${percent(WIRE_FILL_COMFORTABLE)} it needs careful hand winding or formed coils, and a winding needle will not manage it. ${overhang}`,
    });
  } else {
    checks.push({
      severity: 'positive',
      title: 'Wire fits the slot',
      copy: `The insulated wire takes ${percent(fill)} of the slot, within the ${percent(WIRE_FILL_COMFORTABLE)} that winds comfortably. ${overhang}`,
    });
  }

  const mouthNeeded = insulated + SLOT_MOUTH_CLEARANCE_MM;
  if (slotMouthMm < mouthNeeded) {
    checks.push({
      severity: 'warning',
      title: 'Wire does not pass the slot mouth',
      copy: `The slot mouth is ${mm(slotMouthMm)}; ${mm(insulated)} insulated wire needs about ${mm(mouthNeeded)} with its liner. Open the slot, shorten the tooth shoes, or wind thinner strands in hand.`,
    });
  } else {
    const needle = insulated * 3;
    checks.push({
      severity: 'positive',
      title: 'Wire passes the slot mouth',
      copy: `${mm(insulated)} insulated wire through a ${mm(slotMouthMm)} mouth.${windingType === 'concentrated' && slotMouthMm < needle ? ` A winding needle needs about ${mm(needle)}, so this one is wound by hand.` : ''}`,
    });
  }

  if (record.wire_source === 'specified') {
    const sharpBend = windingType === 'concentrated' && toothWidthMm > 0 && toothWidthMm < record.strand_diameter_mm * 4;
    if (record.strand_diameter_mm > STIFF_STRAND_MM || sharpBend) {
      checks.push({
        severity: 'warning',
        title: 'Wire is stiff to form',
        copy: sharpBend
          ? `${mm(record.strand_diameter_mm)} wire has to bend round a ${mm(toothWidthMm)} tooth, tighter than about four wire diameters. Use more strands in hand of thinner wire.`
          : `Single strands above about ${mm(STIFF_STRAND_MM)} are hard to lay by hand. The same copper as more strands in hand of thinner wire winds more easily.`,
      });
    }
  }
  return checks;
}
