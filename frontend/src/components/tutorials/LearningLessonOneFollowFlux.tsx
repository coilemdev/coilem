import React from 'react';
import type { FollowFluxFieldData, FollowFluxMetrics } from './lessonSolveTypes';
import { useLessonSolveClient } from './lessonSolveClient';
import { useLearningProgress } from './useLearningProgress';
import { MeshViewer } from './MeshViewer';
import type {
  LearningLessonHeaderProgress,
  LearningLessonProgressStep,
  LearningLessonStage,
} from './lessonStage';
import { KnowledgeCheck } from './KnowledgeCheck';
import { FollowFluxDepth3D } from './FollowFluxDepth3D';
import {
  LESSON_ONE_FIELD_MAGNET,
  LESSON_ONE_OPEN_AIR_FIELD,
} from './lessonOneOpenAirField';
import './follow-the-flux.css';

interface LearningLessonOneFollowFluxProps {
  onBackToCatalog: () => void;
  onBackHome: () => void;
  stage?: LearningLessonStage;
  onStageChange?: (stage: LearningLessonStage) => void;
  onHeaderProgressChange?: (progress: LearningLessonHeaderProgress | null) => void;
}

type Prediction = 'closed-loop' | 'stops' | 'straight';
type SolveView = 'air' | 'steel' | 'pair';
type FieldDisplayMode = 'lines' | 'density';
type SteelShape = 'bar' | 'plate' | 'puck';
type SteelInsightAnswer = 'lower-reluctance' | 'stronger-magnet' | 'larger-area';

/**
 * Lesson 1's own phases.
 *
 * Deliberately NOT the shared `LearningLessonStage`: that union is read by ten
 * lessons and both app hosts, and the private workspace stores it in state typed
 * to those three ids. The pair phase is lesson-local, so it rides on the shared
 * 'solve' stage and is distinguished here.
 */
type LessonOnePhase = 'design' | 'solve' | 'pair';
type LessonOneProgressStepId = 'predict' | 'air' | 'steel' | 'pair' | 'check';

const LESSON_ONE_GOALS: Record<LessonOneProgressStepId, { title: string; detail: string }> = {
  predict: {
    title: 'Predict the field path',
    detail: 'Choose what happens after flux leaves the magnet’s north face.',
  },
  air: {
    title: 'Establish the open-air baseline',
    detail: 'Place the magnet, solve it in air, and capture the first field measurements.',
  },
  steel: {
    title: 'Change only the return path',
    detail: 'Add steel near the same magnet and compare the new field with the baseline.',
  },
  pair: {
    title: 'Compare opposite and like poles',
    detail: 'Solve N facing S, flip magnet 2, then solve N facing N with every position held fixed.',
  },
  check: {
    title: 'Explain what the field did',
    detail: 'Use the solved frames to complete the knowledge check.',
  },
};

interface SteelPlacement {
  shape: SteelShape;
  xMm: number;
  yMm: number;
  angleDeg: number;
}

interface MagnetPlacement {
  xMm: number;
  yMm: number;
  angleDeg: number;
}

type DraggableFixtureObject = 'magnet' | 'magnet2' | 'steel';

/** Drags fire far faster than a ~0.5 s solve returns; coalesce them. */
const AUTO_SOLVE_DEBOUNCE_MS = 320;

const STEEL_SHAPES: Record<SteelShape, {
  label: string;
  description: string;
  widthMm: number;
  heightMm: number;
  defaultX: number;
  defaultY: number;
}> = {
  bar: {
    label: 'Tall bar',
    description: 'A narrow bar placed beside the magnet.',
    widthMm: 8,
    heightMm: 28,
    defaultX: 28,
    defaultY: 0,
  },
  plate: {
    label: 'Flat plate',
    description: 'A wide plate placed above the magnet.',
    widthMm: 28,
    heightMm: 8,
    defaultX: 0,
    defaultY: 16,
  },
  puck: {
    label: 'Round puck',
    description: 'A compact circular steel target.',
    widthMm: 16,
    heightMm: 16,
    defaultX: 31,
    defaultY: 0,
  },
};

const normalizeAngleDeg = (angleDeg: number) => {
  const wrapped = ((angleDeg + 180) % 360 + 360) % 360 - 180;
  return Math.abs(wrapped) < 0.05 ? 0 : Math.round(wrapped);
};

const rotatedRectExtents = (halfWidth: number, halfHeight: number, angleDeg: number) => {
  const angleRad = angleDeg * Math.PI / 180;
  const cosine = Math.abs(Math.cos(angleRad));
  const sine = Math.abs(Math.sin(angleRad));
  return {
    x: cosine * halfWidth + sine * halfHeight,
    y: sine * halfWidth + cosine * halfHeight,
  };
};

const pointInLocalFrame = (
  xMm: number,
  yMm: number,
  centerX: number,
  centerY: number,
  angleDeg: number,
) => {
  const angleRad = angleDeg * Math.PI / 180;
  const dx = xMm - centerX;
  const dy = yMm - centerY;
  return {
    x: Math.cos(angleRad) * dx + Math.sin(angleRad) * dy,
    y: -Math.sin(angleRad) * dx + Math.cos(angleRad) * dy,
  };
};

const pointFromLocalFrame = (
  localXMm: number,
  localYMm: number,
  centerX: number,
  centerY: number,
  angleDeg: number,
) => {
  const angleRad = angleDeg * Math.PI / 180;
  return {
    x: centerX + Math.cos(angleRad) * localXMm - Math.sin(angleRad) * localYMm,
    y: centerY + Math.sin(angleRad) * localXMm + Math.cos(angleRad) * localYMm,
  };
};

interface OrientedFixtureRect {
  xMm: number;
  yMm: number;
  halfWidth: number;
  halfHeight: number;
  angleDeg: number;
}

const orientedRectsOverlap = (
  first: OrientedFixtureRect,
  second: OrientedFixtureRect,
  clearanceMm = 0.5,
) => {
  const axesFor = (rect: OrientedFixtureRect) => {
    const angleRad = rect.angleDeg * Math.PI / 180;
    return [
      { x: Math.cos(angleRad), y: Math.sin(angleRad) },
      { x: -Math.sin(angleRad), y: Math.cos(angleRad) },
    ];
  };
  const firstAxes = axesFor(first);
  const secondAxes = axesFor(second);
  const delta = { x: second.xMm - first.xMm, y: second.yMm - first.yMm };
  return [...firstAxes, ...secondAxes].every((axis) => {
    const centerDistance = Math.abs(delta.x * axis.x + delta.y * axis.y);
    const projectedRadius = (rect: OrientedFixtureRect, axes: ReturnType<typeof axesFor>) => (
      rect.halfWidth * Math.abs(axes[0].x * axis.x + axes[0].y * axis.y)
      + rect.halfHeight * Math.abs(axes[1].x * axis.x + axes[1].y * axis.y)
    );
    return centerDistance < projectedRadius(first, firstAxes)
      + projectedRadius(second, secondAxes)
      + clearanceMm;
  });
};

const magnetPlacementIsValid = ({ xMm, yMm, angleDeg }: MagnetPlacement) => {
  const extents = rotatedRectExtents(18, 6, angleDeg);
  return Math.abs(xMm) + extents.x <= 48 && Math.abs(yMm) + extents.y <= 32;
};

const steelPlacementIsValid = (
  { shape, xMm, yMm, angleDeg }: SteelPlacement,
  magnet: MagnetPlacement,
) => {
  const dimensions = STEEL_SHAPES[shape];
  const extents = shape === 'puck'
    ? { x: 8, y: 8 }
    : rotatedRectExtents(dimensions.widthMm / 2, dimensions.heightMm / 2, angleDeg);
  const insideDomain = Math.abs(xMm) + extents.x <= 48
    && Math.abs(yMm) + extents.y <= 32;
  if (!insideDomain) return false;
  if (shape === 'puck') {
    const local = pointInLocalFrame(xMm, yMm, magnet.xMm, magnet.yMm, magnet.angleDeg);
    const dx = Math.max(Math.abs(local.x) - 18, 0);
    const dy = Math.max(Math.abs(local.y) - 6, 0);
    return Math.hypot(dx, dy) >= 8.5;
  }
  return !orientedRectsOverlap(
    { xMm: magnet.xMm, yMm: magnet.yMm, halfWidth: 18, halfHeight: 6, angleDeg: magnet.angleDeg },
    {
      xMm,
      yMm,
      halfWidth: dimensions.widthMm / 2,
      halfHeight: dimensions.heightMm / 2,
      angleDeg,
    },
  );
};

/** Both magnets are the same 36 x 12 mm bar, so one half-extent pair covers both. */
const magnet2PlacementIsValid = (magnet2: MagnetPlacement, magnet: MagnetPlacement) => {
  const extents = rotatedRectExtents(18, 6, magnet2.angleDeg);
  const insideDomain = Math.abs(magnet2.xMm) + extents.x <= 48
    && Math.abs(magnet2.yMm) + extents.y <= 32;
  if (!insideDomain) return false;
  return !orientedRectsOverlap(
    { xMm: magnet.xMm, yMm: magnet.yMm, halfWidth: 18, halfHeight: 6, angleDeg: magnet.angleDeg },
    { xMm: magnet2.xMm, yMm: magnet2.yMm, halfWidth: 18, halfHeight: 6, angleDeg: magnet2.angleDeg },
  );
};

/**
 * Which way the pair pushes, from the poles that actually face each other.
 *
 * Not simply "parallel magnetization attracts": that only holds when the magnets
 * lie end to end. Side by side, parallel magnetization repels. So project each
 * magnetization onto the line joining the centres and compare the poles those
 * projections present. Same sign means one shows N to the other's S — attraction.
 * Returns null when either magnet is too close to broadside for a pole face to be
 * the story.
 */
const pairPoleFacing = (magnet: MagnetPlacement, magnet2: MagnetPlacement) => {
  const dx = magnet2.xMm - magnet.xMm;
  const dy = magnet2.yMm - magnet.yMm;
  const separation = Math.hypot(dx, dy);
  if (separation < 1) return null;
  const projection = (angleDeg: number) => {
    const angleRad = angleDeg * Math.PI / 180;
    return (Math.cos(angleRad) * dx + Math.sin(angleRad) * dy) / separation;
  };
  const first = projection(magnet.angleDeg);
  const second = projection(magnet2.angleDeg);
  // cos 70 deg: past this either magnet presents a long side, not a pole.
  if (Math.abs(first) < 0.34 || Math.abs(second) < 0.34) return null;
  return {
    arrangement: first * second > 0 ? ('attract' as const) : ('repel' as const),
    /** The pole magnet 1 turns toward magnet 2. */
    firstFacingPole: first > 0 ? ('N' as const) : ('S' as const),
    /** The pole magnet 2 turns back toward magnet 1. */
    secondFacingPole: second > 0 ? ('S' as const) : ('N' as const),
    separationMm: separation,
  };
};

/**
 * Where the pair phase puts the two magnets on first entry: end to end with a
 * 4 mm gap, both inside the domain (a 36 mm bar needs |x| <= 30 at 0 deg).
 */
const PAIR_LAYOUT = {
  first: { xMm: -20, yMm: 0, angleDeg: 0 },
  second: { xMm: 20, yMm: 0, angleDeg: 0 },
} satisfies Record<'first' | 'second', MagnetPlacement>;

const samePlacement = (first: MagnetPlacement, second: MagnetPlacement) => (
  first.xMm === second.xMm && first.yMm === second.yMm && first.angleDeg === second.angleDeg
);

/**
 * Whether a solved frame was computed with magnet 1 where it now is. Swapping
 * phases moves magnet 1 and then puts it back, so blanket-marking the other
 * frames stale would burn a solve each way re-computing an identical field.
 */
const solvedWithMagnetAt = (
  solved: FollowFluxFieldData | null,
  placement: MagnetPlacement,
) => Boolean(
  solved
  && solved.magnet_center_x_mm === placement.xMm
  && solved.magnet_center_y_mm === placement.yMm
  && solved.magnet_angle_deg === placement.angleDeg,
);

/**
 * S/N labels 9 mm either side of a magnet centre, along its magnetization, sharing
 * the body's drag key so grabbing a pole moves the magnet.
 */
const poleLabelsFor = (
  centerXMm: number,
  centerYMm: number,
  angleDeg: number,
  dragKey: string,
) => {
  const angleRad = angleDeg * Math.PI / 180;
  const offsetXMm = 9 * Math.cos(angleRad);
  const offsetYMm = 9 * Math.sin(angleRad);
  return [
    {
      xMm: centerXMm - offsetXMm,
      yMm: centerYMm - offsetYMm,
      label: 'S',
      tone: 'south' as const,
      dragKey,
    },
    {
      xMm: centerXMm + offsetXMm,
      yMm: centerYMm + offsetYMm,
      label: 'N',
      tone: 'north' as const,
      dragKey,
    },
  ];
};

const PREDICTIONS: Array<{ id: Prediction; label: string }> = [
  { id: 'stops', label: 'It stops after leaving the north face.' },
  { id: 'closed-loop', label: 'It loops through space and returns to the south face.' },
  { id: 'straight', label: 'It continues in a straight line forever.' },
];

const STEEL_INSIGHT_OPTIONS: Array<{ id: SteelInsightAnswer; label: string }> = [
  {
    id: 'stronger-magnet',
    label: 'The nearby steel permanently strengthens the magnet, so it produces more flux everywhere.',
  },
  {
    id: 'larger-area',
    label: 'The steel increases the magnet’s pole-face area, so the same total flux appears as a higher |B|.',
  },
  {
    id: 'lower-reluctance',
    label: 'Steel has much lower reluctance than air, so the unchanged magnet drives more flux through the same pole-face area.',
  },
];

