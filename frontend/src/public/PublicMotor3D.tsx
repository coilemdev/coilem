import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

import { buildConcentratedCoil, buildWindingHarness } from './coil3d';
import { deriveStatorSectionWidths } from './dimensionAnnotations';
import { publicFlatIpmMagnetCenterRadiusMm } from './flatIpmBurialHealth';
import type { MotorConfig, PublicMotorComponentSelection } from './model';
import { PUBLIC_MOTOR_COLORS, PUBLIC_PHASE_COLORS, renderTargetColor } from './motorPalette';

interface PublicMotor3DProps {
  config: MotorConfig;
  resetSignal: number;
  rotorAngleDeg: number;
  explodedAmount: number;
  introProgress?: number | null;
  onInteraction?: () => void;
  onComponentSelect?: (component: PublicMotorComponentSelection | null) => void;
}

/**
 * Parts the viewer can hide. Hiding one or more is how you look inside the
 * machine without exploding it. Each id maps to one or more scene groups below —
 * `stator` covers the yoke and its teeth, `windings` takes the rear links with
 * it, since neither reads on its own.
 */
type HideablePartId = 'stator' | 'windings' | 'rotor' | 'magnets' | 'airgap' | 'endcaps' | 'bearings' | 'shaft';

const HIDEABLE_PARTS: Array<{ id: HideablePartId; label: string }> = [
  { id: 'endcaps', label: 'End caps' },
  { id: 'stator', label: 'Stator' },
  { id: 'windings', label: 'Windings' },
  { id: 'airgap', label: 'Air gap' },
  { id: 'magnets', label: 'Magnets' },
  { id: 'rotor', label: 'Rotor' },
  { id: 'bearings', label: 'Bearings' },
  { id: 'shaft', label: 'Shaft' },
];

/**
 * The end caps are off on first view. They are the outermost part, so with them
 * on the opening shot of a new design is two grey discs and a housing — the
 * windings, magnets and rotor that the design actually is stay buried. Both
 * halves of each magnet are physical parts of one dipole, so opposite poles
 * remain visible by default in the engineering view.
 */
const DEFAULT_HIDDEN_PARTS: readonly HideablePartId[] = ['endcaps'];

/** A hidden part must not be clickable through, so picks skip it. */
function isVisibleThrough(object: THREE.Object3D): boolean {
  let current: THREE.Object3D | null = object;
  while (current) {
    if (!current.visible) return false;
    current = current.parent;
  }
  return true;
}

function componentSelectionForObject(object: THREE.Object3D): { object: THREE.Object3D; selection: PublicMotorComponentSelection } | null {
  let current: THREE.Object3D | null = object;
  while (current) {
    const selection = current.userData.publicMotorSelection as PublicMotorComponentSelection | undefined;
    if (selection) return { object: current, selection };
    current = current.parent;
  }
  return null;
}

function ringShape(outerRadius: number, innerRadius: number): THREE.Shape {
  const shape = new THREE.Shape();
  shape.absarc(0, 0, outerRadius, 0, Math.PI * 2, false);
  const hole = new THREE.Path();
  hole.absarc(0, 0, innerRadius, 0, Math.PI * 2, true);
  shape.holes.push(hole);
  return shape;
}

function sectorShape(innerRadius: number, outerRadius: number, halfSpanRad: number): THREE.Shape {
  const shape = new THREE.Shape();
  shape.absarc(0, 0, outerRadius, -halfSpanRad, halfSpanRad, false);
  shape.absarc(0, 0, innerRadius, halfSpanRad, -halfSpanRad, true);
  shape.closePath();
  return shape;
}

function polarPoint(radius: number, angleRad: number): THREE.Vector2 {
  return new THREE.Vector2(
    Math.cos(angleRad) * radius,
    Math.sin(angleRad) * radius,
  );
}

/** The historical four-corner tooth used when no bore shoe is configured. */
function taperedToothShape(
  boreRadius: number,
  yokeInnerRadius: number,
  boreHalfAngleRad: number,
  yokeHalfAngleRad: number,
): THREE.Shape {
  const shape = new THREE.Shape();
  shape.moveTo(...polarPoint(boreRadius, -boreHalfAngleRad).toArray());
  shape.lineTo(...polarPoint(yokeInnerRadius, -yokeHalfAngleRad).toArray());
  shape.lineTo(...polarPoint(yokeInnerRadius, yokeHalfAngleRad).toArray());
  shape.lineTo(...polarPoint(boreRadius, boreHalfAngleRad).toArray());
  shape.closePath();
  return shape;
}

/**
 * Semi-closed stator tooth matching backend.geometry_ir._shoed_annular_loop.
 *
 * The bore tip is wider than the underlying tooth body. It runs radially for
 * the configured shoe height, steps inward at the shoulder, then tapers to the
 * yoke-side body. Keeping the same eight-boundary profile as the solver makes
 * 2D and 3D tell the same geometry story instead of showing a plain trapezoid
 * after a user enables a tooth shoe.
 */
function shoedToothShape(
  boreRadius: number,
  shoulderRadius: number,
  yokeInnerRadius: number,
  tipHalfAngleRad: number,
  shoulderHalfAngleRad: number,
  yokeHalfAngleRad: number,
): THREE.Shape {
  const shape = new THREE.Shape();
  const boreStart = polarPoint(boreRadius, -tipHalfAngleRad);
  shape.moveTo(boreStart.x, boreStart.y);
  shape.absarc(0, 0, boreRadius, -tipHalfAngleRad, tipHalfAngleRad, false);
  shape.lineTo(...polarPoint(shoulderRadius, tipHalfAngleRad).toArray());
  shape.lineTo(...polarPoint(shoulderRadius, shoulderHalfAngleRad).toArray());
  shape.lineTo(...polarPoint(yokeInnerRadius, yokeHalfAngleRad).toArray());
  shape.absarc(0, 0, yokeInnerRadius, yokeHalfAngleRad, -yokeHalfAngleRad, true);
  shape.lineTo(...polarPoint(shoulderRadius, -shoulderHalfAngleRad).toArray());
  shape.lineTo(...polarPoint(shoulderRadius, -tipHalfAngleRad).toArray());
  shape.closePath();
  return shape;
}

function enamelledCopperMaterial(phaseColor: number, transparent = false): THREE.MeshPhysicalMaterial {
  return new THREE.MeshPhysicalMaterial({
    // The copper tint is kept so the bundles read as enamelled wire rather than
    // painted plastic, but pulled back from 0.18: at that weight it dragged the
    // green and violet phases toward the amber one, so the three phases were
    // harder to tell apart here than in 2D.
    color: new THREE.Color(phaseColor).lerp(new THREE.Color(0xc9722e), 0.1),
    metalness: 0.45,
    roughness: 0.3,
    // Was 0.8, which is a near-mirror coat: it whitened the bundles regardless
    // of the colour underneath.
    clearcoat: 0.4,
    clearcoatRoughness: 0.28,
    transparent,
  });
}

/** Slot-pack copper drawn flat, matching the 2D canvas's per-phase slot fills. */
function phaseMaterial(hex: string): THREE.MeshPhysicalMaterial {
  return new THREE.MeshPhysicalMaterial({
    color: renderTargetColor(hex),
    metalness: 0.08,
    roughness: 0.34,
    clearcoat: 0.2,
    clearcoatRoughness: 0.36,
  });
}

function extrude(shape: THREE.Shape, depth: number): THREE.ExtrudeGeometry {
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: false,
    curveSegments: 64,
  });
  geometry.translate(0, 0, -depth / 2);
  return geometry;
}

/** Flat washer about z = 0 — the housing parts are all stacked annuli. */
function annulusGeometry(innerRadius: number, outerRadius: number, depth: number): THREE.ExtrudeGeometry {
  return extrude(ringShape(outerRadius, innerRadius), depth);
}

/**
 * Rotation cue for the rotor end faces. The core is a surface of revolution,
 * so a plain finish renders identically at every angle and the spinning rotor
 * reads as standing still — the same problem the shaft key solves at the
 * drive end. A square grid scribed into a canvas texture gives each end face a
 * visible angular position while staying the same steel colour as the rest of
 * the core. The fine Cartesian pattern reads as a subtle inspection/scribe grid
 * instead of the heavy radial spokes of a polar plot. It goes on the caps only:
 * the cylindrical side keeps its plain laminated finish, which for IPM has to
 * stay translucent so the buried magnets read through.
 */
