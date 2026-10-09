import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

/**
 * Concentrated tooth-coil geometry builder for the public 3D motor view.
 *
 * Coordinate frame: the coil is generated in the local frame of a stator tooth
 * whose centreline points along +X with the lamination stack centred on Z, so
 * X is radial, Y is tangential, and Z is axial. Rotating the produced mesh by
 * the tooth angle places it, exactly like the extruded tooth geometry itself.
 *
 * The builder is standalone on purpose: future tutorial scenes can reuse the
 * racetrack curve and the strand-packing logic for coils, electromagnets, and
 * other wound components without dragging in the motor scene.
 */

export interface ConcentratedCoilSpec {
  /** Stator bore radius in millimetres. */
  boreRadius: number;
  /** Radius where the slot region meets the stator yoke, in millimetres. */
  yokeInnerRadius: number;
  /** Tooth half-angle at the bore, in radians. */
  toothHalfAngleInnerRad: number;
  /** Tooth half-angle at the yoke, in radians. */
  toothHalfAngleOuterRad: number;
  /** Angular slot pitch, in radians. */
  slotPitchRad: number;
  /** Lamination stack length, in millimetres. */
  stackLength: number;
  /** Electrical turns per coil; rendering may bundle these into fewer strands. */
  turnsPerCoil: number;
}

export interface ConcentratedCoilModel {
  /** Merged strand geometry in the tooth local frame. Caller owns disposal. */
  geometry: THREE.BufferGeometry;
  /** Number of wire loops actually rendered. */
  strandCount: number;
  /** Electrical turn count the rendered bundle represents. */
  turnsRepresented: number;
  /** Tangential wire layers in the rendered bundle. */
  wireLayers: number;
  /** Radial turns per layer in the rendered bundle. */
  turnsPerLayer: number;
  /** Rendered conductor radius, in millimetres. */
  wireRadius: number;
  /** How far the end turns reach past each stack face, in millimetres. */
  axialOverhang: number;
  /** Radial centre of the wound bundle, in millimetres. */
  bundleCenterRadius: number;
  /** Thin slot-liner insulation between tooth steel and the bundle. Caller owns disposal. */
  linerGeometry: THREE.BufferGeometry;
}

interface RacetrackSegment {
  length: number;
  sample: (distance: number, target: THREE.Vector3) => THREE.Vector3;
}

/**
 * Closed rounded-rectangle wire path in a plane of constant radial station.
 * The straight runs hug both tangential sides of the tooth; the rounded ends
 * form the front and rear end turns. Parameterised by arc length so tube
 * sampling stays uniform along the loop.
 */
export class RacetrackCurve extends THREE.Curve<THREE.Vector3> {
  private readonly segments: RacetrackSegment[];

  readonly perimeter: number;

  constructor(radialStation: number, halfWidth: number, halfStraight: number, cornerRadius: number) {
    super();
    const x = radialStation;
    const width = Math.max(0.05, halfWidth);
    const straight = Math.max(0.05, halfStraight);
    const corner = THREE.MathUtils.clamp(cornerRadius, 0.02, width * 0.98);
    const cross = width - corner;
    const arc = (centerY: number, centerZ: number, startAngle: number): RacetrackSegment => ({
      length: corner * Math.PI / 2,
      sample: (distance, target) => {
        const angle = startAngle + distance / corner;
        return target.set(x, centerY + corner * Math.cos(angle), centerZ + corner * Math.sin(angle));
      },
    });
    const line = (fromY: number, fromZ: number, toY: number, toZ: number): RacetrackSegment => {
      const length = Math.hypot(toY - fromY, toZ - fromZ);
      return {
        length,
        sample: (distance, target) => {
          const fraction = length === 0 ? 0 : distance / length;
          return target.set(x, fromY + (toY - fromY) * fraction, fromZ + (toZ - fromZ) * fraction);
        },
      };
    };
    this.segments = [
      line(width, -straight, width, straight),
      arc(cross, straight, 0),
      line(cross, straight + corner, -cross, straight + corner),
      arc(-cross, straight, Math.PI / 2),
      line(-width, straight, -width, -straight),
      arc(-cross, -straight, Math.PI),
      line(-cross, -straight - corner, cross, -straight - corner),
      arc(cross, -straight, Math.PI * 1.5),
    ];
    this.perimeter = this.segments.reduce((total, segment) => total + segment.length, 0);
  }

  override getPoint(t: number, optionalTarget = new THREE.Vector3()): THREE.Vector3 {
    let distance = THREE.MathUtils.euclideanModulo(t, 1) * this.perimeter;
    for (const segment of this.segments) {
      if (distance <= segment.length) return segment.sample(distance, optionalTarget);
      distance -= segment.length;
    }
    const last = this.segments[this.segments.length - 1];
    return last.sample(last.length, optionalTarget);
  }
}

