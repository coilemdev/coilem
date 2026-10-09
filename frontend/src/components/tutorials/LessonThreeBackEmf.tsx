import React from 'react';
import { KnowledgeCheck } from './KnowledgeCheck';
import { LessonCompleteButton } from './LessonCompleteButton';
import type { KnowledgeCheckQuestion } from './magneticCircuit';
import { useLearningProgress } from './useLearningProgress';
import {
  BEMF_ANGLE_CHECKPOINTS, BEMF_LAB_BASELINE, BEMF_RECOVERY_RPM,
  backEmfAnglesInspected, backEmfLabComplete, backEmfLabReducer,
  backEmfPhaseVoltage as phaseVoltageAt, calculateBackEmfState, createBackEmfLabProgress,
} from './lessonTenBackEmf';
import type {
  LearningLessonHeaderProgress,
  LearningLessonProgressStep,
} from './lessonStage';
import './learning.css';
import './lesson-three-bemf.css';

type BackEmfStage = 'design' | 'mesh' | 'solve';

interface LearningLessonThreeBackEmfProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: BackEmfStage;
  onStageChange?: (stage: BackEmfStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

interface WindingPreset {
  id: 'low' | 'medium' | 'high';
  label: string;
  keVPerKrpm: number;
  summary: string;
}

const BEMF_STAGES: Array<{ id: BackEmfStage; title: string; summary: string }> = [
  { id: 'design', title: 'Rotor Angle', summary: 'Inspect the phase voltages at 0°, 90°, and 180°.' },
  { id: 'mesh', title: 'Speed Limit', summary: 'Increase RPM until the voltage reserve is exhausted.' },
  { id: 'solve', title: 'Recover', summary: 'Restore headroom at 6,000 RPM with a different motor–inverter match.' },
];

const WINDING_PRESETS: WindingPreset[] = [
  {
    id: 'low',
    label: 'Low Ke',
    keVPerKrpm: 3.4,
    summary: 'Higher speed range, more current for the same torque.',
  },
  {
    id: 'medium',
    label: 'Mid Ke',
    keVPerKrpm: 5.6,
    summary: 'Balanced 48 V class example for a small SPM motor.',
  },
  {
    id: 'high',
    label: 'High Ke',
    keVPerKrpm: 8.8,
    summary: 'More torque per amp, lower voltage-limited speed.',
  },
];

const BUS_VOLTAGES = [24, 48, 96, 400] as const;

const BEMF_KNOWLEDGE_CHECK: KnowledgeCheckQuestion[] = [
  {
    id: 'rpm-scales-bemf',
    prompt: 'If the motor RPM doubles and the winding does not change, what happens to BEMF?',
    options: ['It roughly doubles.', 'It stays fixed by the battery.', 'It falls because the motor is moving faster.'],
    correctIndex: 0,
    explanation: 'BEMF is proportional to speed: E = Ke * RPM.',
  },
  {
    id: 'voltage-headroom',
    prompt: 'Why does high BEMF reduce high-speed torque?',
    options: [
      'It leaves less inverter voltage to push current into the windings.',
      'It removes the rotor magnets from the magnetic circuit.',
      'It makes the phase resistance disappear.',
    ],
    correctIndex: 0,
    explanation: 'The inverter must cover BEMF plus resistive and inductive voltage drops. Less headroom means less current authority.',
  },
  {
    id: 'dc-bus-convention',
    prompt: 'What should a 48 V setting in the designer usually mean?',
    options: [
      'The battery/DC bus feeding the inverter.',
      'A guaranteed 48 V RMS sine wave on each phase.',
      'The BEMF limit at every RPM.',
    ],
    correctIndex: 0,
    explanation: 'The inverter converts the DC bus into three-phase AC/PWM. The usable line-line RMS voltage is lower than Vdc.',
  },
];

const clampNumber = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value));

const formatVolts = (value: number): string => `${value.toFixed(value >= 100 ? 0 : 1)} V`;
const formatRpm = (value: number): string => `${Math.round(value).toLocaleString()} rpm`;
const formatPercent = (value: number): string => `${Math.round(value)}%`;
const formatAngle = (value: number): string => `${Math.round(value)} deg`;

const PHASES = [
  { id: 'A', label: 'Phase A', shiftDeg: 0, color: '#f87171' },
  { id: 'B', label: 'Phase B', shiftDeg: -120, color: '#60a5fa' },
  { id: 'C', label: 'Phase C', shiftDeg: 120, color: '#4ade80' },
] as const;

function stageOrder(stage: BackEmfStage): number {
  return BEMF_STAGES.findIndex((item) => item.id === stage);
}

function normalizeAngleDeg(angleDeg: number): number {
  return ((angleDeg % 360) + 360) % 360;
}

function polarPoint(cx: number, cy: number, radius: number, angleDeg: number): { x: number; y: number } {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return {
    x: cx + Math.cos(rad) * radius,
    y: cy + Math.sin(rad) * radius,
  };
}