function makeRotorFaceTexture(): THREE.CanvasTexture {
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d');
  if (context) {
    const base = new THREE.Color(0x36465c);
    context.fillStyle = `#${base.getHexString()}`;
    context.fillRect(0, 0, size, size);

    const center = size / 2;
    const gridStep = 24;
    const grid = base.clone().lerp(new THREE.Color(0xb8c5d6), 0.28);
    context.strokeStyle = `#${grid.getHexString()}`;
    context.lineWidth = 1.15;

    // Anchor the grid on the rotor axis so opposite faces and topology changes
    // keep the same calm, symmetric square pattern.
    for (let offset = 0; offset <= center; offset += gridStep) {
      const positions = offset === 0
        ? [center + 0.5]
        : [center - offset + 0.5, center + offset + 0.5];
      positions.forEach((position) => {
        context.beginPath();
        context.moveTo(position, 0);
        context.lineTo(position, size);
        context.stroke();
        context.beginPath();
        context.moveTo(0, position);
        context.lineTo(size, position);
        context.stroke();
      });
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  return texture;
}

interface VShapeMagnetPlacement3D {
  centerX: number;
  centerY: number;
  axisAngleRad: number;
  effectiveLengthMm: number;
  side: 'left' | 'right';
}

/**
 * Match the backend's V-shape construction: two slabs start on opposite sides
 * of the inner web and open toward the rotor OD. The fit calculation keeps the
 * far corners below the outer bridge, so the 3D representation uses the same
 * valid dimensions as the 2D preview instead of drawing oversized generic
 * boxes through the rotor surface.
 */
function vShapeMagnetPlacement(
  config: MotorConfig,
  poleAngleRad: number,
  sideSign: 1 | -1,
): VShapeMagnetPlacement3D {
  const rotorOuterRadius = config.rotor.OD_mm / 2;
  const magnetLength = config.rotor.magnet_width_mm;
  const magnetThickness = config.rotor.magnet_thickness_mm;
  const pocketClearance = config.rotor.pocket_clearance_mm || 0;
  const innerWeb = config.rotor.inner_web_thickness_mm || 0;
  const outerBridge = config.rotor.outer_bridge_thickness_mm || 0;
  const halfAngle = config.rotor.v_angle_deg * Math.PI / 360;
  const apexRadius = rotorOuterRadius - (config.rotor.v_depth_mm || 0);
  const radialX = Math.cos(poleAngleRad);
  const radialY = Math.sin(poleAngleRad);
  const tangentialX = -radialY;
  const tangentialY = radialX;
  const axisX = Math.cos(halfAngle) * radialX + sideSign * Math.sin(halfAngle) * tangentialX;
  const axisY = Math.cos(halfAngle) * radialY + sideSign * Math.sin(halfAngle) * tangentialY;
  const normalX = Math.sin(halfAngle) * radialX - sideSign * Math.cos(halfAngle) * tangentialX;
  const normalY = Math.sin(halfAngle) * radialY - sideSign * Math.cos(halfAngle) * tangentialY;
  const innerCenterX = apexRadius * radialX + sideSign * (innerWeb / 2) * tangentialX;
  const innerCenterY = apexRadius * radialY + sideSign * (innerWeb / 2) * tangentialY;

  const fitRadius = rotorOuterRadius - outerBridge;
  let effectiveLength = magnetLength;
  if (fitRadius > 0) {
    const pocketHalfThickness = magnetThickness / 2 + pocketClearance;
    let maximumLength = magnetLength;
    for (const cornerSign of [1, -1] as const) {
      const cornerBaseX = innerCenterX
        + pocketClearance * axisX
        + cornerSign * pocketHalfThickness * normalX;
      const cornerBaseY = innerCenterY
        + pocketClearance * axisY
        + cornerSign * pocketHalfThickness * normalY;
      const alongAxis = cornerBaseX * axisX + cornerBaseY * axisY;
      const discriminant = alongAxis * alongAxis
        - (cornerBaseX * cornerBaseX + cornerBaseY * cornerBaseY)
        + fitRadius * fitRadius;
      const root = discriminant > 0 ? -alongAxis + Math.sqrt(discriminant) : 0;
      maximumLength = Math.min(maximumLength, root);
    }
    if (maximumLength < magnetLength - 1e-9) {
      effectiveLength = Math.max(maximumLength, 0.5);
    }
  }

  return {
    centerX: innerCenterX + (effectiveLength / 2) * axisX,
    centerY: innerCenterY + (effectiveLength / 2) * axisY,
    axisAngleRad: Math.atan2(axisY, axisX),
    effectiveLengthMm: effectiveLength,
    side: sideSign > 0 ? 'left' : 'right',
  };
}

/**
 * Assembled, the end cap is a translucent shell: a closed machine would
 * otherwise hide the end windings that make the assembled view legible. It goes
 * fully solid as soon as the explode pulls it clear of the stack.
 */
const ENDCAP_ASSEMBLED_OPACITY = 0.42;

interface HousingBuild {
  group: THREE.Group;
  geometries: THREE.BufferGeometry[];
}

interface BearingAnimationRig extends HousingBuild {
  innerRace: THREE.Group;
  cage: THREE.Group;
  ballSpinners: THREE.Group[];
  cageRatio: number;
  ballRollRatio: number;
}

/**
 * Deep-groove ball bearing: two races, a cage, and the ball set between them.
 * Proportions follow a 6900-series section — roughly a third of the radial
 * build per race with the balls filling the middle — rather than any solved
 * dimension. Built about z = 0 and positioned by the caller.
 */
function buildBearing(
  dims: { boreRadius: number; outerRadius: number; width: number },
  materials: {
    race: THREE.Material;
    ball: THREE.Material;
    cage: THREE.Material;
    motionMark: THREE.Material;
  },
): BearingAnimationRig {
  const group = new THREE.Group();
  const innerRace = new THREE.Group();
  const outerRace = new THREE.Group();
  const cage = new THREE.Group();
  innerRace.name = 'bearing-inner-race';
  outerRace.name = 'bearing-outer-race-fixed';
  cage.name = 'bearing-cage';
  group.add(innerRace, outerRace, cage);

  const build = dims.outerRadius - dims.boreRadius;
  const innerRaceOuter = dims.boreRadius + build * 0.34;
  const outerRaceInner = dims.boreRadius + build * 0.76;
  const ballPitch = (innerRaceOuter + outerRaceInner) / 2;
  const ballRadius = Math.max(0.2, (outerRaceInner - innerRaceOuter) * 0.62);

  const innerRaceGeometry = annulusGeometry(dims.boreRadius, innerRaceOuter, dims.width);
  const outerRaceGeometry = annulusGeometry(outerRaceInner, dims.outerRadius, dims.width);
  const cageGeometry = annulusGeometry(
    ballPitch - ballRadius * 0.42,
    ballPitch + ballRadius * 0.42,
    dims.width * 0.42,
  );
  // One ball geometry shared across the set — they differ only by position.
  const ballGeometry = new THREE.SphereGeometry(ballRadius, 20, 14);
  const raceMotionMarkGeometry = new THREE.BoxGeometry(
    build * 0.2,
    build * 0.07,
    dims.width * 0.035,
  );
  const cageMotionMarkGeometry = new THREE.BoxGeometry(
    ballRadius * 0.7,
    ballRadius * 0.16,
    dims.width * 0.035,
  );
  const ballMotionMarkGeometry = new THREE.SphereGeometry(ballRadius * 0.12, 10, 7);

  innerRace.add(new THREE.Mesh(innerRaceGeometry, materials.race));
  outerRace.add(new THREE.Mesh(outerRaceGeometry, materials.race));
  cage.add(new THREE.Mesh(cageGeometry, materials.cage));

  const raceMotionMark = new THREE.Mesh(raceMotionMarkGeometry, materials.motionMark);
  raceMotionMark.position.set(
    (dims.boreRadius + innerRaceOuter) / 2,
    0,
    dims.width * 0.51,
  );
  innerRace.add(raceMotionMark);
  const cageMotionMark = new THREE.Mesh(cageMotionMarkGeometry, materials.motionMark);
  cageMotionMark.position.set(ballPitch, 0, dims.width * 0.23);
  cage.add(cageMotionMark);

  const ballCount = 9;
  const ballSpinners: THREE.Group[] = [];
  for (let index = 0; index < ballCount; index += 1) {
    const angle = (index / ballCount) * Math.PI * 2;
    const ballSpinner = new THREE.Group();
    ballSpinner.name = `bearing-ball-${index + 1}`;
    ballSpinner.position.set(ballPitch * Math.cos(angle), ballPitch * Math.sin(angle), 0);
    const ball = new THREE.Mesh(ballGeometry, materials.ball);
    const motionMark = new THREE.Mesh(ballMotionMarkGeometry, materials.motionMark);
    motionMark.position.set(ballRadius * 0.92, 0, 0);
    ballSpinner.add(ball, motionMark);
    cage.add(ballSpinner);
    ballSpinners.push(ballSpinner);
  }

  const ballToPitchRatio = ballRadius / ballPitch;
  const cageRatio = 0.5 * (1 - ballToPitchRatio);
  const ballRollRatio = 0.5 * ((1 / ballToPitchRatio) - ballToPitchRatio);

  return {
    group,
    geometries: [
      innerRaceGeometry,
      outerRaceGeometry,
      cageGeometry,
      ballGeometry,
      raceMotionMarkGeometry,
      cageMotionMarkGeometry,
      ballMotionMarkGeometry,
    ],
    innerRace,
    cage,
    ballSpinners,
    cageRatio,
    ballRollRatio,
  };
}

function syncBearingKinematics(bearings: readonly BearingAnimationRig[], shaftAngle: number) {
  bearings.forEach((bearing) => {
    bearing.innerRace.rotation.z = shaftAngle;
    bearing.cage.rotation.z = shaftAngle * bearing.cageRatio;
    bearing.ballSpinners.forEach((ballSpinner) => {
      ballSpinner.rotation.z = -shaftAngle * bearing.ballRollRatio;
    });
  });
}

/**
 * End cap / bell housing: a stepped casting — outer flange, a thinner web, and
 * a hub that reaches back inboard to hold the bearing's outer race, tied
 * together by radial ribs. Built about z = 0 and positioned by the caller.
 */
function buildEndCap(
  dims: { boreRadius: number; outerRadius: number; thickness: number; hubDepth: number },
  material: THREE.Material,
): HousingBuild {
  const group = new THREE.Group();
  const hubOuterRadius = Math.max(dims.boreRadius * 1.5, dims.boreRadius + dims.thickness * 0.7);
  const webOuterRadius = Math.max(hubOuterRadius + dims.thickness, dims.outerRadius * 0.82);

  const flangeGeometry = annulusGeometry(webOuterRadius * 0.98, dims.outerRadius, dims.thickness);
  group.add(new THREE.Mesh(flangeGeometry, material));

  const webGeometry = annulusGeometry(hubOuterRadius * 0.98, webOuterRadius, dims.thickness * 0.52);
  const web = new THREE.Mesh(webGeometry, material);
  web.position.z = dims.thickness * 0.24;
  group.add(web);

  // The hub runs inboard from the outer face so the bearing nests *inside* the
  // cap rather than hanging off the shaft beyond it.
  const hubLength = dims.thickness + dims.hubDepth;
  const hubGeometry = annulusGeometry(dims.boreRadius, hubOuterRadius, hubLength);
  const hub = new THREE.Mesh(hubGeometry, material);
  hub.position.z = (dims.thickness - hubLength) / 2 + dims.thickness / 2;
  group.add(hub);

  const ribCount = 6;
  const ribLength = Math.max(0.1, webOuterRadius - hubOuterRadius);
  const ribGeometry = new THREE.BoxGeometry(ribLength, dims.thickness * 0.34, dims.thickness * 0.5);
  for (let index = 0; index < ribCount; index += 1) {
    const angle = (index / ribCount) * Math.PI * 2 + Math.PI / ribCount;
    const rib = new THREE.Mesh(ribGeometry, material);
    rib.position.set(
      ((hubOuterRadius + webOuterRadius) / 2) * Math.cos(angle),
      ((hubOuterRadius + webOuterRadius) / 2) * Math.sin(angle),
      -dims.thickness * 0.02,
    );
    rib.rotation.z = angle;
    group.add(rib);
  }

  return { group, geometries: [flangeGeometry, webGeometry, hubGeometry, ribGeometry] };
}

/**
 * Floating part label for the exploded view: a rounded chip drawn to a canvas
 * and hung off a sprite, so it stays screen-facing and legible from any orbit
 * angle. The texture comes back alongside the sprite because only the caller
 * knows when the scene is torn down.
 */
function makeChipSprite(text: string): { sprite: THREE.Sprite; texture: THREE.CanvasTexture | null } {
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
  const fontPx = 44;
  const padX = 26;
  const padY = 14;
  const font = `700 ${fontPx}px "Inter", "SF Pro Text", system-ui, sans-serif`;

  const measureContext = document.createElement('canvas').getContext('2d');
  let textWidth = fontPx * text.length * 0.62;
  if (measureContext) {
    measureContext.font = font;
    textWidth = measureContext.measureText(text).width;
  }

  const width = Math.ceil((textWidth + padX * 2) * pixelRatio);
  const height = Math.ceil((fontPx + padY * 2) * pixelRatio);
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');

  let texture: THREE.CanvasTexture | null = null;
  if (context) {
    const chipWidth = width / pixelRatio;
    const chipHeight = height / pixelRatio;
    const radius = chipHeight / 2;
    context.scale(pixelRatio, pixelRatio);
    context.beginPath();
    context.moveTo(radius, 0);
    context.arcTo(chipWidth, 0, chipWidth, chipHeight, radius);
    context.arcTo(chipWidth, chipHeight, 0, chipHeight, radius);
    context.arcTo(0, chipHeight, 0, 0, radius);
    context.arcTo(0, 0, chipWidth, 0, radius);
    context.closePath();
    context.fillStyle = 'rgba(9, 13, 22, 0.86)';
    context.fill();
    context.strokeStyle = 'rgba(103, 232, 249, 0.34)';
    context.lineWidth = 2;
    context.stroke();
    context.font = font;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillStyle = '#dbe6f6';
    context.fillText(text, chipWidth / 2, chipHeight / 2 + 1);

    texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 4;
  }

  const material = new THREE.SpriteMaterial({ transparent: true, depthTest: false, opacity: 0 });
  if (texture) material.map = texture;
  const sprite = new THREE.Sprite(material);
  sprite.renderOrder = 12;
  sprite.userData.aspect = width / height;
  return { sprite, texture };
}

export function PublicMotor3D({
  config,
  resetSignal,
  rotorAngleDeg,
  explodedAmount,
  introProgress = null,
  onInteraction,
  onComponentSelect,
}: PublicMotor3DProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rotorRef = useRef<THREE.Group | null>(null);
  const bearingRigsRef = useRef<BearingAnimationRig[]>([]);
  const resetCameraRef = useRef<(() => void) | null>(null);
  const explodedAmountRef = useRef(explodedAmount);
  const introProgressRef = useRef(introProgress);
  const onInteractionRef = useRef(onInteraction);
  const onComponentSelectRef = useRef(onComponentSelect);
  const [failed, setFailed] = useState(false);
  const [hiddenParts, setHiddenParts] = useState<ReadonlySet<HideablePartId>>(
    () => new Set<HideablePartId>(DEFAULT_HIDDEN_PARTS),
  );
  // Mirrored into a ref so a scene rebuild (config change) can restore whatever
  // the user had hidden instead of snapping everything back on.
  const hiddenPartsRef = useRef(hiddenParts);
  const applyPartVisibilityRef = useRef<((hidden: ReadonlySet<HideablePartId>) => void) | null>(null);

  const togglePart = (part: HideablePartId) => {
    setHiddenParts((current) => {
      const next = new Set(current);
      if (!next.delete(part)) next.add(part);
      return next;
    });
  };

  useEffect(() => {
    hiddenPartsRef.current = hiddenParts;
    applyPartVisibilityRef.current?.(hiddenParts);
  }, [hiddenParts]);

  useEffect(() => {
    onComponentSelectRef.current = onComponentSelect;
  }, [onComponentSelect]);

  useEffect(() => {
    onInteractionRef.current = onInteraction;
  }, [onInteraction]);

  useEffect(() => {
    introProgressRef.current = introProgress;
  }, [introProgress]);

  useEffect(() => {
    const host = hostRef.current;
    const canvas = canvasRef.current;
    if (!host || !canvas) return undefined;

    let animationFrame = 0;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    } catch {
      setFailed(true);
      return undefined;
    }
    setFailed(false);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.02;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 5_000);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.enablePan = false;
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let pointerDownPosition: [number, number] = [0, 0];
    let selectionHelper: THREE.BoxHelper | null = null;

    const outerRadius = config.stator.OD_mm / 2;
    const statorInnerRadius = config.stator.ID_mm / 2;
    const yokeInnerRadius = Math.max(statorInnerRadius + 2, outerRadius - config.stator.yoke_thickness_mm);
    const rotorRadius = config.rotor.OD_mm / 2;
    const shaftRadius = Math.max(outerRadius * 0.055, (config.rotor.ID_mm || outerRadius * 0.12) / 2);
    const stackDepth = Math.max(8, config.stator.stack_length_mm);
    const coilDepth = stackDepth * 0.82;
    // Housing proportions. Both parts are illustrative, so every number here is
    // taken off the solved radii rather than from a solved dimension. The cap
    // stands clear of the stack ends and the bearing seats inside its bore.
    const capBoreRadius = Math.max(shaftRadius * 1.95, outerRadius * 0.16);
    const capThickness = stackDepth * 0.115;
    const capCenterZ = stackDepth / 2 + stackDepth * 0.13 + capThickness / 2;
    const capOuterFaceZ = capCenterZ + capThickness / 2;
    // Frame off whichever dimension actually drives the silhouette. Keying the
    // camera off the radius alone puts a long-stack machine half outside the
    // view before the explode even starts, and the max() only ever pulls back,
    // so nothing shorter than a 2.4:1 stack-to-radius machine moves at all.
    const framingRadius = Math.max(outerRadius, stackDepth * 0.42);
    const assembledCameraPosition = new THREE.Vector3(
      framingRadius * 2.45,
      framingRadius * 1.8,
      framingRadius * 2.7,
    );
    // The exploded row reaches far past the old fixed far plane on a long stack.
    camera.far = Math.max(5_000, stackDepth * 45);
    camera.updateProjectionMatrix();
    // How far back the explode has to dolly to hold the whole teardown. The
    // drive end travels TOWARD the camera, so perspective magnifies it and
    // pushes it off-frame well before the rear end runs out of room — this has
    // to clear the near end, not the row's half-length.
    const explodedFitDistance = Math.max(outerRadius * 7.6, stackDepth * 12);
    const crossSectionCameraPosition = new THREE.Vector3(0, 0, outerRadius * 3.45);

    const resetCamera = () => {
      camera.position.copy(assembledCameraPosition);
      camera.lookAt(0, 0, 0);
      controls.target.set(0, 0, 0);
      controls.minDistance = outerRadius * 1.3;
      // The explode lays its row out in stack lengths, so a long-stack machine
      // needs to dolly much further back than its radius alone would suggest.
      // A radius-only ceiling clamps the exploded pull-back below and leaves the
      // camera buried inside the stator.
      controls.maxDistance = Math.max(outerRadius * 10, stackDepth * 13);
      controls.update();
    };
    resetCameraRef.current = resetCamera;
    resetCamera();

    const pmrem = new THREE.PMREMGenerator(renderer);
    const environmentTarget = pmrem.fromScene(new RoomEnvironment(), 0.04);
    scene.environment = environmentTarget.texture;
    scene.environmentIntensity = 0.62;
    pmrem.dispose();

    // Warm-biased rig. The ambient was pure white and the hemisphere sky a cool
    // blue-white, which on a grey stator read as flat daylight; the key was only
    // faintly warm, so the blue fill and cyan rim set the overall cast. The key is
    // clearly warm now and the ambient/sky carry a little amber, while the fill stays
    // slightly cool so the shaded side still separates from the lit side.
    scene.add(new THREE.AmbientLight(0xffe4c4, 0.30));
    scene.add(new THREE.HemisphereLight(0xffe2bd, 0x171310, 0.52));
    const key = new THREE.DirectionalLight(0xffdcae, 1.62);
    key.position.set(outerRadius * 2, outerRadius * 2.4, outerRadius * 2.6);
    key.castShadow = true;
    key.shadow.mapSize.set(1_024, 1_024);
    key.shadow.camera.left = -outerRadius * 2.4;
    key.shadow.camera.right = outerRadius * 2.4;
    key.shadow.camera.top = outerRadius * 2.4;
    key.shadow.camera.bottom = -outerRadius * 2.4;
    key.shadow.camera.near = 1;
    key.shadow.camera.far = outerRadius * 8;
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xbcd4f0, 0.56);
    fill.position.set(-outerRadius * 2.2, outerRadius * 0.8, outerRadius * 1.4);
    scene.add(fill);
    const rim = new THREE.DirectionalLight(0x67e8f9, 0.58);
    rim.position.set(-outerRadius * 2, -outerRadius, outerRadius * 1.2);
    scene.add(rim);
    const warmRim = new THREE.DirectionalLight(0xffb347, 0.42);
    warmRim.position.set(outerRadius * 0.8, -outerRadius * 2.1, -outerRadius);
    scene.add(warmRim);

    const materials = {
      stator: new THREE.MeshPhysicalMaterial({
        color: renderTargetColor(PUBLIC_MOTOR_COLORS.statorSteel),
        // Dropped from 0.78: at high metalness the environment map, not the base
        // colour, decides what the steel looks like, which is what pulled the 3D
        // stator away from the 2D fill however the colour was set.
        metalness: 0.62,
        // Roughened and de-coated from 0.34/0.20. The clearcoat laid a second
        // specular sheet on top of the metal, and on a surface as large as the
        // housing the two blew out to white wherever the view grazed it.
        roughness: 0.47,
        clearcoat: 0.06,
        clearcoatRoughness: 0.45,
        // The studio environment is neutral and bright; at full strength it, not
        // the palette, decided how light the steel looked.
        envMapIntensity: 0.55,
      }),
      tooth: new THREE.MeshPhysicalMaterial({
        color: renderTargetColor(PUBLIC_MOTOR_COLORS.statorTooth),
        metalness: 0.56,
        roughness: 0.48,
        clearcoat: 0.05,
        clearcoatRoughness: 0.45,
        envMapIntensity: 0.55,
      }),
      rotor: new THREE.MeshPhysicalMaterial({
        color: 0x36465c,
        metalness: 0.68,
        roughness: 0.46,
        clearcoat: 0.05,
        clearcoatRoughness: 0.5,
        envMapIntensity: 0.55,
        transparent: config.topology === 'IPM',
        opacity: config.topology === 'IPM' ? 0.68 : 1,
        depthWrite: config.topology !== 'IPM',
      }),
      // End-cap faces of the rotor core: same steel, but the fine square
      // grid makes the spin visible. White base colour so the map carries the tint.
      rotorFace: new THREE.MeshPhysicalMaterial({
        color: 0xffffff,
        map: makeRotorFaceTexture(),
        metalness: 0.68,
        roughness: 0.46,
        clearcoat: 0.05,
        clearcoatRoughness: 0.5,
        envMapIntensity: 0.55,
        transparent: config.topology === 'IPM',
        opacity: config.topology === 'IPM' ? 0.68 : 1,
        depthWrite: config.topology !== 'IPM',
      }),
      shaft: new THREE.MeshPhysicalMaterial({
        // Was 0.96 metal at 0.16 roughness with a 0.45 coat — a mirror, which
        // clipped to pure white in the middle of the face-on view. Machined steel,
        // not chrome.
        color: 0xaeb8c6,
        metalness: 0.8,
        roughness: 0.33,
        clearcoat: 0.12,
        clearcoatRoughness: 0.32,
        envMapIntensity: 0.5,
      }),
      magnetNorth: new THREE.MeshPhysicalMaterial({
        color: renderTargetColor(PUBLIC_MOTOR_COLORS.magnetNorth),
        emissive: 0x3d090c,
        metalness: 0.2,
        roughness: 0.28,
        // Halved from 0.52: a strong clearcoat lays a white specular sheet over
        // the whole face, which is most of why the magnets read pastel.
        clearcoat: 0.26,
        clearcoatRoughness: 0.3,
      }),
      magnetSouth: new THREE.MeshPhysicalMaterial({
        color: renderTargetColor(PUBLIC_MOTOR_COLORS.magnetSouth),
        emissive: 0x071d42,
        metalness: 0.2,
        roughness: 0.28,
        clearcoat: 0.26,
        clearcoatRoughness: 0.3,
      }),
      // The opposite half has the same magnetic material as the airgap-facing
      // half. Separate materials keep its polarity explicit while orbiting or
      // hiding the rotor core.
      oppositeNorth: new THREE.MeshPhysicalMaterial({
        color: renderTargetColor(PUBLIC_MOTOR_COLORS.magnetNorth),
        emissive: 0x5b0c12,
        metalness: 0.12,
        roughness: 0.24,
        clearcoat: 0.18,
      }),
      oppositeSouth: new THREE.MeshPhysicalMaterial({
        color: renderTargetColor(PUBLIC_MOTOR_COLORS.magnetSouth),
        emissive: 0x0a2d63,
        metalness: 0.12,
        roughness: 0.24,
        clearcoat: 0.18,
      }),
      // Render only the inward-facing walls of the slightly oversized box.
      // From outside this reads as a hollow lamination pocket rather than a
      // second solid laid over the translucent rotor.
      pocket: new THREE.MeshPhysicalMaterial({
        color: 0x101722,
        emissive: 0x02060b,
        metalness: 0.04,
        roughness: 0.84,
        transparent: true,
        opacity: 0.88,
        depthWrite: false,
        side: THREE.BackSide,
      }),
      phaseA: phaseMaterial(PUBLIC_PHASE_COLORS.A),
      phaseB: phaseMaterial(PUBLIC_PHASE_COLORS.B),
      phaseC: phaseMaterial(PUBLIC_PHASE_COLORS.C),
      coilA: enamelledCopperMaterial(renderTargetColor(PUBLIC_PHASE_COLORS.A)),
      coilB: enamelledCopperMaterial(renderTargetColor(PUBLIC_PHASE_COLORS.B)),
      coilC: enamelledCopperMaterial(renderTargetColor(PUBLIC_PHASE_COLORS.C)),
      liner: new THREE.MeshPhysicalMaterial({
        color: 0xf1ead8,
        metalness: 0.02,
        roughness: 0.72,
        clearcoat: 0.06,
        clearcoatRoughness: 0.5,
      }),
      // Cast housing — deliberately lighter and flatter than the stator
      // lamination above. Exploded, the caps join a row of grey discs, and a
      // dark casting just reads as more anonymous steel; the lift is what tells
      // an aluminium cap apart at a glance. `transparent` is pinned on so
      // applyExplosion can ramp opacity every frame without a shader recompile.
      endcap: new THREE.MeshPhysicalMaterial({
        color: 0xa9b6c7,
        metalness: 0.42,
        roughness: 0.6,
        clearcoat: 0.05,
        clearcoatRoughness: 0.55,
        envMapIntensity: 0.6,
        transparent: true,
        opacity: ENDCAP_ASSEMBLED_OPACITY,
      }),
      // The rear cap is solid: nothing sits behind it to read through, so its
      // only job is to close the machine off. Only the drive-end cap — the one
      // between the camera and the end windings — stays a shell.
      endcapRear: new THREE.MeshPhysicalMaterial({
        color: 0xa9b6c7,
        metalness: 0.42,
        roughness: 0.6,
        clearcoat: 0.05,
        clearcoatRoughness: 0.55,
        envMapIntensity: 0.6,
      }),
      bearingRace: new THREE.MeshPhysicalMaterial({
        color: 0xa8b4c4,
        metalness: 0.82,
        roughness: 0.3,
        clearcoat: 0.12,
        clearcoatRoughness: 0.3,
        envMapIntensity: 0.5,
      }),
      bearingBall: new THREE.MeshPhysicalMaterial({
        // A near-white mirror ball reads as a light bulb at this scale.
        color: 0xccd5e1,
        metalness: 0.88,
        roughness: 0.22,
        clearcoat: 0.14,
        clearcoatRoughness: 0.28,
        envMapIntensity: 0.5,
      }),
      bearingCage: new THREE.MeshPhysicalMaterial({
        color: 0xd0a557,
        metalness: 0.7,
        roughness: 0.36,
        clearcoat: 0.2,
      }),
      bearingMotionMark: new THREE.MeshPhysicalMaterial({
        color: 0x263241,
        metalness: 0.58,
        roughness: 0.5,
        clearcoat: 0.08,
      }),
    };
    const geometries: THREE.BufferGeometry[] = [];

    const makeSelectable = (object: THREE.Object3D, selection: PublicMotorComponentSelection) => {
      object.userData.publicMotorSelection = selection;
    };

    const addEdges = (mesh: THREE.Mesh, color = 0x202938) => {
      const edgeGeometry = new THREE.EdgesGeometry(mesh.geometry, 22);
      geometries.push(edgeGeometry);
      const edges = new THREE.LineSegments(
        edgeGeometry,
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.3 }),
      );
      mesh.add(edges);
    };

    interface RadialExplodable {
      object: THREE.Object3D;
      basePosition: THREE.Vector3;
      direction: THREE.Vector3;
      distance: number;
    }
    const radialExplodables: RadialExplodable[] = [];
    const registerRadialExplosion = (
      object: THREE.Object3D,
      angle: number,
      distance: number,
    ) => {
      radialExplodables.push({
        object,
        basePosition: object.position.clone(),
        direction: new THREE.Vector3(Math.cos(angle), Math.sin(angle), 0),
        distance,
      });
    };

    const statorGroup = new THREE.Group();
    const teethGroup = new THREE.Group();
    const windingsGroup = new THREE.Group();
    const yokeGeometry = extrude(ringShape(outerRadius, yokeInnerRadius), stackDepth);
    geometries.push(yokeGeometry);
    const yoke = new THREE.Mesh(yokeGeometry, materials.stator);
    makeSelectable(yoke, { id: '3d-stator-yoke', kind: 'stator', label: 'Stator yoke', role: 'Stationary magnetic flux path' });
    addEdges(yoke);
    statorGroup.add(yoke);

    const slotPitch = (Math.PI * 2) / Math.max(1, config.stator.slot_count);
    const statorWidths = deriveStatorSectionWidths(config);
    const toothHalfInner = Math.min(
      slotPitch * 0.499,
      statorWidths.boreToothWidthMm / Math.max(statorInnerRadius, 1) / 2,
    );
    const toothHalfOuter = Math.min(
      slotPitch * 0.499,
      statorWidths.toothWidthAtYokeMm / Math.max(yokeInnerRadius, 1) / 2,
    );
    let coilBoreRadius = statorInnerRadius;
    let coilToothHalfInner = toothHalfInner;
    let toothShape: THREE.Shape;
    if (config.stator.tooth_shoe_enabled) {
      const shoeHeight = Math.max(0.5, config.stator.tooth_shoe_height_mm ?? 1.5);
      const shoulderRadius = Math.min(
        statorInnerRadius + shoeHeight,
        yokeInnerRadius - 1e-4,
      );
      const shoeOverhang = Math.max(0, config.stator.tooth_shoe_overhang_mm ?? 0);
      const bodyToothWidthAtBore = Math.max(
        0,
        statorWidths.boreToothWidthMm - 2 * shoeOverhang,
      );
      const bodyHalfInner = Math.min(
        slotPitch * 0.499,
        bodyToothWidthAtBore / Math.max(statorInnerRadius, 1) / 2,
      );
      const shoulderFraction = THREE.MathUtils.clamp(
        (shoulderRadius - statorInnerRadius)
          / Math.max(1e-6, yokeInnerRadius - statorInnerRadius),
        0,
        1,
      );
      const shoulderHalf = THREE.MathUtils.lerp(
        bodyHalfInner,
        toothHalfOuter,
        shoulderFraction,
      );
      toothShape = shoedToothShape(
        statorInnerRadius,
        shoulderRadius,
        yokeInnerRadius,
        toothHalfInner,
        shoulderHalf,
        toothHalfOuter,
      );
      // A real concentrated coil sits behind the shoe rather than wrapping its
      // widened tip. Start the racetrack bundle at the body shoulder so copper
      // and slot liner do not intersect the new ledge.
      coilBoreRadius = shoulderRadius;
      coilToothHalfInner = shoulderHalf;
    } else {
      toothShape = taperedToothShape(
        statorInnerRadius,
        yokeInnerRadius,
        toothHalfInner,
        toothHalfOuter,
      );
    }
    const toothGeometry = extrude(toothShape, stackDepth);
    geometries.push(toothGeometry);

    const concentratedCoil = config.winding.type === 'concentrated'
      ? buildConcentratedCoil({
          boreRadius: coilBoreRadius,
          yokeInnerRadius,
          toothHalfAngleInnerRad: coilToothHalfInner,
          toothHalfAngleOuterRad: toothHalfOuter,
          slotPitchRad: slotPitch,
          stackLength: stackDepth,
          turnsPerCoil: config.winding.turns_per_coil,
        })
      : null;
    let coilModelNote = '';
    if (concentratedCoil) {
      geometries.push(concentratedCoil.geometry, concentratedCoil.linerGeometry);
      const turnsNote = concentratedCoil.strandCount >= concentratedCoil.turnsRepresented
        ? `all ${concentratedCoil.turnsRepresented} turns modeled`
        : `${concentratedCoil.strandCount} strands representing ${concentratedCoil.turnsRepresented} turns`;
      const bundleNote = concentratedCoil.wireLayers === 1
        ? `single wire layer × ${concentratedCoil.turnsPerLayer}`
        : `${concentratedCoil.wireLayers} wire layers × ${concentratedCoil.turnsPerLayer} per layer`;
      coilModelNote = `${turnsNote} · ${bundleNote}`;
    }

    for (let slot = 0; slot < config.stator.slot_count; slot += 1) {
      const angle = slot * slotPitch;
      const tooth = new THREE.Mesh(toothGeometry, materials.tooth);
      tooth.rotation.z = angle;
      makeSelectable(tooth, { id: `3d-stator-tooth-${slot + 1}`, kind: 'stator', label: `Stator tooth ${slot + 1}`, role: 'Stationary magnetic flux path', slotIndex: slot + 1 });
      teethGroup.add(tooth);
      registerRadialExplosion(tooth, angle, outerRadius * 0.075);

      const phase = (['A', 'C', 'B'] as const)[slot % 3];
      const direction = slot % 2 === 0 ? '+' : '-';
      if (concentratedCoil) {
        const coilMaterial = { A: materials.coilA, B: materials.coilB, C: materials.coilC }[phase];
        const coilAssembly = new THREE.Group();
        coilAssembly.add(
          new THREE.Mesh(concentratedCoil.linerGeometry, materials.liner),
          new THREE.Mesh(concentratedCoil.geometry, coilMaterial),
        );
        coilAssembly.rotation.z = angle;
        makeSelectable(coilAssembly, {
          id: `3d-winding-${slot + 1}`,
          kind: 'winding',
          label: `Tooth ${slot + 1} coil · phase ${phase}${direction}`,
          role: 'Concentrated coil wound around the stator tooth',
          slotIndex: slot + 1,
          phase,
          direction,
          windingModel: coilModelNote,
        });
        windingsGroup.add(coilAssembly);
        registerRadialExplosion(coilAssembly, angle, outerRadius * 0.16);
      } else {
        const coilHalfSpan = Math.max(0.04, slotPitch * 0.18);
        const coilGeometry = extrude(
          sectorShape(statorInnerRadius + 1.2, Math.max(statorInnerRadius + 2, yokeInnerRadius - 1), coilHalfSpan),
          coilDepth,
        );
        geometries.push(coilGeometry);
        const phaseMaterial = { A: materials.phaseA, B: materials.phaseB, C: materials.phaseC }[phase];
        const coil = new THREE.Mesh(coilGeometry, phaseMaterial);
        coil.rotation.z = angle + slotPitch / 2;
        makeSelectable(coil, { id: `3d-winding-${slot + 1}`, kind: 'winding', label: `Slot ${slot + 1} · phase ${phase}${direction}`, role: 'Current-carrying stator winding', slotIndex: slot + 1, phase, direction });
        windingsGroup.add(coil);
        registerRadialExplosion(coil, angle + slotPitch / 2, outerRadius * 0.16);
      }
    }
    scene.add(statorGroup, teethGroup, windingsGroup);

    let harnessGroup: THREE.Group | null = null;
    const harnessMaterials: THREE.MeshPhysicalMaterial[] = [];
    if (concentratedCoil) {
      const harness = buildWindingHarness({
        slotCount: config.stator.slot_count,
        slotPitchRad: slotPitch,
        phaseOfSlot: (slot) => (['A', 'C', 'B'] as const)[slot % 3],
        bundleCenterRadius: concentratedCoil.bundleCenterRadius,
        stackHalf: stackDepth / 2,
        axialOverhang: concentratedCoil.axialOverhang,
        wireRadius: concentratedCoil.wireRadius,
        yokeInnerRadius,
        outerRadius,
      });
      harnessGroup = new THREE.Group();
      (['A', 'B', 'C'] as const).forEach((phase) => {
        const geometry = harness.phaseGeometries[phase];
        if (!geometry) return;
        geometries.push(geometry);
        const material = enamelledCopperMaterial(
          renderTargetColor(PUBLIC_PHASE_COLORS[phase]),
          true,
        );
        harnessMaterials.push(material);
        const mesh = new THREE.Mesh(geometry, material);
        makeSelectable(mesh, {
          id: `3d-harness-${phase}`,
          kind: 'harness',
          label: `Phase ${phase} rear links · drive lead`,
          role: 'Series jumpers joining the phase coils behind the stack, out to the drive lead',
          phase,
        });
        harnessGroup?.add(mesh);
      });
      if (harness.neutralGeometry) {
        geometries.push(harness.neutralGeometry);
        const neutralMaterial = new THREE.MeshPhysicalMaterial({
          color: 0xdfe5ec,
          metalness: 0.35,
          roughness: 0.42,
          clearcoat: 0.3,
          transparent: true,
        });
        harnessMaterials.push(neutralMaterial);
        const neutral = new THREE.Mesh(harness.neutralGeometry, neutralMaterial);
        makeSelectable(neutral, {
          id: '3d-harness-star',
          kind: 'harness',
          label: 'Star point (wye)',
          role: 'Neutral junction tying the three phase tails together inside the motor',
        });
        harnessGroup.add(neutral);
      }
      geometries.push(harness.terminalGeometry);
      const terminalMaterial = new THREE.MeshPhysicalMaterial({
        color: 0x2b3442,
        metalness: 0.5,
        roughness: 0.4,
        clearcoat: 0.2,
        transparent: true,
      });
      harnessMaterials.push(terminalMaterial);
      const terminal = new THREE.Mesh(harness.terminalGeometry, terminalMaterial);
      makeSelectable(terminal, {
        id: '3d-harness-terminal',
        kind: 'harness',
        label: 'Drive lead terminal',
        role: 'Phase leads U · V · W exit here toward the motor drive',
      });
      harnessGroup.add(terminal);
      scene.add(harnessGroup);
    }

    const rotorGroup = new THREE.Group();
    const rotorCoreGroup = new THREE.Group();
    const pocketsGroup = new THREE.Group();
    const magnetsGroup = new THREE.Group();
    const shaftGroup = new THREE.Group();
    rotorCoreGroup.add(pocketsGroup);
    rotorGroup.add(rotorCoreGroup, magnetsGroup, shaftGroup);
    rotorRef.current = rotorGroup;
    const coreGeometry = new THREE.CylinderGeometry(rotorRadius, rotorRadius, stackDepth, 96);
    coreGeometry.rotateX(Math.PI / 2);
    geometries.push(coreGeometry);
    // Material array: CylinderGeometry groups are side, top cap, bottom cap.
    // Only the caps carry the grid so the spin reads on the end faces while
    // the side keeps the plain (and for IPM, translucent) lamination finish.
    const core = new THREE.Mesh(coreGeometry, [materials.rotor, materials.rotorFace, materials.rotorFace]);
    makeSelectable(core, { id: '3d-rotor-core', kind: 'rotor', label: 'Rotor core', role: 'Rotating magnetic flux path' });
    addEdges(core);
    rotorCoreGroup.add(core);

    // Drive-end convention: the shaft runs long out the front face toward the
    // load, with only a short stub behind the rear bearing plane. Both ends are
    // measured off the cap's outer face so the shaft always passes through both
    // castings — a visible drive stub at the front, just enough to read as
    // supported at the rear.
    const shaftCapClearance = capOuterFaceZ - stackDepth / 2;
    const shaftFrontOverhang = Math.max(stackDepth * 0.34, shaftRadius * 1.6, shaftCapClearance + stackDepth * 0.28);
    const shaftRearStub = shaftCapClearance + stackDepth * 0.06;
    const shaftGeometry = new THREE.CylinderGeometry(
      shaftRadius,
      shaftRadius,
      stackDepth + shaftFrontOverhang + shaftRearStub,
      64,
    );
    shaftGeometry.rotateX(Math.PI / 2);
    shaftGeometry.translate(0, 0, (shaftFrontOverhang - shaftRearStub) / 2);
    geometries.push(shaftGeometry);
    const shaft = new THREE.Mesh(shaftGeometry, materials.shaft);
    makeSelectable(shaft, { id: '3d-shaft', kind: 'shaft', label: 'Shaft', role: 'Mechanical rotor support' });
    shaftGroup.add(shaft);

    // Drive key on the exposed stub. The shaft already turns with the rotor —
    // it is a child of rotorGroup — but a plain cylinder is its own surface of
    // revolution, so every frame of that rotation renders identically and the
    // shaft reads as standing still next to the visibly turning magnets. The
    // key is what a real shaft carries to drive a load, and it gives the
    // rotation something to show. Parented to the shaft MESH, not the group,
    // so clicking it still resolves to the shaft's own selection.
    const shaftEndZ = stackDepth / 2 + shaftFrontOverhang;
    const keyLength = Math.max(1, (shaftEndZ - capOuterFaceZ) * 0.62);
    const keyGeometry = new THREE.BoxGeometry(
      Math.max(0.5, shaftRadius * 0.44),
      Math.max(0.4, shaftRadius * 0.3),
      keyLength,
    );
    geometries.push(keyGeometry);
    const shaftKey = new THREE.Mesh(keyGeometry, materials.shaft);
    // Seated on the shaft surface, standing a little proud of it.
    shaftKey.position.set(0, shaftRadius * 0.94, (capOuterFaceZ + shaftEndZ) / 2);
    shaft.add(shaftKey);

    const polePitch = (Math.PI * 2) / Math.max(1, config.rotor.pole_count);
    if (config.topology === 'SPM') {
      const magnetInnerRadius = rotorRadius;
      const magnetOuterRadius = rotorRadius + config.rotor.magnet_thickness_mm;
      const magnetSplitRadius = (magnetInnerRadius + magnetOuterRadius) / 2;
      const magnetHalfSpan = Math.max(0.04, polePitch * config.rotor.magnet_embrace / 2);
      const airgapHalfGeometry = extrude(
        sectorShape(magnetSplitRadius, magnetOuterRadius, magnetHalfSpan),
        stackDepth * 0.91,
      );
      const rotorHalfGeometry = extrude(
        sectorShape(magnetInnerRadius, magnetSplitRadius, magnetHalfSpan),
        stackDepth * 0.91,
      );
      geometries.push(airgapHalfGeometry, rotorHalfGeometry);
      for (let pole = 0; pole < config.rotor.pole_count; pole += 1) {
        const northAtAirgap = pole % 2 === 0;
        const magnetUnit = new THREE.Group();
        const airgapHalf = new THREE.Mesh(
          airgapHalfGeometry,
          northAtAirgap ? materials.magnetNorth : materials.magnetSouth,
        );
        const rotorHalf = new THREE.Mesh(
          rotorHalfGeometry,
          northAtAirgap ? materials.oppositeSouth : materials.oppositeNorth,
        );
        magnetUnit.rotation.z = pole * polePitch;
        makeSelectable(magnetUnit, {
          id: `3d-magnet-${pole + 1}`,
          kind: 'magnet',
          label: `Magnet ${northAtAirgap ? 'N' : 'S'} · pole ${pole + 1}`,
          role: 'Complete permanent-magnet dipole with airgap- and rotor-facing poles',
          poleIndex: pole + 1,
        });
        addEdges(airgapHalf, northAtAirgap ? 0x7f1d1d : 0x1e3a8a);
        addEdges(rotorHalf, northAtAirgap ? 0x1e3a8a : 0x7f1d1d);
        magnetUnit.add(airgapHalf, rotorHalf);
        magnetsGroup.add(magnetUnit);
        registerRadialExplosion(magnetUnit, pole * polePitch, rotorRadius * 0.14);
      }
    } else if (config.rotor.ipm_topology === 'v_shape') {
      const magnetDepth = Math.max(1, config.rotor.magnet_thickness_mm);
      const magnetAxialDepth = stackDepth * 0.92;
      const pocketAxialDepth = stackDepth * 0.98;
      const pocketClearance = Math.max(0.25, config.rotor.pocket_clearance_mm || 0);
      const angleOffset = config.rotor.magnet_angle_deg * Math.PI / 180;
      for (let pole = 0; pole < config.rotor.pole_count; pole += 1) {
        const poleAngle = pole * polePitch + angleOffset;
        for (const sideSign of [1, -1] as const) {
          const placement = vShapeMagnetPlacement(config, poleAngle, sideSign);
          const pocketGeometry = new THREE.BoxGeometry(
            placement.effectiveLengthMm + pocketClearance * 2,
            magnetDepth + pocketClearance * 2,
            pocketAxialDepth,
          );
          const magnetHalfGeometry = new THREE.BoxGeometry(
            placement.effectiveLengthMm,
            magnetDepth / 2,
            magnetAxialDepth,
          );
          geometries.push(pocketGeometry, magnetHalfGeometry);
          const northAtAirgap = pole % 2 === 0;
          const pocket = new THREE.Mesh(pocketGeometry, materials.pocket);
          const magnetUnit = new THREE.Group();
          const airgapHalf = new THREE.Mesh(
            magnetHalfGeometry,
            northAtAirgap ? materials.magnetNorth : materials.magnetSouth,
          );
          const oppositeHalf = new THREE.Mesh(
            magnetHalfGeometry,
            northAtAirgap ? materials.oppositeSouth : materials.oppositeNorth,
          );
          airgapHalf.position.y = -sideSign * magnetDepth / 4;
          oppositeHalf.position.y = sideSign * magnetDepth / 4;
          pocket.position.set(placement.centerX, placement.centerY, 0);
          pocket.rotation.z = placement.axisAngleRad;
          pocket.renderOrder = 2;
          magnetUnit.position.set(placement.centerX, placement.centerY, 0);
          magnetUnit.rotation.z = placement.axisAngleRad;
          makeSelectable(pocket, {
            id: `3d-magnet-pocket-${pole + 1}-${placement.side}`,
            kind: 'rotor',
            label: `V magnet pocket ${placement.side} · pole ${pole + 1}`,
            role: 'Lamination cavity and insertion clearance around the buried magnet',
            poleIndex: pole + 1,
          });
          makeSelectable(magnetUnit, {
            id: `3d-magnet-${pole + 1}-${placement.side}`,
            kind: 'magnet',
            label: `V magnet ${placement.side} · ${northAtAirgap ? 'N' : 'S'} · pole ${pole + 1}`,
            role: 'Complete permanent-magnet dipole with both pole halves',
            poleIndex: pole + 1,
          });
          addEdges(pocket, 0x0b1220);
          addEdges(airgapHalf, northAtAirgap ? 0x7f1d1d : 0x1e3a8a);
          addEdges(oppositeHalf, northAtAirgap ? 0x1e3a8a : 0x7f1d1d);
          pocketsGroup.add(pocket);
          magnetUnit.add(airgapHalf, oppositeHalf);
          magnetsGroup.add(magnetUnit);
          registerRadialExplosion(magnetUnit, poleAngle, rotorRadius * 0.16);
        }
      }
    } else if (config.rotor.flat_buried_magnet_shape === 'legacy_arc') {
      const magnetCenterRadius = publicFlatIpmMagnetCenterRadiusMm(config);
      const magnetInnerRadius = magnetCenterRadius - config.rotor.magnet_thickness_mm / 2;
      const magnetOuterRadius = magnetCenterRadius + config.rotor.magnet_thickness_mm / 2;
      const magnetHalfSpan = magnetCenterRadius > 0
        ? config.rotor.magnet_width_mm / (2 * magnetCenterRadius)
        : 0;
      const magnetGeometry = extrude(
        sectorShape(magnetInnerRadius, magnetOuterRadius, magnetHalfSpan),
        stackDepth * 0.92,
      );
      geometries.push(magnetGeometry);
      const angleOffset = config.rotor.magnet_angle_deg * Math.PI / 180;
      for (let pole = 0; pole < config.rotor.pole_count; pole += 1) {
        const angle = pole * polePitch + angleOffset;
        const magnet = new THREE.Mesh(
          magnetGeometry,
          pole % 2 === 0 ? materials.magnetNorth : materials.magnetSouth,
        );
        magnet.rotation.z = angle;
        makeSelectable(magnet, {
          id: `3d-magnet-${pole + 1}`,
          kind: 'magnet',
          label: `Legacy curved magnet ${pole % 2 === 0 ? 'N' : 'S'} · pole ${pole + 1}`,
          role: 'Compatibility geometry retained from a pre-v4 project',
          poleIndex: pole + 1,
        });
        addEdges(magnet, pole % 2 === 0 ? 0x7f1d1d : 0x1e3a8a);
        magnetsGroup.add(magnet);
        registerRadialExplosion(magnet, angle, rotorRadius * 0.16);
      }
    } else {
      const magnetWidth = config.rotor.magnet_width_mm;
      const magnetDepth = config.rotor.magnet_thickness_mm;
      const pocketClearance = config.rotor.pocket_clearance_mm ?? 0;
      const magnetCenterRadius = publicFlatIpmMagnetCenterRadiusMm(config);
      const magnetGeometry = new THREE.BoxGeometry(magnetWidth, magnetDepth, stackDepth * 0.92);
      const pocketGeometry = new THREE.BoxGeometry(
        magnetWidth + pocketClearance * 2,
        magnetDepth + pocketClearance * 2,
        stackDepth * 0.98,
      );
      geometries.push(magnetGeometry, pocketGeometry);
      const angleOffset = config.rotor.magnet_angle_deg * Math.PI / 180;
      for (let pole = 0; pole < config.rotor.pole_count; pole += 1) {
        const angle = pole * polePitch + angleOffset;
        const magnet = new THREE.Mesh(magnetGeometry, pole % 2 === 0 ? materials.magnetNorth : materials.magnetSouth);
        const pocket = new THREE.Mesh(pocketGeometry, materials.pocket);
        magnet.position.set(
          Math.cos(angle) * magnetCenterRadius,
          Math.sin(angle) * magnetCenterRadius,
          0,
        );
        magnet.rotation.z = angle + Math.PI / 2;
        pocket.position.copy(magnet.position);
        pocket.rotation.copy(magnet.rotation);
        pocket.renderOrder = 2;
        makeSelectable(pocket, {
          id: `3d-magnet-pocket-${pole + 1}`,
          kind: 'rotor',
          label: `Buried magnet pocket · pole ${pole + 1}`,
          role: 'Lamination cavity and insertion clearance around the buried magnet',
          poleIndex: pole + 1,
        });
        makeSelectable(magnet, { id: `3d-magnet-${pole + 1}`, kind: 'magnet', label: `Buried magnet ${pole % 2 === 0 ? 'N' : 'S'} · pole ${pole + 1}`, role: 'Permanent-magnet field source', poleIndex: pole + 1 });
        addEdges(pocket, 0x0b1220);
        addEdges(magnet, pole % 2 === 0 ? 0x7f1d1d : 0x1e3a8a);
        pocketsGroup.add(pocket);
        magnetsGroup.add(magnet);
        registerRadialExplosion(magnet, angle, rotorRadius * 0.16);
      }
    }
    scene.add(rotorGroup);

    // Bearings and end caps — illustrative housing, not solved geometry. Every
    // group hangs off the scene rather than rotorGroup: a bolted cap and a
    // stationary outer race do not turn with the rotor. Each END gets its own
    // pair of groups so the drive-end cap and bearing come off the front with
    // the shaft while the rear pair comes off the back — a teardown pulls each
    // cap off its own end rather than stacking both behind the stator.
    const driveBearingGroup = new THREE.Group();
    const driveEndcapGroup = new THREE.Group();
    const rearBearingGroup = new THREE.Group();
    const rearEndcapGroup = new THREE.Group();
    const bearingRigs: BearingAnimationRig[] = [];
    const bearingWidth = stackDepth * 0.13;
    [1, -1].forEach((zSign) => {
      const isDriveEnd = zSign > 0;
      const end = isDriveEnd ? 'drive' : 'non-drive';

      const bearing = buildBearing(
        { boreRadius: shaftRadius, outerRadius: capBoreRadius, width: bearingWidth },
        {
          race: materials.bearingRace,
          ball: materials.bearingBall,
          cage: materials.bearingCage,
          motionMark: materials.bearingMotionMark,
        },
      );
      geometries.push(...bearing.geometries);
      bearingRigs.push(bearing);
      // Seated in the cap bore, inboard of the cap's outer face — the bearing
      // never hangs off the shaft outside the casting.
      bearing.group.position.z = zSign * capCenterZ;
      makeSelectable(bearing.group, {
        id: `3d-bearing-${end}`,
        kind: 'bearing',
        label: `Bearing · ${end} end`,
        role: 'Outer race fixed to end cap · inner race follows shaft · balls roll in a slower cage · illustrative',
      });
      (isDriveEnd ? driveBearingGroup : rearBearingGroup).add(bearing.group);

      const cap = buildEndCap(
        { boreRadius: capBoreRadius, outerRadius, thickness: capThickness, hubDepth: stackDepth * 0.1 },
        isDriveEnd ? materials.endcap : materials.endcapRear,
      );
      geometries.push(...cap.geometries);
      // Mirror the casting so both hubs reach inboard toward the stack.
      cap.group.scale.z = zSign;
      cap.group.position.z = zSign * capCenterZ;
      makeSelectable(cap.group, {
        id: `3d-endcap-${end}`,
        kind: 'endcap',
        label: `End cap · ${end} end`,
        role: 'Bolted end housing carrying the bearing · illustrative · not part of the EM model',
      });
      (isDriveEnd ? driveEndcapGroup : rearEndcapGroup).add(cap.group);
    });
    bearingRigsRef.current = bearingRigs;
    scene.add(driveBearingGroup, driveEndcapGroup, rearBearingGroup, rearEndcapGroup);

    // The air gap is a volume between two coaxial cylindrical surfaces, not a
    // single circular wire. Draw the complete annular sleeve across the stack.
    const airgapInnerRadius = rotorRadius
      + (config.topology === 'SPM' ? config.rotor.magnet_thickness_mm : 0);
    const airgapGeometry = annulusGeometry(
      airgapInnerRadius,
      statorInnerRadius,
      stackDepth * 0.96,
    );
    geometries.push(airgapGeometry);
    const airgapMaterial = new THREE.MeshPhysicalMaterial({
      color: 0x5ee7f7,
      emissive: 0x063a42,
      metalness: 0,
      roughness: 0.18,
      transparent: true,
      opacity: 0.14,
      clearcoat: 0.8,
      clearcoatRoughness: 0.1,
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    const airgap = new THREE.Mesh(airgapGeometry, airgapMaterial);
    makeSelectable(airgap, { id: '3d-airgap', kind: 'airgap', label: 'Air gap', role: 'Magnetic clearance region' });
    addEdges(airgap, 0x5ee7f7);
    scene.add(airgap);
    scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      object.castShadow = true;
      object.receiveShadow = true;
    });

    // Floating part labels, revealed by the explode. Each chip is parented to
    // the scene and tracks its part's z every frame rather than being parented
    // to the part itself: the rotor, magnet and shaft groups spin with
    // rotorAngleDeg, and a parented chip would orbit the axis with them.
    const partChips: Array<{ sprite: THREE.Sprite; anchor: THREE.Vector3; follows: THREE.Object3D }> = [];
    const chipTextures: THREE.CanvasTexture[] = [];
    // Sized off the distance the chips are actually READ from, so every machine
    // gets the same apparent chip size. Scaling off a model dimension instead
    // shrinks the chips to an unreadable smudge on a long machine, because the
    // exploded dolly grows faster than the radius does.
    const chipScale = Math.max(8, explodedFitDistance * 0.047);
    const addPartChip = (text: string, follows: THREE.Object3D, anchor: THREE.Vector3) => {
      const { sprite, texture } = makeChipSprite(text);
      if (texture) chipTextures.push(texture);
      sprite.scale.set(chipScale * (sprite.userData.aspect as number) * 0.32, chipScale * 0.32, 1);
      sprite.position.copy(anchor);
      sprite.visible = false;
      // Chips are annotation, not geometry — they must never win a pick.
      sprite.raycast = () => {};
      scene.add(sprite);
      partChips.push({ sprite, anchor, follows });
    };

    // Anchors sit outside their part's silhouette and alternate above/below the
    // axis in chip-position order — not station order, which is not the same
    // thing once the housing anchors add their own offset. Anchoring the
    // bearing chip on the inboard face instead drops it between the yoke and
    // the teeth, which is how the dev viewer ends up captioning the stator body
    // "Bearing". Each housing chip therefore rides its own end's outboard face.
    // Chips hold a constant apparent size, so on a very long stack the lanes
    // have to widen with them or the row's chips overlap even though the parts
    // are well separated. The max() is inert until the stack passes ~2× the OD.
    const chipLane = Math.max(outerRadius, chipScale);
    addPartChip('End cap', rearEndcapGroup, new THREE.Vector3(0, chipLane * 1.3, -capCenterZ));
    addPartChip('Bearing', rearBearingGroup, new THREE.Vector3(0, -chipLane * 1.22, -capCenterZ));
    // Yoke and teeth explode as one part now, so they take one chip between
    // them — two labels on a single station would just stack on each other.
    addPartChip('Stator', statorGroup, new THREE.Vector3(0, chipLane * 1.14, 0));
    addPartChip('Windings', windingsGroup, new THREE.Vector3(0, chipLane * 0.98, 0));
    if (harnessGroup) {
      addPartChip('Phase links', harnessGroup, new THREE.Vector3(0, -chipLane * 0.5, 0));
    }
    addPartChip('Air gap', airgap, new THREE.Vector3(0, -chipLane * 0.9, 0));
    addPartChip('Magnets', magnetsGroup, new THREE.Vector3(0, Math.max(rotorRadius * 1.5, chipLane * 0.82), 0));
    addPartChip('Rotor core', rotorCoreGroup, new THREE.Vector3(0, -Math.max(rotorRadius * 1.28, chipLane * 0.7), 0));
    addPartChip('Shaft', shaftGroup, new THREE.Vector3(0, shaftRadius + chipLane * 0.22, 0));
    addPartChip('Bearing', driveBearingGroup, new THREE.Vector3(0, -chipLane * 1.22, capCenterZ));
    addPartChip('End cap', driveEndcapGroup, new THREE.Vector3(0, chipLane * 1.3, capCenterZ));

    // Show/hide plumbing. Each toggle owns the groups that only read as a part
    // together — hiding the stator without its teeth, or the coils without
    // their rear links, would just leave a fragment floating in the bore.
    const hideableGroups: Record<HideablePartId, THREE.Object3D[]> = {
      stator: [statorGroup, teethGroup],
      windings: harnessGroup ? [windingsGroup, harnessGroup] : [windingsGroup],
      rotor: [rotorCoreGroup],
      magnets: [magnetsGroup],
      airgap: [airgap],
      endcaps: [driveEndcapGroup, rearEndcapGroup],
      bearings: [driveBearingGroup, rearBearingGroup],
      shaft: [shaftGroup],
    };
    const applyPartVisibility = (hidden: ReadonlySet<HideablePartId>) => {
      (Object.keys(hideableGroups) as HideablePartId[]).forEach((part) => {
        hideableGroups[part].forEach((object) => {
          object.visible = !hidden.has(part);
        });
      });
    };
    applyPartVisibilityRef.current = applyPartVisibility;
    applyPartVisibility(hiddenPartsRef.current);

    let fullExplosionAutoFitApplied = false;
    const applyExplosion = (amount: number) => {
      const normalized = THREE.MathUtils.clamp(amount, 0, 1);
      const eased = normalized * normalized * (3 - 2 * normalized);
      // At 70% the smoothstep easing is only ~78% complete. A 0.72-stack
      // station therefore left the nearly full-depth air-gap sleeve intersecting
      // the magnets until the slider was close to 100%. This larger base step
      // leaves enough travel for clearly separated component silhouettes at
      // 70%, while still converging to the exact assembled geometry at zero.
      const station = stackDepth * 1.12 * eased;
      statorGroup.position.z = -4.25 * station;
      // Teeth ride the yoke's station: they are one lamination in the real
      // machine, and giving them a station of their own both crowded the
      // windings and buried the rear links inside the teeth's axial span.
      teethGroup.position.z = statorGroup.position.z;
      // These four parts all span most of the stack depth. One station step is
      // therefore slightly larger than a full stack so the translucent air-gap
      // sleeve does not intersect the windings or magnets in the teardown.
      windingsGroup.position.z = -2.75 * station;
      // The sleeve gets a complete rearward station of its own. Its radial
      // silhouette is nearly as large as the rotor, so a merely non-intersecting
      // axial gap still looks overlapped from the default oblique camera.
      airgap.position.z = -1.25 * station;
      magnetsGroup.position.z = 1.25 * station;
      rotorCoreGroup.position.z = 2.55 * station;
      shaftGroup.position.z = 4.25 * station;
      // Each end's housing continues past the outermost part on ITS side: the
      // rear pair beyond the stator, the drive pair beyond the shaft. The
      // bearing comes out of its cap just ahead of the cap, which is the last
      // thing off that end of the machine in a teardown.
      // The bearing stays close behind its own cap — it lifts out of that cap's
      // bore, so it reads as belonging to the cap rather than as one more disc
      // spaced evenly along the row.
      rearBearingGroup.position.z = -5.6 * station;
      rearEndcapGroup.position.z = -6.4 * station;
      driveBearingGroup.position.z = 5.45 * station;
      driveEndcapGroup.position.z = 6.1 * station;
      airgapMaterial.opacity = 0.14 - eased * 0.035;
      // Assembled, the drive-end cap is a shell you read the end windings
      // through; once it clears the stack it turns into a solid casting. Only
      // opacity moves — `transparent` stays pinned, so this never triggers a
      // shader recompile. The rear cap is opaque throughout and needs no ramp.
      materials.endcap.opacity = THREE.MathUtils.lerp(
        ENDCAP_ASSEMBLED_OPACITY,
        1,
        THREE.MathUtils.smoothstep(normalized, 0.05, 0.4),
      );
      const chipOpacity = THREE.MathUtils.smoothstep(normalized, 0.22, 0.6);
      partChips.forEach(({ sprite, anchor, follows }) => {
        sprite.position.set(anchor.x, anchor.y, anchor.z + follows.position.z);
        // A chip goes with its part: labelling something the user just hid
        // would leave a caption pointing at empty space.
        sprite.visible = chipOpacity > 0.02 && follows.visible;
        sprite.material.opacity = chipOpacity;
      });
      radialExplodables.forEach(({ object, basePosition, direction, distance }) => {
        object.position.copy(basePosition).addScaledVector(direction, distance * eased);
      });
      if (harnessGroup) {
        harnessGroup.position.z = windingsGroup.position.z;
        // The rear links stay on show through the whole explode — they are the
        // part of the winding you cannot see in the assembled machine. They
        // only ghost back, because the coils they join fan outward radially
        // while the links do not, so a solid harness would read as broken wire.
        const harnessOpacity = THREE.MathUtils.lerp(1, 0.8, THREE.MathUtils.smoothstep(eased, 0.05, 0.45));
        // Visibility belongs to the part toggles now — setting it here would
        // reinstate the harness every frame the user tried to hide it.
        harnessMaterials.forEach((material) => {
          material.opacity = harnessOpacity;
        });
      }
      if (normalized < 0.9) {
        fullExplosionAutoFitApplied = false;
      }
      if (normalized > 0.92 && !fullExplosionAutoFitApplied) {
        const cameraOffset = camera.position.clone().sub(controls.target);
        // The exploded row is laid out in stack lengths, but the rest of the
        // camera framing keys off the outer radius. A long-stack machine walks
        // its end caps clean out of a radius-only fit distance, so the pull-back
        // has to track whichever dimension is actually driving the spread. Do
        // this once when the slider enters its fully exploded range: repeating
        // the fit every render frame would undo every user wheel-zoom at 100%.
        if (cameraOffset.length() < explodedFitDistance) {
          camera.position.copy(controls.target).add(cameraOffset.setLength(explodedFitDistance));
          controls.update();
        }
        fullExplosionAutoFitApplied = true;
      }
    };
    let displayedExplosion = explodedAmountRef.current;
    applyExplosion(displayedExplosion);

    const onPointerDown = (event: PointerEvent) => {
      onInteractionRef.current?.();
      pointerDownPosition = [event.clientX, event.clientY];
    };
    const onWheel = () => onInteractionRef.current?.();
    const onPointerUp = (event: PointerEvent) => {
      if (Math.hypot(event.clientX - pointerDownPosition[0], event.clientY - pointerDownPosition[1]) > 5) return;
      const rect = canvas.getBoundingClientRect();
      pointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const selected = raycaster.intersectObjects(scene.children, true)
        .filter((intersection) => isVisibleThrough(intersection.object))
        .map((intersection) => componentSelectionForObject(intersection.object))
        .find((candidate) => candidate !== null) ?? null;
      if (selectionHelper) {
        scene.remove(selectionHelper);
        selectionHelper.geometry.dispose();
        selectionHelper.material.dispose();
        selectionHelper = null;
      }
      if (selected) {
        selectionHelper = new THREE.BoxHelper(selected.object, 0x22d3ee);
        scene.add(selectionHelper);
      }
      onComponentSelectRef.current?.(selected?.selection ?? null);
    };
    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('wheel', onWheel, { passive: true });

    const resize = () => {
      const width = host.clientWidth;
      const height = host.clientHeight;
      if (width < 1 || height < 1) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(host);
    resize();

    const render = () => {
      animationFrame = window.requestAnimationFrame(render);
      displayedExplosion = THREE.MathUtils.lerp(
        displayedExplosion,
        explodedAmountRef.current,
        0.095,
      );
      if (Math.abs(displayedExplosion - explodedAmountRef.current) < 0.001) {
        displayedExplosion = explodedAmountRef.current;
      }
      applyExplosion(displayedExplosion);
      const intro = introProgressRef.current;
      if (intro === null) {
        controls.update();
      } else {
        const clamped = THREE.MathUtils.clamp(intro, 0, 1);
        const eased = clamped * clamped * (3 - 2 * clamped);
        camera.position.lerpVectors(assembledCameraPosition, crossSectionCameraPosition, eased);
        controls.target.set(0, 0, 0);
        camera.lookAt(controls.target);
      }
      syncBearingKinematics(bearingRigs, rotorGroup.rotation.z);
      selectionHelper?.update();
      renderer.render(scene, camera);
    };
    render();

    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      controls.dispose();
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointerup', onPointerUp);
      canvas.removeEventListener('wheel', onWheel);
      if (selectionHelper) {
        selectionHelper.geometry.dispose();
        selectionHelper.material.dispose();
      }
      resetCameraRef.current = null;
      rotorRef.current = null;
      bearingRigsRef.current = [];
      applyPartVisibilityRef.current = null;
      scene.traverse((object) => {
        const material = 'material' in object ? object.material as THREE.Material | THREE.Material[] : null;
        (Array.isArray(material) ? material : material ? [material] : []).forEach((item) => item.dispose());
      });
      geometries.forEach((geometry) => geometry.dispose());
      // The traverse above disposes each chip's SpriteMaterial but not the
      // canvas texture hanging off it.
      chipTextures.forEach((texture) => texture.dispose());
      // The material disposes above do not touch the map hanging off rotorFace.
      materials.rotorFace.map?.dispose();
      Object.values(materials).forEach((material) => material.dispose());
      environmentTarget.dispose();
      renderer.dispose();
    };
  }, [config]);

  useEffect(() => {
    if (!rotorRef.current) return;
    rotorRef.current.rotation.z = -rotorAngleDeg * Math.PI / 180;
    syncBearingKinematics(bearingRigsRef.current, rotorRef.current.rotation.z);
  }, [rotorAngleDeg]);

  useEffect(() => {
    explodedAmountRef.current = explodedAmount;
  }, [explodedAmount]);

  useEffect(() => {
    if (resetSignal > 0) resetCameraRef.current?.();
  }, [resetSignal]);

  return (
    <div
      className={`public-motor-3d-stage${introProgress !== null ? ' is-intro' : ''}`}
      ref={hostRef}
      aria-label="Interactive 3D motor view"
    >
      <canvas ref={canvasRef} />
      {introProgress === null && (
        <div className="public-3d-part-toggles" role="group" aria-label="Show or hide motor parts">
          {HIDEABLE_PARTS.map(({ id, label }) => {
              const shown = !hiddenParts.has(id);
              return (
                <button
                  key={id}
                  type="button"
                  className={`public-3d-part-toggle${shown ? '' : ' is-off'}`}
                  aria-pressed={shown}
                  title={shown ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
                  onClick={() => togglePart(id)}
                >
                  {label}
                </button>
              );
            })}
        </div>
      )}
      <div className="public-3d-hint">
        {introProgress !== null
          ? 'Assembly view · turning to engineering cross-section'
          : `${explodedAmount > 0.04 ? 'Exploded assembly · ' : ''}Click a part · drag to orbit · wheel to zoom`}
      </div>
      {failed && <div className="public-viewport-message">3D preview is unavailable on this graphics device.</div>}
    </div>
  );
}
