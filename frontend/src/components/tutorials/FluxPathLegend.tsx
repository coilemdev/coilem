import React from 'react';

interface FluxPathSegment {
  id: string;
  label: string;
  detail: string;
  dominant?: boolean;
}

const FLUX_PATH_SEGMENTS: FluxPathSegment[] = [
  { id: 'magnet', label: 'Magnet (MMF source)', detail: 'Flux leaves the N face — this is the source driving the loop.' },
  { id: 'airgap-out', label: 'Airgap (out)', detail: 'Crosses the gap into a stator tooth.', dominant: true },
  { id: 'iron', label: 'Tooth + back iron', detail: 'Up the tooth, around the back iron, down the opposite tooth. Cheap reluctance — until it saturates.' },
  { id: 'airgap-return', label: 'Airgap (return)', detail: 'Crosses the gap again into the magnet S face, closing the loop.', dominant: true },
];

export const FluxPathLegend: React.FC = () => (
  <div className="tutorial-flux-path" aria-label="Magnetic circuit flux path">
    <p className="tutorial-flux-path-intro">
      One closed flux loop — a series chain of reluctances. The two airgaps dominate; iron is
      nearly free until it saturates.
    </p>
    <ol className="tutorial-flux-path-list">
      {FLUX_PATH_SEGMENTS.map((segment, index) => (
        <li
          key={segment.id}
          className={`tutorial-flux-path-step${segment.dominant ? ' is-dominant' : ''}`}
        >
          <span className="tutorial-flux-path-index" aria-hidden="true">{index + 1}</span>
          <span className="tutorial-flux-path-body">
            <strong>
              {segment.label}
              {segment.dominant ? <em className="tutorial-flux-path-tag">dominant</em> : null}
            </strong>
            <span>{segment.detail}</span>
          </span>
        </li>
      ))}
    </ol>
  </div>
);
