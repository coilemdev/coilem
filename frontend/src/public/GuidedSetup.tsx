import { useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { MotorConfig } from './model';
import type { PublicParameterSection, SolveSetupSection } from './CoilEmWorkspace';
import { GuidedDesignProgressContext, NewDesignEntryContext, entrySectionComplete, hasEntry } from './newDesignEntry';

export type GuidedWorkflowStep = 'design' | 'solve' | 'report';
export interface GuidedStop {
  id: string;
  step: GuidedWorkflowStep;
  target: string;
  label: string;
  title: string;
  section?: PublicParameterSection;
  solveSection?: SolveSetupSection;
}

/** The same outside-in sequence as New Design, followed by every Solve section. */
export const PUBLIC_GUIDED_STOPS: GuidedStop[] = [
  { id: 'arrangement', step: 'design', target: 'arrangement-selector', label: 'Arrangement',
    title: 'Choose the rotor arrangement' },
  { id: 'topology', step: 'design', target: 'topology-selector', label: 'Topology',
    title: 'Choose the motor topology' },
  { id: 'ipm-layout', step: 'design', target: 'ipm-layout-selector', label: 'IPM layout',
    title: 'Choose the IPM rotor layout' },
  { id: 'stator', step: 'design', target: 'section-stator', section: 'stator', label: 'Stator',
    title: 'Build the stator from outside inward' },
  { id: 'advanced', step: 'design', target: 'section-advanced', section: 'advanced', label: 'Teeth & slots',
    title: 'Shape the teeth and slots' },
  { id: 'rotor', step: 'design', target: 'section-rotor', section: 'rotor', label: 'Rotor & magnets',
    title: 'Shape the rotor and magnets' },
  { id: 'winding', step: 'design', target: 'section-winding', section: 'winding', label: 'Winding',
    title: 'Define the winding' },
  { id: 'materials', step: 'design', target: 'section-materials', section: 'materials', label: 'Materials',
    title: 'Assign materials' },
  { id: 'solve-operating', step: 'solve', target: 'solve-operating', solveSection: 'operating', label: 'Operating point',
    title: 'Review the operating point' },
  { id: 'solve-analysis', step: 'solve', target: 'solve-analysis', solveSection: 'analysis', label: 'Analysis',
    title: 'Choose your analyses' },
  { id: 'solve-plan', step: 'solve', target: 'solve-plan', solveSection: 'plan', label: 'Accuracy plan',
    title: 'Pick a solve plan' },
  { id: 'solve-run', step: 'solve', target: 'solve-run', label: 'Run',
    title: 'Run the analysis' },
  { id: 'report', step: 'solve', target: 'open-report', label: 'Results',
    title: 'Solved — open the report' },
];

interface PublicGuidedSetupProps {
  activeStep: GuidedWorkflowStep;
  activeDesignSection: PublicParameterSection | null;
  topology: MotorConfig['topology'];
  resultReady: boolean;
  meshReady: boolean;
  busy: boolean;
  onWorkflowStepChange: (step: GuidedWorkflowStep) => void;
  onDesignSectionChange: (section: PublicParameterSection | null) => void;
  onSolveSectionChange: (section: SolveSetupSection | null) => void;
  onAcceptDesignSection: (section: PublicParameterSection) => void;
  onGenerateMesh: () => void;
  onStartSolve: () => void;
  onExit: (completed: boolean) => void;
}

export function PublicGuidedSetup({ activeStep, activeDesignSection, topology, resultReady, meshReady, busy,
  onWorkflowStepChange, onDesignSectionChange, onSolveSectionChange, onAcceptDesignSection,
  onGenerateMesh, onStartSolve, onExit }: PublicGuidedSetupProps) {
  const entry = useContext(NewDesignEntryContext);
  const progress = useContext(GuidedDesignProgressContext);
  const [currentId, setCurrentId] = useState('arrangement');
  const [reviewed, setReviewed] = useState<string[]>([]);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const priorChoices = useRef({ layout: entry?.layout, topology: entry?.topology, ready: entry?.ready });
  const stops = useMemo(() => PUBLIC_GUIDED_STOPS.filter((stop) => stop.id !== 'ipm-layout' || topology === 'IPM'), [topology]);
  const index = Math.max(0, stops.findIndex((stop) => stop.id === currentId));
  const stop = stops[index];

  const completed = useCallback((item: GuidedStop): boolean => {
    if (item.id === 'arrangement') return Boolean(entry?.layout);
    if (item.id === 'topology') return Boolean(entry?.topology);
    if (item.id === 'ipm-layout') return Boolean(entry && hasEntry(entry, 'topology', 'IPM rotor layout'));
    if (item.section) return Boolean(entry && entrySectionComplete(entry, item.section));
    if (item.id === 'solve-run' || item.id === 'report') return resultReady;
    return reviewed.includes(item.id);
  }, [entry, resultReady, reviewed]);
  const canVisit = (nextIndex: number) => stops.slice(0, nextIndex).every(completed)
    && (stops[nextIndex].step !== 'solve' || progress.complete);
  const ready = stop.step === 'design'
    ? completed(stop) && !progress.blocked && (stop.id !== 'materials' || progress.complete)
    : stop.id === 'report' ? resultReady : stop.id === 'solve-run' ? meshReady && !progress.blocked : true;

  const showStop = useCallback((id: string) => {
    let item = stops.find((candidate) => candidate.id === id);
    if (!item) return;
    if (item.step === 'solve' && activeStep !== 'solve') item = stops.find((candidate) => candidate.id === 'solve-operating')!;
    setCurrentId(item.id);
    onDesignSectionChange(item.section ?? null);
    onSolveSectionChange(item.solveSection ?? null);
    if (item.step !== activeStep) onWorkflowStepChange(item.step);
  }, [activeStep, onDesignSectionChange, onSolveSectionChange, onWorkflowStepChange, stops]);

  // The guide stays mounted in the entry context; only its normal-flow right
  // panel host changes between Design and Solve. There is no viewport overlay.
  useLayoutEffect(() => {
    setHost(document.querySelector<HTMLElement>('[data-guide="guided-setup-panel"]'));
  }, [activeStep]);

  useEffect(() => {
    if (activeStep === 'report') { onExit(true); return; }
    if (stop.step !== activeStep) {
      const first = stops.find((item) => item.step === activeStep);
      if (first) showStop(first.id);
    }
  }, [activeStep, onExit, showStop, stop.step, stops]);

  // Follow actual choices, without auto-advancing again when Back reviews them.
  useEffect(() => {
    const previous = priorChoices.current;
    priorChoices.current = { layout: entry?.layout, topology: entry?.topology, ready: entry?.ready };
    if (activeStep !== 'design') return;
    if (entry?.layout && entry.layout !== previous.layout) { setReviewed([]); showStop('topology'); }
    else if (entry?.topology && entry.topology !== previous.topology) { setReviewed([]); showStop(entry.topology === 'IPM' ? 'ipm-layout' : 'stator'); }
    else if (entry?.ready && !previous.ready) showStop('stator');
  }, [activeStep, entry?.layout, entry?.topology, entry?.ready, showStop]);

  // Sidebar Continue Setup and completed-section visits use the same guide.
  useEffect(() => {
    if (activeStep !== 'design' || !activeDesignSection) return;
    const nextIndex = stops.findIndex((item) => item.section === activeDesignSection);
    if (nextIndex >= 0 && nextIndex !== index && stops.slice(0, nextIndex).every(completed)) setCurrentId(stops[nextIndex].id);
  }, [activeDesignSection, activeStep, completed, index, stops]);

  useEffect(() => {
    if (stop.id === 'solve-run' && resultReady) showStop('report');
  }, [resultReady, showStop, stop.id]);

  const handleNext = () => {
    if (!ready || busy) return;
    if (stop.id === 'solve-run') { if (resultReady) showStop('report'); else onStartSolve(); return; }
    if (stop.id === 'report') { onWorkflowStepChange('report'); return; }
    if (stop.section) onAcceptDesignSection(stop.section);
    if (stop.step === 'solve') setReviewed((current) => current.includes(stop.id) ? current : [...current, stop.id]);
    if (stop.id === 'solve-plan' && !meshReady) onGenerateMesh();
    const nextStop = stops[index + 1];
    if (nextStop) showStop(nextStop.id);
  };

  if (!host) return null;
  return createPortal(
    <aside className="public-guided-coach" role="region" aria-label="Guided motor setup">
      <div className="public-guided-card">
        <div className="public-guided-progress"><span className="public-section-kicker">Guided setup</span><span>Step {index + 1} of {stops.length}</span></div>
        <h3 className="public-visually-hidden" aria-live="polite">{stop.title}</h3>
        <nav className="public-guided-steps" aria-label="Guided setup steps">
          {stops.map((item, itemIndex) => <button key={item.id} type="button"
            aria-current={item.id === stop.id ? 'step' : undefined}
            className={item.id === stop.id ? 'is-current' : completed(item) ? 'is-complete' : ''}
            disabled={busy || item.id !== stop.id && !canVisit(itemIndex)}
            onClick={() => showStop(item.id)}>
            <span aria-hidden="true">{completed(item) && item.id !== stop.id ? '✓' : itemIndex + 1}</span>{item.label}
          </button>)}
        </nav>
        <div className="public-guided-actions">
          <button type="button" className="public-guided-exit" onClick={() => onExit(false)}>Exit guided setup</button>
          <div className="public-guided-nav">
            {index > 0 && stops[index - 1].step === stop.step && <button type="button" disabled={busy} onClick={() => showStop(stops[index - 1].id)}>Back</button>}
            <button type="button" className="public-guided-next" disabled={busy || !ready} onClick={handleNext}>Next</button>
          </div>
        </div>
      </div>
    </aside>, host,
  );
}
