/**
 * Tooth-coil windings (#91): which concentrated layouts are wound as real tooth
 * coils, the phase and sign of each coil, and whether the layout balances.
 * Mirrors backend/winding_utils.py and backend/geometry.py; tests/fixtures/
 * tooth_coil_layouts.json holds both to the same layouts.
 */

export type Phase = 'A' | 'B' | 'C';
export type Direction = 'in' | 'out';

export interface ToothCoil {
  /** The tooth the coil wraps; its go side is in slot `tooth`, its return side in slot `tooth + 1`. */
  tooth: number;
  phase: Phase;
  direction: Direction;
}

// The 60-degree sector order, and the bias that keeps q = 1/2 coil phasors,
// which sit on sector boundaries, assigned stably.
const CONCENTRATED_SECTORS: readonly (readonly [Phase, Direction])[] = [
  ['A', 'in'], ['C', 'out'], ['B', 'in'], ['A', 'out'], ['C', 'in'], ['B', 'out'],
];
const SECTOR_BOUNDARY_BIAS_DEG = 1e-7;

function electricalSlotPitchRad(slotCount: number, poleCount: number): number {
  return 2 * Math.PI * (poleCount / 2) / Math.max(1, slotCount);
}

function sectorFor(angleDeg: number): readonly [Phase, Direction] {
  const wrapped = ((angleDeg % 360) + 360) % 360;
  return CONCENTRATED_SECTORS[Math.floor(wrapped / 60) % 6];
}

/** Fractional-slot concentrated windings (q < 1) are real tooth coils. */
export function concentratedUsesToothCoils(slotCount: number, poleCount: number): boolean {
  return slotCount > 0 && slotCount % 3 === 0 && poleCount > 0 && slotCount < 3 * poleCount;
}

/** The wound teeth: alternate teeth with one layer, every tooth with two. */
export function toothCoilAssignments(slotCount: number, poleCount: number, layers: number): ToothCoil[] {
  const pitch = electricalSlotPitchRad(slotCount, poleCount);
  const coils: ToothCoil[] = [];
  for (let tooth = 0; tooth < slotCount; tooth += layers >= 2 ? 1 : 2) {
    const re = Math.cos(pitch * tooth) - Math.cos(pitch * (tooth + 1));
    const im = Math.sin(pitch * tooth) - Math.sin(pitch * (tooth + 1));
    const [phase, direction] = sectorFor(Math.atan2(im, re) * 180 / Math.PI + SECTOR_BOUNDARY_BIAS_DEG);
    coils.push({ tooth, phase, direction });
  }
  return coils;
}

function toothCoilLayoutIsBalanced(slotCount: number, poleCount: number, layers: number): boolean {
  if (layers < 2 && slotCount % 2 !== 0) return false;
  const pitch = electricalSlotPitchRad(slotCount, poleCount);
  const counts = { A: 0, B: 0, C: 0 };
  const phasors = { A: [0, 0], B: [0, 0], C: [0, 0] };
  for (const { tooth, phase, direction } of toothCoilAssignments(slotCount, poleCount, layers)) {
    counts[phase] += 1;
    const sign = direction === 'in' ? 1 : -1;
    phasors[phase][0] += sign * (Math.cos(pitch * tooth) - Math.cos(pitch * (tooth + 1)));
    phasors[phase][1] += sign * (Math.sin(pitch * tooth) - Math.sin(pitch * (tooth + 1)));
  }
  if (!(counts.A > 0 && counts.A === counts.B && counts.B === counts.C)) return false;
  const magnitude = Math.hypot(phasors.A[0], phasors.A[1]);
  if (magnitude < 1e-9) return false;
  const angles = (['A', 'B', 'C'] as const).map((phase) => {
    if (Math.abs(Math.hypot(phasors[phase][0], phasors[phase][1]) - magnitude) > 1e-9 * Math.max(1, magnitude)) return NaN;
    return Math.atan2(phasors[phase][1], phasors[phase][0]) * 180 / Math.PI;
  });
  return angles.every((angle, index) => {
    const gap = (((angles[(index + 1) % 3] - angle) % 360) + 360) % 360;
    return Math.abs(gap - 120) <= 1e-6;
  });
}

function legacyConcentratedSlotPhase(slotIndex: number, slotCount: number, poleCount: number): Phase {
  const polePairs = Math.max(1, poleCount / 2);
  const electricalAngleDeg = (slotIndex * 360 * polePairs / slotCount) % 360;
  return CONCENTRATED_SECTORS[Math.floor(electricalAngleDeg / 60) % 6][0];
}

