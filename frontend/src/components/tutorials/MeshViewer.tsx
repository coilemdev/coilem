import React, { useRef, useState, useCallback, useEffect, useMemo } from 'react';
import type { FieldLinePlotData, MeshPreviewData } from './lessonSolveTypes';
import { BACK_EMF_PHASE_COLORS } from './phaseColors';
import { deriveMagneticPolarityCues } from './fieldPolarityCues';
import { buildDominantFieldLinePath } from './fieldLineStitching';
import type { FieldLinePathSegment } from './fieldLineStitching';
import { FIELD_LINE_STRENGTH_PALETTE } from './fieldLineStyle';
import './meshviewer.css';

/** Color map for mesh regions — matches the motor schematic palette. */
const REGION_COLORS: Record<string, string> = {
  air: '#0b1220',
  steel_return: '#64748b',
  iron_ring: '#64748b',
  iron_tooth: '#94a3b8',
  iron_yoke: '#64748b',
  iron_return_tooth: '#64748b',
  iron_rotor: '#475569',
  spm_magnet_n: '#ef4444',
  rotor_core: '#6b7280',
  magnet: '#3b82f6',
  magnet_n: '#ef4444',
  magnet_s: '#3b82f6',
  // Lesson 1's second magnet. Same pole colours as the first: an unmapped region
  // falls back to pale grey, which read as an unidentified blob rather than a magnet.
  magnet2_n: '#ef4444',
  magnet2_s: '#3b82f6',
  force_magnet_n: '#ef4444',
  force_magnet_s: '#3b82f6',
  magnet_pocket_air: '#1f2937',
  airgap: '#ffffff',
  air_gap: '#ffffff',
  stator_tooth: '#9ca3af',
  two_phase_stator_tooth_a: '#22d3ee',
  two_phase_stator_tooth_b: '#f59e0b',
  stator_yoke: '#4b5563',
  slot_winding: '#f59e0b',
  slot_winding_a: BACK_EMF_PHASE_COLORS.A,
  slot_winding_b: BACK_EMF_PHASE_COLORS.B,
  slot_winding_c: BACK_EMF_PHASE_COLORS.C,
  wire: '#d97706',
  tooth_coil_out: '#d97706',
  tooth_coil_in: '#d97706',
  capstone_magnet_n: '#ef4444',
  capstone_magnet_s: '#3b82f6',
  capstone_back_iron: '#475569',
  capstone_winding_out: '#f59e0b',
  capstone_winding_in: '#d97706',
  shaft: '#111827',
};

const REGION_LABELS: Record<string, string> = {
  air: 'Air',
  steel_return: 'Steel Return Path',
  iron_ring: 'M350-50A Steel Ring',
  iron_tooth: 'Energized M350-50A Tooth',
  iron_yoke: 'M350-50A Stator Yoke',
  iron_return_tooth: 'M350-50A Return Tooth',
  iron_rotor: 'M350-50A Rotor Return',
  spm_magnet_n: 'N42 Surface Magnet · North Face',
  rotor_core: 'Rotor Core',
  magnet: 'Magnet',
  magnet_n: 'North Magnet',
  magnet_s: 'South Magnet',
  magnet2_n: 'North Magnet 2',
  magnet2_s: 'South Magnet 2',
  force_magnet_n: 'North pole magnet',
  force_magnet_s: 'South pole magnet',
  magnet_pocket_air: 'Magnet Pocket Air',
  airgap: 'Airgap',
  stator_tooth: 'Stator Tooth',
  two_phase_stator_tooth_a: 'Phase A Stator Iron',
  two_phase_stator_tooth_b: 'Phase B Stator Iron',
  stator_yoke: 'Stator Yoke',
  slot_winding: 'Winding',
  slot_winding_a: 'Phase A Winding',
  slot_winding_b: 'Phase B Winding',
  slot_winding_c: 'Phase C Winding',
  wire: 'Copper conductor',
  tooth_coil_out: 'Coil Current Out of Screen',
  tooth_coil_in: 'Coil Current Into Screen',
  capstone_magnet_n: 'Linear Track Magnet · North Face Up',
  capstone_magnet_s: 'Linear Track Magnet · South Face Up',
  capstone_back_iron: 'M350-50A Back Iron',
  capstone_winding_out: 'Moving Winding · Current Out of Screen',
  capstone_winding_in: 'Moving Winding · Current Into Screen',
  shaft: 'Shaft Bore',
};

const SCALE_BAR_TARGET_PX = 96;
const SCALE_BAR_STEPS_MM = [1, 2, 5, 10, 20, 50, 100, 200];
const ROTOR_REGIONS = new Set([
  'rotor_core',
  'magnet',
  'magnet_n',
  'magnet_s',
  'spm_magnet_n',
  'magnet_pocket_air',
  'shaft',
]);
const FIELD_LINE_DIRECTION_ARROW_TARGET = 28;
const FIELD_LINE_CORE_LOOP_SUPPRESS_RADIUS_RATIO = 0.56;
const FIELD_LINE_CORE_LOOP_KEEP_PER_LEVEL = 3;

interface FieldDirectionArrow {
  angleDeg: number;
  key: string;
  opacity: number;
  x: number;
  y: number;
}

type MeshViewerData = MeshPreviewData | FieldLinePlotData;
type TutorialOverlayMode = 'flux' | 'forces' | 'mmf';
type TorqueDirection = 'cw' | 'ccw' | 'zero';
type MagnetizationLabelMode = 'both' | 'pm' | 'stator';

export interface WindingCurrentCue {
  slotIndex: number;
  angleDeg: number;
  phase: 'A' | 'B' | 'C';
  phaseCurrentA: number;
  slotCurrentA: number;
}

export interface WindingMmfSampleSector {
  startAngleDeg: number;
  endAngleDeg: number;
  startSlotIndex: number;
  endSlotIndex: number;
  sampleAngleDeg: number;
  ampereTurns: number;
}

export interface MeshViewerPointLabel {
  xMm: number;
  yMm: number;
  label: string;
  /** Optional value rendered beside the badge so the central marker can stay large. */
  detailLabel?: string;
  tone?: 'north' | 'south' | 'neutral';
  dragKey?: string;
  scale?: number;
  textScale?: number;
  showBadge?: boolean;
}

export interface MeshViewerMeasurementGate {
  x1Mm: number;
  y1Mm: number;
  x2Mm: number;
  y2Mm: number;
  labelXmm: number;
  labelYmm: number;
  label: string;
  detail?: string;
  dragKey?: string;
}

export interface MeshViewerForceVector {
  x1Mm: number;
  y1Mm: number;
  x2Mm: number;
  y2Mm: number;
  label?: string;
}

export interface MeshViewerDirectionVector {
  x1Mm: number;
  y1Mm: number;
  x2Mm: number;
  y2Mm: number;
  label?: string;
  labelXmm?: number;
  labelYmm?: number;
  tone?: 'cyan' | 'blue' | 'slate' | 'amber';
  /** Optional host palette. Different endpoints render as a directional gradient. */
  colorStart?: string;
  colorEnd?: string;
  labelColor?: string;
  dashed?: boolean;
  strokeScale?: number;
  /** Optional construction circle centered on the vector origin. */
  orbitGuideRadiusMm?: number;
}

const directionVectorToneColor = (tone: MeshViewerDirectionVector['tone']) => (
  tone === 'blue'
    ? '#60a5fa'
    : tone === 'slate'
      ? '#cbd5e1'
      : tone === 'amber'
        ? '#f59e0b'
        : '#67e8f9'
);

export interface MeshViewerDipoleMarker {
  xMm: number;
  yMm: number;
  angleDeg: number;
  lengthMm: number;
  thicknessMm: number;
  shape?: 'bar' | 'surface-arcs';
  rotorRadiusMm?: number;
  poleArcDeg?: number;
  poleThicknessMm?: number;
  torqueDirection?: 'cw' | 'ccw';
  animateTorque?: boolean;
}

const annularSectorPath = (
  centerAngleDeg: number,
  spanDeg: number,
  innerRadius: number,
  outerRadius: number,
) => {
  const toRadians = (angleDeg: number) => (angleDeg * Math.PI) / 180;
  const startAngle = toRadians(centerAngleDeg - (spanDeg / 2));
  const endAngle = toRadians(centerAngleDeg + (spanDeg / 2));
  const point = (radius: number, angle: number) => ({
    x: radius * Math.cos(angle),
    y: radius * Math.sin(angle),
  });
  const outerStart = point(outerRadius, startAngle);
  const outerEnd = point(outerRadius, endAngle);
  const innerEnd = point(innerRadius, endAngle);
  const innerStart = point(innerRadius, startAngle);
  const largeArc = spanDeg > 180 ? 1 : 0;
  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerRadius} ${outerRadius} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
    'Z',
  ].join(' ');
};

/** Turbo-like ramp for the |B| intensity layer, low to high. */
const FIELD_INTENSITY_COLORS = [
  '#30123b',
  '#4145ab',
  '#4675ed',
  '#39a2fc',
  '#1bcdd4',
  '#24f894',
  '#7dff5f',
  '#c1f334',
  '#f8ca25',
  '#f39411',
  '#e64c02',
  '#a21401',
];

const interpolateHexColor = (start: string, end: string, t: number) => {
  const channel = (color: string, offset: number) => Number.parseInt(color.slice(offset, offset + 2), 16);
  const toHex = (value: number) => Math.round(value).toString(16).padStart(2, '0');
  return `#${[1, 3, 5].map((offset) => (
    toHex(channel(start, offset) + (channel(end, offset) - channel(start, offset)) * t)
  )).join('')}`;
};

const buildInterpolatedPalette = (colors: readonly string[], count: number) => (
  Array.from({ length: count }, (_, index) => {
    const position = index * (colors.length - 1) / Math.max(1, count - 1);
    const lower = Math.floor(position);
    const upper = Math.min(colors.length - 1, Math.ceil(position));
    return interpolateHexColor(colors[lower], colors[upper], position - lower);
  })
);

const SMOOTH_FIELD_INTENSITY_COLORS = buildInterpolatedPalette(FIELD_INTENSITY_COLORS, 48);

interface MeshViewerProps {
  meshData: MeshViewerData;
  onClose?: () => void;
  embedded?: boolean;
  compactEmbedded?: boolean;
  minScale?: number;
  title?: string;
  subtitle?: string | null;
  /** Host-provided controls rendered in the viewer title bar. */
  headerActions?: React.ReactNode;
  showRotorAnimationControls?: boolean;
  rotorAngleDeg?: number;
  statorFieldAngleDeg?: number;
  tutorialOverlayMode?: TutorialOverlayMode;
  torqueDirection?: TorqueDirection;
  showMagnetizationLabels?: boolean;
  shaftRadiusMm?: number;
  /** Optional host interaction for workflows that configure material regions. */
  onRegionClick?: (region: string) => void;
  selectedRegion?: string | null;
  /** Keep the geometry fit to frame and omit zoom/pan controls. */
  fixedView?: boolean;
  /** Reduce the toolbar to zoom in, zoom out, and fit controls. */
  toolbarMode?: 'full' | 'zoom-only';
  /** Optional visualization label shown beside the zoom-only controls. */
  toolbarLabel?: string;
  /** Show triangle boundaries on top of the material regions. */
  showMeshEdges?: boolean;
  /** Geometry-anchored badges that follow the mesh through zoom and pan. */
  pointLabels?: readonly MeshViewerPointLabel[];
  /** Geometry-anchored integration surfaces used by teaching measurements. */
  measurementGates?: readonly MeshViewerMeasurementGate[];
  /** Geometry-anchored force arrows used by teaching fixtures. */
  forceVectors?: readonly MeshViewerForceVector[];
  /** Geometry-anchored directional arrows used to explain field paths. */
  directionVectors?: readonly MeshViewerDirectionVector[];
  /** Geometry-anchored permanent-magnet dipoles used by teaching overlays. */
  dipoleMarkers?: readonly MeshViewerDipoleMarker[];
  /** Presentation zoom supplied by an embedding workflow. */
  viewScale?: number;
  /** Let presentation zoom extend beyond the viewer's internal SVG bounds. */
  allowOverflow?: boolean;
  /** Color winding regions with the A/B/C phase palette. */
  colorCodeWindings?: boolean;
  /** Split each concentrated-winding slot between its two adjacent tooth coils. */
  splitConcentratedSlotWindings?: boolean;
  /** Allow mouse-drag panning even in fixedView (zoom stays host-controlled). */
  panEnabled?: boolean;
  /** Disable camera panning while preserving toolbar zoom. */
  viewportPanEnabled?: boolean;
  /** Map material region names to a shared draggable object key. */
  draggableRegionGroups?: Readonly<Record<string, string>>;
  /** Commit a material object's model-space displacement after mouse drop. */
  onDraggableRegionDrop?: (dragKey: string, deltaXMm: number, deltaYMm: number) => void;
  /** Bump to reset pan/zoom back to the fitted view from the host. */
  panResetToken?: number;
  /** Keep the user's current pan/zoom when the host swaps solved frames. */
  preserveViewportOnMeshChange?: boolean;
  /** Paint a |B| intensity heat layer under the flux lines (solved frames). */
  showFieldIntensity?: boolean;
  /** Keep |B| colors comparable across multiple solved frames. */
  fieldIntensityRange?: Readonly<{ low: number; high: number }>;
  /** Blend element colors into a denser, presentation-quality |B| map. */
  smoothFieldIntensity?: boolean;
  /** Optional host override for field-line visibility in custom view toggles. */
  fieldLinesVisible?: boolean;
  /** Pulse the B direction arrows so the local field direction reads at a glance. */
  animateFieldArrows?: boolean;
  /** Restrict N/S teaching labels to one source (PM-only / armature-only views). */
  magnetizationLabelMode?: MagnetizationLabelMode;
  /** Render magnet material without the N/S alternating color split. */
  neutralMagnets?: boolean;
  /** Show each Lesson 5 bar magnet as one body with S and N polarity halves. */
  splitForceMagnetPolarity?: boolean;
  /** Polarity axis (deg, mesh frame) for split force-magnet fills. Used when
   * the host rotates the solved fixture rigidly, so the S→N gradient follows
   * the rotated magnetization direction instead of staying axis-aligned. */
  forceMagnetPolarityAxisDeg?: number;
  /** Baked N-pole direction (deg, mesh frame). Used for magnet polarity when
   * the displayed field cannot reveal it (armature-only frames, Br = 0). */
  magnetPolarityHintDeg?: number | null;
  /** Place stator N/S cues where the active solved air-gap Br profile puts the
   * poles instead of pinning them to the analytic current axis. */
  statorPoleLabelsFromField?: boolean;
  /** Match MotorViewport's canonical solver/SVG convention, where solver +Y
   * is rendered downward. Legacy mesh views retain their mirrored math +Y-up
   * presentation unless this is enabled. */
  useSolverScreenCoordinates?: boolean;
  /** Instantaneous signed conductor currents shown over the winding slots in
   * the teaching MMF overlay. Positive uses a dot; negative uses a cross. */
  windingCurrentCues?: readonly WindingCurrentCue[];
  /** Keep slot identities visible while presenting phase badges as inactive.
   * Used by PM-only field views, where the stator winding current is 0 A. */
  windingCurrentCuesMuted?: boolean;
  /** Air-gap sector associated with the selected winding-MMF chart sample. */
  windingMmfSampleSector?: WindingMmfSampleSector | null;
}

