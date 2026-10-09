import React from 'react';
import { LessonGlyph } from './LessonGlyph';
import { useLearningProgress } from './useLearningProgress';
import './learning.css';

export type LearningLessonId =
  | 'follow-the-flux'
  | 'airgap-tax'
  | 'current-field'
  | 'iron-saturation'
  | 'field-force'
  | 'review-fields'
  | 'rotor-chase'
  | 'rotating-field'
  | 'three-phase-motor'
  | 'back-emf-voltage-headroom'
  | 'torque-production'
  | 'motor-magnetic-circuit';
export type { LearningLessonStage } from './lessonStage';

interface LearningCatalogProps {
  onSelectLesson: (lessonId: LearningLessonId) => void;
  onBackHome: () => void;
  /** Launch the guided first-solve tour on the real app. Omitted in the
   *  public build, which has no coach-marked workspace to launch. */
  onStartGuidedTour?: () => void;
  /** "Back to design start" reads as private-workspace language; the public app
   *  returns to its landing page instead. */
  backHomeLabel?: string;
}

const TIER_ONE_LESSONS = [
  {
    id: 'follow-the-flux',
    number: 1,
    title: 'Follow the Flux',
    summary: 'Solve one magnet in open air, then move different steel shapes nearby and watch the field redistribute.',
    status: 'available',
    estimate: '8 min',
  },
  {
    id: 'airgap-tax',
    number: 2,
    title: 'Close the Loop: The Airgap Tax',
    summary: 'Close one magnet with steel, change two airgaps, and watch the solved flux pay the price.',
    status: 'available',
    estimate: '7 min',
  },
  {
    id: 'current-field',
    number: 3,
    title: 'Make a Field with Current',
    summary: 'Drive one straight conductor, reverse the current, and compare the solved field with the right-hand rule and the straight-wire equation.',
    status: 'available',
    estimate: '7 min',
  },
  {
    id: 'iron-saturation',
    number: 4,
    title: 'When Iron Saturates',
    summary: 'Drive an M350-50A ring through its B–H knee and watch effective permeability collapse in a nonlinear FEM solve.',
    status: 'available',
    estimate: '8 min',
  },
  {
    id: 'field-force',
    number: 5,
    title: 'Turn Field into Force',
    summary: 'Put a current-carrying conductor between magnet poles, reverse current, and compare FEM force with F = BIL.',
    status: 'available',
    estimate: '8 min',
  },
  {
    id: 'rotor-chase',
    number: 6,
    title: 'Give the Rotor Something to Chase',
    summary: 'Release a permanent-magnet rotor into a fixed field, then move the field target and watch alignment torque pull the rotor after it.',
    status: 'available',
    estimate: '8 min',
  },
  {
    id: 'rotating-field',
    number: 7,
    title: 'Make the Field Rotate',
    summary: 'Drive two perpendicular conductor pairs 90° apart and animate the solver-backed field through one electrical cycle.',
    status: 'available',
    estimate: '8 min',
  },
  {
    id: 'three-phase-motor',
    number: 8,
    title: 'Three Wires, One Rotating Field',
    summary: 'Drive six wound teeth with three balanced currents, release a PM rotor, then open one phase and reverse the phase sequence.',
    status: 'available',
    estimate: '9 min',
  },
  {
    id: 'motor-magnetic-circuit',
    number: 9,
    title: 'Build the 2p/6s Three-Phase Motor',
    summary: 'Turn the six-electromagnet teaching fixture into the first complete slotted SPM motor and inspect its magnetic circuit.',
    status: 'available',
    estimate: '10 min',
  },
  {
    id: 'back-emf-voltage-headroom',
    number: 10,
    title: 'BEMF & Voltage Headroom',
    summary: 'Spin the SPM motor, watch three-phase BEMF grow with speed, and compare it with inverter voltage.',
    status: 'available',
    estimate: '7 min',
  },
] as const;

/**
 * The primer splits at the point where the physics stops being about fields in
 * general and starts being about a machine. Lessons 1-5 are single-idea field
 * fixtures with no rotor; from lesson 6 every lesson has something turning.
 *
 * Each part closes with a review that ties its lessons together on one fixture.
 * Chapter 1's review is the "Make It Move" capstone; Chapter 2 remains planned.
 */
