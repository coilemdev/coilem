import React from 'react';
import { BACK_EMF_PHASE_COLORS, type BackEmfPhaseId } from './phaseColors';
import {
  DESIGN_MAGNET_N_FILL,
  DESIGN_MAGNET_S_FILL,
} from './magnetPoleFills';
import type { LearningLessonStage } from './lessonStage';

// The 2-pole/6-slot SPM teaching cross-section and its geometry helpers, moved
// here out of components/LearningLessons.tsx so the shared tutorial tree owns
// them. LearningLessons re-exports `LessonMotorDiagram` unchanged.

interface LessonDesignSettings {
  airgapMm: number;
  magnetArcPct: number;
  magnetThicknessMm: number;
}

const LESSON_DEFAULT_DESIGN_SETTINGS: LessonDesignSettings = {
  airgapMm: 1,
  magnetArcPct: 74,
  magnetThicknessMm: 4,
};

// Keep the complete stator inside the lesson Solve stage at its default fit.
// Users can still zoom back to 100% (or farther) with the viewport controls.

function polarPoint(deg: number, radius: number, center = 260) {
  const rad = (deg * Math.PI) / 180;
  return {
    x: center + Math.cos(rad) * radius,
    y: center + Math.sin(rad) * radius,
  };
}

function lessonTorqueScale(settings: LessonDesignSettings) {
  const airgapFactor = Math.pow(LESSON_DEFAULT_DESIGN_SETTINGS.airgapMm / settings.airgapMm, 0.75);
  const thicknessFactor = Math.pow(settings.magnetThicknessMm / LESSON_DEFAULT_DESIGN_SETTINGS.magnetThicknessMm, 0.6);
  const defaultArcFactor = Math.sin((LESSON_DEFAULT_DESIGN_SETTINGS.magnetArcPct / 100) * (Math.PI / 2));
  const arcFactor = Math.sin((settings.magnetArcPct / 100) * (Math.PI / 2)) / defaultArcFactor;
  return clampNumber(airgapFactor * thicknessFactor * arcFactor, 0.45, 2.3);
}

function torqueValue(angleDeg: number, currentA: number, currentAngleDeg = 0, torqueScale = 1) {
  return currentA * 0.32 * torqueScale * Math.sin(((angleDeg - currentAngleDeg) * Math.PI) / 180);
}

function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function buildAngleArc(angleDeg: number) {
  const radius = 52;
  const start = polarPoint(0, radius);
  const end = polarPoint(angleDeg, radius);
  const large = Math.abs(angleDeg) > 180 ? 1 : 0;
  const sweep = angleDeg >= 0 ? 1 : 0;
  return `M ${start.x.toFixed(1)} ${start.y.toFixed(1)} A ${radius} ${radius} 0 ${large} ${sweep} ${end.x.toFixed(1)} ${end.y.toFixed(1)}`;
}

function annularSectorPath(startDeg: number, endDeg: number, innerRadius: number, outerRadius: number) {
  const startOuter = polarPoint(startDeg, outerRadius);
  const endOuter = polarPoint(endDeg, outerRadius);
  const startInner = polarPoint(startDeg, innerRadius);
  const endInner = polarPoint(endDeg, innerRadius);
  const largeArc = Math.abs(endDeg - startDeg) > 180 ? 1 : 0;

  return [
    `M ${startOuter.x.toFixed(1)} ${startOuter.y.toFixed(1)}`,
    `A ${outerRadius} ${outerRadius} 0 ${largeArc} 1 ${endOuter.x.toFixed(1)} ${endOuter.y.toFixed(1)}`,
    `L ${endInner.x.toFixed(1)} ${endInner.y.toFixed(1)}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${startInner.x.toFixed(1)} ${startInner.y.toFixed(1)}`,
    'Z',
  ].join(' ');
}

function annulusPath(innerRadius: number, outerRadius: number) {
  return [
    annularSectorPath(0, 180, innerRadius, outerRadius),
    annularSectorPath(180, 360, innerRadius, outerRadius),
  ].join(' ');
}

