import React from 'react';
import { useLearningProgress } from './useLearningProgress';

interface LessonCompleteButtonProps {
  lessonId: string;
  canComplete: boolean;
  requirementsLabel?: string;
}

export const LessonCompleteButton: React.FC<LessonCompleteButtonProps> = ({
  lessonId,
  canComplete,
  requirementsLabel = 'Complete the required checkpoints first',
}) => {
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const complete = isLessonComplete(lessonId);
  const disabled = !complete && !canComplete;
  return (
    <button
      type="button"
      className={`learning-complete-button${complete ? ' is-complete' : ''}`}
      onClick={() => {
        if (complete || canComplete) setLessonComplete(lessonId, !complete);
      }}
      aria-pressed={complete}
      disabled={disabled}
      title={disabled ? requirementsLabel : undefined}
    >
      {complete ? 'Lesson completed ✓' : canComplete ? 'Mark lesson complete' : requirementsLabel}
    </button>
  );
};
