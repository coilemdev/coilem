import { useState } from 'react';
import { currentStepSegments } from './bldcChartPaths';

interface BldcTorqueCurrentChartProps {
  angles: number[];
  torqueNm: number[];
  phaseA: number[];
  phaseB: number[];
  phaseC: number[];
  commutationAdvanceDeg: number;
  cycleComplete: boolean;
}

const PHASE_COLORS = ['#f87171', '#4ade80', '#60a5fa'] as const;

function wrap360(value: number): number {
  const wrapped = value % 360;
  return wrapped < 0 ? wrapped + 360 : wrapped;
}

function sectorAt(angle: number, advance: number): number {
  return Math.floor(wrap360(angle + advance) / 60) % 6;
}

function sectorSegments(advance: number): Array<{ start: number; end: number; sector: number }> {
  const boundaries = [0, 360];
  for (let sector = 0; sector < 6; sector += 1) {
    const boundary = wrap360(sector * 60 - advance);
    if (boundary > 1e-9 && boundary < 360 - 1e-9) boundaries.push(boundary);
  }
  boundaries.sort((left, right) => left - right);
  return boundaries.slice(0, -1).map((start, index) => {
    const end = boundaries[index + 1];
    return { start, end, sector: sectorAt((start + end) / 2, advance) };
  });
}

function conductingPhases(a: number, b: number, c: number): string {
  const entries = [['A', a], ['B', b], ['C', c]] as const;
  return entries
    .filter(([, current]) => Math.abs(current) > 1e-9)
    .map(([phase, current]) => `${phase}${current > 0 ? '+' : '−'}`)
    .join(' / ');
}

