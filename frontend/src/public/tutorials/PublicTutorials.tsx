import { Suspense, lazy, useCallback, useState } from 'react';
import { LessonSolveClientContext } from '../../components/tutorials/lessonSolveClient';
import { LearningCatalog } from '../../components/tutorials/LessonCatalog';
import type { LearningLessonId } from '../../components/tutorials/LessonCatalog';
import type {
  LearningLessonHeaderProgress,
  LearningLessonStage,
} from '../../components/tutorials/lessonStage';
import { useLearningProgress } from '../../components/tutorials/useLearningProgress';
import { publicLessonSolveClient } from './publicLessonSolveClient';
import {
  LESSON_ID_BY_CATALOG_ID,
  type PublicLessonId,
  type PublicTutorialsView,
} from './lessonRoutes';

/**
 * The public tutorials area: the shared catalog plus the ten shared lessons.
 *
 * Every lesson is behind its own React.lazy boundary. Measured, an eager barrel
 * import costs the landing page +548 KB raw / +125 KB gzip; ten lazy boundaries
 * cost +5 KB raw / +1.6 KB gzip. Never turn one of these into a static import,
 * and never import components/tutorials/index.ts here — that barrel pulls all
 * ten in at once and silently undoes the split.
 */

const LESSON_COMPONENTS: Record<
  PublicLessonId,
  React.LazyExoticComponent<React.ComponentType<LessonProps>>
> = {
  'lesson-1': lazy(() =>
    import('../../components/tutorials/LearningLessonOneFollowFlux').then((m) => ({
      default: m.LearningLessonOneFollowFlux as React.ComponentType<LessonProps>,
    }))),
  'lesson-2': lazy(() =>
    import('../../components/tutorials/LessonTwoAirgapTax').then((m) => ({
      default: m.LearningLessonTwoAirgapTax as React.ComponentType<LessonProps>,
    }))),
  'lesson-3': lazy(() =>
    import('../../components/tutorials/LessonThreeCurrentField').then((m) => ({
      default: m.LearningLessonThreeCurrentField as React.ComponentType<LessonProps>,
    }))),
  'lesson-4': lazy(() =>
    import('../../components/tutorials/LessonFourIronSaturation').then((m) => ({
      default: m.LearningLessonFourIronSaturation as React.ComponentType<LessonProps>,
    }))),
  'lesson-5': lazy(() =>
    import('../../components/tutorials/LessonFiveFieldForce').then((m) => ({
      default: m.LearningLessonFiveFieldForce as React.ComponentType<LessonProps>,
    }))),
  'chapter-1-capstone': lazy(() =>
    import('../../components/tutorials/ChapterOneLinearMotorCapstone').then((m) => ({
      default: m.ChapterOneLinearMotorCapstone as React.ComponentType<LessonProps>,
    }))),
  'lesson-6': lazy(() =>
    import('../../components/tutorials/LessonSixRotorChase').then((m) => ({
      default: m.LearningLessonSixRotorChase as React.ComponentType<LessonProps>,
    }))),
  'lesson-7': lazy(() =>
    import('../../components/tutorials/LessonSevenRotatingField').then((m) => ({
      default: m.LearningLessonSevenRotatingField as React.ComponentType<LessonProps>,
    }))),
  'lesson-8': lazy(() =>
    import('../../components/tutorials/LessonEightThreePhaseMotor').then((m) => ({
      default: m.LearningLessonEightThreePhaseMotor as React.ComponentType<LessonProps>,
    }))),
  'lesson-9': lazy(() =>
    import('../../components/tutorials/LessonTwoMagneticCircuit').then((m) => ({
      default: m.LearningMotorMagneticCircuit as React.ComponentType<LessonProps>,
    }))),
  'lesson-10': lazy(() =>
    import('../../components/tutorials/LessonThreeBackEmf').then((m) => ({
      default: m.LearningLessonThreeBackEmf as React.ComponentType<LessonProps>,
    }))),
};

interface LessonProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

interface PublicTutorialsProps {
  view: PublicTutorialsView;
  stage: LearningLessonStage;
  onViewChange: (view: PublicTutorialsView) => void;
  onStageChange: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
  /** Leave the tutorials area entirely and return to the public landing page. */
  onExit: () => void;
}