const MAX_RENDERED_STRANDS = 24;
const MAX_WIRE_LAYERS = 4;
const MAX_WIRE_DIAMETER = 5.2;

/**
 * Build one concentrated tooth coil as a merged bundle of insulated-wire
 * strands. Identical teeth should share the returned geometry across meshes;
 * the whole bundle is a single static geometry with one draw call per tooth.
 */
export function buildConcentratedCoil(spec: ConcentratedCoilSpec): ConcentratedCoilModel {
  const boreX = spec.boreRadius * Math.cos(spec.toothHalfAngleInnerRad);
  const boreFlank = spec.boreRadius * Math.sin(spec.toothHalfAngleInnerRad);
  const yokeX = spec.yokeInnerRadius * Math.cos(spec.toothHalfAngleOuterRad);
  const yokeFlank = spec.yokeInnerRadius * Math.sin(spec.toothHalfAngleOuterRad);
  const flankHalfWidthAt = (x: number) => {
    const fraction = THREE.MathUtils.clamp((x - boreX) / Math.max(1e-6, yokeX - boreX), 0, 1);
    return boreFlank + (yokeFlank - boreFlank) * fraction;
  };
  const slotHalfAt = (x: number) => x * Math.tan(spec.slotPitchRad / 2);
  const flankGap = 0.35;
  const slotGap = Math.max(0.3, spec.yokeInnerRadius * 0.005);

  const provisionalInset = Math.max(1.5, (yokeX - boreX) * 0.06);
  const sizingStart = boreX + provisionalInset;
  const sizingSpan = Math.max(1, yokeX - provisionalInset * 0.8 - sizingStart);
  const sizingAvail = Math.max(0.5, slotHalfAt(sizingStart) - slotGap - flankHalfWidthAt(sizingStart) - flankGap);

  const turns = Math.max(1, Math.round(spec.turnsPerCoil) || 1);
  const strandTarget = Math.min(turns, MAX_RENDERED_STRANDS);
  let wireLayers = 1;
  let turnsPerLayer = strandTarget;
  let bestDiameter = 0;
  for (let layers = 1; layers <= Math.min(MAX_WIRE_LAYERS, strandTarget); layers += 1) {
    const rows = Math.ceil(strandTarget / layers);
    const diameter = Math.min(sizingSpan / rows, sizingAvail / layers, MAX_WIRE_DIAMETER);
    if (diameter > bestDiameter) {
      bestDiameter = diameter;
      wireLayers = layers;
      turnsPerLayer = rows;
    }
  }
  const wireRadius = THREE.MathUtils.clamp(bestDiameter * 0.47, 0.22, 2.6);

  const usableStart = boreX + Math.max(1.2, wireRadius + 0.5);
  const usableEnd = yokeX - Math.max(1, wireRadius + 0.4);
  const radialSpan = Math.max(0.4, usableEnd - usableStart);
  let rowSpacing = wireRadius * 2 * 1.08;
  if (turnsPerLayer > 1 && rowSpacing * (turnsPerLayer - 1) > radialSpan) {
    rowSpacing = radialSpan / (turnsPerLayer - 1);
  }
  const blockExtent = rowSpacing * (turnsPerLayer - 1);
  const firstRowX = usableStart + Math.max(0, (radialSpan - blockExtent) / 2);

  const stackHalf = spec.stackLength / 2;
  const strandGeometries: THREE.BufferGeometry[] = [];
  let strandCount = 0;
  let axialOverhang = 0;
  for (let row = 0; row < turnsPerLayer && strandCount < strandTarget; row += 1) {
    const x = firstRowX + row * rowSpacing;
    for (let layer = 0; layer < wireLayers && strandCount < strandTarget; layer += 1) {
      const idealHalfWidth = flankHalfWidthAt(x) + flankGap + wireRadius + layer * wireRadius * 2.08;
      const maxHalfWidth = slotHalfAt(x) - slotGap - wireRadius;
      const halfWidth = Math.max(flankHalfWidthAt(x) + 0.2, Math.min(idealHalfWidth, maxHalfWidth));
      // Outer layers arc over inner ones so end turns nest without touching.
      const endReach = wireRadius * 2.2 + layer * wireRadius * 2.1;
      const cornerRadius = Math.min(endReach, Math.max(wireRadius * 1.2, halfWidth * 0.86));
      const halfStraight = stackHalf + Math.max(0, endReach - cornerRadius);
      axialOverhang = Math.max(axialOverhang, halfStraight + cornerRadius + wireRadius - stackHalf);
      const curve = new RacetrackCurve(x, halfWidth, halfStraight, cornerRadius);
      const tubularSegments = Math.round(THREE.MathUtils.clamp(curve.perimeter / 2.6, 40, 128));
      strandGeometries.push(new THREE.TubeGeometry(curve, tubularSegments, wireRadius, 8, true));
      strandCount += 1;
    }
  }
  const geometry = mergeGeometries(strandGeometries, false) ?? new THREE.BufferGeometry();
  strandGeometries.forEach((strand) => strand.dispose());

  // Slot liner: a thin insulation strip hugging each tooth flank, part of the
  // coil assembly so it slides off with the winding in the exploded view.
  const linerStart = Math.max(boreX + 0.7, usableStart - wireRadius - 0.7);
  const linerEnd = Math.min(yokeX - 0.5, Math.max(linerStart + 1, usableEnd + wireRadius + 0.7));
  const linerThickness = 0.26;
  const linerShape = (side: 1 | -1): THREE.Shape => {
    const inner = (x: number) => side * (flankHalfWidthAt(x) + 0.05);
    const outer = (x: number) => side * (flankHalfWidthAt(x) + 0.05 + linerThickness);
    const shape = new THREE.Shape();
    shape.moveTo(linerStart, inner(linerStart));
    shape.lineTo(linerEnd, inner(linerEnd));
    shape.lineTo(linerEnd, outer(linerEnd));
    shape.lineTo(linerStart, outer(linerStart));
    shape.closePath();
    return shape;
  };
  const linerDepth = spec.stackLength + 2.6;
  const linerGeometry = new THREE.ExtrudeGeometry([linerShape(1), linerShape(-1)], {
    depth: linerDepth,
    bevelEnabled: false,
  });
  linerGeometry.translate(0, 0, -linerDepth / 2);

  return {
    geometry,
    strandCount,
    turnsRepresented: turns,
    wireLayers,
    turnsPerLayer,
    wireRadius,
    axialOverhang,
    bundleCenterRadius: firstRowX + blockExtent / 2,
    linerGeometry,
  };
}

