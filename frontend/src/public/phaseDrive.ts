/**
 * The terminal currents a solve drives at each rotor position, for the 2D view's
 * Phases preview: the motor's phase colours and the A / B / C waveforms wired into
 * it follow these, so they light the phases the solver would.
 *
 * Public clockwise-positive frame, the one the preview spins in, normalised to the
 * peak (sine) or the plateau (six-step). It mirrors what a launch-surface solve
 * applies (backend.solver._clockwise_excitation_config, then
 * backend.excitation.resolve_phase_current_sample at the native angle -theta):
 *
 * - sine: i_k = sin(90 - theta - gamma - axis - 120 k);
 * - six-step: the public sector table at floor((theta + axis + advance) / 60).
 *
 * `axis` is phase A's axis, which the preview reports
 * (metadata.phase_axis_offset_elec_deg). tests/fixtures/public_sine_phase_current_vectors.json
 * and bldc_six_step_golden_vectors.json pin both against the solver.
 */

export type ExcitationMode = 'sinusoidal' | 'ideal_six_step_120';

export interface PhaseDrive {
  mode: ExcitationMode;
  /** gamma, from the q-axis; sine drive only. */
  currentAngleDeg: number;
  /** Six-step only. */
  commutationAdvanceDeg: number;
  /** Phase A's axis in electrical degrees, from the geometry preview. */
  axisOffsetDeg: number;
  poleCount: number;
}

/** Terminal A / B / C currents per sector, public clockwise frame (backend _PUBLIC_SIX_STEP_TABLE). */
export const PUBLIC_SIX_STEP_TABLE: ReadonlyArray<readonly [number, number, number]> = [
  [1, -1, 0],
  [0, -1, 1],
  [-1, 0, 1],
  [-1, 1, 0],
  [0, 1, -1],
  [1, 0, -1],
];

export function wrap360(angleDeg: number): number {
  const wrapped = ((angleDeg % 360) + 360) % 360;
  return wrapped === 360 ? 0 : wrapped;
}

/** The rotor's electrical angle at a mechanical preview angle. */
export function rotorElectricalDeg(rotorMechDeg: number, poleCount: number): number {
  return wrap360(rotorMechDeg * Math.max(1, Math.floor(poleCount / 2)));
}