const QUIZ = [
  {
    id: 'flux-loop',
    prompt: 'What do magnetic field lines do?',
    options: ['End in open air', 'Form closed loops', 'Exist only inside steel'],
    correctIndex: 1,
    explanation: 'Magnetic flux has no start or end: every field line closes on itself.',
  },
  {
    id: 'comparison',
    prompt: 'What does the movable-steel comparison demonstrate?',
    options: [
      'Moving steel permanently strengthens the magnet',
      'Steel has no effect unless it touches the magnet',
      'Nearby steel can redirect and concentrate a magnet’s field',
    ],
    correctIndex: 2,
    explanation: 'High-permeability steel changes the reluctance around the magnet, so the field redistributes toward it.',
  },
  {
    id: 'density-versus-flux',
    prompt: 'Two flux surfaces have the same average normal B, but one has twice the area. What changes?',
    options: [
      'The larger surface carries twice the total flux',
      'Both surfaces carry the same total flux',
      'The smaller surface carries twice the total flux',
    ],
    correctIndex: 0,
    explanation: 'Total flux is the normal flux density integrated over area. At the same average B, doubling area doubles total flux.',
  },
  {
    id: 'airgap-torque',
    prompt: 'Why is the stronger N→S cross-gap flux useful in a motor?',
    options: [
      'It permanently strengthens both magnets',
      'It gives the rotor field more opportunity to interact with stator current and produce force or torque',
      'It eliminates the need for alternating motor poles',
    ],
    correctIndex: 1,
    explanation: 'Motor force and torque come from interacting fields. Useful rotor flux must cross the air gap to interact strongly with the stator current; flipping a magnet redirects that flux but does not strengthen or weaken the magnet.',
  },
];

