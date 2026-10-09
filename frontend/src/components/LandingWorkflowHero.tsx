import { useId, useState } from 'react';

import { Landing3DPreview } from './landing-3d/Landing3DPreview';
import { LandingHalbachPreview } from './landing-3d/LandingHalbachPreview';

type LandingWorkflow = 'motor' | 'halbach';

interface LandingWorkflowHeroProps {
  onStartMotor: () => void;
  onUseExampleMotor: () => void;
  onOpenTutorials: () => void;
  onOpenHalbach: () => void;
  tutorialLabel?: string;
  githubHref?: string;
}

export function LandingWorkflowHero({
  onStartMotor,
  onUseExampleMotor,
  onOpenTutorials,
  onOpenHalbach,
  tutorialLabel = 'Tutorials',
  githubHref = 'https://github.com/coilemdev/coilem',
}: LandingWorkflowHeroProps) {
  const [workflow, setWorkflow] = useState<LandingWorkflow>('motor');
  const descriptionId = useId();
  const isMotor = workflow === 'motor';

  return (
    <section className={`selector-hero landing-workflow-hero is-${workflow}`} data-active-workflow={workflow}>
      <div className="selector-copy">
        <span className="selector-open-source-badge">
          <span aria-hidden="true" />
          Open source
        </span>
        <div className="landing-workflow-switch" role="group" aria-label="Design workflow">
          <span>Design workflow</span>
          <button
            type="button"
            className={isMotor ? 'active' : ''}
            aria-pressed={isMotor}
            aria-describedby={descriptionId}
            onClick={() => setWorkflow('motor')}
          >
            <i className="landing-workflow-motor-mark" aria-hidden="true" />
            Motor designs
          </button>
          <button
            type="button"
            className={!isMotor ? 'active' : ''}
            aria-pressed={!isMotor}
            aria-describedby={descriptionId}
            onClick={() => setWorkflow('halbach')}
          >
            <i className="landing-workflow-halbach-mark" aria-hidden="true" />
            Halbach arrays
          </button>
        </div>

        {isMotor ? (
          <>
            <h1>Electric Motor<br />Design,<br /><em>Simplified</em></h1>
            <p id={descriptionId}>Design and solve electric motors in minutes with live 3D feedback.</p>
          </>
        ) : (
          <>
            <h1>Halbach Array<br />Design,<br /><em>Simplified</em></h1>
            <p id={descriptionId}>Shape focused magnetic fields with guided cylindrical and linear array workflows.</p>
          </>
        )}

        <div className="selector-action-row">
          <button
            className="btn-sample btn-sample-primary"
            type="button"
            onClick={isMotor ? onStartMotor : onOpenHalbach}
          >
            {isMotor ? 'Start a design' : 'Design a Halbach array'}
          </button>
          {isMotor && (
            <button className="btn-sample" type="button" onClick={onUseExampleMotor}>
              Use Example Motor
            </button>
          )}
          <button className="btn-sample" type="button" onClick={onOpenTutorials}>
            {tutorialLabel}
          </button>
          <a
            className="btn-sample selector-github-link"
            href={githubHref}
            target="_blank"
            rel="noreferrer"
            aria-label="View coilEM on GitHub (opens in a new tab)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 2.6a9.6 9.6 0 0 0-3 18.7c.5.1.7-.2.7-.5v-1.9c-2.8.6-3.4-1.2-3.4-1.2-.5-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 0 1.6 1.1 1.6 1.1.9 1.6 2.4 1.1 2.9.9.1-.7.4-1.1.7-1.4-2.3-.3-4.7-1.1-4.7-4.8 0-1.1.4-2 1-2.7-.1-.3-.4-1.3.1-2.7 0 0 .8-.3 2.8 1a9.5 9.5 0 0 1 5 0c1.9-1.3 2.8-1 2.8-1 .5 1.4.2 2.4.1 2.7.6.7 1 1.6 1 2.7 0 3.7-2.4 4.5-4.7 4.8.4.3.7 1 .7 1.9v2.8c0 .4.2.6.7.5A9.6 9.6 0 0 0 12 2.6Z" />
            </svg>
            GitHub
          </a>
        </div>

        <div className="selector-proof-points" aria-label={isMotor ? 'Motor design benefits' : 'Halbach design benefits'}>
          {(isMotor
            ? ['Experimental 2D FEM', 'Runs fully offline', 'Guided motor setup', 'Source-built preview']
            : ['Cylindrical & linear arrays', '2D Magneto2D solves', 'Runs fully offline', 'Field-data exports']
          ).map((benefit) => <span key={benefit}>{benefit}</span>)}
        </div>
      </div>

      <div
        className="selector-preview-card landing-workflow-preview"
        aria-label={isMotor ? 'Surface PM inrunner preview' : 'Linear Halbach array preview'}
      >
        <div className="card-visual">
          {isMotor ? <Landing3DPreview /> : <LandingHalbachPreview />}
        </div>
      </div>
    </section>
  );
}
