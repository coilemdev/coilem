/**
 * The three stages a tutorial lesson walks through.
 *
 * Declared here (rather than in components/LearningLessons.tsx) so the shared
 * lesson tree owns it; LearningLessons re-exports the name unchanged.
 */
export type LearningLessonStage = 'design' | 'mesh' | 'solve';

export interface LearningLessonProgressStep {
  id: string;
  label: string;
  complete: boolean;
  available: boolean;
}

export interface LearningLessonHeaderProgress {
  /** Overrides the default "Lesson n of total" label for chapter reviews. */
  eyebrow?: string;
  lessonNumber: number;
  lessonCount: number;
  title: string;
  currentStepId: string;
  steps: LearningLessonProgressStep[];
  onStepSelect?: (stepId: string) => void;
}
