import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import { createPortal } from 'react-dom';

import {
  buildDimensionAnnotations,
  RESTING_DIMENSIONS,
  type DimensionAnnotation,
  type DimensionId,
} from './dimensionAnnotations';
import type {
  GeometryPreview,
  MeshPreview,
  MotorConfig,
  PublicMotorComponentKind,
  PublicMotorComponentSelection,
} from './model';
import {
  computeMagnetPoleFaces,
  computeSpmMagnetPolarityHalves,
} from './magnetPoleFaces';
import { PUBLIC_MOTOR_COLORS, PUBLIC_PHASE_COLORS } from './motorPalette';
import { polygonLabelSpot } from './canvasLabels';
import { fitTransform } from './viewportTransform';
import {
  PHASE_SCOPE_WINDOW_S,
  STRIP_END,
  STRIP_LABEL,
  coilSideOutOfPage,
  electricalFrequencyHz,
  formatHz,
  formatRevPerSecond,
  phaseCurrents,
  phaseDriveFrame,
  phaseStrips,
  TRACE_AMPLITUDE,
  phaseChargeShift,
  phasePanelTop,
  rotorElectricalDeg,
  slotCurrents,
  toothIndexAt,
  toothPoles,
  waveformTrace,
  windingSymbolSide,
  type PhaseDrive,
  type Rect,
} from './phaseDrive';
import { drawPhaseDriveWired } from './phaseDrivePanel';
import { pointInContours, previewContours, type Contour } from './previewContours';
import { publishedReference } from './publishedReferences';
import { outerRotorRing, ringKey, sectorView } from './sectorFraming';
import {
  useViewportNavigation,
  ViewportNavigationControls,
} from './ViewportNavigation';
import {
  publicMeshQualityBand,
  type PublicMeshQualityBand,
} from './meshQuality';

export type PublicMeshDisplayMode = 'geometry' | 'quality' | 'problems';

export interface PublicMeshElementSelection {
  index: number;
  quality: number;
  band: PublicMeshQualityBand;
  region: string;
}

const EMPTY_MESH_QUALITIES: number[] = [];

interface MotorCanvasProps {
  geometry: GeometryPreview | null;
  mesh: MeshPreview | null;
  mode: 'geometry' | 'mesh';
  layer?: PublicCanvasLayer;
  /** Labels drawn over the motor, each on or off by itself. Left out, they follow `layer`. */
  overlays?: PublicCanvasOverlays;
  rotorAngleDeg?: number;
  windingType?: 'concentrated' | 'distributed';
  selectedComponent?: PublicMotorComponentSelection | null;
  highlightComponentKind?: PublicMotorComponentKind | null;
  onComponentSelect?: (component: PublicMotorComponentSelection | null) => void;
  /** Needed by the Dims layer: tooth, slot, magnet and yoke sizes are config-only. */
  config?: MotorConfig;
  activeDimension?: DimensionId | null;
  /** Previewed from the readout without committing a selection. */
  hoveredDimension?: DimensionId | null;
  onDimensionSelect?: (dimension: DimensionId | null) => void;
  /** Display-only polarity treatment; it never changes geometry or solver inputs. */
  magnetPolarityView?: PublicMagnetPolarityView;
  /** Tint each stator tooth N / S by the pole the drive currents make it. */
  showToothPoles?: boolean;
  /** Preview speed: the Phases waveforms show the electrical frequency it makes. */
  previewRpm?: number;
  meshDisplayMode?: PublicMeshDisplayMode;
  showMeshEdges?: boolean;
  /** Element-edge colour in place of the usual grey. */
  meshEdgeColor?: string | null;
  /** Mesh view: show the area under the pointer enlarged in a corner. */
  magnifier?: boolean;
  /** Draw every coil side in one plain colour instead of its phase colour. */
  plainWinding?: boolean;
  meshQualities?: number[];
  meshQualityThreshold?: number;
  focusedMeshElementIndex?: number | null;
  onMeshElementHover?: (element: PublicMeshElementSelection | null) => void;
  onMeshElementSelect?: (element: PublicMeshElementSelection | null) => void;
  /** Where the zoom controls go; without one they float over the canvas. */
  navigationSlot?: HTMLElement | null;
}

/** 'none' = every overlay off, leaving the bare cross-section. */
export type PublicCanvasLayer = 'none' | 'dimensions' | 'slots' | 'windings' | 'phases' | 'materials';
/** The label overlays: dimension lines, slot numbers, tooth numbers and coil-side labels (A+, A-). */
export interface PublicCanvasOverlays { dimensions: boolean; slots: boolean; teeth: boolean; windings: boolean }
export const NO_CANVAS_OVERLAYS: PublicCanvasOverlays = { dimensions: false, slots: false, teeth: false, windings: false };
export type PublicMagnetPolarityView = 'dominant' | 'split';

interface HitRegion {
  points: Array<[number, number]>;
  loops?: Contour[];
  selection: PublicMotorComponentSelection;
}

/** A drawn dimension line in canvas space, so clicking near it can name it. */
interface DimensionHit {
  id: DimensionId;
  from: [number, number];
  to: [number, number];
}

interface MeshTriangleHit {
  points: Array<[number, number]>;
  selection: PublicMeshElementSelection;
}

/** What one pass of drawMesh leaves out or changes. */
interface MeshDrawOptions {
  /** Only the elements that turn with the rotor, or only those that do not. */
  part?: 'all' | 'fixed' | 'rotor';
  /** False leaves the region fills out, for a mesh drawn over the geometry. */
  fill?: boolean;
  /** Each element's phase when it is in a coil side (meshCoilPhases). */
  coilPhases?: Array<string | null> | null;
  /** Draw only elements touching this box, in canvas px: left, top, right, bottom. */
  cull?: [number, number, number, number] | null;
  edgeWidthScale?: number;
}

/** Where a drawn mesh sits on the canvas: the motor centre and its outer radius, in px. */
interface MeshDrawFrame {
  origin: [number, number];
  radiusPx: number;
}

const MESH_FILL_KEY_SEPARATOR = '\u0000';
/** The magnifier panel: its side in CSS px, and how much larger it draws than the view. */
const MESH_LOUPE_SIZE_PX = 240;
const MESH_LOUPE_MAGNIFICATION = 3;
/** Keep a full rotor bitmap within 16 MiB, even at the highest viewport zoom. */
const MAX_ROTOR_CACHE_SIDE_PX = 2048;
const ROTOR_CACHE_PADDING_PX = 16;

const meshRotorRadiusCache = new WeakMap<MeshPreview, number>();
function meshRotorRadiusMm(mesh: MeshPreview): number {
  let radius = meshRotorRadiusCache.get(mesh);
  if (radius === undefined) {
    radius = 0;
    for (let index = 0; index < mesh.triangles.length; index += 1) {
      if (!isRotorRegion(mesh.regions[index] || 'mesh')) continue;
      for (const node of mesh.triangles[index]) radius = Math.max(radius, Math.hypot(...mesh.nodes_mm[node]));
    }
    meshRotorRadiusCache.set(mesh, radius);
  }
  return radius;
}

const meshOuterRadiusCache = new WeakMap<MeshPreview, number>();
function meshOuterRadiusMm(mesh: MeshPreview): number {
  let radius = meshOuterRadiusCache.get(mesh);
  if (radius === undefined) {
    radius = 0;
    for (const [x, y] of mesh.nodes_mm) radius = Math.max(radius, Math.hypot(x, y));
    meshOuterRadiusCache.set(mesh, radius);
  }
  return radius;
}

const meshCoilPhaseCache = new WeakMap<MeshPreview, { geometry: GeometryPreview; phases: Array<string | null> }>();
/**
 * The phase of each mesh element that lies in a coil side, null elsewhere. The
 * mesh names its coil regions without a phase, so it is read from the geometry
 * preview's coil sides: the one that contains the element's centre.
 */
function meshCoilPhases(mesh: MeshPreview, geometry: GeometryPreview): Array<string | null> {
  const cached = meshCoilPhaseCache.get(mesh);
  if (cached && cached.geometry === geometry) return cached.phases;
  const coilSides = geometry.regions.flatMap((region) => {
    const winding = windingToken(region.region_type);
    if (!winding || region.points.length < 3) return [];
    const xs = region.points.map(([x]) => x);
    const ys = region.points.map(([, y]) => y);
    return [{
      phase: winding.phase as string,
      points: region.points,
      box: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)],
    }];
  });
  const phases = mesh.triangles.map((triangle, index) => {
    if (coilSides.length === 0 || !/slot|winding|coil/i.test(mesh.regions[index] || '')) return null;
    const x = (mesh.nodes_mm[triangle[0]][0] + mesh.nodes_mm[triangle[1]][0] + mesh.nodes_mm[triangle[2]][0]) / 3;
    const y = (mesh.nodes_mm[triangle[0]][1] + mesh.nodes_mm[triangle[1]][1] + mesh.nodes_mm[triangle[2]][1]) / 3;
    const side = coilSides.find(({ box, points }) => (
      x >= box[0] && x <= box[2] && y >= box[1] && y <= box[3] && pointInPolygon([x, y], points)
    ));
    return side?.phase ?? null;
  });
  meshCoilPhaseCache.set(mesh, { geometry, phases });
  return phases;
}

const REGION_COLORS: Array<[RegExp, string]> = [
  [/stator/i, '#6b7280'],
  [/rotor/i, '#3d4350'],
  [/magnet.*(?:n|0|2|4|6)/i, PUBLIC_MOTOR_COLORS.magnetNorth],
  [/magnet/i, PUBLIC_MOTOR_COLORS.magnetSouth],
  [/slot|winding/i, '#d18b32'],
  [/shaft/i, '#242a34'],
  [/air/i, '#18202a'],
];

function regionColor(name: string, fallback = '#697386'): string {
  return REGION_COLORS.find(([pattern]) => pattern.test(name))?.[1] ?? fallback;
}

const PHASE_COLORS = PUBLIC_PHASE_COLORS;

function windingToken(regionType: string): { phase: keyof typeof PHASE_COLORS; direction: '+' | '−' } | null {
  const match = regionType.match(/\(([abc])([+\-−])\)/i);
  if (!match) return null;
  return {
    phase: match[1].toUpperCase() as keyof typeof PHASE_COLORS,
    direction: match[2] === '+' ? '+' : '−',
  };
}

function slotNumberFromRegion(regionType: string): number | null {
  const match = regionType.match(/slot[_-]?(\d+)/i);
  return match ? Number(match[1]) : null;
}

/** Keep the polygon part on the non-negative side of the line through the origin with this normal. */
function clipPolygonToHalfPlane(
  points: Array<[number, number]>,
  normal: [number, number],
): Array<[number, number]> {
  const signedSide = (point: [number, number]) => normal[0] * point[0] + normal[1] * point[1];
  const clipped: Array<[number, number]> = [];
  for (let index = 0; index < points.length; index += 1) {
    const previous = points[(index + points.length - 1) % points.length];
    const current = points[index];
    const previousSide = signedSide(previous);
    const currentSide = signedSide(current);
    if ((previousSide >= 0) !== (currentSide >= 0)) {
      const fraction = previousSide / (previousSide - currentSide);
      clipped.push([
        previous[0] + (current[0] - previous[0]) * fraction,
        previous[1] + (current[1] - previous[1]) * fraction,
      ]);
    }
    if (currentSide >= 0) clipped.push(current);
  }
  return clipped;
}

