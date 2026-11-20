import { PUBLIC_PHASE_COLORS } from './motorPalette';
import type { RecordedPhaseHistory } from './fieldPhases';
import {
  PHASE_SCOPE_WINDOW_S,
  STRIP_END,
  STRIP_LABEL,
  TRACE_AMPLITUDE,
  electricalFrequencyHz,
  formatHz,
  formatRevPerSecond,
  phaseChargeShift,
  phaseStrips,
  waveformTrace,
  type PhaseCurrentSampler,
  type PhaseDrive,
  type Rect,
} from './phaseDrive';

const PHASE_COLORS = PUBLIC_PHASE_COLORS;

/** Where a phase's wire goes: it turns at the terminal's x, and from the terminal dot runs level to the motor. */
export interface PhaseLead {
  terminal: [number, number];
  motor: [number, number];
}

/**
 * The A / B / C waveform strips and the wires from them into the motor, shared by
 * the 2D cross-section, the 3D view and the Field solution. Each wire leaves its
 * strip level, turns once through a right angle at its terminal, and runs level
 * to where it enters. `sample` replaces the drive settings' currents (the Field
 * solution passes its solve's), and `title` the caption above the strips.
 */
export function drawPhaseDriveWired(
  context: CanvasRenderingContext2D,
  panel: Rect,
  drive: PhaseDrive,
  rotorElecDeg: number,
  currents: [number, number, number] | null,
  leads: PhaseLead[],
  previewRpm: number,
  { sample, title, history }: { sample?: PhaseCurrentSampler; title?: string; history?: RecordedPhaseHistory } = {},
): void {
  const phases = ['A', 'B', 'C'] as const;
  // A scope with a fixed sweep: the strips hold the cycles the drive runs in that
  // time at the preview speed, so twice the speed shows twice as many.
  const frequencyHz = electricalFrequencyHz(previewRpm, drive.poleCount);
  const windowElecDeg = 360 * frequencyHz * PHASE_SCOPE_WINDOW_S;
  const strips = phaseStrips(panel);
  context.save();
  context.fillStyle = 'rgba(148, 163, 184, 0.78)';
  context.font = '700 10px ui-monospace, monospace';
  context.textAlign = 'left';
  context.textBaseline = 'bottom';
  context.fillText(title ?? `${drive.mode === 'ideal_six_step_120' ? 'SIX-STEP DRIVE' : 'SINE DRIVE'} · ${formatHz(frequencyHz)}`, panel.x, panel.y - 6);
  // What sets the frequency, and the sweep the strips show.
  context.fillStyle = 'rgba(148, 163, 184, 0.6)';
  context.font = '600 9px ui-monospace, monospace';
  context.textBaseline = 'top';
  context.fillText(`${Math.max(1, Math.floor(drive.poleCount / 2))} pole pairs × ${formatRevPerSecond(previewRpm)} rev/s · last ${PHASE_SCOPE_WINDOW_S} s`, panel.x, panel.y + panel.height + 6);
  if (history?.gaps.length) {
    context.fillStyle = 'rgba(203, 213, 225, 0.9)';
    context.fillText('Outside solved sweep', panel.x, panel.y + panel.height + 18);
  }

  strips.forEach((strip, index) => {
    const colour = PHASE_COLORS[phases[index]];
    const level = Math.abs(currents?.[index] ?? 0);
    const mid = strip.y + strip.height / 2;
    const right = strip.x + strip.width;
    const nowX = right - STRIP_END;
    const left = strip.x + STRIP_LABEL;

    context.beginPath();
    if (typeof context.roundRect === 'function') context.roundRect(strip.x, strip.y, strip.width, strip.height, 8);
    else context.rect(strip.x, strip.y, strip.width, strip.height);
    context.fillStyle = 'rgba(12, 15, 21, 0.78)';
    context.fill();
    context.strokeStyle = 'rgba(148, 163, 184, 0.16)';
    context.lineWidth = 1;
    context.stroke();

    context.fillStyle = 'rgba(148, 163, 184, 0.09)';
    for (const [from, to] of history?.gaps ?? []) {
      context.fillRect(left + from * (nowX - left), strip.y + 2, (to - from) * (nowX - left), strip.height - 4);
    }
    context.setLineDash([3, 4]);
    context.beginPath();
    context.moveTo(strip.x + STRIP_LABEL, mid);
    context.lineTo(right - STRIP_END, mid);
    context.strokeStyle = 'rgba(148, 163, 184, 0.24)';
    context.stroke();
    context.setLineDash([]);

    context.fillStyle = colour;
    context.font = '800 11px ui-monospace, monospace';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(phases[index], strip.x + STRIP_LABEL / 2, mid + 0.5);
    // The wave's frequency, in its own plot.
    context.fillStyle = 'rgba(148, 163, 184, 0.72)';
    context.font = '700 9px ui-monospace, monospace';
    context.textAlign = 'right';
    context.textBaseline = 'top';
    context.fillText(formatHz(frequencyHz), right - STRIP_END, strip.y + 4);

    const swing = strip.height * TRACE_AMPLITUDE;
    const traces = history
      ? history.segments.map(segment => segment.map(({ fraction, currents }) =>
        [left + fraction * (nowX - left), mid - currents[index] * swing] as const))
      : [waveformTrace(drive, index, rotorElecDeg, strip, windowElecDeg, undefined, sample)];
    context.strokeStyle = colour;
    context.lineWidth = 1.8;
    context.lineJoin = 'round';
    context.fillStyle = colour;
    for (const trace of traces) {
      context.beginPath();
      if (trace.length === 1) {
        const [x, y] = trace[0];
        if (y === null) continue;
        context.arc(x, y, 1.8, 0, Math.PI * 2);
        context.fill();
      } else {
        let drawing = false;
        for (const [x, y] of trace) {
          if (y !== null) {
            if (drawing) context.lineTo(x, y);
            else context.moveTo(x, y);
          }
          drawing = y !== null;
        }
        context.stroke();
      }
    }

    // The wire is fixed: it leaves from a terminal on the strip's centre line. The
    // wave's newest point rides a short rail beside it and a stem ties the two, so
    // the wave still reads as what feeds the wire.
    const { motor, terminal } = leads[index];
    context.strokeStyle = 'rgba(148, 163, 184, 0.3)';
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(nowX, mid - swing);
    context.lineTo(nowX, mid + swing);
    context.stroke();
    context.strokeStyle = colour;
    context.lineWidth = 2;
    context.lineCap = 'round';
    if (currents) {
      const nowY = mid - currents[index] * swing;
      context.beginPath();
      context.arc(nowX, nowY, 3.2, 0, Math.PI * 2);
      context.fill();
      context.beginPath();
      context.moveTo(nowX, nowY);
      context.lineTo(nowX, mid);
      context.stroke();
    }
    // Level out of the strip, one right-angle turn down or up to the terminal, then level into the motor.
    context.lineJoin = 'miter';
    const wire = () => {
      context.beginPath();
      context.moveTo(nowX, mid);
      context.lineTo(terminal[0], mid);
      context.lineTo(terminal[0], terminal[1]);
      context.lineTo(motor[0], motor[1]);
      context.stroke();
    };
    // The conductor itself, always there.
    context.globalAlpha = 0.34;
    context.lineWidth = 1.6;
    wire();
    // The current in it: marks that run into the motor while the phase current is
    // positive and back out while it is negative, brighter and heavier the more
    // current there is. Their position is the charge moved so far this cycle.
    context.globalAlpha = 0.25 + 0.75 * level;
    context.lineWidth = 1.6 + 2.2 * level;
    context.setLineDash([7, 11]);
    context.lineDashOffset = -phaseChargeShift(drive, index, rotorElecDeg, undefined, sample) * 26;
    wire();
    context.setLineDash([]);
    context.lineDashOffset = 0;
    context.globalAlpha = 1;
    context.fillStyle = colour;
    context.beginPath();
    context.arc(nowX, mid, 2.6, 0, Math.PI * 2);
    context.fill();
    context.beginPath();
    context.arc(terminal[0], terminal[1], 2.8, 0, Math.PI * 2);
    context.fill();
    context.globalAlpha = 1;
  });
  context.restore();

}

