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

function floorToTenth(value: number): number {
  return Math.floor((value + 1e-9) * 10) / 10;
}

function phaseForConcentratedSlot(
  slotIndex: number,
  slotCount: number,
  poleCount: number,
): 'A' | 'B' | 'C' {
  const phases = ['A', 'C', 'B', 'A', 'C', 'B'] as const;
  const polePairs = Math.max(1, poleCount / 2);
  const electricalAngleDeg = (slotIndex * 360 * polePairs / slotCount) % 360;
  return phases[Math.floor(electricalAngleDeg / 60) % phases.length];
}

export function concentratedGuidedLayoutIsBalanced(
  slotCount: number,
  poleCount: number,
): boolean {
  if (!Number.isInteger(slotCount) || slotCount < 1 || !Number.isInteger(poleCount) || poleCount < 2) {
    return false;
  }
  const counts = { A: 0, B: 0, C: 0 };
  for (let slotIndex = 0; slotIndex < slotCount; slotIndex += 1) {
    counts[phaseForConcentratedSlot(slotIndex, slotCount, poleCount)] += 1;
  }
  return counts.A > 0 && counts.A === counts.B && counts.B === counts.C;
}

function nearestBalancedPoleCount(slotCount: number, currentPoleCount: number): number | null {
  if (concentratedGuidedLayoutIsBalanced(slotCount, currentPoleCount)) return currentPoleCount;
  const candidates = Array.from({ length: 16 }, (_, index) => (index + 1) * 2)
    .filter((poleCount) => concentratedGuidedLayoutIsBalanced(slotCount, poleCount))
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
    const terminalCoilsPerPhase = next.winding.type === 'distributed'
      ? Math.floor(next.stator.slot_count / 6)
      : Math.floor(next.stator.slot_count / 3);
    if (
      terminalCoilsPerPhase > 0
      && terminalCoilsPerPhase % next.winding.parallel_paths !== 0
    ) {
      const repairedPaths = Array.from(
        { length: Math.min(6, terminalCoilsPerPhase) },
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
