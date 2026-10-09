import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { MotorConfig } from './model';
import type { PublicParameterSection } from './CoilEmWorkspace';

/**
 * Guided setup coach for the public workspace: coach-marks over the real app,
 * pitched at someone building their first motor. Stops anchor to stable
 * [data-guide] attributes, the ring highlights the active parameter section,
 * and every stop offers the same Back/Next navigation. Workflow-boundary
 * steps use Next to enter Solve, start the run, or open the finished report.
 */

export type GuidedWorkflowStep = 'design' | 'solve' | 'report';

export interface GuidedStop {
  id: string;
  /** Workflow stage the stop belongs to. */
  step: GuidedWorkflowStep;
  /** data-guide attribute of the highlighted element; null = centered card. */
  target: string | null;
  title: string;
  body: string;
  /**
   * Stops always expose Next. These values add optional automatic advancement:
   * 'next'   — button only.
   * 'anchor' — also advances when `advanceWhenActive` becomes active.
   * 'stage'  — also advances when the workflow stage moves past this stop.
   * 'result' — also advances when the solver result arrives.
   */
  advance: 'next' | 'anchor' | 'stage' | 'result';
  advanceWhenActive?: string;
}

export const PUBLIC_GUIDED_STOPS: GuidedStop[] = [
  {
    id: 'topology',
    step: 'design',
    target: 'topology-selector',
    title: 'Choose the motor topology',
    body: 'Start with the rotor architecture, before entering dimensions. Choose SPM for surface-mounted magnets or IPM for magnets buried inside the rotor. The starter design is already a valid 8-pole/12-slot motor, so you can accept every later default and keep moving.',
    advance: 'next',
  },
  {
    id: 'ipm-layout',
    step: 'design',
    target: 'ipm-layout-selector',
    title: 'Choose the IPM rotor layout',
    body: 'Flat / buried keeps each magnet parallel inside the rotor. V-shape angles magnet pairs to add saliency. Pick the architecture now; V-angle and depth remain available later under Advanced Geometry if you want to fine-tune them.',
    advance: 'next',
  },
  {
    id: 'stator',
    step: 'design',
    target: 'section-stator',
    title: 'Start with the stator',
    body: 'The stator is the stationary steel ring that carries the windings. Outer diameter, bore, slot count, and stack length live here — the cross-section redraws as you type, so nudge a value and watch it follow.',
    advance: 'anchor',
    advanceWhenActive: 'section-rotor',
  },
  {
    id: 'rotor',
    step: 'design',
    target: 'section-rotor',
    title: 'Shape the rotor and magnets',
    body: 'The rotor spins inside the stator bore. Pole count and magnet size set the magnetic loading, and the derived air gap updates live — around half a millimetre to one millimetre is practical at this scale.',
    advance: 'anchor',
    advanceWhenActive: 'section-advanced',
  },
  {
    id: 'advanced',
    step: 'design',
    target: 'section-advanced',
    title: 'Tune the advanced geometry',
    body: 'Bore tooth width, yoke tooth width, and yoke thickness trade copper room against iron saturation. The corresponding bore opening and yoke-side slot width are calculated from those two tooth widths. The defaults suit the example motor, so feel free to continue straight on to the winding.',
    advance: 'anchor',
    advanceWhenActive: 'section-winding',
  },
  {
    id: 'winding',
    step: 'design',
    target: 'section-winding',
    title: 'Define the winding',
    body: 'Each stator tooth carries one concentrated coil, so every slot holds two coil sides — the 2D Winding layer paints both halves and marks current out of the page (⊙) and into the page (⊗). Turns and parallel paths scale torque against current.',
    advance: 'anchor',
    advanceWhenActive: 'section-materials',
  },
  {
    id: 'materials',
    step: 'design',
    target: 'section-materials',
    title: 'Assign materials',
    body: 'Steel grades set saturation and the magnet grade sets remanence; the open reference set is made for learning. That completes the motor definition — select Next to move to the analysis stage.',
    advance: 'stage',
  },
  {
    id: 'solve-plan',
    step: 'solve',
    target: 'solve-plan',
    title: 'Pick a solve plan',
    body: 'A plan sets mesh density and angular sampling: Preview offers a quick check, Standard balances resolution and runtime, and High accuracy uses a finer mesh. Choosing a plan prepares the native mesh automatically. Preset names do not guarantee accuracy.',
    advance: 'next',
  },
  {
    id: 'solve-run',
    step: 'solve',
    target: 'solve-run',
    title: 'Run the analysis',
    body: 'Select Next to start the local solver. It steps the rotor through a sweep of positions while live torque and back-EMF samples stream into the right panel, then advances when the run completes.',
    advance: 'result',
  },
  {
    id: 'report',
    step: 'solve',
    target: 'open-report',
    title: 'Solved — open the report',
    body: 'Summary metrics are in and the solved field is painted on the motor. Select Next to open the full report for torque, back-EMF, and flux-density plots. That is the whole loop: design, solve, report — change one value and run it again.',
    advance: 'stage',
  },
];