function annularSectorPath(
  cx: number,
  cy: number,
  innerRadius: number,
  outerRadius: number,
  startDeg: number,
  endDeg: number,
): string {
  const largeArcFlag = Math.abs(endDeg - startDeg) > 180 ? 1 : 0;
  const outerStart = polarPoint(cx, cy, outerRadius, startDeg);
  const outerEnd = polarPoint(cx, cy, outerRadius, endDeg);
  const innerEnd = polarPoint(cx, cy, innerRadius, endDeg);
  const innerStart = polarPoint(cx, cy, innerRadius, startDeg);

  return [
    `M ${outerStart.x.toFixed(2)} ${outerStart.y.toFixed(2)}`,
    `A ${outerRadius} ${outerRadius} 0 ${largeArcFlag} 1 ${outerEnd.x.toFixed(2)} ${outerEnd.y.toFixed(2)}`,
    `L ${innerEnd.x.toFixed(2)} ${innerEnd.y.toFixed(2)}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArcFlag} 0 ${innerStart.x.toFixed(2)} ${innerStart.y.toFixed(2)}`,
    'Z',
  ].join(' ');
}

function phasePath({
  phaseShiftDeg,
  phasePeakV,
  x,
  y,
}: {
  phaseShiftDeg: number;
  phasePeakV: number;
  x: (angleDeg: number) => number;
  y: (voltage: number) => number;
}): string {
  return Array.from({ length: 121 }, (_, index) => {
    const angleDeg = (360 / 120) * index;
    const voltage = phaseVoltageAt(angleDeg, phaseShiftDeg, phasePeakV);
    return `${index === 0 ? 'M' : 'L'} ${x(angleDeg).toFixed(1)} ${y(voltage).toFixed(1)}`;
  }).join(' ');
}

function BEMFActionMotor({
  rotorAngleDeg,
  rpm,
  phasePeakV,
  isAnimating,
  onTogglePlayback,
}: {
  rotorAngleDeg: number;
  rpm: number;
  phasePeakV: number;
  isAnimating: boolean;
  onTogglePlayback: () => void;
}) {
  const center = 180;
  const coils = [
    { phase: 'A', angle: -90, polarity: '+', color: PHASES[0].color },
    { phase: 'B', angle: -30, polarity: '-', color: PHASES[1].color },
    { phase: 'C', angle: 30, polarity: '+', color: PHASES[2].color },
    { phase: 'A', angle: 90, polarity: '-', color: PHASES[0].color },
    { phase: 'B', angle: 150, polarity: '+', color: PHASES[1].color },
    { phase: 'C', angle: 210, polarity: '-', color: PHASES[2].color },
  ];
  const teeth = Array.from({ length: 12 }, (_, index) => index * 30);

  return (
    <figure className="bemf-motor-action">
      <div className="bemf-playback-controls" role="group" aria-label="Rotor playback">
        <span>Rotor playback</span>
        <button type="button" className="learning-ghost-button" aria-pressed={isAnimating}
          disabled={rpm <= 0 && !isAnimating} onClick={onTogglePlayback}>
          {isAnimating ? 'Pause Rotor' : 'Spin Rotor'}
        </button>
      </div>
      <svg className="bemf-motor-svg" viewBox="0 0 360 360" role="img" aria-label="Surface permanent magnet motor generating back EMF">
        <defs>
          <filter id="bemfMotorGlow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feColorMatrix
              in="blur"
              type="matrix"
              values="0 0 0 0 0.14 0 0 0 0 0.83 0 0 0 0 0.93 0 0 0 0.44 0"
            />
            <feBlend in="SourceGraphic" mode="screen" />
          </filter>
        </defs>
        <circle cx={center} cy={center} r="156" className="bemf-stator-outer" />
        <circle cx={center} cy={center} r="108" className="bemf-stator-bore" />
        <g className="bemf-stator-teeth">
          {teeth.map((angle) => {
            const start = polarPoint(center, center, 110, angle);
            const end = polarPoint(center, center, 153, angle);
            return <line key={angle} x1={start.x} y1={start.y} x2={end.x} y2={end.y} />;
          })}
        </g>
        <g className="bemf-phase-coils">
          {coils.map((coil) => {
            const point = polarPoint(center, center, 133, coil.angle);
            return (
              <g key={`${coil.phase}${coil.polarity}${coil.angle}`} transform={`translate(${point.x} ${point.y}) rotate(${coil.angle + 90})`}>
                <rect x="-17" y="-13" width="34" height="26" rx="6" style={{ fill: coil.color }} />
                <text x="0" y="4">{coil.phase}{coil.polarity}</text>
              </g>
            );
          })}
        </g>
        <g transform={`rotate(${rotorAngleDeg} ${center} ${center})`}>
          <circle cx={center} cy={center} r="82" className="bemf-rotor-core" />
          <path d={annularSectorPath(center, center, 64, 86, -72, 72)} className="bemf-magnet-n" />
          <path d={annularSectorPath(center, center, 64, 86, 108, 252)} className="bemf-magnet-s" />
          <line x1={center} y1={center} x2={center} y2={92} className="bemf-rotor-axis" />
          <text x={center} y="116" textAnchor="middle" className="bemf-magnet-label">N</text>
          <text x={center} y="258" textAnchor="middle" className="bemf-magnet-label">S</text>
        </g>
        <circle cx={center} cy={center} r="19" className="bemf-shaft" />
        <circle cx={center} cy={center} r="100" className="bemf-airgap" />
      </svg>
      <figcaption>
        <strong>{formatRpm(rpm)}</strong>
        <span>{formatVolts(phasePeakV)} phase peak generated</span>
      </figcaption>
    </figure>
  );
}