/** ⊙ current toward the viewer, ⊗ current into the page. */
function drawCurrentMarker(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  outOfPage: boolean,
  ringColor: string,
): void {
  context.save();
  context.shadowColor = 'rgba(3, 5, 9, 0.6)';
  context.shadowBlur = radius * 0.9;
  context.shadowOffsetY = radius * 0.16;
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.fillStyle = 'rgba(8, 10, 14, 0.82)';
  context.fill();
  context.shadowColor = 'transparent';
  context.shadowBlur = 0;
  context.shadowOffsetY = 0;
  context.strokeStyle = ringColor;
  context.lineWidth = Math.max(1.1, radius * 0.18);
  context.stroke();
  if (outOfPage) {
    context.beginPath();
    context.arc(x, y, Math.max(1.3, radius * 0.34), 0, Math.PI * 2);
    context.fillStyle = '#f8fafc';
    context.fill();
  } else {
    const reach = radius * 0.52;
    context.strokeStyle = '#f8fafc';
    context.lineWidth = Math.max(1.1, radius * 0.22);
    context.beginPath();
    context.moveTo(x - reach, y - reach);
    context.lineTo(x + reach, y + reach);
    context.moveTo(x + reach, y - reach);
    context.lineTo(x - reach, y + reach);
    context.stroke();
  }
  context.restore();
}

function isRotorRegion(regionType: string): boolean {
  // V-shape IPM pockets are separate dark clearance polygons named
  // `ipm_pocket_*`. They are cut into the rotor, so they must follow the
  // magnets during playback; leaving them stationary produces a second set of
  // "ghost" V outlines as soon as the rotor moves.
  return /rotor|magnet|shaft|inter_pole_air|ipm_pocket|pocket_air/i.test(regionType) && !/stator/i.test(regionType);
}

function componentSelectionFromRegion(regionType: string, regionIndex: number): PublicMotorComponentSelection | null {
  const slotMatch = regionType.match(/slot[_-]?(\d+)/i);
  const poleMatch = regionType.match(/magnet[^0-9]*(\d+)/i);
  const winding = windingToken(regionType);
  const base = { id: `region-${regionIndex}`, regionType, regionIndex };

  if (/magnet/i.test(regionType)) {
    const poleIndex = poleMatch ? Number(poleMatch[1]) + 1 : undefined;
    const polarity = /(?:magnet.*n|magnet_n)/i.test(regionType) ? 'N' : /(?:magnet.*s|magnet_s)/i.test(regionType) ? 'S' : '';
    return {
      ...base,
      kind: 'magnet',
      label: `Magnet${polarity ? ` ${polarity}` : ''}${poleIndex ? ` · pole ${poleIndex}` : ''}`,
      role: 'Permanent-magnet field source',
      poleIndex,
    };
  }
  if (slotMatch || /winding|coil/i.test(regionType)) {
    const slotIndex = slotMatch ? Number(slotMatch[1]) : undefined;
    return {
      ...base,
      kind: 'winding',
      label: `${slotIndex ? `Slot ${slotIndex}` : 'Winding'}${winding ? ` · phase ${winding.phase}${winding.direction}` : ''}`,
      role: 'Current-carrying stator winding',
      slotIndex,
      phase: winding?.phase,
      direction: winding?.direction === '+' ? '+' : winding ? '-' : undefined,
    };
  }
  if (/stator/i.test(regionType)) {
    return {
      ...base,
      kind: 'stator',
      label: /tooth/i.test(regionType) ? 'Stator tooth' : /yoke/i.test(regionType) ? 'Stator yoke' : 'Stator core',
      role: 'Stationary magnetic flux path',
    };
  }
  if (/shaft/i.test(regionType)) {
    return { ...base, kind: 'shaft', label: 'Shaft', role: 'Mechanical rotor support' };
  }
  if (/air.?gap|inter_pole_air|air/i.test(regionType)) {
    return { ...base, kind: 'airgap', label: /inter_pole/i.test(regionType) ? 'Inter-pole air' : 'Air gap', role: 'Magnetic clearance region' };
  }
  if (/rotor/i.test(regionType)) {
    return { ...base, kind: 'rotor', label: 'Rotor core', role: 'Rotating magnetic flux path' };
  }
  return null;
}

function pointInPolygon(point: [number, number], polygon: Array<[number, number]>): boolean {
  let inside = false;
  for (let current = 0, previous = polygon.length - 1; current < polygon.length; previous = current, current += 1) {
    const [currentX, currentY] = polygon[current];
    const [previousX, previousY] = polygon[previous];
    const crosses = (currentY > point[1]) !== (previousY > point[1])
      && point[0] < (previousX - currentX) * (point[1] - currentY) / (previousY - currentY) + currentX;
    if (crosses) inside = !inside;
  }
  return inside;
}

function rotatePoint([x, y]: [number, number], angleDeg: number): [number, number] {
  if (!angleDeg) return [x, y];
  const angle = angleDeg * Math.PI / 180;
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return [x * cosine - y * sine, x * sine + y * cosine];
}

/** How hard each phase is driven right now, 0..1 (phaseDrive.ts). */
type PhaseLevels = Record<keyof typeof PHASE_COLORS, number>;

function phaseFill(phase: keyof typeof PHASE_COLORS, layer: PublicCanvasLayer, phaseLevels: PhaseLevels | null, plain = false): string {
  if (layer === 'phases' && phaseLevels) {
    // Each phase as bright as the current the solver drives through it at this
    // rotor position, so a phase six-step switches off goes dark.
    const strength = 0.48 + phaseLevels[phase] * 0.52;
    // With Coil colors off the coils stay copper, and only their brightness follows the current.
    const color = plain ? PUBLIC_MOTOR_COLORS.winding : PHASE_COLORS[phase];
    const red = Math.round(Number.parseInt(color.slice(1, 3), 16) * strength);
    const green = Math.round(Number.parseInt(color.slice(3, 5), 16) * strength);
    const blue = Math.round(Number.parseInt(color.slice(5, 7), 16) * strength);
    return `rgb(${red}, ${green}, ${blue})`;
  }
  return plain ? PUBLIC_MOTOR_COLORS.winding : PHASE_COLORS[phase];
}

function parseColorChannels(color: string): [number, number, number] {
  if (color.startsWith('#') && color.length >= 7) {
    return [
      Number.parseInt(color.slice(1, 3), 16),
      Number.parseInt(color.slice(3, 5), 16),
      Number.parseInt(color.slice(5, 7), 16),
    ];
  }
  const match = color.match(/rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)/);
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : [105, 115, 134];
}

function shadeColor(color: string, factor: number): string {
  const [red, green, blue] = parseColorChannels(color)
    .map((channel) => Math.max(0, Math.min(255, Math.round(channel * factor))));
  return `rgb(${red}, ${green}, ${blue})`;
}

/** Radial light falloff per component family — fakes the 3D key light in 2D. */
const REGION_SHADING: Array<[RegExp, Array<[number, number]>]> = [
  [/stator_yoke/i, [[0, 0.82], [0.55, 1.08], [0.9, 0.96], [1, 0.78]]],
  [/stator_tooth/i, [[0, 0.74], [1, 1.08]]],
  [/rotor/i, [[0, 1.12], [0.72, 0.96], [1, 0.74]]],
  [/magnet/i, [[0, 0.76], [0.6, 1], [1, 1.22]]],
  [/shaft/i, [[0, 1.5], [0.55, 1], [1, 0.58]]],
  [/slot|winding|coil/i, [[0, 0.84], [0.55, 1], [1, 1.16]]],
];

function shadedRegionFill(
  context: CanvasRenderingContext2D,
  regionType: string,
  baseColor: string,
  center: [number, number],
  innerRadiusPx: number,
  outerRadiusPx: number,
): string | CanvasGradient {
  const stops = REGION_SHADING.find(([pattern]) => pattern.test(regionType))?.[1];
  if (!stops || outerRadiusPx <= 0 || outerRadiusPx <= innerRadiusPx + 0.5) return baseColor;
  const highlightOffset = /shaft/i.test(regionType) ? outerRadiusPx * 0.32 : 0;
  const gradient = context.createRadialGradient(
    center[0] - highlightOffset,
    center[1] - highlightOffset,
    Math.max(0, innerRadiusPx),
    center[0],
    center[1],
    outerRadiusPx,
  );
  stops.forEach(([offset, factor]) => gradient.addColorStop(offset, shadeColor(baseColor, factor)));
  return gradient;
}

function radialExtentMm(points: Array<[number, number]>): [number, number] {
  let minRadius = Number.POSITIVE_INFINITY;
  let maxRadius = 0;
  for (const [x, y] of points) {
    const radius = Math.hypot(x, y);
    if (radius < minRadius) minRadius = radius;
    if (radius > maxRadius) maxRadius = radius;
  }
  return [minRadius === Number.POSITIVE_INFINITY ? 0 : minRadius, maxRadius];
}

function magnetAirgapPolarity(regionType: string): 'north' | 'south' {
  if (/magnet.*(?:north|[_-]n(?:[_-]|$))/i.test(regionType)) return 'north';
  if (/magnet.*(?:south|[_-]s(?:[_-]|$))/i.test(regionType)) return 'south';
  const poleIndex = Number(regionType.match(/magnet[^0-9]*(\d+)/i)?.[1] ?? 0);
  return poleIndex % 2 === 0 ? 'north' : 'south';
}

/** A magnet, or one pole's half of it, to letter N or S; canvas px. */
interface MagnetPoleLabel {
  points: Array<[number, number]>;
  north: boolean;
  /** Split view: each half's own pole, lettered when both fit. */
  halves?: MagnetPoleLabel[] | null;
}

function drawVShapeMagnetPolarityHalves(
  context: CanvasRenderingContext2D,
  magnetPoints: Array<[number, number]>,
  map: (point: [number, number]) => [number, number],
  regionType: string,
): MagnetPoleLabel[] | null {
  const faces = computeMagnetPoleFaces(magnetPoints);
  if (!faces) return null;

  const airgapIsNorth = magnetAirgapPolarity(regionType) === 'north';
  const airgapColor = airgapIsNorth
    ? PUBLIC_MOTOR_COLORS.magnetNorth
    : PUBLIC_MOTOR_COLORS.magnetSouth;
  const backColor = airgapIsNorth
    ? PUBLIC_MOTOR_COLORS.magnetSouth
    : PUBLIC_MOTOR_COLORS.magnetNorth;
  const centeredPoints = magnetPoints.map<[number, number]>(([x, y]) => [
    x - faces.center[0],
    y - faces.center[1],
  ]);
  const airgapHalf = clipPolygonToHalfPlane(
    centeredPoints,
    faces.airgapNormal,
  ).map<[number, number]>(([x, y]) => [
    x + faces.center[0],
    y + faces.center[1],
  ]);
  const backHalf = clipPolygonToHalfPlane(
    centeredPoints,
    [-faces.airgapNormal[0], -faces.airgapNormal[1]],
  ).map<[number, number]>(([x, y]) => [
    x + faces.center[0],
    y + faces.center[1],
  ]);

  const fillHalf = (points: Array<[number, number]>, color: string) => {
    if (points.length < 3) return;
    const canvasPoints = points.map(map);
    context.beginPath();
    context.moveTo(canvasPoints[0][0], canvasPoints[0][1]);
    for (const point of canvasPoints.slice(1)) context.lineTo(point[0], point[1]);
    context.closePath();
    context.fillStyle = color;
    context.fill();
  };

  context.save();
  context.globalAlpha = 0.94;
  fillHalf(airgapHalf, airgapColor);
  fillHalf(backHalf, backColor);
  context.restore();
  return [
    { points: airgapHalf.map(map), north: airgapIsNorth },
    { points: backHalf.map(map), north: !airgapIsNorth },
  ].filter((half) => half.points.length >= 3);
}