const LESSON_SECTIONS = [
  {
    id: 'fields',
    kicker: 'Part 1',
    title: 'Fields before motors',
    blurb: 'Explore flux, reluctance, current, saturation, and force.',
    lessonIds: [
      'follow-the-flux',
      'airgap-tax',
      'current-field',
      'iron-saturation',
      'field-force',
    ],
    review: {
      id: 'review-fields',
      title: 'Make It Move',
      summary:
        'Build a linear actuator without a recipe. Arrange the magnetic track, energize the carriage, strengthen it, and watch your machine move in 3D.',
      covers: '1-5',
      available: true,
    },
  },
  {
    id: 'machine',
    kicker: 'Part 2',
    title: 'From rotating field to motor',
    blurb:
      'Turn those fields into rotation: give a rotor something to chase, synthesize a rotating field from phased currents, assemble the first complete machine, and find the speed where it runs out of voltage.',
    lessonIds: [
      'rotor-chase',
      'rotating-field',
      'three-phase-motor',
      'motor-magnetic-circuit',
      'back-emf-voltage-headroom',
    ],
    review: {
      id: 'review-machine',
      title: 'Review: From Rotating Field to Working Motor',
      summary:
        'Trace one design end to end: three phase currents into a rotating MMF, MMF into alignment torque, and rising speed into the back-EMF that finally caps it.',
      covers: '6-10',
      available: false,
    },
  },
] as const;

export { LessonMotorDiagram } from './LessonMotorDiagram';