/** A / B / C terminal currents at a rotor electrical angle, each in -1..1. */
export function phaseCurrents(drive: PhaseDrive, rotorElecDeg: number): [number, number, number] {
  if (drive.mode === 'ideal_six_step_120') {
    let effective = wrap360(rotorElecDeg + drive.axisOffsetDeg + drive.commutationAdvanceDeg);
    // Snap representation noise onto a commutation boundary, as the backend does.
    const boundary = Math.round(effective / 60) * 60;
    if (Math.abs(effective - boundary) <= 1e-12) effective = wrap360(boundary);
    const [a, b, c] = PUBLIC_SIX_STEP_TABLE[Math.floor(effective / 60) % 6];
    return [a, b, c];
  }
  const source = 90 - rotorElecDeg - drive.currentAngleDeg - drive.axisOffsetDeg;
  const at = (offset: number) => Math.sin(((source - offset) * Math.PI) / 180);
  return [at(0), at(120), at(240)];
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Below this canvas width the waveforms have no room; the motor stays centred. */
export const PHASE_DRIVE_MIN_WIDTH = 420;

/**
 * Where the waveforms and the motor go: the waveforms on the left, the motor
 * slightly smaller in what is left on the right. Null when the canvas is too
 * narrow, and the motor keeps the whole canvas.
 */
export function phaseDriveFrame(width: number, height: number): { panel: Rect; motor: Rect } | null {
  if (width < PHASE_DRIVE_MIN_WIDTH || height < 200) return null;
  const margin = Math.max(12, width * 0.03);
  const panelWidth = Math.min(300, Math.max(130, width * 0.28));
  const panelHeight = Math.min(330, Math.max(150, height * 0.5));
  const panel = { x: margin, y: (height - panelHeight) / 2, width: panelWidth, height: panelHeight };
  // A gap for the wires, then the motor, a little smaller than it would be alone.
  const motorX = panel.x + panel.width + Math.max(36, width * 0.05);
  const shrink = 0.9;
  const motorWidth = (width - motorX) * shrink;
  const motorHeight = height * shrink;
  return {
    panel,
    motor: { x: motorX + (width - motorX - motorWidth) / 2, y: (height - motorHeight) / 2, width: motorWidth, height: motorHeight },
  };
}

/** One waveform strip per phase, A on top. */
export function phaseStrips(panel: Rect): Rect[] {
  const pitch = panel.height / 3;
  const gap = Math.min(10, pitch * 0.18);
  return [0, 1, 2].map((index) => ({ x: panel.x, y: panel.y + index * pitch + gap / 2, width: panel.width, height: pitch - gap }));
}

/** Room at a strip's left for its phase letter, and at its right before the wire. */
export const STRIP_LABEL = 22;
export const STRIP_END = 8;

/**
 * A phase's current over the last electrical cycle, scrolling like a scope: the
 * right end is now, where the wire leaves, and the trace moves left as the rotor
 * turns. Points in canvas px.
 */
export function waveformTrace(
  drive: PhaseDrive,
  phaseIndex: number,
  rotorElecDeg: number,
  strip: Rect,
  samples = 180,
): Array<[number, number]> {
  const left = strip.x + STRIP_LABEL;
  const right = strip.x + strip.width - STRIP_END;
  const mid = strip.y + strip.height / 2;
  const amplitude = strip.height * 0.38;
  return Array.from({ length: samples + 1 }, (_, step) => {
    const t = step / samples;
    const value = phaseCurrents(drive, wrap360(rotorElecDeg - (1 - t) * 360))[phaseIndex];
    return [left + (right - left) * t, mid - value * amplitude];
  });
}

export interface WindingSide {
  slot_index: number;
  phase: 'A' | 'B' | 'C';
  direction: 'in' | 'out';
}

/**
 * Net current out of the page in each slot, as a share of a full slot's
 * conductors. An "in" side carries +J, out of the page (the solver's source sign,
 * and the cross-section's ⊙); each side holds an equal share of its slot.
 */
export function slotCurrents(sides: WindingSide[], slotCount: number, currents: [number, number, number]): number[] {
  const perSlot = new Array<number>(slotCount).fill(0);
  sides.forEach((side) => { if (side.slot_index >= 0 && side.slot_index < slotCount) perSlot[side.slot_index] += 1; });
  const out = new Array<number>(slotCount).fill(0);
  const phaseIndex = { A: 0, B: 1, C: 2 } as const;
  sides.forEach((side) => {
    if (side.slot_index < 0 || side.slot_index >= slotCount) return;
    out[side.slot_index] += (side.direction === 'in' ? 1 : -1) * currents[phaseIndex[side.phase]] / perSlot[side.slot_index];
  });
  return out;
}

/**
 * Each tooth's pole at its face toward the rotor, N positive, scaled so the
 * strongest is 1. Tooth k sits between slots k and k+1. Going round the bore
 * counter-clockwise, Ampere's law steps the airgap MMF (rotor to stator positive)
 * down by each slot's out-of-page current, so the flux a tooth sends into the
 * airgap — an N pole — follows the running sum of slot currents, about its mean.
 */
export function toothPoles(currentsBySlot: number[]): number[] {
  let running = 0;
  const sums = currentsBySlot.map((current) => (running += current));
  const mean = sums.reduce((total, value) => total + value, 0) / Math.max(1, sums.length);
  const poles = sums.map((value) => value - mean);
  const peak = Math.max(0, ...poles.map(Math.abs));
  return peak > 1e-9 ? poles.map((value) => value / peak) : poles.map(() => 0);
}

/** The tooth at an angle (radians, counter-clockwise from +x): tooth k spans slots k to k+1. */
export function toothIndexAt(angleRad: number, slotCount: number): number {
  const pitch = (2 * Math.PI) / Math.max(1, slotCount);
  const turn = ((angleRad % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  return Math.floor(turn / pitch) % Math.max(1, slotCount);
}