const GUIDED_DESIGN_SECTIONS: Record<string, PublicParameterSection> = {
  'section-stator': 'stator',
  'section-rotor': 'rotor',
  'section-advanced': 'advanced',
  'section-winding': 'winding',
  'section-materials': 'materials',
};

function designSectionForStop(stop: GuidedStop): PublicParameterSection | null {
  return stop.target ? GUIDED_DESIGN_SECTIONS[stop.target] ?? null : null;
}

interface GuidedTargetRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface PublicGuidedSetupProps {
  activeStep: GuidedWorkflowStep;
  topology: MotorConfig['topology'];
  resultReady: boolean;
  busy: boolean;
  onWorkflowStepChange: (step: GuidedWorkflowStep) => void;
  onDesignSectionChange: (section: PublicParameterSection | null) => string | null;
  onStartSolve: () => void;
  onExit: (completed: boolean) => void;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

function guidedStopsForTopology(topology: MotorConfig['topology']): GuidedStop[] {
  return topology === 'IPM'
    ? PUBLIC_GUIDED_STOPS
    : PUBLIC_GUIDED_STOPS.filter((stop) => stop.id !== 'ipm-layout');
}

function firstStopIndexForStep(step: GuidedWorkflowStep, stops: GuidedStop[]): number {
  const index = stops.findIndex((stop) => stop.step === step);
  return index >= 0 ? index : 0;
}

export function PublicGuidedSetup({
  activeStep,
  topology,
  resultReady,
  busy,
  onWorkflowStepChange,
  onDesignSectionChange,
  onStartSolve,
  onExit,
}: PublicGuidedSetupProps) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<GuidedTargetRect | null>(null);
  const [adjustmentMessage, setAdjustmentMessage] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const scrolledStopRef = useRef<string | null>(null);
  const ipmAutoAdvanceRef = useRef(false);
  const stops = useMemo(() => guidedStopsForTopology(topology), [topology]);
  const currentIndex = Math.min(index, stops.length - 1);
  const stop = stops[currentIndex];

  const finish = useCallback((completed: boolean) => {
    onExit(completed);
  }, [onExit]);

  useEffect(() => {
    // Repair notes belong to the design stop that produced them. A direct
    // stepper/stage jump must not carry that message into Solve or Report.
    setAdjustmentMessage(null);
  }, [activeStep]);

  const showStop = useCallback((nextIndex: number) => {
    const nextStop = stops[nextIndex];
    if (!nextStop) return;
    setIndex(nextIndex);
    setAdjustmentMessage(onDesignSectionChange(designSectionForStop(nextStop)));
    if (nextStop.step !== activeStep) onWorkflowStepChange(nextStop.step);
  }, [activeStep, onDesignSectionChange, onWorkflowStepChange, stops]);

  const next = useCallback(() => {
    showStop(Math.min(currentIndex + 1, stops.length - 1));
  }, [currentIndex, showStop, stops.length]);

  const handleNext = useCallback(() => {
    if (stop.id === 'solve-run' && !resultReady) {
      if (!busy) onStartSolve();
      return;
    }
    const nextStop = stops[currentIndex + 1];
    if (!nextStop) {
      if (stop.id === 'report') onWorkflowStepChange('report');
      else finish(true);
      return;
    }
    showStop(currentIndex + 1);
  }, [
    busy,
    currentIndex,
    finish,
    onStartSolve,
    onWorkflowStepChange,
    resultReady,
    showStop,
    stop.id,
    stops,
  ]);

  // Follow the workflow: performing a stage action (or jumping via the
  // stepper) snaps the coach to that stage; reaching Report completes it.
  useEffect(() => {
    if (activeStep === 'report') {
      finish(true);
      return;
    }
    if (activeStep !== 'design') onDesignSectionChange(null);
    if (stop.step !== activeStep) setIndex(firstStopIndexForStep(activeStep, stops));
  }, [activeStep, finish, onDesignSectionChange, stop.step, stops]);

