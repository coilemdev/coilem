import type { PublicParameterSection } from './CoilEmWorkspace';
import type { MotorConfig } from './model';

export interface GuidedConfigAdjustment {
  field: string;
  label: string;
  previous: number | string | null;
  next: number | string | null;
}

export interface GuidedConfigRepair {
  config: MotorConfig;
  adjustments: GuidedConfigAdjustment[];
}

const MIN_ROTOR_OD_MM = 15;
const MIN_MAGNET_THICKNESS_MM = 2;
const MIN_SPM_MAGNET_WIDTH_MM = 5;
const MIN_SLOT_OPENING_MM = 2;
const MIN_TOOTH_WIDTH_MM = 2;
const MIN_SLOT_BODY_WIDTH_MM = 0.5;
const TARGET_AIRGAP_MM = 0.5;
// backend/models/config.py WindingConfig.parallel_paths le=32 (#91).
const MAX_PARALLEL_PATHS = 32;

function floorToTenth(value: number): number {
  return Math.floor((value + 1e-9) * 10) / 10;
}

type Phase = 'A' | 'B' | 'C';
type Direction = 'in' | 'out';

// Mirrors backend/winding_utils.py: the 60-degree sector order and the bias that
// keeps q = 1/2 coil phasors, which sit on sector boundaries, assigned stably.
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

/** Fractional-slot concentrated windings (q < 1) are real tooth coils (#91). */
export function concentratedUsesToothCoils(slotCount: number, poleCount: number): boolean {
  return slotCount > 0 && slotCount % 3 === 0 && poleCount > 0 && slotCount < 3 * poleCount;
}