function BEMFWaveformChart({
  electricalAngleDeg,
  phasePeakV,
  reservedPhasePeakV,
  voltagePhasePeakV,
}: {
  electricalAngleDeg: number;
  phasePeakV: number;
  reservedPhasePeakV: number;
  voltagePhasePeakV: number;
}) {
  const W = 640;
  const H = 340;
  const left = 48;
  const right = W - 24;
  const top = 28;
  const bottom = H - 42;
  const zeroY = (top + bottom) / 2;
  const scaleMax = Math.max(phasePeakV, reservedPhasePeakV, voltagePhasePeakV, 1) * 1.22;
  const x = (angleDeg: number) => left + (angleDeg / 360) * (right - left);
  const y = (voltage: number) => zeroY - (voltage / scaleMax) * ((bottom - top) / 2);
  const markerAngle = normalizeAngleDeg(electricalAngleDeg);
  const markerX = x(markerAngle);
  const reservedYp = y(reservedPhasePeakV);
  const reservedYn = y(-reservedPhasePeakV);
  const voltageYp = y(voltagePhasePeakV);
  const voltageYn = y(-voltagePhasePeakV);

  return (
    <svg className="bemf-waveform-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Three phase BEMF waveforms">
      <line x1={left} y1={zeroY} x2={right} y2={zeroY} className="bemf-wave-grid" />
      {[0, 90, 180, 270, 360].map((angle) => (
        <line key={angle} x1={x(angle)} y1={top} x2={x(angle)} y2={bottom} className="bemf-wave-grid is-muted" />
      ))}
      <line x1={left} y1={voltageYp} x2={right} y2={voltageYp} className="bemf-wave-limit" />
      <line x1={left} y1={voltageYn} x2={right} y2={voltageYn} className="bemf-wave-limit" />
      <line x1={left} y1={reservedYp} x2={right} y2={reservedYp} className="bemf-wave-reserve" />
      <line x1={left} y1={reservedYn} x2={right} y2={reservedYn} className="bemf-wave-reserve" />
      {PHASES.map((phase) => (
        <path
          key={phase.id}
          d={phasePath({ phaseShiftDeg: phase.shiftDeg, phasePeakV, x, y })}
          fill="none"
          stroke={phase.color}
          className="bemf-wave-phase"
        />
      ))}
      <line x1={markerX} y1={top} x2={markerX} y2={bottom} className="bemf-wave-marker-line" />
      {PHASES.map((phase) => {
        const voltage = phaseVoltageAt(markerAngle, phase.shiftDeg, phasePeakV);
        return <circle key={phase.id} cx={markerX} cy={y(voltage)} r="5" fill={phase.color} className="bemf-wave-marker" />;
      })}
      <text x={left + 8} y={voltageYp - 8} className="bemf-wave-label">inverter limit</text>
      <text x={left + 8} y={reservedYp + 16} className="bemf-wave-label is-reserve">reserve limit</text>
      <text x={markerX + 10} y={top + 20} className="bemf-wave-label is-live">{formatAngle(markerAngle)}</text>
      <text x={left} y={H - 12} className="bemf-wave-axis">0 elec deg</text>
      <text x={right} y={H - 12} textAnchor="end" className="bemf-wave-axis">360 elec deg</text>
      <g className="bemf-wave-legend">
        {PHASES.map((phase, index) => (
          <g key={phase.id} transform={`translate(${left + index * 86} 14)`}>
            <circle cx="0" cy="0" r="4" fill={phase.color} />
            <text x="9" y="4">{phase.label}</text>
          </g>
        ))}
      </g>
    </svg>
  );
}