export const LearningCatalog: React.FC<LearningCatalogProps> = ({
  onSelectLesson,
  onBackHome,
  onStartGuidedTour,
  backHomeLabel = 'Back to design start',
}) => {
  const { completedLessons, isLessonComplete } = useLearningProgress();
  const primerCompleteCount = TIER_ONE_LESSONS.filter((lesson) => completedLessons.has(lesson.id)).length;
  const primerTotal = TIER_ONE_LESSONS.length;
  const primerPercent = Math.round((primerCompleteCount / primerTotal) * 100);
  // Resume at the first lesson not yet finished; once every lesson is done there is
  // nothing to resume, so the callout drops away instead of pointing back at lesson 1.
  const nextLesson = TIER_ONE_LESSONS.find((lesson) => !completedLessons.has(lesson.id)) ?? null;
  const featuredLesson = nextLesson ?? TIER_ONE_LESSONS[TIER_ONE_LESSONS.length - 1];
  const courseComplete = nextLesson === null;

  return (
    <main className="learning-shell learning-catalog-shell">
      <section className="learning-path-hero" aria-labelledby="learning-path-title">
        <div className="learning-path-intro">
          <p className="learning-kicker">Electric motor primer</p>
          <h1 id="learning-path-title">Learn how a motor works</h1>
          <p>Ten short, interactive experiments take you from a single magnetic field to a complete rotating machine.</p>
        </div>

        <button
          type="button"
          className={`learning-continue-card${courseComplete ? ' is-complete' : ''}`}
          onClick={() => onSelectLesson(featuredLesson.id as LearningLessonId)}
        >
          <span className="learning-continue-number" aria-hidden="true">
            {courseComplete ? '✓' : String(featuredLesson.number).padStart(2, '0')}
          </span>
          <LessonGlyph lessonId={featuredLesson.id} className="learning-continue-glyph" />
          <span className="learning-continue-copy">
            <span className="learning-continue-kicker">
              {courseComplete ? 'Course complete' : primerCompleteCount === 0 ? 'Begin here' : 'Continue learning'}
            </span>
            <strong>{featuredLesson.title}</strong>
            <span>{featuredLesson.summary}</span>
          </span>
          <span className="learning-continue-action">
            <span>{featuredLesson.estimate}</span>
            <strong>{courseComplete ? 'Review lesson' : primerCompleteCount === 0 ? 'Start lesson' : 'Continue'} →</strong>
          </span>
        </button>

        <div className="learning-path-progress">
          <div
            className="learning-path-progress-track"
            role="progressbar"
            aria-label="Primer progress"
            aria-valuemin={0}
            aria-valuemax={primerTotal}
            aria-valuenow={primerCompleteCount}
            aria-valuetext={`${primerCompleteCount} of ${primerTotal} lessons complete`}
          >
            <span style={{ width: `${primerPercent}%` }} />
          </div>
          <span>{primerCompleteCount} of {primerTotal} complete</span>
        </div>

        <div className="learning-path-roadmap" aria-label="Course chapters">
          {LESSON_SECTIONS.map((section, index) => {
            const completed = section.lessonIds.filter((id) => completedLessons.has(id)).length;
            const active = section.lessonIds.some((id) => id === featuredLesson.id);
            return (
              <div key={section.id} className={`learning-roadmap-chapter${active ? ' is-active' : ''}${completed === section.lessonIds.length ? ' is-complete' : ''}`}>
                <span className="learning-roadmap-index">{completed === section.lessonIds.length ? '✓' : index + 1}</span>
                <span>
                  <small>Chapter {index + 1} · lessons {section.review.covers}</small>
                  <strong>{section.title}</strong>
                </span>
                <em>{completed}/{section.lessonIds.length}</em>
              </div>
            );
          })}
        </div>
      </section>

      {LESSON_SECTIONS.map((section, sectionIndex) => {
        const sectionLessons = section.lessonIds
          .map((id) => TIER_ONE_LESSONS.find((lesson) => lesson.id === id))
          .filter((lesson): lesson is (typeof TIER_ONE_LESSONS)[number] => Boolean(lesson));
        const sectionComplete = sectionLessons.filter((lesson) => completedLessons.has(lesson.id)).length;
        const reviewComplete = completedLessons.has(section.review.id);
        // Capstones are always explorable from the course map. Completion still
        // communicates progression, but it should never hide a useful project.
        const reviewUnlocked = section.review.available;
        return (
          <section
            key={section.id}
            className="learning-path-chapter"
            aria-label={`${section.kicker}: ${section.title}`}
          >
            <header className="learning-path-chapter-header">
              <span className="learning-path-chapter-number">{String(sectionIndex + 1).padStart(2, '0')}</span>
              <div>
                <p className="learning-kicker">Chapter {sectionIndex + 1} · lessons {section.review.covers}</p>
                <h2>{section.title}</h2>
                <p>{section.blurb}</p>
              </div>
              <span className="learning-path-chapter-progress">
                {sectionComplete}/{sectionLessons.length} complete
              </span>
            </header>
            <ol
              className="learning-path-lessons"
              start={sectionIndex === 0 ? 1 : sectionLessons[0]?.number ?? 1}
            >
              {sectionLessons.map((lesson) => {
                const available = lesson.status === 'available';
                const complete = isLessonComplete(lesson.id);
                const isNext = nextLesson?.id === lesson.id;
                return (
                  <li key={lesson.id}>
                    <button
                      type="button"
                      className={`learning-path-lesson${available ? ' is-available' : ' is-planned'}${complete ? ' is-complete' : ''}${isNext ? ' is-next' : ''}`}
                      onClick={() => {
                        if (available) onSelectLesson(lesson.id as LearningLessonId);
                      }}
                      disabled={!available}
                      aria-current={isNext ? 'step' : undefined}
                    >
                      <span className="learning-path-lesson-number">
                        {complete ? '\u2713' : String(lesson.number).padStart(2, '0')}
                      </span>
                      <LessonGlyph lessonId={lesson.id} className="learning-path-lesson-glyph" />
                      <span className="learning-path-lesson-copy">
                        <strong>{lesson.title}</strong>
                        <span>{lesson.summary}</span>
                      </span>
                      <span className={`learning-path-lesson-state${complete ? ' is-complete' : ''}${isNext ? ' is-next' : ''}`}>
                        <small>{lesson.estimate}</small>
                        <strong>{complete ? 'Complete' : isNext ? primerCompleteCount === 0 ? 'Start here' : 'Continue' : available ? 'Available' : 'Planned'}</strong>
                      </span>
                      <span className="learning-path-lesson-arrow" aria-hidden="true">→</span>
                    </button>
                  </li>
                );
              })}
            </ol>
            <button
              type="button"
              className={`learning-path-coming-next${reviewUnlocked ? ' is-available' : ''}${reviewComplete ? ' is-complete' : ''}`}
              aria-label={`${section.review.title}${reviewUnlocked ? ', available' : ', locked'}`}
              disabled={!reviewUnlocked}
              onClick={() => {
                if (reviewUnlocked) onSelectLesson(section.review.id as LearningLessonId);
              }}
            >
              <LessonGlyph lessonId="section-review" className="learning-path-review-glyph" />
              <span>
                <small>{reviewComplete ? 'Chapter complete' : reviewUnlocked ? 'Ready · chapter capstone' : 'Coming next · chapter review'}</small>
                <strong>{section.review.title}</strong>
              </span>
              <p>{section.review.summary}</p>
              {reviewUnlocked ? <em>{reviewComplete ? 'Review again →' : 'Start capstone →'}</em> : null}
            </button>
          </section>
        );
      })}

      {onStartGuidedTour && (
        <section className="learning-path-secondary" aria-label="Other ways in">
          <header>
            <p className="learning-kicker">Other ways in</p>
            <h2>Prefer to start in the real app?</h2>
          </header>
          <div className="learning-alt-paths">
            <button type="button" className="learning-alt-card" onClick={onStartGuidedTour}>
              <LessonGlyph lessonId="guided-first-solve" className="learning-lesson-glyph" />
              <span className="learning-alt-copy">
                <span className="learning-lesson-status">Ready now</span>
                <span className="learning-lesson-title">Guided first solve</span>
                <span className="learning-lesson-summary">
                  Design the example motor, mesh it, run a solve, and read the report -
                  with coach marks on the real workspace.
                </span>
                <span className="learning-lesson-meta">~5 min - runs in the live workspace</span>
              </span>
            </button>
          </div>
        </section>
      )}

      <footer className="learning-path-footer">
        <button type="button" onClick={onBackHome}>← {backHomeLabel}</button>
        <span>Your lesson progress is saved on this computer.</span>
      </footer>
    </main>
  );
};