/** (phase, direction) of each wound tooth: alternate teeth with one layer, every tooth with two. */
function toothCoils(slotCount: number, poleCount: number, layers: number): { tooth: number; phase: Phase; direction: Direction }[] {
  const pitch = electricalSlotPitchRad(slotCount, poleCount);
  const coils: { tooth: number; phase: Phase; direction: Direction }[] = [];
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
  for (const { tooth, phase, direction } of toothCoils(slotCount, poleCount, layers)) {
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
export function concentratedGuidedLayoutIsBalanced(
  slotCount: number,
  poleCount: number,
  layers = 1,
): boolean {
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

/** Coils each phase has, which parallel paths must divide (backend/geometry.py validate_geometry). */
export function coilsPerPhase(slotCount: number, poleCount: number, windingType: string, layers: number): number {
  if (windingType === 'distributed') return Math.floor(slotCount / 6);
  if (concentratedUsesToothCoils(slotCount, poleCount)) {
    return Math.floor(toothCoils(slotCount, poleCount, layers).length / 3);
  }
  return Math.floor(slotCount / 3);
}

function nearestBalancedPoleCount(slotCount: number, currentPoleCount: number, layers: number): number | null {
  if (concentratedGuidedLayoutIsBalanced(slotCount, currentPoleCount, layers)) return currentPoleCount;
  const candidates = Array.from({ length: 16 }, (_, index) => (index + 1) * 2)
    .filter((poleCount) => concentratedGuidedLayoutIsBalanced(slotCount, poleCount, layers))
    .sort((left, right) => (
      Math.abs(left - currentPoleCount) - Math.abs(right - currentPoleCount)
      || left - right
    ));
  return candidates[0] ?? null;
}

/**
 * Repair only the section the coach is about to reveal.
 *
 * Upstream choices remain untouched: entering Rotor may adapt its still-unseen
 * defaults to a stator the user just changed, while entering Advanced Geometry
 * may clamp its stored tooth/yoke defaults to the new envelope. Once a section
 * has been shown, later transitions never revisit and silently rewrite it.
 */
export function repairGuidedSection(
  config: MotorConfig,
  section: PublicParameterSection,
): GuidedConfigRepair {
  // Experimental HoleM50 rotors carry their own pocket geometry; the flat and
  // V-shape repairs below would rewrite it, so leave such designs untouched.
  if (config.topology === 'IPM' && config.rotor.ipm_topology === 'pyleecan_holem50') {
    return { config, adjustments: [] };
  }
  const next = structuredClone(config);
  const adjustments: GuidedConfigAdjustment[] = [];

  const adjust = (
    field: string,
    label: string,
    previous: number | string | null,
    value: number | string | null,
    apply: () => void,
  ) => {
    if (Object.is(previous, value)) return;
    apply();
    adjustments.push({ field, label, previous, next: value });
  };

  if (section === 'rotor') {
    if (next.winding.type === 'concentrated') {
      const balancedPoleCount = nearestBalancedPoleCount(
        next.stator.slot_count,
        next.rotor.pole_count,
        next.winding.layers,
      );
      if (balancedPoleCount !== null) {
        adjust(
          'rotor.pole_count',
          'pole count',
          next.rotor.pole_count,
          balancedPoleCount,
          () => { next.rotor.pole_count = balancedPoleCount; },
        );
      }
    }

    if (next.topology === 'SPM') {
      const maximumThicknessForMinimumRotor = (
        next.stator.ID_mm - MIN_ROTOR_OD_MM
      ) / 2 - TARGET_AIRGAP_MM;
      if (
        maximumThicknessForMinimumRotor >= MIN_MAGNET_THICKNESS_MM
        && next.rotor.magnet_thickness_mm > maximumThicknessForMinimumRotor
      ) {
        const repairedThickness = floorToTenth(maximumThicknessForMinimumRotor);
        adjust(
          'rotor.magnet_thickness_mm',
          'magnet thickness',
          next.rotor.magnet_thickness_mm,
          repairedThickness,
          () => { next.rotor.magnet_thickness_mm = repairedThickness; },
        );
      }
    }

    const maximumRotorOd = next.topology === 'SPM'
      ? next.stator.ID_mm - 2 * (next.rotor.magnet_thickness_mm + TARGET_AIRGAP_MM)
      : next.stator.ID_mm - 2 * TARGET_AIRGAP_MM;
    if (maximumRotorOd >= MIN_ROTOR_OD_MM && next.rotor.OD_mm > maximumRotorOd) {
      const repairedRotorOd = floorToTenth(maximumRotorOd);
      adjust(
        'rotor.OD_mm',
        'rotor OD',
        next.rotor.OD_mm,
        repairedRotorOd,
        () => { next.rotor.OD_mm = repairedRotorOd; },
      );
    }

    if (next.rotor.ID_mm !== null && next.rotor.ID_mm >= next.rotor.OD_mm) {
      const repairedRotorId = Math.max(0, floorToTenth(next.rotor.OD_mm - 1));
      adjust(
        'rotor.ID_mm',
        'rotor ID',
        next.rotor.ID_mm,
        repairedRotorId,
        () => { next.rotor.ID_mm = repairedRotorId; },
      );
    }

    const maximumMagnetThickness = next.rotor.OD_mm / 4;
    if (
      maximumMagnetThickness >= MIN_MAGNET_THICKNESS_MM
      && next.rotor.magnet_thickness_mm > maximumMagnetThickness
    ) {
      const repairedThickness = floorToTenth(maximumMagnetThickness);
      adjust(
        'rotor.magnet_thickness_mm',
        'magnet thickness',
        next.rotor.magnet_thickness_mm,
        repairedThickness,
        () => { next.rotor.magnet_thickness_mm = repairedThickness; },
      );
    }

    if (
      next.rotor.pole_count > 0
      && (next.topology !== 'IPM' || next.rotor.ipm_topology !== 'v_shape')
    ) {
      const magnetCenterRadius = next.topology === 'SPM'
        ? next.rotor.OD_mm / 2 + next.rotor.magnet_thickness_mm / 2
        : next.rotor.OD_mm / 2
          - next.rotor.bridge_thickness_mm
          - next.rotor.pocket_clearance_mm
          - next.rotor.magnet_thickness_mm / 2;
      const polePitchAtMagnet = 2 * Math.PI * Math.max(1, magnetCenterRadius)
        / next.rotor.pole_count;
      const bridgeAllowance = next.topology === 'IPM'
        ? 2 * (next.rotor.side_bridge_thickness_mm + next.rotor.pocket_clearance_mm)
        : 0;
      const geometryLimit = polePitchAtMagnet - bridgeAllowance;
      const minimumWidth = next.topology === 'SPM' ? MIN_SPM_MAGNET_WIDTH_MM : 0.1;
      if (geometryLimit >= minimumWidth && next.rotor.magnet_width_mm > geometryLimit) {
        const coverageTarget = geometryLimit * Math.min(0.95, Math.max(0.1, next.rotor.magnet_embrace));
        const repairedWidth = Math.max(minimumWidth, floorToTenth(coverageTarget));
        adjust(
          'rotor.magnet_width_mm',
          'magnet width',
          next.rotor.magnet_width_mm,
          repairedWidth,
          () => { next.rotor.magnet_width_mm = repairedWidth; },
        );
      }
    }
  }

  if (section === 'advanced') {
    const radialBuild = (next.stator.OD_mm - next.stator.ID_mm) / 2;
    const maximumYokeThickness = floorToTenth(radialBuild - 2);
    if (
      maximumYokeThickness >= 2
      && next.stator.yoke_thickness_mm > maximumYokeThickness
    ) {
      adjust(
        'stator.yoke_thickness_mm',
        'yoke thickness',
        next.stator.yoke_thickness_mm,
        maximumYokeThickness,
        () => { next.stator.yoke_thickness_mm = maximumYokeThickness; },
      );
    }

    const borePitch = Math.PI * next.stator.ID_mm / Math.max(1, next.stator.slot_count);
    const maximumSlotOpening = floorToTenth(borePitch - 0.1);
    if (
      maximumSlotOpening >= MIN_SLOT_OPENING_MM
      && next.stator.slot_opening_mm > maximumSlotOpening
    ) {
      adjust(
        'stator.slot_opening_mm',
        'bore slot opening',
        next.stator.slot_opening_mm,
        maximumSlotOpening,
        () => { next.stator.slot_opening_mm = maximumSlotOpening; },
      );
    }

    const slotRadialDepth = Math.max(0, radialBuild - next.stator.yoke_thickness_mm);
    const bodyRadius = next.stator.ID_mm / 2 + slotRadialDepth;
    const bodyPitch = 2 * Math.PI * bodyRadius / Math.max(1, next.stator.slot_count);
    const maximumToothWidth = floorToTenth(bodyPitch - MIN_SLOT_BODY_WIDTH_MM);
    if (
      maximumToothWidth >= MIN_TOOTH_WIDTH_MM
      && next.stator.tooth_width_mm > maximumToothWidth
    ) {
      adjust(
        'stator.tooth_width_mm',
        'yoke tooth width',
        next.stator.tooth_width_mm,
        maximumToothWidth,
        () => { next.stator.tooth_width_mm = maximumToothWidth; },
      );
    }

    if (
      next.stator.tooth_shoe_enabled
      && (next.stator.tooth_shoe_overhang_mm ?? 0) * 2 >= next.stator.slot_opening_mm
    ) {
      const repairedOverhang = Math.max(
        0,
        floorToTenth((next.stator.slot_opening_mm - 0.1) / 2),
      );
      adjust(
        'stator.tooth_shoe_overhang_mm',
        'tooth-shoe overhang',
        next.stator.tooth_shoe_overhang_mm ?? 0,
        repairedOverhang,
        () => { next.stator.tooth_shoe_overhang_mm = repairedOverhang; },
      );
    }
  }

  if (section === 'winding') {
    const terminalCoilsPerPhase = coilsPerPhase(
      next.stator.slot_count,
      next.rotor.pole_count,
      next.winding.type,
      next.winding.layers,
    );
    if (
      terminalCoilsPerPhase > 0
      && terminalCoilsPerPhase % next.winding.parallel_paths !== 0
    ) {
      const repairedPaths = Array.from(
        { length: Math.min(MAX_PARALLEL_PATHS, terminalCoilsPerPhase) },
        (_, index) => index + 1,
      )
        .filter((candidate) => terminalCoilsPerPhase % candidate === 0)
        .reverse()
        .find((candidate) => candidate <= next.winding.parallel_paths) ?? 1;
      adjust(
        'winding.parallel_paths',
        'parallel paths',
        next.winding.parallel_paths,
        repairedPaths,
        () => { next.winding.parallel_paths = repairedPaths; },
      );
    }

    if (next.winding.type === 'concentrated' && next.winding.coil_span != null) {
      adjust(
        'winding.coil_span',
        'coil span',
        next.winding.coil_span,
        null,
        () => { delete next.winding.coil_span; },
      );
    }
  }

  return {
    config: adjustments.length > 0 ? next : config,
    adjustments,
  };
}