/**
 * A coil side's current mark: ⊙ out of the page, ⊗ into it, white on a dark disc
 * ringed in the phase colour. Shared by the Geometry view and the Field
 * solution's Phases, drawn at screen size so it reads at any zoom.
 */
export function drawCurrentMarker(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  outOfPage: boolean,
  ringColor: string,
): void {
  context.save();
  context.shadowColor = 'rgba(3, 5, 9, 0.6)';
  context.shadowBlur = radius * 0.9;
  context.shadowOffsetY = radius * 0.16;
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.fillStyle = 'rgba(8, 10, 14, 0.82)';
  context.fill();
  context.shadowColor = 'transparent';
  context.shadowBlur = 0;
  context.shadowOffsetY = 0;
  context.strokeStyle = ringColor;
  context.lineWidth = Math.max(1.1, radius * 0.18);
  context.stroke();
  if (outOfPage) {
    context.beginPath();
    context.arc(x, y, Math.max(1.3, radius * 0.34), 0, Math.PI * 2);
    context.fillStyle = '#f8fafc';
    context.fill();
  } else {
    const reach = radius * 0.52;
    context.strokeStyle = '#f8fafc';
    context.lineWidth = Math.max(1.1, radius * 0.22);
    context.beginPath();
    context.moveTo(x - reach, y - reach);
    context.lineTo(x + reach, y + reach);
    context.moveTo(x + reach, y - reach);
    context.lineTo(x - reach, y + reach);
    context.stroke();
  }
  context.restore();
}