function drawSpmMagnetPolarityHalves(
  context: CanvasRenderingContext2D,
  magnetPoints: Array<[number, number]>,
  map: (point: [number, number]) => [number, number],
  regionType: string,
): MagnetPoleLabel[] | null {
  const halves = computeSpmMagnetPolarityHalves(magnetPoints);
  if (!halves) return null;

  const airgapIsNorth = magnetAirgapPolarity(regionType) === 'north';
  const drawHalf = (points: Array<[number, number]>, color: string) => {
    const canvasPoints = points.map(map);
    if (canvasPoints.length < 3) return;
    context.beginPath();
    context.moveTo(canvasPoints[0][0], canvasPoints[0][1]);
    for (const point of canvasPoints.slice(1)) context.lineTo(point[0], point[1]);
    context.closePath();
    context.fillStyle = color;
    context.fill();
  };

  context.save();
  context.globalAlpha = 0.94;
  drawHalf(
    halves.airgapHalf,
    airgapIsNorth ? PUBLIC_MOTOR_COLORS.magnetNorth : PUBLIC_MOTOR_COLORS.magnetSouth,
  );
  drawHalf(
    halves.backHalf,
    airgapIsNorth ? PUBLIC_MOTOR_COLORS.magnetSouth : PUBLIC_MOTOR_COLORS.magnetNorth,
  );
  context.restore();
  return [
    { points: halves.airgapHalf.map(map), north: airgapIsNorth },
    { points: halves.backHalf.map(map), north: !airgapIsNorth },
  ].filter((half) => half.points.length >= 3);
}

/**
 * Region types bounded by concentric circles; stroking those circles instead
 * of the tessellated polygon hides the polygon's radial closing seam.
 */
const ANNULAR_REGIONS = /^(stator_yoke|rotor_core|shaft)$/i;

function regionFill(regionType: string, sourceFill: string | null | undefined, layer: PublicCanvasLayer, phaseLevels: PhaseLevels | null, plainWinding = false): string {
  const winding = windingToken(regionType);
  // One colour for every coil side, so the eye stays on the N / S fields. Phases keeps the copper and shades it by current.
  if (plainWinding && winding && layer === 'phases') return phaseFill(winding.phase, layer, phaseLevels, true);
  if (plainWinding && winding && layer !== 'windings' && layer !== 'materials') return PUBLIC_MOTOR_COLORS.winding;
  if (layer === 'materials') {
    if (/stator/i.test(regionType)) return PUBLIC_MOTOR_COLORS.statorSteel;
    if (/rotor/i.test(regionType)) return PUBLIC_MOTOR_COLORS.rotorSteel;
    if (/magnet.*(?:n|0|2|4|6)/i.test(regionType)) return PUBLIC_MOTOR_COLORS.magnetNorth;
    if (/magnet/i.test(regionType)) return PUBLIC_MOTOR_COLORS.magnetSouth;
    if (winding || /winding/i.test(regionType)) return PUBLIC_MOTOR_COLORS.winding;
  }
  if (winding && (layer === 'windings' || layer === 'phases')) {
    return phaseFill(winding.phase, layer, phaseLevels);
  }
  return sourceFill || regionColor(regionType);
}

