import { useEffect, useRef, useState } from 'react';

import { getPublicFieldFrame, type PublicSolveProgress } from './api';
import type { PublicFieldLinePlot } from './model';
import { publicProgressFieldFrameId } from './solveProgress';

/**
 * The solved field of the first rotor position a running solve reports, or
 * null until there is one.
 *
 * A solve stores each position's field as it goes and names it in its
 * progress events. This reads the first one, once, so the Solve page can show
 * a real result while the rest of the sweep runs. It asks nothing more of the
 * solver than that one stored frame.
 */
export function useFirstSolvedField(solving: boolean, progress: PublicSolveProgress | null): PublicFieldLinePlot | null {
  const [plot, setPlot] = useState<PublicFieldLinePlot | null>(null);
  const requestedIdRef = useRef<string | null>(null);
  const startingOver = !solving || !progress || progress.stage === 'Validating';
  const frameId = startingOver ? null : publicProgressFieldFrameId(progress);

  useEffect(() => {
    if (startingOver) {
      requestedIdRef.current = null;
      setPlot(null);
      return;
    }
    if (!frameId || requestedIdRef.current) return;
    requestedIdRef.current = frameId;
    getPublicFieldFrame(frameId)
      .then((payload) => {
        const frame = payload.field_line_frame as unknown as PublicFieldLinePlot | undefined;
        if (frame && requestedIdRef.current === frameId) setPlot(frame);
      })
      .catch(() => {
        // The preview is optional: without it the mesh keeps showing.
      });
  }, [frameId, startingOver]);

  return plot;
}