export function BldcTorqueCurrentChart({
  angles,
  torqueNm,
  phaseA,
  phaseB,
  phaseC,
  commutationAdvanceDeg,
  cycleComplete,
}: BldcTorqueCurrentChartProps) {
  const [showTorque, setShowTorque] = useState(true);
  const [showPhaseCurrents, setShowPhaseCurrents] = useState(true);
  const aligned = angles.length >= 2
    && [torqueNm, phaseA, phaseB, phaseC].every((values) => values.length === angles.length);
  if (!aligned) return null;

  const width = 760;
  const height = 290;
  const margin = { top: 32, right: 62, bottom: 38, left: 58 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const minTorque = Math.min(...torqueNm);
  const maxTorque = Math.max(...torqueNm);
  const torquePad = Math.max((maxTorque - minTorque) * 0.12, Math.abs(maxTorque) * 0.04, 0.01);
  const torqueLow = minTorque - torquePad;
  const torqueHigh = maxTorque + torquePad;
  const maxCurrent = Math.max(1, ...phaseA.map(Math.abs), ...phaseB.map(Math.abs), ...phaseC.map(Math.abs));
  const x = (angle: number) => margin.left + wrap360(angle) / 360 * plotWidth;
  const torqueY = (value: number) => margin.top + (torqueHigh - value) / Math.max(torqueHigh - torqueLow, 1e-9) * plotHeight;
  const currentY = (value: number) => margin.top + (maxCurrent - value) / (2 * maxCurrent) * plotHeight;
  const torquePath = torqueNm.map((value, index) => `${index ? 'L' : 'M'} ${x(angles[index]).toFixed(2)} ${torqueY(value).toFixed(2)}`).join(' ');
  const stepSegments = (values: number[]) => currentStepSegments(
    angles, values, x, currentY, cycleComplete ? width - margin.right : undefined,
  );
  const segments = sectorSegments(commutationAdvanceDeg);
  const torqueTicks = [0, 0.5, 1];
  const currentTicks = [-maxCurrent, 0, maxCurrent];
  const visibleSeriesLabel = showTorque && showPhaseCurrents
    ? 'Torque and commanded phase currents'
    : showTorque
      ? 'Torque'
      : 'Commanded phase currents';
  const chartDescription = showTorque && showPhaseCurrents
    ? 'Six shaded sixty-degree commutation sectors. Torque uses the left axis in newton metres. Phase currents use the right axis in amperes and change as steps.'
    : showTorque
      ? 'Six shaded sixty-degree commutation sectors with torque on the left axis in newton metres.'
      : 'Six shaded sixty-degree commutation sectors with commanded phase currents on the right axis in amperes. Solid lines show two conducting phases and dashed lines show the open phase.';

  return (
    <section className="chart-shell public-bldc-chart" aria-label="Ideal six-step torque and phase-current waveforms">
      <div className="chart-heading">
        <span>{visibleSeriesLabel}</span>
        <span>{angles.length} positions · {cycleComplete ? 'complete cycle' : 'preview only'}</span>
      </div>
      <div className="public-bldc-series-controls" role="group" aria-label="Visible waveform groups">
        <button
          type="button"
          aria-pressed={showTorque}
          disabled={showTorque && !showPhaseCurrents}
          title={showTorque && !showPhaseCurrents ? 'At least one waveform group must remain visible.' : `${showTorque ? 'Hide' : 'Show'} torque`}
          onClick={() => setShowTorque((visible) => !visible)}
        >
          <i className="torque" />
          Torque
        </button>
        <button
          type="button"
          aria-pressed={showPhaseCurrents}
          disabled={showPhaseCurrents && !showTorque}
          title={showPhaseCurrents && !showTorque ? 'At least one waveform group must remain visible.' : `${showPhaseCurrents ? 'Hide' : 'Show'} commanded phase currents`}
          onClick={() => setShowPhaseCurrents((visible) => !visible)}
        >
          <span className="public-bldc-phase-swatches" aria-hidden="true">
            <i style={{ background: PHASE_COLORS[0] }} />
            <i style={{ background: PHASE_COLORS[1] }} />
            <i style={{ background: PHASE_COLORS[2] }} />
          </span>
          Ia / Ib / Ic
        </button>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="bldc-chart-title bldc-chart-description">
        <title id="bldc-chart-title">Ideal six-step {visibleSeriesLabel.toLowerCase()}</title>
        <desc id="bldc-chart-description">{chartDescription}</desc>
        {segments.map((segment, index) => (
          <g key={`${segment.start}-${segment.sector}`}>
            <rect
              x={x(segment.start)}
              y={margin.top}
              width={Math.max(0, x(segment.end === 360 ? 359.999999 : segment.end) - x(segment.start))}
              height={plotHeight}
              className={`public-bldc-sector sector-${segment.sector % 2}`}
            />
            <text x={(x(segment.start) + x(segment.end === 360 ? 359.999999 : segment.end)) / 2} y={margin.top + 12} textAnchor="middle" className="public-bldc-sector-label">S{segment.sector + 1}{index === 0 && segment.start > 0 ? ' (wrap)' : ''}</text>
          </g>
        ))}
        {showTorque && torqueTicks.map((tick) => {
          const y = margin.top + tick * plotHeight;
          const value = torqueHigh - tick * (torqueHigh - torqueLow);
          return <g key={tick}><line x1={margin.left} x2={width - margin.right} y1={y} y2={y} className="chart-grid" /><text x={margin.left - 9} y={y + 4} textAnchor="end" className="chart-label">{value.toFixed(2)}</text></g>;
        })}
        {showPhaseCurrents && currentTicks.map((value) => <g key={value}>{!showTorque && <line x1={margin.left} x2={width - margin.right} y1={currentY(value)} y2={currentY(value)} className="chart-grid" />}<text x={width - margin.right + 9} y={currentY(value) + 4} className="chart-label">{value.toFixed(0)}</text></g>)}
        {showTorque && <path d={torquePath} className="public-bldc-torque-line" />}
        {showPhaseCurrents && [phaseA, phaseB, phaseC].map((values, index) => stepSegments(values).map((segment, segmentIndex) => <path key={`${PHASE_COLORS[index]}-${segmentIndex}`} d={segment.path} className={segment.conducting ? undefined : 'public-bldc-open-phase'} fill="none" stroke={PHASE_COLORS[index]} strokeWidth="1.8" strokeLinejoin="miter" />))}
        {showTorque && <text x={margin.left} y="13" className="chart-label chart-unit-label">Torque (N·m)</text>}
        {showPhaseCurrents && <text x={width - margin.right} y="13" textAnchor="end" className="chart-label chart-unit-label">Current (A plateau)</text>}
        <text x={margin.left} y={height - 12} className="chart-label">0°</text>
        <text x={width - margin.right} y={height - 12} textAnchor="end" className="chart-label">360° electrical</text>
      </svg>
      <details className="public-waveform-data">
        <summary>Accessible waveform data</summary>
        <div tabIndex={0} role="region" aria-label="Scrollable six-step waveform data">
          <table>
            <thead><tr><th>Angle</th><th>Sector</th><th>Conducting phases</th><th>Ia</th><th>Ib</th><th>Ic</th><th>Torque</th></tr></thead>
            <tbody>{angles.map((angle, index) => <tr key={`${angle}-${index}`}><td>{angle.toFixed(3)}°</td><td>S{sectorAt(angle, commutationAdvanceDeg) + 1}</td><td>{conductingPhases(phaseA[index], phaseB[index], phaseC[index])}</td><td>{phaseA[index].toFixed(6)} A</td><td>{phaseB[index].toFixed(6)} A</td><td>{phaseC[index].toFixed(6)} A</td><td>{torqueNm[index].toFixed(6)} N·m</td></tr>)}</tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
