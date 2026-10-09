/**
 * Path <-> lesson mapping for the public tutorials area.
 *
 * Deliberately free of component imports: this module is reached from the public
 * app's eager entry chunk to decide *which* lesson to load, so importing the
 * lessons here would defeat the lazy boundaries in TutorialsRoute and pull ~550 KB
 * of lesson code onto the landing page's critical path.
 *
 * The alias paths mirror the private app's table (src/App.tsx:245-295) so a link
 * shared out of either build resolves in the other.
 */

export type PublicLessonId =
  | 'lesson-1'
  | 'lesson-2'
  | 'lesson-3'
  | 'lesson-4'
  | 'lesson-5'
  | 'lesson-6'
  | 'lesson-7'
  | 'lesson-8'
  | 'lesson-9'
  | 'lesson-10'
  | 'chapter-1-capstone';

export type PublicTutorialsView = 'catalog' | PublicLessonId;

/** Canonical path first; the rest are accepted aliases. */
const LESSON_PATHS: Record<PublicLessonId, readonly string[]> = {
  'lesson-1': ['/tutorials/lesson-1', '/tutorials/follow-the-flux'],
  'lesson-2': ['/tutorials/lesson-2', '/tutorials/airgap-tax'],
  'lesson-3': ['/tutorials/lesson-3', '/tutorials/current-field'],
  'lesson-4': ['/tutorials/lesson-4', '/tutorials/iron-saturation'],
  'lesson-5': ['/tutorials/lesson-5', '/tutorials/field-force'],
  'lesson-6': ['/tutorials/lesson-6', '/tutorials/rotor-chase', '/tutorials/torque-production'],
  'lesson-7': ['/tutorials/lesson-7', '/tutorials/rotating-field'],
  'lesson-8': ['/tutorials/lesson-8', '/tutorials/three-phase-motor'],
  'lesson-9': [
    '/tutorials/lesson-9',
    '/tutorials/magnetic-circuit',
    '/tutorials/motor-magnetic-circuit',
  ],
  'lesson-10': [
    '/tutorials/lesson-10',
    '/tutorials/back-emf',
    '/tutorials/back-emf-voltage-headroom',
  ],
  'chapter-1-capstone': [
    '/tutorials/chapter-1-capstone',
    '/tutorials/make-it-move',
    '/tutorials/review-fields',
  ],
};

/** Maps the catalog's lesson ids onto the route ids. */
export const LESSON_ID_BY_CATALOG_ID: Record<string, PublicLessonId> = {
  'follow-the-flux': 'lesson-1',
  'airgap-tax': 'lesson-2',
  'current-field': 'lesson-3',
  'iron-saturation': 'lesson-4',
  'field-force': 'lesson-5',
  'review-fields': 'chapter-1-capstone',
  'rotor-chase': 'lesson-6',
  'torque-production': 'lesson-6',
  'rotating-field': 'lesson-7',
  'three-phase-motor': 'lesson-8',
  'motor-magnetic-circuit': 'lesson-9',
  'back-emf-voltage-headroom': 'lesson-10',
};

export function tutorialsViewFromPathname(pathname: string): PublicTutorialsView | null {
  const normalized = pathname.replace(/\/+$/, '') || '/';
  if (normalized === '/tutorials') return 'catalog';
  for (const [id, paths] of Object.entries(LESSON_PATHS)) {
    if (paths.includes(normalized)) return id as PublicLessonId;
  }
  return null;
}

export function pathForTutorialsView(view: PublicTutorialsView): string {
  if (view === 'catalog') return '/tutorials';
  return LESSON_PATHS[view][0];
}