/** Mirrors backend/geometry.py concentrated_winding_is_balanced. */
export function concentratedLayoutIsBalanced(slotCount: number, poleCount: number, layers = 1): boolean {
  if (!Number.isInteger(slotCount) || slotCount < 1 || !Number.isInteger(poleCount) || poleCount < 2) {
    return false;
  }
  if (concentratedUsesToothCoils(slotCount, poleCount)) {
    return toothCoilLayoutIsBalanced(slotCount, poleCount, layers);
  }
  const counts = { A: 0, B: 0, C: 0 };
  for (let slotIndex = 0; slotIndex < slotCount; slotIndex += 1) {
    counts[legacyConcentratedSlotPhase(slotIndex, slotCount, poleCount)] += 1;
  }
  return counts.A > 0 && counts.A === counts.B && counts.B === counts.C;
}

export interface WindingLayerOption {
  layers: 1 | 2;
  available: boolean;
  /** Why the backend would refuse this layer count, or null when it accepts it. */
  reason: string | null;
}

/**
 * The layer counts a layout can be wound with. Tooth-coil layouts take one layer
 * (every other tooth) or two (every tooth) when the coils balance, so an odd slot
 * count needs two. Whole-slot concentrated maps keep one: backend/qualification.py
 * rejects a second layer there. Distributed windings take either; the backend
 * reports an unbalanced star-of-slots table.
 */
export function windingLayerOptions(slotCount: number, poleCount: number, windingType: string): WindingLayerOption[] {
  return ([1, 2] as const).map((layers) => {
    if (windingType === 'distributed') return { layers, available: true, reason: null };
    if (!concentratedUsesToothCoils(slotCount, poleCount)) {
      return layers === 1
        ? { layers, available: true, reason: null }
        : { layers, available: false, reason: 'needs a fractional-slot layout' };
    }
    return toothCoilLayoutIsBalanced(slotCount, poleCount, layers)
      ? { layers, available: true, reason: null }
      : { layers, available: false, reason: `unbalanced with ${slotCount} slots` };
  });
}

export interface WindingLayerWording {
  /** The Design panel label for `winding.layers`. */
  label: string;
  /** What each layer count is called; short enough to fit the select. */
  choice: Record<1 | 2, string>;
  /** The Winding section summary for each layer count. */
  summary: Record<1 | 2, string>;
  hint: string;
  /** Whole-slot concentrated maps wind one layer only; the row shows only to fix a second. */
  hidden: boolean;
}

/**
 * How `winding.layers` reads for a layout (#102). Tooth-coil users think in teeth
 * wound and distributed-winding users in coil sides per slot, not in layers.
 * The design file keeps `winding.layers` either way.
 */
export function windingLayerWording(slotCount: number, poleCount: number, windingType: string): WindingLayerWording {
  if (windingType === 'distributed') {
    return {
      label: 'Coil sides / slot',
      choice: { 1: '1', 2: '2' },
      summary: { 1: '1 coil side', 2: '2 coil sides' },
      hint: 'Single or double layer. Two-layer distributed windings are the benchmark-qualified option.',
      hidden: false,
    };
  }
  if (concentratedUsesToothCoils(slotCount, poleCount)) {
    return {
      label: 'Wound teeth',
      choice: { 1: 'Alternate', 2: 'All' },
      summary: { 1: 'alternate teeth', 2: 'all teeth' },
      hint: 'Alternate: a coil on every other tooth (single layer). All: a coil on every tooth, two coil sides per slot (double layer); not in the benchmark yet.',
      hidden: false,
    };
  }
  return {
    label: 'Layers',
    choice: { 1: '1', 2: '2' },
    summary: { 1: '1 layer', 2: '2 layers' },
    hint: 'This slot/pole combination winds one phase per slot, in one layer.',
    hidden: true,
  };
}

/**
 * Why a balanced concentrated layout with q >= 1 (6p/36s) has no Wound teeth
 * choice, or null when the note does not apply. An info note, not an error: the
 * layout still solves, as full-pitch coils with one phase per slot. The suggested
 * slot count is the q = 1/2 tooth-coil layout, 1.5 slots per pole.
 */
export function wholeSlotConcentratedNote(slotCount: number, poleCount: number, windingType: string): string | null {
  if (windingType !== 'concentrated' || poleCount % 2 !== 0) return null;
  if (concentratedUsesToothCoils(slotCount, poleCount) || !concentratedLayoutIsBalanced(slotCount, poleCount)) return null;
  return `For ${poleCount}p/${slotCount}s, coilEM's Concentrated option uses full-pitch coils with one phase per slot, `
    + "so Wound teeth doesn't apply. For tooth coils in coilEM with "
    + `${poleCount} poles, use fewer than ${3 * poleCount} slots, such as ${(3 * poleCount) / 2}.`;
}

/** Coils each phase has, which parallel paths must divide (backend/geometry.py validate_geometry). */
export function coilsPerPhase(slotCount: number, poleCount: number, windingType: string, layers: number): number {
  if (windingType === 'distributed') return Math.floor(slotCount / 6);
  if (concentratedUsesToothCoils(slotCount, poleCount)) {
    return Math.floor(toothCoilAssignments(slotCount, poleCount, layers).length / 3);
  }
  return Math.floor(slotCount / 3);
}