function drawGeometry(
  context: CanvasRenderingContext2D,
  data: GeometryPreview,
  width: number,
  height: number,
  layer: PublicCanvasLayer,
  rotorAngleDeg: number,
  windingType: 'concentrated' | 'distributed',
  hitRegions: HitRegion[],
  selectedComponent: PublicMotorComponentSelection | null,
  hoveredComponent: PublicMotorComponentSelection | null,
  highlightComponentKind: PublicMotorComponentKind | null,
  viewportScale: number,
  pan: [number, number],
  /** The sector turntable's rotation about the motor centre, clockwise on screen. */
  rotationRad: number,
  annotations: DimensionAnnotation[],
  activeDimension: DimensionId | null,
  hoveredDimension: DimensionId | null,
  dimensionHits: DimensionHit[],
  magnetPolarityView: PublicMagnetPolarityView,
  phaseDrive: PhaseDrive | null,
  showToothPoles: boolean,
  previewRpm: number,
  plainWinding = false,
  overlays: PublicCanvasOverlays = NO_CANVAS_OVERLAYS,
): void {
  const points = data.regions.flatMap((region) => region.points);
  if (points.length === 0) return;
  // Phases: the motor moves right, a little smaller, to make room for the A / B / C
  // waveforms wired into it, and its phases light with the currents they carry.
  const driveFrame = layer === 'phases' && phaseDrive ? phaseDriveFrame(width, height) : null;
  if (driveFrame) {
    // The small 3D view sits over the canvas's bottom-left corner: the waveforms move up to clear it.
    const canvasBox = context.canvas.getBoundingClientRect?.();
    const insetBox = context.canvas.ownerDocument?.querySelector('.public-viewport-3d-inset')?.getBoundingClientRect();
    const covered = canvasBox && insetBox && insetBox.right > canvasBox.left + driveFrame.panel.x
      ? Math.max(0, canvasBox.bottom - insetBox.top)
      : 0;
    driveFrame.panel.y = phasePanelTop(driveFrame.panel, height, covered);
  }
  const rotorElecDeg = phaseDrive ? rotorElectricalDeg(rotorAngleDeg, phaseDrive.poleCount) : 0;
  const currents = (layer === 'phases' || showToothPoles) && phaseDrive ? phaseCurrents(phaseDrive, rotorElecDeg) : null;
  // Phases keeps each coil at its full, steady colour: the waveforms, the wires and
  // the ⊙ / ⊗ marks carry the change, and coils pulsing as well were too much to follow.
  const phaseLevels: PhaseLevels | null = null;
  // Tooth poles, with or without Phases: each stator tooth turns N or S with the
  // slot currents either side of it.
  const statorSlotCount = Number(data.metadata.slot_count || 0);
  const poleByTooth = showToothPoles && currents && data.winding_layout?.length && statorSlotCount > 0
    ? toothPoles(slotCurrents(data.winding_layout, statorSlotCount, currents), data.metadata.rotor_layout === 'outer' ? 'outward' : 'inward')
    : null;
  const toothPoleLabels: Array<{ x: number; y: number; north: boolean; strength: number; size: number }> = [];
  const magnetPoleLabels: MagnetPoleLabel[] = [];
  const { map, scale } = fitTransform(points, width, height, viewportScale, pan, driveFrame?.motor, rotationRad);
  const slotCount = Number(data.metadata.slot_count || 0);
  // Slots draw as the backend lays them out (#91): a single-layer tooth-coil slot
  // holds one coil side, a two-layer one arrives as two side-by-side regions,
  // each with its own phase and the backend's ⊙/⊗ marker.
  const concentratedWinding = windingType === 'concentrated' && slotCount >= 3;
  const origin = map([0, 0]);
  const [, boundingRadiusMm] = radialExtentMm(points);
  const outerRadiusPx = Math.max(1, (Number(data.metadata.stator_od_mm || 0) / 2 || boundingRadiusMm) * scale);
  const pendingMarkers: Array<{ x: number; y: number; radius: number; outOfPage: boolean; ring: string }> = [];
  interface ComponentPath {
    points: Array<[number, number]>;
    loops?: Contour[];
    annulus?: {
      center: [number, number];
      innerRadiusPx: number;
      outerRadiusPx: number;
    };
  }
  const selectedPaths: ComponentPath[] = [];
  const hoveredPaths: ComponentPath[] = [];
  const editedPaths: ComponentPath[] = [];
  const trackComponentPath = (
    selection: PublicMotorComponentSelection,
    canvasPoints: Array<[number, number]>,
    annulus?: ComponentPath['annulus'],
    loops?: Contour[],
  ) => {
    const componentPath = { points: canvasPoints, annulus, loops };
    if (selectedComponent?.id === selection.id) selectedPaths.push(componentPath);
    if (hoveredComponent?.id === selection.id && selectedComponent?.id !== selection.id) {
      hoveredPaths.push(componentPath);
    }
    if (highlightComponentKind === selection.kind) editedPaths.push(componentPath);
  };

  // Grounding shadow beneath the whole cross-section, echoing the 3D scene.
  const groundShadow = context.createRadialGradient(
    origin[0] + outerRadiusPx * 0.04,
    origin[1] + outerRadiusPx * 0.09,
    outerRadiusPx * 0.82,
    origin[0] + outerRadiusPx * 0.04,
    origin[1] + outerRadiusPx * 0.09,
    outerRadiusPx * 1.2,
  );
  groundShadow.addColorStop(0, 'rgba(0, 0, 0, 0.5)');
  groundShadow.addColorStop(1, 'rgba(0, 0, 0, 0)');
  context.fillStyle = groundShadow;
  context.beginPath();
  context.arc(origin[0] + outerRadiusPx * 0.04, origin[1] + outerRadiusPx * 0.09, outerRadiusPx * 1.2, 0, Math.PI * 2);
  context.fill();

  context.lineJoin = 'round';
  // Coil-side marks: ⊙ for current out of the page, ⊗ into it, drawn as rings at
  // the preview glyphs' places and sizes (its two-bar ⊗ became two squares on
  // small motors; one ring per side here). With Phases each mark shows the way its
  // current flows now, so a phase driven negative turns all its marks round and a
  // switched-off phase shows none; otherwise it shows the winding's own sense.
  let lastCross: { phase: string; x: number; y: number; marker: number | null } | null = null;
  const coilSideMark = (region: (typeof data.regions)[number]): boolean => {
    if (region.region_type !== 'winding_symbol' || layer === 'materials') return false;
    const side = windingSymbolSide(region.label);
    if (!side) return false;
    const corners = region.points.slice(0, -1);
    const [cx, cy] = corners.reduce<[number, number]>(
      (sum, [x, y]) => [sum[0] + x / corners.length, sum[1] + y / corners.length],
      [0, 0],
    );
    const radiusMm = Math.max(...corners.map(([x, y]) => Math.hypot(x - cx, y - cy)));
    if (side.direction === 'out' && lastCross?.phase === side.phase && Math.hypot(cx - lastCross.x, cy - lastCross.y) < radiusMm) {
      // The ⊗'s second bar: centre the mark between the two.
      if (lastCross.marker !== null) {
        const [x, y] = map([(cx + lastCross.x) / 2, (cy + lastCross.y) / 2]);
        Object.assign(pendingMarkers[lastCross.marker], { x, y });
      }
      lastCross = null;
      return true;
    }
    const live = layer === 'phases' && currents !== null;
    const outOfPage = live
      ? coilSideOutOfPage(side.direction, currents[{ A: 0, B: 1, C: 2 }[side.phase]])
      : side.direction === 'in';
    let marker: number | null = null;
    if (outOfPage !== null) {
      const [x, y] = map([cx, cy]);
      const ring = (layer === 'phases' && !plainWinding) || layer === 'windings' ? PHASE_COLORS[side.phase] : 'rgba(226, 232, 240, 0.8)';
      marker = pendingMarkers.push({ x, y, radius: Math.max(3, radiusMm * scale * 1.1), outOfPage, ring }) - 1;
    }
    lastCross = side.direction === 'out' ? { phase: side.phase, x: cx, y: cy, marker } : null;
    return true;
  };
  data.regions.forEach((region, regionIndex) => {
    if (region.points.length < 2) return;
    if (coilSideMark(region)) return;
    const slotNumber = slotNumberFromRegion(region.region_type);
    const [innerRadiusMm, outerRadiusMm] = radialExtentMm(region.points);
    if (/^airgap$/i.test(region.region_type)) {
      // The airgap reads as a glowing clearance ring, like the 3D torus cue.
      const midRadiusPx = ((innerRadiusMm + outerRadiusMm) / 2) * scale;
      const bandPx = Math.max(1.2, (outerRadiusMm - innerRadiusMm) * scale);
      context.save();
      context.beginPath();
      context.arc(origin[0], origin[1], midRadiusPx, 0, Math.PI * 2);
      context.strokeStyle = 'rgba(94, 231, 247, 0.16)';
      context.lineWidth = bandPx;
      context.stroke();
      context.strokeStyle = 'rgba(94, 231, 247, 0.55)';
      context.lineWidth = Math.max(0.8, bandPx * 0.2);
      context.shadowColor = 'rgba(94, 231, 247, 0.7)';
      context.shadowBlur = bandPx * 1.8;
      context.stroke();
      context.restore();
      const airgapSelection = componentSelectionFromRegion(region.region_type, regionIndex);
      if (airgapSelection) {
        const airgapPoints = region.points.map(map);
        hitRegions.push({ points: airgapPoints, selection: airgapSelection });
        trackComponentPath(airgapSelection, airgapPoints, {
          center: origin,
          innerRadiusPx: innerRadiusMm * scale,
          outerRadiusPx: outerRadiusMm * scale,
        });
      }
      return;
    }
    const transformedPoints = isRotorRegion(region.region_type)
      ? region.points.map((point) => rotatePoint(point, -rotorAngleDeg))
      : region.points;
    const isSpmMagnet = String(data.metadata.topology || '').toUpperCase() === 'SPM'
      && /magnet/i.test(region.region_type);
    const isVShapeMagnet = data.metadata.ipm_topology === 'v_shape'
      && /magnet/i.test(region.region_type);
    const usesSplitPolarity = magnetPolarityView === 'split'
      && (isSpmMagnet || isVShapeMagnet);
    const canvasPoints = transformedPoints.map(map);
    const canvasLoops = previewContours(region).map((loop) => loop.map((point) => map(
      isRotorRegion(region.region_type) ? rotatePoint(point, -rotorAngleDeg) : point,
    )));
    context.beginPath();
    for (const loop of canvasLoops) {
      if (!loop.length) continue;
      context.moveTo(...loop[0]);
      for (const [x, y] of loop.slice(1)) context.lineTo(x, y);
      context.closePath();
    }
    context.fillStyle = shadedRegionFill(
      context,
      region.region_type,
      usesSplitPolarity
        ? PUBLIC_MOTOR_COLORS.magnetBody
        : regionFill(region.region_type, region.fill, layer, phaseLevels, plainWinding),
      origin,
      /shaft/i.test(region.region_type) ? 0 : innerRadiusMm * scale,
      outerRadiusMm * scale,
    );
    context.globalAlpha = /air/i.test(region.region_type) ? 0.45 : 0.94;
    context.fill('evenodd');
    context.globalAlpha = 1;
    if (poleByTooth && /stator_tooth/i.test(region.region_type)) {
      // The tooth as an electromagnet pole: red N, blue S, as the magnets are, and
      // as strong as its share of the stator MMF.
      const [meanX, meanY] = region.points.reduce<[number, number]>(
        (sum, [x, y]) => [sum[0] + x / region.points.length, sum[1] + y / region.points.length],
        [0, 0],
      );
      const strength = poleByTooth[toothIndexAt(Math.atan2(meanY, meanX), statorSlotCount)] ?? 0;
      if (Math.abs(strength) > 0.06) {
        context.fillStyle = strength > 0 ? PUBLIC_MOTOR_COLORS.magnetNorth : PUBLIC_MOTOR_COLORS.magnetSouth;
        context.globalAlpha = 0.14 + 0.5 * Math.abs(strength);
        context.fill();
        context.globalAlpha = 1;
        const [labelX, labelY] = map([meanX, meanY]);
        const toothWidthPx = (2 * Math.PI * Math.hypot(labelX - origin[0], labelY - origin[1])) / statorSlotCount * 0.42;
        toothPoleLabels.push({ x: labelX, y: labelY, north: strength > 0, strength: Math.abs(strength), size: Math.min(14, toothWidthPx * 0.55) });
      }
    }
    let splitHalves: MagnetPoleLabel[] | null = null;
    if (isVShapeMagnet && usesSplitPolarity) {
      splitHalves = drawVShapeMagnetPolarityHalves(
        context,
        transformedPoints,
        map,
        region.region_type,
      );
    } else if (isSpmMagnet && usesSplitPolarity) {
      splitHalves = drawSpmMagnetPolarityHalves(
        context,
        transformedPoints,
        map,
        region.region_type,
      );
    }
    if (/magnet/i.test(region.region_type)) {
      // Every magnet says which pole faces the airgap; split, each half its own.
      magnetPoleLabels.push({ points: canvasPoints, north: magnetAirgapPolarity(region.region_type) === 'north', halves: splitHalves });
    }
    context.strokeStyle = 'rgba(6, 8, 12, 0.68)';
    context.lineWidth = Math.max(0.7, Math.min(1.5, scale * 0.035));
    if (ANNULAR_REGIONS.test(region.region_type) && !region.loops?.length) {
      // Concentric boundaries: stroke true circles so the polygon's radial
      // closing seam never shows.
      context.beginPath();
      context.arc(origin[0], origin[1], outerRadiusMm * scale, 0, Math.PI * 2);
      if (innerRadiusMm > 0.5 && innerRadiusMm < outerRadiusMm * 0.94) {
        context.moveTo(origin[0] + innerRadiusMm * scale, origin[1]);
        context.arc(origin[0], origin[1], innerRadiusMm * scale, 0, Math.PI * 2);
      }
      context.stroke();
      if (/stator_yoke/i.test(region.region_type)) {
        context.save();
        context.strokeStyle = 'rgba(255, 255, 255, 0.24)';
        context.lineWidth = Math.max(1, scale * 0.02);
        context.beginPath();
        context.arc(origin[0], origin[1], outerRadiusMm * scale - context.lineWidth, Math.PI * 0.82, Math.PI * 1.62);
        context.stroke();
        context.restore();
      }
    } else {
      context.stroke();
    }
    let selection = componentSelectionFromRegion(region.region_type, regionIndex);
    if (selection && concentratedWinding && selection.kind === 'winding' && slotNumber !== null) {
      selection = {
        ...selection,
        label: `Slot ${slotNumber} coil side`,
        role: 'One side of a concentrated coil wound around an adjacent tooth',
      };
    }
    if (selection) hitRegions.push({ points: canvasPoints, loops: canvasLoops, selection });
    if (selection) {
      trackComponentPath(
        selection,
        canvasPoints,
        ANNULAR_REGIONS.test(region.region_type) && !region.loops?.length
          ? {
            center: origin,
            innerRadiusPx: innerRadiusMm * scale,
            outerRadiusPx: outerRadiusMm * scale,
          }
          : undefined,
        canvasLoops,
      );
    }
  });

  // Directional sheen over the whole cross-section — the 2D cousin of the
  // 3D scene's key and rim lights.
  context.save();
  context.beginPath();
  context.arc(origin[0], origin[1], outerRadiusPx + 1, 0, Math.PI * 2);
  context.clip();
  const sheen = context.createLinearGradient(
    origin[0] - outerRadiusPx,
    origin[1] - outerRadiusPx,
    origin[0] + outerRadiusPx,
    origin[1] + outerRadiusPx,
  );
  sheen.addColorStop(0, 'rgba(255, 255, 255, 0.2)');
  sheen.addColorStop(0.48, 'rgba(255, 255, 255, 0)');
  sheen.addColorStop(1, 'rgba(3, 7, 15, 0.34)');
  context.globalCompositeOperation = 'soft-light';
  context.fillStyle = sheen;
  context.fillRect(
    origin[0] - outerRadiusPx - 1,
    origin[1] - outerRadiusPx - 1,
    outerRadiusPx * 2 + 2,
    outerRadiusPx * 2 + 2,
  );
  context.restore();

  pendingMarkers.forEach((marker) => {
    drawCurrentMarker(context, marker.x, marker.y, marker.radius, marker.outOfPage, marker.ring);
  });

  // N / S on every magnet, upright. A thin SPM magnet is narrower than a readable
  // letter, so the letter may overhang its band (outlined to stay legible); only a
  // magnet too short for it goes unlabelled.
  if (magnetPoleLabels.length) {
    context.save();
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.lineJoin = 'round';
    const letter = (north: boolean, x: number, y: number, size: number) => {
      context.font = `800 ${size.toFixed(1)}px ui-monospace, monospace`;
      context.lineWidth = Math.max(2, size * 0.24);
      context.strokeStyle = 'rgba(8, 10, 14, 0.5)';
      context.strokeText(north ? 'N' : 'S', x, y + 0.5);
      context.fillStyle = '#f8fafc';
      context.fillText(north ? 'N' : 'S', x, y + 0.5);
    };
    for (const label of magnetPoleLabels) {
      // Split: each half its own letter, but only where both fit inside their
      // halves; two letters overhanging a thin band would run into each other.
      const halfSpots = (label.halves ?? []).map((half) => ({ half, spot: polygonLabelSpot(half.points, origin) }));
      const halvesFit = halfSpots.length === 2
        && halfSpots.every(({ spot }) => spot.thickness * 0.85 >= 8 && spot.span >= spot.thickness * 0.85 * 1.6);
      if (halvesFit) {
        halfSpots.forEach(({ half, spot }) => letter(half.north, spot.x, spot.y, Math.min(14, spot.thickness * 0.85)));
        continue;
      }
      // Otherwise the pole facing the airgap, as the Pole view colours it.
      const spot = polygonLabelSpot(label.points, origin);
      const size = Math.min(14, Math.max(9, spot.thickness * 0.8));
      if (spot.span < size * 1.6) continue;
      letter(label.north, spot.x, spot.y, size);
    }
    context.restore();
  }

  // N / S on the teeth that are clearly poles, where a letter fits.
  if (toothPoleLabels.length) {
    context.save();
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    for (const label of toothPoleLabels) {
      if (label.size < 8 || label.strength < 0.3) continue;
      context.font = `800 ${label.size.toFixed(1)}px ui-monospace, monospace`;
      context.fillStyle = `rgba(248, 250, 252, ${(0.45 + 0.55 * label.strength).toFixed(2)})`;
      context.fillText(label.north ? 'N' : 'S', label.x, label.y + 0.5);
    }
    context.restore();
  }

  // Slots and Winding are labels only, each on or off by itself; the coil
  // colours have their own toggle. With both on, the slot numbers go down first
  // and the winding labels step clear of them.
  const badgeKinds = (['slots', 'windings'] as const).filter((kind) => overlays[kind]);
  const placed: Array<[number, number]> = [];
  for (const badgeKind of badgeKinds) {
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    // The badges sit on the yoke just behind each slot, clear of the ⊙ / ⊗
    // marks drawn inside it. The yoke is outside the slots on an inner-rotor
    // machine and inside them on an outer-rotor one.
    const badgeRadius = badgeKind === 'slots' ? 10 : 12;
    const yokeInside = data.metadata.rotor_layout === 'outer';
    const [originX, originY] = map([0, 0]);
    const [unitX, unitY] = map([1, 0]);
    const pixelsPerMm = Math.max(1e-6, Math.hypot(unitX - originX, unitY - originY));
    const slotRegions = data.regions.filter((region) => /slot_(\d+)/i.test(region.region_type) && region.points.length > 0);
    const slotRadii = slotRegions.flatMap((region) => region.points.map(([px, py]) => Math.hypot(px, py)));
    const slotBackMm = slotRadii.length ? (yokeInside ? Math.min(...slotRadii) : Math.max(...slotRadii)) : 0;
    const slotFrontMm = slotRadii.length ? (yokeInside ? Math.max(...slotRadii) : Math.min(...slotRadii)) : 0;
    const badgeStepMm = (badgeRadius + 4) / pixelsPerMm;
    // Slots numbers each slot once, however many coil sides it holds; Winding
    // labels every coil side.
    const badges = new Map<string, { sumX: number; sumY: number; count: number; slot: string; region: (typeof slotRegions)[number] }>();
    slotRegions.forEach((region, index) => {
      const slot = region.region_type.match(/slot_(\d+)/i)?.[1];
      if (!slot) return;
      const center = region.points.reduce<[number, number]>(
        (current, point) => [current[0] + point[0], current[1] + point[1]],
        [0, 0],
      ).map((value) => value / region.points.length) as [number, number];
      const key = badgeKind === 'slots' ? slot : `${slot}:${index}`;
      const badge = badges.get(key) ?? { sumX: 0, sumY: 0, count: 0, slot, region };
      badge.sumX += center[0];
      badge.sumY += center[1];
      badge.count += 1;
      badges.set(key, badge);
    });
    // A small yoke (the inside of an outer-rotor stator) has no room for a ring of
    // badges: they would pile onto each other. There each badge sits in its own
    // coil side instead, between the ⊙ / ⊗ mark and the slot opening, where the
    // slot is widest.
    const yokeRadiusMm = slotBackMm + (yokeInside ? -badgeStepMm : badgeStepMm);
    const badgeAngles = [...badges.values()].map(({ sumX, sumY }) => Math.atan2(sumY, sumX)).sort((a, b) => a - b);
    const closestGapRad = badgeAngles.reduce((closest, angle, index) => {
      const next = index + 1 < badgeAngles.length ? badgeAngles[index + 1] : badgeAngles[0] + Math.PI * 2;
      return Math.min(closest, next - angle);
    }, Math.PI * 2);
    const yokeCrowded = badgeAngles.length > 1
      && Math.max(0, yokeRadiusMm) * pixelsPerMm * closestGapRad < badgeRadius * 2 + 2;
    for (const { sumX, sumY, count, slot, region } of badges.values()) {
      const slotMatch = [slot, slot];
      const angle = Math.atan2(sumY, sumX);
      const centroidMm = Math.hypot(sumX, sumY) / Math.max(1, count);
      // Two coil sides stacked in one slot share an angle: the second badge
      // steps further back rather than landing on the first.
      // Inside the slot, with both kinds on, the slot number takes the back of the slot and the winding label the front.
      const inSlotMm = badgeKind === 'slots' && badgeKinds.length > 1
        ? centroidMm + (slotBackMm - centroidMm) * 0.6
        : centroidMm + (slotFrontMm - centroidMm) * 0.55;
      let radiusMm = yokeCrowded ? inSlotMm : yokeRadiusMm;
      let [x, y] = map([Math.cos(angle) * radiusMm, Math.sin(angle) * radiusMm]);
      for (let attempt = 0; !yokeCrowded && attempt < 3 && placed.some(([px, py]) => Math.hypot(px - x, py - y) < badgeRadius * 2); attempt += 1) {
        radiusMm += (yokeInside ? -1 : 1) * (badgeRadius * 2 + 2) / pixelsPerMm;
        [x, y] = map([Math.cos(angle) * radiusMm, Math.sin(angle) * radiusMm]);
      }
      placed.push([x, y]);
      const winding = windingToken(region.region_type);
      const label = badgeKind === 'slots' ? slotMatch[1] : winding ? `${winding.phase}${winding.direction}` : slotMatch[1];
      context.beginPath();
      context.arc(x, y, badgeRadius, 0, Math.PI * 2);
      context.fillStyle = 'rgba(8, 10, 14, 0.78)';
      context.fill();
      context.strokeStyle = winding ? PHASE_COLORS[winding.phase] : 'rgba(255,255,255,.34)';
      context.lineWidth = 1.2;
      context.stroke();
      context.fillStyle = '#f8fafc';
      context.font = `700 ${badgeKind === 'slots' ? 9 : 10}px ui-monospace, monospace`;
      context.fillText(label, x, y + 0.5);
    }
  }

  if (overlays.teeth) {
    // Tooth k stands between slot k and slot k + 1, as the tooth poles count them.
    // Its number sits toward the yoke, clear of the N / S letter at the tooth's middle.
    const slotAngles = new Map<number, { x: number; y: number }>();
    for (const region of data.regions) {
      const slot = Number(region.region_type.match(/slot_(\d+)/i)?.[1]);
      if (!slot || region.points.length === 0) continue;
      const sum = slotAngles.get(slot) ?? { x: 0, y: 0 };
      for (const [px, py] of region.points) { sum.x += px; sum.y += py; }
      slotAngles.set(slot, sum);
    }
    const slotTotal = Math.max(0, ...slotAngles.keys());
    const turn = (angle: number) => ((angle % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
    const yokeInside = data.metadata.rotor_layout === 'outer';
    context.save();
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    for (const region of data.regions) {
      if (!/stator_tooth/i.test(region.region_type) || region.points.length < 3) continue;
      const [meanX, meanY] = region.points.reduce<[number, number]>(
        (sum, [px, py]) => [sum[0] + px / region.points.length, sum[1] + py / region.points.length],
        [0, 0],
      );
      const toothAngle = Math.atan2(meanY, meanX);
      // The slot just behind the tooth, going the way the slots count up.
      let number = 0;
      let nearest = Infinity;
      for (const [slot, sum] of slotAngles) {
        const next = slotAngles.get(slot === slotTotal ? 1 : slot + 1);
        if (!next) continue;
        const from = Math.atan2(sum.y, sum.x);
        const span = turn(Math.atan2(next.y, next.x) - from);
        const forward = span <= Math.PI;
        const offset = forward ? turn(toothAngle - from) : turn(from - toothAngle);
        const width = forward ? span : Math.PI * 2 - span;
        if (offset <= width && offset < nearest) { nearest = offset; number = slot; }
      }
      if (!number) continue;
      const [innerMm, outerMm] = radialExtentMm(region.points);
      const backMm = yokeInside ? innerMm : outerMm;
      const centreMm = Math.hypot(meanX, meanY);
      const radiusMm = centreMm + (backMm - centreMm) * 0.6;
      const [x, y] = map([Math.cos(toothAngle) * radiusMm, Math.sin(toothAngle) * radiusMm]);
      const text = `T${number}`;
      context.font = '700 9px ui-monospace, monospace';
      const half = Math.max(9, context.measureText(text).width / 2 + 4);
      context.beginPath();
      context.roundRect(x - half, y - 8, half * 2, 16, 4);
      context.fillStyle = 'rgba(8, 10, 14, 0.78)';
      context.fill();
      context.strokeStyle = 'rgba(255,255,255,.34)';
      context.lineWidth = 1.2;
      context.stroke();
      context.fillStyle = '#f8fafc';
      context.fillText(text, x, y + 0.5);
    }
    context.restore();
  }

  const addComponentPath = (path: Path2D, componentPath: ComponentPath) => {
    if (componentPath.loops) {
      for (const loop of componentPath.loops) {
        if (!loop.length) continue;
        path.moveTo(...loop[0]);
        for (const [x, y] of loop.slice(1)) path.lineTo(x, y);
        path.closePath();
      }
      return;
    }
    if (componentPath.annulus) {
      const { center, innerRadiusPx, outerRadiusPx: componentOuterRadiusPx } = componentPath.annulus;
      path.moveTo(center[0] + componentOuterRadiusPx, center[1]);
      path.arc(center[0], center[1], componentOuterRadiusPx, 0, Math.PI * 2);
      if (innerRadiusPx > 0.5) {
        path.moveTo(center[0] + innerRadiusPx, center[1]);
        path.arc(center[0], center[1], innerRadiusPx, 0, Math.PI * 2);
      }
      return;
    }
    if (componentPath.points.length < 2) return;
    path.moveTo(componentPath.points[0][0], componentPath.points[0][1]);
    for (const [x, y] of componentPath.points.slice(1)) path.lineTo(x, y);
    path.closePath();
  };
  const strokeComponentPaths = (
    paths: ComponentPath[],
    color: string,
    widthPx: number,
    shadowColor: string,
    shadowBlur: number,
  ) => {
    if (paths.length === 0) return;
    context.save();
    context.strokeStyle = color;
    context.lineWidth = widthPx;
    context.lineJoin = 'round';
    context.shadowColor = shadowColor;
    context.shadowBlur = shadowBlur;
    for (const componentPath of paths) {
      const path = new Path2D();
      addComponentPath(path, componentPath);
      context.stroke(path);
    }
    context.restore();
  };

  if (selectedPaths.length > 0) {
    // A committed selection lowers the surrounding motor without muting the
    // selected region itself. This keeps the engineering colour of the part
    // visible while making the cyan selection cue unambiguous.
    const focusMask = new Path2D();
    focusMask.rect(0, 0, width, height);
    selectedPaths.forEach((componentPath) => addComponentPath(focusMask, componentPath));
    context.save();
    context.fillStyle = 'rgba(2, 5, 10, 0.22)';
    context.fill(focusMask, 'evenodd');
    context.restore();
  }

  strokeComponentPaths(
    editedPaths,
    'rgba(251, 191, 36, 0.92)',
    2.2,
    'rgba(245, 158, 11, 0.72)',
    14,
  );
  strokeComponentPaths(
    hoveredPaths,
    'rgba(34, 211, 238, 0.72)',
    2,
    'rgba(34, 211, 238, 0.5)',
    8,
  );
  strokeComponentPaths(
    selectedPaths,
    '#22d3ee',
    3.2,
    'rgba(34, 211, 238, 0.9)',
    14,
  );

  if (overlays.dimensions) {
    drawDimensionAnnotations(
      context,
      map,
      annotations,
      activeDimension,
      hoveredDimension,
      dimensionHits,
    );
  }

  if (driveFrame && phaseDrive && currents) {
    drawPhaseDrive(context, driveFrame.panel, phaseDrive, rotorElecDeg, currents, origin, outerRadiusPx, previewRpm);
  }
  drawRotorZeroMark(context, origin, Math.max(outerRadiusPx, boundingRadiusMm * scale), rotorAngleDeg, rotationRad);
}

/**
 * Where the rotor is: a tick fixed at 0° just outside the motor, and a dot that
 * starts on it and goes round with the rotor.
 */
function drawRotorZeroMark(
  context: CanvasRenderingContext2D,
  origin: [number, number],
  motorRadiusPx: number,
  rotorAngleDeg: number,
  /** The view's own rotation (the sector turntable), clockwise on screen. */
  viewRotationRad: number,
): void {
  const at = (radius: number, angleRad: number): [number, number] => [
    origin[0] + radius * Math.cos(angleRad),
    origin[1] + radius * Math.sin(angleRad),
  ];
  const zero = viewRotationRad;
  // The rotor turns clockwise on screen as its angle grows, as the drawing does.
  const rotor = viewRotationRad + (rotorAngleDeg * Math.PI) / 180;
  context.save();
  const [tickFromX, tickFromY] = at(motorRadiusPx + 5, zero);
  const [tickToX, tickToY] = at(motorRadiusPx + 19, zero);
  context.beginPath();
  context.moveTo(tickFromX, tickFromY);
  context.lineTo(tickToX, tickToY);
  context.strokeStyle = 'rgba(148, 163, 184, 0.7)';
  context.lineWidth = 1.5;
  context.lineCap = 'round';
  context.stroke();
  const [dotX, dotY] = at(motorRadiusPx + 12, rotor);
  context.beginPath();
  context.arc(dotX, dotY, 4, 0, Math.PI * 2);
  context.fillStyle = '#fbbf24';
  context.shadowColor = 'rgba(251, 191, 36, 0.8)';
  context.shadowBlur = 6;
  context.fill();
  context.shadowBlur = 0;
  context.strokeStyle = 'rgba(8, 10, 14, 0.9)';
  context.lineWidth = 1;
  context.stroke();
  context.restore();
}

/**
 * Phases: the A / B / C terminal currents as scrolling waveforms on the left (now
 * at the right end), each wired to its lead out of the motor at nine o'clock. A
 * wire is as bright and thick as its phase's current, so the phase six-step
 * switches off goes dark with its slots.
 */
function drawPhaseDrive(
  context: CanvasRenderingContext2D,
  panel: Rect,
  drive: PhaseDrive,
  rotorElecDeg: number,
  currents: [number, number, number],
  origin: [number, number],
  statorRadiusPx: number,
  previewRpm: number,
): void {
  const strips = phaseStrips(panel);
  // Drawn like a schematic: each wire runs level out of its strip, turns once through
  // a right angle, and from its terminal dot goes level into the motor. A enters
  // above the centre and C below. The turns are staggered so that no wire crosses
  // another: whichever way the wires have to drop, the one that drops furthest turns last.
  const stripRight = panel.x + panel.width;
  const entryStep = statorRadiusPx * Math.sin((16 * Math.PI) / 180);
  const motorLeft = origin[0] - statorRadiusPx;
  const lane = Math.max(6, Math.min(16, (motorLeft - stripRight) / 5));
  const wiresDrop = strips[1].y + strips[1].height / 2 <= origin[1];
  const leads = [-1, 0, 1].map((side, index) => {
    const y = origin[1] + side * entryStep;
    const turn = motorLeft - lane * (wiresDrop ? index + 1 : 3 - index);
    return {
      motor: [origin[0] - Math.sqrt(Math.max(0, statorRadiusPx ** 2 - (side * entryStep) ** 2)), y] as [number, number],
      terminal: [turn, y] as [number, number],
    };
  });

  drawPhaseDriveWired(context, panel, drive, rotorElecDeg, currents, leads, previewRpm);
}

/**
 * The Dims layer's lines. Every annotation is drawn faint so the whole set reads as
 * one measured drawing, and the selected one is drawn bright — clicking a line and
 * clicking its row in the readout are the same act, which is why the hit segments
 * are collected here in canvas space rather than recomputed on click.
 */
function drawDimensionAnnotations(
  context: CanvasRenderingContext2D,
  map: (point: [number, number]) => [number, number],
  annotations: DimensionAnnotation[],
  activeDimension: DimensionId | null,
  hoveredDimension: DimensionId | null,
  dimensionHits: DimensionHit[],
): void {
  const TICK = 5;
  // A pick shows that dimension and only that dimension. With nothing picked the
  // two orienting diameters rest on screen, so the layer is never blank.
  const picked = activeDimension ?? hoveredDimension;
  const shown = picked ? [picked] : RESTING_DIMENSIONS;
  context.save();
  context.lineCap = 'butt';

  for (const annotation of annotations) {
    if (!shown.includes(annotation.id)) continue;
    const isPicked = annotation.id === picked;
    // Hover is a preview, so it reads a step below a click.
    context.strokeStyle = isPicked
      ? (activeDimension ? 'rgba(251, 191, 36, 0.98)' : 'rgba(251, 191, 36, 0.75)')
      : 'rgba(245, 158, 11, 0.5)';
    context.lineWidth = isPicked ? 1.8 : 1;

    for (const shape of annotation.shapes) {
      if (shape.kind === 'segment') {
        const from = map(shape.from);
        const to = map(shape.to);
        context.setLineDash(annotation.dash);
        context.beginPath();
        context.moveTo(from[0], from[1]);
        context.lineTo(to[0], to[1]);
        context.stroke();
        context.setLineDash([]);
        // Ticks perpendicular to the span, so short spans stay findable.
        const dx = to[0] - from[0];
        const dy = to[1] - from[1];
        const length = Math.hypot(dx, dy) || 1;
        const nx = (-dy / length) * TICK;
        const ny = (dx / length) * TICK;
        context.beginPath();
        for (const end of [from, to]) {
          context.moveTo(end[0] - nx, end[1] - ny);
          context.lineTo(end[0] + nx, end[1] + ny);
        }
        context.stroke();
        dimensionHits.push({ id: annotation.id, from, to });
      } else {
        // Arcs are sampled rather than using context.arc: map() may flip y, and a
        // sampled polyline gives the hit test the same points that were drawn.
        const steps = 28;
        const points: Array<[number, number]> = [];
        for (let i = 0; i <= steps; i += 1) {
          const angle = shape.startRad + ((shape.endRad - shape.startRad) * i) / steps;
          points.push(map([
            shape.radiusMm * Math.cos(angle),
            shape.radiusMm * Math.sin(angle),
          ]));
        }
        context.setLineDash(annotation.dash);
        context.beginPath();
        points.forEach(([x, y], index) => (index ? context.lineTo(x, y) : context.moveTo(x, y)));
        context.stroke();
        context.setLineDash([]);
        for (let i = 0; i < points.length - 1; i += 1) {
          dimensionHits.push({ id: annotation.id, from: points[i], to: points[i + 1] });
        }
      }
    }
  }

  context.restore();
}

function drawMesh(
  context: CanvasRenderingContext2D,
  data: MeshPreview,
  width: number,
  height: number,
  rotorAngleDeg: number,
  viewportScale: number,
  pan: [number, number],
  /** The sector turntable's rotation about the motor centre, clockwise on screen. */
  rotationRad: number,
  displayMode: PublicMeshDisplayMode,
  showEdges: boolean,
  qualities: number[],
  qualityThreshold: number,
  focusedElementIndex: number | null,
  meshHits: MeshTriangleHit[],
  /** Replaces the usual grey of the element edges (the Solve page's field-solve glow). */
  edgeColor: string | null,
  options: MeshDrawOptions = {},
): MeshDrawFrame | null {
  if (data.nodes_mm.length === 0 || data.triangles.length === 0) return null;
  const { map } = fitTransform(data.nodes_mm, width, height, viewportScale, pan, undefined, rotationRad);
  const part = options.part ?? 'all';
  const fillRegions = options.fill ?? true;
  const cull = options.cull ?? null;
  const coilPhases = options.coilPhases ?? null;
  // Elements left out of this pass: the other layer's, or those outside the magnifier's window.
  const skipped = part !== 'all' || cull ? new Uint8Array(data.triangles.length) : null;
  const fillPaths = new Map<string, Path2D>();
  const qualityColors: Record<PublicMeshQualityBand, string> = {
    good: '#2a9d8f',
    acceptable: '#4c78a8',
    marginal: '#f59e0b',
    failing: '#ef4444',
  };
  const rotorAngleRad = -rotorAngleDeg * Math.PI / 180;
  const rotorCosine = Math.cos(rotorAngleRad);
  const rotorSine = Math.sin(rotorAngleRad);
  const mapMeshNode = (nodeIndex: number, rotateRotor: boolean): [number, number] => {
    const [x, y] = data.nodes_mm[nodeIndex];
    return map(rotateRotor
      ? [x * rotorCosine - y * rotorSine, x * rotorSine + y * rotorCosine]
      : [x, y]);
  };

  data.triangles.forEach((triangle, index) => {
    const region = data.regions[index] || 'mesh';
    const rotateRotor = isRotorRegion(region);
    if (skipped && part !== 'all' && rotateRotor !== (part === 'rotor')) {
      skipped[index] = 1;
      return;
    }
    // A coil side takes its phase colour, so the winding reads in the mesh too.
    const phase = coilPhases?.[index] ?? null;
    const fillKey = phase ? `${region}${MESH_FILL_KEY_SEPARATOR}${phase}` : region;
    const path = fillPaths.get(fillKey) || new Path2D();
    const a = mapMeshNode(triangle[0], rotateRotor);
    const b = mapMeshNode(triangle[1], rotateRotor);
    const c = mapMeshNode(triangle[2], rotateRotor);
    if (skipped && cull && (
      Math.max(a[0], b[0], c[0]) < cull[0] || Math.min(a[0], b[0], c[0]) > cull[2]
      || Math.max(a[1], b[1], c[1]) < cull[1] || Math.min(a[1], b[1], c[1]) > cull[3]
    )) {
      skipped[index] = 1;
      return;
    }
    const quality = qualities[index] ?? 0;
    const band = publicMeshQualityBand(quality, qualityThreshold);
    meshHits.push({
      points: [a, b, c],
      selection: { index, quality, band, region },
    });
    if (displayMode === 'geometry' && !fillRegions) return;
    if (displayMode === 'geometry') {
      // An explicit closing edge, not closePath(): Chromium's closePath() cost
      // grows with the path built so far, so per-region paths of thousands of
      // triangles made every zoom and pan step take about a second.
      path.moveTo(a[0], a[1]);
      path.lineTo(b[0], b[1]);
      path.lineTo(c[0], c[1]);
      path.lineTo(a[0], a[1]);
      fillPaths.set(fillKey, path);
      return;
    }
    const weak = band === 'marginal' || band === 'failing';
    context.beginPath();
    context.moveTo(a[0], a[1]);
    context.lineTo(b[0], b[1]);
    context.lineTo(c[0], c[1]);
    context.closePath();
    context.fillStyle = displayMode === 'problems' && !weak
      ? '#202733'
      : qualityColors[band];
    context.globalAlpha = displayMode === 'problems' && !weak ? 0.13 : 0.82;
    context.fill();
  });

  if (displayMode === 'geometry') {
    for (const [fillKey, path] of fillPaths) {
      const [region, phase] = fillKey.split(MESH_FILL_KEY_SEPARATOR);
      context.fillStyle = phase ? PHASE_COLORS[phase as keyof typeof PHASE_COLORS] : regionColor(region, '#697386');
      context.globalAlpha = phase ? 0.78 : /air/i.test(region) ? 0.25 : 0.68;
      context.fill(path);
    }
  }
  context.globalAlpha = 1;

  if (showEdges) {
    const uniqueEdges = new Set<string>();
    context.beginPath();
    data.triangles.forEach((triangle, triangleIndex) => {
      if (skipped?.[triangleIndex]) return;
      const rotateRotor = isRotorRegion(data.regions[triangleIndex] || 'mesh');
      const triangleEdges: Array<[number, number]> = [
        [triangle[0], triangle[1]],
        [triangle[1], triangle[2]],
        [triangle[2], triangle[0]],
      ];
      triangleEdges.forEach(([startIndex, endIndex]) => {
        const edgeKey = startIndex < endIndex
          ? `${rotateRotor ? 'rotor' : 'fixed'}:${startIndex}:${endIndex}`
          : `${rotateRotor ? 'rotor' : 'fixed'}:${endIndex}:${startIndex}`;
        if (uniqueEdges.has(edgeKey)) return;
        uniqueEdges.add(edgeKey);
        const start = mapMeshNode(startIndex, rotateRotor);
        const end = mapMeshNode(endIndex, rotateRotor);
        context.moveTo(start[0], start[1]);
        context.lineTo(end[0], end[1]);
      });
    });
    context.strokeStyle = edgeColor ?? (displayMode === 'problems'
      ? 'rgba(226, 232, 240, 0.12)'
      : 'rgba(226, 232, 240, 0.28)');
    context.lineWidth = (edgeColor ? 0.5 : 0.4) * (options.edgeWidthScale ?? 1);
    context.stroke();
  }

  if (displayMode === 'problems') {
    for (const hit of meshHits) {
      if (hit.selection.band !== 'marginal' && hit.selection.band !== 'failing') continue;
      const centroidX = (hit.points[0][0] + hit.points[1][0] + hit.points[2][0]) / 3;
      const centroidY = (hit.points[0][1] + hit.points[1][1] + hit.points[2][1]) / 3;
      context.save();
      context.beginPath();
      context.arc(
        centroidX,
        centroidY,
        hit.selection.band === 'failing' ? 3.3 : 2.4,
        0,
        Math.PI * 2,
      );
      context.fillStyle = hit.selection.band === 'failing' ? '#ef4444' : '#f59e0b';
      context.shadowColor = context.fillStyle;
      context.shadowBlur = 6;
      context.fill();
      context.restore();
    }
  }

  if (
    focusedElementIndex !== null
    && focusedElementIndex >= 0
    && focusedElementIndex < data.triangles.length
    && !skipped?.[focusedElementIndex]
  ) {
    const triangle = data.triangles[focusedElementIndex];
    const rotateRotor = isRotorRegion(data.regions[focusedElementIndex] || 'mesh');
    const points = triangle.map((nodeIndex) => mapMeshNode(nodeIndex, rotateRotor));
    context.save();
    context.beginPath();
    context.moveTo(points[0][0], points[0][1]);
    context.lineTo(points[1][0], points[1][1]);
    context.lineTo(points[2][0], points[2][1]);
    context.closePath();
    context.strokeStyle = '#f8fafc';
    context.lineWidth = 2.2;
    context.shadowColor = '#22d3ee';
    context.shadowBlur = 10;
    context.stroke();
    context.restore();
  }
  const origin = map([0, 0]);
  const [edgeX, edgeY] = map([meshOuterRadiusMm(data), 0]);
  return { origin, radiusPx: Math.hypot(edgeX - origin[0], edgeY - origin[1]) };
}

export function MotorCanvas({
  geometry,
  mesh,
  mode,
  layer = 'dimensions',
  overlays,
  rotorAngleDeg = 0,
  windingType = 'concentrated',
  selectedComponent = null,
  highlightComponentKind = null,
  onComponentSelect,
  config,
  activeDimension = null,
  hoveredDimension = null,
  onDimensionSelect,
  magnetPolarityView = 'dominant',
  showToothPoles = false,
  previewRpm = 20,
  meshDisplayMode = 'geometry',
  showMeshEdges = true,
  meshQualities = EMPTY_MESH_QUALITIES,
  meshQualityThreshold = 0.01,
  focusedMeshElementIndex = null,
  meshEdgeColor = null,
  magnifier = false,
  plainWinding = false,
  onMeshElementHover,
  onMeshElementSelect,
  navigationSlot = null,
}: MotorCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Phases: the solve's drive settings with the geometry's phase-A axis and poles.
  const solveParams = config?.solve_params;
  const metadataAxis = Number(geometry?.metadata.phase_axis_offset_elec_deg);
  const metadataPoles = Number(geometry?.metadata.pole_count);
  const phaseDrive = useMemo<PhaseDrive | null>(() => (solveParams
    ? {
      mode: solveParams.excitation_mode,
      currentAngleDeg: solveParams.current_angle_deg,
      currentAngleReference: geometry?.metadata.phase_current_convention === 'pyleecan_d_axis'
        || publishedReference(config)?.phaseCurrentConvention === 'pyleecan_d_axis' ? 'pyleecan_d_axis' : 'q_axis',
      currentAmplitudeA: solveParams.current_amplitude_A,
      commutationAdvanceDeg: solveParams.commutation_advance_deg,
      axisOffsetDeg: Number.isFinite(metadataAxis) ? metadataAxis : 0,
      poleCount: Number.isFinite(metadataPoles) && metadataPoles > 0 ? metadataPoles : config?.rotor.pole_count ?? 2,
    }
    : null), [
    solveParams?.excitation_mode,
    solveParams?.current_angle_deg,
    solveParams?.current_amplitude_A,
    solveParams?.commutation_advance_deg,
    metadataAxis,
    metadataPoles,
    config?.rotor.pole_count,
    config?.geometry_reference,
    geometry?.metadata.phase_current_convention,
  ]);
  const hitRegionsRef = useRef<HitRegion[]>([]);
  const dimensionHitsRef = useRef<DimensionHit[]>([]);
  const meshHitsRef = useRef<MeshTriangleHit[]>([]);
  const [hoveredComponent, setHoveredComponent] = useState<PublicMotorComponentSelection | null>(null);
  const phaseFrameEnabled = mode === 'geometry' && layer === 'phases' && phaseDrive !== null;
  const navigationFrame = useCallback((width: number, height: number) => (
    phaseFrameEnabled ? phaseDriveFrame(width, height)?.motor ?? null : null
  ), [phaseFrameEnabled]);
  const ring = outerRotorRing(config);
  const ringInnerMm = ring?.innerMm;
  const ringOuterMm = ring?.outerMm;
  // fitTransform pads the motor by 7.5% of the frame's smaller side, then fits its diameter.
  const sectorForSize = useCallback((width: number, height: number) => {
    const box = navigationFrame(width, height) ?? { width, height };
    const padding = Math.min(box.width, box.height) * 0.075;
    return sectorView(
      ringInnerMm !== undefined && ringOuterMm !== undefined ? { innerMm: ringInnerMm, outerMm: ringOuterMm } : null,
      box.width,
      box.height,
      Math.min(box.width - 2 * padding, box.height - 2 * padding) / 2,
    );
  }, [navigationFrame, ringInnerMm, ringOuterMm]);
  const navigation = useViewportNavigation(undefined, navigationFrame, sectorForSize, ringKey(ring));
  // A caller that passes no overlays gets the ones its layer used to stand for.
  const overlayDimensions = overlays ? overlays.dimensions : layer === 'dimensions';
  const overlaySlots = overlays ? overlays.slots : layer === 'slots';
  const overlayTeeth = overlays ? overlays.teeth : false;
  const overlayWindings = overlays ? overlays.windings : layer === 'windings';
  const shownOverlays = useMemo<PublicCanvasOverlays>(
    () => ({ dimensions: overlayDimensions, slots: overlaySlots, teeth: overlayTeeth, windings: overlayWindings }),
    [overlayDimensions, overlaySlots, overlayTeeth, overlayWindings],
  );
  const annotations = useMemo(
    () => (config && overlayDimensions ? buildDimensionAnnotations(config, geometry) : []),
    [config, geometry, overlayDimensions],
  );

  // The mesh view can carry the Slots or Winding overlay: the geometry is drawn
  // with it, and the mesh's edges go over the top.
  // Tooth poles are drawn by the geometry too, so they bring it in on their own.
  const meshOverlay: PublicCanvasLayer | null = mode === 'mesh' && meshDisplayMode === 'geometry' && geometry
    && (overlaySlots || overlayTeeth || overlayWindings || showToothPoles)
    ? 'none'
    : null;
  // The mesh carries no dimension lines.
  const meshOverlays = useMemo<PublicCanvasOverlays>(() => ({ ...shownOverlays, dimensions: false }), [shownOverlays]);
  const drawMeshOverlayGeometry = (target: CanvasRenderingContext2D, width: number, height: number) => {
    if (!meshOverlay || !geometry) return;
    drawGeometry(
      target, geometry, width, height, meshOverlay, rotorAngleDeg, windingType, [], null, null, null,
      navigation.scale, [navigation.pan.x, navigation.pan.y], (navigation.rotationDeg * Math.PI) / 180,
      [], null, null, [], magnetPolarityView, phaseDrive, showToothPoles, previewRpm, plainWinding, meshOverlays,
    );
  };
  const meshLayersRef = useRef<{
    key: unknown[];
    fixed: HTMLCanvasElement;
    rotor: HTMLCanvasElement;
    rotorSize: number;
    frame: MeshDrawFrame | null;
    hits: MeshTriangleHit[];
  } | null>(null);
  const meshHitRotationRef = useRef<{ origin: [number, number]; angleDeg: number } | null>(null);
  // The magnifier: where the pointer is on the canvas (CSS px) and the corner its panel takes.
  const [loupePoint, setLoupePoint] = useState<{ x: number; y: number; onRight: boolean } | null>(null);
  const loupeCanvasRef = useRef<HTMLCanvasElement>(null);
  const loupeShown = magnifier && mode === 'mesh' && Boolean(mesh);
  useEffect(() => {
    if (!loupeShown) setLoupePoint(null);
  }, [loupeShown]);
  const loupeX = loupePoint?.x ?? null;
  const loupeY = loupePoint?.y ?? null;
  useEffect(() => {
    const loupe = loupeCanvasRef.current;
    const canvas = canvasRef.current;
    if (!loupeShown || !mesh || loupeX === null || loupeY === null || !loupe || !canvas) return undefined;
    const animationFrame = window.requestAnimationFrame(() => {
      const rect = canvas.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const pixels = Math.round(MESH_LOUPE_SIZE_PX * ratio);
      if (loupe.width !== pixels || loupe.height !== pixels) {
        loupe.width = pixels;
        loupe.height = pixels;
      }
      const context = loupe.getContext('2d');
      if (!context) return;
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.fillStyle = '#0b0d12';
      context.fillRect(0, 0, pixels, pixels);
      // The view's own drawing, redrawn larger about the pointer, so it stays sharp.
      const zoom = MESH_LOUPE_MAGNIFICATION;
      context.setTransform(
        ratio * zoom, 0, 0, ratio * zoom,
        ratio * (MESH_LOUPE_SIZE_PX / 2 - zoom * loupeX),
        ratio * (MESH_LOUPE_SIZE_PX / 2 - zoom * loupeY),
      );
      const reach = MESH_LOUPE_SIZE_PX / (2 * zoom);
      if (meshOverlay && geometry) drawMeshOverlayGeometry(context, rect.width, rect.height);
      drawMesh(
        context, mesh, rect.width, rect.height, rotorAngleDeg, navigation.scale,
        [navigation.pan.x, navigation.pan.y], (navigation.rotationDeg * Math.PI) / 180,
        meshDisplayMode, showMeshEdges, meshQualities, meshQualityThreshold, focusedMeshElementIndex, [], meshEdgeColor,
        {
          fill: !meshOverlay,
          coilPhases: geometry && !plainWinding ? meshCoilPhases(mesh, geometry) : null,
          cull: [loupeX - reach, loupeY - reach, loupeX + reach, loupeY + reach],
          edgeWidthScale: 0.6,
        },
      );
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.strokeStyle = 'rgba(255, 255, 255, 0.85)';
      context.lineWidth = 1;
      const centre = MESH_LOUPE_SIZE_PX / 2;
      context.beginPath();
      context.moveTo(centre - 7, centre);
      context.lineTo(centre + 7, centre);
      context.moveTo(centre, centre - 7);
      context.lineTo(centre, centre + 7);
      context.stroke();
    });
    return () => window.cancelAnimationFrame(animationFrame);
    // drawMeshOverlayGeometry reads only values listed here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    focusedMeshElementIndex, geometry, loupeShown, loupeX, loupeY, magnetPolarityView, mesh, meshDisplayMode,
    meshEdgeColor, meshOverlay, meshOverlays, meshQualities, meshQualityThreshold, navigation.pan.x, navigation.pan.y,
    navigation.rotationDeg, navigation.scale, phaseDrive, plainWinding, previewRpm, rotorAngleDeg, showMeshEdges, showToothPoles, windingType,
  ]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const render = () => {
      const rect = canvas.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      const context = canvas.getContext('2d');
      if (!context) return;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, rect.width, rect.height);

      const gradient = context.createRadialGradient(
        rect.width * 0.5,
        rect.height * 0.45,
        0,
        rect.width * 0.5,
        rect.height * 0.5,
        Math.max(rect.width, rect.height) * 0.7,
      );
      gradient.addColorStop(0, '#171a22');
      gradient.addColorStop(1, '#0b0d12');
      context.fillStyle = gradient;
      context.fillRect(0, 0, rect.width, rect.height);
      hitRegionsRef.current = [];
      dimensionHitsRef.current = [];
      meshHitsRef.current = [];
      meshHitRotationRef.current = null;

      context.strokeStyle = 'rgba(255, 255, 255, 0.035)';
      context.lineWidth = 1;
      const grid = 36;
      for (let x = grid; x < rect.width; x += grid) {
        context.beginPath();
        context.moveTo(x, 0);
        context.lineTo(x, rect.height);
        context.stroke();
      }
      for (let y = grid; y < rect.height; y += grid) {
        context.beginPath();
        context.moveTo(0, y);
        context.lineTo(rect.width, y);
        context.stroke();
      }

      if (mode === 'geometry' && geometry) {
        drawGeometry(
          context,
          geometry,
          rect.width,
          rect.height,
          layer,
          rotorAngleDeg,
          windingType,
          hitRegionsRef.current,
          selectedComponent,
          hoveredComponent,
          highlightComponentKind,
          navigation.scale,
          [navigation.pan.x, navigation.pan.y],
          (navigation.rotationDeg * Math.PI) / 180,
          annotations,
          activeDimension,
          hoveredDimension,
          dimensionHitsRef.current,
          magnetPolarityView,
          phaseDrive,
          showToothPoles,
          previewRpm,
          plainWinding,
          shownOverlays,
        );
      } else if (mode === 'mesh' && mesh) {
        const viewRotationRad = (navigation.rotationDeg * Math.PI) / 180;
        const pan: [number, number] = [navigation.pan.x, navigation.pan.y];
        const coilPhases = geometry && !plainWinding ? meshCoilPhases(mesh, geometry) : null;
        if (meshOverlay && geometry) drawMeshOverlayGeometry(context, rect.width, rect.height);
        const meshPass = (
          target: CanvasRenderingContext2D,
          angleDeg: number,
          hits: MeshTriangleHit[],
          part: 'all' | 'fixed' | 'rotor',
        ) => drawMesh(
          target,
          mesh,
          rect.width,
          rect.height,
          angleDeg,
          navigation.scale,
          pan,
          viewRotationRad,
          meshDisplayMode,
          showMeshEdges,
          meshQualities,
          meshQualityThreshold,
          focusedMeshElementIndex,
          hits,
          meshEdgeColor,
          { part, fill: !meshOverlay, coilPhases },
        );
        let frame: MeshDrawFrame | null;
        if (rotorAngleDeg === 0) {
          frame = meshPass(context, 0, meshHitsRef.current, 'all');
        } else {
          // A turning rotor: the still part and the rotor are each drawn once, and the
          // rotor's picture is turned for every frame, which is what keeps it smooth.
          const key = [
            mesh, canvas.width, canvas.height, navigation.scale, pan[0], pan[1], viewRotationRad, meshDisplayMode,
            showMeshEdges, meshQualities, meshQualityThreshold, focusedMeshElementIndex, meshEdgeColor, meshOverlay, coilPhases,
          ];
          let layers = meshLayersRef.current;
          if (!layers || layers.key.length !== key.length || layers.key.some((value, index) => value !== key[index])) {
            const fixedHits: MeshTriangleHit[] = [];
            const rotorHits: MeshTriangleHit[] = [];
            const fixed = document.createElement('canvas');
            fixed.width = canvas.width;
            fixed.height = canvas.height;
            const fixedContext = fixed.getContext('2d');
            fixedContext?.setTransform(ratio, 0, 0, ratio, 0, 0);
            const fixedFrame = fixedContext ? meshPass(fixedContext, 0, fixedHits, 'fixed') : null;
            const { map, scale } = fitTransform(mesh.nodes_mm, rect.width, rect.height, navigation.scale, pan, undefined, viewRotationRad);
            const origin = map([0, 0]);
            // Centre the entire rotor in its own surface. Viewport-sized layers
            // discard off-screen elements before rotation can bring them back.
            const rotorSize = Math.max(1, 2 * (meshRotorRadiusMm(mesh) * scale + ROTOR_CACHE_PADDING_PX));
            const rotor = document.createElement('canvas');
            rotor.width = rotor.height = Math.min(MAX_ROTOR_CACHE_SIDE_PX, Math.ceil(rotorSize * ratio));
            const rotorContext = rotor.getContext('2d');
            const rotorRatio = rotor.width / rotorSize;
            rotorContext?.setTransform(
              rotorRatio, 0, 0, rotorRatio,
              (rotorSize / 2 - origin[0]) * rotorRatio,
              (rotorSize / 2 - origin[1]) * rotorRatio,
            );
            const rotorFrame = rotorContext ? meshPass(rotorContext, 0, rotorHits, 'rotor') : null;
            layers = { key, fixed, rotor, rotorSize, frame: fixedFrame ?? rotorFrame, hits: [...fixedHits, ...rotorHits] };
            meshLayersRef.current = layers;
          }
          frame = layers.frame;
          meshHitsRef.current = layers.hits;
          context.drawImage(layers.fixed, 0, 0, rect.width, rect.height);
          if (frame) {
            meshHitRotationRef.current = { origin: frame.origin, angleDeg: rotorAngleDeg };
            context.save();
            context.translate(frame.origin[0], frame.origin[1]);
            context.rotate((rotorAngleDeg * Math.PI) / 180);
            context.drawImage(layers.rotor, -layers.rotorSize / 2, -layers.rotorSize / 2, layers.rotorSize, layers.rotorSize);
            context.restore();
          }
        }
        // The geometry drawn under an overlay has already marked the rotor's place.
        if (frame && !(meshOverlay && geometry)) drawRotorZeroMark(context, frame.origin, frame.radiusPx, rotorAngleDeg, viewRotationRad);
      }
    };

    const observer = new ResizeObserver(render);
    observer.observe(canvas);
    render();
    return () => observer.disconnect();
  }, [
    activeDimension,
    annotations,
    geometry,
    highlightComponentKind,
    hoveredDimension,
    hoveredComponent,
    layer,
    mesh,
    meshDisplayMode,
    meshQualities,
    meshQualityThreshold,
    magnetPolarityView,
    mode,
    phaseDrive,
    plainWinding,
    shownOverlays,
    meshOverlays,
    showToothPoles,
    previewRpm,
    navigation.pan.x,
    navigation.pan.y,
    navigation.scale,
    navigation.rotationDeg,
    rotorAngleDeg,
    selectedComponent,
    showMeshEdges,
    meshEdgeColor,
    focusedMeshElementIndex,
    windingType,
  ]);

  const pointerPoint = (event: MouseEvent<HTMLCanvasElement>): [number, number] => {
    const rect = event.currentTarget.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  };

  const componentAtPointer = (event: MouseEvent<HTMLCanvasElement>) => {
    const point = pointerPoint(event);
    for (let index = hitRegionsRef.current.length - 1; index >= 0; index -= 1) {
      const region = hitRegionsRef.current[index];
      if (region && pointInContours(point, region.loops ?? [region.points])) return region.selection;
    }
    return null;
  };

  const meshElementAtPointer = (event: MouseEvent<HTMLCanvasElement>) => {
    const point = pointerPoint(event);
    const rotation = meshHitRotationRef.current;
    // Unturn the pointer once; the cached rotor hit polygons stay at 0°.
    const rotorPoint = rotation ? rotatePoint(
      [point[0] - rotation.origin[0], point[1] - rotation.origin[1]], -rotation.angleDeg,
    ).map((value, axis) => value + rotation.origin[axis]) as [number, number] : point;
    for (let index = meshHitsRef.current.length - 1; index >= 0; index -= 1) {
      const hit = meshHitsRef.current[index];
      if (hit && pointInPolygon(isRotorRegion(hit.selection.region) ? rotorPoint : point, hit.points)) return hit.selection;
    }
    return null;
  };

  /** Nearest dimension line within a finger's width, so 1mm spans stay clickable. */
  const dimensionAtPointer = (event: MouseEvent<HTMLCanvasElement>): DimensionId | null => {
    const [px, py] = pointerPoint(event);
    const TOLERANCE = 7;
    let best: { id: DimensionId; distance: number } | null = null;
    for (const hit of dimensionHitsRef.current) {
      const [x0, y0] = hit.from;
      const [x1, y1] = hit.to;
      const dx = x1 - x0;
      const dy = y1 - y0;
      const lengthSq = dx * dx + dy * dy;
      // Distance to the segment, clamped to its ends rather than the infinite line.
      const t = lengthSq > 0
        ? Math.max(0, Math.min(1, ((px - x0) * dx + (py - y0) * dy) / lengthSq))
        : 0;
      const distance = Math.hypot(px - (x0 + t * dx), py - (y0 + t * dy));
      if (distance <= TOLERANCE && (!best || distance < best.distance)) {
        best = { id: hit.id, distance };
      }
    }
    return best?.id ?? null;
  };

  return (
    <div
      className={`public-viewport-navigation public-motor-navigation${navigation.panEnabled ? ' is-pannable' : ''}${navigation.isDragging ? ' is-dragging' : ''}`}
      ref={navigation.viewportRef}
      {...navigation.bind}
    >
      <canvas
        className="motor-canvas"
        ref={canvasRef}
        aria-label={`${mode} motor view, ${layer} layer`}
        onPointerMove={(event) => {
          if (loupeShown) {
            const bounds = event.currentTarget.getBoundingClientRect();
            const x = event.clientX - bounds.left;
            const y = event.clientY - bounds.top;
            // The panel sits top left, and steps to the top right when the pointer comes under it.
            const reach = MESH_LOUPE_SIZE_PX + 40;
            setLoupePoint({ x, y, onRight: x < reach && y < reach });
          }
          if (navigation.panEnabled) {
            setHoveredComponent(null);
            onMeshElementHover?.(null);
            return;
          }
          const component = componentAtPointer(event);
          const meshElement = mode === 'mesh' ? meshElementAtPointer(event) : null;
          const overSomething = Boolean(dimensionAtPointer(event)) || Boolean(component) || Boolean(meshElement);
          setHoveredComponent((current) => current?.id === component?.id ? current : component);
          onMeshElementHover?.(meshElement);
          event.currentTarget.style.cursor = overSomething ? 'pointer' : 'default';
        }}
        onPointerLeave={(event) => {
          setLoupePoint(null);
          setHoveredComponent(null);
          onMeshElementHover?.(null);
          if (!navigation.panEnabled) event.currentTarget.style.cursor = 'default';
        }}
        onClick={(event) => {
          if (navigation.didDragRef.current) {
            navigation.didDragRef.current = false;
            return;
          }
          // A dimension line wins over the region under it: the line is a thin
          // target drawn on top of a large one, so whoever hits it meant it.
          const dimension = dimensionAtPointer(event);
          if (dimension) {
            onDimensionSelect?.(activeDimension === dimension ? null : dimension);
            return;
          }
          if (mode === 'mesh') {
            onMeshElementSelect?.(meshElementAtPointer(event));
            return;
          }
          if (activeDimension) onDimensionSelect?.(null);
          onComponentSelect?.(componentAtPointer(event));
        }}
      />
      {loupeShown && loupePoint && (
        <div className={`public-field-loupe${loupePoint.onRight ? '' : ' is-left'}`} aria-hidden="true">
          <canvas ref={loupeCanvasRef} />
          <span>{MESH_LOUPE_MAGNIFICATION}×</span>
        </div>
      )}
      {(() => {
        const zoomControls = (
          <ViewportNavigationControls
            scale={navigation.scale}
            onZoomIn={navigation.zoomIn}
            onZoomOut={navigation.zoomOut}
            onReset={navigation.reset}
            onSector={navigation.sector}
            onSectorStep={navigation.sectorStep}
            onSectorGoTo={navigation.sectorGoTo}
            sectorActive={navigation.sectorActive}
            sectorAngleDeg={navigation.sectorAngleDeg}
            sectorSpanDeg={navigation.sectorSpanDeg}
          />
        );
        return navigationSlot ? createPortal(zoomControls, navigationSlot) : zoomControls;
      })()}
    </div>
  );
}