  // Track the highlighted element. Poll cheaply — panels mount, sections
  // expand, and layout shifts; a short cadence follows along closely enough.
  useEffect(() => {
    let cancelled = false;
    const measure = () => {
      if (cancelled) return;
      const element = stop.target
        ? document.querySelector<HTMLElement>(`[data-guide="${stop.target}"]`)
        : null;
      if (!element) {
        setRect(null);
        return;
      }
      if (scrolledStopRef.current !== stop.id) {
        scrolledStopRef.current = stop.id;
        element.scrollIntoView({
          block: 'nearest',
          behavior: prefersReducedMotion() ? 'auto' : 'smooth',
        });
      }
      const bounds = element.getBoundingClientRect();
      setRect({ top: bounds.top, left: bounds.left, width: bounds.width, height: bounds.height });
    };
    measure();
    const interval = window.setInterval(measure, 300);
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [stop]);

  // Anchor stops advance when the user clicks the section's own
  // "Continue Setup: →" button and the next section becomes the active one.
  useEffect(() => {
    if (stop.advance !== 'anchor' || !stop.advanceWhenActive) return undefined;
    const probe = window.setInterval(() => {
      const nextSectionActive = document.querySelector(
        `[data-guide="${stop.advanceWhenActive}"][data-guide-active="true"]`,
      );
      const ownSectionActive = stop.target
        ? document.querySelector(`[data-guide="${stop.target}"][data-guide-active="true"]`)
        : null;
      if (nextSectionActive && !ownSectionActive) {
        window.clearInterval(probe);
        next();
      }
    }, 350);
    return () => window.clearInterval(probe);
  }, [next, stop]);

  useEffect(() => {
    if (stop.advance === 'result' && resultReady) next();
  }, [next, resultReady, stop]);

  // The starter is SPM, so choosing IPM is an explicit user decision. Move
  // straight into the conditional layout stop rather than making them confirm
  // the topology with a second click. Keep the ref set so Back remains useful.
  useEffect(() => {
    if (stop.id === 'topology' && topology === 'IPM' && !ipmAutoAdvanceRef.current) {
      ipmAutoAdvanceRef.current = true;
      next();
    }
  }, [next, stop.id, topology]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') finish(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [finish]);

  useEffect(() => {
    cardRef.current?.focus({ preventScroll: true });
  }, [stop.id]);

  const cardStyle = useMemo(() => {
    if (!rect) {
      return { left: '50%', top: '50%', transform: 'translate(-50%, -50%)' } as const;
    }
    const cardWidth = 324;
    const cardHeight = adjustmentMessage ? 278 : 236;
    const margin = 12;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const fitsBeside = rect.left + rect.width + margin + cardWidth < viewportWidth;
    const left = fitsBeside
      ? rect.left + rect.width + margin
      : Math.min(Math.max(rect.left, margin), Math.max(margin, viewportWidth - cardWidth - margin));
    const below = rect.top + rect.height + margin;
    const top = fitsBeside
      ? Math.min(Math.max(rect.top, margin), Math.max(margin, viewportHeight - cardHeight - margin))
      : below + cardHeight < viewportHeight
        ? below
        : Math.max(margin, rect.top - cardHeight - margin);
    return { left: `${left}px`, top: `${top}px` } as const;
  }, [adjustmentMessage, rect]);

  const canGoBack = currentIndex > 0 && stops[currentIndex - 1].step === stop.step;
  const nextDisabled = stop.id === 'solve-run' && busy;

  return (
    <div className="public-guided-coach" role="dialog" aria-label="Guided motor setup">
      {rect ? (
        <div
          className="public-guided-highlight"
          style={{ top: rect.top - 5, left: rect.left - 5, width: rect.width + 10, height: rect.height + 10 }}
        />
      ) : (
        <div className="public-guided-scrim" />
      )}
      <div className="public-guided-card" style={cardStyle} ref={cardRef} tabIndex={-1}>
        <div className="public-guided-progress">
          <span className="public-section-kicker">Guided setup</span>
          <span>Step {currentIndex + 1} of {stops.length}</span>
        </div>
        <h3>{stop.title}</h3>
        <p aria-live="polite">{stop.body}</p>
        {adjustmentMessage && (
          <div className="public-guided-auto-adjustment" role="status">
            <span aria-hidden="true">✓</span>
            {adjustmentMessage}
          </div>
        )}
        <div className="public-guided-actions">
          <button type="button" className="public-guided-exit" onClick={() => finish(false)}>
            Exit guided setup
          </button>
          <div className="public-guided-nav">
            {canGoBack && (
              <button type="button" onClick={() => showStop(currentIndex - 1)}>Back</button>
            )}
            <button
              type="button"
              className="public-guided-next"
              disabled={nextDisabled}
              onClick={handleNext}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
