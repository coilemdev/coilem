import type { FieldPhaseView, PhaseCycleSample, PhaseId } from './fieldPhases';
import { PUBLIC_PHASE_COLORS } from './motorPalette';

const WIDTH = 176;
const HEIGHT = 54;
const PAD = 4;
const PHASES: readonly PhaseId[] = ['A', 'B', 'C'];

/** Signed amps to one decimal; a current that rounds to zero has no sign. */
export function formatCurrent(currentA: number): string {
  const rounded = Math.round(currentA * 10) / 10;
  if (rounded === 0) return '0.0 A';
  return `${rounded > 0 ? '+' : '−'}${Math.abs(rounded).toFixed(1)} A`;
}

/**
 * The Phases layer's readout over the field: one electrical cycle of the A / B /
 * C currents the solver applied, a marker at the position on screen, and the
 * currents there.
 */
export function FieldPhaseReadout({ phases }: { phases: FieldPhaseView }) {
  const { cycle, angleDeg, currentsA } = phases;
  const peak = cycle.peakA > 0 ? cycle.peakA : 1;
  const x = (angle: number) => PAD + (angle / 360) * (WIDTH - 2 * PAD);
  const y = (current: number) => HEIGHT / 2 - (current / peak) * (HEIGHT / 2 - PAD);
  const samples: PhaseCycleSample[] = [...cycle.samples];
  // Close the cycle when the positions span it, so the traces meet at 360°.
  const step = samples.length > 1 ? 360 / samples.length : 360;
  const first = samples[0];
  const last = samples[samples.length - 1];
  if (first && last && first.angleDeg + 360 - last.angleDeg <= step * 1.5) {
    samples.push({ angleDeg: first.angleDeg + 360, currentsA: first.currentsA });
  }
  const shownAngle = ((angleDeg % 360) + 360) % 360;
  return (
    <div className="public-field-phase-readout" role="group" aria-label="Phase currents at this rotor position">
      <header>
        <strong>Phase currents</strong>
        <span>{shownAngle.toFixed(1)}° elec</span>
      </header>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true" className={currentsA ? undefined : 'is-idle'}>
        <line className="is-axis" x1={PAD} x2={WIDTH - PAD} y1={HEIGHT / 2} y2={HEIGHT / 2} />
        {PHASES.map((phase, index) => (
          <polyline
            key={phase}
            points={samples.map((sample) => `${x(sample.angleDeg).toFixed(2)},${y(sample.currentsA[index]).toFixed(2)}`).join(' ')}
            style={{ stroke: PUBLIC_PHASE_COLORS[phase] }}
          />
        ))}
        <line className="is-playhead" x1={x(shownAngle)} x2={x(shownAngle)} y1={PAD / 2} y2={HEIGHT - PAD / 2} />
        {currentsA && PHASES.map((phase, index) => (
          <circle key={phase} cx={x(shownAngle)} cy={y(currentsA[index])} r={2.4} style={{ fill: PUBLIC_PHASE_COLORS[phase] }} />
        ))}
      </svg>
      {currentsA ? (
        <dl>
          {PHASES.map((phase, index) => (
            <div key={phase}>
              <dt style={{ color: PUBLIC_PHASE_COLORS[phase] }}>{phase}</dt>
              <dd>{formatCurrent(currentsA[index])}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p>PM only: no stator current in this solve</p>
      )}
    </div>
  );
}
