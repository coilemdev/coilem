import { ReferenceMotor3D } from './ReferenceMotor3D';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

import { buildConcentratedCoil, buildDistributedCoil, buildWindingHarness } from './coil3d';
import { deriveStatorSectionWidths } from './dimensionAnnotations';
import { publicFlatIpmMagnetCenterRadiusMm } from './flatIpmBurialHealth';
import { magnetPoleCoverage } from './magnetCoverage';
import type { GeometryPreview, MotorConfig, PublicMotorComponentSelection, PublicWindingCoil } from './model';
import { PUBLIC_MOTOR_COLORS, PUBLIC_PHASE_COLORS, renderTargetColor } from './motorPalette';
import { STRIP_END, phaseCurrents, phaseDriveFrame, phaseStrips, rotorElectricalDeg, slotCurrents, toothPoles, type PhaseDrive, type WindingSide } from './phaseDrive';
import { drawPhaseDriveWired } from './phaseDrivePanel';
import { publishedReference } from './publishedReferences';
import { insulatedDiameterMm } from './windingBuild';
import { readWindingResistance } from './windingResistance';
import { shoeShoulderFraction, stator3dRadii } from './stator3dRadii';
import { concentratedUsesToothCoils, toothCoilAssignments } from './toothCoils';

interface PublicMotor3DProps {
  config: MotorConfig;
  geometry?: GeometryPreview | null;
  resetSignal: number;
  rotorAngleDeg: number;
  explodedAmount: number;
  introProgress?: number | null;
  onInteraction?: () => void;
  onComponentSelect?: (component: PublicMotorComponentSelection | null) => void;
  /** Draw every coil in one plain copper instead of its phase colour, as the 2D view does. */
  plainWinding?: boolean;
  /** Tint each stator tooth by its N / S pole as the rotor turns. */
  showToothPoles?: boolean;
  /** Shade each phase's coils by the current it carries as the rotor turns. */
  showPhases?: boolean;
  /** Number chips over the slots, teeth and coil sides. */
  overlays?: Motor3DOverlays;
  /** The preview speed, which sets the frequency the Phases waveforms show. */
  previewRpm?: number;
  /**
   * The part toggles and the peel slider go in the viewport dock instead of over
   * the motor: they are drawn into `dockSlot` once the dock has made it.
   */
  controlsInDock?: boolean;
  dockSlot?: HTMLElement | null;
}

export interface Motor3DOverlays { slots: boolean; teeth: boolean; windings: boolean }
const NO_3D_OVERLAYS: Motor3DOverlays = { slots: false, teeth: false, windings: false };

/**
 * Parts the viewer can hide. Hiding one or more is how you look inside the
 * machine without exploding it. Each id maps to one or more scene groups below —
 * `stator` covers the yoke and its teeth, `windings` takes the rear links with
 * it, since neither reads on its own.
 */
type HideablePartId = 'stator' | 'windings' | 'rotor' | 'rotorBell' | 'magnets' | 'airgap' | 'endcaps' | 'bearings' | 'shaft';

