import React from 'react';
import type {
  LearningLessonHeaderProgress,
  LearningLessonStage,
} from './lessonStage';
import {
  LessonDock,
  LessonDockGroup,
  LessonDockToggle,
  LessonGoal,
  LessonLab,
  LessonLabCanvas,
  LessonLabPanel,
  LessonLabStage,
  LessonLabViewport,
  LessonLink,
  LessonNextStep,
  LessonSegmented,
  LessonTerms,
} from './lab/LessonLab';
import type { LessonTerm } from './lab/LessonLab';
import { LinearMotorCapstone3D } from './LinearMotorCapstone3D';
import { MeshViewer } from './MeshViewer';
import type { MeshViewerPointLabel } from './MeshViewer';
import type { LinearMotorCapstoneFieldData } from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { useLearningProgress } from './useLearningProgress';
import { oneOf, useLessonSessionState } from './lessonSession';
import './linear-motor-capstone.css';

interface ChapterOneLinearMotorCapstoneProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  /** Passed by the host page to every lesson. The capstone reports its stage but does not read it. */
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type CapstonePhase = 'build' | 'move' | 'strengthen' | 'reveal' | 'complete';
type ViewMode = '2d' | '3d';
type GoalPhase = Exclude<CapstonePhase, 'complete'>;

const MAGNET_X = [190, 370, 550, 730] as const;
const WINDING_SIGNS = [1, -1, 1, -1] as const;
const LESSON_ID = 'review-fields';
const FORCE_TARGET_N = 0.25;
const PITCH_PRESETS = [
  { id: '12', label: 'Tight' },
  { id: '18', label: 'Aligned' },
  { id: '22', label: 'Wide' },
] as const;

/** One line under each goal saying what to do about it. */
const GOAL_DETAILS: Record<GoalPhase, string> = {
  build: 'Flip magnets or change the conductor pitch, then test the track.',
  move: 'Pick a current direction, then let the solver work out the force.',
  strengthen: 'Change the coil current and the airgap. The warning zone starts at 90% saturation.',
  reveal: 'Look at it in 2D and 3D, then run the actuator.',
};

// The vocabulary of the capstone, kept beside the measurements.
const TERMS: readonly LessonTerm[] = [
  { term: 'Back iron', definition: 'The steel plate under the magnets. It carries the flux from one magnet to the next. Here it is electrical steel (grade M350-50A).' },
  { term: 'Airgap', definition: 'The space between the magnets and the coil, in millimetres (mm). A smaller gap puts a stronger field on the coil.' },
  { term: 'Flux density, |B|', definition: 'How strong the magnetic field is at one spot, in tesla (T).' },
  { term: 'Coil current', definition: 'The current in the winding, in amperes (A). A dot means it flows toward you, a cross means away from you. Changing the sign reverses it in every section.' },
  { term: 'Conductor pitch', definition: 'The distance between neighbouring active sections, in mm. The active sections are the four straight parts of the coil that sit over the magnets.' },
  { term: 'Useful field', definition: 'How much of the push on the four active sections adds up instead of cancelling. 100% means all four push the same way.' },
  { term: 'Net force', definition: 'The sum of the forces on all four active sections, in newtons (N). 1 N = 1000 mN.' },
  { term: 'Saturation', definition: 'How close the back iron is to the most flux it can carry, in percent. Past 90%, extra current buys little extra force.' },
];

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function signOf(value: number): -1 | 0 | 1 {
  if (Math.abs(value) < 0.001) return 0;
  return value > 0 ? 1 : -1;
}

function directionLabel(value: number) {
  return value > 0 ? 'Right' : value < 0 ? 'Left' : 'No motion';
}

function formatForce(value: number) {
  const magnitude = Math.abs(value);
  return magnitude < 1
    ? `${Math.round(magnitude * 1000)} mN`
    : `${magnitude.toFixed(2)} N`;
}

function windingCentersMm(spacingMm: number) {
  return [-1.5, -0.5, 0.5, 1.5].map((factor) => factor * spacingMm);
}

function solvedForceX(data: LinearMotorCapstoneFieldData | null) {
  return data?.net_force_x_n ?? data?.metrics?.wire_force_x_n ?? null;
}