const formatTesla = (value?: number | null, digits = 3) => (
  typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(digits)} T` : '—'
);

const formatMicroWebers = (value?: number | null, digits = 1) => (
  typeof value === 'number' && Number.isFinite(value)
    ? `${(value * 1.0e6).toFixed(digits)} \u00b5Wb`
    : '—'
);

const scaleFluxMetricsForDepth = (
  metrics: FollowFluxMetrics,
  assumedDepthMm: number,
): FollowFluxMetrics => {
  const solvedDepthMm = metrics.teaching_depth_mm;
  if (!solvedDepthMm || solvedDepthMm <= 0) return metrics;
  const depthScale = assumedDepthMm / solvedDepthMm;
  return {
    ...metrics,
    teaching_depth_mm: assumedDepthMm,
    north_face_area_mm2: metrics.north_face_area_mm2 === undefined
      ? undefined
      : metrics.north_face_area_mm2 * depthScale,
    north_face_flux_wb: metrics.north_face_flux_wb === undefined
      ? undefined
      : metrics.north_face_flux_wb * depthScale,
    south_face_flux_wb: metrics.south_face_flux_wb === undefined
      ? undefined
      : metrics.south_face_flux_wb * depthScale,
  };
};

const percentChange = (before?: number, after?: number) => {
  if (!before || after === undefined) return null;
  return ((after - before) / before) * 100;
};

/**
 * Predict-stage fixture diagram.
 *
 * The loop case draws the REAL solved field for this exact fixture (one magnet,
 * open air) from LESSON_ONE_OPEN_AIR_FIELD — precomputed iso-Az polylines, no
 * solver call. The two wrong-answer cases stay schematic on purpose: they
 * illustrate a model the learner is about to disprove, so there is no real field
 * to show.
 *
 * Everything shares one mm -> viewBox transform derived from the baked data, so
 * the magnet block cannot drift out of register with the field lines, and the
 * magnet keeps its true 3:1 aspect instead of the elongated block the
 * hand-drawn version used.
 */
const FIELD_VIEW = { width: 760, height: 430, pad: 14 };

const FIELD_TRANSFORM = (() => {
  let xMax = LESSON_ONE_FIELD_MAGNET.xMax;
  let yMax = LESSON_ONE_FIELD_MAGNET.yMax;
  for (const level of LESSON_ONE_OPEN_AIR_FIELD) {
    for (const path of level.paths) {
      for (let i = 0; i < path.length; i += 2) {
        xMax = Math.max(xMax, Math.abs(path[i]));
        yMax = Math.max(yMax, Math.abs(path[i + 1]));
      }
    }
  }
  // The fixture is symmetric about both axes, so fit a symmetric box and keep a
  // single uniform scale — anisotropic scaling would misrepresent the field.
  const scale = Math.min(
    (FIELD_VIEW.width / 2 - FIELD_VIEW.pad) / xMax,
    (FIELD_VIEW.height / 2 - FIELD_VIEW.pad) / yMax,
  );
  const cx = FIELD_VIEW.width / 2;
  const cy = FIELD_VIEW.height / 2;
  return {
    scale,
    // Solver +y points up; SVG +y points down.
    x: (xMm: number) => cx + xMm * scale,
    y: (yMm: number) => cy - yMm * scale,
  };
})();

const MAGNET_RECT = {
  left: FIELD_TRANSFORM.x(LESSON_ONE_FIELD_MAGNET.xMin),
  right: FIELD_TRANSFORM.x(LESSON_ONE_FIELD_MAGNET.xMax),
  top: FIELD_TRANSFORM.y(LESSON_ONE_FIELD_MAGNET.yMax),
  bottom: FIELD_TRANSFORM.y(LESSON_ONE_FIELD_MAGNET.yMin),
  midX: FIELD_TRANSFORM.x(0),
  midY: FIELD_TRANSFORM.y(0),
};

const SOLVED_FIELD_PATHS: string[] = LESSON_ONE_OPEN_AIR_FIELD.flatMap((level) =>
  level.paths.map((path) => {
    let d = '';
    for (let i = 0; i < path.length; i += 2) {
      const x = FIELD_TRANSFORM.x(path[i]).toFixed(1);
      const y = FIELD_TRANSFORM.y(path[i + 1]).toFixed(1);
      d += i === 0 ? `M${x} ${y}` : ` L${x} ${y}`;
    }
    return `${d} Z`;
  }),
);

/**
 * Direction arrowheads, drawn as small filled triangles rather than SVG markers
 * so they sit mid-line instead of only at a path end. The baked tangent is
 * already oriented along B; y is negated here because SVG y grows downward.
 */
const SOLVED_FIELD_ARROWS: string[] = LESSON_ONE_OPEN_AIR_FIELD.flatMap((level) =>
  level.arrows.map(([xMm, yMm, dxMm, dyMm]) => {
    const x = FIELD_TRANSFORM.x(xMm);
    const y = FIELD_TRANSFORM.y(yMm);
    const dx = dxMm;
    const dy = -dyMm;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    // px/py is the unit normal; 7 long, 4.4 wide reads at this scale.
    const px = -uy;
    const py = ux;
    const tipX = x + ux * 4.6;
    const tipY = y + uy * 4.6;
    const backX = x - ux * 2.4;
    const backY = y - uy * 2.4;
    return [
      `M${tipX.toFixed(1)} ${tipY.toFixed(1)}`,
      `L${(backX + px * 2.2).toFixed(1)} ${(backY + py * 2.2).toFixed(1)}`,
      `L${(backX - px * 2.2).toFixed(1)} ${(backY - py * 2.2).toFixed(1)}`,
      'Z',
    ].join(' ');
  }),
);

const FieldFixtureDiagram: React.FC<{ prediction: Prediction | null }> = ({ prediction }) => (
  <svg
    className="follow-flux-concept-svg"
    viewBox={prediction === 'closed-loop'
      ? `0 0 ${FIELD_VIEW.width} ${FIELD_VIEW.height}`
      : '80 90 600 250'}
    role="img"
    aria-label={prediction === 'closed-loop'
      ? 'Solved field of a bar magnet in open air: closed flux paths leaving the north face and returning to the south face'
      : prediction === 'stops'
        ? 'Prediction showing magnetic field paths stopping in open air'
        : prediction === 'straight'
          ? 'Prediction showing magnetic field paths continuing away in straight lines'
          : 'Bar magnet with an unknown return path through air'}
  >
    <defs>
      <marker
        id="follow-flux-arrow"
        markerWidth="7"
        markerHeight="7"
        refX="6.5"
        refY="3.5"
        orient="auto"
        markerUnits="userSpaceOnUse"
      >
        <path d="M0.75 0.75 L6.25 3.5 L0.75 6.25" className="follow-flux-arrowhead" />
      </marker>
      <filter id="follow-flux-glow">
        <feGaussianBlur stdDeviation="5" result="blur" />
        <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
    </defs>

    <rect
      x={MAGNET_RECT.left}
      y={MAGNET_RECT.top}
      width={MAGNET_RECT.midX - MAGNET_RECT.left}
      height={MAGNET_RECT.bottom - MAGNET_RECT.top}
      rx="5"
      fill="#2563eb"
    />
    <rect
      x={MAGNET_RECT.midX}
      y={MAGNET_RECT.top}
      width={MAGNET_RECT.right - MAGNET_RECT.midX}
      height={MAGNET_RECT.bottom - MAGNET_RECT.top}
      rx="5"
      fill="#ef4444"
    />
    <text
      x={(MAGNET_RECT.left + MAGNET_RECT.midX) / 2}
      y={MAGNET_RECT.midY + 11}
      textAnchor="middle"
      className="follow-flux-pole"
    >S</text>
    <text
      x={(MAGNET_RECT.midX + MAGNET_RECT.right) / 2}
      y={MAGNET_RECT.midY + 11}
      textAnchor="middle"
      className="follow-flux-pole"
    >N</text>

    {prediction === 'closed-loop' ? (
      // Drawn after the magnet so the run through the body is visible and each
      // line reads as one closed loop; the pole letters are re-stamped on top.
      <g className="follow-flux-prediction-field is-loop is-solved">
        {SOLVED_FIELD_PATHS.map((d, index) => (
          <path key={`line-${index}`} d={d} />
        ))}
        {SOLVED_FIELD_ARROWS.map((d, index) => (
          <path key={`arrow-${index}`} d={d} className="follow-flux-field-arrow" />
        ))}
        <text
          x={(MAGNET_RECT.left + MAGNET_RECT.midX) / 2}
          y={MAGNET_RECT.midY + 11}
          textAnchor="middle"
          className="follow-flux-pole"
        >S</text>
        <text
          x={(MAGNET_RECT.midX + MAGNET_RECT.right) / 2}
          y={MAGNET_RECT.midY + 11}
          textAnchor="middle"
          className="follow-flux-pole"
        >N</text>
      </g>
    ) : prediction === 'stops' ? (
      <g className="follow-flux-prediction-field is-stopped">
        <path d={`M${MAGNET_RECT.right} ${MAGNET_RECT.top + 8} C${MAGNET_RECT.right + 44} ${MAGNET_RECT.top - 8} ${MAGNET_RECT.right + 76} ${MAGNET_RECT.top - 40} ${MAGNET_RECT.right + 104} ${MAGNET_RECT.top - 72}`} />
        <path d={`M${MAGNET_RECT.right} ${MAGNET_RECT.midY} L${MAGNET_RECT.right + 120} ${MAGNET_RECT.midY}`} />
        <path d={`M${MAGNET_RECT.right} ${MAGNET_RECT.bottom - 8} C${MAGNET_RECT.right + 44} ${MAGNET_RECT.bottom + 8} ${MAGNET_RECT.right + 76} ${MAGNET_RECT.bottom + 40} ${MAGNET_RECT.right + 104} ${MAGNET_RECT.bottom + 72}`} />
        <circle cx={MAGNET_RECT.right + 104} cy={MAGNET_RECT.top - 72} r="6" />
        <circle cx={MAGNET_RECT.right + 120} cy={MAGNET_RECT.midY} r="6" />
        <circle cx={MAGNET_RECT.right + 104} cy={MAGNET_RECT.bottom + 72} r="6" />
      </g>
    ) : prediction === 'straight' ? (
      <g className="follow-flux-prediction-field is-straight">
        <path d={`M${MAGNET_RECT.right} ${MAGNET_RECT.top + 8} L${MAGNET_RECT.right + 144} ${MAGNET_RECT.top - 88}`} markerEnd="url(#follow-flux-arrow)" />
        <path d={`M${MAGNET_RECT.right} ${MAGNET_RECT.midY} L${MAGNET_RECT.right + 144} ${MAGNET_RECT.midY}`} markerEnd="url(#follow-flux-arrow)" />
        <path d={`M${MAGNET_RECT.right} ${MAGNET_RECT.bottom - 8} L${MAGNET_RECT.right + 144} ${MAGNET_RECT.bottom + 88}`} markerEnd="url(#follow-flux-arrow)" />
      </g>
    ) : (
      <>
        <path d={`M${MAGNET_RECT.right - 12} ${MAGNET_RECT.top + 4} C${MAGNET_RECT.right + 40} ${MAGNET_RECT.top - 18} ${MAGNET_RECT.right + 80} ${MAGNET_RECT.top - 50} ${MAGNET_RECT.right + 114} ${MAGNET_RECT.top - 88}`} className="follow-flux-question-line" markerEnd="url(#follow-flux-arrow)" />
        <path d={`M${MAGNET_RECT.right - 12} ${MAGNET_RECT.bottom - 4} C${MAGNET_RECT.right + 40} ${MAGNET_RECT.bottom + 18} ${MAGNET_RECT.right + 80} ${MAGNET_RECT.bottom + 50} ${MAGNET_RECT.right + 114} ${MAGNET_RECT.bottom + 88}`} className="follow-flux-question-line" markerEnd="url(#follow-flux-arrow)" />
        <text x={MAGNET_RECT.right + 70} y={MAGNET_RECT.midY} textAnchor="middle" className="follow-flux-question" filter="url(#follow-flux-glow)">Then what?</text>
      </>
    )}
  </svg>
);

/**
 * One draggable bar magnet in the placement domain. Extracted so the pair phase's
 * second magnet is drawn from exactly this definition instead of a copy that could
 * drift from it.
 */
const DraggableMagnetBody: React.FC<{
  drawXMm: number;
  drawYMm: number;
  drawAngleDeg: number;
  isDragging: boolean;
  /** Only the first magnet carries the 36 mm dimension line; twice is clutter. */
  showDimension: boolean;
  /** Shown when a second magnet is present, so the two can be told apart. */
  badge?: string;
  dragLabel: string;
  rotateLabel: string;
  onBeginDrag: (event: React.MouseEvent) => void;
  onBeginRotate: (event: React.MouseEvent) => void;
}> = ({
  drawXMm,
  drawYMm,
  drawAngleDeg,
  isDragging,
  showDimension,
  badge,
  dragLabel,
  rotateLabel,
  onBeginDrag,
  onBeginRotate,
}) => (
  <g
    className={`follow-flux-draggable-object is-magnet${isDragging ? ' is-dragging' : ''}`}
    transform={`translate(${drawXMm} ${-drawYMm}) rotate(${-drawAngleDeg})`}
    onMouseDown={onBeginDrag}
    role="button"
    aria-label={dragLabel}
  >
    <rect x="-18" y="-6" width="18" height="12" rx="0.8" fill="#2563eb" />
    <rect x="0" y="-6" width="18" height="12" rx="0.8" fill="#ef4444" />
    <rect className="follow-flux-magnet-outline" x="-18" y="-6" width="36" height="12" rx="0.8" />
    <text x="-9" y="1.7" textAnchor="middle" className="follow-flux-domain-pole" transform={`rotate(${drawAngleDeg} -9 1.7)`}>S</text>
    <text x="9" y="1.7" textAnchor="middle" className="follow-flux-domain-pole" transform={`rotate(${drawAngleDeg} 9 1.7)`}>N</text>
    {badge ? (
      <text x="0" y="1.7" textAnchor="middle" className="follow-flux-magnet-badge" transform={`rotate(${drawAngleDeg} 0 1.7)`}>{badge}</text>
    ) : null}
    <line className="follow-flux-rotation-stem" x1="0" y1="-6" x2="0" y2="-11" />
    <circle
      className="follow-flux-rotation-handle"
      cx="0"
      cy="-12"
      r="1.8"
      onMouseDown={onBeginRotate}
      role="button"
      aria-label={rotateLabel}
    />
    {showDimension ? (
      <>
        <line className="follow-flux-dimension-line" x1="-18" y1="12" x2="18" y2="12" />
        <line className="follow-flux-dimension-tick" x1="-18" y1="9.5" x2="-18" y2="14.5" />
        <line className="follow-flux-dimension-tick" x1="18" y1="9.5" x2="18" y2="14.5" />
        <text x="0" y="17" textAnchor="middle" className="follow-flux-dimension-label" transform={`rotate(${drawAngleDeg} 0 17)`}>36 mm</text>
      </>
    ) : null}
  </g>
);

const UnmeshedFieldDomain: React.FC<{
  magnet: MagnetPlacement;
  magnet2?: MagnetPlacement;
  steel?: SteelPlacement;
  disabled?: boolean;
  onObjectDrop: (
    object: DraggableFixtureObject,
    nextCenter: { xMm: number; yMm: number },
  ) => void;
  onObjectRotate: (object: DraggableFixtureObject, angleDeg: number) => void;
  onObjectSelect?: (object: DraggableFixtureObject) => void;
}> = ({ magnet, magnet2, steel, disabled = false, onObjectDrop, onObjectRotate, onObjectSelect }) => {
  const svgRef = React.useRef<SVGSVGElement>(null);
  const [drag, setDrag] = React.useState<{
    object: DraggableFixtureObject;
    startPointerX: number;
    startPointerY: number;
    startCenterX: number;
    startCenterY: number;
    deltaX: number;
    deltaY: number;
  } | null>(null);
  const dragRef = React.useRef<typeof drag>(null);
  const [rotationDrag, setRotationDrag] = React.useState<{
    object: DraggableFixtureObject;
    startPointerAngleDeg: number;
    startObjectAngleDeg: number;
    angleDeg: number;
  } | null>(null);
  const rotationDragRef = React.useRef<typeof rotationDrag>(null);
  const steelDimensions = steel ? STEEL_SHAPES[steel.shape] : null;
  const placementFor = (object: DraggableFixtureObject): MagnetPlacement | SteelPlacement | undefined => {
    if (object === 'magnet') return magnet;
    if (object === 'magnet2') return magnet2;
    return steel;
  };
  const magnetDrawX = magnet.xMm + (drag?.object === 'magnet' ? drag.deltaX : 0);
  const magnetDrawY = magnet.yMm + (drag?.object === 'magnet' ? drag.deltaY : 0);
  const magnet2DrawX = magnet2 ? magnet2.xMm + (drag?.object === 'magnet2' ? drag.deltaX : 0) : 0;
  const magnet2DrawY = magnet2 ? magnet2.yMm + (drag?.object === 'magnet2' ? drag.deltaY : 0) : 0;
  const steelDrawX = steel ? steel.xMm + (drag?.object === 'steel' ? drag.deltaX : 0) : 0;
  const steelDrawY = steel ? steel.yMm + (drag?.object === 'steel' ? drag.deltaY : 0) : 0;
  const magnetDrawAngle = rotationDrag?.object === 'magnet' ? rotationDrag.angleDeg : magnet.angleDeg;
  const magnet2DrawAngle = magnet2
    ? rotationDrag?.object === 'magnet2' ? rotationDrag.angleDeg : magnet2.angleDeg
    : 0;
  const steelDrawAngle = steel
    ? rotationDrag?.object === 'steel' ? rotationDrag.angleDeg : steel.angleDeg
    : 0;

  const clientToModel = (clientX: number, clientY: number) => {
    const svg = svgRef.current;
    const matrix = svg?.getScreenCTM();
    if (!svg || !matrix) return null;
    const point = svg.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const transformed = point.matrixTransform(matrix.inverse());
    return { x: transformed.x, y: -transformed.y };
  };

  const beginDrag = (event: React.MouseEvent, object: DraggableFixtureObject) => {
    if (disabled || event.button !== 0) return;
    const pointer = clientToModel(event.clientX, event.clientY);
    if (!pointer) return;
    const center = placementFor(object);
    if (!center) return;
    event.preventDefault();
    event.stopPropagation();
    onObjectSelect?.(object);
    const nextDrag = {
      object,
      startPointerX: pointer.x,
      startPointerY: pointer.y,
      startCenterX: center.xMm,
      startCenterY: center.yMm,
      deltaX: 0,
      deltaY: 0,
    };
    dragRef.current = nextDrag;
    setDrag(nextDrag);
  };

  const beginRotation = (event: React.MouseEvent, object: DraggableFixtureObject) => {
    if (disabled || event.button !== 0) return;
    const pointer = clientToModel(event.clientX, event.clientY);
    const placement = placementFor(object);
    if (!pointer || !placement || (object === 'steel' && steel?.shape === 'puck')) return;
    event.preventDefault();
    event.stopPropagation();
    onObjectSelect?.(object);
    const nextRotation = {
      object,
      startPointerAngleDeg: Math.atan2(pointer.y - placement.yMm, pointer.x - placement.xMm) * 180 / Math.PI,
      startObjectAngleDeg: placement.angleDeg,
      angleDeg: placement.angleDeg,
    };
    rotationDragRef.current = nextRotation;
    setRotationDrag(nextRotation);
  };

  const moveDrag = (event: React.MouseEvent) => {
    const currentRotation = rotationDragRef.current;
    if (currentRotation) {
      const pointer = clientToModel(event.clientX, event.clientY);
      const placement = placementFor(currentRotation.object);
      if (!pointer || !placement) return;
      const pointerAngleDeg = Math.atan2(
        pointer.y - placement.yMm,
        pointer.x - placement.xMm,
      ) * 180 / Math.PI;
      const angleDeg = normalizeAngleDeg(
        currentRotation.startObjectAngleDeg
        + normalizeAngleDeg(pointerAngleDeg - currentRotation.startPointerAngleDeg),
      );
      const nextRotation = { ...currentRotation, angleDeg };
      rotationDragRef.current = nextRotation;
      setRotationDrag(nextRotation);
      return;
    }
    const current = dragRef.current;
    if (!current) return;
    const pointer = clientToModel(event.clientX, event.clientY);
    if (!pointer) return;
    const nextDrag = {
      ...current,
      deltaX: pointer.x - current.startPointerX,
      deltaY: pointer.y - current.startPointerY,
    };
    dragRef.current = nextDrag;
    setDrag(nextDrag);
  };

  const finishDrag = () => {
    const currentRotation = rotationDragRef.current;
    if (currentRotation) {
      rotationDragRef.current = null;
      onObjectRotate(currentRotation.object, currentRotation.angleDeg);
      setRotationDrag(null);
      return;
    }
    const current = dragRef.current;
    if (!current) return;
    dragRef.current = null;
    onObjectDrop(current.object, {
      xMm: Math.round(current.startCenterX + current.deltaX),
      yMm: Math.round(current.startCenterY + current.deltaY),
    });
    setDrag(null);
  };

  return (
  <div className="follow-flux-geometry-card">
    <header>
      <h3>
        {magnet2
          ? 'Two magnets'
          : steel
            ? `Magnet + ${steelDimensions?.label.toLowerCase()}`
            : 'Magnet in open air'}
      </h3>
      <span>
        {magnet2
          ? `Drag either magnet to move, cyan handles to rotate · M1 ${magnet.angleDeg.toFixed(0)}° · M2 ${magnet2.angleDeg.toFixed(0)}°`
          : steel
            ? `Drag bodies to move, cyan handles to rotate · magnet ${magnet.angleDeg.toFixed(0)}° · steel ${steel.angleDeg.toFixed(0)}°`
            : `Drag body to move, cyan handle to rotate · center (${magnet.xMm.toFixed(0)}, ${magnet.yMm.toFixed(0)}) mm · ${magnet.angleDeg.toFixed(0)}°`}
      </span>
    </header>
    <div className="follow-flux-geometry-canvas">
      <svg
        ref={svgRef}
        viewBox="-55 -39 110 78"
        role="img"
        aria-label={magnet2
          ? 'Fixed field domain with two independently draggable magnets'
          : 'Fixed field domain with independently draggable magnet and steel'}
        onMouseMove={moveDrag}
        onMouseUp={finishDrag}
        onMouseLeave={finishDrag}
      >
        <rect className="follow-flux-domain-fill" x="-50" y="-34" width="100" height="68" rx="1" />
        <line className="follow-flux-domain-axis" x1="-50" y1="0" x2="50" y2="0" />
        <line className="follow-flux-domain-axis" x1="0" y1="-34" x2="0" y2="34" />
        <DraggableMagnetBody
          drawXMm={magnetDrawX}
          drawYMm={magnetDrawY}
          drawAngleDeg={magnetDrawAngle}
          isDragging={drag?.object === 'magnet'}
          showDimension
          badge={magnet2 ? '1' : undefined}
          dragLabel={magnet2 ? 'Drag first permanent magnet' : 'Drag permanent magnet'}
          rotateLabel={magnet2 ? 'Rotate first permanent magnet' : 'Rotate permanent magnet'}
          onBeginDrag={(event) => beginDrag(event, 'magnet')}
          onBeginRotate={(event) => beginRotation(event, 'magnet')}
        />
        {magnet2 ? (
          <DraggableMagnetBody
            drawXMm={magnet2DrawX}
            drawYMm={magnet2DrawY}
            drawAngleDeg={magnet2DrawAngle}
            isDragging={drag?.object === 'magnet2'}
            showDimension={false}
            badge="2"
            dragLabel="Drag second permanent magnet"
            rotateLabel="Rotate second permanent magnet"
            onBeginDrag={(event) => beginDrag(event, 'magnet2')}
            onBeginRotate={(event) => beginRotation(event, 'magnet2')}
          />
        ) : null}
        {steel && steelDimensions ? (
          <g
            className={`follow-flux-draggable-object is-steel${drag?.object === 'steel' ? ' is-dragging' : ''}`}
            transform={`translate(${steelDrawX} ${-steelDrawY}) rotate(${-steelDrawAngle})`}
            onMouseDown={(event) => beginDrag(event, 'steel')}
            role="button"
            aria-label="Drag steel object"
          >
            {steel.shape === 'puck' ? (
              <circle className="follow-flux-steel-object" cx={0} cy={0} r={8} />
            ) : (
              <rect
                className="follow-flux-steel-object"
                x={-steelDimensions.widthMm / 2}
                y={-steelDimensions.heightMm / 2}
                width={steelDimensions.widthMm}
                height={steelDimensions.heightMm}
                rx="0.8"
              />
            )}
            <text x={0} y={0.9} textAnchor="middle" className="follow-flux-steel-label" transform={`rotate(${steelDrawAngle} 0 0.9)`}>steel</text>
            {steel.shape !== 'puck' ? (
              <>
                <line
                  className="follow-flux-rotation-stem"
                  x1="0"
                  y1={-steelDimensions.heightMm / 2}
                  x2="0"
                  y2={-steelDimensions.heightMm / 2 - 5}
                />
                <circle
                  className="follow-flux-rotation-handle"
                  cx="0"
                  cy={-steelDimensions.heightMm / 2 - 6}
                  r="1.8"
                  onMouseDown={(event) => beginRotation(event, 'steel')}
                  role="button"
                  aria-label="Rotate steel object"
                />
              </>
            ) : null}
          </g>
        ) : null}
      </svg>
    </div>
  </div>
  );
};

const FluxGateReadout: React.FC<{ metrics: FollowFluxMetrics }> = ({ metrics }) => {
  if (
    metrics.north_face_mean_bn_t === undefined
    || metrics.north_face_area_mm2 === undefined
    || metrics.north_face_flux_wb === undefined
    || metrics.teaching_depth_mm === undefined
  ) return null;

  return (
    <section className="follow-flux-gate-readout" aria-label="North-face total flux measurement">
      <header>
        <div><strong>North-face flux surface</strong><span>Solver integral</span></div>
        <code>&Phi; = &int; B<sub>n</sub> dA</code>
      </header>
      <div className="follow-flux-gate-equation" aria-label="Average normal flux density times gate area equals total flux">
        <div><span>Mean B<sub>n</sub></span><strong>{formatTesla(metrics.north_face_mean_bn_t)}</strong></div>
        <b>&times;</b>
        <div><span>Surface area</span><strong>{metrics.north_face_area_mm2.toFixed(0)} mm<sup>2</sup></strong></div>
        <b>=</b>
        <div className="is-total"><span>Total &Phi;</span><strong>{formatMicroWebers(metrics.north_face_flux_wb)}</strong></div>
      </div>
      <p>
        12 mm pole face &times; {metrics.teaching_depth_mm.toFixed(0)} mm assumed Z depth.
        {metrics.south_face_flux_wb !== undefined
          ? ` South-face surface: ${formatMicroWebers(metrics.south_face_flux_wb)}; flux may also cross the magnet's long faces.`
          : ''}
      </p>
    </section>
  );
};

