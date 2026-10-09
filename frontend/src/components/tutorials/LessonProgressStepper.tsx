import type { LearningLessonHeaderProgress } from './lessonStage';

interface LessonProgressStepperProps {
  progress: LearningLessonHeaderProgress;
}

export function LessonProgressStepper({ progress }: LessonProgressStepperProps) {
  return (
    <nav
      className="workflow-stepper workflow-stepper-inline lesson-progress-stepper"
      aria-label={`${progress.eyebrow ?? `Lesson ${progress.lessonNumber}`} progress`}
    >
      {progress.steps.map((step, index) => {
        const active = step.id === progress.currentStepId;
        const disabled = !step.available && !active;
        return (
          <span className="lesson-progress-step-wrap" key={step.id}>
            <button
              type="button"
              className={`stepper-step${active ? ' active' : ''}${step.complete ? ' done' : ''}${disabled ? ' disabled' : ''}`}
              disabled={disabled}
              aria-current={active ? 'step' : undefined}
              onClick={() => progress.onStepSelect?.(step.id)}
            >
              <span className="stepper-step-num">{step.complete ? '✓' : index + 1}</span>
              <span className="lesson-progress-label">{step.label}</span>
            </button>
            {index < progress.steps.length - 1 ? (
              <span className="stepper-arrow" aria-hidden="true" />
            ) : null}
          </span>
        );
      })}
    </nav>
  );
}