function BEMFChart({
  rpm,
  maxRpm,
  keVPerKrpm,
  voltageLimit,
  reservedLimit,
  bemfV,
}: {
  rpm: number;
  maxRpm: number;
  keVPerKrpm: number;
  voltageLimit: number;
  reservedLimit: number;
  bemfV: number;
}) {
  const W = 440;
  const H = 250;
  const left = 54;
  const right = W - 26;
  const top = 22;
  const bottom = H - 36;
  const yMax = Math.max(voltageLimit, bemfV, reservedLimit, keVPerKrpm * maxRpm / 1000, 1) * 1.22;
  const x = (value: number) => left + (value / maxRpm) * (right - left);
  const y = (value: number) => bottom - (value / yMax) * (bottom - top);
  const steps = 28;
  const bemfPath = Array.from({ length: steps + 1 }, (_, index) => {
    const pointRpm = (maxRpm / steps) * index;
    const pointBemf = keVPerKrpm * (pointRpm / 1000);
    return `${index === 0 ? 'M' : 'L'} ${x(pointRpm).toFixed(1)} ${y(pointBemf).toFixed(1)}`;
  }).join(' ');
  const markerX = x(rpm);
  const markerY = y(bemfV);
  const voltageY = y(voltageLimit);
  const reserveY = y(reservedLimit);

  return (
    <svg className="bemf-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="BEMF versus RPM voltage headroom">
      <rect x={left} y={top} width={right - left} height={voltageY - top} className="bemf-chart-danger" />
      <line x1={left} y1={bottom} x2={right} y2={bottom} className="bemf-chart-grid" />
      <line x1={left} y1={top} x2={left} y2={bottom} className="bemf-chart-grid" />
      {[0.25, 0.5, 0.75, 1].map((fraction) => (
        <line
          key={fraction}
          x1={left + (right - left) * fraction}
          y1={top}
          x2={left + (right - left) * fraction}
          y2={bottom}
          className="bemf-chart-grid is-muted"
        />
      ))}
      <line x1={left} y1={voltageY} x2={right} y2={voltageY} className="bemf-chart-voltage" />
      <line x1={left} y1={reserveY} x2={right} y2={reserveY} className="bemf-chart-reserve" />
      <path d={bemfPath} className="bemf-chart-line" />
      <line x1={markerX} y1={top} x2={markerX} y2={bottom} className="bemf-chart-marker-line" />
      <circle cx={markerX} cy={markerY} r="6" className="bemf-chart-marker" />
      <text x={left + 8} y={voltageY - 8} className="bemf-chart-label">
        usable inverter voltage
      </text>
      <text x={left + 8} y={reserveY + 17} className="bemf-chart-label is-reserve">
        reserve exhausted
      </text>
      <text x={Math.min(markerX + 12, right - 150)} y={Math.max(markerY - 12, top + 14)} className="bemf-chart-label is-live">
        {formatVolts(bemfV)} BEMF
      </text>
      <text x={left} y={H - 10} className="bemf-chart-axis">
        0 rpm
      </text>
      <text x={right} y={H - 10} textAnchor="end" className="bemf-chart-axis">
        {formatRpm(maxRpm)}
      </text>
      <text x={left - 8} y={voltageY + 4} textAnchor="end" className="bemf-chart-axis">
        {formatVolts(voltageLimit)}
      </text>
    </svg>
  );
}

