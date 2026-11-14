import { PUBLIC_PHASE_COLORS } from './motorPalette';
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
 * the 2D cross-section and the 3D view. Each wire leaves its strip level, turns
 * once through a right angle at its terminal, and runs level to where it enters.
 */
export function drawPhaseDriveWired(
  context: CanvasRenderingContext2D,
  panel: Rect,
  drive: PhaseDrive,
  rotorElecDeg: number,
  currents: [number, number, number],
  leads: PhaseLead[],
  previewRpm: number,
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
  context.fillText(`${drive.mode === 'ideal_six_step_120' ? 'SIX-STEP DRIVE' : 'SINE DRIVE'} · ${formatHz(frequencyHz)}`, panel.x, panel.y - 6);
  // What sets the frequency, and the sweep the strips show.
  context.fillStyle = 'rgba(148, 163, 184, 0.6)';
  context.font = '600 9px ui-monospace, monospace';
  context.textBaseline = 'top';
  context.fillText(`${Math.max(1, Math.floor(drive.poleCount / 2))} pole pairs × ${formatRevPerSecond(previewRpm)} rev/s · last ${PHASE_SCOPE_WINDOW_S} s`, panel.x, panel.y + panel.height + 6);

  strips.forEach((strip, index) => {
    const colour = PHASE_COLORS[phases[index]];
    const level = Math.abs(currents[index]);
    const mid = strip.y + strip.height / 2;
    const right = strip.x + strip.width;

    context.beginPath();
    if (typeof context.roundRect === 'function') context.roundRect(strip.x, strip.y, strip.width, strip.height, 8);
    else context.rect(strip.x, strip.y, strip.width, strip.height);
    context.fillStyle = 'rgba(12, 15, 21, 0.78)';
    context.fill();
    context.strokeStyle = 'rgba(148, 163, 184, 0.16)';
    context.lineWidth = 1;
    context.stroke();

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

    const trace = waveformTrace(drive, index, rotorElecDeg, strip, windowElecDeg);
    context.beginPath();
    context.moveTo(trace[0][0], trace[0][1]);
    for (const [x, y] of trace.slice(1)) context.lineTo(x, y);
    context.strokeStyle = colour;
    context.lineWidth = 1.8;
    context.lineJoin = 'round';
    context.stroke();
    const [nowX, nowY] = trace[trace.length - 1];
    context.beginPath();
    context.arc(nowX, nowY, 3.2, 0, Math.PI * 2);
    context.fillStyle = colour;
    context.fill();

    // The wire is fixed: it leaves from a terminal on the strip's centre line. The
    // wave's newest point rides a short rail beside it and a stem ties the two, so
    // the wave still reads as what feeds the wire.
    const { motor, terminal } = leads[index];
    const swing = strip.height * TRACE_AMPLITUDE;
    context.strokeStyle = 'rgba(148, 163, 184, 0.3)';
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(nowX, mid - swing);
    context.lineTo(nowX, mid + swing);
    context.stroke();
    context.strokeStyle = colour;
    context.lineWidth = 2;
    context.lineCap = 'round';
    context.beginPath();
    context.moveTo(nowX, nowY);
    context.lineTo(nowX, mid);
    context.stroke();
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
    context.lineDashOffset = -phaseChargeShift(drive, index, rotorElecDeg) * 26;
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