class HarnessArcCurve extends THREE.Curve<THREE.Vector3> {
  constructor(
    private readonly radius: number,
    private readonly startAngle: number,
    private readonly endAngle: number,
    private readonly z: number,
  ) {
    super();
  }

  override getPoint(t: number, optionalTarget = new THREE.Vector3()): THREE.Vector3 {
    const angle = this.startAngle + (this.endAngle - this.startAngle) * t;
    return optionalTarget.set(Math.cos(angle) * this.radius, Math.sin(angle) * this.radius, this.z);
  }
}

function polar(radius: number, angle: number, z: number): THREE.Vector3 {
  return new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius, z);
}

function tubeAlong(curve: THREE.Curve<THREE.Vector3>, length: number, radius: number): THREE.TubeGeometry {
  const segments = Math.round(THREE.MathUtils.clamp(length / 2.4, 6, 96));
  return new THREE.TubeGeometry(curve, segments, radius, 8, false);
}

function circularMean(angles: number[]): number {
  let x = 0;
  let y = 0;
  angles.forEach((angle) => {
    x += Math.cos(angle);
    y += Math.sin(angle);
  });
  return Math.atan2(y, x);
}

export type HarnessPhase = 'A' | 'B' | 'C';

export interface WindingHarnessSpec {
  slotCount: number;
  slotPitchRad: number;
  phaseOfSlot: (slot: number) => HarnessPhase;
  /** Radial position of the rear jumper ring, in millimetres. */
  bundleCenterRadius: number;
  stackHalf: number;
  axialOverhang: number;
  wireRadius: number;
  yokeInnerRadius: number;
  outerRadius: number;
}

export interface WindingHarnessModel {
  phaseGeometries: Record<HarnessPhase, THREE.BufferGeometry | null>;
  /** Star links plus the wye junction block. */
  neutralGeometry: THREE.BufferGeometry | null;
  /** Terminal block on the rear yoke face where the drive leads land. */
  terminalGeometry: THREE.BufferGeometry;
  leadRadius: number;
}

/**
 * Rear-side winding interconnects for a concentrated three-phase winding:
 * a drop stub from every coil, series jumper arcs joining the coils of each
 * phase, one lead per phase routed to a terminal block on the yoke, and a
 * wye star point tying the three phase tails together inside the motor.
 * Geometries are in world frame; caller owns disposal.
 */
