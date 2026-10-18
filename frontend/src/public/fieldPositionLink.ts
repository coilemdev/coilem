/**
 * Links the Solve tab's field view and its waveform plots. Hovering or clicking
 * a torque or back-EMF curve moves the field to that solved position, and the
 * curves mark where the field is while it plays. A small store rather than
 * React state, so playback re-renders only the plots, not the whole Solve page.
 */
export interface FieldPositionLink {
  /** The field view's electrical angle, or null when no field is shown. */
  getPlayhead: () => number | null;
  setPlayhead: (angleDeg: number | null) => void;
  subscribePlayhead: (listener: () => void) => () => void;
  /** Ask the field view to show the solved position nearest this angle. */
  requestAngle: (angleDeg: number) => void;
  subscribeRequests: (listener: (angleDeg: number) => void) => () => void;
}

export function createFieldPositionLink(): FieldPositionLink {
  let playhead: number | null = null;
  const playheadListeners = new Set<() => void>();
  const requestListeners = new Set<(angleDeg: number) => void>();
  return {
    getPlayhead: () => playhead,
    setPlayhead: (angleDeg) => {
      if (angleDeg === playhead) return;
      playhead = angleDeg;
      playheadListeners.forEach((listener) => listener());
    },
    subscribePlayhead: (listener) => {
      playheadListeners.add(listener);
      return () => {
        playheadListeners.delete(listener);
      };
    },
    requestAngle: (angleDeg) => {
      if (!Number.isFinite(angleDeg)) return;
      requestListeners.forEach((listener) => listener(angleDeg));
    },
    subscribeRequests: (listener) => {
      requestListeners.add(listener);
      return () => {
        requestListeners.delete(listener);
      };
    },
  };
}
