import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';

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
  meshDisplayMode?: PublicMeshDisplayMode;
  showMeshEdges?: boolean;
  meshQualities?: number[];
  meshQualityThreshold?: number;
  focusedMeshElementIndex?: number | null;
  onMeshElementHover?: (element: PublicMeshElementSelection | null) => void;
  onMeshElementSelect?: (element: PublicMeshElementSelection | null) => void;
}

/** 'none' = every overlay off, leaving the bare cross-section. */
export type PublicCanvasLayer = 'none' | 'dimensions' | 'slots' | 'windings' | 'phases' | 'materials';
export type PublicMagnetPolarityView = 'dominant' | 'split';

interface HitRegion {
  points: Array<[number, number]>;
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

const TOOTH_PHASE_SEQUENCE = ['A', 'C', 'B'] as const;

/** Per-tooth coil identity — the same pattern the 3D concentrated coils use. */
function toothCoil(toothIndex: number): { phase: keyof typeof PHASE_COLORS; direction: '+' | '-' } {
  const wrapped = ((toothIndex % 3) + 3) % 3;
  return {
    phase: TOOTH_PHASE_SEQUENCE[wrapped],
    direction: toothIndex % 2 === 0 ? '+' : '-',
  };
}

function slotNumberFromRegion(regionType: string): number | null {
  const match = regionType.match(/slot[_-]?(\d+)/i);
  return match ? Number(match[1]) : null;
}

interface ToothCoilSide {
  toothIndex: number;
  phase: keyof typeof PHASE_COLORS;
  direction: '+' | '-';
  outOfPage: boolean;
}

/**
 * The two coil sides sharing one slot of a double-layer tooth winding.
 * Tooth t sits counterclockwise of slot t, so slot k holds the clockwise side
 * of tooth k's coil (upper half) and the counterclockwise side of tooth k−1's
 * coil (lower half); the two sides of any one coil carry opposite current.
 */
function toothCoilSidesForSlot(slotIndex: number, slotCount: number): { lower: ToothCoilSide; upper: ToothCoilSide } {
  const upperTooth = ((slotIndex % slotCount) + slotCount) % slotCount;
  const lowerTooth = (upperTooth + slotCount - 1) % slotCount;
  const upperCoil = toothCoil(upperTooth);
  const lowerCoil = toothCoil(lowerTooth);
  return {
    lower: { toothIndex: lowerTooth, ...lowerCoil, outOfPage: lowerCoil.direction === '+' },
    upper: { toothIndex: upperTooth, ...upperCoil, outOfPage: upperCoil.direction === '-' },
  };
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

function polygonAreaAndCentroid(points: Array<[number, number]>): { area: number; centroid: [number, number] } {
  let doubledArea = 0;
  let centroidX = 0;
  let centroidY = 0;
  for (let index = 0; index < points.length; index += 1) {
    const [x0, y0] = points[index];
    const [x1, y1] = points[(index + 1) % points.length];
    const cross = x0 * y1 - x1 * y0;
    doubledArea += cross;
    centroidX += (x0 + x1) * cross;
    centroidY += (y0 + y1) * cross;
  }
  if (Math.abs(doubledArea) < 1e-9) {
    const fallback = points.reduce<[number, number]>(
      (sum, point) => [sum[0] + point[0], sum[1] + point[1]],
      [0, 0],
    );
    return { area: 0, centroid: [fallback[0] / Math.max(1, points.length), fallback[1] / Math.max(1, points.length)] };
  }
  return {
    area: Math.abs(doubledArea) / 2,
    centroid: [centroidX / (3 * doubledArea), centroidY / (3 * doubledArea)],
  };
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
  return /rotor|magnet|shaft|inter_pole_air|ipm_pocket/i.test(regionType) && !/stator/i.test(regionType);
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

function phaseFill(phase: keyof typeof PHASE_COLORS, layer: PublicCanvasLayer, rotorAngleDeg: number): string {
  if (layer === 'phases') {
    const phaseOffset = phase === 'A' ? 0 : phase === 'B' ? -120 : 120;
    const strength = 0.48 + Math.abs(Math.sin((rotorAngleDeg + phaseOffset) * Math.PI / 180)) * 0.52;
    const color = PHASE_COLORS[phase];
    const red = Math.round(Number.parseInt(color.slice(1, 3), 16) * strength);
    const green = Math.round(Number.parseInt(color.slice(3, 5), 16) * strength);
    const blue = Math.round(Number.parseInt(color.slice(5, 7), 16) * strength);
    return `rgb(${red}, ${green}, ${blue})`;
  }
  return PHASE_COLORS[phase];
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

function drawVShapeMagnetPolarityHalves(
  context: CanvasRenderingContext2D,
  magnetPoints: Array<[number, number]>,
  map: (point: [number, number]) => [number, number],
  regionType: string,
): void {
  const faces = computeMagnetPoleFaces(magnetPoints);
  if (!faces) return;

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
}

function drawSpmMagnetPolarityHalves(
  context: CanvasRenderingContext2D,
  magnetPoints: Array<[number, number]>,
  map: (point: [number, number]) => [number, number],
  regionType: string,
): void {
  const halves = computeSpmMagnetPolarityHalves(magnetPoints);
  if (!halves) return;

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
}

/**
 * Region types bounded by concentric circles; stroking those circles instead
 * of the tessellated polygon hides the polygon's radial closing seam.
 */
const ANNULAR_REGIONS = /^(stator_yoke|rotor_core|shaft)$/i;

function regionFill(regionType: string, sourceFill: string | null | undefined, layer: PublicCanvasLayer, rotorAngleDeg: number): string {
  const winding = windingToken(regionType);
  if (layer === 'materials') {
    if (/stator/i.test(regionType)) return PUBLIC_MOTOR_COLORS.statorSteel;
    if (/rotor/i.test(regionType)) return PUBLIC_MOTOR_COLORS.rotorSteel;
    if (/magnet.*(?:n|0|2|4|6)/i.test(regionType)) return PUBLIC_MOTOR_COLORS.magnetNorth;
    if (/magnet/i.test(regionType)) return PUBLIC_MOTOR_COLORS.magnetSouth;
    if (winding || /winding/i.test(regionType)) return PUBLIC_MOTOR_COLORS.winding;
  }
  if (winding && (layer === 'windings' || layer === 'phases')) {
    return phaseFill(winding.phase, layer, rotorAngleDeg);
  }
  return sourceFill || regionColor(regionType);
}

function fitTransform(
  points: Array<[number, number]>,
  width: number,
  height: number,
  viewportScale = 1,
  pan: [number, number] = [0, 0],
): { map: (point: [number, number]) => [number, number]; scale: number } {
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const padding = Math.min(width, height) * 0.075;
  const scale = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY);
  const offsetX = (width - spanX * scale) / 2 - minX * scale;
  const offsetY = (height - spanY * scale) / 2 + maxY * scale;
  const centerX = width / 2;
  const centerY = height / 2;
  return {
    scale: scale * viewportScale,
    map: ([x, y]) => {
      const fittedX = offsetX + x * scale;
      const fittedY = offsetY - y * scale;
      return [
        centerX + (fittedX - centerX) * viewportScale + pan[0],
        centerY + (fittedY - centerY) * viewportScale + pan[1],
      ];
    },
  };
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
  annotations: DimensionAnnotation[],
  activeDimension: DimensionId | null,
  hoveredDimension: DimensionId | null,
  dimensionHits: DimensionHit[],
  magnetPolarityView: PublicMagnetPolarityView,
): void {
  const points = data.regions.flatMap((region) => region.points);
  if (points.length === 0) return;
  const { map, scale } = fitTransform(points, width, height, viewportScale, pan);
  const slotCount = Number(data.metadata.slot_count || 0);
  // Every layer except Materials draws the winding split into its two coil sides.
  // 'none' included: the split is what the winding physically is — two coil sides
  // sharing a slot — not an annotation, so turning an overlay off must not redraw
  // the slots as single solid wedges in a different colour.
  const splitLayer = layer !== 'materials';
  const toothSplitActive = windingType === 'concentrated' && slotCount >= 3;
  const origin = map([0, 0]);
  const [, boundingRadiusMm] = radialExtentMm(points);
  const outerRadiusPx = Math.max(1, (Number(data.metadata.stator_od_mm || 0) / 2 || boundingRadiusMm) * scale);
  const pendingMarkers: Array<{ x: number; y: number; radius: number; outOfPage: boolean; ring: string }> = [];
  interface ComponentPath {
    points: Array<[number, number]>;
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
  ) => {
    const componentPath = { points: canvasPoints, annulus };
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

  const drawToothCoilHalf = (
    regionPoints: Array<[number, number]>,
    normal: [number, number],
    side: ToothCoilSide,
    slotNumber: number,
    regionIndex: number,
  ) => {
    const halfPoints = clipPolygonToHalfPlane(regionPoints, normal);
    if (halfPoints.length < 3) return;
    const canvasPoints = halfPoints.map(map);
    context.beginPath();
    context.moveTo(canvasPoints[0][0], canvasPoints[0][1]);
    for (const [x, y] of canvasPoints.slice(1)) {
      context.lineTo(x, y);
    }
    context.closePath();
    const [innerCoilMm, outerCoilMm] = radialExtentMm(halfPoints);
    context.fillStyle = shadedRegionFill(
      context,
      'winding',
      phaseFill(side.phase, layer, rotorAngleDeg),
      origin,
      innerCoilMm * scale,
      outerCoilMm * scale,
    );
    context.globalAlpha = 0.94;
    context.fill();
    context.globalAlpha = 1;
    context.strokeStyle = 'rgba(6, 8, 12, 0.68)';
    context.lineWidth = Math.max(0.7, Math.min(1.5, scale * 0.035));
    context.stroke();
    const selection: PublicMotorComponentSelection = {
      id: `region-${regionIndex}-tooth-${side.toothIndex}`,
      kind: 'winding',
      label: `Tooth ${side.toothIndex + 1} coil · phase ${side.phase}${side.direction}`,
      role: `Concentrated coil side in slot ${slotNumber} — current ${side.outOfPage ? 'out of the page ⊙' : 'into the page ⊗'}`,
      regionType: `tooth_${side.toothIndex}_coil_side`,
      regionIndex,
      slotIndex: slotNumber,
      toothIndex: side.toothIndex + 1,
      phase: side.phase,
      direction: side.direction,
    };
    hitRegions.push({ points: canvasPoints, selection });
    trackComponentPath(selection, canvasPoints);
    // Slots deliberately omits the direction glyphs; every other layer, including
    // 'none', keeps them, so the winding reads the same whatever is switched on.
    if (layer !== 'materials' && layer !== 'slots') {
      const { area, centroid } = polygonAreaAndCentroid(halfPoints);
      const [markerX, markerY] = map(centroid);
      const markerRadius = Math.max(4, Math.min(11, Math.sqrt(Math.max(area, 1)) * scale * 0.21));
      // Markers render after the lighting pass so their glyphs stay crisp.
      pendingMarkers.push({ x: markerX, y: markerY, radius: markerRadius, outOfPage: side.outOfPage, ring: PHASE_COLORS[side.phase] });
    }
  };

  context.lineJoin = 'round';
  data.regions.forEach((region, regionIndex) => {
    if (region.points.length < 2) return;
    // The double-layer tooth winding draws its own per-side ⊙/⊗ markers, so
    // the backend's single homogenized slot marker would contradict them.
    if (toothSplitActive && region.region_type === 'winding_symbol') return;
    const slotNumber = slotNumberFromRegion(region.region_type);
    if (toothSplitActive && splitLayer && slotNumber !== null && windingToken(region.region_type)) {
      const slotAngle = ((slotNumber - 1) * Math.PI * 2) / slotCount;
      const normal: [number, number] = [-Math.sin(slotAngle), Math.cos(slotAngle)];
      const sides = toothCoilSidesForSlot(slotNumber - 1, slotCount);
      drawToothCoilHalf(region.points, [-normal[0], -normal[1]], sides.lower, slotNumber, regionIndex);
      drawToothCoilHalf(region.points, normal, sides.upper, slotNumber, regionIndex);
      return;
    }
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
    const [firstX, firstY] = canvasPoints[0];
    context.beginPath();
    context.moveTo(firstX, firstY);
    for (const [x, y] of canvasPoints.slice(1)) {
      context.lineTo(x, y);
    }
    context.closePath();
    context.fillStyle = shadedRegionFill(
      context,
      region.region_type,
      usesSplitPolarity
        ? PUBLIC_MOTOR_COLORS.magnetBody
        : regionFill(region.region_type, region.fill, layer, rotorAngleDeg),
      origin,
      /shaft/i.test(region.region_type) ? 0 : innerRadiusMm * scale,
      outerRadiusMm * scale,
    );
    context.globalAlpha = /air/i.test(region.region_type) ? 0.45 : 0.94;
    context.fill();
    context.globalAlpha = 1;
    if (isVShapeMagnet && usesSplitPolarity) {
      drawVShapeMagnetPolarityHalves(
        context,
        transformedPoints,
        map,
        region.region_type,
      );
    } else if (isSpmMagnet && usesSplitPolarity) {
      drawSpmMagnetPolarityHalves(
        context,
        transformedPoints,
        map,
        region.region_type,
      );
    }
    context.strokeStyle = 'rgba(6, 8, 12, 0.68)';
    context.lineWidth = Math.max(0.7, Math.min(1.5, scale * 0.035));
    if (ANNULAR_REGIONS.test(region.region_type)) {
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
    if (selection && toothSplitActive && selection.kind === 'winding' && slotNumber !== null) {
      selection = {
        ...selection,
        label: `Slot ${slotNumber} winding`,
        role: 'Carries one coil side from each adjacent tooth coil',
      };
    }
    if (selection) hitRegions.push({ points: canvasPoints, selection });
    if (selection) {
      trackComponentPath(
        selection,
        canvasPoints,
        ANNULAR_REGIONS.test(region.region_type)
          ? {
            center: origin,
            innerRadiusPx: innerRadiusMm * scale,
            outerRadiusPx: outerRadiusMm * scale,
          }
          : undefined,
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

  if (layer === 'slots' || layer === 'windings' || layer === 'phases') {
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    for (const region of data.regions) {
      const slotMatch = region.region_type.match(/slot_(\d+)/i);
      if (!slotMatch || region.points.length === 0) continue;
      // In the tooth-split view the phase identity lives on the half-wedges
      // and their markers; a single homogenized phase chip would mislead.
      if (toothSplitActive && layer !== 'slots') continue;
      const center = region.points.reduce<[number, number]>(
        (current, point) => [current[0] + point[0], current[1] + point[1]],
        [0, 0],
      ).map((value) => value / region.points.length) as [number, number];
      const [x, y] = map(center);
      const winding = windingToken(region.region_type);
      const label = layer === 'slots' ? slotMatch[1] : winding ? `${winding.phase}${winding.direction}` : slotMatch[1];
      context.beginPath();
      context.arc(x, y, layer === 'slots' ? 10 : 12, 0, Math.PI * 2);
      context.fillStyle = 'rgba(8, 10, 14, 0.78)';
      context.fill();
      context.strokeStyle = winding && !toothSplitActive ? PHASE_COLORS[winding.phase] : 'rgba(255,255,255,.34)';
      context.lineWidth = 1.2;
      context.stroke();
      context.fillStyle = '#f8fafc';
      context.font = `700 ${layer === 'slots' ? 9 : 10}px ui-monospace, monospace`;
      context.fillText(label, x, y + 0.5);
    }
  }

  const addComponentPath = (path: Path2D, componentPath: ComponentPath) => {
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

  if (layer === 'dimensions') {
    drawDimensionAnnotations(
      context,
      map,
      annotations,
      activeDimension,
      hoveredDimension,
      dimensionHits,
    );
  }
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
  displayMode: PublicMeshDisplayMode,
  showEdges: boolean,
  qualities: number[],
  qualityThreshold: number,
  focusedElementIndex: number | null,
  meshHits: MeshTriangleHit[],
): void {
  if (data.nodes_mm.length === 0 || data.triangles.length === 0) return;
  const { map } = fitTransform(data.nodes_mm, width, height, viewportScale, pan);
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
    const path = fillPaths.get(region) || new Path2D();
    const a = mapMeshNode(triangle[0], rotateRotor);
    const b = mapMeshNode(triangle[1], rotateRotor);
    const c = mapMeshNode(triangle[2], rotateRotor);
    const quality = qualities[index] ?? 0;
    const band = publicMeshQualityBand(quality, qualityThreshold);
    meshHits.push({
      points: [a, b, c],
      selection: { index, quality, band, region },
    });
    if (displayMode === 'geometry') {
      path.moveTo(a[0], a[1]);
      path.lineTo(b[0], b[1]);
      path.lineTo(c[0], c[1]);
      path.closePath();
      fillPaths.set(region, path);
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
    for (const [region, path] of fillPaths) {
      context.fillStyle = regionColor(region, '#697386');
      context.globalAlpha = /air/i.test(region) ? 0.25 : 0.68;
      context.fill(path);
    }
  }
  context.globalAlpha = 1;

  if (showEdges) {
    const uniqueEdges = new Set<string>();
    context.beginPath();
    data.triangles.forEach((triangle, triangleIndex) => {
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
    context.strokeStyle = displayMode === 'problems'
      ? 'rgba(226, 232, 240, 0.12)'
      : 'rgba(226, 232, 240, 0.28)';
    context.lineWidth = 0.4;
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
}

export function MotorCanvas({
  geometry,
  mesh,
  mode,
  layer = 'dimensions',
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
  meshDisplayMode = 'geometry',
  showMeshEdges = true,
  meshQualities = EMPTY_MESH_QUALITIES,
  meshQualityThreshold = 0.01,
  focusedMeshElementIndex = null,
  onMeshElementHover,
  onMeshElementSelect,
}: MotorCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hitRegionsRef = useRef<HitRegion[]>([]);
  const dimensionHitsRef = useRef<DimensionHit[]>([]);
  const meshHitsRef = useRef<MeshTriangleHit[]>([]);
  const [hoveredComponent, setHoveredComponent] = useState<PublicMotorComponentSelection | null>(null);
  const navigation = useViewportNavigation();
  const annotations = useMemo(
    () => (config && layer === 'dimensions' ? buildDimensionAnnotations(config, geometry) : []),
    [config, geometry, layer],
  );

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
          annotations,
          activeDimension,
          hoveredDimension,
          dimensionHitsRef.current,
          magnetPolarityView,
        );
      } else if (mode === 'mesh' && mesh) {
        drawMesh(
          context,
          mesh,
          rect.width,
          rect.height,
          rotorAngleDeg,
          navigation.scale,
          [navigation.pan.x, navigation.pan.y],
          meshDisplayMode,
          showMeshEdges,
          meshQualities,
          meshQualityThreshold,
          focusedMeshElementIndex,
          meshHitsRef.current,
        );
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
    navigation.pan.x,
    navigation.pan.y,
    navigation.scale,
    rotorAngleDeg,
    selectedComponent,
    showMeshEdges,
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
      if (region && pointInPolygon(point, region.points)) return region.selection;
    }
    return null;
  };

  const meshElementAtPointer = (event: MouseEvent<HTMLCanvasElement>) => {
    const point = pointerPoint(event);
    for (let index = meshHitsRef.current.length - 1; index >= 0; index -= 1) {
      const hit = meshHitsRef.current[index];
      if (hit && pointInPolygon(point, hit.points)) return hit.selection;
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
      <ViewportNavigationControls
        scale={navigation.scale}
        onZoomIn={navigation.zoomIn}
        onZoomOut={navigation.zoomOut}
        onReset={navigation.reset}
      />
    </div>
  );
}