const HIDEABLE_PARTS: Array<{ id: HideablePartId; label: string }> = [
  { id: 'endcaps', label: 'End caps' },
  { id: 'rotorBell', label: 'Rotor bell' },
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
 * windings, magnets and rotor that the design actually is stay buried.
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

const HAND_WOUND_STRANDS = 42;

/** Bare-metal colours of the 3D steel parts, shared with the landing page motor. */
const STEEL_3D = { stator: 0x6d7682, tooth: 0x78818e, rotor: 0x8c939d } as const;

function mutedMagnetColor(hex: string): THREE.Color {
  return new THREE.Color(renderTargetColor(hex)).lerp(new THREE.Color(0x8d939c), 0.22);
}

function enamelledCopperMaterial(phaseColor: number, transparent = false): THREE.MeshPhysicalMaterial {
  return new THREE.MeshPhysicalMaterial({
    // The copper tint is kept so the bundles read as enamelled wire rather than
    // painted plastic, but pulled back from 0.18: at that weight it dragged the
    // green and violet phases toward the amber one, so the three phases were
    // harder to tell apart here than in 2D.
    color: new THREE.Color(phaseColor).lerp(new THREE.Color(0xc9722e), 0.1),
    // Enamelled magnet wire: metal under a glossy coat. The studio rig is dimmer
    // than the warm one this was first tuned for, so the coat can be stronger
    // without whitening the bundles.
    metalness: 0.6,
    roughness: 0.34,
    clearcoat: 0.55,
    clearcoatRoughness: 0.24,
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

/**
 * `bevel` breaks the two end-face edges so they catch a highlight, as a
 * machined or stamped part does. The outline and overall length are unchanged.
 */
function extrude(shape: THREE.Shape, depth: number, bevel = 0): THREE.ExtrudeGeometry {
  const edge = Math.min(bevel, depth * 0.2);
  const geometry = new THREE.ExtrudeGeometry(shape, edge > 0
    ? {
      depth: depth - edge * 2,
      bevelEnabled: true,
      bevelThickness: edge,
      bevelSize: edge,
      bevelOffset: -edge,
      bevelSegments: 2,
      curveSegments: 64,
    }
    : { depth, bevelEnabled: false, curveSegments: 64 });
  geometry.translate(0, 0, -depth / 2 + edge);
  return geometry;
}

/** Flat washer about z = 0 — the housing parts are all stacked annuli. */
function annulusGeometry(innerRadius: number, outerRadius: number, depth: number, bevel = 0): THREE.ExtrudeGeometry {
  return extrude(ringShape(outerRadius, innerRadius), depth, bevel);
}

/**
 * Rotation cue for the rotor end faces. The core is a surface of revolution,
 * so a plain finish renders identically at every angle and the spinning rotor
 * reads as standing still — the same problem the bearing's race mark solves
 * at the drive end. A square grid scribed into a canvas texture gives each end face a
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
    const base = new THREE.Color(STEEL_3D.rotor);
    context.fillStyle = `#${base.getHexString()}`;
    context.fillRect(0, 0, size, size);

    const center = size / 2;
    const gridStep = 24;
    // Scribed a shade darker than the steel, so it stays a faint cue.
    const grid = base.clone().lerp(new THREE.Color(0x2b323c), 0.3);
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
    seal: THREE.Material;
    sealLip: THREE.Material;
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
  // The balls and cage stay inside the seals. A short, wide bearing (a thin
  // outrunner stack) would otherwise have balls taller than the bearing is
  // wide, poking out through both seal faces.
  const ballRadius = Math.max(0.2, Math.min((outerRaceInner - innerRaceOuter) * 0.62, dims.width * 0.36));

  const raceBevel = dims.width * 0.07;
  const innerRaceGeometry = annulusGeometry(dims.boreRadius, innerRaceOuter, dims.width, raceBevel);
  const outerRaceGeometry = annulusGeometry(outerRaceInner, dims.outerRadius, dims.width, raceBevel);
  // Sealed (2RS-style), as fitted to most motors: a rubber seal just inside
  // each face hides the balls and cage. The seals belong to the outer race,
  // which stays put in its seat; only the inner race turns with the shaft.
  const sealRecess = dims.width * 0.07;
  const sealGap = build * 0.025;
  const sealGeometry = annulusGeometry(innerRaceOuter + sealGap, outerRaceInner - sealGap, dims.width - sealRecess * 2);
  const sealLipGeometry = annulusGeometry(innerRaceOuter, innerRaceOuter + sealGap + build * 0.07, dims.width - sealRecess * 3.2);
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
  outerRace.add(
    new THREE.Mesh(outerRaceGeometry, materials.race),
    new THREE.Mesh(sealGeometry, materials.seal),
    new THREE.Mesh(sealLipGeometry, materials.sealLip),
  );
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
      sealGeometry,
      sealLipGeometry,
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
 * An outer rotor's end bell: the drive-end plate closing its can, clamped to the
 * shaft so the shaft turns with the rotor. Open between spokes, as on a drone
 * motor, so the windings stay in view. The spokes slope up from the rim to a
 * raised hub, leaving room over the end turns. Built with the rim's inner face
 * at z = 0 and positioned by the caller.
 */
function buildRotorBell(
  dims: { shaftRadius: number; rimInnerRadius: number; outerRadius: number; thickness: number; rise: number },
  material: THREE.Material,
): HousingBuild {
  const group = new THREE.Group();
  const hubOuterRadius = Math.max(dims.shaftRadius * 2.1, dims.shaftRadius + dims.thickness);

  const bevel = Math.min(dims.thickness * 0.12, (dims.outerRadius - dims.rimInnerRadius) * 0.12);
  const rimGeometry = annulusGeometry(dims.rimInnerRadius, dims.outerRadius, dims.thickness, bevel);
  const rim = new THREE.Mesh(rimGeometry, material);
  rim.position.z = dims.thickness / 2;
  group.add(rim);

  // The clamp hub stands proud of the plate on both faces, gripping the shaft.
  const hubGeometry = annulusGeometry(dims.shaftRadius, hubOuterRadius, dims.thickness * 1.8);
  const hub = new THREE.Mesh(hubGeometry, material);
  hub.position.z = dims.rise + dims.thickness / 2;
  group.add(hub);

  const spokeCount = 5;
  const spokeWidth = Math.max(dims.thickness, ((2 * Math.PI * dims.rimInnerRadius) / spokeCount) * 0.2);
  const spokeRoot = hubOuterRadius * 0.85;
  const spokeTip = dims.rimInnerRadius + dims.thickness * 0.4;
  const spokeShape = new THREE.Shape();
  spokeShape.moveTo(spokeRoot, -spokeWidth * 0.32);
  spokeShape.lineTo(spokeTip, -spokeWidth / 2);
  spokeShape.lineTo(spokeTip, spokeWidth / 2);
  spokeShape.lineTo(spokeRoot, spokeWidth * 0.32);
  spokeShape.closePath();
  const spokeGeometry = extrude(spokeShape, dims.thickness, bevel);
  spokeGeometry.translate(0, 0, dims.thickness / 2);
  // Lift the inner end without rotating a thick box into the hub or rim.
  const positions = spokeGeometry.getAttribute('position');
  for (let index = 0; index < positions.count; index += 1) {
    const lift = THREE.MathUtils.clamp(
      (dims.rimInnerRadius - positions.getX(index)) / (dims.rimInnerRadius - hubOuterRadius), 0, 1,
    ) * dims.rise;
    positions.setZ(index, positions.getZ(index) + lift);
  }
  spokeGeometry.computeVertexNormals();
  for (let index = 0; index < spokeCount; index += 1) {
    const angle = (index / spokeCount) * Math.PI * 2;
    const spoke = new THREE.Mesh(spokeGeometry, material);
    spoke.rotation.z = angle;
    group.add(spoke);
  }

  return { group, geometries: [rimGeometry, hubGeometry, spokeGeometry] };
}

/**
 * Floating part label for the exploded view: a rounded chip drawn to a canvas
 * and hung off a sprite, so it stays screen-facing and legible from any orbit
 * angle. The texture comes back alongside the sprite because only the caller
 * knows when the scene is torn down.
 */
function makeChipSprite(text: string, stroke = 'rgba(103, 232, 249, 0.34)'): { sprite: THREE.Sprite; texture: THREE.CanvasTexture | null } {
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
    context.strokeStyle = stroke;
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

export function PublicMotor3D(props: PublicMotor3DProps) {
  // The parametric build draws inner and outer rotors; published references extrude their preview regions.
  return props.config.geometry_reference
    ? <ReferenceMotor3D {...props} /> : <ParametricMotor3D {...props} />;
}

function ParametricMotor3D({
  config,
  resetSignal,
  rotorAngleDeg,
  explodedAmount,
  introProgress = null,
  onInteraction,
  onComponentSelect,
  geometry,
  plainWinding = false,
  showToothPoles = false,
  showPhases = false,
  overlays = NO_3D_OVERLAYS,
  previewRpm = 20,
  controlsInDock = false,
  dockSlot = null,
}: PublicMotor3DProps) {
  // The same phase drive the 2D view shades by: the solve's own terminal currents.
  const solveParams = config.solve_params;
  const metadataAxis = Number(geometry?.metadata.phase_axis_offset_elec_deg);
  const metadataPoles = Number(geometry?.metadata.pole_count);
  const pyleecanAxis = geometry?.metadata.phase_current_convention === 'pyleecan_d_axis'
    || publishedReference(config)?.phaseCurrentConvention === 'pyleecan_d_axis';
  const phaseDrive = useMemo<PhaseDrive | null>(() => (solveParams
    ? {
      mode: solveParams.excitation_mode,
      currentAngleDeg: solveParams.current_angle_deg,
      currentAngleReference: pyleecanAxis ? 'pyleecan_d_axis' : 'q_axis',
      currentAmplitudeA: solveParams.current_amplitude_A,
      commutationAdvanceDeg: solveParams.commutation_advance_deg,
      axisOffsetDeg: Number.isFinite(metadataAxis) ? metadataAxis : 0,
      poleCount: Number.isFinite(metadataPoles) && metadataPoles > 0 ? metadataPoles : config.rotor.pole_count,
    }
    : null), [
    solveParams?.excitation_mode,
    solveParams?.current_angle_deg,
    solveParams?.current_amplitude_A,
    solveParams?.commutation_advance_deg,
    pyleecanAxis,
    metadataAxis,
    metadataPoles,
    config.rotor.pole_count,
  ]);
  const windingLayout: WindingSide[] | null = geometry?.winding_layout ?? null;
  const windingCoils: PublicWindingCoil[] | null = geometry?.winding_coils ?? null;
  // One turn's conductor as the preview sizes it: the insulated wire, or the bundle its strands in hand make.
  const wireRecord = readWindingResistance(geometry?.metadata?.winding_resistance);
  const strandsInHand = wireRecord?.wire_source === 'specified' ? Math.max(1, Math.round(wireRecord.strands_in_hand)) : 1;
  const turnDiameter = wireRecord
    ? Number((insulatedDiameterMm(wireRecord.strand_diameter_mm) * Math.sqrt(wireRecord.strands_in_hand)).toFixed(3))
    : null;
  // What the scene shows now. It is built once per design, so the toggles reach it through this.
  const displayRef = useRef({ plainWinding, showToothPoles, showPhases, overlays, rotorAngleDeg, phaseDrive, windingLayout, windingCoils, turnDiameter, strandsInHand, previewRpm });
  displayRef.current = { plainWinding, showToothPoles, showPhases, overlays, rotorAngleDeg, phaseDrive, windingLayout, windingCoils, turnDiameter, strandsInHand, previewRpm };
  // The Phases waveforms are drawn on a flat canvas: under the 3D one while the
  // drive leads are on the far side of the motor, so the wires pass behind it, and
  // over it once the view is turned to the back and the leads are in sight.
  const driveUnderRef = useRef<HTMLCanvasElement>(null);
  const driveOverRef = useRef<HTMLCanvasElement>(null);
  const applyDisplayRef = useRef<(() => void) | null>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rotorRef = useRef<THREE.Group | null>(null);
  const bearingRigsRef = useRef<BearingAnimationRig[]>([]);
  const resetCameraRef = useRef<(() => void) | null>(null);
  // The view the user left, kept across a scene rebuild: a change to the winding or
  // the wire redraws the motor where it was, turned and zoomed as before. A change to
  // the machine's size or layout frames it afresh.
  const keptViewRef = useRef<{ frame: string; position: THREE.Vector3; target: THREE.Vector3 } | null>(null);
  const requestRenderRef = useRef<(() => void) | null>(null);
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

  // The parts from the outside in, for the slider that peels the motor: on an
  // outer-rotor machine the rotor and magnets are outside the stator.
  const outerRotor = config.rotor_layout === 'outer';
  const availableParts = useMemo(() => HIDEABLE_PARTS.filter(({ id }) => outerRotor || id !== 'rotorBell'), [outerRotor]);
  const shownPartCount = availableParts.filter(({ id }) => !hiddenParts.has(id)).length;
  const peelOrder = useMemo<HideablePartId[]>(() => (outerRotor
    ? ['endcaps', 'rotorBell', 'rotor', 'magnets', 'airgap', 'windings', 'stator', 'bearings', 'shaft']
    : ['endcaps', 'stator', 'windings', 'airgap', 'magnets', 'rotor', 'bearings', 'shaft']), [outerRotor]);
  // How many parts are left, counted from the shaft outwards: every part up to the first one still shown is peeled.
  const firstShown = peelOrder.findIndex((part) => !hiddenParts.has(part));
  const partsLeft = firstShown < 0 ? 0 : peelOrder.length - firstShown;
  const peelTo = (left: number) => {
    setHiddenParts(new Set(peelOrder.slice(0, peelOrder.length - left)));
  };
  const outermostShown = firstShown < 0 ? null : HIDEABLE_PARTS.find(({ id }) => id === peelOrder[firstShown])?.label ?? null;

  useEffect(() => {
    hiddenPartsRef.current = hiddenParts;
    applyPartVisibilityRef.current?.(hiddenParts);
    requestRenderRef.current?.();
  }, [hiddenParts]);

  useEffect(() => {
    onComponentSelectRef.current = onComponentSelect;
  }, [onComponentSelect]);

  useEffect(() => {
    onInteractionRef.current = onInteraction;
  }, [onInteraction]);

  useEffect(() => {
    introProgressRef.current = introProgress;
    requestRenderRef.current?.();
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
    const gl = renderer.getContext();
    const rendererInfo = gl.getExtension('WEBGL_debug_renderer_info');
    const softwareRendering = rendererInfo !== null && /swiftshader|llvmpipe|softpipe|software/i.test(
      gl.getParameter(rendererInfo.UNMASKED_RENDERER_WEBGL) as string,
    );
    // Idle software WebGL redraws can stall input when this scene mounts.
    // Render changes on demand while preserving animation on hardware GPUs.
    const renderContinuously = !softwareRendering
      && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 5_000);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = renderContinuously;
    controls.dampingFactor = 0.07;
    controls.enablePan = false;
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let pointerDownPosition: [number, number] = [0, 0];
    let selectionHelper: THREE.BoxHelper | null = null;

    // An outer rotor turns the machine inside out: the stator's yoke sits on its
    // hub with the teeth pointing out to the air gap at its OD, and the rotor is
    // a ring round it with the magnets on its inner face. Radii are named by role
    // so one build serves both (stator3dRadii.ts).
    const {
      outerRotor,
      outerRadius,
      statorInnerRadius,
      yokeInnerRadius,
      yokeOuterRadius,
      coilRootRadius,
    } = stator3dRadii(config);
    const rotorRadius = config.rotor.OD_mm / 2;
    // An outer rotor's magnets sit on its inner face, the rotor ID.
    // (An outer rotor always has an ID; the schema requires it.)
    const magnetSeatRadius = outerRotor ? (config.rotor.ID_mm ?? 0) / 2 : rotorRadius;
    // An outer rotor's shaft runs through the stator hub. Size it off the machine,
    // not the hub bore: a drone motor's hub can be most of its stator.
    const shaftRadius = outerRotor
      ? Math.min(yokeOuterRadius * 0.42, Math.max(0.6, outerRadius * 0.08))
      : Math.max(outerRadius * 0.055, (config.rotor.ID_mm || outerRadius * 0.12) / 2);
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
    const viewFrame = `${outerRotor}:${outerRadius}:${stackDepth}`;
    if (keptViewRef.current?.frame === viewFrame && introProgressRef.current === null) {
      camera.position.copy(keptViewRef.current.position);
      controls.target.copy(keptViewRef.current.target);
      controls.update();
    }

    const pmrem = new THREE.PMREMGenerator(renderer);
    const environmentTarget = pmrem.fromScene(new RoomEnvironment(), 0.04);
    scene.environment = environmentTarget.texture;
    scene.environmentIntensity = 0.8;
    pmrem.dispose();

    // Studio lighting, shared with the landing page motor: a near-white key
    // with soft shadows, a cool fill, and two faint coloured rims that keep the
    // part edges off the dark page.
    scene.add(new THREE.AmbientLight(0xffffff, 0.12));
    scene.add(new THREE.HemisphereLight(0xe8eef7, 0x15171c, 0.35));
    const key = new THREE.DirectionalLight(0xfff1de, 1.75);
    key.position.set(outerRadius * 2, outerRadius * 2.4, outerRadius * 2.6);
    key.castShadow = true;
    key.shadow.mapSize.set(2_048, 2_048);
    key.shadow.camera.left = -outerRadius * 2.4;
    key.shadow.camera.right = outerRadius * 2.4;
    key.shadow.camera.top = outerRadius * 2.4;
    key.shadow.camera.bottom = -outerRadius * 2.4;
    key.shadow.camera.near = 1;
    key.shadow.camera.far = outerRadius * 8;
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.6;
    key.shadow.radius = 4;
    key.shadow.intensity = 0.6;
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xc7d7ee, 0.45);
    fill.position.set(-outerRadius * 2.2, outerRadius * 0.8, outerRadius * 1.4);
    scene.add(fill);
    const rim = new THREE.DirectionalLight(0x8fdcf0, 0.4);
    rim.position.set(-outerRadius * 2, -outerRadius, outerRadius * 1.2);
    scene.add(rim);
    const warmRim = new THREE.DirectionalLight(0xffb866, 0.3);
    warmRim.position.set(outerRadius * 0.8, -outerRadius * 2.1, -outerRadius);
    scene.add(warmRim);

    const materials = {
      stator: new THREE.MeshPhysicalMaterial({
        // Electrical-steel laminations, drawn as the neutral grey metal they are
        // (as on the landing page motor) rather than tinted to the 2D fill.
        color: STEEL_3D.stator,
        metalness: 0.85,
        roughness: 0.46,
      }),
      tooth: new THREE.MeshPhysicalMaterial({
        color: STEEL_3D.tooth,
        metalness: 0.85,
        roughness: 0.44,
      }),
      rotor: new THREE.MeshPhysicalMaterial({
        color: STEEL_3D.rotor,
        metalness: 0.9,
        roughness: 0.36,
        transparent: config.topology === 'IPM',
        opacity: config.topology === 'IPM' ? 0.68 : 1,
        depthWrite: config.topology !== 'IPM',
      }),
      // End-cap faces of the rotor core: same steel, but the fine square
      // grid makes the spin visible. White base colour so the map carries the tint.
      rotorFace: new THREE.MeshPhysicalMaterial({
        color: 0xffffff,
        map: makeRotorFaceTexture(),
        metalness: 0.9,
        roughness: 0.36,
        transparent: config.topology === 'IPM',
        opacity: config.topology === 'IPM' ? 0.68 : 1,
        depthWrite: config.topology !== 'IPM',
      }),
      shaft: new THREE.MeshPhysicalMaterial({
        // Was 0.96 metal at 0.16 roughness with a 0.45 coat — a mirror, which
        // clipped to pure white in the middle of the face-on view. Machined steel,
        // not chrome.
        color: 0xc9d0d9,
        metalness: 0.95,
        roughness: 0.24,
        envMapIntensity: 0.8,
      }),
      // Coated magnets, each one piece coloured by the pole it presents to the
      // stator: red north, blue south. The colours are muted towards the steel
      // around them, as on the landing page motor, so the magnets read as coated
      // metal and do not outshout the copper.
      magnetNorth: new THREE.MeshPhysicalMaterial({
        color: mutedMagnetColor(PUBLIC_MOTOR_COLORS.magnetNorth),
        emissive: 0x120304,
        metalness: 0.62,
        roughness: 0.3,
        clearcoat: 0.5,
        clearcoatRoughness: 0.25,
      }),
      magnetSouth: new THREE.MeshPhysicalMaterial({
        color: mutedMagnetColor(PUBLIC_MOTOR_COLORS.magnetSouth),
        emissive: 0x030a18,
        metalness: 0.62,
        roughness: 0.3,
        clearcoat: 0.5,
        clearcoatRoughness: 0.25,
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
        color: 0x8b95a3,
        metalness: 0.7,
        roughness: 0.52,
        envMapIntensity: 0.5,
        transparent: true,
        opacity: ENDCAP_ASSEMBLED_OPACITY,
      }),
      // The rear cap is solid: nothing sits behind it to read through, so its
      // only job is to close the machine off. Only the drive-end cap — the one
      // between the camera and the end windings — stays a shell.
      endcapRear: new THREE.MeshPhysicalMaterial({
        color: 0x8b95a3,
        metalness: 0.7,
        roughness: 0.52,
        envMapIntensity: 0.5,
      }),
      // Black anodized aluminium on the outrunner's open, raised end bell.
      rotorBell: new THREE.MeshPhysicalMaterial({
        color: 0x171a1f,
        metalness: 0.78,
        roughness: 0.38,
        clearcoat: 0.16,
        clearcoatRoughness: 0.4,
        envMapIntensity: 0.65,
      }),
      bearingRace: new THREE.MeshPhysicalMaterial({
        color: 0xbfc7d2,
        metalness: 0.95,
        roughness: 0.2,
        envMapIntensity: 0.8,
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
      bearingSeal: new THREE.MeshPhysicalMaterial({
        color: 0x1b1f27,
        metalness: 0.08,
        roughness: 0.58,
        clearcoat: 0.22,
        clearcoatRoughness: 0.42,
        envMapIntensity: 0.35,
      }),
      bearingSealLip: new THREE.MeshPhysicalMaterial({ color: 0x0f1218, metalness: 0.05, roughness: 0.7 }),
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
    // Break the end-face edges of the laminations so they catch the light.
    const edgeBevel = outerRadius * 0.0045;
    const yokeGeometry = extrude(
      ringShape(Math.max(yokeOuterRadius, yokeInnerRadius), Math.min(yokeOuterRadius, yokeInnerRadius)),
      stackDepth,
      edgeBevel,
    );
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
      const shoulderRadius = outerRotor
        ? Math.max(statorInnerRadius - shoeHeight, yokeInnerRadius + 1e-4)
        : Math.min(
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
      const shoulderFraction = shoeShoulderFraction(statorInnerRadius, shoulderRadius, yokeInnerRadius);
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
    const toothGeometry = extrude(toothShape, stackDepth, edgeBevel);
    geometries.push(toothGeometry);

    // The coil builder winds from the tooth's inner radius out; an outer
    // stator's tooth runs from the yoke out to the shoe, so its ends swap.
    // Draw the coil as wound magnet wire, one loop for each turn: a one-turn coil
    // is one loop round the tooth. Coils with more turns than the limit draw the
    // limit, and machines with many teeth get a lower one to stay light to render.
    const handWound = {
      strands: Math.min(
        Math.max(1, Math.round(config.winding.turns_per_coil) || 1),
        config.stator.slot_count > 24 ? 24 : HAND_WOUND_STRANDS,
      ),
      endTurnRoundness: 0.5,
      irregularity: 0.14,
    };
    // A wire the designer has set is drawn at its own size; without one the loops fill the slot.
    const setWire = config.winding.wire;
    const specifiedTurnDiameter = setWire
      ? insulatedDiameterMm(setWire.wire_bare_diameter_mm) * Math.sqrt(Math.max(1, setWire.strands_in_hand ?? 1))
      : undefined;
    const concentratedCoil = config.winding.type === 'concentrated'
      ? buildConcentratedCoil(outerRotor
        ? {
            boreRadius: coilRootRadius,
            yokeInnerRadius: coilBoreRadius,
            toothHalfAngleInnerRad: toothHalfOuter,
            toothHalfAngleOuterRad: coilToothHalfInner,
            slotPitchRad: slotPitch,
            stackLength: stackDepth,
            turnsPerCoil: config.winding.turns_per_coil,
            turnDiameter: specifiedTurnDiameter,
            handWound,
          }
        : {
            boreRadius: coilBoreRadius,
            yokeInnerRadius,
            toothHalfAngleInnerRad: coilToothHalfInner,
            toothHalfAngleOuterRad: toothHalfOuter,
            slotPitchRad: slotPitch,
            stackLength: stackDepth,
            turnsPerCoil: config.winding.turns_per_coil,
            turnDiameter: specifiedTurnDiameter,
            handWound,
          })
      : null;
    let coilModelNote = '';
    if (concentratedCoil) {
      geometries.push(concentratedCoil.geometry, concentratedCoil.linerGeometry);
      // The loops are illustrative; the turn count is the design's.
      // A turn of several strands in hand is one loop here: say so, so loops are not read as wires.
      const strandsInHand = Math.max(1, Math.round(setWire?.strands_in_hand ?? 1));
      const turnsNote = `${concentratedCoil.turnsRepresented} turns per coil · drawn as ${concentratedCoil.strandCount} wire loops${strandsInHand > 1 ? ` · each turn is ${strandsInHand} strands in hand` : ''}`;
      const bundleNote = concentratedCoil.wireLayers === 1
        ? `single wire layer × ${concentratedCoil.turnsPerLayer}`
        : `${concentratedCoil.wireLayers} wire layers × ${concentratedCoil.turnsPerLayer} per layer`;
      coilModelNote = `${turnsNote} · ${bundleNote}`;
    }

    // Tooth coils (#91) follow the backend's layout: alternate teeth with one
    // layer, every tooth with two, each with its own phase and sign.
    const toothCoilByTooth = config.winding.type === 'concentrated'
      && concentratedUsesToothCoils(config.stator.slot_count, config.rotor.pole_count)
      ? new Map(
        toothCoilAssignments(config.stator.slot_count, config.rotor.pole_count, config.winding.layers)
          .map((coil) => [coil.tooth, coil] as const),
      )
      : null;
    const toothMaterials: THREE.MeshPhysicalMaterial[] = [];
    // A distributed winding's plain slot blocks, shown only until the preview brings its coils.
    const slotBlocks: THREE.Mesh[] = [];
    for (let slot = 0; slot < config.stator.slot_count; slot += 1) {
      // The backend centres slot k at k slot pitches and tooth k between slots
      // k and k + 1, the frame the 2D view and the tooth-coil rules use.
      const angle = (slot + 0.5) * slotPitch;
      const slotAngle = slot * slotPitch;
      // Its own material, so Tooth poles can tint each tooth by itself.
      const toothMaterial = materials.tooth.clone();
      toothMaterials.push(toothMaterial);
      const tooth = new THREE.Mesh(toothGeometry, toothMaterial);
      tooth.rotation.z = angle;
      makeSelectable(tooth, { id: `3d-stator-tooth-${slot + 1}`, kind: 'stator', label: `Stator tooth ${slot + 1}`, role: 'Stationary magnetic flux path', slotIndex: slot + 1 });
      teethGroup.add(tooth);
      registerRadialExplosion(tooth, angle, outerRadius * 0.075);

      const toothCoil = toothCoilByTooth?.get(slot);
      const phase = toothCoil?.phase ?? (['A', 'C', 'B'] as const)[slot % 3];
      const direction = toothCoil ? (toothCoil.direction === 'in' ? '+' : '-') : slot % 2 === 0 ? '+' : '-';
      if (concentratedCoil) {
        if (toothCoilByTooth && !toothCoil) continue;
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
          outerRotor
            ? sectorShape(Math.min(statorInnerRadius - 2, yokeInnerRadius + 1), statorInnerRadius - 1.2, coilHalfSpan)
            : sectorShape(statorInnerRadius + 1.2, Math.max(statorInnerRadius + 2, yokeInnerRadius - 1), coilHalfSpan),
          coilDepth,
        );
        geometries.push(coilGeometry);
        const phaseMaterial = { A: materials.phaseA, B: materials.phaseB, C: materials.phaseC }[phase];
        const coil = new THREE.Mesh(coilGeometry, phaseMaterial);
        slotBlocks.push(coil);
        coil.rotation.z = slotAngle;
        makeSelectable(coil, { id: `3d-winding-${slot + 1}`, kind: 'winding', label: `Slot ${slot + 1} · phase ${phase}${direction}`, role: 'Current-carrying stator winding', slotIndex: slot + 1, phase, direction });
        windingsGroup.add(coil);
        registerRadialExplosion(coil, slotAngle, outerRadius * 0.16);
      }
    }
    scene.add(statorGroup, teethGroup, windingsGroup);

    let harnessGroup: THREE.Group | null = null;
    const harnessMaterials: THREE.MeshPhysicalMaterial[] = [];
    const harnessByPhase: Partial<Record<'A' | 'B' | 'C', THREE.MeshPhysicalMaterial>> = {};
    const leadLandings: Partial<Record<'A' | 'B' | 'C', THREE.Vector3>> = {};
    if (concentratedCoil) {
      const harness = buildWindingHarness({
        slotCount: config.stator.slot_count,
        slotPitchRad: slotPitch,
        toothAngleOffsetRad: slotPitch / 2,
        phaseOfSlot: (slot) => (
          toothCoilByTooth ? toothCoilByTooth.get(slot)?.phase ?? null : (['A', 'C', 'B'] as const)[slot % 3]
        ),
        bundleCenterRadius: concentratedCoil.bundleCenterRadius,
        coilLeads: { start: concentratedCoil.startLead, finish: concentratedCoil.finishLead },
        stackHalf: stackDepth / 2,
        axialOverhang: concentratedCoil.axialOverhang,
        wireRadius: concentratedCoil.wireRadius,
        yokeInnerRadius: outerRotor ? yokeOuterRadius : yokeInnerRadius,
        outerRadius: outerRotor ? yokeInnerRadius : outerRadius,
        blockScale: outerRotor ? THREE.MathUtils.clamp(statorInnerRadius / 40, 0.25, 1) : 1,
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
        harnessByPhase[phase] = material;
        if (harness.leadLandings[phase]) leadLandings[phase] = harness.leadLandings[phase];
        const mesh = new THREE.Mesh(geometry, material);
        makeSelectable(mesh, {
          id: `3d-harness-${phase}`,
          kind: 'harness',
          label: `Phase ${phase} wire · crossovers and drive lead`,
          role: 'One continuous wire: each coil’s finish crosses behind the stack to the next coil’s start, from the drive lead to the star point',
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
    const rotorBellGroup = new THREE.Group();
    const pocketsGroup = new THREE.Group();
    const magnetsGroup = new THREE.Group();
    const shaftGroup = new THREE.Group();
    rotorCoreGroup.add(pocketsGroup);
    rotorGroup.add(rotorCoreGroup, rotorBellGroup, magnetsGroup, shaftGroup);
    rotorRef.current = rotorGroup;
    let core: THREE.Mesh;
    if (outerRotor) {
      // The back-iron ring round the stator. Extrude groups are the end faces
      // then the sides, so the grid again sits only on the end faces.
      const coreGeometry = annulusGeometry(magnetSeatRadius, rotorRadius, stackDepth);
      geometries.push(coreGeometry);
      core = new THREE.Mesh(coreGeometry, [materials.rotorFace, materials.rotor]);
    } else {
      const coreGeometry = new THREE.CylinderGeometry(rotorRadius, rotorRadius, stackDepth, 96);
      coreGeometry.rotateX(Math.PI / 2);
      geometries.push(coreGeometry);
      // Material array: CylinderGeometry groups are side, top cap, bottom cap.
      // Only the caps carry the grid so the spin reads on the end faces while
      // the side keeps the plain (and for IPM, translucent) lamination finish.
      core = new THREE.Mesh(coreGeometry, [materials.rotor, materials.rotorFace, materials.rotorFace]);
    }
    makeSelectable(core, { id: '3d-rotor-core', kind: 'rotor', label: 'Rotor core', role: 'Rotating magnetic flux path' });
    addEdges(core);
    rotorCoreGroup.add(core);

    // An outer rotor is a cup: its can runs on past the stack and the coils' end
    // turns to an end bell clamped to the shaft, which is how the shaft turns
    // with it. The bell spins and explodes with the rotor core, with a separate
    // visibility toggle so the windings can be inspected through the open can.
    let bellOuterFaceZ = 0;
    if (outerRotor) {
      const bellThickness = Math.max(0.6, capThickness);
      const bellRise = Math.max(bellThickness * 1.5, rotorRadius * 0.11);
      const bellInnerFaceZ = stackDepth / 2
        + (concentratedCoil?.axialOverhang ?? stackDepth * 0.08)
        + Math.max(0.8, rotorRadius * 0.045, bellThickness * 0.9);
      // Include the raised clamp hub when sizing the visible shaft extension.
      bellOuterFaceZ = bellInnerFaceZ + bellRise + bellThickness * 1.4;
      const canGeometry = annulusGeometry(magnetSeatRadius, rotorRadius, bellInnerFaceZ - stackDepth / 2);
      geometries.push(canGeometry);
      const can = new THREE.Mesh(canGeometry, [materials.rotorFace, materials.rotor]);
      can.position.z = (stackDepth / 2 + bellInnerFaceZ) / 2;
      makeSelectable(can, { id: '3d-rotor-can', kind: 'rotor', label: 'Rotor can', role: 'The rotor ring carried on past the stack to its end bell' });
      addEdges(can);
      rotorCoreGroup.add(can);
      const bell = buildRotorBell(
        { shaftRadius, rimInnerRadius: magnetSeatRadius * 0.86, outerRadius: rotorRadius, thickness: bellThickness, rise: bellRise },
        materials.rotorBell,
      );
      geometries.push(...bell.geometries);
      bell.group.position.z = bellInnerFaceZ;
      makeSelectable(bell.group, {
        id: '3d-rotor-bell',
        kind: 'rotor',
        label: 'Rotor bell',
        role: 'Closes the outer rotor and is clamped to the shaft, so the shaft turns with it · illustrative · not part of the EM model',
      });
      rotorBellGroup.add(bell.group);
    }

    // Drive-end convention: the shaft runs long out the front face toward the
    // load, with only a short stub behind the rear bearing plane. Both ends are
    // measured off the cap's outer face so the shaft always passes through both
    // castings — a visible drive stub at the front, just enough to read as
    // supported at the rear.
    const shaftCapClearance = capOuterFaceZ - stackDepth / 2;
    const shaftFrontOverhang = Math.max(
      stackDepth * 0.34,
      shaftRadius * 1.6,
      shaftCapClearance + stackDepth * 0.28,
      outerRotor ? bellOuterFaceZ - stackDepth / 2 + stackDepth * 0.3 : 0,
    );
    // A full-width outrunner rear plate must sit behind the end turns and their
    // crossovers, rather than cutting through the coils at the old hub-only cap.
    const rearCapCenterZ = outerRotor
      ? Math.max(
          stackDepth / 2,
          -new THREE.Box3().setFromObject(windingsGroup).min.z,
          harnessGroup ? -new THREE.Box3().setFromObject(harnessGroup).min.z : 0,
        ) + Math.max(0.6, capThickness * 0.8) + capThickness / 2
      : capCenterZ;
    const shaftRearStub = rearCapCenterZ + capThickness / 2 - stackDepth / 2 + stackDepth * 0.06;
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

    // The shaft carries no key: the mark on the drive-end bearing's turning race shows the rotation.

    const polePitch = (Math.PI * 2) / Math.max(1, config.rotor.pole_count);
    if (config.topology === 'SPM') {
      const magnetInnerRadius = outerRotor ? magnetSeatRadius - config.rotor.magnet_thickness_mm : rotorRadius;
      const magnetOuterRadius = outerRotor ? magnetSeatRadius : rotorRadius + config.rotor.magnet_thickness_mm;
      const magnetHalfSpan = Math.max(0.04, polePitch * Math.min(1, magnetPoleCoverage(config)) / 2);
      // One piece per pole, coloured by the pole it presents to the stator.
      const magnetGeometry = extrude(
        sectorShape(magnetInnerRadius, magnetOuterRadius, magnetHalfSpan),
        stackDepth * 0.91,
        Math.min(edgeBevel, config.rotor.magnet_thickness_mm * 0.12),
      );
      geometries.push(magnetGeometry);
      for (let pole = 0; pole < config.rotor.pole_count; pole += 1) {
        const northAtAirgap = pole % 2 === 0;
        const magnetUnit = new THREE.Group();
        const magnet = new THREE.Mesh(
          magnetGeometry,
          northAtAirgap ? materials.magnetNorth : materials.magnetSouth,
        );
        magnetUnit.rotation.z = pole * polePitch;
        makeSelectable(magnetUnit, {
          id: `3d-magnet-${pole + 1}`,
          kind: 'magnet',
          label: `Magnet ${northAtAirgap ? 'N' : 'S'} · pole ${pole + 1}`,
          role: `Permanent magnet · ${northAtAirgap ? 'north' : 'south'} pole faces the air gap`,
          poleIndex: pole + 1,
        });
        magnetUnit.add(magnet);
        magnetsGroup.add(magnetUnit);
        registerRadialExplosion(magnetUnit, pole * polePitch, (outerRotor ? -0.1 : 0.14) * rotorRadius);
      }
    } else if (config.rotor.ipm_topology === 'pyleecan_holem50') {
      // Experimental HoleM50 pockets have no parametric 3D model; the 2D
      // cross-section shows the solved geometry. The rotor core still renders.
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
          const magnetGeometry = new THREE.BoxGeometry(
            placement.effectiveLengthMm,
            magnetDepth,
            magnetAxialDepth,
          );
          geometries.push(pocketGeometry, magnetGeometry);
          const northAtAirgap = pole % 2 === 0;
          const pocket = new THREE.Mesh(pocketGeometry, materials.pocket);
          const magnetUnit = new THREE.Group();
          const magnet = new THREE.Mesh(
            magnetGeometry,
            northAtAirgap ? materials.magnetNorth : materials.magnetSouth,
          );
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
            role: `Buried permanent magnet · ${northAtAirgap ? 'north' : 'south'} pole faces the air gap`,
            poleIndex: pole + 1,
          });
          addEdges(pocket, 0x0b1220);
          addEdges(magnet, northAtAirgap ? 0x7f1d1d : 0x1e3a8a);
          pocketsGroup.add(pocket);
          magnetUnit.add(magnet);
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
    const hubBearingOuterRadius = Math.min(yokeOuterRadius * 0.98, shaftRadius * 2.4);
    // The rear cap cups over the end turns and laps the rotating can's rear
    // edge. Its skirt stays outside the can with a small radial running gap.
    const rearCapRadialClearance = Math.max(0.3, rotorRadius * 0.018);
    const rearCapWallThickness = Math.max(0.6, rotorRadius * 0.035);
    const rearCapSkirtInnerRadius = rotorRadius + rearCapRadialClearance;
    const rearCapRadius = rearCapSkirtInnerRadius + rearCapWallThickness;
    [1, -1].forEach((zSign) => {
      const isDriveEnd = zSign > 0;
      const end = isDriveEnd ? 'drive' : 'non-drive';

      const bearing = buildBearing(
        outerRotor
          ? { boreRadius: shaftRadius, outerRadius: hubBearingOuterRadius, width: bearingWidth }
          : { boreRadius: shaftRadius, outerRadius: capBoreRadius, width: bearingWidth },
        {
          race: materials.bearingRace,
          ball: materials.bearingBall,
          cage: materials.bearingCage,
          motionMark: materials.bearingMotionMark,
          seal: materials.bearingSeal,
          sealLip: materials.bearingSealLip,
        },
      );
      geometries.push(...bearing.geometries);
      bearingRigs.push(bearing);
      // Seated in the cap bore, inboard of the cap's outer face — the bearing
      // never hangs off the shaft outside the casting. An outer rotor's shaft
      // runs through the stator hub, so its bearings sit in the hub bore.
      bearing.group.position.z = zSign * (outerRotor ? stackDepth / 2 - bearingWidth * 0.7 : capCenterZ);
      makeSelectable(bearing.group, {
        id: `3d-bearing-${end}`,
        kind: 'bearing',
        label: `Bearing · ${end} end`,
        role: outerRotor
          ? 'Outer race fixed in the stator hub · inner race follows shaft · balls roll in a slower cage · illustrative'
          : 'Outer race fixed to end cap · inner race follows shaft · balls roll in a slower cage · illustrative',
      });
      (isDriveEnd ? driveBearingGroup : rearBearingGroup).add(bearing.group);

      if (outerRotor && isDriveEnd) return;
      const cap = buildEndCap(
        outerRotor
          ? { boreRadius: shaftRadius * 1.3, outerRadius: rearCapRadius, thickness: capThickness, hubDepth: rearCapCenterZ - stackDepth / 2 }
          : { boreRadius: capBoreRadius, outerRadius, thickness: capThickness, hubDepth: stackDepth * 0.1 },
        isDriveEnd ? materials.endcap : materials.endcapRear,
      );
      if (outerRotor) {
        const skirtOverlap = Math.min(capThickness * 0.4, stackDepth * 0.04);
        const skirtDepth = rearCapCenterZ - capThickness / 2 - stackDepth / 2 + skirtOverlap;
        const skirtGeometry = annulusGeometry(
          rearCapSkirtInnerRadius, rearCapRadius, skirtDepth,
          Math.min(capThickness * 0.1, rearCapWallThickness * 0.2),
        );
        cap.geometries.push(skirtGeometry);
        const skirt = new THREE.Mesh(skirtGeometry, materials.endcapRear);
        // Local -z is inboard; the rear cap is mirrored below, as is its hub.
        skirt.position.z = -capThickness / 2 - skirtDepth / 2;
        addEdges(skirt);
        cap.group.add(skirt);
        // Bolt holes through the stator mount, where it fixes to the frame.
        const holeRadius = Math.max(0.3, rearCapRadius * 0.035);
        const holeGeometry = new THREE.CylinderGeometry(holeRadius, holeRadius, capThickness * 1.04, 20);
        holeGeometry.rotateX(Math.PI / 2);
        cap.geometries.push(holeGeometry);
        // Disposed with the rest when the scene is torn down (scene.traverse).
        const holeMaterial = new THREE.MeshStandardMaterial({ color: 0x0b1220, roughness: 0.9 });
        const holeRadiusPosition = (hubBearingOuterRadius + rearCapRadius) / 2 + rearCapRadius * 0.12;
        for (let hole = 0; hole < 4; hole += 1) {
          const angle = Math.PI / 4 + (hole * Math.PI) / 2;
          const mesh = new THREE.Mesh(holeGeometry, holeMaterial);
          mesh.position.set(holeRadiusPosition * Math.cos(angle), holeRadiusPosition * Math.sin(angle), 0);
          cap.group.add(mesh);
        }
      }
      geometries.push(...cap.geometries);
      // Mirror the casting so both hubs reach inboard toward the stack.
      cap.group.scale.z = zSign;
      cap.group.position.z = zSign * (isDriveEnd ? capCenterZ : rearCapCenterZ);
      makeSelectable(cap.group, {
        id: `3d-endcap-${end}`,
        kind: 'endcap',
        label: outerRotor ? 'Stator mount · non-drive end' : `End cap · ${end} end`,
        role: outerRotor
          ? 'Bolts the stator hub to the frame · illustrative · not part of the EM model'
          : 'Bolted end housing carrying the bearing · illustrative · not part of the EM model',
      });
      (isDriveEnd ? driveEndcapGroup : rearEndcapGroup).add(cap.group);
    });
    bearingRigsRef.current = bearingRigs;
    scene.add(driveBearingGroup, driveEndcapGroup, rearBearingGroup, rearEndcapGroup);
    if (outerRotor && yokeOuterRadius - hubBearingOuterRadius > 0.2) {
      // The stator is pressed onto a fixed tube that carries both bearings, so
      // the shaft turns inside a stationary stator.
      const tubeGeometry = annulusGeometry(hubBearingOuterRadius, yokeOuterRadius, stackDepth);
      geometries.push(tubeGeometry);
      const tube = new THREE.Mesh(tubeGeometry, materials.endcapRear);
      makeSelectable(tube, {
        id: '3d-stator-hub',
        kind: 'stator',
        label: 'Stator hub · bearing tube',
        role: 'Fixed sleeve the stator is pressed onto; it holds both shaft bearings · illustrative',
      });
      addEdges(tube);
      statorGroup.add(tube);
    }

    // The air gap is a volume between two coaxial cylindrical surfaces, not a
    // single circular wire. Draw the complete annular sleeve across the stack.
    const airgapGeometry = outerRotor
      ? annulusGeometry(
        statorInnerRadius,
        magnetSeatRadius - (config.topology === 'SPM' ? config.rotor.magnet_thickness_mm : 0),
        stackDepth * 0.96,
      )
      : annulusGeometry(
        rotorRadius + (config.topology === 'SPM' ? config.rotor.magnet_thickness_mm : 0),
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
    addPartChip(outerRotor ? 'Stator mount' : 'End cap', rearEndcapGroup, new THREE.Vector3(0, chipLane * 1.3, -rearCapCenterZ));
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
    addPartChip(outerRotor ? 'Rotor can' : 'Rotor core', rotorCoreGroup, new THREE.Vector3(0, -Math.max(rotorRadius * 1.28, chipLane * 0.7), 0));
    if (outerRotor) addPartChip('Rotor bell', rotorBellGroup, new THREE.Vector3(0, chipLane * 1.2, bellOuterFaceZ));
    addPartChip('Shaft', shaftGroup, new THREE.Vector3(0, shaftRadius + chipLane * 0.22, 0));
    addPartChip('Bearing', driveBearingGroup, new THREE.Vector3(0, -chipLane * 1.22, capCenterZ));
    if (!outerRotor) addPartChip('End cap', driveEndcapGroup, new THREE.Vector3(0, chipLane * 1.3, capCenterZ));

    // Slot, tooth and coil-side chips on the stack's end face, for the Overlay toggles.
    const overlayLabels: Array<{ sprite: THREE.Sprite; kind: keyof Motor3DOverlays }> = [];
    const slotTotal = Math.max(1, config.stator.slot_count);
    const slotBackRadius = outerRotor ? yokeOuterRadius : yokeInnerRadius;
    const yokeFarRadius = outerRotor ? yokeInnerRadius : outerRadius;
    const along = (from: number, to: number, share: number) => from + (to - from) * share;
    const labelHeight = THREE.MathUtils.clamp(
      (Math.PI * 2 * along(statorInnerRadius, slotBackRadius, 0.5)) / slotTotal * 0.42,
      outerRadius * 0.03,
      outerRadius * 0.07,
    );
    const addOverlayLabel = (kind: keyof Motor3DOverlays, text: string, angle: number, radius: number, stroke?: string) => {
      const { sprite, texture } = makeChipSprite(text, stroke);
      if (texture) chipTextures.push(texture);
      sprite.material.opacity = 1;
      sprite.scale.set(labelHeight * (sprite.userData.aspect as number), labelHeight, 1);
      sprite.position.set(Math.cos(angle) * radius, Math.sin(angle) * radius, stackDepth / 2);
      sprite.visible = false;
      sprite.raycast = () => {};
      scene.add(sprite);
      overlayLabels.push({ sprite, kind });
    };
    for (let slot = 0; slot < config.stator.slot_count; slot += 1) {
      addOverlayLabel('slots', String(slot + 1), slot * slotPitch, along(statorInnerRadius, slotBackRadius, 0.5), 'rgba(255, 255, 255, 0.34)');
      addOverlayLabel('teeth', `T${slot + 1}`, (slot + 0.5) * slotPitch, along(statorInnerRadius, slotBackRadius, 0.8), 'rgba(255, 255, 255, 0.34)');
    }
    // Coil sides sit on the yoke behind their slot; a second side in the slot steps further back.
    // The layout comes with the preview, after the scene is built, so its chips are made when it arrives.
    let labelledLayout: WindingSide[] | null = null;
    const syncWindingLabels = (layout: WindingSide[] | null) => {
      if (layout === labelledLayout) return;
      labelledLayout = layout;
      for (let index = overlayLabels.length - 1; index >= 0; index -= 1) {
        const { sprite, kind } = overlayLabels[index];
        if (kind !== 'windings') continue;
        scene.remove(sprite);
        sprite.material.map?.dispose();
        sprite.material.dispose();
        overlayLabels.splice(index, 1);
      }
      const sidesPlaced = new Map<number, number>();
      (layout ?? []).forEach((side) => {
        const placed = sidesPlaced.get(side.slot_index) ?? 0;
        sidesPlaced.set(side.slot_index, placed + 1);
        addOverlayLabel(
          'windings',
          `${side.phase}${side.direction === 'in' ? '+' : '\u2212'}`,
          side.slot_index * slotPitch,
          along(slotBackRadius, yokeFarRadius, Math.min(0.9, 0.3 + placed * 0.45)),
          PUBLIC_PHASE_COLORS[side.phase],
        );
      });
    };

    // A distributed winding drawn coil by coil, as the backend lays it out: each coil
    // is a wound loop through its two slots with an end turn over each end of the stack.
    // The coil list comes with the preview, after the scene is built.
    let builtCoils = '';
    const distributedCoils: THREE.Mesh[] = [];
    const syncDistributedCoils = (coils: PublicWindingCoil[] | null, wireDiameter: number | null, strandsInHand: number) => {
      if (concentratedCoil) return;
      const spanning = (coils ?? []).filter((coil) => !coil.tooth_wound && coil.slot_in !== coil.slot_out);
      const signature = JSON.stringify([spanning, wireDiameter, strandsInHand]);
      if (signature === builtCoils) return;
      builtCoils = signature;
      distributedCoils.splice(0).forEach((mesh) => {
        windingsGroup.remove(mesh);
        mesh.geometry.dispose();
      });
      slotBlocks.forEach((block) => { block.visible = spanning.length === 0; });
      if (spanning.length === 0) return;
      const boreEnd = outerRotor ? statorInnerRadius - 1.2 : statorInnerRadius + 1.2;
      const yokeEnd = outerRotor
        ? Math.min(statorInnerRadius - 2, yokeInnerRadius + 1)
        : Math.max(statorInnerRadius + 2, yokeInnerRadius - 1);
      const middle = (boreEnd + yokeEnd) / 2;
      // Two coil sides share a slot in a two-layer winding: the side going in takes the yoke half, the one coming out the bore half.
      const sidesInSlot = new Map<number, number>();
      spanning.forEach((coil) => [coil.slot_in, coil.slot_out].forEach((slot) => sidesInSlot.set(slot, (sidesInSlot.get(slot) ?? 0) + 1)));
      const twoLayer = Math.max(...sidesInSlot.values()) > 1;
      const coilMaterials = { A: materials.coilA, B: materials.coilB, C: materials.coilC };
      // With two coil sides in a slot, each side holds half the slot's turns (backend/gmsh_solver.py
      // _coil_side_turn_fraction), so each drawn coil carries half of Turns / Coil.
      const turnsPerDrawnCoil = Math.max(1, Math.round(config.winding.turns_per_coil / (twoLayer ? 2 : 1)));
      spanning.forEach((coil) => {
        const { geometry: coilGeometry, strandCount } = buildDistributedCoil({
          slotInAngle: coil.slot_in * slotPitch,
          slotOutAngle: coil.slot_out * slotPitch,
          inBand: twoLayer ? [middle, yokeEnd] : [boreEnd, yokeEnd],
          outBand: twoLayer ? [boreEnd, middle] : [boreEnd, yokeEnd],
          slotHalfAngle: Math.max(0.04, slotPitch * 0.18),
          stackHalf: stackDepth / 2,
          yokeSide: outerRotor ? -1 : 1,
          turns: turnsPerDrawnCoil,
          turnDiameter: wireDiameter ?? undefined,
          yokeRoom: Math.abs(yokeFarRadius - yokeEnd) - 2,
          // About 800 loops over the whole winding, at most 24 a coil as the tooth coils draw.
          maxStrands: Math.max(6, Math.min(24, Math.floor(800 / spanning.length))),
        });
        const mesh = new THREE.Mesh(coilGeometry, coilMaterials[coil.phase]);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        makeSelectable(mesh, {
          id: `3d-winding-coil-${coil.coil_index + 1}`,
          kind: 'winding',
          label: `Coil ${coil.coil_index + 1} · phase ${coil.phase} · slots ${coil.slot_in + 1} to ${coil.slot_out + 1}`,
          role: 'Distributed coil: two slot sides joined by an end turn at each end of the stack',
          slotIndex: coil.slot_in + 1,
          phase: coil.phase,
          windingModel: `${turnsPerDrawnCoil} turns in this coil${twoLayer ? ' (half the slot)' : ''} · drawn as ${strandCount} wire loops${strandsInHand > 1 ? ` · each turn is ${strandsInHand} strands in hand` : ''}`,
        });
        windingsGroup.add(mesh);
        distributedCoils.push(mesh);
      });
    };

    // Coil colours, Phases and Tooth poles recolour materials in place, so no toggle rebuilds the scene.
    const plainCoil = new THREE.Color(renderTargetColor(PUBLIC_MOTOR_COLORS.winding));
    const toothBase = materials.tooth.color.clone();
    const northPole = new THREE.Color(renderTargetColor(PUBLIC_MOTOR_COLORS.magnetNorth));
    const southPole = new THREE.Color(renderTargetColor(PUBLIC_MOTOR_COLORS.magnetSouth));
    const phaseTints = (['A', 'B', 'C'] as const).map((phase) => (
      [materials[`coil${phase}`], materials[`phase${phase}`], harnessByPhase[phase]]
        .filter((material): material is THREE.MeshPhysicalMaterial => Boolean(material))
        .map((material) => ({ material, base: material.color.clone() }))
    ));
    const applyDisplay = () => {
      const shown = displayRef.current;
      syncWindingLabels(shown.windingLayout);
      syncDistributedCoils(shown.windingCoils, shown.turnDiameter, shown.strandsInHand);
      const drive = shown.phaseDrive;
      const currents = (shown.showPhases || shown.showToothPoles) && drive
        ? phaseCurrents(drive, rotorElectricalDeg(shown.rotorAngleDeg, drive.poleCount))
        : null;
      phaseTints.forEach((tints, index) => {
        // The coils hold a steady colour under Phases, as in 2D: phase colours, or copper with Coil colors off.
        const strength = 1;
        tints.forEach(({ material, base }) => {
          material.color.copy(shown.plainWinding ? plainCoil : base).multiplyScalar(strength);
        });
      });
      const poles = shown.showToothPoles && currents && shown.windingLayout?.length
        ? toothPoles(slotCurrents(shown.windingLayout, config.stator.slot_count, currents), outerRotor ? 'outward' : 'inward')
        : null;
      toothMaterials.forEach((material, tooth) => {
        const strength = poles?.[tooth] ?? 0;
        material.color.copy(toothBase);
        if (Math.abs(strength) > 0.06) material.color.lerp(strength > 0 ? northPole : southPole, 0.25 + 0.6 * Math.abs(strength));
      });
    };
    applyDisplayRef.current = applyDisplay;
    applyDisplay();

    // Phases in 3D: the 2D view's waveforms, wired to where the drive leads come in
    // at the back of the motor. A machine drawn without its leads takes three points
    // on the rear face of the yoke instead.
    const rearYokeRadius = (slotBackRadius + yokeFarRadius) / 2;
    const leadEntries = (['A', 'B', 'C'] as const).map((phase, index) => leadLandings[phase]
      ?? new THREE.Vector3(Math.cos(Math.PI + (index - 1) * 0.12) * rearYokeRadius, Math.sin(Math.PI + (index - 1) * 0.12) * rearYokeRadius, -stackDepth / 2));
    let viewShift = 0;
    let viewShiftSize = '';
    /** Moves the motor right to make room for the waveforms; null when they are not shown. */
    const phaseDrivePanel = () => {
      const shown = displayRef.current;
      const width = host.clientWidth;
      const height = host.clientHeight;
      const frame = shown.showPhases && shown.phaseDrive && introProgressRef.current === null ? phaseDriveFrame(width, height) : null;
      const shift = frame ? Math.round((frame.panel.x + frame.panel.width) / 2) : 0;
      // The motor is drawn below the part toggles and the peel slider, a little smaller, so it never runs behind them.
      const peel = host.querySelector<HTMLElement>('.public-3d-peel');
      const top = peel && peel.offsetParent !== null && introProgressRef.current === null
        ? Math.round(peel.getBoundingClientRect().bottom - host.getBoundingClientRect().top + 6)
        : 0;
      const size = `${width}x${height}x${top}`;
      if (shift !== viewShift || size !== viewShiftSize) {
        viewShift = shift;
        viewShiftSize = size;
        if (shift > 0 || top > 0) {
          const scale = Math.max(0.5, (height - top) / height);
          camera.setViewOffset(width * scale, height * scale, -(width * (1 - scale)) / 2 - shift, -top, width, height);
        } else camera.clearViewOffset();
      }
      if (!frame) return null;
      // Below the part toggles and the peel slider at the top left.
      const panel = { ...frame.panel };
      // Below the bars over the motor where there are any; otherwise just below the design's name chip.
      panel.y = Math.max(panel.y, top > 0 ? 104 : 56);
      panel.height = Math.max(110, Math.min(panel.height, height - 28 - panel.y));
      return { panel, width, height };
    };
    const drawPhaseDriveOverlay = (layout: ReturnType<typeof phaseDrivePanel>) => {
      const shown = displayRef.current;
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      const width = host.clientWidth;
      const height = host.clientHeight;
      const canvases = [driveUnderRef.current, driveOverRef.current];
      const contexts = canvases.map((overlay) => {
        if (!overlay) return null;
        if (overlay.width !== Math.round(width * pixelRatio) || overlay.height !== Math.round(height * pixelRatio)) {
          overlay.width = Math.round(width * pixelRatio);
          overlay.height = Math.round(height * pixelRatio);
        }
        const context = overlay.getContext('2d');
        context?.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        context?.clearRect(0, 0, width, height);
        return context ?? null;
      });
      const drive = shown.phaseDrive;
      if (!layout || !drive) return;
      const carrier = harnessGroup ?? statorGroup;
      const ends = leadEntries.map((entry) => {
        const point = entry.clone().add(carrier.position).project(camera);
        return [(point.x + 1) / 2 * width, (1 - point.y) / 2 * height] as [number, number];
      });
      // One right-angle turn each, staggered as in 2D so the wires do not cross on the way down or up.
      const strips = phaseStrips(layout.panel);
      const stripRight = layout.panel.x + layout.panel.width;
      const nearest = Math.min(...ends.map(([x]) => x));
      const lane = Math.max(6, Math.min(16, (nearest - stripRight) / 5));
      const wiresDrop = strips[1].y + strips[1].height / 2 <= ends[1][1];
      const leads = ends.map((end, index) => ({
        terminal: [Math.max(stripRight + STRIP_END + 4, nearest - lane * (wiresDrop ? index + 1 : 3 - index)), end[1]] as [number, number],
        motor: end,
      }));
      const rotorElecDeg = rotorElectricalDeg(shown.rotorAngleDeg, drive.poleCount);
      // Looking at the front, the leads are behind the motor: draw under it.
      const leadsInSight = camera.position.z < leadEntries[1].z + carrier.position.z;
      const context = contexts[leadsInSight ? 1 : 0];
      if (context) drawPhaseDriveWired(context, layout.panel, drive, rotorElecDeg, phaseCurrents(drive, rotorElecDeg), leads, shown.previewRpm);
    };

    // Show/hide plumbing. Each toggle owns the groups that only read as a part
    // together — hiding the stator without its teeth, or the coils without
    // their rear links, would just leave a fragment floating in the bore.
    const hideableGroups: Record<HideablePartId, THREE.Object3D[]> = {
      stator: [statorGroup, teethGroup],
      windings: harnessGroup ? [windingsGroup, harnessGroup] : [windingsGroup],
      rotor: [rotorCoreGroup],
      rotorBell: [rotorBellGroup],
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
      rotorBellGroup.position.z = rotorCoreGroup.position.z;
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
      // The number chips belong to the assembled stator: they go while it is hidden or taken apart.
      overlayLabels.forEach(({ sprite, kind }) => {
        sprite.visible = displayRef.current.overlays[kind] && normalized < 0.05 && statorGroup.visible;
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
      requestRenderRef.current?.();
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
      requestRenderRef.current?.();
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(host);
    resize();

    const render = () => {
      animationFrame = renderContinuously ? window.requestAnimationFrame(render) : 0;
      displayedExplosion = THREE.MathUtils.lerp(
        displayedExplosion,
        explodedAmountRef.current,
        renderContinuously ? 0.095 : 1,
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
      const driveLayout = phaseDrivePanel();
      renderer.render(scene, camera);
      drawPhaseDriveOverlay(driveLayout);
    };
    const requestRender = () => {
      if (!animationFrame) animationFrame = window.requestAnimationFrame(render);
    };
    requestRenderRef.current = requestRender;
    controls.addEventListener('change', requestRender);
    requestRender();

    return () => {
      window.cancelAnimationFrame(animationFrame);
      requestRenderRef.current = null;
      resizeObserver.disconnect();
      controls.removeEventListener('change', requestRender);
      controls.dispose();
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointerup', onPointerUp);
      canvas.removeEventListener('wheel', onWheel);
      if (selectionHelper) {
        selectionHelper.geometry.dispose();
        selectionHelper.material.dispose();
      }
      keptViewRef.current = { frame: viewFrame, position: camera.position.clone(), target: controls.target.clone() };
      resetCameraRef.current = null;
      rotorRef.current = null;
      bearingRigsRef.current = [];
      applyPartVisibilityRef.current = null;
      applyDisplayRef.current = null;
      distributedCoils.forEach((mesh) => mesh.geometry.dispose());
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
    applyDisplayRef.current?.();
    requestRenderRef.current?.();
  }, [plainWinding, showToothPoles, showPhases, overlays, phaseDrive, rotorAngleDeg, windingLayout, windingCoils, turnDiameter, strandsInHand, previewRpm]);

  useEffect(() => {
    if (!rotorRef.current) return;
    rotorRef.current.rotation.z = -rotorAngleDeg * Math.PI / 180;
    syncBearingKinematics(bearingRigsRef.current, rotorRef.current.rotation.z);
    requestRenderRef.current?.();
  }, [rotorAngleDeg]);

  useEffect(() => {
    explodedAmountRef.current = explodedAmount;
    requestRenderRef.current?.();
  }, [explodedAmount]);

  useEffect(() => {
    if (resetSignal > 0) {
      resetCameraRef.current?.();
      requestRenderRef.current?.();
    }
  }, [resetSignal]);

  return (
    <div
      className={`public-motor-3d-stage${introProgress !== null ? ' is-intro' : ''}`}
      ref={hostRef}
      aria-label="Interactive 3D motor view"
    >
      <canvas className="public-3d-drive is-under" ref={driveUnderRef} aria-hidden="true" />
      <canvas ref={canvasRef} />
      <canvas className="public-3d-drive is-over" ref={driveOverRef} aria-hidden="true" />
      {introProgress === null && !controlsInDock && (
        <div className="public-3d-part-toggles" role="group" aria-label="Show or hide motor parts">
          {availableParts.map(({ id, label }) => {
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
      {introProgress === null && !controlsInDock && (
        <label className="public-3d-peel" title="Slide left to take the motor apart from the outside in; all the way right shows every part">
          <span>Outside in</span>
          <input
            type="range"
            min={0}
            max={peelOrder.length}
            step={1}
            value={partsLeft}
            aria-label="Parts shown, from the shaft outwards"
            aria-valuetext={outermostShown ? `Out to the ${outermostShown.toLowerCase()}` : 'No parts'}
            onChange={(event) => peelTo(Number(event.target.value))}
          />
          <em>{outermostShown ?? 'None'}</em>
        </label>
      )}
      {controlsInDock && dockSlot && createPortal(
        <>
          <span className="vc-group public-dock-peel" role="group" aria-label="Peel the motor from the outside in" title="Slide left to take the motor apart from the outside in; all the way right shows every part">
            <span className="public-dock-group-label" aria-hidden="true">Outside in</span>
            <input
              type="range"
              min={0}
              max={peelOrder.length}
              step={1}
              value={partsLeft}
              aria-label="Parts shown, from the shaft outwards"
              aria-valuetext={outermostShown ? `Out to the ${outermostShown.toLowerCase()}` : 'No parts'}
              onChange={(event) => peelTo(Number(event.target.value))}
            />
            <output aria-live="polite">{outermostShown ?? 'None'}</output>
          </span>
          <span className="vc-group public-dock-parts" role="group" aria-label="Motor parts">
            <span className="public-dock-group-label" aria-hidden="true">Parts</span>
            <details
              className="public-field-layer-menu public-dock-more"
              // Opens above the dock, lined up with its button, as More does on the Mesh tab.
              onToggle={(event) => {
                const menu = event.currentTarget;
                const dock = menu.closest('.viewport-bottom-bar');
                const panel = menu.querySelector<HTMLElement>('.public-field-layer-controls');
                // The list is placed against whatever positions it, so it is measured from there: clear of the whole dock, tab row included.
                const anchor = panel?.offsetParent?.getBoundingClientRect();
                if (dock && panel && anchor) {
                  panel.style.left = `${menu.getBoundingClientRect().left - anchor.left}px`;
                  panel.style.bottom = `${anchor.bottom - dock.getBoundingClientRect().top + 6}px`;
                }
              }}
            >
              <summary>Shown<em>{shownPartCount} of {availableParts.length}</em></summary>
              <div className="public-field-layer-controls" role="group" aria-label="Show or hide motor parts">
                {availableParts.map(({ id, label }) => {
                  const shown = !hiddenParts.has(id);
                  return (
                    <button
                      key={id}
                      type="button"
                      aria-pressed={shown}
                      title={shown ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
                      onClick={() => togglePart(id)}
                    >
                      <i aria-hidden="true" />{label}
                    </button>
                  );
                })}
              </div>
            </details>
          </span>
        </>,
        dockSlot,
      )}
      {introProgress !== null && <div className="public-3d-hint">Assembly view · turning to engineering cross-section</div>}
      {failed && <div className="public-viewport-message">3D preview is unavailable on this graphics device.</div>}
    </div>
  );
}
