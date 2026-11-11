/**
 * Where a student is inside a lesson, kept for the browser tab.
 *
 * A reload, the browser's Back button, or a trip to the catalog unmounts the
 * lesson and would otherwise put it back at step 1. The small choices that
 * place a student in a lesson (the prediction, the step reached) are kept
 * here, keyed by lesson id. Solved fields are never stored: they are large,
 * and the lesson asks the solver for them again when it resumes.
 *
 * sessionStorage is used on purpose. It survives a reload and in-tab
 * navigation, and a new tab starts clean, so a stored state can never keep a
 * lesson stuck for good. Finished lessons are remembered separately (and for
 * longer) by useLearningProgress.
 */
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';

const SESSION_KEY_PREFIX = 'coilem.learning.session.v1.';

type LessonSessionRecord = Record<string, unknown>;

const storage = (): Storage | null => {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    // Storage blocked (private mode, sandboxed frame): lessons simply start fresh.
    return null;
  }
};

export function readLessonSession(lessonId: string): LessonSessionRecord {
  try {
    const raw = storage()?.getItem(SESSION_KEY_PREFIX + lessonId);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as LessonSessionRecord
      : {};
  } catch {
    return {};
  }
}

export function writeLessonSessionValue(lessonId: string, key: string, value: unknown): void {
  try {
    const store = storage();
    if (!store) return;
    const next = { ...readLessonSession(lessonId) };
    if (value === null || value === undefined) delete next[key];
    else next[key] = value;
    if (Object.keys(next).length === 0) store.removeItem(SESSION_KEY_PREFIX + lessonId);
    else store.setItem(SESSION_KEY_PREFIX + lessonId, JSON.stringify(next));
  } catch {
    // Full or blocked storage: the lesson still works, it just will not resume.
  }
}

/** Forget where the student was. "Restart lesson" calls this. */
export function clearLessonSession(lessonId: string): void {
  try {
    storage()?.removeItem(SESSION_KEY_PREFIX + lessonId);
  } catch {
    // Nothing to clear.
  }
}

/**
 * useState that is remembered for this lesson in this tab. Only for small
 * JSON values (a choice id, a flag, a number). `isValid` guards against a
 * stored value from an older build that the lesson no longer understands.
 */
export function useLessonSessionState<T>(
  lessonId: string,
  key: string,
  initial: T,
  isValid?: (value: unknown) => boolean,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    const stored = readLessonSession(lessonId)[key];
    if (stored === undefined) return initial;
    if (isValid ? !isValid(stored) : typeof stored !== typeof initial && initial !== null) return initial;
    return stored as T;
  });
  const firstRun = useRef(true);
  useEffect(() => {
    // The first run only repeats what was just read.
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
    writeLessonSessionValue(lessonId, key, value);
  }, [key, lessonId, value]);
  return [value, setValue];
}

/**
 * Remember the lesson's stage and, when the lesson is opened again, take the
 * student back into the lab.
 *
 * The host always opens a lesson at its first stage. If the student had moved
 * past it, `resume` is called once: it should do what the first step's main
 * button does (enter the lab and ask for its first solve again). Pass null
 * while that is not possible, for example when no correct prediction is stored.
 */
export function useLessonResume(
  lessonId: string,
  stage: string,
  resume: (() => void) | null,
  firstStage = 'design',
): void {
  const started = useRef(false);
  const resumeRef = useRef(resume);
  resumeRef.current = resume;
  useEffect(() => {
    if (!started.current) {
      started.current = true;
      const stored = readLessonSession(lessonId).stage;
      if (typeof stored === 'string' && stored !== firstStage && stage === firstStage && resumeRef.current) {
        resumeRef.current();
        return;
      }
    }
    writeLessonSessionValue(lessonId, 'stage', stage);
  }, [firstStage, lessonId, stage]);
}

/** An "is one of these ids (or nothing chosen yet)" check for useLessonSessionState. */
export function oneOf<T extends string>(ids: readonly T[]): (value: unknown) => boolean {
  return (value: unknown) => (
    value === null || (typeof value === 'string' && (ids as readonly string[]).includes(value))
  );
}