interface LessonMotorDiagramProps {
  stage: LearningLessonStage;
  rotorAngle: number;
  currentMagnitude: number;
  designSettings: LessonDesignSettings;
  sweepProgress: number;
}

export const LessonMotorDiagram: React.FC<LessonMotorDiagramProps> = ({
  stage,
  rotorAngle,
  currentMagnitude,
  designSettings,
  sweepProgress,
}) => {
  const showVectors = stage === 'solve';
  const showFlux = stage === 'solve';
  const currentScale = Math.max(0.2, Math.min(1, currentMagnitude / 10));
  const rotorEnd = polarPoint(rotorAngle, 160);
  const rawRotorLabel = polarPoint(rotorAngle, 184);
  const vectorsAligned = rotorAngle < 24 || rotorAngle > 336;
  const rotorLabel = vectorsAligned ? { x: 388, y: 286 } : rawRotorLabel;
  const statorLabel = vectorsAligned ? { x: 388, y: 246 } : { x: 426, y: 250 };
  const angleLabel = polarPoint(Math.max(18, Math.min(150, rotorAngle / 2)), 76);
  const statorFluxOpacity = 0.18 + currentScale * 0.44;
  const windingSlotCenters = [0, 60, 120, 180, 240, 300];
  const toothCoilPhaseByIndex: BackEmfPhaseId[] = ['A', 'C', 'B', 'A', 'C', 'B'];
  const toothCoilPolarityByIndex = [
    '+',
    '−',
    '+',
    '−',
    '+',
    '−',
  ] as const;
  const statorInnerR = 156;
  const statorOuterR = 184;
  const magnetOuterR = clampNumber(statorInnerR - designSettings.airgapMm * 6, 137, 153);
  const magnetInnerR = clampNumber(magnetOuterR - designSettings.magnetThicknessMm * 8, 86, magnetOuterR - 12);
  const rotorCoreR = Math.max(76, magnetInnerR - 2);
  const magnetLabelR = magnetInnerR + (magnetOuterR - magnetInnerR) * 0.75;
  const magnetNorthCenterDeg = 0;
  const magnetSouthCenterDeg = 180;
  const magnetNLabel = polarPoint(magnetNorthCenterDeg, magnetLabelR);
  const magnetSLabel = polarPoint(magnetSouthCenterDeg, magnetLabelR);
  const magnetHalfSpanDeg = 90 * (designSettings.magnetArcPct / 100);
  const previewTorque = torqueValue(rotorAngle, currentMagnitude, 0, lessonTorqueScale(designSettings));
  const windingHalfSpanDeg = 13.5;

  return (
    <svg className="learning-motor-svg" viewBox="0 0 520 520" role="img" aria-label="2 pole 6 slot SPM tutorial motor">
      <defs>
        <marker id="lesson-arrow-cyan" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10Z" fill="#22d3ee" />
        </marker>
        <marker id="lesson-arrow-amber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10Z" fill="#f59e0b" />
        </marker>
        <marker id="lesson-arrow-green" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto">
          <path d="M0 0L10 5L0 10Z" fill="#84cc16" />
        </marker>
        <radialGradient id="lesson-rotor-steel" cx="50%" cy="50%" r="62%">
          <stop offset="0%" stopColor="#334155" />
          <stop offset="100%" stopColor="#202938" />
        </radialGradient>
      </defs>

      <circle cx="260" cy="260" r="225" fill="#475569" stroke="#3b4558" strokeWidth="5" />
      <circle cx="260" cy="260" r={statorOuterR} fill="#0d1119" stroke="#273348" strokeWidth="2" />
      <path d={annulusPath(statorInnerR, statorOuterR)} fill="#9ca3af" stroke="#4b5563" strokeWidth="1.4" />

      {windingSlotCenters.map((centerDeg, index) => {
        const previousToothIndex = (index + windingSlotCenters.length - 1) % windingSlotCenters.length;
        const previousPhase = toothCoilPhaseByIndex[previousToothIndex];
        const currentPhase = toothCoilPhaseByIndex[index];
        return (
          <React.Fragment key={`slot-phase-sides-${centerDeg}`}>
            <path
              d={annularSectorPath(centerDeg - windingHalfSpanDeg, centerDeg, statorInnerR, statorOuterR)}
              fill={BACK_EMF_PHASE_COLORS[previousPhase]}
              opacity="0.96"
              stroke="#111827"
              strokeWidth="1.1"
            />
            <path
              d={annularSectorPath(centerDeg, centerDeg + windingHalfSpanDeg, statorInnerR, statorOuterR)}
              fill={BACK_EMF_PHASE_COLORS[currentPhase]}
              opacity="0.96"
              stroke="#111827"
              strokeWidth="1.1"
            />
          </React.Fragment>
        );
      })}
      {windingSlotCenters.map((centerDeg, index) => {
        const previousToothIndex = (index + windingSlotCenters.length - 1) % windingSlotCenters.length;
        const sides = [
          {
            angleDeg: centerDeg - windingHalfSpanDeg / 2,
            phase: toothCoilPhaseByIndex[previousToothIndex],
            direction: toothCoilPolarityByIndex[previousToothIndex] === '+' ? '⊙' : '⊗',
          },
          {
            angleDeg: centerDeg + windingHalfSpanDeg / 2,
            phase: toothCoilPhaseByIndex[index],
            direction: toothCoilPolarityByIndex[index] === '−' ? '⊙' : '⊗',
          },
        ] as const;
        return (
          <React.Fragment key={`slot-side-${centerDeg}`}>
            {sides.map((side, sideIndex) => {
              const label = polarPoint(side.angleDeg, (statorInnerR + statorOuterR) / 2);
              return (
                <g
                  key={`${centerDeg}-${sideIndex}`}
                  className="lesson-nine-slot-assignment"
                  transform={`translate(${label.x.toFixed(1)} ${label.y.toFixed(1)})`}
                >
                  <title>{`Phase ${side.phase} coil side · current ${side.direction === '⊙' ? 'out of' : 'into'} the screen`}</title>
                  <circle r="11" fill="rgba(8, 13, 22, 0.9)" stroke={BACK_EMF_PHASE_COLORS[side.phase]} strokeWidth="1.8" />
                  <text y="-1" textAnchor="middle" className="lesson-nine-slot-phase">{side.phase}</text>
                  <text y="8" textAnchor="middle" className="lesson-nine-slot-direction">{side.direction}</text>
                </g>
              );
            })}
          </React.Fragment>
        );
      })}

      <path d={annulusPath(magnetOuterR, statorInnerR)} fill="#f8fafc" stroke="#cbd5e1" strokeWidth="1" />
      <circle cx="260" cy="260" r={magnetOuterR} fill="#101722" stroke="#2f3b52" strokeWidth="2" />

      {showFlux && (
        <g className="learning-flux-layer">
          <path d={annularSectorPath(-18, 18, statorInnerR, 220)} fill="#22d3ee" opacity={statorFluxOpacity} />
          <path d={annularSectorPath(162, 198, statorInnerR, 220)} fill="#22d3ee" opacity={statorFluxOpacity * 0.42} />
          <path d={annularSectorPath(28, 54, statorInnerR, 218)} fill="#67e8f9" opacity={0.16 + sweepProgress * 0.2} />
          <path d={annularSectorPath(208, 234, statorInnerR, 218)} fill="#67e8f9" opacity={0.16 + sweepProgress * 0.2} />
        </g>
      )}

      <g transform={`rotate(${rotorAngle - 90} 260 260)`}>
        {showFlux && (
          <g className="learning-flux-layer">
            <path d={annularSectorPath(magnetNorthCenterDeg - magnetHalfSpanDeg, magnetNorthCenterDeg + magnetHalfSpanDeg, magnetInnerR, magnetOuterR)} fill={DESIGN_MAGNET_N_FILL} opacity="0.52" />
            <path d={annularSectorPath(magnetSouthCenterDeg - magnetHalfSpanDeg, magnetSouthCenterDeg + magnetHalfSpanDeg, magnetInnerR, magnetOuterR)} fill={DESIGN_MAGNET_S_FILL} opacity="0.44" />
          </g>
        )}
        <circle cx="260" cy="260" r={rotorCoreR} fill="url(#lesson-rotor-steel)" stroke="#64748b" strokeWidth="3" />
        <circle cx="260" cy="260" r="78" fill="#263143" stroke="rgba(203,213,225,0.24)" strokeWidth="1.5" />
        <path d={annularSectorPath(magnetNorthCenterDeg + magnetHalfSpanDeg, magnetSouthCenterDeg - magnetHalfSpanDeg, magnetInnerR, magnetOuterR)} fill="#111827" stroke="rgba(148,163,184,0.22)" strokeWidth="1.2" />
        <path d={annularSectorPath(magnetSouthCenterDeg + magnetHalfSpanDeg, 360 - magnetHalfSpanDeg, magnetInnerR, magnetOuterR)} fill="#111827" stroke="rgba(148,163,184,0.22)" strokeWidth="1.2" />
        <path d={annularSectorPath(magnetNorthCenterDeg - magnetHalfSpanDeg, magnetNorthCenterDeg + magnetHalfSpanDeg, magnetInnerR, magnetOuterR)} fill={DESIGN_MAGNET_N_FILL} />
        <path d={annularSectorPath(magnetSouthCenterDeg - magnetHalfSpanDeg, magnetSouthCenterDeg + magnetHalfSpanDeg, magnetInnerR, magnetOuterR)} fill={DESIGN_MAGNET_S_FILL} />
        <path d={annularSectorPath(magnetNorthCenterDeg - magnetHalfSpanDeg, magnetNorthCenterDeg + magnetHalfSpanDeg, magnetInnerR, magnetOuterR)} fill="none" stroke="#fecaca" strokeWidth="1.8" />
        <path d={annularSectorPath(magnetSouthCenterDeg - magnetHalfSpanDeg, magnetSouthCenterDeg + magnetHalfSpanDeg, magnetInnerR, magnetOuterR)} fill="none" stroke="#bfdbfe" strokeWidth="1.8" />
        <circle cx="260" cy="260" r="22" fill="#111827" stroke="#94a3b8" strokeWidth="2" />
        <text x={magnetNLabel.x} y={magnetNLabel.y + 5} textAnchor="middle" className="learning-svg-pole-label">N</text>
        <text x={magnetSLabel.x} y={magnetSLabel.y + 5} textAnchor="middle" className="learning-svg-pole-label">S</text>
      </g>

      {showVectors && (
        <g className="learning-vector-layer">
          <circle cx="260" cy="260" r="9" fill="#cbd5e1" />
          <line x1="260" y1="260" x2="420" y2="260" stroke="#22d3ee" strokeWidth="7" strokeLinecap="round" markerEnd="url(#lesson-arrow-cyan)" />
          <line x1="260" y1="260" x2={rotorEnd.x} y2={rotorEnd.y} stroke="#f59e0b" strokeWidth="7" strokeLinecap="round" markerEnd="url(#lesson-arrow-amber)" />
          <path
            d={previewTorque >= 0 ? 'M365 178A140 140 0 0 1 365 342' : 'M365 342A140 140 0 0 0 365 178'}
            fill="none"
            stroke="#84cc16"
            strokeWidth={3 + Math.min(7, Math.abs(previewTorque) * 2.2)}
            strokeLinecap="round"
            markerEnd="url(#lesson-arrow-green)"
            opacity={0.28 + Math.min(0.7, Math.abs(previewTorque) / 3.2)}
          />
          <path d={buildAngleArc(rotorAngle)} fill="none" stroke="#cbd5e1" strokeWidth="2" strokeDasharray="4 5" />
          <text x={angleLabel.x} y={angleLabel.y} className="learning-svg-label">{rotorAngle.toFixed(0)} deg</text>
          <text x={statorLabel.x} y={statorLabel.y} className="learning-svg-label">stator flux</text>
          <text x={rotorLabel.x} y={rotorLabel.y} className="learning-svg-label">rotor flux</text>
        </g>
      )}
    </svg>
  );
};