const PhysicalDepthInset: React.FC<{
  depthMm: number;
  metrics: FollowFluxMetrics;
  onDepthChange: (depthMm: number) => void;
}> = ({ depthMm, metrics, onDepthChange }) => {
  const frontX = 42;
  const frontY = 73;
  const magnetWidth = 142;
  const magnetHeight = 50;
  const magnetMiddleX = frontX + magnetWidth / 2;
  const depthOffsetX = 26 + ((depthMm - 5) / 15) * 28;
  const depthOffsetY = -depthOffsetX * 0.44;
  const northX = frontX + magnetWidth;
  const backY = frontY + depthOffsetY;
  const fluxSurfaceCenterX = northX + depthOffsetX / 2;
  const fluxSurfaceCenterY = frontY + magnetHeight / 2 + depthOffsetY / 2;
  const fluxSurfaceLabelX = Math.min(250, northX + depthOffsetX + 26);
  const fluxSurfaceLabelY = frontY + magnetHeight + 18;
  const polygon = (points: Array<[number, number]>) => points.map(([x, y]) => `${x},${y}`).join(' ');
  const frontTopFieldPath = `M ${northX} ${frontY + 12} C 258 58, 238 23, 148 19 C 70 16, 22 39, ${frontX} ${frontY + 12}`;
  const frontBottomFieldPath = `M ${northX} ${frontY + 38} C 258 127, 238 157, 148 160 C 72 162, 24 143, ${frontX} ${frontY + 38}`;
  const backTopFieldPath = `M ${northX + depthOffsetX} ${backY + 13} C 276 ${Math.max(13, backY - 10)}, 241 8, 151 10 C 82 9, 40 ${Math.max(17, backY - 5)}, ${frontX + depthOffsetX} ${backY + 13}`;
  const backBottomFieldPath = `M ${northX + depthOffsetX} ${backY + 37} C 274 112, 239 145, 151 148 C 82 149, 42 125, ${frontX + depthOffsetX} ${backY + 37}`;
  const illustrativeFieldPaths = [
    backTopFieldPath,
    frontTopFieldPath,
    backBottomFieldPath,
    frontBottomFieldPath,
  ];

  return (
    <section id="follow-flux-depth-inset" className="follow-flux-depth-inset" aria-label="3D extrusion of the 2D magnetic solution">
      <header>
        <div><strong>Physical depth</strong><span>2D field paths repeated through Z</span></div>
        <em>Illustrative · not 3D FEM</em>
      </header>
      <svg viewBox="0 0 290 168" role="img" aria-label={`Bar magnet extruded ${depthMm} millimeters along Z with illustrative magnetic field loops and a cyan north-pole flux surface`}>
        <defs>
          <marker id="follow-flux-depth-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" />
          </marker>
          <marker id="follow-flux-depth-field-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path className="is-field-marker" d="M 0 0 L 10 5 L 0 10 z" />
          </marker>
        </defs>

        <g className="follow-flux-depth-field-lines" aria-label="Illustrative field paths copied from the 2D solution through the front and back Z planes">
          {illustrativeFieldPaths.map((path, index) => (
            <React.Fragment key={path}>
              <path
                className={`is-depth-field-line${index % 2 === 0 ? ' is-back-plane' : ' is-front-plane'}`}
                d={path}
                markerEnd="url(#follow-flux-depth-field-arrow)"
              />
              <path
                className={`is-depth-field-flow${index % 2 === 0 ? ' is-back-plane' : ' is-front-plane'}`}
                d={path}
                style={{ animationDelay: `${index * -1.35}s` }}
              />
            </React.Fragment>
          ))}
        </g>

        <polygon
          className="is-magnet-top is-south"
          points={polygon([
            [frontX, frontY],
            [magnetMiddleX, frontY],
            [magnetMiddleX + depthOffsetX, backY],
            [frontX + depthOffsetX, backY],
          ])}
        />
        <polygon
          className="is-magnet-top is-north"
          points={polygon([
            [magnetMiddleX, frontY],
            [northX, frontY],
            [northX + depthOffsetX, backY],
            [magnetMiddleX + depthOffsetX, backY],
          ])}
        />
        <polygon
          className="is-magnet-side"
          points={polygon([
            [frontX, frontY],
            [frontX + depthOffsetX, backY],
            [frontX + depthOffsetX, backY + magnetHeight],
            [frontX, frontY + magnetHeight],
          ])}
        />
        <rect className="is-magnet-front is-south" x={frontX} y={frontY} width={magnetWidth / 2} height={magnetHeight} rx="2" />
        <rect className="is-magnet-front is-north" x={magnetMiddleX} y={frontY} width={magnetWidth / 2} height={magnetHeight} rx="2" />
        <text className="is-pole-label" x={frontX + magnetWidth * 0.25} y={frontY + 31}>S</text>
        <text className="is-pole-label" x={frontX + magnetWidth * 0.75} y={frontY + 31}>N</text>

        <polygon
          className="is-flux-surface"
          points={polygon([
            [northX, frontY],
            [northX + depthOffsetX, backY],
            [northX + depthOffsetX, backY + magnetHeight],
            [northX, frontY + magnetHeight],
          ])}
        />
        {[0.22, 0.5, 0.78].map((fraction) => {
          const arrowStartX = northX + depthOffsetX * fraction;
          const arrowStartY = frontY + depthOffsetY * fraction + magnetHeight * fraction;
          return (
            <line
              key={fraction}
              className="is-b-arrow"
              x1={arrowStartX}
              y1={arrowStartY}
              x2={arrowStartX + 27}
              y2={arrowStartY}
              markerEnd="url(#follow-flux-depth-arrow)"
            />
          );
        })}
        <text className="is-surface-label" x={northX + depthOffsetX + 29} y={backY + magnetHeight / 2 + 3}>B</text>
        <g className="is-flux-surface-callout">
          <line
            x1={fluxSurfaceCenterX}
            y1={fluxSurfaceCenterY}
            x2={fluxSurfaceLabelX}
            y2={fluxSurfaceLabelY - 7}
          />
          <rect x={fluxSurfaceLabelX - 30} y={fluxSurfaceLabelY - 10} width="60" height="15" rx="3" />
          <text x={fluxSurfaceLabelX} y={fluxSurfaceLabelY}>Flux surface</text>
        </g>

        <g className="follow-flux-depth-axes" transform="translate(32 150)">
          <line x1="0" y1="0" x2="35" y2="0" markerEnd="url(#follow-flux-depth-arrow)" />
          <text x="41" y="4">X</text>
          <line x1="0" y1="0" x2="0" y2="-30" markerEnd="url(#follow-flux-depth-arrow)" />
          <text x="-4" y="-36">Y</text>
          <line x1="0" y1="0" x2="24" y2="-18" markerEnd="url(#follow-flux-depth-arrow)" />
          <text x="28" y="-20">Z</text>
        </g>
        <text className="is-dimension-label" x={frontX - 8} y={frontY + magnetHeight / 2} transform={`rotate(-90 ${frontX - 8} ${frontY + magnetHeight / 2})`}>12 mm</text>
        <text className="is-depth-label" x={northX + depthOffsetX / 2 - 10} y={backY - 8}>{depthMm} mm Z</text>
      </svg>
      <label className="follow-flux-depth-slider">
        <span><strong>Assumed out-of-plane depth</strong><em>{depthMm} mm</em></span>
        <input
          type="range"
          min={5}
          max={20}
          step={1}
          value={depthMm}
          onInput={(event) => onDepthChange(Number(event.currentTarget.value))}
          aria-label={`Assumed out-of-plane depth ${depthMm} millimeters`}
        />
        <small><span>5</span><span>10</span><span>20 mm</span></small>
      </label>
      <div className="follow-flux-depth-result" aria-live="polite">
        <span><b>B</b> unchanged</span>
        <span><b>Area</b> {metrics.north_face_area_mm2?.toFixed(0) ?? '—'} mm<sup>2</sup></span>
        <span><b>&Phi;</b> {formatMicroWebers(metrics.north_face_flux_wb)}</span>
      </div>
    </section>
  );
};

const ComparisonMetric: React.FC<{
  label: string;
  air: number;
  steel: number;
  lowerIsBetter?: boolean;
  formatter?: (value: number) => string;
  detail?: string;
  firstLabel?: string;
  secondLabel?: string;
}> = ({
  label,
  air,
  steel,
  lowerIsBetter = false,
  formatter = formatTesla,
  detail,
  firstLabel = 'Air',
  secondLabel = 'Steel',
}) => {
  const change = percentChange(air, steel);
  const displayedChange = change === null || Math.abs(change) < 0.5 ? 0 : Math.round(change);
  const favorable = change !== null && (lowerIsBetter ? change <= 0 : change >= 0);
  return (
    <div className="follow-flux-comparison-metric">
      <div className="follow-flux-comparison-metric-heading">
        <strong title={detail ?? (lowerIsBetter ? 'Near the outer boundary' : 'Beside the magnet ends')}>{label}</strong>
      </div>
      <div className="follow-flux-comparison-values">
        <div><span>{firstLabel}</span><strong>{formatter(air)}</strong></div>
        <div className="is-steel"><span>{secondLabel}</span><strong>{formatter(steel)}</strong></div>
      </div>
      {change !== null ? (
        <span className={`follow-flux-comparison-change${favorable ? ' is-favorable' : ''}`}>
          {displayedChange > 0 ? '+' : ''}{displayedChange}%
        </span>
      ) : null}
    </div>
  );
};

