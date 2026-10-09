import React from 'react';
import { clampNumber, formatTesla } from './magneticCircuit';

interface AirgapFluxGaugeProps {
  peakT: number | null;
  meanT: number | null;
  airgapMm: number;
  baselinePeakT?: number | null;
  // Highest peak airgap B seen across the lesson, used to scale the gauge.
  scaleMaxT?: number;
}

const GAUGE_FLOOR_T = 0.2;

export const AirgapFluxGauge: React.FC<AirgapFluxGaugeProps> = ({
  peakT,
  meanT,
  airgapMm,
  baselinePeakT,
  scaleMaxT,
}) => {
  const hasValue = peakT !== null && Number.isFinite(peakT);
  const scaleMax = Math.max(scaleMaxT ?? 0, peakT ?? 0, baselinePeakT ?? 0, 1.2);
  const fillFraction = hasValue
    ? clampNumber((peakT! - GAUGE_FLOOR_T) / (scaleMax - GAUGE_FLOOR_T), 0, 1)
    : 0;
  const baselineFraction = baselinePeakT !== null && baselinePeakT !== undefined && Number.isFinite(baselinePeakT)
    ? clampNumber((baselinePeakT - GAUGE_FLOOR_T) / (scaleMax - GAUGE_FLOOR_T), 0, 1)
    : null;

  const delta = hasValue && baselinePeakT !== null && baselinePeakT !== undefined && Number.isFinite(baselinePeakT)
    ? peakT! - baselinePeakT
    : null;
  const ratio = delta !== null && baselinePeakT && baselinePeakT > 1e-6
    ? peakT! / baselinePeakT
    : null;

  return (
    <div className="tutorial-airgap-gauge" aria-label="Airgap flux gauge">
      <div className="tutorial-airgap-gauge-head">
        <span className="tutorial-airgap-gauge-label">Peak airgap flux density</span>
        <strong className="tutorial-airgap-gauge-value">{formatTesla(peakT)}</strong>
      </div>
      <div
        className="tutorial-airgap-gauge-track"
        role="meter"
        aria-valuemin={GAUGE_FLOOR_T}
        aria-valuemax={Number(scaleMax.toFixed(2))}
        aria-valuenow={hasValue ? Number(peakT!.toFixed(3)) : GAUGE_FLOOR_T}
        aria-label="Peak radial airgap B"
      >
        <span className="tutorial-airgap-gauge-fill" style={{ width: `${fillFraction * 100}%` }} />
        {baselineFraction !== null ? (
          <span
            className="tutorial-airgap-gauge-baseline"
            style={{ left: `${baselineFraction * 100}%` }}
            title={`Baseline ${formatTesla(baselinePeakT)}`}
          />
        ) : null}
      </div>
      <dl className="tutorial-airgap-gauge-stats">
        <div>
          <dt>Airgap</dt>
          <dd>{airgapMm.toFixed(1)} mm</dd>
        </div>
        <div>
          <dt>Mean |B|</dt>
          <dd>{formatTesla(meanT)}</dd>
        </div>
        {ratio !== null ? (
          <div>
            <dt>vs. baseline</dt>
            <dd className={delta && delta >= 0 ? 'is-up' : 'is-down'}>
              {ratio.toFixed(2)}× ({delta && delta >= 0 ? '+' : ''}{formatTesla(delta)})
            </dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
};