export const LearningLessonThreeBackEmf: React.FC<LearningLessonThreeBackEmfProps> = ({
  onBackToCatalog, onBackHome, stage, onStageChange, onHeaderProgressChange,
}) => {
  const [internalStage, setInternalStage] = React.useState<BackEmfStage>('design');
  const [dcBusV, setDcBusV] = React.useState<number>(BEMF_LAB_BASELINE.dcBusV);
  const [windingId, setWindingId] = React.useState<WindingPreset['id']>('medium');
  const [customKeVPerKrpm, setCustomKeVPerKrpm] = React.useState<number>(BEMF_LAB_BASELINE.keVPerKrpm);
  const [rpm, setRpm] = React.useState<number>(BEMF_LAB_BASELINE.rpm);
  const [reservePct, setReservePct] = React.useState<number>(BEMF_LAB_BASELINE.reservePct);
  const [rotorAngleDeg, setRotorAngleDeg] = React.useState(0);
  const [isRotorAnimating, setIsRotorAnimating] = React.useState(false);
  const [knowledgePassed, setKnowledgePassed] = React.useState(false);
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [labProgress, dispatchLab] = React.useReducer(backEmfLabReducer, undefined, createBackEmfLabProgress);
  const { setLessonComplete } = useLearningProgress();
  const anglesInspected = backEmfAnglesInspected(labProgress);
  const labComplete = backEmfLabComplete(labProgress);
  // Existing route stage names remain compatible, but cannot bypass the lab.
  const requestedStage = stage ?? internalStage;
  const lessonStage = !anglesInspected ? 'design'
    : !labProgress.reserveCrossed && requestedStage === 'solve' ? 'mesh' : requestedStage;
  const currentStageOrder = stageOrder(lessonStage);
  const activeStageItem = BEMF_STAGES[currentStageOrder];
  const selectedWinding = WINDING_PRESETS.find((preset) => preset.id === windingId) ?? WINDING_PRESETS[1];
  const winding = { ...selectedWinding, keVPerKrpm: windingId === 'medium' ? customKeVPerKrpm : selectedWinding.keVPerKrpm };
  const inputs = { dcBusV, keVPerKrpm: winding.keVPerKrpm, rpm, reservePct };
  const model = calculateBackEmfState(inputs);
  const { inverterLineLineRmsV, reservedLineLineRmsV, bemfV, phasePeakV,
    voltagePhasePeakV, reservedPhasePeakV, headroomV, baseSpeedRpm, inverterLimitRpm } = model;
  const electricalAngleDeg = normalizeAngleDeg(rotorAngleDeg);
  const maxPlotRpm = Math.ceil(Math.max(9000, rpm * 1.25, baseSpeedRpm * 1.18) / 500) * 500;
  const status = {
    'inverter-exceeded': 'Inverter voltage exceeded', 'reserve-exhausted': 'Reserve exhausted',
    'low-headroom': 'Low headroom', 'headroom-ok': 'Headroom ok',
  }[model.status];
  const statusClass = model.status === 'inverter-exceeded' ? 'is-danger'
    : model.status === 'headroom-ok' ? 'is-ok' : 'is-warning';
  const animationFrameRef = React.useRef<number | null>(null);
  const lastFrameMsRef = React.useRef<number | null>(null);
  const knowledgeHeadingRef = React.useRef<HTMLHeadingElement | null>(null);

  React.useEffect(() => {
    // Route-driven stage changes get the same fixed starting point as the Next buttons.
    setIsRotorAnimating(false);
    setDcBusV(BEMF_LAB_BASELINE.dcBusV);
    setWindingId('medium');
    setCustomKeVPerKrpm(BEMF_LAB_BASELINE.keVPerKrpm);
    setReservePct(BEMF_LAB_BASELINE.reservePct);
    setRpm(lessonStage === 'solve' ? BEMF_RECOVERY_RPM : BEMF_LAB_BASELINE.rpm);
  }, [lessonStage]);

  React.useEffect(() => {
    if (quizOpen && labComplete) {
      knowledgeHeadingRef.current?.focus({ preventScroll: true });
      knowledgeHeadingRef.current?.scrollIntoView({ block: 'nearest' });
    }
  }, [quizOpen, labComplete]);

  React.useEffect(() => {
    if (labComplete && knowledgePassed) setLessonComplete('back-emf-voltage-headroom', true);
  }, [labComplete, knowledgePassed, setLessonComplete]);

  React.useEffect(() => {
    if (!isRotorAnimating || rpm <= 0) return undefined;
    const tick = (timestamp: number) => {
      const last = lastFrameMsRef.current ?? timestamp;
      const deltaS = Math.min(0.05, Math.max(0, (timestamp - last) / 1000));
      lastFrameMsRef.current = timestamp;
      // Slow-motion playback is illustrative; only manual inspection earns checkpoints.
      const visualDegPerSecond = clampNumber(rpm / 12, 60, 760);
      setRotorAngleDeg((current) => normalizeAngleDeg(current + visualDegPerSecond * deltaS));
      animationFrameRef.current = window.requestAnimationFrame(tick);
    };
    animationFrameRef.current = window.requestAnimationFrame(tick);
    return () => {
      if (animationFrameRef.current !== null) window.cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
      lastFrameMsRef.current = null;
    };
  }, [isRotorAnimating, rpm]);

  const setLessonStage = React.useCallback((nextStage: BackEmfStage) => {
    setInternalStage(nextStage);
    onStageChange?.(nextStage);
    setQuizOpen(false);
    setIsRotorAnimating(false);
    // Each exercise starts with a reproducible comparison. Completed tasks remain checked.
    setDcBusV(BEMF_LAB_BASELINE.dcBusV);
    setWindingId('medium');
    setCustomKeVPerKrpm(BEMF_LAB_BASELINE.keVPerKrpm);
    setReservePct(BEMF_LAB_BASELINE.reservePct);
    setRpm(nextStage === 'solve' ? BEMF_RECOVERY_RPM : BEMF_LAB_BASELINE.rpm);
  }, [onStageChange]);

  const handleAngleChange = (nextAngle: number) => {
    setIsRotorAnimating(false);
    setRotorAngleDeg(nextAngle);
    if (lessonStage === 'design') dispatchLab({ type: 'angle', angleDeg: nextAngle, source: 'user' });
  };
  const handleRpmChange = (nextRpm: number) => {
    setRpm(nextRpm);
    if (lessonStage === 'mesh') dispatchLab({ type: 'speed', inputs: { ...inputs, rpm: nextRpm } });
  };
  const handleBusChange = (nextBus: number) => {
    setDcBusV(nextBus);
    if (lessonStage === 'solve') dispatchLab({ type: 'match', inputs: { ...inputs, dcBusV: nextBus } });
  };
  const handleKeChange = (nextKe: number, presetId: WindingPreset['id'] = 'medium') => {
    setWindingId(presetId);
    if (presetId === 'medium') setCustomKeVPerKrpm(nextKe);
    if (lessonStage === 'solve') dispatchLab({ type: 'match', inputs: { ...inputs, keVPerKrpm: nextKe } });
  };
  const resetLab = () => {
    dispatchLab({ type: 'reset' });
    setKnowledgePassed(false);
    setRotorAngleDeg(0);
    setLessonStage('design');
  };
  const taskComplete = lessonStage === 'design' ? anglesInspected
    : lessonStage === 'mesh' ? labProgress.reserveCrossed : labProgress.recovered;
  const primaryActionLabel = lessonStage === 'design' ? 'Next: Speed Limit'
    : lessonStage === 'mesh' ? 'Next: Recover' : 'Continue to Quiz';
  const handlePrimaryAdvance = () => {
    if (!taskComplete) return;
    if (lessonStage === 'design') setLessonStage('mesh');
    else if (lessonStage === 'mesh') setLessonStage('solve');
    else if (labComplete) { setIsRotorAnimating(false); setQuizOpen(true); }
  };

  const progressSteps = React.useMemo<LearningLessonProgressStep[]>(() => [
    { id: 'design', label: 'Rotor Angle', complete: anglesInspected, available: true },
    { id: 'mesh', label: 'Speed Limit', complete: labProgress.reserveCrossed, available: anglesInspected },
    { id: 'solve', label: 'Recover', complete: labProgress.recovered, available: labProgress.reserveCrossed },
    { id: 'check', label: 'Check', complete: labComplete && knowledgePassed, available: labComplete },
  ], [anglesInspected, labProgress.reserveCrossed, labProgress.recovered, labComplete, knowledgePassed]);
  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 10, lessonCount: 10, title: 'BEMF & Voltage Headroom',
    currentStepId: quizOpen && labComplete ? 'check' : lessonStage,
    steps: progressSteps,
    onStepSelect: (stepId) => {
      if (!progressSteps.find((item) => item.id === stepId)?.available) return;
      if (stepId === 'check') { setIsRotorAnimating(false); setQuizOpen(true); }
      else if (stepId === lessonStage) setQuizOpen(false);
      else setLessonStage(stepId as BackEmfStage);
    },
  }), [labComplete, lessonStage, progressSteps, quizOpen, setLessonStage]);
  React.useEffect(() => { onHeaderProgressChange?.(headerProgress); }, [headerProgress, onHeaderProgressChange]);

  const feedback = lessonStage === 'design'
    ? anglesInspected ? 'Angle inspection complete. The phase values changed; the RMS amplitude stayed fixed.'
      : `Inspect all three angles (${labProgress.inspectedAngles.length}/3). Angle moves the cursor, not the amplitude.`
    : lessonStage === 'mesh'
      ? labProgress.reserveCrossed ? 'Speed challenge complete. Compare the yellow reserve line with the cyan inverter limit.'
        : 'Raise the speed above the reserved speed. Keep the 48 V bus, Mid Ke winding, and 15% reserve.'
      : labProgress.recovered ? 'Recovery complete. You restored positive headroom at the same speed and reserve.'
        : 'Keep 6,000 RPM and 15% reserve. Increase the DC bus or choose a lower Ke to restore positive headroom.';
  const busControl = (label: string) => (
    <div className="learning-overlay-selector bemf-rail-control">
      <span>DC bus</span>
      <div className="learning-segmented-control bemf-segmented-four" role="group" aria-label={label}>
        {BUS_VOLTAGES.map((voltage) => <button key={voltage} type="button" aria-pressed={dcBusV === voltage}
          className={dcBusV === voltage ? 'is-active' : ''} onClick={() => handleBusChange(voltage)}>{voltage} V</button>)}
      </div>
    </div>
  );
  const windingControl = (label: string) => (
    <div className="learning-overlay-selector bemf-rail-control">
      <span>Winding constant</span>
      <div className="learning-segmented-control" role="group" aria-label={label}>
        {WINDING_PRESETS.map((preset) => <button key={preset.id} type="button" aria-pressed={windingId === preset.id}
          className={windingId === preset.id ? 'is-active' : ''} onClick={() => handleKeChange(preset.keVPerKrpm, preset.id)}>
          {preset.label}<small>{preset.keVPerKrpm.toFixed(1)} V/krpm</small>
        </button>)}
      </div>
    </div>
  );

  return (
    <main className={`learning-shell learning-lesson-shell bemf-shell is-${lessonStage}-stage`}>
      <section className={`learning-main-stage is-${lessonStage}-stage bemf-main-stage`}>
        <div className="learning-motor-viewport">
          <div className="learning-stage-badge"><span>{quizOpen ? 'Knowledge Check' : activeStageItem.title}</span>
            <strong className={`bemf-status ${statusClass}`}>{status}</strong></div>
          <div className="bemf-hero-panel">
            <BEMFActionMotor rotorAngleDeg={electricalAngleDeg} rpm={rpm} phasePeakV={phasePeakV}
              isAnimating={isRotorAnimating} onTogglePlayback={() => setIsRotorAnimating((current) => !current)} />
            <div className="bemf-waveform-panel">
              <div className="bemf-waveform-head"><div><span>Generated BEMF</span>
                <strong>{formatVolts(bemfV)} line-line RMS</strong></div></div>
              <div className="bemf-phase-values" aria-label="Instantaneous phase voltages">
                {PHASES.map((phase) => <div key={phase.id}><span style={{ color: phase.color }}>{phase.label}</span>
                  <output aria-live="off">{formatVolts(phaseVoltageAt(electricalAngleDeg, phase.shiftDeg, phasePeakV))}</output></div>)}
              </div>
              <BEMFWaveformChart electricalAngleDeg={electricalAngleDeg} phasePeakV={phasePeakV}
                reservedPhasePeakV={reservedPhasePeakV} voltagePhasePeakV={voltagePhasePeakV} />
            </div>
            <div className="bemf-action-readouts" aria-label="BEMF live readouts">
              <div><span>Equation</span><strong>{winding.keVPerKrpm.toFixed(1)} V/krpm × {(rpm / 1000).toFixed(1)} krpm</strong></div>
              <div><span>Inverter voltage</span><strong>{formatVolts(inverterLineLineRmsV)} line-line RMS</strong></div>
              <div><span>Reserved headroom</span><strong className={statusClass}>{formatVolts(headroomV)}</strong></div>
            </div>
          </div>
        </div>
        <section className="learning-plot-row">
          <div className="learning-plot-panel">
            <div className="learning-panel-heading"><h2>BEMF vs. RPM</h2><span className="learning-provenance">analytic model</span></div>
            <BEMFChart rpm={rpm} maxRpm={maxPlotRpm} keVPerKrpm={winding.keVPerKrpm}
              voltageLimit={inverterLineLineRmsV} reservedLimit={reservedLineLineRmsV} bemfV={bemfV} />
            <dl className="bemf-thresholds">
              <div><dt>Reserve exhausted</dt><dd>{formatRpm(baseSpeedRpm)}</dd></div>
              <div><dt>Inverter voltage limit</dt><dd>{formatRpm(inverterLimitRpm)}</dd></div>
            </dl>
            <p className="bemf-model-note">Ideal sinusoidal BEMF and linear SVPWM. The reserve allows for winding voltage drops; this model does not calculate loaded torque.</p>
          </div>
          <div className="learning-knowledge-panel">
            <h2 ref={knowledgeHeadingRef} tabIndex={-1}>{quizOpen && labComplete ? 'Knowledge Check' : 'Lab Checklist'}</h2>
            {/* Preserve answers during navigation; Reset Lab unmounts the quiz. */}
            {labComplete ? (
              <div hidden={!quizOpen}>
                <KnowledgeCheck questions={BEMF_KNOWLEDGE_CHECK} onPassedChange={setKnowledgePassed} />
              </div>
            ) : null}
            {!quizOpen || !labComplete ? (
              <div className="bemf-checklist">
                {progressSteps.slice(0, 3).map((item) => <div key={item.id} className={item.complete ? 'is-complete' : ''}>
                  <span aria-hidden="true">{item.complete ? '✓' : '○'}</span><span>{item.label}</span>
                  <strong>{item.complete ? 'Complete' : 'Pending'}</strong>
                </div>)}
                <p>{labComplete ? 'All exercises complete. Continue to the quiz.' : 'Complete all three exercises to unlock the quiz.'}</p>
              </div>
            ) : null}
          </div>
        </section>
      </section>
      <aside className="learning-control-panel">
        <section className="tutorial-studio-goal">
          <span>{quizOpen ? '4/4' : `${currentStageOrder + 1}/3`}</span>
          <div><p className="learning-kicker">Current goal</p><h2>{quizOpen ? 'Check your understanding'
            : lessonStage === 'design' ? 'Inspect the rotor angle'
              : lessonStage === 'mesh' ? 'Find the reserved speed' : 'Restore voltage headroom'}</h2></div>
        </section>
        {!quizOpen ? <section className="learning-control-section bemf-exercise" aria-label="Current exercise">
          <p>{activeStageItem.summary}</p>
          {lessonStage === 'design' ? <>
            <div className="bemf-angle-checkpoints" role="group" aria-label="Angle checkpoints">
              {BEMF_ANGLE_CHECKPOINTS.map((angle) => <button key={angle} type="button" onClick={() => handleAngleChange(angle)}
                aria-label={`Inspect ${angle} degrees`} className={labProgress.inspectedAngles.includes(angle) ? 'is-complete' : ''}>
                {angle}° {labProgress.inspectedAngles.includes(angle) ? '✓' : ''}
              </button>)}
            </div>
            <label className="learning-setting-field"><span>Electrical angle</span><div>
              <input type="number" min={0} max={360} step={1} value={Math.round(electricalAngleDeg)}
                onChange={(event) => handleAngleChange(clampNumber(event.currentTarget.valueAsNumber || 0, 0, 360))} /><em>deg</em>
            </div><input className="learning-setting-range" type="range" min={0} max={360} step={1}
              value={Math.round(electricalAngleDeg)} aria-label="Electrical angle slider"
              onChange={(event) => handleAngleChange(Number(event.currentTarget.value))} /></label>
            <p className="bemf-model-note">Playback is shown in slow motion. Pause and select each angle to inspect it. The angle exercise uses 4,200 RPM.</p>
          </> : lessonStage === 'mesh' ? <>
            <p className="bemf-fixed-inputs">48 V DC bus · Mid Ke 5.6 · 15% reserve</p>
            <label className="learning-setting-field"><span>Motor speed</span><div>
              <input type="number" min={0} max={9000} step={100} value={rpm}
                onChange={(event) => handleRpmChange(clampNumber(event.currentTarget.valueAsNumber || 0, 0, 9000))} /><em>rpm</em>
            </div><input className="learning-setting-range" type="range" min={0} max={9000} step={100} value={rpm}
              aria-label="Motor speed slider" onChange={(event) => handleRpmChange(Number(event.currentTarget.value))} /></label>
            <p>Reserved speed: <strong>{formatRpm(baseSpeedRpm)}</strong>. Watch headroom reach zero as you cross the yellow line.</p>
          </> : <>
            <p className="bemf-fixed-inputs">{labComplete ? 'Recovery target' : 'Held'} at 6,000 RPM · 15% reserve</p>
            {busControl('Recovery DC bus')}{windingControl('Recovery winding constant')}
            <p className={`bemf-live-status ${statusClass}`}>{status} · {formatVolts(headroomV)} reserved headroom</p>
          </>}
          <p className={`bemf-task-feedback${taskComplete ? ' is-complete' : ''}`} role="status">{feedback}</p>
          <div className="learning-panel-actions is-single">
            <button type="button" className="learning-primary-button" disabled={!taskComplete} onClick={handlePrimaryAdvance}>{primaryActionLabel}</button>
          </div>
          <div className="bemf-exercise-nav">
            {lessonStage !== 'design' ? <button type="button" className="learning-ghost-button"
              onClick={() => setLessonStage(lessonStage === 'solve' ? 'mesh' : 'design')}>Back: {lessonStage === 'solve' ? 'Speed Limit' : 'Rotor Angle'}</button> : null}
            <button type="button" className="learning-ghost-button" onClick={resetLab}>Reset Lab</button>
          </div>
        </section> : <section className="learning-control-section bemf-exercise">
          <p>All three lab exercises are complete. Answer the questions on the right to finish this lesson.</p>
          <button type="button" className="learning-ghost-button" onClick={() => setQuizOpen(false)}>Back to lab</button>
          <button type="button" className="learning-ghost-button" onClick={resetLab}>Reset Lab</button>
        </section>}
        <section className="learning-metrics">
          <h2>Current State</h2><dl>
            <div><dt>DC bus</dt><dd>{formatVolts(dcBusV)}</dd></div>
            <div><dt>Speed</dt><dd>{formatRpm(rpm)}</dd></div>
            <div><dt>Winding Ke</dt><dd>{winding.keVPerKrpm.toFixed(1)} V/krpm</dd></div>
            <div><dt>Reserve</dt><dd>{formatPercent(reservePct)}</dd></div>
            <div><dt>BEMF · LL RMS</dt><dd>{formatVolts(bemfV)}</dd></div>
            <div><dt>Reserved headroom</dt><dd className={statusClass}>{formatVolts(headroomV)}</dd></div>
          </dl>
        </section>
        <details className="bemf-explore learning-control-section">
          <summary>More lesson inputs</summary>
          <p>{labComplete ? 'Try other motor–inverter combinations. Your completed exercises stay checked.' : 'Finish the three exercises to unlock free exploration.'}</p>
          <fieldset disabled={!labComplete}>
            {busControl('Explore DC bus')}{windingControl('Explore winding constant')}
            <label className="learning-setting-field"><span>Custom DC bus</span><div><input type="number" min={12} max={800} value={dcBusV}
              onChange={(event) => handleBusChange(clampNumber(event.currentTarget.valueAsNumber || 48, 12, 800))} /><em>V</em></div></label>
            <label className="learning-setting-field"><span>Custom Ke</span><div><input type="number" min={1} max={80} step={0.1} value={winding.keVPerKrpm}
              onChange={(event) => handleKeChange(clampNumber(event.currentTarget.valueAsNumber || winding.keVPerKrpm, 1, 80))} /><em>V/krpm</em></div></label>
            <label className="learning-setting-field"><span>Explore RPM</span><div><input type="number" min={0} max={24000} step={100} value={rpm}
              onChange={(event) => handleRpmChange(clampNumber(event.currentTarget.valueAsNumber || 0, 0, 24000))} /><em>rpm</em></div></label>
            <label className="learning-setting-field"><span>Explore reserve</span><div><input type="number" min={0} max={35} step={1} value={reservePct}
              onChange={(event) => setReservePct(clampNumber(event.currentTarget.valueAsNumber || 0, 0, 35))} /><em>%</em></div></label>
          </fieldset>
        </details>
        <details className="bemf-explore learning-control-section">
          <summary>Explain this model</summary>
          <p>Electrical angle shifts the instantaneous phase values. RPM and Ke set the voltage amplitude.</p>
          <p>Yellow marks the design limit with reserve. Cyan marks the ideal inverter voltage limit. Exhausting reserve does not yet mean the inverter limit has been exceeded.</p>
          <p>The designer voltage is the DC bus. Compare BEMF and the limits in line-line RMS volts; the waveforms show instantaneous phase volts.</p>
        </details>
        <footer className="learning-panel-footer">
          <LessonCompleteButton lessonId="back-emf-voltage-headroom" canComplete={labComplete && knowledgePassed}
            requirementsLabel="Complete the lab and pass the knowledge check" />
          <div className="learning-panel-nav">
            <button type="button" className="learning-ghost-button" onClick={onBackToCatalog}>Lessons</button>
            <button type="button" className="learning-ghost-button" onClick={onBackHome}>Design start</button>
          </div>
        </footer>
      </aside>
    </main>
  );
};
