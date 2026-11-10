import { LandingWorkflowHero } from '../components/LandingWorkflowHero';
import type { PublicExampleId } from './exampleDesigns';
import { LandingMotorTypes } from './LandingMotorTypes';

interface PublicLandingProps {
  onStartGuided: () => void;
  onUseExample: () => void;
  /** Opens the in-app tutorials area. This used to be an external link to the
   *  docs repo, which sent people out of the product to read prose instead of
   *  into the ten solver-backed lessons the app actually ships. */
  onOpenTutorials: () => void;
  onOpenHalbach: () => void;
  /** Opens one of the shipped example motors in the workspace. */
  onLoadExample: (exampleId: PublicExampleId) => void;
}

export function PublicLanding({ onStartGuided, onUseExample, onOpenTutorials, onOpenHalbach, onLoadExample }: PublicLandingProps) {
  return (
    <main className="template-selector-overlay public-landing">
      <div className="template-selector-container">
        <LandingWorkflowHero
          onStartMotor={onStartGuided}
          onUseExampleMotor={onUseExample}
          onOpenTutorials={onOpenTutorials}
          onOpenHalbach={onOpenHalbach}
        />
        <LandingMotorTypes onLoadExample={onLoadExample} />
      </div>
    </main>
  );
}