export const LearningLessonOneFollowFlux: React.FC<LearningLessonOneFollowFluxProps> = ({
  onBackToCatalog,
  stage,
  onStageChange,
  onHeaderProgressChange,
}) => {
  const [internalStage, setInternalStage] = React.useState<LearningLessonStage>('design');
  const requestedStage = stage ?? internalStage;
  const lessonStage: LearningLessonStage = requestedStage === 'mesh' ? 'solve' : requestedStage;
  /** Lesson-local: the pair phase rides on the shared 'solve' stage. */
  const [pairPhaseOpen, setPairPhaseOpen] = React.useState(false);
  const lessonPhase: LessonOnePhase = lessonStage === 'design'
    ? 'design'
    : pairPhaseOpen ? 'pair' : 'solve';
  const [prediction, setPrediction] = React.useState<Prediction | null>(null);
  const [airSolve, setAirSolve] = React.useState<FollowFluxFieldData | null>(null);
  const [steelSolve, setSteelSolve] = React.useState<FollowFluxFieldData | null>(null);
  const [steelInsightAnswer, setSteelInsightAnswer] = React.useState<SteelInsightAnswer | null>(null);
  const [pairAttractSolve, setPairAttractSolve] = React.useState<FollowFluxFieldData | null>(null);
  const [pairRepelSolve, setPairRepelSolve] = React.useState<FollowFluxFieldData | null>(null);
  const [solveView, setSolveView] = React.useState<SolveView>('air');
  const [fieldDisplayMode, setFieldDisplayMode] = React.useState<FieldDisplayMode>('lines');
  const [meshEdgesVisible, setMeshEdgesVisible] = React.useState(true);
  const [showPhysicalDepth, setShowPhysicalDepth] = React.useState(false);
  const [depth3DUnavailable, setDepth3DUnavailable] = React.useState(false);
  const handleDepth3DUnavailable = React.useCallback(() => setDepth3DUnavailable(true), []);
  const [assumedDepthMm, setAssumedDepthMm] = React.useState(10);
  const [steelPlacement, setSteelPlacement] = React.useState<SteelPlacement>({
    shape: 'bar',
    xMm: STEEL_SHAPES.bar.defaultX,
    yMm: STEEL_SHAPES.bar.defaultY,
    angleDeg: 0,
  });
  const [magnetPlacement, setMagnetPlacement] = React.useState<MagnetPlacement>({
    xMm: 0,
    yMm: 0,
    angleDeg: 0,
  });
  const [magnet2Placement, setMagnet2Placement] = React.useState<MagnetPlacement>(PAIR_LAYOUT.second);
  const [busy, setBusy] = React.useState<'air-solve' | 'steel-solve' | 'pair-solve' | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [quizOpen, setQuizOpen] = React.useState(false);
  const [quizPassed, setQuizPassed] = React.useState(false);
  const [labControlsOpen, setLabControlsOpen] = React.useState(false);
  const [solveInspectorOpen, setSolveInspectorOpen] = React.useState(false);
  const [pairComparisonReviewed, setPairComparisonReviewed] = React.useState(false);
  const [selectedFixtureObject, setSelectedFixtureObject] = React.useState<DraggableFixtureObject>('magnet');
  const [hasManipulatedFixture, setHasManipulatedFixture] = React.useState(false);
  const autoSolveSeq = React.useRef(0);
  const { isLessonComplete, setLessonComplete } = useLearningProgress();
  const solveClient = useLessonSolveClient();
  const lessonComplete = isLessonComplete('follow-the-flux');

  const predictionCorrect = prediction === 'closed-loop';
  const steelInsightCorrect = steelInsightAnswer === 'lower-reluctance';
  const bothSolved = Boolean(airSolve && steelSolve);
  const steelPlacementValid = steelPlacementIsValid(steelPlacement, magnetPlacement);
  const magnetPlacementValid = magnetPlacementIsValid(magnetPlacement);
  const magnet2PlacementValid = magnet2PlacementIsValid(magnet2Placement, magnetPlacement);
  const pairFacing = pairPoleFacing(magnetPlacement, magnet2Placement);
  const pairArrangement = pairFacing?.arrangement ?? null;
  const pairExperimentComplete = Boolean(pairAttractSolve && pairRepelSolve);
  const activePairSolve = pairArrangement === 'attract'
    ? pairAttractSolve
    : pairArrangement === 'repel' ? pairRepelSolve : null;
  const anyPairSolve = activePairSolve ?? pairRepelSolve ?? pairAttractSolve;
  const steelDimensions = STEEL_SHAPES[steelPlacement.shape];
  const steelPlacementExtents = steelPlacement.shape === 'puck'
    ? { x: 8, y: 8 }
    : rotatedRectExtents(
      steelDimensions.widthMm / 2,
      steelDimensions.heightMm / 2,
      steelPlacement.angleDeg,
    );
  const activeData = solveView === 'pair'
    ? activePairSolve
    : solveView === 'steel' ? steelSolve : airSolve;
  const airMetrics = airSolve?.metrics
    ? scaleFluxMetricsForDepth(airSolve.metrics, assumedDepthMm)
    : null;
  const steelMetrics = steelSolve?.metrics
    ? scaleFluxMetricsForDepth(steelSolve.metrics, assumedDepthMm)
    : null;
  const pairAttractMetrics = pairAttractSolve?.metrics
    ? scaleFluxMetricsForDepth(pairAttractSolve.metrics, assumedDepthMm)
    : null;
  const pairRepelMetrics = pairRepelSolve?.metrics
    ? scaleFluxMetricsForDepth(pairRepelSolve.metrics, assumedDepthMm)
    : null;
  const activeMetrics = activeData?.metrics
    ? scaleFluxMetricsForDepth(activeData.metrics, assumedDepthMm)
    : null;
  const inspectorTitle = solveView === 'pair' && pairAttractMetrics && pairRepelMetrics
    ? 'N→S vs N↔N'
    : airMetrics && steelMetrics && solveView !== 'pair'
      ? 'Air vs steel'
      : activeMetrics
        ? solveView === 'pair' ? 'Two magnets' : solveView === 'steel' ? 'Steel return path' : 'Open-air field'
        : 'Solve evidence';
  const inspectorSummary = solveView === 'pair' && pairAttractMetrics && pairRepelMetrics
    ? 'Same magnets. Different path.'
    : airMetrics && steelMetrics && solveView !== 'pair'
      ? 'Same magnet. Easier return path.'
      : activeMetrics
        ? 'One solved frame. Three useful measurements.'
        : 'Solve the field to reveal the evidence.';
  /**
   * Moves between Lesson 1's phases while reporting only the three stages the
   * hosts understand: the pair phase is a 'solve' stage as far as they are
   * concerned, so App.tsx's `LearningLessonStage` state stays valid.
   */
  const setLessonPhase = React.useCallback((next: LessonOnePhase) => {
    setPairPhaseOpen(next === 'pair');
    const sharedStage: LearningLessonStage = next === 'design' ? 'design' : 'solve';
    setInternalStage(sharedStage);
    onStageChange?.(sharedStage);
  }, [onStageChange]);

  const activeProgressStepId: LessonOneProgressStepId = quizOpen
    ? 'check'
    : lessonPhase === 'design'
      ? 'predict'
      : lessonPhase === 'pair'
        ? 'pair'
        : !airSolve
          ? 'air'
          : 'steel';

  const selectProgressStep = React.useCallback((stepId: string) => {
    const next = stepId as LessonOneProgressStepId;
    if (next === 'predict') {
      setQuizOpen(false);
      setSolveView('air');
      setLessonPhase('design');
    } else if (next === 'air' && predictionCorrect) {
      setQuizOpen(false);
      setSolveView('air');
      setLessonPhase('solve');
    } else if (next === 'steel' && airSolve) {
      setQuizOpen(false);
      setSolveView('steel');
      setLessonPhase('solve');
    } else if (next === 'pair' && bothSolved && steelInsightCorrect) {
      setQuizOpen(false);
      setSolveView('pair');
      setLessonPhase('pair');
    } else if (next === 'check' && pairComparisonReviewed) {
      setLessonPhase('pair');
      setQuizOpen(true);
    }
  }, [airSolve, bothSolved, pairComparisonReviewed, predictionCorrect, setLessonPhase, steelInsightCorrect]);

  const lessonProgressSteps = React.useMemo<LearningLessonProgressStep[]>(() => [
    { id: 'predict', label: 'Predict', complete: predictionCorrect, available: true },
    { id: 'air', label: 'Open air', complete: Boolean(airSolve), available: predictionCorrect },
    { id: 'steel', label: 'Add steel', complete: Boolean(steelSolve) && steelInsightCorrect, available: Boolean(airSolve) },
    { id: 'pair', label: 'Two magnets', complete: pairComparisonReviewed, available: bothSolved && steelInsightCorrect },
    { id: 'check', label: 'Check', complete: quizPassed, available: pairComparisonReviewed },
  ], [airSolve, bothSolved, pairComparisonReviewed, predictionCorrect, quizPassed, steelInsightCorrect, steelSolve]);

  const headerProgress = React.useMemo<LearningLessonHeaderProgress>(() => ({
    lessonNumber: 1,
    lessonCount: 10,
    title: 'Follow the flux',
    currentStepId: activeProgressStepId,
    steps: lessonProgressSteps,
    onStepSelect: selectProgressStep,
  }), [activeProgressStepId, lessonProgressSteps, selectProgressStep]);
  const currentGoal = LESSON_ONE_GOALS[activeProgressStepId];
  const completedLessonStepCount = lessonProgressSteps.filter((item) => item.complete).length;

  React.useEffect(() => {
    onHeaderProgressChange?.(headerProgress);
  }, [headerProgress, onHeaderProgressChange]);

  React.useEffect(() => {
    if (bothSolved && pairExperimentComplete && pairComparisonReviewed && quizPassed) {
      setLessonComplete('follow-the-flux', true);
    }
  }, [bothSolved, pairComparisonReviewed, pairExperimentComplete, quizPassed, setLessonComplete]);

  React.useEffect(() => {
    if (!pairExperimentComplete) return;
    setPairComparisonReviewed(false);
    setSolveView('pair');
    setLabControlsOpen(false);
    setSolveInspectorOpen(true);
  }, [pairExperimentComplete]);

  const runAction = async (kind: NonNullable<typeof busy>, action: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The lesson solver could not complete this step.');
    } finally {
      setBusy(null);
    }
  };

  const solveAir = () => runAction('air-solve', async () => {
    const result = await solveClient.fetchFollowFluxSolve({
      steelReturn: false,
      magnetCenterXMm: magnetPlacement.xMm,
      magnetCenterYMm: magnetPlacement.yMm,
      magnetAngleDeg: magnetPlacement.angleDeg,
      meshDensity: 'normal',
    });
    setAirSolve(result);
    setSolveView('air');
    setStaleView((prev) => ({ ...prev, air: false }));
  });

  const solveSteel = () => runAction('steel-solve', async () => {
    const result = await solveClient.fetchFollowFluxSolve({
      steelReturn: true,
      steelShape: steelPlacement.shape,
      steelCenterXMm: steelPlacement.xMm,
      steelCenterYMm: steelPlacement.yMm,
      magnetCenterXMm: magnetPlacement.xMm,
      magnetCenterYMm: magnetPlacement.yMm,
      magnetAngleDeg: magnetPlacement.angleDeg,
      steelAngleDeg: steelPlacement.angleDeg,
      meshDensity: 'normal',
    });
    setSteelSolve(result);
    setSolveView('steel');
    setStaleView((prev) => ({ ...prev, steel: false }));
  });

  const solvePair = () => runAction('pair-solve', async () => {
    if (!pairArrangement) throw new Error('Point both magnets along the line between their centres before solving.');
    const result = await solveClient.fetchFollowFluxSolve({
      steelReturn: false,
      magnetCenterXMm: magnetPlacement.xMm,
      magnetCenterYMm: magnetPlacement.yMm,
      magnetAngleDeg: magnetPlacement.angleDeg,
      magnet2Enabled: true,
      magnet2CenterXMm: magnet2Placement.xMm,
      magnet2CenterYMm: magnet2Placement.yMm,
      magnet2AngleDeg: magnet2Placement.angleDeg,
      meshDensity: 'normal',
    });
    if (pairArrangement === 'attract') setPairAttractSolve(result);
    else setPairRepelSolve(result);
    setSolveView('pair');
    setStaleView((prev) => ({ ...prev, pair: false }));
  });

  const flipMagnet2ForComparison = () => {
    autoSolveSeq.current += 1;
    setAutoSolving(false);
    setPairComparisonReviewed(false);
    const angleDeg = normalizeAngleDeg(magnet2Placement.angleDeg + 180);
    const extents = rotatedRectExtents(18, 6, angleDeg);
    setMagnet2Placement({
      ...magnet2Placement,
      xMm: Math.max(-(48 - extents.x), Math.min(48 - extents.x, magnet2Placement.xMm)),
      yMm: Math.max(-(32 - extents.y), Math.min(32 - extents.y, magnet2Placement.yMm)),
      angleDeg,
    });
    setStaleView((prev) => ({ ...prev, pair: true }));
    setQuizOpen(false);
  };

  const primaryLabel = lessonPhase === 'design'
    ? predictionCorrect
      ? 'Next: Solve'
      : prediction
        ? 'Try another answer →'
        : 'Choose a prediction →'
    : quizOpen
      ? 'Quiz in progress'
      : lessonPhase === 'pair'
        ? !pairAttractSolve
          ? busy === 'pair-solve' ? 'Solving N facing S…' : 'Solve N facing S'
          : !pairRepelSolve
            ? pairArrangement === 'attract'
              ? 'Next: Flip magnet 2'
              : busy === 'pair-solve' ? 'Solving N facing N…' : 'Solve N facing N'
            : pairComparisonReviewed
              ? 'Finish lab: Quiz'
              : 'Review comparison'
        : !airSolve
          ? busy === 'air-solve' ? 'Preparing + solving open air…' : 'Solve open air'
          : !steelSolve
            ? solveView === 'air'
              ? 'Next: Add steel object'
              : busy === 'steel-solve' ? 'Preparing + solving with steel…' : 'Solve with steel'
            : steelInsightCorrect
              ? 'Next: Two magnets'
              : steelInsightAnswer
                ? 'Try another answer ↑'
                : 'Answer the quick check ↑';

  const handlePrimary = () => {
    if (lessonPhase === 'design') {
      if (predictionCorrect) setLessonPhase('solve');
      return;
    }
    if (lessonPhase === 'pair') {
      if (!pairAttractSolve) void solvePair();
      else if (!pairRepelSolve) {
        if (pairArrangement === 'attract') flipMagnet2ForComparison();
        else void solvePair();
      }
      else if (!pairComparisonReviewed) {
        setLabControlsOpen(false);
        setSolveInspectorOpen(true);
      } else setQuizOpen(true);
      return;
    }
    if (!airSolve) void solveAir();
    else if (!steelSolve) {
      if (solveView === 'air') setSolveView('steel');
      else void solveSteel();
    }
    else if (steelInsightCorrect) setLessonPhase('pair');
  };

  const primaryDisabled = Boolean(busy)
    || (lessonPhase === 'design' && !predictionCorrect)
    || (lessonPhase !== 'design' && !magnetPlacementValid)
    || (lessonPhase === 'solve' && Boolean(airSolve) && solveView === 'steel' && !steelSolve && !steelPlacementValid)
    || (lessonPhase === 'solve' && Boolean(steelSolve) && !steelInsightCorrect)
    || (lessonPhase === 'pair' && (!magnet2PlacementValid || !pairArrangement))
    || (lessonPhase === 'pair' && !pairAttractSolve && pairArrangement !== 'attract')
    || (lessonPhase !== 'design' && quizOpen);

  const dockNeedsControls = lessonPhase === 'solve' && Boolean(steelSolve) && !steelInsightCorrect;
  const stageInsight = solveView === 'pair'
    ? pairExperimentComplete
      ? 'Pole orientation changes how much useful flux crosses the air gap.'
      : 'Opposite poles create one shared magnetic path across the gap.'
    : solveView === 'steel'
      ? steelSolve
        ? 'Steel lowers reluctance, so more flux returns through a tighter path.'
        : 'Change only the return path, then compare it with open air.'
      : airSolve
        ? 'A magnetic field has no loose ends. Every line returns to the south pole.'
        : 'Start with one magnet in open air and reveal its complete field path.';
  const placementPreviewVisible = !quizOpen && (
    !airSolve
    || (solveView === 'pair' && !activePairSolve)
    || (solveView === 'steel' && !steelSolve)
  );

  /**
   * Live re-solve.
   *
   * Moving a body used to null the solved field, dropping the canvas back to the
   * placement screen until the user pressed Solve again. A solve is ~0.5 s, so
   * instead the previous field stays on screen, marked stale, and a fresh solve is
   * scheduled. Only re-solves a view that already has a result: the first solve of
   * each view stays an explicit step, because the lesson teaches predict -> solve
   * open air -> add steel -> solve with steel and auto-running that would collapse
   * the sequence.
   *
   * `autoSolveSeq` makes stale responses harmless — drags fire faster than solves
   * return, so a superseded reply must not overwrite a newer one.
   */
  const [staleView, setStaleView] = React.useState<Record<SolveView, boolean>>({
    air: false,
    steel: false,
    pair: false,
  });
  const [autoSolving, setAutoSolving] = React.useState(false);
  /**
   * Magnet 1 is shared by every phase, but the steel phase and the pair phase want
   * it in different places — end to end with magnet 2 versus wherever the user set
   * it up against the steel. So each phase's arrangement is stashed on the way out
   * and restored on the way back in, instead of one phase quietly overwriting the
   * other's work.
   */
  const solvePhaseMagnetRef = React.useRef<MagnetPlacement | null>(null);
  const pairPhaseMagnetRef = React.useRef<MagnetPlacement | null>(null);
  const magnetPlacementRef = React.useRef(magnetPlacement);
  magnetPlacementRef.current = magnetPlacement;
  // Read inside the phase-swap effect, which must not re-run when a solve lands.
  const airSolveRef = React.useRef(airSolve);
  airSolveRef.current = airSolve;
  const steelSolveRef = React.useRef(steelSolve);
  steelSolveRef.current = steelSolve;
  const pairSolveRef = React.useRef(anyPairSolve);
  pairSolveRef.current = anyPairSolve;

  React.useEffect(() => {
    if (lessonPhase === 'pair') {
      setSolveView('pair');
      solvePhaseMagnetRef.current = magnetPlacementRef.current;
      const restored = pairPhaseMagnetRef.current ?? PAIR_LAYOUT.first;
      pairPhaseMagnetRef.current = restored;
      if (samePlacement(magnetPlacementRef.current, restored)) return;
      setMagnetPlacement(restored);
      // Magnet 1 moved, so any frame not solved at its new spot is out of date.
      // Magnet 2 needs no check: it is not swapped between phases, and every change
      // to it already marks the pair frame stale.
      setStaleView((prev) => ({
        ...prev,
        air: !solvedWithMagnetAt(airSolveRef.current, restored),
        steel: !solvedWithMagnetAt(steelSolveRef.current, restored),
        pair: !solvedWithMagnetAt(pairSolveRef.current, restored),
      }));
      return;
    }
    // Left the pair phase: the pair view has no meaning in the earlier phases.
    setSolveView((current) => (current === 'pair' ? 'steel' : current));
    const solvePhaseMagnet = solvePhaseMagnetRef.current;
    if (!solvePhaseMagnet) return;
    solvePhaseMagnetRef.current = null;
    pairPhaseMagnetRef.current = magnetPlacementRef.current;
    if (samePlacement(magnetPlacementRef.current, solvePhaseMagnet)) return;
    setMagnetPlacement(solvePhaseMagnet);
    // The pair flag is left alone: that view is unreachable outside this phase and
    // is recomputed against the restored arrangement on the way back in.
    setStaleView((prev) => ({
      ...prev,
      air: !solvedWithMagnetAt(airSolveRef.current, solvePhaseMagnet),
      steel: !solvedWithMagnetAt(steelSolveRef.current, solvePhaseMagnet),
    }));
  }, [lessonPhase]);

  React.useEffect(() => {
    if (lessonPhase === 'pair') setSelectedFixtureObject('magnet2');
    else if (solveView === 'steel') setSelectedFixtureObject('steel');
    else setSelectedFixtureObject('magnet');
  }, [lessonPhase, solveView]);

  const geometryKey = [
    magnetPlacement.xMm, magnetPlacement.yMm, magnetPlacement.angleDeg,
    steelPlacement.shape, steelPlacement.xMm, steelPlacement.yMm, steelPlacement.angleDeg,
    magnet2Placement.xMm, magnet2Placement.yMm, magnet2Placement.angleDeg,
  ].join('|');

  const solveViewRef = React.useRef(solveView);
  solveViewRef.current = solveView;

  React.useEffect(() => {
    if (lessonStage !== 'solve') return undefined;
    const view = solveViewRef.current;
    // Nothing solved for this view yet, or the geometry is invalid — leave it to the CTA.
    if (view === 'air' && (!airSolve || !magnetPlacementValid)) return undefined;
    if (view === 'steel' && (!steelSolve || !steelPlacementValid || !magnetPlacementValid)) return undefined;
    if (view === 'pair' && (
      !pairExperimentComplete
      || !activePairSolve
      || !pairArrangement
      || !magnetPlacementValid
      || !magnet2PlacementValid
    )) return undefined;
    if (!staleView[view]) return undefined;

    const seq = ++autoSolveSeq.current;
    const timer = window.setTimeout(() => {
      setAutoSolving(true);
      setError(null);
      const magnetOptions = {
        magnetCenterXMm: magnetPlacement.xMm,
        magnetCenterYMm: magnetPlacement.yMm,
        magnetAngleDeg: magnetPlacement.angleDeg,
      };
      const request = view === 'steel'
        ? solveClient.fetchFollowFluxSolve({
          steelReturn: true,
          steelShape: steelPlacement.shape,
          steelCenterXMm: steelPlacement.xMm,
          steelCenterYMm: steelPlacement.yMm,
          ...magnetOptions,
          steelAngleDeg: steelPlacement.angleDeg,
          meshDensity: 'normal',
        })
        : view === 'pair'
          ? solveClient.fetchFollowFluxSolve({
            steelReturn: false,
            ...magnetOptions,
            magnet2Enabled: true,
            magnet2CenterXMm: magnet2Placement.xMm,
            magnet2CenterYMm: magnet2Placement.yMm,
            magnet2AngleDeg: magnet2Placement.angleDeg,
            meshDensity: 'normal',
          })
          : solveClient.fetchFollowFluxSolve({
            steelReturn: false,
            ...magnetOptions,
            meshDensity: 'normal',
          });
      void request
        .then((result) => {
          if (seq !== autoSolveSeq.current) return;
          if (view === 'steel') setSteelSolve(result);
          else if (view === 'pair') {
            if (pairArrangement === 'attract') setPairAttractSolve(result);
            else if (pairArrangement === 'repel') setPairRepelSolve(result);
          }
          else setAirSolve(result);
          setStaleView((prev) => ({ ...prev, [view]: false }));
        })
        .catch((caught: unknown) => {
          if (seq !== autoSolveSeq.current) return;
          setError(caught instanceof Error ? caught.message : 'The lesson solver could not re-solve this geometry.');
        })
        .finally(() => {
          if (seq === autoSolveSeq.current) setAutoSolving(false);
        });
    }, AUTO_SOLVE_DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
    // geometryKey collapses the placement fields; the solves are read to decide
    // whether this view has ever been solved.
  }, [
    geometryKey,
    staleView,
    lessonStage,
    airSolve,
    steelSolve,
    activePairSolve,
    pairExperimentComplete,
    pairArrangement,
    magnetPlacementValid,
    steelPlacementValid,
    magnet2PlacementValid,
    magnetPlacement,
    steelPlacement,
    magnet2Placement,
    solveClient,
  ]);

  const updateSteelPlacement = (next: SteelPlacement) => {
    autoSolveSeq.current += 1;
    setAutoSolving(false);
    setSteelPlacement(next);
    // Keep the solved field on screen and mark it stale; the effect above re-solves.
    // Nulling it here is what used to bounce the canvas back to the placement view.
    setStaleView((prev) => ({ ...prev, steel: true }));
    setSolveView('steel');
    setQuizOpen(false);
  };

  const updateMagnetPlacement = (next: MagnetPlacement) => {
    autoSolveSeq.current += 1;
    setAutoSolving(false);
    setPairComparisonReviewed(false);
    setMagnetPlacement(next);
    // Moving magnet 1 invalidates every view, but keep whatever is solved on
    // screen and let the effect above re-solve the one being looked at. Crucially
    // the view is NOT forced back to 'air': doing that while the user is dragging
    // in the steel stage would yank them out of it mid-drag.
    setStaleView({ air: true, steel: true, pair: true });
    setQuizOpen(false);
  };

  const updateMagnet2Placement = (next: MagnetPlacement) => {
    autoSolveSeq.current += 1;
    setAutoSolving(false);
    setPairComparisonReviewed(false);
    setMagnet2Placement(next);
    // Magnet 2 only exists in the pair solve, so the single-magnet frames stay valid.
    setStaleView((prev) => ({ ...prev, pair: true }));
    setQuizOpen(false);
  };

  const dropFixtureObject = (
    object: DraggableFixtureObject,
    rawCenter: { xMm: number; yMm: number },
  ) => {
    setSelectedFixtureObject(object);
    setHasManipulatedFixture(true);
    // Drags off the meshed viewer arrive as raw model floats, so a drop could land
    // at -9.293981375172734 mm while every readout rounds it to -9. Snap here, where
    // the clamping already happens, so the panel, the URL and the solve agree.
    const nextCenter = {
      xMm: Math.round(rawCenter.xMm),
      yMm: Math.round(rawCenter.yMm),
    };
    if (object === 'magnet') {
      const extents = rotatedRectExtents(18, 6, magnetPlacement.angleDeg);
      updateMagnetPlacement({
        ...magnetPlacement,
        xMm: Math.max(-(48 - extents.x), Math.min(48 - extents.x, nextCenter.xMm)),
        yMm: Math.max(-(32 - extents.y), Math.min(32 - extents.y, nextCenter.yMm)),
      });
      return;
    }
    if (object === 'magnet2') {
      const extents = rotatedRectExtents(18, 6, magnet2Placement.angleDeg);
      updateMagnet2Placement({
        ...magnet2Placement,
        xMm: Math.max(-(48 - extents.x), Math.min(48 - extents.x, nextCenter.xMm)),
        yMm: Math.max(-(32 - extents.y), Math.min(32 - extents.y, nextCenter.yMm)),
      });
      return;
    }
    const dimensions = STEEL_SHAPES[steelPlacement.shape];
    const extents = steelPlacement.shape === 'puck'
      ? { x: 8, y: 8 }
      : rotatedRectExtents(
        dimensions.widthMm / 2,
        dimensions.heightMm / 2,
        steelPlacement.angleDeg,
      );
    updateSteelPlacement({
      ...steelPlacement,
      xMm: Math.max(-(48 - extents.x), Math.min(48 - extents.x, nextCenter.xMm)),
      yMm: Math.max(-(32 - extents.y), Math.min(32 - extents.y, nextCenter.yMm)),
    });
  };

  const rotateFixtureObject = (object: DraggableFixtureObject, angleDeg: number) => {
    setSelectedFixtureObject(object);
    setHasManipulatedFixture(true);
    const normalizedAngle = normalizeAngleDeg(angleDeg);
    if (object === 'magnet') {
      const extents = rotatedRectExtents(18, 6, normalizedAngle);
      updateMagnetPlacement({
        ...magnetPlacement,
        xMm: Math.max(-(48 - extents.x), Math.min(48 - extents.x, magnetPlacement.xMm)),
        yMm: Math.max(-(32 - extents.y), Math.min(32 - extents.y, magnetPlacement.yMm)),
        angleDeg: normalizedAngle,
      });
    } else if (object === 'magnet2') {
      const extents = rotatedRectExtents(18, 6, normalizedAngle);
      updateMagnet2Placement({
        ...magnet2Placement,
        xMm: Math.max(-(48 - extents.x), Math.min(48 - extents.x, magnet2Placement.xMm)),
        yMm: Math.max(-(32 - extents.y), Math.min(32 - extents.y, magnet2Placement.yMm)),
        angleDeg: normalizedAngle,
      });
    } else {
      const dimensions = STEEL_SHAPES[steelPlacement.shape];
      const extents = steelPlacement.shape === 'puck'
        ? { x: 8, y: 8 }
        : rotatedRectExtents(
          dimensions.widthMm / 2,
          dimensions.heightMm / 2,
          normalizedAngle,
        );
      updateSteelPlacement({
        ...steelPlacement,
        xMm: Math.max(-(48 - extents.x), Math.min(48 - extents.x, steelPlacement.xMm)),
        yMm: Math.max(-(32 - extents.y), Math.min(32 - extents.y, steelPlacement.yMm)),
        angleDeg: normalizedAngle,
      });
    }
  };

  const dropMeshedRegion = (dragKey: string, deltaXMm: number, deltaYMm: number) => {
    if (dragKey === 'magnet' || dragKey === 'magnet2' || dragKey === 'steel') {
      setSelectedFixtureObject(dragKey);
    }
    if (Math.hypot(deltaXMm, deltaYMm) < 0.25) return;
    if (solveView === 'pair' && pairAttractSolve) return;
    if (dragKey === 'magnet') {
      dropFixtureObject('magnet', {
        xMm: magnetPlacement.xMm + deltaXMm,
        yMm: magnetPlacement.yMm + deltaYMm,
      });
    } else if (dragKey === 'magnet2') {
      dropFixtureObject('magnet2', {
        xMm: magnet2Placement.xMm + deltaXMm,
        yMm: magnet2Placement.yMm + deltaYMm,
      });
    } else if (dragKey === 'steel') {
      dropFixtureObject('steel', {
        xMm: steelPlacement.xMm + deltaXMm,
        yMm: steelPlacement.yMm + deltaYMm,
      });
    }
  };

  const selectSteelShape = (shape: SteelShape) => {
    setSelectedFixtureObject('steel');
    setHasManipulatedFixture(true);
    const metadata = STEEL_SHAPES[shape];
    updateSteelPlacement({
      shape,
      xMm: metadata.defaultX,
      yMm: metadata.defaultY,
      angleDeg: shape === 'puck' ? 0 : steelPlacement.angleDeg,
    });
  };

  const selectedPlacement = selectedFixtureObject === 'steel'
    ? steelPlacement
    : selectedFixtureObject === 'magnet2' ? magnet2Placement : magnetPlacement;
  const selectedObjectLabel = selectedFixtureObject === 'steel'
    ? 'Steel'
    : selectedFixtureObject === 'magnet2' ? 'Magnet 2' : lessonPhase === 'pair' ? 'Magnet 1' : 'Magnet';
  const selectedExtents = selectedFixtureObject === 'steel'
    ? steelPlacementExtents
    : rotatedRectExtents(18, 6, selectedPlacement.angleDeg);
  const selectedXLimit = Math.floor(48 - selectedExtents.x);
  const selectedYLimit = Math.floor(32 - selectedExtents.y);
  const selectedControlsLocked = Boolean(busy) || (lessonPhase === 'pair' && Boolean(pairAttractSolve));

  const updateSelectedPlacement = (field: 'xMm' | 'yMm' | 'angleDeg', value: number) => {
    if (!Number.isFinite(value) || selectedControlsLocked) return;
    if (field === 'angleDeg') {
      rotateFixtureObject(selectedFixtureObject, value);
      return;
    }
    dropFixtureObject(selectedFixtureObject, {
      xMm: field === 'xMm' ? value : selectedPlacement.xMm,
      yMm: field === 'yMm' ? value : selectedPlacement.yMm,
    });
  };

  const resetSelectedPlacement = () => {
    if (selectedControlsLocked) return;
    setHasManipulatedFixture(true);
    if (selectedFixtureObject === 'steel') {
      const shape = STEEL_SHAPES[steelPlacement.shape];
      updateSteelPlacement({
        ...steelPlacement,
        xMm: shape.defaultX,
        yMm: shape.defaultY,
        angleDeg: 0,
      });
    } else if (selectedFixtureObject === 'magnet2') {
      updateMagnet2Placement(PAIR_LAYOUT.second);
    } else {
      updateMagnetPlacement(lessonPhase === 'pair' ? PAIR_LAYOUT.first : { xMm: 0, yMm: 0, angleDeg: 0 });
    }
  };

  const renderViewer = (data: FollowFluxFieldData) => {
    const depthAdjustedMetrics = data.metrics
      ? scaleFluxMetricsForDepth(data.metrics, assumedDepthMm)
      : null;
    const northGateStart = pointFromLocalFrame(
      18,
      -6,
      data.magnet_center_x_mm,
      data.magnet_center_y_mm,
      data.magnet_angle_deg,
    );
    const northGateEnd = pointFromLocalFrame(
      18,
      6,
      data.magnet_center_x_mm,
      data.magnet_center_y_mm,
      data.magnet_angle_deg,
    );
    // Normally the flux-surface label sits just beyond the north face. With a second
    // magnet there, that lands on top of its south pole label, so lift the label
    // clear of both bodies instead.
    const northGateLabel = pointFromLocalFrame(
      data.magnet2_enabled ? 18 : 31,
      data.magnet2_enabled ? 15 : 0,
      data.magnet_center_x_mm,
      data.magnet_center_y_mm,
      data.magnet_angle_deg,
    );
    const viewIsStale = staleView[solveView];
    // The auto-solve effect refuses invalid geometry, so without this the banner
    // would promise a re-solve that is never coming while the placement error
    // right below it says the opposite.
    const viewCanResolve = magnetPlacementValid
      && (solveView !== 'steel' || steelPlacementValid)
      && (solveView !== 'pair' || magnet2PlacementValid);
    const viewerTitle = data.magnet2_enabled
      ? 'Two magnets'
      : data.steel_return
        ? `Magnet + ${STEEL_SHAPES[data.steel_shape].label.toLowerCase()}`
        : 'Magnet in open air';
    return (
    <div className={`follow-flux-viewer${viewIsStale ? ' is-stale' : ''}`}>
      {viewIsStale ? (
        <p className={`follow-flux-resolving${viewCanResolve ? '' : ' is-blocked'}`} role="status">
          {!viewCanResolve
            ? 'Invalid placement — fix it to re-solve.'
            : autoSolving ? 'Re-solving the moved geometry…' : 'Geometry moved — re-solving…'}
        </p>
      ) : null}
      <div className="mesh-viewer-header follow-flux-visual-header">
        <div className="mesh-viewer-title">
          <h3>{viewerTitle}</h3>
        </div>
        <div className="follow-flux-field-mode-toggle" role="group" aria-label="Field and teaching visualization">
          <button
            type="button"
            className={!showPhysicalDepth && fieldDisplayMode === 'lines' ? 'is-active' : ''}
            onClick={() => {
              setFieldDisplayMode('lines');
              setShowPhysicalDepth(false);
            }}
            aria-pressed={!showPhysicalDepth && fieldDisplayMode === 'lines'}
          >
            <span className="is-line-swatch" aria-hidden="true" />
            Flux lines
          </button>
          <button
            type="button"
            className={!showPhysicalDepth && fieldDisplayMode === 'density' ? 'is-active' : ''}
            onClick={() => {
              setFieldDisplayMode('density');
              setShowPhysicalDepth(false);
            }}
            aria-pressed={!showPhysicalDepth && fieldDisplayMode === 'density'}
          >
            <span className="is-density-swatch" aria-hidden="true" />
            |B| map
          </button>
          <button
            type="button"
            className={!showPhysicalDepth && meshEdgesVisible ? 'is-active' : ''}
            onClick={() => {
              if (showPhysicalDepth) {
                setShowPhysicalDepth(false);
                setMeshEdgesVisible(true);
              } else {
                setMeshEdgesVisible((visible) => !visible);
              }
            }}
            aria-pressed={!showPhysicalDepth && meshEdgesVisible}
          >
            <span className="is-mesh-swatch" aria-hidden="true" />
            Mesh
          </button>
          <button
            type="button"
            className={showPhysicalDepth ? 'is-active' : ''}
            onClick={() => setShowPhysicalDepth(true)}
            aria-pressed={showPhysicalDepth}
            aria-expanded={showPhysicalDepth}
            aria-controls="follow-flux-depth-inset"
          >
            <span className="is-depth-swatch" aria-hidden="true" />
            3D depth
          </button>
        </div>
      </div>
      {showPhysicalDepth && depthAdjustedMetrics?.north_face_flux_wb !== undefined ? (
        depth3DUnavailable ? (
          <PhysicalDepthInset
            depthMm={assumedDepthMm}
            metrics={depthAdjustedMetrics}
            onDepthChange={setAssumedDepthMm}
          />
        ) : (
          <FollowFluxDepth3D
            data={data}
            depthMm={assumedDepthMm}
            metrics={depthAdjustedMetrics}
            onDepthChange={setAssumedDepthMm}
            onUnavailable={handleDepth3DUnavailable}
          />
        )
      ) : (
        <MeshViewer
          meshData={data}
          embedded
          compactEmbedded
          toolbarMode="zoom-only"
          toolbarLabel={fieldDisplayMode === 'lines' ? 'Flux lines' : 'Flux density |B|'}
          showMeshEdges={meshEdgesVisible}
          showFieldIntensity={fieldDisplayMode === 'density'}
          smoothFieldIntensity
          fieldLinesVisible={fieldDisplayMode === 'lines'}
          animateFieldArrows={fieldDisplayMode === 'lines'}
          viewportPanEnabled={false}
          draggableRegionGroups={{
            magnet_n: 'magnet',
            magnet_s: 'magnet',
            ...(data.steel_return ? { steel_return: 'steel' } : {}),
            ...(data.magnet2_enabled ? { magnet2_n: 'magnet2', magnet2_s: 'magnet2' } : {}),
          }}
          onDraggableRegionDrop={dropMeshedRegion}
          pointLabels={[
            ...poleLabelsFor(
              data.magnet_center_x_mm,
              data.magnet_center_y_mm,
              data.magnet_angle_deg,
              'magnet',
            ),
            ...(data.magnet2_enabled
              ? poleLabelsFor(
                data.magnet2_center_x_mm ?? PAIR_LAYOUT.second.xMm,
                data.magnet2_center_y_mm ?? PAIR_LAYOUT.second.yMm,
                data.magnet2_angle_deg ?? PAIR_LAYOUT.second.angleDeg,
                'magnet2',
              )
              : []),
          ]}
          measurementGates={data.metrics?.north_face_flux_wb !== undefined ? [
            {
              x1Mm: northGateStart.x,
              y1Mm: northGateStart.y,
              x2Mm: northGateEnd.x,
              y2Mm: northGateEnd.y,
              labelXmm: northGateLabel.x,
              labelYmm: northGateLabel.y,
              label: 'Flux surface',
              detail: `${assumedDepthMm} mm deep`,
              dragKey: 'magnet',
            },
          ] : []}
        />
      )}
    </div>
    );
  };

  if (lessonPhase === 'design') {
    return (
      <main className="learning-shell learning-lesson-shell follow-flux-predict-shell">
        <section className="follow-flux-predict-experience" aria-labelledby="follow-flux-predict-title">
          <header className="follow-flux-predict-heading">
            <p className="learning-kicker">Lesson 1 · Predict</p>
            <h1 id="follow-flux-predict-title">Where does the field go?</h1>
            <p>Choose what happens after the field leaves the magnet&apos;s north pole.</p>
          </header>

          <div className="follow-flux-predict-visual" aria-live="polite">
            <FieldFixtureDiagram prediction={predictionCorrect ? null : prediction} />
          </div>

          <div className="follow-flux-predict-options" role="radiogroup" aria-label="Field path prediction">
            {PREDICTIONS.map((option, index) => (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={prediction === option.id}
                className={`${prediction === option.id ? 'is-selected' : ''}${prediction === option.id && option.id === 'closed-loop' ? ' is-correct' : ''}`}
                onClick={() => setPrediction(option.id)}
              >
                <span>{index + 1}</span>
                <strong>{option.label}</strong>
              </button>
            ))}
          </div>

          <div className="follow-flux-predict-response" aria-live="polite">
            {prediction ? (
              <p className={predictionCorrect ? 'is-correct' : ''}>
                {predictionCorrect
                  ? 'That is the complete model. Now reveal what the solver sees.'
                  : 'A magnetic field cannot have a loose end. Try a path that returns.'}
              </p>
            ) : (
              <p>Make a prediction before seeing the solved field.</p>
            )}
          </div>

          <button
            type="button"
            className="learning-primary-button follow-flux-reveal-button"
            onClick={() => {
              handlePrimary();
              setLabControlsOpen(false);
            }}
            disabled={!predictionCorrect}
          >
            Reveal the field →
          </button>

          <footer className="follow-flux-predict-footer">
            <button type="button" onClick={onBackToCatalog}>← All lessons</button>
            <span>1 of 5 · Predict</span>
          </footer>
        </section>
      </main>
    );
  }

  return (
    <main className={`learning-shell learning-lesson-shell follow-flux-shell is-${lessonPhase}-stage${placementPreviewVisible ? ' is-placement-preview' : ''}${labControlsOpen ? ' is-lab-open' : ''}${solveInspectorOpen ? ' is-inspector-open' : ''}`}>
      {solveInspectorOpen ? (
      <aside className="learning-step-rail follow-flux-status-panel" aria-label="Solve evidence and lesson explanation">
        <button
          type="button"
          className="follow-flux-drawer-close"
          onClick={() => setSolveInspectorOpen(false)}
          aria-label="Close solve inspector"
        >
          ×
        </button>
        <div className="learning-step-header follow-flux-inspector-header">
          <p className="learning-kicker">Inspect the solve</p>
          <h1>{inspectorTitle}</h1>
          <p>{inspectorSummary}</p>
        </div>

        {solveView === 'pair' && pairAttractMetrics && pairRepelMetrics ? (
          <section className="follow-flux-status-comparison is-pair" aria-label="Opposite and like pole field comparison">
            <div className="follow-flux-comparison-metrics">
              <ComparisonMetric
                label="Facing-pole mean |B|"
                air={pairAttractMetrics.working_gap_mean_b_t}
                steel={pairRepelMetrics.working_gap_mean_b_t}
                firstLabel="N → S"
                secondLabel="N ↔ N"
                detail="Field sampled beside the facing pole"
              />
              {pairAttractMetrics.north_face_flux_wb !== undefined && pairRepelMetrics.north_face_flux_wb !== undefined ? (
                <ComparisonMetric
                  label="Flux through magnet 1 N face"
                  air={pairAttractMetrics.north_face_flux_wb}
                  steel={pairRepelMetrics.north_face_flux_wb}
                  formatter={formatMicroWebers}
                  firstLabel="N → S"
                  secondLabel="N ↔ N"
                  detail={`Across the 12 x ${assumedDepthMm} mm surface`}
                />
              ) : null}
              <ComparisonMetric
                label="Far-field leakage"
                air={pairAttractMetrics.outside_field_mean_b_t}
                steel={pairRepelMetrics.outside_field_mean_b_t}
                firstLabel="N → S"
                secondLabel="N ↔ N"
                detail="Near the outer boundary"
              />
            </div>
            <div className="follow-flux-inspector-takeaway">
              <span>Takeaway</span>
              <strong>N→S sends more useful flux across the air gap.</strong>
            </div>
          </section>
        ) : airMetrics && steelMetrics && solveView !== 'pair' ? (
          <section className="follow-flux-status-comparison" aria-label="Air and steel field comparison">
            <div className="follow-flux-comparison-metrics">
              <ComparisonMetric
                label="Magnet-end mean |B|"
                air={airMetrics.working_gap_mean_b_t}
                steel={steelMetrics.working_gap_mean_b_t}
              />
              {airMetrics.north_face_flux_wb !== undefined && steelMetrics.north_face_flux_wb !== undefined ? (
                <ComparisonMetric
                  label="Flux through N face"
                  air={airMetrics.north_face_flux_wb}
                  steel={steelMetrics.north_face_flux_wb}
                  formatter={formatMicroWebers}
                  detail={`Across the 12 x ${assumedDepthMm} mm surface`}
                />
              ) : null}
              <ComparisonMetric
                label="Far-field leakage"
                air={airMetrics.outside_field_mean_b_t}
                steel={steelMetrics.outside_field_mean_b_t}
                lowerIsBetter
              />
            </div>
            <div className="follow-flux-inspector-takeaway">
              <span>{steelInsightCorrect ? 'Why' : 'Notice'}</span>
              <strong>{steelInsightCorrect ? 'Lower reluctance. More flux. Same area.' : 'Same magnet. More flux.'}</strong>
            </div>
          </section>
        ) : activeMetrics ? (
          <section className="follow-flux-status-results" aria-label="Current field measurements">
            <dl className="follow-flux-live-metrics">
              <div><dt>Local end-field |B|</dt><dd>{formatTesla(activeMetrics.working_gap_mean_b_t)}</dd></div>
              <div><dt>Outside leakage</dt><dd>{formatTesla(activeMetrics.outside_field_mean_b_t, 4)}</dd></div>
              <div><dt>Peak |B|</dt><dd>{formatTesla(activeMetrics.peak_b_t)}</dd></div>
            </dl>
          </section>
        ) : (
          <section className="follow-flux-status-results is-awaiting" aria-label="Solve status">
            <h2>Awaiting field solve</h2>
            <p>
              {solveView === 'pair'
                ? magnet2PlacementValid
                  ? pairAttractSolve && pairArrangement === 'repel'
                    ? 'Magnet 2 is flipped. Solve N facing N to capture the comparison frame.'
                    : 'Start with N facing S and solve the attraction baseline.'
                  : 'Move the magnets apart before solving.'
                : solveView === 'steel'
                  ? steelPlacementValid
                    ? 'Place the steel return path, then solve the comparison frame.'
                    : 'Move the steel clear of the magnet before solving.'
                  : magnetPlacementValid
                    ? 'Place the magnet, then solve the open-air baseline.'
                    : 'Keep the magnet inside the field domain before solving.'}
            </p>
          </section>
        )}

        {solveView === 'pair' && pairExperimentComplete ? (
          <section className="follow-flux-inspector-next" aria-label="Continue after reviewing the pole comparison">
            <span>Evidence reviewed?</span>
            <button
              type="button"
              onClick={() => {
                setPairComparisonReviewed(true);
                setSolveInspectorOpen(false);
                setQuizOpen(true);
              }}
            >
              Continue to Check →
            </button>
          </section>
        ) : null}

        <details className="follow-flux-inspector-details">
          <summary>Details · M350-50A</summary>
          <div>
            <p>Electrical steel uses the same M350-50A curve as motor projects.</p>
            {activeMetrics ? <FluxGateReadout metrics={activeMetrics} /> : null}
            <p><b>B</b> is local flux density. <b>&Phi;</b> is total flux. <b>Reluctance</b> resists the magnetic path.</p>
          </div>
        </details>
      </aside>
      ) : null}

      <section className={`learning-main-stage follow-flux-main is-${lessonPhase}-stage${quizOpen ? ' is-quiz-open' : ''}`}>
        {quizOpen ? (
          <div className="follow-flux-quiz-stage">
            <header><p className="learning-kicker">End of lesson</p><h2>Knowledge check</h2><p>Use the two solved frames, not memorized vocabulary.</p></header>
            <details className="learning-quiz-reference follow-flux-inline-quiz-reference">
              <summary>Review lab reference</summary>
              <div>
                <strong>Completed field comparison</strong>
                <p>Open air and steel frames are saved. Reopen this reference only if you need the measurements while answering.</p>
                {activeMetrics ? (
                  <dl>
                    <div><dt>Local end-field |B|</dt><dd>{formatTesla(activeMetrics.working_gap_mean_b_t)}</dd></div>
                    <div><dt>Outside leakage</dt><dd>{formatTesla(activeMetrics.outside_field_mean_b_t, 4)}</dd></div>
                  </dl>
                ) : null}
              </div>
            </details>
            <KnowledgeCheck questions={QUIZ} onPassedChange={setQuizPassed} />
            {quizPassed ? (
              <div className="follow-flux-completion-card">
                <strong>Lesson 1 complete</strong>
                <span>You can now distinguish local B from total flux and explain how return paths and pole orientation control useful air-gap flux.</span>
                <span>Continue to Lesson 2 when you are ready.</span>
              </div>
            ) : null}
          </div>
        ) : !airSolve ? (
          <div className="follow-flux-visual-stack">
            <div className="follow-flux-geometry-preview">
                <UnmeshedFieldDomain
                  magnet={magnetPlacement}
                  disabled={Boolean(busy)}
                  onObjectDrop={dropFixtureObject}
                  onObjectRotate={rotateFixtureObject}
                  onObjectSelect={setSelectedFixtureObject}
                />
            </div>
          </div>
        ) : solveView === 'pair' && !activePairSolve ? (
          <div className="follow-flux-visual-stack">
            <div className="follow-flux-geometry-preview">
                <UnmeshedFieldDomain
                  magnet={magnetPlacement}
                  magnet2={magnet2Placement}
                  disabled={Boolean(busy) || Boolean(pairAttractSolve)}
                  onObjectDrop={dropFixtureObject}
                  onObjectRotate={rotateFixtureObject}
                  onObjectSelect={setSelectedFixtureObject}
                />
            </div>
          </div>
        ) : solveView === 'steel' && !steelSolve ? (
          <div className="follow-flux-visual-stack">
            <div className="follow-flux-geometry-preview">
                <UnmeshedFieldDomain
                  magnet={magnetPlacement}
                  steel={steelPlacement}
                  disabled={Boolean(busy)}
                  onObjectDrop={dropFixtureObject}
                  onObjectRotate={rotateFixtureObject}
                  onObjectSelect={setSelectedFixtureObject}
                />
            </div>
          </div>
        ) : activeData ? (
          <div className="follow-flux-visual-stack">
            {renderViewer(activeData)}
          </div>
        ) : (
          <div className="follow-flux-empty-stage"><div className="follow-flux-solve-icon" aria-hidden="true">B</div><h2>Ready to solve open air</h2><p>The first solve establishes the baseline. The second changes only the return path.</p></div>
        )}

        {!quizOpen ? (
          <div className="follow-flux-lesson-dock" aria-label="Current experiment controls">
            <div className="follow-flux-dock-insight">
              <span>{lessonProgressSteps.find((item) => item.id === activeProgressStepId)?.label}</span>
              <strong>{stageInsight}</strong>
            </div>
            <div className="follow-flux-dock-actions">
              <button
                type="button"
                className="follow-flux-dock-button"
                aria-expanded={labControlsOpen}
                onClick={() => {
                  setLabControlsOpen((open) => !open);
                  setSolveInspectorOpen(false);
                }}
              >
                {labControlsOpen ? 'Done' : 'Adjust experiment'}
              </button>
              <button
                type="button"
                className="follow-flux-dock-button"
                aria-expanded={solveInspectorOpen}
                onClick={() => {
                  setSolveInspectorOpen((open) => !open);
                  setLabControlsOpen(false);
                }}
              >
                Inspect the solve
              </button>
              {!lessonComplete ? (
                <button
                  type="button"
                  className="learning-primary-button follow-flux-dock-primary"
                  onClick={() => {
                    if (dockNeedsControls) {
                      setLabControlsOpen(true);
                      setSolveInspectorOpen(false);
                    } else {
                      handlePrimary();
                    }
                  }}
                  disabled={dockNeedsControls ? false : primaryDisabled}
                >
                  {primaryLabel}
                </button>
              ) : (
                <a className="learning-primary-button follow-flux-dock-primary" href="/tutorials/lesson-2">Next lesson</a>
              )}
            </div>
          </div>
        ) : (
          <div className="follow-flux-lesson-dock follow-flux-quiz-dock" aria-label="Knowledge check controls">
            <div className="follow-flux-dock-insight">
              <span>Check</span>
              <strong>
                {quizPassed
                  ? 'Lesson complete. Continue when you’re ready.'
                  : 'Answer all four questions to complete Lesson 1.'}
              </strong>
            </div>
            <div className="follow-flux-dock-actions">
              <button
                type="button"
                className="follow-flux-dock-button"
                onClick={() => {
                  setQuizOpen(false);
                  setSolveView('pair');
                  setLabControlsOpen(false);
                  setSolveInspectorOpen(true);
                }}
              >
                Review experiment
              </button>
              <button type="button" className="follow-flux-dock-button" onClick={onBackToCatalog}>
                Lessons
              </button>
              {quizPassed ? (
                <a className="learning-primary-button follow-flux-dock-primary" href="/tutorials/lesson-2">
                  Next: Close the Loop
                </a>
              ) : null}
            </div>
          </div>
        )}
      </section>

      {labControlsOpen && !quizOpen ? (
      <aside className="learning-control-panel follow-flux-control-panel">
        <button
          type="button"
          className="follow-flux-drawer-close"
          onClick={() => setLabControlsOpen(false)}
          aria-label="Close experiment controls"
        >
          ×
        </button>
        <section className="learning-control-section">
          <p className="follow-flux-panel-kicker">Lab setup · {lessonProgressSteps.find((item) => item.id === activeProgressStepId)?.label}</p>
          <h2>{lessonPhase === 'pair' ? 'Two-magnet lab' : 'Field lab'}</h2>
          <section className="follow-flux-lab-goal" aria-label="Current lesson goal">
            <span>{completedLessonStepCount}/{lessonProgressSteps.length}</span>
            <div>
              <p>Current goal</p>
              <strong>{currentGoal.title}</strong>
              <small>{currentGoal.detail}</small>
            </div>
          </section>
          {lessonPhase === 'pair' ? (
            <ol className="follow-flux-pair-sequence" aria-label="Two-magnet comparison steps">
              <li className={pairAttractSolve ? 'is-complete' : 'is-active'}>
                <span>{pairAttractSolve ? '✓' : '1'}</span>
                <div><strong>N facing S</strong><small>Capture the attraction baseline</small></div>
              </li>
              <li className={pairRepelSolve ? 'is-complete' : pairAttractSolve ? 'is-active' : ''}>
                <span>{pairRepelSolve ? '✓' : '2'}</span>
                <div><strong>N facing N</strong><small>Flip magnet 2 and solve again</small></div>
              </li>
            </ol>
          ) : null}
          <>
              <div className="follow-flux-view-toggle" role="group" aria-label="Solved fixture view">
                <button type="button" className={solveView === 'air' ? 'is-active' : ''} onClick={() => { setSolveView('air'); setSelectedFixtureObject('magnet'); }} disabled={!airSolve}>Open air</button>
                <button type="button" className={solveView === 'steel' ? 'is-active' : ''} onClick={() => { setSolveView('steel'); setSelectedFixtureObject('steel'); }} disabled={!airSolve}>Steel object</button>
                {lessonPhase === 'pair' ? (
                  <button type="button" className={solveView === 'pair' ? 'is-active' : ''} onClick={() => { setSolveView('pair'); setSelectedFixtureObject('magnet2'); }}>Two magnets</button>
                ) : null}
              </div>
              {lessonPhase === 'solve' && steelSolve ? (
                steelInsightCorrect ? (
                  <section className="follow-flux-insight-complete" aria-label="Steel comparison quick check complete">
                    <span aria-hidden="true">✓</span>
                    <div><small>Quick check complete</small><strong>Lower reluctance redirects more flux through steel.</strong></div>
                  </section>
                ) : (
                  <section className="follow-flux-steel-insight-check" aria-label="Steel comparison quick check">
                    <p className="learning-kicker">Quick check · required</p>
                    <h3>Why did |B| rise near the magnet?</h3>
                    <p>The magnet and its pole-face area did not change. Choose the explanation that matches the two solved frames.</p>
                    <div className="follow-flux-predictions">
                      {STEEL_INSIGHT_OPTIONS.map((option) => (
                        <button
                          key={option.id}
                          type="button"
                          className={`${steelInsightAnswer === option.id ? 'is-selected' : ''}`}
                          onClick={() => setSteelInsightAnswer(option.id)}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                    {steelInsightAnswer ? <p className="follow-flux-feedback">Not quite. The magnet strength and pole-face area stayed fixed. Look for the answer that changes only the return path.</p> : null}
                  </section>
                )
              ) : null}
              {!quizOpen ? (
                <section className="follow-flux-steel-controls" aria-label="Fixture position and angle controls">
                  <div className="follow-flux-steel-controls-heading">
                    <strong>{lessonPhase === 'pair' && pairAttractSolve ? 'Comparison geometry locked' : 'Selected object'}</strong>
                    <span>{selectedObjectLabel}</span>
                  </div>

                  {!selectedControlsLocked && !hasManipulatedFixture ? (
                    <div className="follow-flux-direct-manipulation-hint">
                      <span aria-hidden="true">↔</span>
                      <div>
                        <strong>Move it on the canvas</strong>
                        <small>Drag an object to move it. Drag its cyan handle to rotate.</small>
                      </div>
                    </div>
                  ) : selectedControlsLocked ? (
                    <p className="follow-flux-drag-note">Positions stay fixed after the baseline so the 180° polarity flip is the only changed variable.</p>
                  ) : null}

                  {solveView === 'steel' || solveView === 'pair' ? (
                    <div className="follow-flux-object-selector" role="group" aria-label="Object to position">
                      <button
                        type="button"
                        className={selectedFixtureObject === 'magnet' ? 'is-active' : ''}
                        aria-pressed={selectedFixtureObject === 'magnet'}
                        onClick={() => setSelectedFixtureObject('magnet')}
                      >
                        {lessonPhase === 'pair' ? 'Magnet 1' : 'Magnet'}
                      </button>
                      <button
                        type="button"
                        className={selectedFixtureObject === (solveView === 'pair' ? 'magnet2' : 'steel') ? 'is-active' : ''}
                        aria-pressed={selectedFixtureObject === (solveView === 'pair' ? 'magnet2' : 'steel')}
                        onClick={() => setSelectedFixtureObject(solveView === 'pair' ? 'magnet2' : 'steel')}
                      >
                        {solveView === 'pair' ? 'Magnet 2' : 'Steel'}
                      </button>
                    </div>
                  ) : null}

                  {solveView === 'steel' && selectedFixtureObject === 'steel' ? (
                    <div className="follow-flux-shape-control">
                      <span>Steel shape</span>
                      <div className="follow-flux-shape-selector" role="group" aria-label="Steel shape">
                        {(Object.entries(STEEL_SHAPES) as Array<[SteelShape, typeof STEEL_SHAPES[SteelShape]]>).map(([shape, metadata]) => (
                          <button
                            key={shape}
                            type="button"
                            className={steelPlacement.shape === shape ? 'is-active' : ''}
                            aria-pressed={steelPlacement.shape === shape}
                            onClick={() => selectSteelShape(shape)}
                            disabled={Boolean(busy)}
                            title={metadata.description}
                          >
                            {metadata.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <details className="follow-flux-precision-controls">
                    <summary>
                      <span>Precise positioning</span>
                      <strong>{selectedPlacement.xMm.toFixed(0)}, {selectedPlacement.yMm.toFixed(0)} mm · {selectedPlacement.angleDeg.toFixed(0)}°</strong>
                    </summary>
                    <div className="follow-flux-precision-grid">
                      <label>
                        <span>X</span>
                        <div><input type="number" min={-selectedXLimit} max={selectedXLimit} step={1} value={selectedPlacement.xMm} onChange={(event) => updateSelectedPlacement('xMm', Number(event.target.value))} disabled={selectedControlsLocked} aria-label={`${selectedObjectLabel} horizontal position in millimeters`} /><em>mm</em></div>
                      </label>
                      <label>
                        <span>Y</span>
                        <div><input type="number" min={-selectedYLimit} max={selectedYLimit} step={1} value={selectedPlacement.yMm} onChange={(event) => updateSelectedPlacement('yMm', Number(event.target.value))} disabled={selectedControlsLocked} aria-label={`${selectedObjectLabel} vertical position in millimeters`} /><em>mm</em></div>
                      </label>
                      <label>
                        <span>Angle</span>
                        <div><input type="number" min={-180} max={180} step={5} value={selectedPlacement.angleDeg} onChange={(event) => updateSelectedPlacement('angleDeg', Number(event.target.value))} disabled={selectedControlsLocked || (selectedFixtureObject === 'steel' && steelPlacement.shape === 'puck')} aria-label={`${selectedObjectLabel} angle in degrees`} /><em>°</em></div>
                      </label>
                    </div>
                    <button type="button" className="follow-flux-reset-position" onClick={resetSelectedPlacement} disabled={selectedControlsLocked}>Reset {selectedObjectLabel.toLowerCase()}</button>
                  </details>

                  {solveView === 'pair' && pairAttractSolve && !pairRepelSolve ? (
                    <div className={`follow-flux-pair-flip-prompt${pairArrangement === 'repel' ? ' is-flipped' : ''}`}>
                      <strong>{pairArrangement === 'repel' ? 'N now faces N' : 'Next: flip magnet 2'}</strong>
                      <p>{pairArrangement === 'repel' ? 'The positions stayed fixed. Solve this orientation next.' : 'Use the orange action below for the controlled 180° flip.'}</p>
                    </div>
                  ) : null}
                  {solveView === 'pair' && !magnet2PlacementValid ? (
                    <p className="follow-flux-placement-error">The two magnets overlap. Move one apart before solving.</p>
                  ) : solveView === 'pair' && pairFacing ? (
                    <div className={`follow-flux-pair-readout is-${pairFacing.arrangement}`}>
                      <strong>{pairFacing.firstFacingPole} facing {pairFacing.secondFacingPole} · {pairFacing.arrangement === 'attract' ? 'they attract' : 'they repel'}</strong>
                      <p>{pairFacing.arrangement === 'attract' ? 'Opposite poles create one shared loop across the gap.' : 'Like poles squeeze the field sideways and quiet the gap.'}</p>
                      <span>{pairFacing.separationMm.toFixed(0)} mm between centres</span>
                    </div>
                  ) : solveView === 'pair' ? (
                    <p className="follow-flux-placement-note">The magnets are broadside. Turn their pole faces toward the gap for a clear comparison.</p>
                  ) : null}
                  {solveView === 'steel' && !steelPlacementValid ? <p className="follow-flux-placement-error">Move the steel clear of the magnet and keep both objects inside the domain before solving.</p> : null}
                </section>
              ) : null}
          </>
        </section>
        {error ? <p className="learning-nav-error">{error}</p> : null}
      </aside>
      ) : null}
    </main>
  );
};
