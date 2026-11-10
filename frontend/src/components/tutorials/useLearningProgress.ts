import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from 'react';

const PRIMER_KEY = 'coilem.learning.primer.v1';
const PROGRESS_EVENT = 'coilem:learning-progress';

const readIdSet = (key: string): Set<string> => {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((id): id is string => typeof id === 'string'));
  } catch {
    return new Set();
  }
};

const writeIdSet = (key: string, ids: Set<string>) => {
  try {
    window.localStorage.setItem(key, JSON.stringify([...ids]));
  } catch {
    // Storage unavailable (private mode etc.): progress simply won't persist.
  }
};

/** Somewhere longer-lived than this browser's storage, supplied by the host app. */
export interface LearningProgressStore {
  load: () => Promise<string[]>;
  save: (lessonIds: string[]) => Promise<void>;
}

let progressStore: LearningProgressStore | null = null;

const saveToStore = (ids: Set<string>) => {
  // Best effort: the browser copy still holds the progress if this fails.
  void progressStore?.save([...ids].sort()).catch(() => undefined);
};

/**
 * Keep lesson progress in the host's store as well as in the browser. Browser
 * storage belongs to one origin, port included, so the app opened on another
 * port or in another browser would otherwise show no finished lessons.
 * Lessons finished in either place are kept.
 */
export async function connectLearningProgressStore(store: LearningProgressStore): Promise<void> {
  progressStore = store;
  let stored: string[];
  try {
    stored = await store.load();
  } catch {
    return;
  }
  const local = readIdSet(PRIMER_KEY);
  const merged = new Set([...local, ...stored]);
  if (merged.size !== local.size) {
    writeIdSet(PRIMER_KEY, merged);
    window.dispatchEvent(new CustomEvent(PROGRESS_EVENT, { detail: { key: PRIMER_KEY } }));
  }
  if (merged.size !== stored.length) saveToStore(merged);
}

const setMembership = (
  key: string,
  setState: Dispatch<SetStateAction<Set<string>>>,
  id: string,
  complete: boolean,
) => {
  const next = readIdSet(key);
  if (complete) next.add(id);
  else next.delete(id);
  writeIdSet(key, next);
  saveToStore(next);
  setState(next);
  window.dispatchEvent(new CustomEvent(PROGRESS_EVENT, { detail: { key } }));
};

export interface LearningProgress {
  completedLessons: Set<string>;
  isLessonComplete: (lessonId: string) => boolean;
  setLessonComplete: (lessonId: string, complete: boolean) => void;
}

export const useLearningProgress = (): LearningProgress => {
  const [completedLessons, setCompletedLessons] = useState<Set<string>>(() => readIdSet(PRIMER_KEY));

  useEffect(() => {
    const syncProgress = () => setCompletedLessons(readIdSet(PRIMER_KEY));
    window.addEventListener(PROGRESS_EVENT, syncProgress);
    window.addEventListener('storage', syncProgress);
    return () => {
      window.removeEventListener(PROGRESS_EVENT, syncProgress);
      window.removeEventListener('storage', syncProgress);
    };
  }, []);

  const setLessonComplete = useCallback((lessonId: string, complete: boolean) => {
    setMembership(PRIMER_KEY, setCompletedLessons, lessonId, complete);
  }, []);

  const isLessonComplete = useCallback(
    (lessonId: string) => completedLessons.has(lessonId),
    [completedLessons],
  );
  return {
    completedLessons,
    isLessonComplete,
    setLessonComplete,
  };
};
