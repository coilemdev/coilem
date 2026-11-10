import React from 'react';
import { LessonGlyph } from './LessonGlyph';
import { useLearningProgress } from './useLearningProgress';
import './learning.css';
import './lesson-catalog.css';

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
    brief: 'See how steel reshapes a magnet’s field.',
    number: 1,
    title: 'Follow the Flux',
    summary: 'Solve one magnet in open air, then move different steel shapes nearby and watch the field redistribute.',
    status: 'available',
    estimate: '8 min',
  },
  {
    id: 'airgap-tax',
    brief: 'Find out what an airgap costs in flux.',
    number: 2,
    title: 'Close the Loop: The Airgap Tax',
    summary: 'Close one magnet with steel, change two airgaps, and watch the solved flux pay the price.',
    status: 'available',
    estimate: '7 min',
  },
  {
    id: 'current-field',
    brief: 'Make a magnetic field with a wire.',
    number: 3,
    title: 'Make a Field with Current',
    summary: 'Drive one straight conductor, reverse the current, and compare the solved field with the right-hand rule and the straight-wire equation.',
    status: 'available',
    estimate: '7 min',
  },
  {
    id: 'iron-saturation',
    brief: 'Push steel until it stops helping.',
    number: 4,
    title: 'When Iron Saturates',
    summary: 'Drive an electrical-steel ring through its B–H knee and watch effective permeability collapse in a nonlinear solve.',
    status: 'available',
    estimate: '8 min',
  },
  {
    id: 'field-force',
    brief: 'Turn field and current into force.',
    number: 5,
    title: 'Turn Field into Force',
    summary: 'Put a current-carrying conductor between magnet poles, reverse current, and compare FEM force with F = BIL.',
    status: 'available',
    estimate: '8 min',
  },
  {
    id: 'rotor-chase',
    brief: 'Let a magnet rotor follow a field.',
    number: 6,
    title: 'Give the Rotor Something to Chase',
    summary: 'Release a permanent-magnet rotor into a fixed field, then move the field target and watch alignment torque pull the rotor after it.',
    status: 'available',
    estimate: '8 min',
  },
  {
    id: 'rotating-field',
    brief: 'Spin a field with two phased currents.',
    number: 7,
    title: 'Make the Field Rotate',
    summary: 'Drive two perpendicular conductor pairs 90° apart and animate the solver-backed field through one electrical cycle.',
    status: 'available',
    estimate: '8 min',
  },
  {
    id: 'three-phase-motor',
    brief: 'Drive a rotor with three phases.',
    number: 8,
    title: 'Three Wires, One Rotating Field',
    summary: 'Drive six wound teeth with three balanced currents, release a PM rotor, then open one phase and reverse the phase sequence.',
    status: 'available',
    estimate: '9 min',
  },
  {
    id: 'motor-magnetic-circuit',
    brief: 'Assemble a complete slotted motor.',
    number: 9,
    title: 'Build the 2p/6s Three-Phase Motor',
    summary: 'Turn the six-electromagnet teaching fixture into the first complete slotted SPM motor and inspect its magnetic circuit.',
    status: 'available',
    estimate: '10 min',
  },
  {
    id: 'back-emf-voltage-headroom',
    brief: 'See why speed runs out of voltage.',
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
  const { completedLessons } = useLearningProgress();
  const total = TIER_ONE_LESSONS.length;
  const done = TIER_ONE_LESSONS.filter((lesson) => completedLessons.has(lesson.id)).length;
  // Resume at the first lesson not yet finished.
  const nextLesson = TIER_ONE_LESSONS.find((lesson) => !completedLessons.has(lesson.id)) ?? null;
  const resumeLabel = nextLesson === null
    ? 'All ten lessons complete'
    : `${done === 0 ? 'Start' : 'Continue'} · Lesson ${nextLesson.number}`;

  return (
    <main className="learning-shell lesson-catalog">
      <header className="lesson-catalog-head">
        <div className="lesson-catalog-intro">
          <p className="lesson-catalog-kicker">Electric motor primer</p>
          <h1>Learn how a motor works</h1>
          <p>Ten short experiments, from a single magnetic field to a complete rotating machine.</p>
        </div>
        <div className="lesson-catalog-resume">
          <div className="lesson-catalog-progress">
            <span>{done} of {total} complete</span>
            <div
              className="lesson-catalog-progress-track"
              role="progressbar"
              aria-label="Lessons complete"
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={done}
              aria-valuetext={`${done} of ${total} lessons complete`}
            >
              <span style={{ width: `${(done / total) * 100}%` }} />
            </div>
          </div>
          <button
            type="button"
            className="learning-primary-button lesson-catalog-resume-button"
            disabled={nextLesson === null}
            onClick={() => {
              if (nextLesson) onSelectLesson(nextLesson.id as LearningLessonId);
            }}
          >
            {resumeLabel}{nextLesson ? ' →' : ''}
          </button>
        </div>
      </header>

      <div className="lesson-catalog-chapters">
        {LESSON_SECTIONS.map((section, sectionIndex) => {
          const lessons = section.lessonIds
            .map((id) => TIER_ONE_LESSONS.find((lesson) => lesson.id === id))
            .filter((lesson): lesson is (typeof TIER_ONE_LESSONS)[number] => Boolean(lesson));
          const chapterDone = lessons.filter((lesson) => completedLessons.has(lesson.id)).length;
          const chapterComplete = chapterDone === lessons.length;
          const review = section.review;
          const reviewComplete = completedLessons.has(review.id);
          return (
            <section
              key={section.id}
              className={`lesson-catalog-chapter${chapterComplete ? ' is-complete' : ''}`}
              aria-label={`Chapter ${sectionIndex + 1}: ${section.title}`}
            >
              <header className="lesson-catalog-chapter-head">
                <span className="lesson-catalog-chapter-index" aria-hidden="true">
                  {chapterComplete ? '\u2713' : sectionIndex + 1}
                </span>
                <div>
                  <p className="lesson-catalog-kicker">Chapter {sectionIndex + 1} · Lessons {review.covers.replace('-', '–')}</p>
                  <h2>{section.title}</h2>
                </div>
                <span className="lesson-catalog-chapter-count">{chapterDone}/{lessons.length}</span>
              </header>
              <ol className="lesson-catalog-lessons" start={lessons[0]?.number ?? 1}>
                {lessons.map((lesson) => {
                  const complete = completedLessons.has(lesson.id);
                  const isNext = nextLesson?.id === lesson.id;
                  return (
                    <li key={lesson.id}>
                      <button
                        type="button"
                        className={`lesson-catalog-lesson${complete ? ' is-complete' : ''}${isNext ? ' is-next' : ''}`}
                        title={lesson.summary}
                        aria-current={isNext ? 'step' : undefined}
                        onClick={() => onSelectLesson(lesson.id as LearningLessonId)}
                      >
                        <span className="lesson-catalog-lesson-number">
                          {complete ? '\u2713' : lesson.number}
                        </span>
                        <LessonGlyph lessonId={lesson.id} className="lesson-catalog-lesson-glyph" />
                        <span className="lesson-catalog-lesson-copy">
                          <strong>{lesson.title}</strong>
                          <span>{lesson.brief}</span>
                        </span>
                        <span className="lesson-catalog-lesson-state">
                          {complete ? 'Done' : isNext ? (done === 0 ? 'Start here' : 'Up next') : lesson.estimate}
                        </span>
                      </button>
                    </li>
                  );
                })}
                <li>
                  <button
                    type="button"
                    className={`lesson-catalog-lesson is-capstone${reviewComplete ? ' is-complete' : ''}`}
                    title={review.summary}
                    disabled={!review.available}
                    onClick={() => {
                      if (review.available) onSelectLesson(review.id as LearningLessonId);
                    }}
                  >
                    <span className="lesson-catalog-lesson-number">{reviewComplete ? '\u2713' : '\u2605'}</span>
                    <LessonGlyph lessonId="section-review" className="lesson-catalog-lesson-glyph" />
                    <span className="lesson-catalog-lesson-copy">
                      <strong>{review.available ? `Capstone: ${review.title}` : 'Chapter 2 capstone'}</strong>
                      <span>{review.available ? 'Build a linear motor from Lessons 1–5.' : 'A project that ties Lessons 6–10 together.'}</span>
                    </span>
                    <span className="lesson-catalog-lesson-state">
                      {reviewComplete ? 'Done' : review.available ? 'Project' : 'Coming soon'}
                    </span>
                  </button>
                </li>
              </ol>
            </section>
          );
        })}
      </div>

      <footer className="lesson-catalog-foot">
        <button type="button" onClick={onBackHome}>← {backHomeLabel}</button>
        {onStartGuidedTour ? (
          <button type="button" onClick={onStartGuidedTour}>Guided first solve in the workspace →</button>
        ) : null}
        <span>Progress is saved on this computer.</span>
      </footer>
    </main>
  );
};