export function buildWindingHarness(spec: WindingHarnessSpec): WindingHarnessModel {
  const radius = spec.bundleCenterRadius;
  const leadRadius = Math.max(spec.wireRadius * 1.05, 0.8);
  const zStubTop = -(spec.stackHalf + spec.axialOverhang * 0.55);
  const zBase = -(spec.stackHalf + spec.axialOverhang + 2.2);
  const zStep = leadRadius * 2.7;

  const slotsByPhase: Record<HarnessPhase, number[]> = { A: [], B: [], C: [] };
  for (let slot = 0; slot < spec.slotCount; slot += 1) {
    slotsByPhase[spec.phaseOfSlot(slot)].push(slot);
  }
  const orderedPhases = (['A', 'B', 'C'] as const)
    .filter((phase) => slotsByPhase[phase].length > 0)
    .sort((a, b) => slotsByPhase[a][0] - slotsByPhase[b][0]);

  const terminalRadius = (spec.yokeInnerRadius + spec.outerRadius) / 2;
  const terminalAngle = circularMean(orderedPhases.map((phase) => slotsByPhase[phase][0] * spec.slotPitchRad));
  const zTerminal = -(spec.stackHalf + 4.2);

  const phaseGeometries: Record<HarnessPhase, THREE.BufferGeometry | null> = { A: null, B: null, C: null };
  const tailPoints: Partial<Record<HarnessPhase, THREE.Vector3>> = {};

  orderedPhases.forEach((phase, phaseIndex) => {
    const slots = slotsByPhase[phase];
    const zPlane = zBase - phaseIndex * zStep;
    const parts: THREE.BufferGeometry[] = [];
    slots.forEach((slot) => {
      const angle = slot * spec.slotPitchRad;
      parts.push(tubeAlong(
        new THREE.LineCurve3(polar(radius, angle, zStubTop), polar(radius, angle, zPlane)),
        Math.abs(zPlane - zStubTop),
        leadRadius,
      ));
    });
    for (let index = 0; index < slots.length - 1; index += 1) {
      const from = slots[index] * spec.slotPitchRad;
      const to = slots[index + 1] * spec.slotPitchRad;
      parts.push(tubeAlong(new HarnessArcCurve(radius, from, to, zPlane), Math.abs(to - from) * radius, leadRadius));
    }
    const leadAngle = slots[0] * spec.slotPitchRad;
    const landAngle = terminalAngle + (phaseIndex - (orderedPhases.length - 1) / 2) * 0.1;
    const lead = new THREE.QuadraticBezierCurve3(
      polar(radius, leadAngle, zPlane),
      polar((radius + terminalRadius) / 2, (leadAngle + landAngle) / 2, zPlane),
      polar(terminalRadius, landAngle, zTerminal),
    );
    parts.push(tubeAlong(lead, lead.getLength(), leadRadius));
    phaseGeometries[phase] = mergeGeometries(parts, false) ?? null;
    parts.forEach((part) => part.dispose());
    tailPoints[phase] = polar(radius, slots[slots.length - 1] * spec.slotPitchRad, zPlane);
  });

  let neutralGeometry: THREE.BufferGeometry | null = null;
  const tails = orderedPhases
    .map((phase) => tailPoints[phase])
    .filter((point): point is THREE.Vector3 => Boolean(point));
  if (tails.length >= 2) {
    const starAngle = circularMean(tails.map((point) => Math.atan2(point.y, point.x)));
    const zStar = zBase - (orderedPhases.length - 1) * zStep - zStep * 1.2;
    const star = polar(radius, starAngle, zStar);
    const parts: THREE.BufferGeometry[] = [];
    tails.forEach((tail) => {
      const control = new THREE.Vector3(
        (tail.x + star.x) / 2,
        (tail.y + star.y) / 2,
        (tail.z + star.z) / 2 - 1.2,
      );
      const link = new THREE.QuadraticBezierCurve3(tail, control, star);
      parts.push(tubeAlong(link, link.getLength(), leadRadius * 0.9));
    });
    const junction = new THREE.BoxGeometry(7, 4.6, 4.6);
    junction.rotateZ(starAngle);
    junction.translate(star.x, star.y, star.z);
    parts.push(junction);
    neutralGeometry = mergeGeometries(parts, false) ?? null;
    parts.forEach((part) => part.dispose());
  }

  const terminalGeometry = new THREE.BoxGeometry(13, 7, 5.2);
  terminalGeometry.rotateZ(terminalAngle + Math.PI / 2);
  const terminalCenter = polar(terminalRadius, terminalAngle, zTerminal - 0.4);
  terminalGeometry.translate(terminalCenter.x, terminalCenter.y, terminalCenter.z);

  return { phaseGeometries, neutralGeometry, terminalGeometry, leadRadius };
}