function LinearMotor2D({
  currentSign,
  energized,
  forceDirection,
  magnetOrientations,
  windingSpacingMm,
  onFlipMagnet,
  running,
}: {
  currentSign: 1 | -1;
  energized: boolean;
  forceDirection: -1 | 0 | 1;
  magnetOrientations: readonly number[];
  windingSpacingMm: number;
  onFlipMagnet: (index: number) => void;
  running: boolean;
}) {
  const motionX = running && forceDirection !== 0 ? forceDirection * 54 : 0;
  const windingX = windingCentersMm(windingSpacingMm).map((xMm) => 460 + xMm * 10);
  const coilLeft = (windingX[0] ?? 190) - 42;
  const coilRight = (windingX[3] ?? 730) + 42;

  return (
    <svg
      className="linear-capstone-diagram"
      viewBox="0 0 1100 620"
      role="img"
      aria-label={`Top-down teaching view of a configurable linear motor. The carriage is ${directionLabel(forceDirection).toLowerCase()}.`}
    >
      <defs>
        <marker id="linearCapstoneForceArrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" className="linear-capstone-force-arrowhead" />
        </marker>
        <filter id="linearCapstoneGlow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="8" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      <text x="550" y="48" className="linear-capstone-stage-kicker">CONFIGURE THE TRACK. LET THE FIELD ANSWER.</text>
      <rect x="112" y="356" width="776" height="120" rx="18" className="linear-capstone-back-iron" />
      <rect x="88" y="494" width="824" height="22" rx="11" className="linear-capstone-rail" />

      {magnetOrientations.map((orientation, index) => {
        const x = MAGNET_X[index] ?? 0;
        const topNorth = orientation > 0;
        return (
          <g
            key={x}
            className="linear-capstone-magnet-slot"
            role="button"
            tabIndex={0}
            aria-label={`Flip magnet ${index + 1}. Its upward-facing pole is ${topNorth ? 'north' : 'south'}.`}
            onClick={() => onFlipMagnet(index)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onFlipMagnet(index);
              }
            }}
          >
            <rect x={x - 64} y="344" width="128" height="126" rx="10" className="linear-capstone-magnet-frame" />
            <rect x={x - 58} y="350" width="116" height="58" rx="6" className={topNorth ? 'is-north' : 'is-south'} />
            <rect x={x - 58} y="408" width="116" height="56" rx="6" className={topNorth ? 'is-south' : 'is-north'} />
            <text x={x} y="389" className="linear-capstone-pole-label">{topNorth ? 'N' : 'S'}</text>
            <text x={x} y="449" className="linear-capstone-pole-label">{topNorth ? 'S' : 'N'}</text>
            <text x={x} y="548" className="linear-capstone-flip-label">FLIP</text>
          </g>
        );
      })}

      <g
        className={`linear-capstone-carriage${running ? ' is-running' : ''}`}
        style={{ transform: `translateX(${motionX}px)` }}
      >
        <rect x="112" y="116" width="776" height="150" rx="28" className="linear-capstone-carriage-body" />
        <path d={`M${coilLeft} 150 H${coilRight} V232 H${coilLeft} Z`} className="linear-capstone-coil" />
        <text x="500" y="106" className="linear-capstone-carriage-title">MOVING COIL CARRIAGE</text>

        {windingX.map((x, index) => {
          const signedCurrent = WINDING_SIGNS[index] * currentSign;
          const localForce = magnetOrientations[index] * signedCurrent;
          return (
            <g key={x}>
              <circle cx={x} cy="191" r="27" className="linear-capstone-conductor" />
              {signedCurrent > 0 ? (
                <circle cx={x} cy="191" r="7" className="linear-capstone-current-glyph" />
              ) : (
                <g className="linear-capstone-current-glyph">
                  <line x1={x - 8} y1="183" x2={x + 8} y2="199" />
                  <line x1={x + 8} y1="183" x2={x - 8} y2="199" />
                </g>
              )}
              {energized ? (
                <line
                  x1={x + (localForce > 0 ? 34 : -34)}
                  y1="191"
                  x2={x + (localForce > 0 ? 76 : -76)}
                  y2="191"
                  className={`linear-capstone-local-force${localForce > 0 ? ' is-right' : ' is-left'}`}
                  markerEnd="url(#linearCapstoneForceArrow)"
                />
              ) : null}
            </g>
          );
        })}
      </g>

      {energized && forceDirection !== 0 ? (
        <g className="linear-capstone-net-force" filter="url(#linearCapstoneGlow)">
          <line
            x1={forceDirection > 0 ? 914 : 86}
            y1="191"
            x2={forceDirection > 0 ? 1030 : -30}
            y2="191"
            markerEnd="url(#linearCapstoneForceArrow)"
          />
          <text x={forceDirection > 0 ? 972 : 28} y="153">NET FORCE</text>
        </g>
      ) : null}

      <text x="550" y="595" className="linear-capstone-stage-note">
        Flip magnets or change the conductor pitch. Current directions stay fixed by the closed coil path.
      </text>
    </svg>
  );
}