const hasFieldLines = (meshData: MeshViewerData): meshData is FieldLinePlotData => (
  'contour_levels' in meshData
);

function alternatingMagnetRegion(
  nodes: [number, number][],
  triangle: [number, number, number],
  poleCount: number,
): 'magnet_n' | 'magnet_s' {
  const [a, b, c] = triangle;
  const centroidX = (nodes[a][0] + nodes[b][0] + nodes[c][0]) / 3;
  const centroidY = (nodes[a][1] + nodes[b][1] + nodes[c][1]) / 3;
  const safePoleCount = Math.max(2, Math.round(poleCount));
  const polePitchDeg = 360 / safePoleCount;
  const angleDeg = ((Math.atan2(centroidY, centroidX) * 180) / Math.PI + 360) % 360;
  const poleIndex = Math.floor((angleDeg + polePitchDeg / 2) / polePitchDeg) % safePoleCount;
  return poleIndex % 2 === 0 ? 'magnet_n' : 'magnet_s';
}

/**
 * Classify magnet triangles per physical magnet arc instead of per fixed
 * stator-frame sector. Solved frame meshes arrive already rotated to the
 * sweep angle, so sector-based coloring slices one magnet across the N/S
 * boundary mid-rotation. Here we cluster triangles into arcs by angular gaps,
 * then read each arc's polarity from the solved radial B field (outward = N).
 * Returns null when the magnets form a continuous ring so callers can fall
 * back to the legacy sector coloring.
 */
function classifyMagnetArcs(
  nodes: [number, number][],
  triangles: [number, number, number][],
  regions: string[],
  poleCount: number,
  elementBxT?: number[],
  elementByT?: number[],
  northHintAngleDeg?: number | null,
): Map<number, 'magnet_n' | 'magnet_s'> | null {
  const safePoleCount = Math.max(2, Math.round(poleCount));
  const polePitchDeg = 360 / safePoleCount;
  const bx = elementBxT && elementBxT.length === triangles.length ? elementBxT : null;
  const by = elementByT && elementByT.length === triangles.length ? elementByT : null;
  const hasElementB = bx !== null && by !== null;
  const entries: { index: number; angleDeg: number; area: number; radialB: number }[] = [];

  for (let index = 0; index < triangles.length; index += 1) {
    if (regions[index] !== 'magnet') continue;
    const [a, b, c] = triangles[index];
    const na = nodes[a];
    const nb = nodes[b];
    const nc = nodes[c];
    const centroidX = (na[0] + nb[0] + nc[0]) / 3;
    const centroidY = (na[1] + nb[1] + nc[1]) / 3;
    const radius = Math.hypot(centroidX, centroidY);
    if (radius <= 1e-9) continue;
    const area = Math.abs(
      (nb[0] - na[0]) * (nc[1] - na[1]) - (nc[0] - na[0]) * (nb[1] - na[1])
    ) / 2;
    const radialB = hasElementB
      ? ((bx as number[])[index] * centroidX + (by as number[])[index] * centroidY) / radius
      : 0;
    entries.push({
      index,
      angleDeg: ((Math.atan2(centroidY, centroidX) * 180) / Math.PI + 360) % 360,
      area,
      radialB,
    });
  }
  if (entries.length === 0) return null;

  entries.sort((p, q) => p.angleDeg - q.angleDeg);
  const gapThresholdDeg = Math.max(3, polePitchDeg * 0.1);

  // Anchor the arc walk just after the largest angular gap so no arc straddles 0/360.
  let largestGapIndex = 0;
  let largestGapDeg = -1;
  for (let i = 0; i < entries.length; i += 1) {
    const next = entries[(i + 1) % entries.length];
    const gapDeg = i === entries.length - 1
      ? entries[0].angleDeg + 360 - entries[i].angleDeg
      : entries[i + 1].angleDeg - entries[i].angleDeg;
    if (gapDeg > largestGapDeg) {
      largestGapDeg = gapDeg;
      largestGapIndex = i;
    }
  }
  if (largestGapDeg <= gapThresholdDeg) return null;

  const arcs: { index: number; angleDeg: number; area: number; radialB: number }[][] = [];
  let currentArc: { index: number; angleDeg: number; area: number; radialB: number }[] = [];
  for (let offset = 0; offset < entries.length; offset += 1) {
    const position = (largestGapIndex + 1 + offset) % entries.length;
    const entry = entries[position];
    if (currentArc.length > 0) {
      const previous = entries[(position + entries.length - 1) % entries.length];
      const gapDeg = (entry.angleDeg - previous.angleDeg + 360) % 360;
      if (gapDeg > gapThresholdDeg) {
        arcs.push(currentArc);
        currentArc = [];
      }
    }
    currentArc.push(entry);
  }
  if (currentArc.length > 0) arcs.push(currentArc);

  const assignments = new Map<number, 'magnet_n' | 'magnet_s'>();
  for (const arc of arcs) {
    let areaSum = 0;
    let xSum = 0;
    let ySum = 0;
    let radialBSum = 0;
    for (const entry of arc) {
      const weight = Math.max(entry.area, 1e-9);
      const radians = (entry.angleDeg * Math.PI) / 180;
      areaSum += weight;
      xSum += Math.cos(radians) * weight;
      ySum += Math.sin(radians) * weight;
      radialBSum += entry.radialB * weight;
    }
    const meanRadialB = radialBSum / areaSum;
    const arcCenterDeg = ((Math.atan2(ySum, xSum) * 180) / Math.PI + 360) % 360;
    let isNorth: boolean;
    if (northHintAngleDeg !== undefined && northHintAngleDeg !== null && Number.isFinite(northHintAngleDeg)) {
      // Caller knows where the bake put the N pole (e.g. armature-only frames
      // solve magnets at Br = 0, so their B field cannot reveal polarity).
      const offsetDeg = (((arcCenterDeg - northHintAngleDeg) % 360) + 360) % 360;
      const poleIndex = Math.round(offsetDeg / polePitchDeg) % safePoleCount;
      isNorth = poleIndex % 2 === 0;
    } else if (hasElementB && Number.isFinite(meanRadialB) && Math.abs(meanRadialB) > 1e-6) {
      isNorth = meanRadialB > 0;
    } else {
      // No solved B field (mesh preview): keep the base-angle alternating convention.
      const poleIndex = Math.round(arcCenterDeg / polePitchDeg) % safePoleCount;
      isNorth = poleIndex % 2 === 0;
    }
    for (const entry of arc) {
      assignments.set(entry.index, isNorth ? 'magnet_n' : 'magnet_s');
    }
  }
  return assignments;
}

function fieldStrengthStyle(
  bMagT: number | undefined,
  range: { low: number; high: number } | null,
): { opacity: number; stroke: string; widthScale: number } {
  if (!range || bMagT === undefined || !Number.isFinite(bMagT)) {
    return FIELD_LINE_STRENGTH_PALETTE[Math.floor(FIELD_LINE_STRENGTH_PALETTE.length / 2)];
  }
  const span = range.high - range.low;
  const normalized = span > 1e-9
    ? Math.max(0, Math.min(1, (bMagT - range.low) / span))
    : 0.5;
  const index = Math.min(
    FIELD_LINE_STRENGTH_PALETTE.length - 1,
    Math.max(0, Math.floor(normalized * FIELD_LINE_STRENGTH_PALETTE.length)),
  );
  return FIELD_LINE_STRENGTH_PALETTE[index];
}

