import { connectLearningProgressStore } from '../../components/tutorials/useLearningProgress';
import { PUBLIC_API_BASE } from '../api';

const PROGRESS_URL = `${PUBLIC_API_BASE}/tutorials/progress`;

/** Lesson progress saved by the local app, so it outlives this browser's storage. */
export function connectPublicLearningProgress(): void {
  void connectLearningProgressStore({
    async load() {
      const response = await fetch(PROGRESS_URL);
      if (!response.ok) throw new Error(`Lesson progress failed to load: ${response.status}`);
      const body = (await response.json()) as { completed?: unknown };
      return Array.isArray(body.completed)
        ? body.completed.filter((id): id is string => typeof id === 'string')
        : [];
    },
    async save(lessonIds) {
      const response = await fetch(PROGRESS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ completed: lessonIds }),
      });
      if (!response.ok) throw new Error(`Lesson progress failed to save: ${response.status}`);
    },
  });
}