export const ChapterOneLinearMotorCapstone: React.FC<ChapterOneLinearMotorCapstoneProps> = ({
  onBackToCatalog,
  onBackHome,
  onStageChange,
  onHeaderProgressChange,
}) => {
  const solveClient = useLessonSolveClient();
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  // The step and the design choices are kept for the tab, so a reload or a
  // trip to the catalog comes back to the same machine. The solved field is
  // not kept: the step's main button solves it again.
  const [phase, setPhase] = useLessonSessionState<CapstonePhase>(
    LESSON_ID, 'phase', 'build', oneOf<CapstonePhase>(['build', 'move', 'strengthen', 'reveal', 'complete']),
  );
  const [viewMode, setViewMode] = React.useState<ViewMode>('2d');
  const [showFieldLines, setShowFieldLines] = React.useState(true);
  const [showFluxDensity, setShowFluxDensity] = React.useState(false);
  const [showMesh, setShowMesh] = React.useState(false);
  const [magnetOrientations, setMagnetOrientations] = useLessonSessionState<number[]>(
    LESSON_ID, 'magnetOrientations', [1, 1, 1, 1],
    (value) => Array.isArray(value) && value.length === 4 && value.every((item) => item === 1 || item === -1),
  );
  const [currentSign, setCurrentSign] = useLessonSessionState<1 | -1>(
    LESSON_ID, 'currentSign', 1, (value) => value === 1 || value === -1,
  );
  const [currentA, setCurrentA] = useLessonSessionState(
    LESSON_ID, 'currentA', 8, (value) => typeof value === 'number' && value >= 4 && value <= 12,
  );
  const [gapMm, setGapMm] = useLessonSessionState(
    LESSON_ID, 'gapMm', 8, (value) => typeof value === 'number' && value >= 2 && value <= 10,
  );
  const [windingSpacingMm, setWindingSpacingMm] = useLessonSessionState(
    LESSON_ID, 'windingSpacingMm', 18, (value) => value === 12 || value === 18 || value === 22,
  );
  const [trackTested, setTrackTested] = React.useState(false);
  const [energized, setEnergized] = React.useState(false);
  const [runOnce, setRunOnce] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [inspectorFlash, setInspectorFlash] = React.useState(false);
  const inspectorFlashTimerRef = React.useRef<number | null>(null);
  const inspectorRef = React.useRef<HTMLElement | null>(null);
  const currentDirectionRef = React.useRef<HTMLElement | null>(null);
  // The mesh viewer draws its zoom buttons into this element in the dock.
  const [zoomSlot, setZoomSlot] = React.useState<HTMLSpanElement | null>(null);
  const [fieldData, setFieldData] = React.useState<LinearMotorCapstoneFieldData | null>(null);
  const [fieldStatus, setFieldStatus] = React.useState<'idle' | 'solving' | 'solved' | 'error'>('idle');
  const [fieldError, setFieldError] = React.useState<string | null>(null);
  const solveRequestId = React.useRef(0);

  const alignment = React.useMemo(
    () => magnetOrientations.reduce(
      (sum, orientation, index) => sum + orientation * (WINDING_SIGNS[index] ?? 1),
      0,
    ) / WINDING_SIGNS.length,
    [magnetOrientations],
  );
  const coherence = Math.abs(alignment);
  const measuredForceX = solvedForceX(fieldData);
  const signedForceN = energized && measuredForceX !== null ? measuredForceX : 0;
  const forceDirection = signOf(signedForceN);
  const saturationPercent = Math.round(clamp(24 + currentA * 3.8 + Math.max(0, 4 - gapMm) * 10, 0, 100));
  const trackReady = coherence >= 0.74;
  const movesRight = energized && fieldStatus === 'solved' && forceDirection > 0;
  const strengthReady = movesRight && signedForceN >= FORCE_TARGET_N && saturationPercent < 90;
  const complete = isLessonComplete(LESSON_ID);
  const conductorLabels = React.useMemo<MeshViewerPointLabel[]>(() => (
    windingCentersMm(windingSpacingMm).map((xMm, index) => {
      const windingSign = WINDING_SIGNS[index] ?? 1;
      const signedCurrentA = (fieldData?.current_a ?? 0) * windingSign;
      const plannedDirection = currentSign * windingSign;
      const shownDirection = Math.abs(signedCurrentA) < 0.01 ? plannedDirection : signedCurrentA;
      const shownCurrentA = Math.abs(signedCurrentA);
      return {
        xMm,
        yMm: fieldData?.wire_center_y_mm ?? gapMm + 3,
        label: shownDirection > 0 ? '•' : '×',
        detailLabel: `${Number.isInteger(shownCurrentA) ? shownCurrentA : shownCurrentA.toFixed(1)} A`,
        tone: 'neutral',
        scale: 0.84,
        textScale: 1.65,
      } as MeshViewerPointLabel;
    })
  ), [currentSign, fieldData, gapMm, windingSpacingMm]);

  const invalidateField = React.useCallback(() => {
    solveRequestId.current += 1;
    setFieldData(null);
    setFieldStatus('idle');
    setFieldError(null);
  }, []);

  const solveField = React.useCallback(async (requestedCurrentA: number) => {
    const requestId = solveRequestId.current + 1;
    solveRequestId.current = requestId;
    setFieldStatus('solving');
    setFieldError(null);
    try {
      const data = await solveClient.fetchLinearMotorCapstoneSolve(
        requestedCurrentA,
        gapMm,
        magnetOrientations,
        windingSpacingMm,
      );
      if (solveRequestId.current !== requestId) return null;
      setFieldData(data);
      setFieldStatus('solved');
      return data;
    } catch (error) {
      if (solveRequestId.current !== requestId) return null;
      setFieldStatus('error');
      setFieldError(error instanceof Error ? error.message : 'Magneto2D solve failed.');
      return null;
    }
  }, [gapMm, magnetOrientations, solveClient, windingSpacingMm]);

  const steps = React.useMemo(() => [
    { id: 'build', label: 'Build', complete: phase !== 'build', available: true },
    // A finished capstone reopens with every step available.
    { id: 'move', label: 'Make it move', complete: ['strengthen', 'reveal', 'complete'].includes(phase), available: complete || phase !== 'build' },
    { id: 'strengthen', label: 'Make it stronger', complete: ['reveal', 'complete'].includes(phase), available: complete || ['strengthen', 'reveal', 'complete'].includes(phase) },
    { id: 'reveal', label: 'See it work', complete: phase === 'complete', available: complete || ['reveal', 'complete'].includes(phase) },
  ], [complete, phase]);

  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    eyebrow: 'Chapter 1 capstone',
    lessonNumber: 5,
    lessonCount: 5,
    title: 'Make It Move',
    currentStepId: phase === 'complete' ? 'reveal' : phase,
    steps,
    onStepSelect: (stepId) => {
      const target = steps.find((step) => step.id === stepId);
      if (!target?.available) return;
      setPhase(stepId as Exclude<CapstonePhase, 'complete'>);
      if (stepId === 'reveal') {
        setViewMode('3d');
        // Opened without a solved field (a finished capstone, reopened): solve
        // the machine as it is set, so the result shown is a measured one.
        if (!fieldData && fieldStatus !== 'solving') {
          void solveField(currentA * currentSign).then((solved) => {
            if (solved) setEnergized(true);
          });
        }
      }
    },
  }), [currentA, currentSign, fieldData, fieldStatus, phase, solveField, steps]);

  // The last two steps show a solved, energized machine. Reopened after a
  // reload there is no solved field yet, so come back one step earlier: its
  // main button solves the machine and moves on again.
  const resumeChecked = React.useRef(false);
  React.useEffect(() => {
    if (resumeChecked.current) return;
    resumeChecked.current = true;
    if (phase === 'reveal' || phase === 'complete') setPhase('strengthen');
  }, [phase, setPhase]);

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
    return () => onHeaderProgressChange?.(null);
  }, [headerProgress, onHeaderProgressChange]);

  React.useEffect(() => {
    onStageChange?.(phase === 'build' ? 'design' : 'solve');
  }, [onStageChange, phase]);

  React.useEffect(() => {
    if (!running) return undefined;
    const timeout = window.setTimeout(() => {
      setRunning(false);
      setRunOnce(true);
    }, 2600);
    return () => window.clearTimeout(timeout);
  }, [running]);

  React.useEffect(() => () => {
    if (inspectorFlashTimerRef.current !== null) window.clearTimeout(inspectorFlashTimerRef.current);
  }, []);

  /** Ring the Inspect card for a moment so the eye goes to the result. */
  const flashInspector = () => {
    inspectorRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    setInspectorFlash(true);
    if (inspectorFlashTimerRef.current !== null) window.clearTimeout(inspectorFlashTimerRef.current);
    inspectorFlashTimerRef.current = window.setTimeout(() => setInspectorFlash(false), 1_600);
  };

  const flipMagnet = (index: number) => {
    setMagnetOrientations((current) => current.map((orientation, itemIndex) => (
      itemIndex === index ? -orientation : orientation
    )));
    setTrackTested(false);
    setEnergized(false);
    setRunOnce(false);
    invalidateField();
  };

  const selectCurrentSign = (next: 1 | -1) => {
    setCurrentSign(next);
    setEnergized(false);
    setRunOnce(false);
    invalidateField();
  };

  const selectWindingSpacing = (next: number) => {
    setWindingSpacingMm(next);
    setTrackTested(false);
    setEnergized(false);
    setRunOnce(false);
    invalidateField();
  };

  const primaryAction = async () => {
    if (phase === 'build') {
      const solved = await solveField(0);
      if (!solved) return;
      setTrackTested(true);
      if (trackReady) setPhase('move');
      return;
    }
    if (phase === 'move') {
      if (!energized) {
        const solved = await solveField(currentA * currentSign);
        if (!solved) return;
        setEnergized(true);
        return;
      }
      if (movesRight) {
        setPhase('strengthen');
        return;
      }
      // The carriage went the wrong way. Take the student to the one
      // electrical choice this step offers: the direction they have not tried.
      const card = currentDirectionRef.current;
      card?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      card?.querySelector<HTMLButtonElement>('button[aria-pressed="false"]')?.focus();
      return;
    }
    if (phase === 'strengthen') {
      const solved = await solveField(currentA * currentSign);
      if (!solved) return;
      setEnergized(true);
      const solvedNetForceX = solvedForceX(solved) ?? 0;
      const solvedStrengthReady = solvedNetForceX >= FORCE_TARGET_N && saturationPercent < 90;
      if (solvedStrengthReady) {
        setPhase('reveal');
        setViewMode('3d');
      }
      return;
    }
    if (phase === 'reveal') {
      if (!runOnce) {
        setRunning(true);
        return;
      }
      setPhase('complete');
      setLessonComplete(LESSON_ID, true);
      // The chapter result has just appeared in the Inspect card.
      flashInspector();
    }
  };

  const primaryLabel = fieldStatus === 'solving'
    ? phase === 'build' ? 'Solving magnet field…' : 'Solving magnets + winding…'
    : phase === 'build'
    ? 'Test magnetic track'
    : phase === 'move'
      ? !energized
        ? 'Energize carriage'
        : movesRight
          ? 'Make it stronger'
          : 'Adjust the design'
      : phase === 'strengthen'
        ? strengthReady
          ? 'Reveal in 3D'
          : 'Test performance'
        : phase === 'reveal'
          ? runOnce
            ? 'Finish chapter'
            : running
              ? 'Running…'
              : 'Run actuator'
          : 'Chapter complete';

  const insight = phase === 'build'
    ? trackTested
      ? trackReady
        ? 'The active sections now add instead of cancelling.'
        : 'The carriage sees competing forces. Change the track and test again.'
      : 'Arrange the magnetic track. The preview will not reveal a recipe.'
    : phase === 'move'
      ? energized
        ? movesRight
          ? 'It moves. Now find out how much stronger it can become.'
          : 'The carriage moved the wrong way. Change one electrical choice.'
        : 'Choose a current direction, then energize the carriage.'
      : phase === 'strengthen'
        ? strengthReady
          ? 'Target reached without driving the iron into the warning zone.'
          : `Reach ${formatForce(FORCE_TARGET_N)} to the right while keeping saturation below 90%.`
        : phase === 'reveal'
          ? 'The cross-section is now a physical machine. Run what you built.'
          : 'Field became force. Force became motion.';

  const goalPhase: GoalPhase = phase === 'complete' ? 'reveal' : phase;
  const stepNumber = steps.findIndex((step) => step.id === goalPhase) + 1;
  const stepLabel = steps[stepNumber - 1]?.label ?? '';
  const solvedSources = fieldData
    ? Math.abs(fieldData.current_a) < 0.01 ? 'magnets only' : 'magnets + winding'
    : null;

  // The canvas controls, in the same dock as the motor workspace. Before the
  // first solve they are shown greyed out, so the canvas keeps its size. The
  // 3D machine draws the solved field too, but has no mesh to show.
  const unsolved = !fieldData;
  const viewDock = (
    <LessonDock
      tabs={[
        { id: '2d', label: '2D', title: 'The cross-section the solver works on' },
        { id: '3d', label: '3D', title: 'The same machine drawn in 3D' },
      ]}
      tab={viewMode}
      onTab={setViewMode}
      end={unsolved ? 'Solve to see the field' : <span ref={setZoomSlot} />}
    >
      <LessonDockGroup label="Show">
        <LessonDockToggle
          pressed={showFieldLines}
          onChange={setShowFieldLines}
          disabled={unsolved}
          title="Lines that follow the direction of the field"
        >
          Field lines
        </LessonDockToggle>
        <LessonDockToggle
          pressed={showFluxDensity}
          onChange={setShowFluxDensity}
          disabled={unsolved}
          title="Colour by field strength, |B|"
        >
          Flux density
        </LessonDockToggle>
        <LessonDockToggle
          pressed={showMesh}
          onChange={setShowMesh}
          disabled={unsolved || viewMode === '3d'}
          title={viewMode === '3d' ? 'Switch to the 2D view to see the mesh' : 'The triangles the solver divides the space into'}
        >
          Mesh
        </LessonDockToggle>
      </LessonDockGroup>
    </LessonDock>
  );

  const inspectPanel = (
    <LessonLabPanel
      ref={inspectorRef}
      side="inspect"
      kicker="Inspect"
      title={phase === 'complete' ? 'You made a motor move.' : 'What the machine is doing'}
      summary={phase === 'complete' ? 'Field became force. Force became motion.' : undefined}
      label="Capstone design evidence"
      flash={inspectorFlash}
      scrollTopKey={`${phase}-${fieldStatus}`}
    >
      {fieldStatus === 'solving' ? (
        <p className="lesson-lab-note" role="status">
          Running Magneto2D… Meshing magnets, electrical steel back iron, and four winding sections.
        </p>
      ) : null}
      <section className="linear-capstone-evidence-card" aria-label="Measurements">
        <div><span>Carriage motion</span><strong>{directionLabel(forceDirection)}</strong></div>
        {/* The share stays hidden until the track is tested, so flipping
            magnets does not give the answer away. */}
        <div><span>Useful field</span><strong>{trackTested ? `${Math.round(coherence * 100)}%` : 'Not tested'}</strong></div>
        <div><span>Net force</span><strong>{energized && measuredForceX !== null ? `${forceDirection > 0 ? '→' : forceDirection < 0 ? '←' : ''} ${formatForce(signedForceN)}` : 'Off'}</strong></div>
        <div className={saturationPercent >= 90 ? 'is-warning' : ''}><span>Saturation</span><strong>{saturationPercent}%</strong></div>
      </section>
      <div className={`linear-capstone-target-card${strengthReady ? ' is-complete' : ''}`}>
        <span>{strengthReady ? '✓' : '○'}</span>
        <div><small>Design target</small><strong>{formatForce(FORCE_TARGET_N)} right · saturation below 90%</strong></div>
      </div>
      {phase === 'complete' || complete ? (
        <section className="linear-capstone-complete-card">
          <small>Your chapter result</small>
          <strong>{formatForce(signedForceN)} to the {forceDirection > 0 ? 'right' : forceDirection < 0 ? 'left' : 'stationary'}</strong>
          <p>You created a magnetic path, drove current through a conductor, managed the airgap, avoided the saturation warning, and turned field into motion.</p>
        </section>
      ) : null}
      <section className="lesson-lab-card" aria-label="About the winding">
        <h3>The winding</h3>
        <p className="lesson-lab-note">The four active sections move symmetrically while the winding remains one closed circuit.</p>
      </section>
      <LessonTerms terms={TERMS} />
    </LessonLabPanel>
  );

  return (
    <LessonLab className="linear-capstone-lab">
      {inspectPanel}
      <LessonLabStage>
        <LessonLabCanvas className="linear-capstone-viewer">
          <LessonLabViewport
            label={solvedSources ? `Linear actuator · ${solvedSources}` : 'Linear actuator · moving-coil track'}
            hint={solvedSources ? `${gapMm.toFixed(1)} mm airgap` : 'Not solved yet'}
            className={viewMode === '2d' && !fieldData ? 'is-centered' : ''}
          >
            {viewMode === '3d' ? (
              <LinearMotorCapstone3D
                currentSign={currentSign}
                forceDirection={forceDirection}
                netForceN={measuredForceX}
                gapMm={gapMm}
                windingSpacingMm={windingSpacingMm}
                magnetOrientations={magnetOrientations}
                running={running}
                showFluxLines={showFieldLines}
                showBMap={showFluxDensity}
                fieldData={fieldData}
              />
            ) : fieldData ? (
              <div className="linear-capstone-solver-view">
                <MeshViewer
                  meshData={fieldData}
                  embedded
                  compactEmbedded
                  toolbarMode="zoom-only"
                  zoomControlsSlot={zoomSlot}
                  showMeshEdges={showMesh}
                  showFieldIntensity={showFluxDensity}
                  smoothFieldIntensity
                  fieldLinesVisible={showFieldLines}
                  animateFieldArrows={showFieldLines}
                  viewportPanEnabled={false}
                  pointLabels={conductorLabels}
                />
                {energized && measuredForceX !== null && forceDirection !== 0 ? (
                  <div className={`linear-capstone-force-result${forceDirection > 0 ? ' is-right' : ' is-left'}`} role="status" aria-live="polite">
                    <span>Magneto2D net force</span>
                    <strong><b aria-hidden="true">{forceDirection > 0 ? '⟶' : '⟵'}</b>{formatForce(measuredForceX)}</strong>
                    <small>∫ winding J × B dV</small>
                  </div>
                ) : null}
              </div>
            ) : (
              <LinearMotor2D
                currentSign={currentSign}
                energized={energized}
                forceDirection={forceDirection}
                magnetOrientations={magnetOrientations}
                windingSpacingMm={windingSpacingMm}
                onFlipMagnet={flipMagnet}
                running={running}
              />
            )}
          </LessonLabViewport>
          {viewDock}
        </LessonLabCanvas>
      </LessonLabStage>
      <LessonLabPanel
        side="do"
        kicker={`Capstone · ${stepLabel}`}
        title={phase === 'build' ? 'Build the track' : phase === 'move' ? 'Make it move' : phase === 'strengthen' ? 'Make it stronger' : 'Your actuator'}
        label="Linear motor design controls"
        footer={(
          <LessonNextStep hint={phase === 'complete' ? `${insight} Next: Give the Rotor Something to Chase.` : insight}>
            {phase !== 'complete' ? (
              <button
                type="button"
                className="learning-primary-button"
                disabled={running || fieldStatus === 'solving'}
                onClick={() => { void primaryAction(); }}
              >
                {primaryLabel}
              </button>
            ) : (
              <a className="learning-primary-button" href="/tutorials/lesson-6">Next lesson</a>
            )}
            <div className="lesson-lab-next-row">
              <LessonLink onClick={onBackToCatalog}>← All lessons</LessonLink>
              <LessonLink onClick={onBackHome}>Design start</LessonLink>
            </div>
          </LessonNextStep>
        )}
      >
        <LessonGoal
          step={stepNumber}
          total={steps.length}
          title={phase === 'build' ? 'Create a useful field across the carriage' : phase === 'move' ? 'Move the carriage to the right' : phase === 'strengthen' ? `Reach ${formatForce(FORCE_TARGET_N)} without the warning zone` : 'Watch the machine you built'}
          detail={GOAL_DETAILS[goalPhase]}
        />

        <section className="linear-capstone-control-card">
          <header><strong>Magnetic track</strong></header>
          <div className="linear-capstone-magnet-controls" role="group" aria-label="Flip track magnets">
            {magnetOrientations.map((orientation, index) => (
              <button type="button" key={index} onClick={() => flipMagnet(index)}>
                <span className={orientation > 0 ? 'is-north' : 'is-south'}>{orientation > 0 ? 'N' : 'S'}</span>
                <small>Magnet {index + 1}</small>
                <em>Flip</em>
              </button>
            ))}
          </div>
        </section>

        <section className="linear-capstone-control-card">
          <header><strong>Conductor pitch</strong><span>{windingSpacingMm.toFixed(0)} mm</span></header>
          <LessonSegmented
            stretch
            label="Conductor pitch"
            value={String(windingSpacingMm)}
            onChange={(id) => selectWindingSpacing(Number(id))}
            options={PITCH_PRESETS.map((preset) => ({ id: preset.id as string, label: preset.label, title: `${preset.id} mm` }))}
          />
        </section>

        {phase !== 'build' ? (
          <section ref={currentDirectionRef} className="linear-capstone-control-card">
            <header><strong>Coil current direction</strong></header>
            <LessonSegmented
              stretch
              label="Coil current direction"
              value={currentSign > 0 ? 'positive' : 'negative'}
              onChange={(id) => selectCurrentSign(id === 'positive' ? 1 : -1)}
              options={[
                { id: 'positive', label: `+${currentA} A` },
                { id: 'negative', label: `−${currentA} A` },
              ]}
            />
          </section>
        ) : null}

        {phase === 'strengthen' || phase === 'reveal' || phase === 'complete' ? (
          <section className="linear-capstone-control-card">
            <label htmlFor="linear-capstone-current"><span>Coil current</span><strong>{currentA} A</strong></label>
            <input id="linear-capstone-current" aria-label="Linear motor current" type="range" min="4" max="12" step="2" value={currentA} onChange={(event) => { setCurrentA(Number(event.target.value)); setEnergized(true); setRunOnce(false); invalidateField(); }} />
            <div className="linear-capstone-scale"><span>4 A</span><span>12 A</span></div>
            <label htmlFor="linear-capstone-gap"><span>Airgap</span><strong>{gapMm.toFixed(1)} mm</strong></label>
            <input id="linear-capstone-gap" aria-label="Linear motor airgap" type="range" min="2" max="10" step="0.5" value={gapMm} onChange={(event) => { setGapMm(Number(event.target.value)); setEnergized(true); setRunOnce(false); invalidateField(); }} />
            <div className="linear-capstone-scale"><span>2 mm</span><span>10 mm</span></div>
          </section>
        ) : null}

        <p className="lesson-lab-note">No configuration is suggested. The field and motion are the feedback.</p>
        {fieldError ? <p className="lesson-lab-error" role="alert">Field solve unavailable. {fieldError}</p> : null}
      </LessonLabPanel>
    </LessonLab>
  );
};
