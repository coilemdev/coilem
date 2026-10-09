import { LandingWorkflowHero } from '../components/LandingWorkflowHero';

interface PublicLandingProps {
  onStartGuided: () => void;
  onUseExample: () => void;
  /** Opens the in-app tutorials area. This used to be an external link to the
   *  docs repo, which sent people out of the product to read prose instead of
   *  into the ten solver-backed lessons the app actually ships. */
  onOpenTutorials: () => void;
  onOpenHalbach: () => void;
}

export function PublicLanding({ onStartGuided, onUseExample, onOpenTutorials, onOpenHalbach }: PublicLandingProps) {
  return (
    <main className="template-selector-overlay public-landing">
      <div className="template-selector-container">
        <LandingWorkflowHero
          onStartMotor={onStartGuided}
          onUseExampleMotor={onUseExample}
          onOpenTutorials={onOpenTutorials}
          onOpenHalbach={onOpenHalbach}
        />
      </div>
    </main>
  );
}