const LESSON_META: Record<PublicLessonId, {
  catalogId: LearningLessonId;
  next: PublicLessonId | 'catalog';
  nextLabel: string;
}> = {
  'lesson-1': { catalogId: 'follow-the-flux', next: 'lesson-2', nextLabel: 'Close the Loop' },
  'lesson-2': { catalogId: 'airgap-tax', next: 'lesson-3', nextLabel: 'Make a Field with Current' },
  'lesson-3': { catalogId: 'current-field', next: 'lesson-4', nextLabel: 'When Iron Saturates' },
  'lesson-4': { catalogId: 'iron-saturation', next: 'lesson-5', nextLabel: 'Turn Field into Force' },
  'lesson-5': { catalogId: 'field-force', next: 'chapter-1-capstone', nextLabel: 'Make It Move' },
  'chapter-1-capstone': { catalogId: 'review-fields', next: 'lesson-6', nextLabel: 'Give the Rotor Something to Chase' },
  'lesson-6': { catalogId: 'rotor-chase', next: 'lesson-7', nextLabel: 'Make the Field Rotate' },
  'lesson-7': { catalogId: 'rotating-field', next: 'lesson-8', nextLabel: 'Three Wires, One Rotating Field' },
  'lesson-8': { catalogId: 'three-phase-motor', next: 'lesson-9', nextLabel: 'Build the 2p/6s Motor' },
  'lesson-9': { catalogId: 'motor-magnetic-circuit', next: 'lesson-10', nextLabel: 'BEMF & Voltage Headroom' },
  'lesson-10': { catalogId: 'back-emf-voltage-headroom', next: 'catalog', nextLabel: 'All lessons' },
};

export function PublicTutorials({
  view,
  stage,
  onViewChange,
  onStageChange,
  onHeaderProgressChange,
  onExit,
}: PublicTutorialsProps) {
  const [restartToken, setRestartToken] = useState(0);
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const handleSelectLesson = useCallback(
    (lessonId: LearningLessonId) => {
      const routeId = LESSON_ID_BY_CATALOG_ID[lessonId];
      if (routeId) onViewChange(routeId);
    },
    [onViewChange],
  );

  const backToCatalog = useCallback(() => onViewChange('catalog'), [onViewChange]);
  const lessonMeta = view === 'catalog' ? null : LESSON_META[view];
  const replayingCompletedLesson = Boolean(
    lessonMeta && isLessonComplete(lessonMeta.catalogId),
  );

  const restartLesson = useCallback(() => {
    if (!lessonMeta) return;
    setLessonComplete(lessonMeta.catalogId, false);
    onStageChange('design');
    setRestartToken((value) => value + 1);
  }, [lessonMeta, onStageChange, setLessonComplete]);

  const continueAfterCompletedLesson = useCallback(() => {
    if (!lessonMeta) return;
    onStageChange('design');
    onViewChange(lessonMeta.next);
  }, [lessonMeta, onStageChange, onViewChange]);

  return (
    <LessonSolveClientContext.Provider value={publicLessonSolveClient}>
      <div className="public-tutorials-scroll">
        {view === 'catalog' ? (
          <LearningCatalog
            onSelectLesson={handleSelectLesson}
            onBackHome={onExit}
            backHomeLabel="Back to home"
          />
        ) : (
          <Suspense fallback={<LessonLoading />}>
            {(() => {
              const Lesson = LESSON_COMPONENTS[view];
              return (
                <div className={`tutorial-lesson-page${replayingCompletedLesson ? ' tutorial-replay-mode' : ''}`}>
                  {replayingCompletedLesson ? (
                    <section className="tutorial-replay-banner" role="status">
                      <div>
                        <strong>Replaying completed lesson</strong>
                        <span>Your completed checkpoints stay marked until you choose to restart.</span>
                      </div>
                    </section>
                  ) : null}
                  <Lesson
                    key={`${view}-${restartToken}`}
                    onBackToCatalog={backToCatalog}
                    onBackHome={onExit}
                    stage={stage}
                    onStageChange={onStageChange}
                    onHeaderProgressChange={onHeaderProgressChange}
                  />
                  {replayingCompletedLesson ? (
                    <nav className="tutorial-replay-dock" aria-label="Completed lesson controls">
                      <div className="tutorial-replay-dock-copy">
                        <span>Lesson complete</span>
                        <strong>Keep exploring, restart, or continue when you’re ready.</strong>
                      </div>
                      <div>
                        <button type="button" className="learning-ghost-button" onClick={restartLesson}>
                          Restart lesson
                        </button>
                        <button type="button" className="learning-primary-button" onClick={continueAfterCompletedLesson}>
                          Continue: {lessonMeta?.nextLabel}
                        </button>
                      </div>
                    </nav>
                  ) : null}
                </div>
              );
            })()}
          </Suspense>
        )}
      </div>
    </LessonSolveClientContext.Provider>
  );
}

function LessonLoading() {
  return (
    <main className="learning-shell learning-catalog-shell">
      <p className="learning-kicker">Loading lesson…</p>
    </main>
  );
}