export const MeshViewer: React.FC<MeshViewerProps> = ({
  meshData,
  onClose,
  embedded = false,
  compactEmbedded = false,
  minScale = 0.1,
  title,
  subtitle,
  headerActions,
  showRotorAnimationControls = false,
  rotorAngleDeg: controlledRotorAngleDeg,
  statorFieldAngleDeg = 0,
  tutorialOverlayMode = 'flux',
  torqueDirection = 'zero',
  showMagnetizationLabels = false,
  shaftRadiusMm,
  onRegionClick,
  selectedRegion = null,
  fixedView = false,
  toolbarMode = 'full',
  toolbarLabel,
  showMeshEdges = true,
  pointLabels = [],
  measurementGates = [],
  forceVectors = [],
  directionVectors = [],
  dipoleMarkers = [],
  viewScale = 1,
  allowOverflow = false,
  colorCodeWindings = false,
  splitConcentratedSlotWindings = false,
  panEnabled = false,
  viewportPanEnabled = true,
  draggableRegionGroups,
  onDraggableRegionDrop,
  panResetToken,
  preserveViewportOnMeshChange = false,
  showFieldIntensity = false,
  fieldIntensityRange,
  smoothFieldIntensity = false,
  fieldLinesVisible,
  animateFieldArrows = false,
  magnetizationLabelMode = 'both',
  neutralMagnets = false,
  splitForceMagnetPolarity = false,
  forceMagnetPolarityAxisDeg = 0,
  magnetPolarityHintDeg = null,
  statorPoleLabelsFromField = false,
  useSolverScreenCoordinates = false,
  windingCurrentCues = [],
  windingCurrentCuesMuted = false,
  windingMmfSampleSector = null,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const animationFrameRef = useRef<number | null>(null);
  const lastFrameTimeRef = useRef<number | null>(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const [activeRegionDrag, setActiveRegionDrag] = useState<{
    dragKey: string;
    startSvgX: number;
    startSvgY: number;
    deltaXMm: number;
    deltaYMm: number;
  } | null>(null);
  const activeRegionDragRef = useRef<typeof activeRegionDrag>(null);
  const [hoveredRegion, setHoveredRegion] = useState<string | null>(null);
  const [showDimensions, setShowDimensions] = useState(false);
  const [showMesh, setShowMesh] = useState(true);
  const [showFieldLines, setShowFieldLines] = useState(hasFieldLines(meshData));
  const effectiveShowFieldLines = fieldLinesVisible ?? showFieldLines;
  const [isAnimating, setIsAnimating] = useState(false);
  const [animationSpeed, setAnimationSpeed] = useState(1);
  const [animatedRotorAngleDeg, setAnimatedRotorAngleDeg] = useState(0);
  const effectiveRotorAngleDeg = controlledRotorAngleDeg ?? animatedRotorAngleDeg;
  const effectiveScale = transform.scale * Math.max(0.1, viewScale);
  const solverYSign = useSolverScreenCoordinates ? 1 : -1;
  const forceMarkerId = React.useId().replace(/:/g, '');
  const forcePolarityGradientPrefix = React.useId().replace(/:/g, '');
  const directionVectorDefsPrefix = React.useId().replace(/:/g, '');
  const mmfNorthMarkerId = React.useId().replace(/:/g, '');
  const mmfSouthMarkerId = React.useId().replace(/:/g, '');
  const fieldIntensityBlurId = React.useId().replace(/:/g, '');
  const fieldIntensityColors = smoothFieldIntensity
    ? SMOOTH_FIELD_INTENSITY_COLORS
    : FIELD_INTENSITY_COLORS;

  const canShowFieldLines = hasFieldLines(meshData)
    && meshData.contour_levels.some((level) => level.segments_mm.length > 0);
  const fieldStrengthRange = useMemo(() => {
    if (!hasFieldLines(meshData)) return null;
    const values = meshData.contour_levels
      .flatMap((level) => level.segment_b_mag_t ?? [])
      .filter((value) => Number.isFinite(value) && value > 0)
      .sort((a, b) => a - b);
    if (values.length === 0) return null;
    const q = (fraction: number) => {
      const index = (values.length - 1) * fraction;
      const lower = Math.floor(index);
      const upper = Math.ceil(index);
      if (lower === upper) return values[lower];
      const t = index - lower;
      return values[lower] * (1 - t) + values[upper] * t;
    };
    return { low: q(0.08), high: q(0.94) };
  }, [meshData]);
  const stitchedFieldLinePaths = useMemo(() => {
    if (!hasFieldLines(meshData)) return [];
    const maxRadiusMm = meshData.contour_levels.reduce((maxRadius, contour) => {
      for (const [x1, y1, x2, y2] of contour.segments_mm) {
        maxRadius = Math.max(
          maxRadius,
          Math.hypot(x1, y1),
          Math.hypot(x2, y2),
        );
      }
      return maxRadius;
    }, 0);
    const suppressClosedLoopsInsideRadiusMm = maxRadiusMm
      * FIELD_LINE_CORE_LOOP_SUPPRESS_RADIUS_RATIO;

    return meshData.contour_levels.flatMap((contour, contourIndex) => {
      const segments: FieldLinePathSegment[] = contour.segments_mm.map(
        ([x1, y1, x2, y2], segmentIndex) => ({
          x1,
          y1,
          x2,
          y2,
          bMagT: contour.segment_b_mag_t?.[segmentIndex],
        }),
      );
      const d = buildDominantFieldLinePath(segments, {
        coreLoopKeepPerLevel: FIELD_LINE_CORE_LOOP_KEEP_PER_LEVEL,
        suppressClosedLoopsInsideRadiusMm,
      });
      if (!d) return [];

      const strengths = segments
        .map(({ bMagT }) => bMagT)
        .filter((value): value is number => (
          typeof value === 'number' && Number.isFinite(value) && value > 0
        ))
        .sort((a, b) => a - b);
      const representativeStrength = strengths.length
        ? strengths[Math.floor((strengths.length - 1) * 0.82)]
        : undefined;
      return [{
        d,
        key: `${contour.level}-${contourIndex}`,
        style: fieldStrengthStyle(representativeStrength, fieldStrengthRange),
      }];
    });
  }, [fieldStrengthRange, meshData]);
  const fieldDirectionArrows = useMemo((): FieldDirectionArrow[] => {
    if (!hasFieldLines(meshData)) return [];
    const solvedSegments = meshData.contour_levels.flatMap((contour, contourIndex) => (
      contour.segments_mm.map((segment, segmentIndex) => ({
        bxT: contour.segment_bx_t?.[segmentIndex],
        byT: contour.segment_by_t?.[segmentIndex],
        key: `${contourIndex}-${segmentIndex}`,
        segment,
      }))
    ));
    if (solvedSegments.length === 0) return [];

    const stride = Math.max(
      18,
      Math.ceil(solvedSegments.length / FIELD_LINE_DIRECTION_ARROW_TARGET),
    );
    const arrows: FieldDirectionArrow[] = [];
    solvedSegments.forEach(({ bxT, byT, key, segment }, index) => {
      if (index % stride !== 0 || !Number.isFinite(bxT) || !Number.isFinite(byT)) return;
      const vectorLength = Math.hypot(bxT ?? 0, byT ?? 0);
      if (vectorLength <= 1e-9) return;
      const [x1, y1, x2, y2] = segment;
      arrows.push({
        angleDeg: (Math.atan2(solverYSign * (byT ?? 0), bxT ?? 0) * 180) / Math.PI,
        key,
        opacity: 0.94,
        x: (x1 + x2) / 2,
        y: solverYSign * (y1 + y2) / 2,
      });
    });
    return arrows;
  }, [meshData, solverYSign]);

  const viewerTitle = title ?? (canShowFieldLines ? 'Mesh + Field Lines' : 'Mesh Preview');
  const viewerSubtitle = subtitle === null
    ? null
    : subtitle ?? [
      `${meshData.config_summary.topology} ${meshData.config_summary.poles}p/${meshData.config_summary.slots}s`,
      `${meshData.mesh_info.num_nodes.toLocaleString()} nodes`,
      `${meshData.mesh_info.num_triangles.toLocaleString()} elements`,
      'generation_time_ms' in meshData ? `${meshData.generation_time_ms}ms` : 'solved field plot',
    ].join(' · ');

  const xs = meshData.nodes_mm.map((n) => n[0]);
  const ys = meshData.nodes_mm.map((n) => n[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const rangeX = maxX - minX;
  const rangeY = maxY - minY;
  const pad = Math.max(rangeX, rangeY) * 0.05;

  useEffect(() => {
    if (!preserveViewportOnMeshChange) {
      // A newly loaded fixture should start fitted. Animated hosts can opt out
      // so swapping solved frames does not disturb the user's camera.
      setTransform((current) => (panEnabled ? { ...current, scale: 1 } : { x: 0, y: 0, scale: 1 }));
    }
    setShowFieldLines(hasFieldLines(meshData));
    setIsAnimating(false);
    setAnimationSpeed(1);
    setAnimatedRotorAngleDeg(0);
    activeRegionDragRef.current = null;
    setActiveRegionDrag(null);
  }, [meshData, panEnabled, preserveViewportOnMeshChange]);

  useEffect(() => {
    if (panResetToken === undefined) return;
    setTransform({ x: 0, y: 0, scale: 1 });
  }, [panResetToken]);

  useEffect(() => {
    if (!showRotorAnimationControls || !isAnimating) {
      if (animationFrameRef.current !== null) {
        window.cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      lastFrameTimeRef.current = null;
      return undefined;
    }

    const animate = (timestamp: number) => {
      if (lastFrameTimeRef.current === null) {
        lastFrameTimeRef.current = timestamp;
      }

      const deltaMs = timestamp - lastFrameTimeRef.current;
      lastFrameTimeRef.current = timestamp;
      const degreesPerMs = 0.06 * animationSpeed;

      setAnimatedRotorAngleDeg((current) => (current + deltaMs * degreesPerMs) % 360);
      animationFrameRef.current = window.requestAnimationFrame(animate);
    };

    animationFrameRef.current = window.requestAnimationFrame(animate);

    return () => {
      if (animationFrameRef.current !== null) {
        window.cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      lastFrameTimeRef.current = null;
    };
  }, [animationSpeed, isAnimating, showRotorAnimationControls]);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (fixedView) return;
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    setTransform((current) => ({
      ...current,
      scale: Math.max(minScale, Math.min(20, current.scale * factor)),
    }));
  }, [fixedView, minScale]);

  const clientToSvgPoint = useCallback((clientX: number, clientY: number) => {
    const svg = svgRef.current;
    const matrix = svg?.getScreenCTM();
    if (!svg || !matrix) return null;
    const point = svg.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const transformed = point.matrixTransform(matrix.inverse());
    return { x: transformed.x, y: transformed.y };
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (viewportPanEnabled && (!fixedView || panEnabled) && e.button === 0) {
      setIsPanning(true);
      setPanStart({ x: e.clientX - transform.x, y: e.clientY - transform.y });
    }
  }, [fixedView, panEnabled, transform, viewportPanEnabled]);

  const handleRegionMouseDown = useCallback((event: React.MouseEvent, dragKey: string) => {
    if (event.button !== 0 || !onDraggableRegionDrop) return;
    const point = clientToSvgPoint(event.clientX, event.clientY);
    if (!point) return;
    event.preventDefault();
    event.stopPropagation();
    setIsPanning(false);
    const nextDrag = {
      dragKey,
      startSvgX: point.x,
      startSvgY: point.y,
      deltaXMm: 0,
      deltaYMm: 0,
    };
    activeRegionDragRef.current = nextDrag;
    setActiveRegionDrag(nextDrag);
  }, [clientToSvgPoint, onDraggableRegionDrop]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const currentRegionDrag = activeRegionDragRef.current;
    if (currentRegionDrag) {
      const point = clientToSvgPoint(e.clientX, e.clientY);
      if (!point) return;
      const nextDrag = {
        ...currentRegionDrag,
        deltaXMm: (point.x - currentRegionDrag.startSvgX) / effectiveScale,
        deltaYMm: (point.y - currentRegionDrag.startSvgY) / (effectiveScale * solverYSign),
      };
      activeRegionDragRef.current = nextDrag;
      setActiveRegionDrag(nextDrag);
      return;
    }
    if (isPanning) {
      setTransform((current) => ({
        ...current,
        x: e.clientX - panStart.x,
        y: e.clientY - panStart.y,
      }));
    }
  }, [clientToSvgPoint, effectiveScale, isPanning, panStart, solverYSign]);

  const handleMouseUp = useCallback(() => {
    const currentRegionDrag = activeRegionDragRef.current;
    if (currentRegionDrag && onDraggableRegionDrop) {
      activeRegionDragRef.current = null;
      onDraggableRegionDrop(
        currentRegionDrag.dragKey,
        currentRegionDrag.deltaXMm,
        currentRegionDrag.deltaYMm,
      );
      setActiveRegionDrag(null);
    }
    setIsPanning(false);
  }, [onDraggableRegionDrop]);

  const fitToView = useCallback(() => {
    setTransform({ x: 0, y: 0, scale: 1 });
  }, []);

  const zoomIn = useCallback(() => {
    setTransform((current) => ({ ...current, scale: current.scale * 1.3 }));
  }, []);

  const zoomOut = useCallback(() => {
    setTransform((current) => ({ ...current, scale: Math.max(minScale, current.scale / 1.3) }));
  }, [minScale]);

  const regionGroups: Record<string, string[]> = {};
  const triangleRegions: string[] = new Array(meshData.triangles.length);
  const forceMagnetBounds = useMemo(() => {
    const bounds: Record<string, { minX: number; maxX: number; minY: number; maxY: number }> = {};
    meshData.triangles.forEach((triangle, index) => {
      const region = meshData.regions[index];
      if (region !== 'force_magnet_n' && region !== 'force_magnet_s') return;
      const xs = triangle.map((nodeIndex) => meshData.nodes_mm[nodeIndex][0]);
      const ys = triangle.map((nodeIndex) => meshData.nodes_mm[nodeIndex][1]);
      const current = bounds[region] ?? {
        minX: Number.POSITIVE_INFINITY,
        maxX: Number.NEGATIVE_INFINITY,
        minY: Number.POSITIVE_INFINITY,
        maxY: Number.NEGATIVE_INFINITY,
      };
      bounds[region] = {
        minX: Math.min(current.minX, ...xs),
        maxX: Math.max(current.maxX, ...xs),
        minY: Math.min(current.minY, ...ys),
        maxY: Math.max(current.maxY, ...ys),
      };
    });
    return bounds;
  }, [meshData.nodes_mm, meshData.regions, meshData.triangles]);
  const forceMagnetGradientId = (region: string) => `${forcePolarityGradientPrefix}-${region}`;
  const magnetArcAssignments = useMemo(() => {
    if (!showMagnetizationLabels || neutralMagnets) return null;
    const fieldData = hasFieldLines(meshData) ? meshData : null;
    return classifyMagnetArcs(
      meshData.nodes_mm,
      meshData.triangles,
      meshData.regions,
      meshData.config_summary.poles,
      fieldData?.element_bx_t,
      fieldData?.element_by_t,
      magnetPolarityHintDeg,
    );
  }, [meshData, showMagnetizationLabels, neutralMagnets, magnetPolarityHintDeg]);
  // Solved teaching view: fit the pole-pair harmonic of the active air-gap Br
  // profile so the stator N/S cues sit on the displayed field poles.
  // The profile shares the baked frame coordinates with the contour lines, so
  // the cues land where the rendered field really is.
  const fieldStatorCues = useMemo(() => {
    if (!statorPoleLabelsFromField || !showMagnetizationLabels) return [];
    if (!hasFieldLines(meshData) || !meshData.airgap_brbt) return [];
    return deriveMagneticPolarityCues(
      meshData.airgap_brbt,
      meshData.config_summary.poles,
      'stator',
    );
  }, [meshData, showMagnetizationLabels, statorPoleLabelsFromField]);
  for (let index = 0; index < meshData.triangles.length; index += 1) {
    const [a, b, c] = meshData.triangles[index];
    const sourceRegion = meshData.regions[index];
    let region = sourceRegion;
    if (sourceRegion === 'magnet' && showMagnetizationLabels && !neutralMagnets) {
      region = magnetArcAssignments?.get(index) ?? alternatingMagnetRegion(
        meshData.nodes_mm,
        meshData.triangles[index],
        meshData.config_summary.poles,
      );
    } else if (sourceRegion === 'slot_winding' && splitConcentratedSlotWindings) {
      const centroidX = (meshData.nodes_mm[a][0] + meshData.nodes_mm[b][0] + meshData.nodes_mm[c][0]) / 3;
      const centroidY = (meshData.nodes_mm[a][1] + meshData.nodes_mm[b][1] + meshData.nodes_mm[c][1]) / 3;
      const slotCount = Math.max(3, Math.round(meshData.config_summary.slots));
      const slotPitchDeg = 360 / slotCount;
      const angleDeg = ((Math.atan2(centroidY, centroidX) * 180) / Math.PI + 360) % 360;
      const slotIndex = Math.round(angleDeg / slotPitchDeg) % slotCount;
      const slotCenterDeg = slotIndex * slotPitchDeg;
      const signedOffsetDeg = ((angleDeg - slotCenterDeg + 540) % 360) - 180;
      const toothIndex = signedOffsetDeg < 0
        ? (slotIndex + slotCount - 1) % slotCount
        : slotIndex;
      const phase = (['a', 'c', 'b'] as const)[toothIndex % 3];
      region = `slot_winding_${phase}`;
    } else if (sourceRegion === 'slot_winding' && colorCodeWindings) {
      const centroidX = (meshData.nodes_mm[a][0] + meshData.nodes_mm[b][0] + meshData.nodes_mm[c][0]) / 3;
      const centroidY = (meshData.nodes_mm[a][1] + meshData.nodes_mm[b][1] + meshData.nodes_mm[c][1]) / 3;
      const slotCount = Math.max(3, Math.round(meshData.config_summary.slots));
      const slotPitchDeg = 360 / slotCount;
      const angleDeg = ((Math.atan2(centroidY, centroidX) * 180) / Math.PI + 360) % 360;
      const slotIndex = Math.round(angleDeg / slotPitchDeg) % slotCount;
      const phase = (['a', 'c', 'b'] as const)[slotIndex % 3];
      region = `slot_winding_${phase}`;
    }
    if (!regionGroups[region]) regionGroups[region] = [];
    triangleRegions[index] = region;

    const na = meshData.nodes_mm[a];
    const nb = meshData.nodes_mm[b];
    const nc = meshData.nodes_mm[c];
    regionGroups[region].push(`M${na[0]},${solverYSign * na[1]}L${nb[0]},${solverYSign * nb[1]}L${nc[0]},${solverYSign * nc[1]}Z`);
  }

  const uniqueRegions = Object.keys(regionGroups);
  const rotorRegions = uniqueRegions.filter((region) => ROTOR_REGIONS.has(region));
  const stationaryRegions = uniqueRegions.filter((region) => !ROTOR_REGIONS.has(region));
  // |B| intensity layer: quantile-scaled heat buckets merged into one path per
  // level, split rotor/stationary so each follows the same transform as the
  // region fills underneath it.
  let fieldIntensity: {
    high: number;
    low: number;
    rotorBuckets: string[][];
    stationaryBuckets: string[][];
  } | null = null;
  if (showFieldIntensity && hasFieldLines(meshData)) {
    const bValues = meshData.element_b_mag_t;
    if (bValues && bValues.length === meshData.triangles.length) {
      const sorted = bValues.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
      if (sorted.length > 0) {
        const quantile = (fraction: number) => {
          const index = (sorted.length - 1) * fraction;
          const lower = Math.floor(index);
          const upper = Math.ceil(index);
          if (lower === upper) return sorted[lower];
          return sorted[lower] * (upper - index) + sorted[upper] * (index - lower);
        };
        const hasFixedRange = fieldIntensityRange
          && Number.isFinite(fieldIntensityRange.low)
          && Number.isFinite(fieldIntensityRange.high)
          && fieldIntensityRange.high > fieldIntensityRange.low;
        const low = hasFixedRange ? fieldIntensityRange.low : quantile(0.04);
        const high = hasFixedRange ? fieldIntensityRange.high : quantile(0.96);
        const span = high - low > 1e-9 ? high - low : 1;
        const bucketCount = fieldIntensityColors.length;
        const rotorBuckets: string[][] = Array.from({ length: bucketCount }, () => []);
        const stationaryBuckets: string[][] = Array.from({ length: bucketCount }, () => []);
        for (let index = 0; index < meshData.triangles.length; index += 1) {
          const region = triangleRegions[index];
          // Keep the A/B/C phase fills readable: windings carry negligible |B|
          // anyway, so the heat layer skips them instead of washing them out.
          if (region.startsWith('slot_winding')) continue;
          const bMag = bValues[index];
          if (!Number.isFinite(bMag)) continue;
          const t = Math.max(0, Math.min(1, (bMag - low) / span));
          const bucket = Math.min(bucketCount - 1, Math.floor(t * bucketCount));
          const [a, bIdx, c] = meshData.triangles[index];
          const na = meshData.nodes_mm[a];
          const nb = meshData.nodes_mm[bIdx];
          const nc = meshData.nodes_mm[c];
          (ROTOR_REGIONS.has(region) ? rotorBuckets : stationaryBuckets)[bucket].push(
            `M${na[0]},${solverYSign * na[1]}L${nb[0]},${solverYSign * nb[1]}L${nc[0]},${solverYSign * nc[1]}Z`,
          );
        }
        fieldIntensity = { high, low, rotorBuckets, stationaryBuckets };
      }
    }
  }
  const fieldIntensityLegendScale = fieldIntensity && fieldIntensity.high < 0.01
    ? { multiplier: 1_000, unit: 'mT' }
    : { multiplier: 1, unit: 'T' };
  const shouldRenderShaftOverlay = Boolean(shaftRadiusMm && shaftRadiusMm > 0 && !uniqueRegions.includes('shaft'));
  const vbX = minX - pad;
  const vbY = useSolverScreenCoordinates ? minY - pad : -(maxY + pad);
  const vbW = rangeX + 2 * pad;
  const vbH = rangeY + 2 * pad;
  const viewWidthPx = 1200;
  const pxPerMm = viewWidthPx / vbW;
  const scaleBarMm = SCALE_BAR_STEPS_MM.find((value) => value * pxPerMm >= SCALE_BAR_TARGET_PX)
    ?? SCALE_BAR_STEPS_MM[SCALE_BAR_STEPS_MM.length - 1];
  const scaleBarWidth = scaleBarMm / pxPerMm;

  const statorOuterRadiusMm = meshData.config_summary.stator_od_mm / 2;
  const statorInnerRadiusMm = meshData.config_summary.rotor_od_mm / 2 + meshData.config_summary.magnet_thickness_mm;
  const rotorOuterRadiusMm = meshData.config_summary.rotor_od_mm / 2;
  const magnetThicknessMm = meshData.config_summary.magnet_thickness_mm;
  const airgapMm = Math.max(0, statorInnerRadiusMm - rotorOuterRadiusMm);
  const annotationStroke = 0.08 / effectiveScale;
  const labelFontSize = 1.6 / effectiveScale;
  const annotationBoxPadding = 0.6 / effectiveScale;
  const magneticLabelFontSize = 2 / effectiveScale;
  const magneticLabelPaddingX = 1.1 / effectiveScale;
  const magneticLabelPaddingY = 0.7 / effectiveScale;

  const radialDimensions = [
    {
      key: 'stator-od',
      label: `Stator OD ${meshData.config_summary.stator_od_mm.toFixed(1)} mm`,
      x: statorOuterRadiusMm + 6,
      inner: 0,
      outer: statorOuterRadiusMm,
      textY: -(statorOuterRadiusMm / 2),
    },
    {
      key: 'stator-id',
      label: `Stator ID ${(statorInnerRadiusMm * 2).toFixed(1)} mm`,
      x: statorInnerRadiusMm - 10,
      inner: 0,
      outer: statorInnerRadiusMm,
      textY: -(statorInnerRadiusMm / 2),
    },
    {
      key: 'rotor-od',
      label: `Rotor OD ${meshData.config_summary.rotor_od_mm.toFixed(1)} mm`,
      x: -(rotorOuterRadiusMm + 8),
      inner: 0,
      outer: rotorOuterRadiusMm,
      textY: -(rotorOuterRadiusMm / 2),
    },
    {
      key: 'magnet-thickness',
      label: `Magnet ${magnetThicknessMm.toFixed(1)} mm`,
      x: rotorOuterRadiusMm + magnetThicknessMm / 2,
      inner: rotorOuterRadiusMm,
      outer: rotorOuterRadiusMm + magnetThicknessMm,
      textY: -(rotorOuterRadiusMm + magnetThicknessMm / 2),
    },
    {
      key: 'airgap',
      label: `Airgap ${airgapMm.toFixed(1)} mm`,
      x: statorInnerRadiusMm - airgapMm / 2,
      inner: rotorOuterRadiusMm + magnetThicknessMm,
      outer: statorInnerRadiusMm,
      textY: -(rotorOuterRadiusMm + magnetThicknessMm + airgapMm / 2),
    },
  ];

  const fullMotorOutline = statorOuterRadiusMm * 2 > vbW * 0.92;
  const showEmbeddedHeader = !(embedded && compactEmbedded);
  const resetAnimation = useCallback(() => {
    setIsAnimating(false);
    setAnimatedRotorAngleDeg(0);
  }, []);

  const labelPoint = (angleDeg: number, radiusMm: number) => {
    const radians = (angleDeg * Math.PI) / 180;
    return {
      x: Math.cos(radians) * radiusMm,
      y: solverYSign * Math.sin(radians) * radiusMm,
    };
  };
  const annularBandPath = (startDeg: number, endDeg: number, innerRadiusMm: number, outerRadiusMm: number) => {
    const steps = 18;
    const outerPoints = Array.from({ length: steps + 1 }, (_, index) => {
      const angle = startDeg + ((endDeg - startDeg) * index) / steps;
      return labelPoint(angle, outerRadiusMm);
    });
    const innerPoints = Array.from({ length: steps + 1 }, (_, index) => {
      const angle = endDeg - ((endDeg - startDeg) * index) / steps;
      return labelPoint(angle, innerRadiusMm);
    });
    return [...outerPoints, ...innerPoints].map((point, index) => (
      `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`
    )).join(' ') + ' Z';
  };
  const rotateSvgPoint = (point: { x: number; y: number }, angleDeg: number) => {
    const radians = (angleDeg * Math.PI) / 180;
    const cos = Math.cos(radians);
    const sin = Math.sin(radians);
    return {
      x: point.x * cos - point.y * sin,
      y: point.x * sin + point.y * cos,
    };
  };
  const getRegionSvgCentroid = (regionName: string) => {
    let areaTotal = 0;
    let weightedX = 0;
    let weightedY = 0;

    for (let index = 0; index < meshData.triangles.length; index += 1) {
      if (triangleRegions[index] !== regionName) continue;
      const [a, b, c] = meshData.triangles[index];
      const p0 = { x: meshData.nodes_mm[a][0], y: solverYSign * meshData.nodes_mm[a][1] };
      const p1 = { x: meshData.nodes_mm[b][0], y: solverYSign * meshData.nodes_mm[b][1] };
      const p2 = { x: meshData.nodes_mm[c][0], y: solverYSign * meshData.nodes_mm[c][1] };
      const area = Math.abs(
        (p0.x * (p1.y - p2.y)
          + p1.x * (p2.y - p0.y)
          + p2.x * (p0.y - p1.y)) / 2,
      );
      if (area <= 1e-9) continue;

      areaTotal += area;
      weightedX += ((p0.x + p1.x + p2.x) / 3) * area;
      weightedY += ((p0.y + p1.y + p2.y) / 3) * area;
    }

    if (areaTotal <= 0) return null;
    return {
      x: weightedX / areaTotal,
      y: weightedY / areaTotal,
    };
  };
  const getNearestRegionSvgPoint = (
    regionName: string,
    target: { x: number; y: number },
    options?: { minRadiusMm?: number; maxRadiusMm?: number },
  ) => {
    let nearest: { x: number; y: number } | null = null;
    let nearestDistanceSq = Number.POSITIVE_INFINITY;

    for (let index = 0; index < meshData.triangles.length; index += 1) {
      if (meshData.regions[index] !== regionName) continue;
      const [a, b, c] = meshData.triangles[index];
      const centroid = {
        x: (meshData.nodes_mm[a][0] + meshData.nodes_mm[b][0] + meshData.nodes_mm[c][0]) / 3,
        y: solverYSign * (
          meshData.nodes_mm[a][1] + meshData.nodes_mm[b][1] + meshData.nodes_mm[c][1]
        ) / 3,
      };
      const radius = Math.hypot(centroid.x, centroid.y);
      if (options?.minRadiusMm !== undefined && radius < options.minRadiusMm) continue;
      if (options?.maxRadiusMm !== undefined && radius > options.maxRadiusMm) continue;
      const dx = centroid.x - target.x;
      const dy = centroid.y - target.y;
      const distanceSq = dx * dx + dy * dy;
      if (distanceSq < nearestDistanceSq) {
        nearest = centroid;
        nearestDistanceSq = distanceSq;
      }
    }

    return nearest;
  };
  const getRegionSectorSvgCentroid = (
    regionName: string,
    centerAngleDeg: number,
    sectorSpanDeg: number,
  ) => {
    let areaTotal = 0;
    let weightedX = 0;
    let weightedY = 0;

    for (let index = 0; index < meshData.triangles.length; index += 1) {
      if (meshData.regions[index] !== regionName) continue;
      const [a, b, c] = meshData.triangles[index];
      const centroidX = (
        meshData.nodes_mm[a][0]
        + meshData.nodes_mm[b][0]
        + meshData.nodes_mm[c][0]
      ) / 3;
      const centroidY = (
        meshData.nodes_mm[a][1]
        + meshData.nodes_mm[b][1]
        + meshData.nodes_mm[c][1]
      ) / 3;
      const triangleAngleDeg = ((Math.atan2(centroidY, centroidX) * 180) / Math.PI + 360) % 360;
      const angleDeltaDeg = ((triangleAngleDeg - centerAngleDeg + 540) % 360) - 180;
      if (Math.abs(angleDeltaDeg) > sectorSpanDeg / 2) continue;

      const p0 = { x: meshData.nodes_mm[a][0], y: solverYSign * meshData.nodes_mm[a][1] };
      const p1 = { x: meshData.nodes_mm[b][0], y: solverYSign * meshData.nodes_mm[b][1] };
      const p2 = { x: meshData.nodes_mm[c][0], y: solverYSign * meshData.nodes_mm[c][1] };
      const area = Math.abs(
        (p0.x * (p1.y - p2.y)
          + p1.x * (p2.y - p0.y)
          + p2.x * (p0.y - p1.y)) / 2,
      );
      if (area <= 1e-9) continue;

      areaTotal += area;
      weightedX += centroidX * area;
      weightedY += solverYSign * centroidY * area;
    }

    if (areaTotal <= 0) return null;
    return {
      x: weightedX / areaTotal,
      y: weightedY / areaTotal,
    };
  };
  const statorNeutralLabelRadiusMm = Math.min(
    statorOuterRadiusMm - 7,
    Math.max(rotorOuterRadiusMm + magnetThicknessMm + 9, statorOuterRadiusMm * 0.72),
  );
  const statorToothRadialDepthMm = Math.max(0, statorOuterRadiusMm - statorInnerRadiusMm);
  const statorPoleLabelRadiusMm = Math.min(
    statorOuterRadiusMm - 10,
    statorInnerRadiusMm + Math.max(4, statorToothRadialDepthMm * 0.52),
  );
  const statorPoleLabelSearchBand = {
    minRadiusMm: statorInnerRadiusMm + statorToothRadialDepthMm * 0.28,
    maxRadiusMm: statorOuterRadiusMm - statorToothRadialDepthMm * 0.12,
  };
  const statorNorthTarget = labelPoint(statorFieldAngleDeg, statorPoleLabelRadiusMm);
  const statorSouthTarget = labelPoint(statorFieldAngleDeg + 180, statorPoleLabelRadiusMm);
  const statorNorthLabel = getNearestRegionSvgPoint('stator_tooth', statorNorthTarget, statorPoleLabelSearchBand)
    ?? getNearestRegionSvgPoint('stator_tooth', statorNorthTarget)
    ?? statorNorthTarget;
  const statorSouthLabel = getNearestRegionSvgPoint('stator_tooth', statorSouthTarget, statorPoleLabelSearchBand)
    ?? getNearestRegionSvgPoint('stator_tooth', statorSouthTarget)
    ?? statorSouthTarget;
  const rotorLabelRadiusMm = rotorOuterRadiusMm + magnetThicknessMm * 0.55;
  const rotorPmNBaseLabel = getRegionSvgCentroid('magnet_n') ?? { x: rotorLabelRadiusMm, y: 0 };
  const rotorPmSBaseLabel = getRegionSvgCentroid('magnet_s') ?? { x: -rotorLabelRadiusMm, y: 0 };
  const rotorPmNLabel = rotateSvgPoint(rotorPmNBaseLabel, effectiveRotorAngleDeg);
  const rotorPmSLabel = rotateSvgPoint(rotorPmSBaseLabel, effectiveRotorAngleDeg);
  const torqueDirectionSign = torqueDirection === 'ccw' ? 1 : torqueDirection === 'cw' ? -1 : 0;
  const forceArrowRadiusMm = rotorOuterRadiusMm + magnetThicknessMm + Math.max(2, airgapMm * 0.72);
  const forceArrowLengthMm = Math.max(9.5, statorOuterRadiusMm * 0.11);
  const forceArrowAngles = [45, 135, 225, 315];
  const mmfBandInnerRadiusMm = statorInnerRadiusMm + Math.max(0.8, statorToothRadialDepthMm * 0.08);
  const mmfBandOuterRadiusMm = Math.min(
    statorOuterRadiusMm - 1.4,
    statorInnerRadiusMm + Math.max(4.2, statorToothRadialDepthMm * 0.32),
  );
  const mmfBandSpanDeg = 42;
  const slotCurrentCueRadiusMm = Math.min(
    statorOuterRadiusMm - 9,
    statorInnerRadiusMm + Math.max(7.5, statorToothRadialDepthMm * 0.4),
  );
  // Slot IDs belong in the stator-yoke ring, outside the colored winding.
  // Leave enough room for the horizontal pill at the left/right positions.
  const slotIdentityRadiusMm = Math.max(
    statorInnerRadiusMm + 5,
    statorOuterRadiusMm - 4.5,
  );
  const mmfSampleInnerRadiusMm = Math.max(
    rotorOuterRadiusMm + magnetThicknessMm + airgapMm * 0.08,
    statorInnerRadiusMm - Math.max(1.2, airgapMm * 0.52),
  );
  const mmfSampleOuterRadiusMm = statorInnerRadiusMm
    + Math.max(2.4, statorToothRadialDepthMm * 0.13);
  const mmfArrowInnerRadiusMm = Math.max(
    rotorOuterRadiusMm + magnetThicknessMm * 0.45,
    statorInnerRadiusMm - Math.max(2.4, magnetThicknessMm * 0.48),
  );
  const mmfArrowOuterRadiusMm = Math.min(
    statorOuterRadiusMm - 2.5,
    statorInnerRadiusMm + Math.max(7.5, statorToothRadialDepthMm * 0.5),
  );
  const referenceAxisRadiusMm = statorOuterRadiusMm + 3;
  const currentAxisStart = labelPoint(statorFieldAngleDeg, referenceAxisRadiusMm);
  const currentAxisEnd = labelPoint(statorFieldAngleDeg + 180, referenceAxisRadiusMm);
  const neutralAxisStart = labelPoint(statorFieldAngleDeg + 90, referenceAxisRadiusMm);
  const neutralAxisEnd = labelPoint(statorFieldAngleDeg + 270, referenceAxisRadiusMm);
  // When the solved air-gap Br profile is enabled, pin the stator pole chips
  // to the fitted field poles and the neutral chips to the zero crossings
  // halfway between them. Otherwise fall back to the analytic current axis.
  const magneticLabels = fieldStatorCues.length > 0
    ? [
      ...fieldStatorCues.map((cue) => {
        const target = labelPoint(cue.angleDeg, statorPoleLabelRadiusMm);
        const point = getNearestRegionSvgPoint('stator_tooth', target, statorPoleLabelSearchBand)
          ?? getNearestRegionSvgPoint('stator_tooth', target)
          ?? target;
        return {
          label: `Stator ${cue.label}`,
          kind: cue.label === 'N' ? 'stator-n' : 'stator-s',
          ...point,
        };
      }),
      ...fieldStatorCues.map((cue) => ({
        label: 'Neutral',
        kind: 'neutral',
        ...labelPoint(cue.angleDeg + 180 / fieldStatorCues.length, statorNeutralLabelRadiusMm),
      })),
    ]
    : [
      { label: 'Stator N', kind: 'stator-n', ...statorNorthLabel },
      { label: 'Stator S', kind: 'stator-s', ...statorSouthLabel },
      { label: 'Neutral', kind: 'neutral', ...labelPoint(statorFieldAngleDeg + 90, statorNeutralLabelRadiusMm) },
      { label: 'Neutral', kind: 'neutral', ...labelPoint(statorFieldAngleDeg + 270, statorNeutralLabelRadiusMm) },
    ];

  const renderForceArrow = (angleDeg: number, index: number) => {
    const center = labelPoint(angleDeg, forceArrowRadiusMm);
    const tangent = labelPoint(angleDeg + (torqueDirectionSign > 0 ? 90 : -90), forceArrowLengthMm / 2);
    return (
      <line
        key={`force-${index}`}
        x1={center.x - tangent.x}
        y1={center.y - tangent.y}
        x2={center.x + tangent.x}
        y2={center.y + tangent.y}
        markerEnd={`url(#${forceMarkerId})`}
      />
    );
  };

  const renderMmfSourceArrow = (kind: 'north' | 'south', angleDeg: number) => {
    const inner = labelPoint(angleDeg, mmfArrowInnerRadiusMm);
    const outer = labelPoint(angleDeg, mmfArrowOuterRadiusMm);
    const start = kind === 'north' ? outer : inner;
    const end = kind === 'north' ? inner : outer;
    return (
      <line
        key={`mmf-${kind}`}
        className={`mesh-mmf-source-arrow is-${kind}`}
        x1={start.x}
        y1={start.y}
        x2={end.x}
        y2={end.y}
        markerEnd={`url(#${kind === 'north' ? mmfNorthMarkerId : mmfSouthMarkerId})`}
      />
    );
  };

  const renderMagneticLabel = (
    key: string,
    label: string,
    x: number,
    y: number,
    kind: string,
  ) => {
    const fontSize = kind === 'neutral' ? magneticLabelFontSize : magneticLabelFontSize * 2;
    const paddingX = kind === 'neutral' ? magneticLabelPaddingX : magneticLabelPaddingX * 1.25;
    const paddingY = kind === 'neutral' ? magneticLabelPaddingY : magneticLabelPaddingY * 1.25;
    const poleBadgeScale = kind === 'neutral' ? 1 : 0.5;
    const width = label.length * fontSize * 0.62 + paddingX * 2;
    const height = fontSize + paddingY * 2;
    return (
      <g
        key={key}
        className={`mesh-magnetization-label is-${kind}`}
        transform={poleBadgeScale === 1
          ? undefined
          : `translate(${x} ${y}) scale(${poleBadgeScale}) translate(${-x} ${-y})`}
      >
        <rect
          x={x - width / 2}
          y={y - height / 2}
          width={width}
          height={height}
          rx={0.9 / effectiveScale}
        />
        <text
          x={x}
          y={y + fontSize * 0.34}
          fontSize={fontSize}
          textAnchor="middle"
        >
          {label}
        </text>
      </g>
    );
  };

  const renderRegion = (region: string) => {
    const dragKey = draggableRegionGroups?.[region];
    const dragIsActive = Boolean(dragKey && activeRegionDrag?.dragKey === dragKey);
    const regionFill = splitForceMagnetPolarity && forceMagnetBounds[region]
      ? `url(#${forceMagnetGradientId(region)})`
      : REGION_COLORS[region] || '#e5e7eb';
    return (
    <path
      key={region}
      d={regionGroups[region].join('')}
      className={dragKey ? 'mesh-viewer-draggable-region' : undefined}
      transform={dragIsActive
        ? `translate(${activeRegionDrag?.deltaXMm ?? 0} ${solverYSign * (activeRegionDrag?.deltaYMm ?? 0)})`
        : undefined}
      fill={regionFill}
      stroke={selectedRegion === region ? '#f59e0b' : showMeshEdges ? '#1e293b' : 'none'}
      strokeWidth={selectedRegion === region
        ? 0.32 / effectiveScale
        : showMeshEdges
          ? 0.08 / effectiveScale
          : 0}
      opacity={hoveredRegion && hoveredRegion !== region ? 0.3 : canShowFieldLines && effectiveShowFieldLines ? 0.72 : 1}
      onMouseEnter={() => setHoveredRegion(region)}
      onMouseLeave={() => setHoveredRegion(null)}
      onMouseDown={dragKey ? (event) => handleRegionMouseDown(event, dragKey) : undefined}
      onClick={onRegionClick ? (event) => {
        event.stopPropagation();
        onRegionClick(region);
      } : undefined}
      role={onRegionClick || dragKey ? 'button' : undefined}
      aria-label={dragKey ? `Drag ${dragKey}` : undefined}
      tabIndex={onRegionClick ? 0 : undefined}
      onKeyDown={onRegionClick ? (event) => {
        if (event.key === 'Enter' || event.key === ' ') onRegionClick(region);
      } : undefined}
      style={dragKey ? { cursor: dragIsActive ? 'grabbing' : 'move' } : onRegionClick ? { cursor: 'pointer' } : undefined}
    />
    );
  };

  const content = (
    <div className={`mesh-viewer-container ${embedded ? 'mesh-viewer-container-embedded' : ''} ${compactEmbedded ? 'mesh-viewer-container-compact' : ''} ${allowOverflow ? 'mesh-viewer-container-overflow-visible' : ''} ${toolbarMode === 'zoom-only' ? 'mesh-viewer-container-toolbar-zoom-only' : ''}`}>
      {showEmbeddedHeader && (
        <div className="mesh-viewer-header">
          <div className="mesh-viewer-title">
            <h3>{viewerTitle}</h3>
            {viewerSubtitle ? <span className="mesh-viewer-subtitle">{viewerSubtitle}</span> : null}
          </div>
          {headerActions ? <div className="mesh-viewer-header-actions">{headerActions}</div> : null}
          {!embedded && onClose && (
            <button className="mesh-viewer-close" onClick={onClose} type="button" aria-label="Close mesh viewer">
              ×
            </button>
          )}
        </div>
      )}

      <div className="mesh-viewer-viewport">
        <svg
          ref={svgRef}
          className="mesh-viewer-svg"
          viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`}
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          style={{ cursor: !viewportPanEnabled || (fixedView && !panEnabled) ? 'default' : isPanning ? 'grabbing' : 'grab' }}
        >
          <defs>
            {smoothFieldIntensity ? (
              <filter id={fieldIntensityBlurId} x="-4%" y="-6%" width="108%" height="112%">
                <feGaussianBlur stdDeviation={0.22 / effectiveScale} />
              </filter>
            ) : null}
            {splitForceMagnetPolarity ? Object.entries(forceMagnetBounds).map(([region, bounds]) => {
              // Region paths render with solverYSign applied to Y, so the
              // gradient axis is expressed in that same flipped space. At
              // axisDeg = 0 this reduces to the original minX→maxX split.
              const centerX = (bounds.minX + bounds.maxX) / 2;
              const centerY = (bounds.minY + bounds.maxY) / 2;
              const halfSpanX = Math.max((bounds.maxX - bounds.minX) / 2, 1e-6);
              const axisRad = (forceMagnetPolarityAxisDeg * Math.PI) / 180;
              const axisX = Math.cos(axisRad);
              const axisY = solverYSign * Math.sin(axisRad);
              return (
                <linearGradient
                  key={region}
                  id={forceMagnetGradientId(region)}
                  gradientUnits="userSpaceOnUse"
                  x1={centerX - axisX * halfSpanX}
                  y1={solverYSign * centerY - axisY * halfSpanX}
                  x2={centerX + axisX * halfSpanX}
                  y2={solverYSign * centerY + axisY * halfSpanX}
                >
                  <stop offset="0%" stopColor="#2563eb" />
                  <stop offset="49.8%" stopColor="#2563eb" />
                  <stop offset="50.2%" stopColor="#ef4444" />
                  <stop offset="100%" stopColor="#ef4444" />
                </linearGradient>
              );
            }) : null}
            <marker
              id={forceMarkerId}
              markerWidth="8"
              markerHeight="8"
              refX="7"
              refY="4"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 8 4 L 0 8 Z" fill="#f59e0b" />
            </marker>
            {directionVectors.map((vector, index) => {
              const startColor = vector.colorStart ?? directionVectorToneColor(vector.tone);
              const endColor = vector.colorEnd ?? startColor;
              const gradientId = `${directionVectorDefsPrefix}-gradient-${index}`;
              const markerId = `${directionVectorDefsPrefix}-marker-${index}`;
              return (
                <React.Fragment key={`${gradientId}-${startColor}-${endColor}`}>
                  <linearGradient
                    id={gradientId}
                    gradientUnits="userSpaceOnUse"
                    x1={vector.x1Mm}
                    y1={solverYSign * vector.y1Mm}
                    x2={vector.x2Mm}
                    y2={solverYSign * vector.y2Mm}
                  >
                    <stop offset="0%" stopColor={startColor} />
                    <stop offset="100%" stopColor={endColor} />
                  </linearGradient>
                  <marker
                    id={markerId}
                    markerWidth="5"
                    markerHeight="5"
                    refX="4.5"
                    refY="2.5"
                    orient="auto"
                    markerUnits="strokeWidth"
                  >
                    <path d="M 0 0 L 5 2.5 L 0 5 Z" fill={endColor} />
                  </marker>
                </React.Fragment>
              );
            })}
            <marker
              id={mmfNorthMarkerId}
              markerWidth="8"
              markerHeight="8"
              refX="7"
              refY="4"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 8 4 L 0 8 Z" fill="#60a5fa" />
            </marker>
            <marker
              id={mmfSouthMarkerId}
              markerWidth="8"
              markerHeight="8"
              refX="7"
              refY="4"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 8 4 L 0 8 Z" fill="#f87171" />
            </marker>
          </defs>
          <g transform={`translate(${transform.x / effectiveScale}, ${transform.y / effectiveScale}) scale(${effectiveScale})`}>
            {meshData.n_pole_pitches < meshData.config_summary.poles && !fullMotorOutline && (
              <circle
                cx={0}
                cy={0}
                r={statorOuterRadiusMm}
                fill="none"
                stroke="rgba(148, 163, 184, 0.28)"
                strokeDasharray={`${2 / effectiveScale} ${2.5 / effectiveScale}`}
                strokeWidth={0.16 / effectiveScale}
              />
            )}

            {showMesh && stationaryRegions.map(renderRegion)}

            {fieldIntensity && (
              <g
                className="mesh-field-intensity"
                opacity={0.84}
                pointerEvents="none"
                filter={smoothFieldIntensity ? `url(#${fieldIntensityBlurId})` : undefined}
              >
                {fieldIntensity.stationaryBuckets.map((paths, bucket) => (
                  paths.length > 0 ? (
                    <path
                      key={`intensity-s-${bucket}`}
                      d={paths.join('')}
                      fill={fieldIntensityColors[bucket]}
                      stroke="none"
                    />
                  ) : null
                ))}
              </g>
            )}

            {showMeshEdges && fieldIntensity ? (
              <path
                d={stationaryRegions.flatMap((region) => regionGroups[region]).join('')}
                fill="none"
                stroke="rgba(2, 6, 23, 0.48)"
                strokeWidth={0.055 / effectiveScale}
                pointerEvents="none"
              />
            ) : null}

            {showMesh && (
              <g transform={`rotate(${effectiveRotorAngleDeg} 0 0)`}>
                {rotorRegions.map(renderRegion)}
                {fieldIntensity && (
                  <g
                    className="mesh-field-intensity"
                    opacity={0.84}
                    pointerEvents="none"
                    filter={smoothFieldIntensity ? `url(#${fieldIntensityBlurId})` : undefined}
                  >
                    {fieldIntensity.rotorBuckets.map((paths, bucket) => (
                      paths.length > 0 ? (
                        <path
                          key={`intensity-r-${bucket}`}
                          d={paths.join('')}
                          fill={fieldIntensityColors[bucket]}
                          stroke="none"
                        />
                      ) : null
                    ))}
                  </g>
                )}
                {showMeshEdges && fieldIntensity ? (
                  <path
                    d={rotorRegions.flatMap((region) => regionGroups[region]).join('')}
                    fill="none"
                    stroke="rgba(2, 6, 23, 0.48)"
                    strokeWidth={0.055 / effectiveScale}
                    pointerEvents="none"
                  />
                ) : null}
              </g>
            )}

            {showMagnetizationLabels && !showMesh && tutorialOverlayMode !== 'flux' ? (
              <g className="mesh-tutorial-reference">
                <circle cx={0} cy={0} r={statorOuterRadiusMm} className="is-stator-outer" />
                <circle cx={0} cy={0} r={statorInnerRadiusMm} className="is-stator-inner" />
                <circle cx={0} cy={0} r={rotorOuterRadiusMm + magnetThicknessMm} className="is-rotor-outer" />
                <circle cx={0} cy={0} r={rotorOuterRadiusMm} className="is-rotor-core" />
                {shaftRadiusMm ? <circle cx={0} cy={0} r={shaftRadiusMm} className="is-shaft" /> : null}
                <line
                  x1={currentAxisStart.x}
                  y1={currentAxisStart.y}
                  x2={currentAxisEnd.x}
                  y2={currentAxisEnd.y}
                  className="is-current-axis"
                />
                <line
                  x1={neutralAxisStart.x}
                  y1={neutralAxisStart.y}
                  x2={neutralAxisEnd.x}
                  y2={neutralAxisEnd.y}
                  className="is-neutral-axis"
                />
              </g>
            ) : null}

            {canShowFieldLines && effectiveShowFieldLines && hasFieldLines(meshData) && (
              <g className="mesh-field-lines" opacity={0.96}>
                <g transform={`scale(1 ${solverYSign})`}>
                  {stitchedFieldLinePaths.map(({ d, key, style }) => (
                    <path
                      key={`field-glow-${key}`}
                      d={d}
                      fill="none"
                      stroke="rgba(96, 165, 250, 0.14)"
                      strokeWidth={(0.28 * style.widthScale) / effectiveScale}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      opacity={0.5}
                    />
                  ))}
                  {stitchedFieldLinePaths.map(({ d, key, style }) => (
                    <path
                      key={`field-halo-${key}`}
                      d={d}
                      fill="none"
                      stroke="rgba(186, 230, 253, 0.22)"
                      strokeWidth={(0.155 * style.widthScale) / effectiveScale}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      opacity={0.62}
                    />
                  ))}
                  {stitchedFieldLinePaths.map(({ d, key, style }) => (
                    <path
                      key={`field-strength-${key}`}
                      d={d}
                      fill="none"
                      stroke={style.stroke}
                      strokeWidth={(0.094 * style.widthScale) / effectiveScale}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      opacity={style.opacity}
                      style={{ filter: 'drop-shadow(0 0 1.2px rgba(96, 165, 250, 0.24))' }}
                    />
                  ))}
                </g>
                {fieldDirectionArrows.map((arrow, arrowIndex) => {
                  const size = 1.65 / effectiveScale;
                  const wing = size * 0.42;
                  const notch = size * 0.16;
                  const point = size * 0.56;
                  const tail = -size * 0.5;
                  const arrowPath = [
                    `M ${point.toFixed(3)},0`,
                    `L ${tail.toFixed(3)},${(-wing).toFixed(3)}`,
                    `L ${(-notch).toFixed(3)},0`,
                    `L ${tail.toFixed(3)},${wing.toFixed(3)}`,
                    'Z',
                  ].join(' ');
                  return (
                    <g
                      key={`field-direction-${arrow.key}`}
                      transform={`translate(${arrow.x} ${arrow.y}) rotate(${arrow.angleDeg})`}
                    >
                      <path
                        d={arrowPath}
                        className={`mesh-field-direction-arrow${animateFieldArrows ? ' is-flowing' : ''}`}
                        opacity={arrow.opacity}
                        style={animateFieldArrows ? {
                          animationDelay: `${(arrowIndex % 8) * 0.22}s`,
                          ['--field-flow-distance' as string]: `${(size * 0.42).toFixed(3)}px`,
                        } : undefined}
                      />
                    </g>
                  );
                })}
              </g>
            )}

            {showMagnetizationLabels && tutorialOverlayMode === 'mmf' ? (
              <g className="mesh-mmf-overlay">
                {windingMmfSampleSector && !windingCurrentCuesMuted ? (
                  <path
                    className="mesh-mmf-sampled-sector"
                    d={annularBandPath(
                      windingMmfSampleSector.startAngleDeg,
                      windingMmfSampleSector.endAngleDeg,
                      mmfSampleInnerRadiusMm,
                      mmfSampleOuterRadiusMm,
                    )}
                  >
                    <title>
                      {`Selected ${windingMmfSampleSector.sampleAngleDeg.toFixed(0)} deg stator position: air-gap sector S${windingMmfSampleSector.startSlotIndex + 1} to S${windingMmfSampleSector.endSlotIndex + 1}, ${windingMmfSampleSector.ampereTurns >= 0 ? '+' : ''}${windingMmfSampleSector.ampereTurns.toFixed(1)} A-turn`}
                    </title>
                  </path>
                ) : null}
                {!windingCurrentCuesMuted ? (
                  <>
                    <path
                      className="mesh-mmf-band is-north"
                      d={annularBandPath(
                        statorFieldAngleDeg - mmfBandSpanDeg / 2,
                        statorFieldAngleDeg + mmfBandSpanDeg / 2,
                        mmfBandInnerRadiusMm,
                        mmfBandOuterRadiusMm,
                      )}
                    />
                    <path
                      className="mesh-mmf-band is-south"
                      d={annularBandPath(
                        statorFieldAngleDeg + 180 - mmfBandSpanDeg / 2,
                        statorFieldAngleDeg + 180 + mmfBandSpanDeg / 2,
                        mmfBandInnerRadiusMm,
                        mmfBandOuterRadiusMm,
                      )}
                    />
                    {renderMmfSourceArrow('north', statorFieldAngleDeg)}
                    {renderMmfSourceArrow('south', statorFieldAngleDeg + 180)}
                  </>
                ) : null}
                {windingCurrentCues.map((cue) => {
                  const currentTarget = labelPoint(cue.angleDeg, slotCurrentCueRadiusMm);
                  const identityTarget = labelPoint(cue.angleDeg, slotIdentityRadiusMm);
                  // Use the area-weighted center of the complete winding wedge,
                  // rather than one nearby mesh triangle, so A/B/C stays visually
                  // centered for coarse and uneven meshes. S1-S6 remains in the
                  // yoke ring so the two teaching labels cannot cover one another.
                  const point = getRegionSectorSvgCentroid(
                    'slot_winding',
                    cue.angleDeg,
                    360 / Math.max(3, Math.round(meshData.config_summary.slots)),
                  )
                    ?? currentTarget;
                  const identityPoint = identityTarget;
                  const currentSign = windingCurrentCuesMuted || Math.abs(cue.slotCurrentA) < 0.05
                    ? 0
                    : cue.slotCurrentA > 0 ? 1 : -1;
                  const phaseColor = BACK_EMF_PHASE_COLORS[cue.phase];
                  const currentCueColor = windingCurrentCuesMuted ? '#64748b' : phaseColor;
                  return (
                    <React.Fragment key={`slot-current-${cue.slotIndex}-${cue.phase}`}>
                      <g
                        className="mesh-slot-identity-chip"
                        transform={`translate(${identityPoint.x} ${identityPoint.y})`}
                        style={{ ['--slot-phase-color' as string]: phaseColor }}
                      >
                        <rect x={-4.2} y={-2.65} width={8.4} height={5.3} rx={1.6} />
                        <text x={0} y={0.85}>{`S${cue.slotIndex + 1}`}</text>
                        <title>{`Winding slot S${cue.slotIndex + 1} at ${cue.angleDeg.toFixed(0)} electrical degrees`}</title>
                      </g>
                      <g
                        className={`mesh-slot-current-cue is-${currentSign > 0 ? 'positive' : currentSign < 0 ? 'negative' : 'zero'}${windingCurrentCuesMuted ? ' is-muted' : ''}`}
                        transform={`translate(${point.x} ${point.y})`}
                        style={{ ['--slot-phase-color' as string]: currentCueColor }}
                      >
                        <circle r={3.25} />
                        <text x={-0.98} y={0.85} className="mesh-slot-current-phase">{cue.phase}</text>
                        <text x={1.18} y={0.95} className="mesh-slot-current-symbol">
                          {currentSign > 0 ? '•' : currentSign < 0 ? '×' : '○'}
                        </text>
                        <title>
                          {windingCurrentCuesMuted
                            ? `Slot S${cue.slotIndex + 1} at ${cue.angleDeg.toFixed(0)} deg: phase ${cue.phase} stator current disabled in PM-only view (0 A)`
                            : `Slot S${cue.slotIndex + 1} at ${cue.angleDeg.toFixed(0)} deg: phase ${cue.phase} ${Math.abs(cue.phaseCurrentA) < 0.05 ? '0.00' : `${cue.phaseCurrentA > 0 ? '+' : ''}${cue.phaseCurrentA.toFixed(2)}`} A; ${currentSign > 0 ? 'out of page (+J)' : currentSign < 0 ? 'into page (-J)' : 'no axial current'}`}
                        </title>
                      </g>
                    </React.Fragment>
                  );
                })}
              </g>
            ) : null}

            {showMagnetizationLabels && tutorialOverlayMode === 'forces' && torqueDirectionSign !== 0 ? (
              <g
                className={`mesh-force-overlay is-${torqueDirection}`}
                strokeWidth={1.6 / effectiveScale}
              >
                {forceArrowAngles.map(renderForceArrow)}
              </g>
            ) : null}

            {showMesh && shouldRenderShaftOverlay && shaftRadiusMm ? (
              <g transform={`rotate(${effectiveRotorAngleDeg} 0 0)`}>
                <circle
                  cx={0}
                  cy={0}
                  r={shaftRadiusMm}
                  fill={REGION_COLORS.shaft}
                  stroke="rgba(203, 213, 225, 0.72)"
                  strokeWidth={0.18 / effectiveScale}
                  onMouseEnter={() => setHoveredRegion('shaft')}
                  onMouseLeave={() => setHoveredRegion(null)}
                />
              </g>
            ) : null}

            {showDimensions && (
              <g className="mesh-viewer-annotations">
                {radialDimensions.map((dimension) => (
                  <g key={dimension.key}>
                    <line
                      x1={dimension.x}
                      y1={-dimension.inner}
                      x2={dimension.x}
                      y2={-dimension.outer}
                      stroke="rgba(241, 245, 249, 0.72)"
                      strokeWidth={annotationStroke}
                    />
                    <line
                      x1={dimension.x - 0.9 / effectiveScale}
                      y1={-dimension.inner}
                      x2={dimension.x + 0.9 / effectiveScale}
                      y2={-dimension.inner}
                      stroke="rgba(241, 245, 249, 0.72)"
                      strokeWidth={annotationStroke}
                    />
                    <line
                      x1={dimension.x - 0.9 / effectiveScale}
                      y1={-dimension.outer}
                      x2={dimension.x + 0.9 / effectiveScale}
                      y2={-dimension.outer}
                      stroke="rgba(241, 245, 249, 0.72)"
                      strokeWidth={annotationStroke}
                    />
                    <rect
                      x={dimension.x + 0.9 / effectiveScale}
                      y={dimension.textY - labelFontSize}
                      width={dimension.label.length * (labelFontSize * 0.56) + annotationBoxPadding * 2}
                      height={labelFontSize * 1.7}
                      rx={0.8 / effectiveScale}
                      fill="rgba(15, 23, 42, 0.82)"
                      stroke="rgba(148, 163, 184, 0.3)"
                      strokeWidth={0.08 / effectiveScale}
                    />
                    <text
                      x={dimension.x + 0.9 / effectiveScale + annotationBoxPadding}
                      y={dimension.textY}
                      fontSize={labelFontSize}
                      fill="rgba(241, 245, 249, 0.92)"
                    >
                      {dimension.label}
                    </text>
                  </g>
                ))}
              </g>
            )}

            {showMagnetizationLabels && (
              <g className="mesh-magnetization-labels">
                {magnetizationLabelMode !== 'pm' && magneticLabels.map((item, index) => renderMagneticLabel(
                  `stator-${index}`,
                  item.label,
                  item.x,
                  item.y,
                  item.kind,
                ))}
                {magnetizationLabelMode !== 'stator' && renderMagneticLabel(
                  'rotor-n',
                  'PM N',
                  rotorPmNLabel.x,
                  rotorPmNLabel.y,
                  'rotor-n',
                )}
                {magnetizationLabelMode !== 'stator' && renderMagneticLabel(
                  'rotor-s',
                  'PM S',
                  rotorPmSLabel.x,
                  rotorPmSLabel.y,
                  'rotor-s',
                )}
              </g>
            )}

            {dipoleMarkers.length > 0 ? (
              <g className="mesh-viewer-dipole-markers" pointerEvents="none">
                {dipoleMarkers.map((marker, index) => {
                  const halfLength = marker.lengthMm / 2;
                  const halfThickness = marker.thicknessMm / 2;
                  const screenAngleDeg = solverYSign * marker.angleDeg;
                  const labelFontSize = 1.55 / effectiveScale;
                  const isSurfaceArcRotor = marker.shape === 'surface-arcs';
                  const rotorRadius = marker.rotorRadiusMm ?? halfLength;
                  const poleArcDeg = Math.min(160, Math.max(70, marker.poleArcDeg ?? 132));
                  const poleOuterRadius = rotorRadius * 0.96;
                  const poleThickness = Math.min(
                    poleOuterRadius * 0.42,
                    Math.max(rotorRadius * 0.1, marker.poleThicknessMm ?? rotorRadius * 0.19),
                  );
                  const poleInnerRadius = poleOuterRadius - poleThickness;
                  const poleLabelRadius = (poleOuterRadius + poleInnerRadius) / 2;
                  const torqueRadius = isSurfaceArcRotor
                    ? Math.max(rotorRadius * 1.24, marker.thicknessMm * 1.25)
                    : Math.max(marker.lengthMm * 0.69, marker.thicknessMm * 1.25);
                  const torqueArrowReach = 1.7 / effectiveScale;
                  const torqueArrowWing = 0.82 / effectiveScale;
                  const torqueTopY = -torqueRadius;
                  const torqueBottomY = torqueRadius;
                  const torqueTopPath = marker.torqueDirection === 'cw'
                    ? `M ${-torqueArrowReach} ${torqueTopY - torqueArrowWing} L ${torqueArrowReach * 0.18} ${torqueTopY} L ${-torqueArrowReach} ${torqueTopY + torqueArrowWing}`
                    : `M ${torqueArrowReach} ${torqueTopY - torqueArrowWing} L ${-torqueArrowReach * 0.18} ${torqueTopY} L ${torqueArrowReach} ${torqueTopY + torqueArrowWing}`;
                  const torqueBottomPath = marker.torqueDirection === 'cw'
                    ? `M ${torqueArrowReach} ${torqueBottomY - torqueArrowWing} L ${-torqueArrowReach * 0.18} ${torqueBottomY} L ${torqueArrowReach} ${torqueBottomY + torqueArrowWing}`
                    : `M ${-torqueArrowReach} ${torqueBottomY - torqueArrowWing} L ${torqueArrowReach * 0.18} ${torqueBottomY} L ${-torqueArrowReach} ${torqueBottomY + torqueArrowWing}`;
                  return (
                    <g
                      key={`${marker.xMm}-${marker.yMm}-${index}`}
                      transform={`translate(${marker.xMm} ${solverYSign * marker.yMm})`}
                    >
                      {marker.torqueDirection ? (
                        <g
                          className={`mesh-viewer-torque-indicator is-${marker.torqueDirection}${marker.animateTorque ? ' is-flowing' : ''}`}
                          style={{ filter: 'drop-shadow(0 0 3px rgba(245, 158, 11, 0.74))' }}
                        >
                          <circle
                            r={torqueRadius}
                            pathLength={100}
                            fill="none"
                            stroke="#f59e0b"
                            strokeWidth={0.54 / effectiveScale}
                            strokeDasharray="7 5"
                            vectorEffect="non-scaling-stroke"
                          />
                          <path d={torqueTopPath} />
                          <path d={torqueBottomPath} />
                          <text
                            x={0}
                            y={-torqueRadius - (2.2 / effectiveScale)}
                            fill="#fbbf24"
                            stroke="rgba(3, 7, 18, 0.96)"
                            strokeWidth={0.44 / effectiveScale}
                            paintOrder="stroke"
                            fontFamily="var(--font-mono)"
                            fontSize={1.18 / effectiveScale}
                            fontWeight={900}
                            textAnchor="middle"
                          >
                            τ {marker.torqueDirection.toUpperCase()}
                          </text>
                        </g>
                      ) : null}
                      <g
                        transform={`rotate(${screenAngleDeg})`}
                        style={{ filter: 'drop-shadow(0 0 4px rgba(245, 158, 11, 0.72))' }}
                      >
                        {isSurfaceArcRotor ? (
                          <>
                            <circle
                              r={poleInnerRadius}
                              fill="rgba(71, 85, 105, 0.42)"
                              stroke="rgba(203, 213, 225, 0.5)"
                              strokeWidth={0.14 / effectiveScale}
                            />
                            <path
                              d={annularSectorPath(180, poleArcDeg, poleInnerRadius, poleOuterRadius)}
                              fill="#2563eb"
                              stroke="rgba(219, 234, 254, 0.9)"
                              strokeWidth={0.16 / effectiveScale}
                            />
                            <path
                              d={annularSectorPath(0, poleArcDeg, poleInnerRadius, poleOuterRadius)}
                              fill="#ef4444"
                              stroke="rgba(254, 226, 226, 0.9)"
                              strokeWidth={0.16 / effectiveScale}
                            />
                            <circle
                              r={poleOuterRadius}
                              fill="none"
                              stroke="rgba(255, 255, 255, 0.46)"
                              strokeWidth={0.12 / effectiveScale}
                            />
                            <text
                              x={-poleLabelRadius}
                              y={labelFontSize * 0.34}
                              transform={`rotate(${-screenAngleDeg} ${-poleLabelRadius} 0)`}
                              fill="#fff"
                              fontFamily="var(--font-mono)"
                              fontSize={labelFontSize}
                              fontWeight={900}
                              textAnchor="middle"
                            >
                              S
                            </text>
                            <text
                              x={poleLabelRadius}
                              y={labelFontSize * 0.34}
                              transform={`rotate(${-screenAngleDeg} ${poleLabelRadius} 0)`}
                              fill="#fff"
                              fontFamily="var(--font-mono)"
                              fontSize={labelFontSize}
                              fontWeight={900}
                              textAnchor="middle"
                            >
                              N
                            </text>
                          </>
                        ) : (
                          <>
                            <rect
                              x={-halfLength}
                              y={-halfThickness}
                              width={halfLength}
                              height={marker.thicknessMm}
                              rx={0.7}
                              fill="#2563eb"
                            />
                            <rect
                              x={0}
                              y={-halfThickness}
                              width={halfLength}
                              height={marker.thicknessMm}
                              rx={0.7}
                              fill="#ef4444"
                            />
                            <rect
                              x={-halfLength}
                              y={-halfThickness}
                              width={marker.lengthMm}
                              height={marker.thicknessMm}
                              rx={0.7}
                              fill="none"
                              stroke="rgba(255, 255, 255, 0.88)"
                              strokeWidth={0.16 / effectiveScale}
                            />
                            <line
                              x1={0}
                              y1={-halfThickness}
                              x2={0}
                              y2={halfThickness}
                              stroke="rgba(255, 255, 255, 0.46)"
                              strokeWidth={0.1 / effectiveScale}
                            />
                            <text
                              x={-halfLength / 2}
                              y={labelFontSize * 0.34}
                              transform={`rotate(${-screenAngleDeg} ${-halfLength / 2} 0)`}
                              fill="#fff"
                              fontFamily="var(--font-mono)"
                              fontSize={labelFontSize}
                              fontWeight={900}
                              textAnchor="middle"
                            >
                              S
                            </text>
                            <text
                              x={halfLength / 2}
                              y={labelFontSize * 0.34}
                              transform={`rotate(${-screenAngleDeg} ${halfLength / 2} 0)`}
                              fill="#fff"
                              fontFamily="var(--font-mono)"
                              fontSize={labelFontSize}
                              fontWeight={900}
                              textAnchor="middle"
                            >
                              N
                            </text>
                          </>
                        )}
                        <circle
                          r={isSurfaceArcRotor ? Math.max(0.85, rotorRadius * 0.12) : 0.85}
                          fill="#0f172a"
                          stroke="#fbbf24"
                          strokeWidth={0.13 / effectiveScale}
                        />
                      </g>
                    </g>
                  );
                })}
              </g>
            ) : null}

            {directionVectors.length > 0 ? (
              <g className="mesh-viewer-direction-vectors" pointerEvents="none">
                {directionVectors.map((vector, index) => {
                  const strokeScale = vector.strokeScale ?? 1;
                  const startColor = vector.colorStart ?? directionVectorToneColor(vector.tone);
                  const endColor = vector.colorEnd ?? startColor;
                  const gradientId = `${directionVectorDefsPrefix}-gradient-${index}`;
                  const markerId = `${directionVectorDefsPrefix}-marker-${index}`;
                  const labelX = vector.labelXmm ?? (vector.x1Mm + vector.x2Mm) / 2;
                  const labelY = vector.labelYmm ?? (vector.y1Mm + vector.y2Mm) / 2;
                  return (
                    <g key={`${vector.x1Mm}-${vector.y1Mm}-${vector.x2Mm}-${vector.y2Mm}-${index}`}>
                      {vector.orbitGuideRadiusMm ? (
                        <circle
                          className="mesh-viewer-vector-orbit-guide"
                          cx={vector.x1Mm}
                          cy={solverYSign * vector.y1Mm}
                          r={vector.orbitGuideRadiusMm}
                          fill="none"
                          stroke={vector.labelColor ?? endColor}
                          strokeWidth={0.42 / effectiveScale}
                          strokeDasharray={`${1.2 / effectiveScale} ${1.8 / effectiveScale}`}
                          opacity={0.3}
                        />
                      ) : null}
                      <line
                        x1={vector.x1Mm}
                        y1={solverYSign * vector.y1Mm}
                        x2={vector.x2Mm}
                        y2={solverYSign * vector.y2Mm}
                        stroke={`url(#${gradientId})`}
                        strokeWidth={(vector.tone === 'cyan' || vector.colorStart ? 1.2 : 0.82) * strokeScale / effectiveScale}
                        strokeDasharray={vector.dashed ? `${2.4 / effectiveScale} ${1.8 / effectiveScale}` : undefined}
                        opacity={vector.tone === 'blue' ? 0.72 : 0.94}
                        markerEnd={`url(#${markerId})`}
                      />
                      {vector.label ? (
                        <text
                          x={labelX}
                          y={solverYSign * labelY}
                          fill={vector.labelColor ?? endColor}
                          stroke="rgba(3, 7, 18, 0.96)"
                          strokeWidth={0.5 / effectiveScale}
                          paintOrder="stroke"
                          fontFamily="var(--font-mono)"
                          fontSize={1.28 / effectiveScale}
                          fontWeight={900}
                          textAnchor="middle"
                          dominantBaseline="middle"
                        >
                          {vector.label}
                        </text>
                      ) : null}
                    </g>
                  );
                })}
              </g>
            ) : null}

            {pointLabels.length > 0 ? (
              <g className="mesh-viewer-point-labels" pointerEvents="none">
                {pointLabels.map((point, index) => {
                  const pointDrag = point.dragKey && activeRegionDrag?.dragKey === point.dragKey
                    ? activeRegionDrag
                    : null;
                  const pointScale = point.scale ?? 1;
                  const textScale = point.textScale ?? 1;
                  const radius = 2.25 * pointScale / effectiveScale;
                  const fontSize = 1.85 * pointScale * textScale / effectiveScale;
                  const detailFontSize = 1.65 * pointScale / effectiveScale;
                  const fill = point.tone === 'north'
                    ? '#ef4444'
                    : point.tone === 'south'
                      ? '#2563eb'
                      : '#334155';
                  return (
                    <g
                      key={`${point.label}-${point.xMm}-${point.yMm}-${index}`}
                      transform={`translate(${point.xMm + (pointDrag?.deltaXMm ?? 0)} ${solverYSign * (point.yMm + (pointDrag?.deltaYMm ?? 0))})`}
                    >
                      {point.showBadge !== false ? (
                        <circle
                          r={radius}
                          fill={fill}
                          stroke="rgba(255, 255, 255, 0.82)"
                          strokeWidth={0.14 * pointScale / effectiveScale}
                        />
                      ) : null}
                      <text
                        x={0}
                        y={fontSize * 0.34}
                        fill="#fff"
                        stroke={point.showBadge === false ? 'rgba(3, 7, 18, 0.92)' : undefined}
                        strokeWidth={point.showBadge === false ? 0.3 * pointScale / effectiveScale : undefined}
                        paintOrder={point.showBadge === false ? 'stroke' : undefined}
                        fontFamily="var(--font-mono)"
                        fontSize={fontSize}
                        fontWeight={900}
                        textAnchor="middle"
                      >
                        {point.label}
                      </text>
                      {point.detailLabel ? (
                        <text
                          x={radius + 1.15 / effectiveScale}
                          y={detailFontSize * 0.34}
                          fill="#f8fafc"
                          stroke="rgba(3, 7, 18, 0.94)"
                          strokeWidth={0.34 * pointScale / effectiveScale}
                          paintOrder="stroke"
                          fontFamily="var(--font-mono)"
                          fontSize={detailFontSize}
                          fontWeight={850}
                          textAnchor="start"
                        >
                          {point.detailLabel}
                        </text>
                      ) : null}
                    </g>
                  );
                })}
              </g>
            ) : null}
            {forceVectors.length > 0 ? (
              <g className="mesh-force-overlay mesh-force-vector-overlay" pointerEvents="none">
                {forceVectors.map((vector, index) => {
                  const labelFontSize = 1.55 / effectiveScale;
                  return (
                    <g key={`${vector.x1Mm}-${vector.y1Mm}-${vector.x2Mm}-${vector.y2Mm}-${index}`}>
                      <line
                        x1={vector.x1Mm}
                        y1={solverYSign * vector.y1Mm}
                        x2={vector.x2Mm}
                        y2={solverYSign * vector.y2Mm}
                        strokeWidth={1.8 / effectiveScale}
                        markerEnd={`url(#${forceMarkerId})`}
                      />
                      {vector.label ? (
                        <text
                          x={vector.x2Mm + 2.2 / effectiveScale}
                          y={solverYSign * vector.y2Mm - 1.2 / effectiveScale}
                          fill="#fbbf24"
                          stroke="none"
                          fontFamily="var(--font-mono)"
                          fontSize={labelFontSize}
                          fontWeight={900}
                          textAnchor="start"
                        >
                          {vector.label}
                        </text>
                      ) : null}
                    </g>
                  );
                })}
              </g>
            ) : null}
            {measurementGates.length > 0 ? (
              <g className="mesh-viewer-measurement-gates" pointerEvents="none">
                {measurementGates.map((gate, index) => {
                  const gateDrag = gate.dragKey && activeRegionDrag?.dragKey === gate.dragKey
                    ? activeRegionDrag
                    : null;
                  const deltaX = gateDrag?.deltaXMm ?? 0;
                  const deltaY = gateDrag?.deltaYMm ?? 0;
                  const x1 = gate.x1Mm + deltaX;
                  const y1 = solverYSign * (gate.y1Mm + deltaY);
                  const x2 = gate.x2Mm + deltaX;
                  const y2 = solverYSign * (gate.y2Mm + deltaY);
                  const labelX = gate.labelXmm + deltaX;
                  const labelY = solverYSign * (gate.labelYmm + deltaY);
                  const labelFontSize = 1.55 / effectiveScale;
                  const detailFontSize = 1.02 / effectiveScale;
                  const labelPaddingX = 0.9 / effectiveScale;
                  const labelWidth = Math.max(
                    gate.label.length * labelFontSize * 0.62,
                    (gate.detail?.length ?? 0) * detailFontSize * 0.58,
                  ) + labelPaddingX * 2;
                  const labelHeight = gate.detail ? labelFontSize * 2.65 : labelFontSize * 1.7;
                  const surfaceOffsetX = 0.85 / effectiveScale;
                  const surfaceOffsetY = -0.65 / effectiveScale;
                  return (
                    <g key={`${gate.label}-${index}`}>
                      <polygon
                        points={`${x1},${y1} ${x2},${y2} ${x2 + surfaceOffsetX},${y2 + surfaceOffsetY} ${x1 + surfaceOffsetX},${y1 + surfaceOffsetY}`}
                        fill="rgba(34, 211, 238, 0.2)"
                        stroke="rgba(165, 243, 252, 0.58)"
                        strokeWidth={0.12 / effectiveScale}
                        strokeLinejoin="round"
                      />
                      <line
                        x1={x1}
                        y1={y1}
                        x2={x2}
                        y2={y2}
                        stroke="rgba(34, 211, 238, 0.22)"
                        strokeWidth={1.0 / effectiveScale}
                        strokeLinecap="round"
                      />
                      <line
                        x1={x1}
                        y1={y1}
                        x2={x2}
                        y2={y2}
                        stroke="#67e8f9"
                        strokeWidth={0.3 / effectiveScale}
                        strokeLinecap="round"
                      />
                      <circle cx={x1} cy={y1} r={0.55 / effectiveScale} fill="#22d3ee" stroke="#cffafe" strokeWidth={0.12 / effectiveScale} />
                      <circle cx={x2} cy={y2} r={0.55 / effectiveScale} fill="#22d3ee" stroke="#cffafe" strokeWidth={0.12 / effectiveScale} />
                      <line
                        x1={(x1 + x2) / 2}
                        y1={(y1 + y2) / 2}
                        x2={labelX}
                        y2={labelY}
                        stroke="rgba(103, 232, 249, 0.68)"
                        strokeWidth={0.16 / effectiveScale}
                        strokeDasharray={`${0.65 / effectiveScale} ${0.55 / effectiveScale}`}
                      />
                      <rect
                        x={labelX - labelWidth / 2}
                        y={labelY - labelHeight / 2}
                        width={labelWidth}
                        height={labelHeight}
                        rx={0.7 / effectiveScale}
                        fill="rgba(8, 47, 73, 0.94)"
                        stroke="rgba(103, 232, 249, 0.76)"
                        strokeWidth={0.12 / effectiveScale}
                      />
                      <text
                        x={labelX}
                        y={labelY + (gate.detail ? -labelFontSize * 0.08 : labelFontSize * 0.34)}
                        fill="#cffafe"
                        fontFamily="var(--font-mono)"
                        fontSize={labelFontSize}
                        fontWeight={800}
                        textAnchor="middle"
                      >
                        {gate.label}
                      </text>
                      {gate.detail ? (
                        <text
                          x={labelX}
                          y={labelY + labelFontSize * 0.78}
                          fill="#67e8f9"
                          fontFamily="var(--font-mono)"
                          fontSize={detailFontSize}
                          fontWeight={700}
                          textAnchor="middle"
                        >
                          {gate.detail}
                        </text>
                      ) : null}
                    </g>
                  );
                })}
              </g>
            ) : null}
          </g>
        </svg>

        {!fixedView && (
          <div className="mesh-viewer-scale-bar" aria-hidden="true">
            <div className="mesh-viewer-scale-bar-line" style={{ width: `${scaleBarWidth}px` }} />
            <span>{scaleBarMm.toFixed(0)} mm</span>
          </div>
        )}

        {fieldIntensity && (
          <div className="mesh-viewer-intensity-legend" aria-hidden="true">
            <span className="mesh-viewer-intensity-legend-label">|B| {(fieldIntensity.low * fieldIntensityLegendScale.multiplier).toFixed(2)}</span>
            <span
              className="mesh-viewer-intensity-legend-ramp"
              style={{
                background: `linear-gradient(90deg, ${fieldIntensityColors.join(', ')})`,
              }}
            />
            <span className="mesh-viewer-intensity-legend-label">{(fieldIntensity.high * fieldIntensityLegendScale.multiplier).toFixed(2)} {fieldIntensityLegendScale.unit}</span>
          </div>
        )}
      </div>

      {!fixedView && <div className={`mesh-viewer-toolbar${toolbarMode === 'zoom-only' ? ' is-zoom-only' : ''}`}>
        <div className="mesh-viewer-controls">
          <button onClick={zoomIn} title="Zoom in" type="button">+</button>
          <button onClick={zoomOut} title="Zoom out" type="button">−</button>
          <button onClick={fitToView} title="Fit to view" type="button">Fit</button>
          {toolbarMode === 'full' ? (
            <button
              className={showMesh ? 'active' : ''}
              onClick={() => setShowMesh((value) => !value)}
              title="Toggle mesh regions"
              type="button"
            >
              Mesh
            </button>
          ) : null}
          {toolbarMode === 'full' && canShowFieldLines ? (
            <button
              className={effectiveShowFieldLines ? 'active' : ''}
              onClick={() => setShowFieldLines((value) => !value)}
              title="Toggle field lines"
              type="button"
            >
              Field Lines
            </button>
          ) : null}
          {toolbarMode === 'full' ? (
            <button
              className={showDimensions ? 'active' : ''}
              onClick={() => setShowDimensions((value) => !value)}
              title="Toggle dimension annotations"
              type="button"
            >
              Dimensions
            </button>
          ) : null}
          {toolbarMode === 'full' && showRotorAnimationControls ? (
            <>
              <div className="mesh-viewer-controls-divider" aria-hidden="true" />
              <button
                onClick={() => setIsAnimating((value) => !value)}
                title={isAnimating ? 'Pause rotor animation' : 'Play rotor animation'}
                type="button"
              >
                {isAnimating ? '⏸' : '▶'}
              </button>
              <button
                onClick={resetAnimation}
                title="Stop and reset rotor animation"
                type="button"
              >
                ⏹
              </button>
              <select
                className="mesh-viewer-speed-select"
                value={animationSpeed}
                onChange={(event) => setAnimationSpeed(Number(event.target.value))}
                title="Rotor animation speed"
              >
                <option value={0.25}>0.25x</option>
                <option value={0.5}>0.5x</option>
                <option value={1}>1x</option>
                <option value={1.5}>1.5x</option>
                <option value={2}>2x</option>
                <option value={4}>4x</option>
              </select>
            </>
          ) : null}
        </div>

        {toolbarMode === 'zoom-only' && toolbarLabel ? (
          <div className="mesh-viewer-toolbar-label">{toolbarLabel}</div>
        ) : null}

        {toolbarMode === 'full' ? (
          <div className="mesh-viewer-legend">
            {uniqueRegions.filter((region) => region !== 'airgap').map((region) => (
              <div
                key={region}
                className={`mesh-legend-item ${hoveredRegion === region ? 'highlighted' : ''}`}
                onMouseEnter={() => setHoveredRegion(region)}
                onMouseLeave={() => setHoveredRegion(null)}
              >
                <span
                  className="mesh-legend-swatch"
                  style={{ backgroundColor: REGION_COLORS[region] }}
                />
                <span className="mesh-legend-label">{REGION_LABELS[region] || region}</span>
              </div>
            ))}
            {canShowFieldLines && (
              <div className="mesh-legend-item">
                <span className="mesh-legend-line" />
                <span className="mesh-legend-label">Field Lines</span>
              </div>
            )}
          </div>
        ) : null}

        {toolbarMode === 'full' ? (
          <div className="mesh-viewer-symmetry">
            {meshData.n_pole_pitches < meshData.config_summary.poles
              ? `${meshData.n_pole_pitches} of ${meshData.config_summary.poles} pole pitches shown`
              : 'Full motor model'}
          </div>
        ) : null}
      </div>}
    </div>
  );

  if (embedded) {
    return <div className={`mesh-viewer-embedded-shell ${compactEmbedded ? 'mesh-viewer-embedded-shell-compact' : ''}`}>{content}</div>;
  }

  return <div className="mesh-viewer-overlay">{content}</div>;
};
