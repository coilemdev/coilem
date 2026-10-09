import React from 'react';
import type {
  LearningLessonHeaderProgress,
  LearningLessonStage,
} from './lessonStage';
import { LinearMotorCapstone3D } from './LinearMotorCapstone3D';
import { MeshViewer } from './MeshViewer';
import type { MeshViewerPointLabel } from './MeshViewer';
import type { LinearMotorCapstoneFieldData } from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { useLearningProgress } from './useLearningProgress';
import './linear-motor-capstone.css';

interface ChapterOneLinearMotorCapstoneProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type CapstonePhase = 'build' | 'move' | 'strengthen' | 'reveal' | 'complete';
type ViewMode = '2d' | '3d';

const MAGNET_X = [190, 370, 550, 730] as const;
const WINDING_SIGNS = [1, -1, 1, -1] as const;
const FORCE_TARGET_N = 0.25;

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
        Flip magnets or change conductor spacing. Current directions stay fixed by the closed coil path.
      </text>
    </svg>
  );
}

export const ChapterOneLinearMotorCapstone: React.FC<ChapterOneLinearMotorCapstoneProps> = ({
  onBackToCatalog,
  onBackHome,
  stage = 'design',
  onStageChange,
  onHeaderProgressChange,
}) => {
  const solveClient = useLessonSolveClient();
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const [phase, setPhase] = React.useState<CapstonePhase>('build');
  const [viewMode, setViewMode] = React.useState<ViewMode>('2d');
  const [showFluxLines, setShowFluxLines] = React.useState(true);
  const [showBMap, setShowBMap] = React.useState(false);
  const [magnetOrientations, setMagnetOrientations] = React.useState<number[]>([1, 1, 1, 1]);
  const [currentSign, setCurrentSign] = React.useState<1 | -1>(1);
  const [currentA, setCurrentA] = React.useState(8);
  const [gapMm, setGapMm] = React.useState(8);
  const [windingSpacingMm, setWindingSpacingMm] = React.useState(18);
  const [trackTested, setTrackTested] = React.useState(false);
  const [energized, setEnergized] = React.useState(false);
  const [runOnce, setRunOnce] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [controlsOpen, setControlsOpen] = React.useState(true);
  const [inspectorOpen, setInspectorOpen] = React.useState(false);
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
  const complete = isLessonComplete('review-fields');
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
    { id: 'move', label: 'Make it move', complete: ['strengthen', 'reveal', 'complete'].includes(phase), available: phase !== 'build' },
    { id: 'strengthen', label: 'Make it stronger', complete: ['reveal', 'complete'].includes(phase), available: ['strengthen', 'reveal', 'complete'].includes(phase) },
    { id: 'reveal', label: 'See it work', complete: phase === 'complete', available: ['reveal', 'complete'].includes(phase) },
  ], [phase]);

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
      if (stepId === 'reveal') setViewMode('3d');
    },
  }), [phase, steps]);

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
      if (movesRight) setPhase('strengthen');
      else setControlsOpen(true);
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
        setControlsOpen(false);
      }
      return;
    }
    if (phase === 'reveal') {
      if (!runOnce) {
        setRunning(true);
        return;
      }
      setPhase('complete');
      setLessonComplete('review-fields', true);
      setInspectorOpen(true);
    }
  };

  const primaryLabel = fieldStatus === 'solving'
    ? phase === 'build' ? 'Solving PM field…' : 'Solving PM + winding…'
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

  return (
    <main className={`learning-shell learning-lesson-shell linear-capstone-shell is-${stage}-stage${controlsOpen ? ' is-controls-open' : ''}${inspectorOpen ? ' is-inspector-open' : ''}`}>
      <section className="learning-main-stage linear-capstone-main">
        <header className="mesh-viewer-header linear-capstone-visual-header">
          <div>
            <strong>Linear actuator · moving-coil track</strong>
            <span>{fieldStatus === 'solving'
              ? 'Magneto2D solving PM + winding sources'
              : fieldData
                ? `Magneto2D · ${Math.abs(fieldData.current_a) < 0.01 ? 'PM only' : 'PM + copper winding'} · ${gapMm.toFixed(1)} mm airgap`
                : phase === 'build' ? 'unpowered configuration · field not solved' : `${currentSign > 0 ? '+' : '−'}${currentA} A · ${gapMm.toFixed(1)} mm airgap · field not solved`}</span>
          </div>
          <div className="linear-capstone-display-controls">
            <div className="linear-capstone-field-toggle" role="group" aria-label="Field visualization">
              <button type="button" className={showFluxLines ? 'is-active' : ''} onClick={() => setShowFluxLines((visible) => !visible)} aria-pressed={showFluxLines}>
                <span className="is-line" aria-hidden="true" /> Flux lines
              </button>
              <button type="button" className={showBMap ? 'is-active' : ''} onClick={() => setShowBMap((visible) => !visible)} aria-pressed={showBMap}>
                <span className="is-density" aria-hidden="true" /> |B| map
              </button>
            </div>
            <div className="linear-capstone-view-toggle" role="group" aria-label="Capstone view">
              <button type="button" className={viewMode === '2d' ? 'is-active' : ''} onClick={() => setViewMode('2d')} aria-pressed={viewMode === '2d'}>▣ 2D build</button>
              <button type="button" className={viewMode === '3d' ? 'is-active' : ''} onClick={() => setViewMode('3d')} aria-pressed={viewMode === '3d'}>◇ 3D machine</button>
            </div>
          </div>
        </header>

        <div className="linear-capstone-canvas">
          {viewMode === '3d' ? (
            <LinearMotorCapstone3D
              currentSign={currentSign}
              forceDirection={forceDirection}
              netForceN={measuredForceX}
              gapMm={gapMm}
              windingSpacingMm={windingSpacingMm}
              magnetOrientations={magnetOrientations}
              running={running}
              showFluxLines={showFluxLines}
              showBMap={showBMap}
              fieldData={fieldData}
            />
          ) : fieldData ? (
            <div className="linear-capstone-solver-view">
              <MeshViewer
                meshData={fieldData}
                embedded
                compactEmbedded
                toolbarMode="zoom-only"
                toolbarLabel={`${Math.abs(fieldData.current_a) < 0.01 ? 'PM-only' : 'PM + winding'} Magneto2D field`}
                showMeshEdges={false}
                showFieldIntensity={showBMap}
                smoothFieldIntensity
                fieldLinesVisible={showFluxLines}
                animateFieldArrows={showFluxLines}
                viewportPanEnabled={false}
                fixedView
                pointLabels={conductorLabels}
              />
              <div className="linear-capstone-solver-key">
                <span>Magneto2D</span>
                <strong>{Math.abs(fieldData.current_a) < 0.01 ? 'Permanent magnets only' : 'Permanent magnets + copper self-field'}</strong>
              </div>
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
          {fieldStatus === 'solving' ? (
            <div className="linear-capstone-solving" role="status"><strong>Running Magneto2D…</strong><span>Meshing magnets, M350-50A back iron, and four winding sections.</span></div>
          ) : null}
          {fieldError ? (
            <div className="linear-capstone-solve-error" role="alert"><strong>Field solve unavailable</strong><span>{fieldError}</span></div>
          ) : null}
        </div>

        <nav className="linear-capstone-dock" aria-label="Capstone controls">
          <div className="linear-capstone-dock-copy">
            <span>{phase === 'complete' ? 'Chapter complete' : phase}</span>
            <strong>{insight}</strong>
          </div>
          <div className="linear-capstone-dock-actions">
            {phase !== 'complete' ? (
              <>
                <button type="button" className="linear-capstone-dock-button" aria-expanded={controlsOpen} onClick={() => { setControlsOpen((open) => !open); setInspectorOpen(false); }}>
                  {controlsOpen ? 'Done' : phase === 'build' ? 'Arrange track' : 'Adjust design'}
                </button>
                <button type="button" className="linear-capstone-dock-button" aria-expanded={inspectorOpen} onClick={() => { setInspectorOpen((open) => !open); setControlsOpen(false); }}>
                  Inspect design
                </button>
                <button type="button" className="learning-primary-button linear-capstone-dock-primary" disabled={running || fieldStatus === 'solving'} onClick={() => { void primaryAction(); }}>{primaryLabel}</button>
              </>
            ) : (
              <>
                <button type="button" className="linear-capstone-dock-button" onClick={onBackToCatalog}>All lessons</button>
                <a className="learning-primary-button linear-capstone-next" href="/tutorials/lesson-6">Continue: Give the Rotor Something to Chase</a>
              </>
            )}
          </div>
        </nav>
      </section>

      <aside className={`learning-control-panel linear-capstone-control-panel${controlsOpen ? ' is-open' : ''}`} aria-label="Linear motor design controls" aria-hidden={!controlsOpen}>
        <button type="button" className="linear-capstone-drawer-close" onClick={() => setControlsOpen(false)} aria-label="Close design controls">×</button>
        <div className="linear-capstone-panel-scroll">
          <p className="linear-capstone-panel-kicker">Chapter challenge · {phase}</p>
          <h2>{phase === 'build' ? 'Build the track' : phase === 'move' ? 'Make it move' : phase === 'strengthen' ? 'Make it stronger' : 'Your actuator'}</h2>
          <section className="linear-capstone-goal">
            <span>{phase === 'build' ? '1/4' : phase === 'move' ? '2/4' : phase === 'strengthen' ? '3/4' : '4/4'}</span>
            <div>
              <small>Current goal</small>
              <strong>{phase === 'build' ? 'Create a useful field across the carriage' : phase === 'move' ? 'Move the carriage to the right' : phase === 'strengthen' ? `Reach ${formatForce(FORCE_TARGET_N)} without the warning zone` : 'Watch the machine you built'}</strong>
            </div>
          </section>

          <section className="linear-capstone-control-card">
            <header><strong>Magnetic track</strong><span>{trackTested ? `${Math.round(coherence * 100)}% useful` : 'untested'}</span></header>
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
            <div className="linear-capstone-spacing-controls" role="group" aria-label="Conductor spacing">
              {[
                { value: 12, label: 'Tight' },
                { value: 18, label: 'Aligned' },
                { value: 22, label: 'Wide' },
              ].map((option) => (
                <button
                  type="button"
                  key={option.value}
                  className={windingSpacingMm === option.value ? 'is-active' : ''}
                  onClick={() => selectWindingSpacing(option.value)}
                >
                  <strong>{option.value} mm</strong>
                  <span>{option.label}</span>
                </button>
              ))}
            </div>
            <p className="linear-capstone-control-hint">The four active sections move symmetrically while the winding remains one closed circuit.</p>
          </section>

          {phase !== 'build' ? (
            <section className="linear-capstone-control-card">
              <header><strong>Coil current</strong><span>{currentSign > 0 ? '+' : '−'}{currentA} A</span></header>
              <div className="linear-capstone-current-buttons" role="group" aria-label="Coil current direction">
                <button type="button" className={currentSign > 0 ? 'is-active' : ''} onClick={() => selectCurrentSign(1)}>+{currentA} A</button>
                <button type="button" className={currentSign < 0 ? 'is-active' : ''} onClick={() => selectCurrentSign(-1)}>−{currentA} A</button>
              </div>
            </section>
          ) : null}

          {phase === 'strengthen' || phase === 'reveal' || phase === 'complete' ? (
            <section className="linear-capstone-control-card">
              <label htmlFor="linear-capstone-current"><span>Current</span><strong>{currentA} A</strong></label>
              <input id="linear-capstone-current" aria-label="Linear motor current" type="range" min="4" max="12" step="2" value={currentA} onChange={(event) => { setCurrentA(Number(event.target.value)); setEnergized(true); setRunOnce(false); invalidateField(); }} />
              <div className="linear-capstone-scale"><span>4 A</span><span>12 A</span></div>
              <label htmlFor="linear-capstone-gap"><span>Airgap</span><strong>{gapMm.toFixed(1)} mm</strong></label>
              <input id="linear-capstone-gap" aria-label="Linear motor airgap" type="range" min="2" max="10" step="0.5" value={gapMm} onChange={(event) => { setGapMm(Number(event.target.value)); setEnergized(true); setRunOnce(false); invalidateField(); }} />
              <div className="linear-capstone-scale"><span>2 mm</span><span>10 mm</span></div>
            </section>
          ) : null}

          <p className="linear-capstone-no-recipe">No configuration is suggested. The field and motion are the feedback.</p>
        </div>
        <footer className="linear-capstone-panel-footer">
          <button type="button" onClick={onBackToCatalog}>Lessons</button>
          <button type="button" onClick={onBackHome}>Design start</button>
        </footer>
      </aside>

      <aside className={`learning-context-panel linear-capstone-context${inspectorOpen ? ' is-open' : ''}`} aria-label="Capstone design evidence" aria-hidden={!inspectorOpen}>
        <button type="button" className="linear-capstone-drawer-close" onClick={() => setInspectorOpen(false)} aria-label="Close design evidence">×</button>
        <div className="linear-capstone-panel-scroll">
          <p className="linear-capstone-panel-kicker">Chapter 1 · evidence</p>
          <h2>{phase === 'complete' ? 'You made a motor move.' : 'What the machine is doing'}</h2>
          <p className="linear-capstone-context-lede">{phase === 'complete' ? 'Field became force. Force became motion.' : directionLabel(forceDirection)}</p>
          <section className="linear-capstone-evidence-card">
            <div><span>Useful field</span><strong>{Math.round(coherence * 100)}%</strong></div>
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
        </div>
      </aside>
    </main>
  );
};
