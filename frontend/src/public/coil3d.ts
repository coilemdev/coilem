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
  /**
   * Optional hand-wound look for close-up hero renders. Leave unset for the
   * default schematic bundle, which is unchanged by these options.
   */
  handWound?: {
    /** Wire loops to draw, independent of the electrical turn count. */
    strands: number;
    /** 0 keeps the tight schematic corners; 1 makes each end turn a full half-circle. */
    endTurnRoundness: number;
    /** Strand placement scatter, as a fraction of the wire radius. */
    irregularity: number;
  };
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
  /**
   * Where the wire enters and leaves, in the tooth local frame: on the rear end
   * turn of the first strand (innermost layer, nearest the bore-side end of the
   * builder's radial range) and of the last (outermost layer, far end). Each
   * sits on its own side of the tooth, so a coil has two distinct leads.
   */
  startLead: THREE.Vector3;
  finishLead: THREE.Vector3;
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
  const handWound = spec.handWound;
  const strandTarget = handWound
    ? Math.max(1, Math.round(handWound.strands))
    : Math.min(turns, MAX_RENDERED_STRANDS);
  // Deterministic scatter, so every tooth shares one geometry and renders match.
  const scatter = (row: number, layer: number, salt: number) => {
    const value = Math.sin(row * 12.9898 + layer * 78.233 + salt * 37.719) * 43758.5453;
    return (value - Math.floor(value)) * 2 - 1;
  };
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
  // A point on a strand's rear end turn, on the given side of the tooth.
  const rearEndTurnPoint = (x: number, halfWidth: number, halfStraight: number, cornerRadius: number, side: 1 | -1) => (
    new THREE.Vector3(x, side * Math.max(0, halfWidth - cornerRadius) * 0.6, -(halfStraight + cornerRadius))
  );
  let startLead = new THREE.Vector3();
  let finishLead = new THREE.Vector3();
  for (let row = 0; row < turnsPerLayer && strandCount < strandTarget; row += 1) {
    const rowX = firstRowX + row * rowSpacing;
    for (let layer = 0; layer < wireLayers && strandCount < strandTarget; layer += 1) {
      // Hand-wound: each layer settles into the grooves of the one below, and
      // no two turns sit exactly where a machine would put them.
      const x = handWound
        ? rowX + (layer % 2 === 0 ? -0.25 : 0.25) * rowSpacing
          + scatter(row, layer, 1) * handWound.irregularity * wireRadius
        : rowX;
      const layerPitch = handWound ? 1.82 : 2.08;
      const idealHalfWidth = flankHalfWidthAt(x) + flankGap + wireRadius + layer * wireRadius * layerPitch
        + (handWound ? scatter(row, layer, 2) * handWound.irregularity * wireRadius * 0.5 : 0);
      const maxHalfWidth = slotHalfAt(x) - slotGap - wireRadius;
      const halfWidth = Math.max(flankHalfWidthAt(x) + 0.2, Math.min(idealHalfWidth, maxHalfWidth));
      // Outer layers arc over inner ones so end turns nest without touching.
      const endReach = wireRadius * 2.2 + layer * wireRadius * 2.1;
      let cornerRadius = Math.min(endReach, Math.max(wireRadius * 1.2, halfWidth * 0.86));
      let halfStraight = stackHalf + Math.max(0, endReach - cornerRadius);
      if (handWound) {
        // Wire bends in a sweep, not a crease: round the end turn towards a
        // half-circle and let outer layers reach further past the stack.
        cornerRadius = Math.max(
          cornerRadius,
          halfWidth * THREE.MathUtils.clamp(handWound.endTurnRoundness, 0, 0.98),
        );
        halfStraight = stackHalf + wireRadius * 1.2 + layer * wireRadius * 1.9
          + Math.abs(scatter(row, layer, 3)) * handWound.irregularity * wireRadius;
      }
      axialOverhang = Math.max(axialOverhang, halfStraight + cornerRadius + wireRadius - stackHalf);
      const curve = new RacetrackCurve(x, halfWidth, halfStraight, cornerRadius);
      if (strandCount === 0) startLead = rearEndTurnPoint(x, halfWidth, halfStraight, cornerRadius, -1);
      finishLead = rearEndTurnPoint(x, halfWidth, halfStraight, cornerRadius, 1);
      const tubularSegments = Math.round(THREE.MathUtils.clamp(curve.perimeter / 2.6, 40, handWound ? 72 : 128));
      strandGeometries.push(new THREE.TubeGeometry(curve, tubularSegments, wireRadius, handWound ? 6 : 8, true));
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
    startLead,
    finishLead,
  };
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
  /** Angle of tooth 0; tooth k sits k slot pitches further on. Defaults to 0. */
  toothAngleOffsetRad?: number;
  /** The phase of the coil on this tooth, or null for a tooth without a coil. */
  phaseOfSlot: (slot: number) => HarnessPhase | null;
  /** Radius the crossovers run at behind the stack, in millimetres. */
  bundleCenterRadius: number;
  /** Where each coil's wire enters and leaves, in the tooth local frame (``ConcentratedCoilModel``). */
  coilLeads: { start: THREE.Vector3; finish: THREE.Vector3 };
  stackHalf: number;
  axialOverhang: number;
  wireRadius: number;
  /** The terminal block lands midway between these two radii, on the yoke. */
  yokeInnerRadius: number;
  outerRadius: number;
  /** Size of the star junction and terminal block, and their set-back; 1 for a full-size machine. */
  blockScale?: number;
}

export interface WindingHarnessModel {
  phaseGeometries: Record<HarnessPhase, THREE.BufferGeometry | null>;
  /** Star links plus the wye junction block. */
  neutralGeometry: THREE.BufferGeometry | null;
  /** Terminal block on the rear yoke face where the drive leads land. */
  terminalGeometry: THREE.BufferGeometry;
  /** Where each phase's drive lead lands on the terminal block. */
  leadLandings: Partial<Record<HarnessPhase, THREE.Vector3>>;
  leadRadius: number;
}

const Z_AXIS = new THREE.Vector3(0, 0, 1);

/**
 * Rear-side wiring of a concentrated three-phase winding, as it is wound: one
 * continuous wire per phase. Its drive lead enters the first coil at its start;
 * each coil's finish crosses to the next coil's start, a short hop just behind
 * the end turns between neighbouring teeth and a longer run in the phase's own
 * plane further back; the last coil's finish runs to the wye star point. The
 * terminal block on the yoke takes the three leads. Geometries are in world
 * frame; caller owns disposal.
 */
export function buildWindingHarness(spec: WindingHarnessSpec): WindingHarnessModel {
  const radius = spec.bundleCenterRadius;
  const blockScale = spec.blockScale ?? 1;
  const leadRadius = Math.max(spec.wireRadius * 1.05, 0.8 * blockScale);
  const endTurnZ = -(spec.stackHalf + spec.axialOverhang);
  const zHop = endTurnZ - leadRadius * 1.8;
  const zBase = endTurnZ - 2.2 * blockScale;
  const zStep = leadRadius * 2.7;
  const toothAngle = (tooth: number) => (spec.toothAngleOffsetRad ?? 0) + tooth * spec.slotPitchRad;
  const leadAt = (local: THREE.Vector3, tooth: number) => local.clone().applyAxisAngle(Z_AXIS, toothAngle(tooth));
  const atZ = (point: THREE.Vector3, z: number) => new THREE.Vector3(point.x, point.y, z);

  const slotsByPhase: Record<HarnessPhase, number[]> = { A: [], B: [], C: [] };
  for (let slot = 0; slot < spec.slotCount; slot += 1) {
    const phase = spec.phaseOfSlot(slot);
    if (phase) slotsByPhase[phase].push(slot);
  }
  const orderedPhases = (['A', 'B', 'C'] as const)
    .filter((phase) => slotsByPhase[phase].length > 0)
    .sort((a, b) => slotsByPhase[a][0] - slotsByPhase[b][0]);

  const terminalRadius = (spec.yokeInnerRadius + spec.outerRadius) / 2;
  const terminalAngle = circularMean(orderedPhases.map((phase) => toothAngle(slotsByPhase[phase][0])));
  const zTerminal = -(spec.stackHalf + 4.2 * blockScale);

  // A wire from one coil's finish to the next coil's start: back off the end
  // turn, round the machine at the crossover radius, and forward onto the start.
  const crossover = (finish: THREE.Vector3, start: THREE.Vector3, z: number): THREE.TubeGeometry => {
    const from = Math.atan2(finish.y, finish.x);
    let to = Math.atan2(start.y, start.x);
    while (to < from) to += Math.PI * 2;
    const sweep = to - from;
    const arcSteps = Math.max(2, Math.ceil(sweep / (Math.PI / 18)));
    const points = [finish, atZ(finish, z)];
    for (let step = 1; step < arcSteps; step += 1) points.push(polar(radius, from + (sweep * step) / arcSteps, z));
    points.push(atZ(start, z), start);
    const curve = new THREE.CatmullRomCurve3(points, false, 'centripetal');
    return tubeAlong(curve, curve.getLength(), leadRadius);
  };

  const phaseGeometries: Record<HarnessPhase, THREE.BufferGeometry | null> = { A: null, B: null, C: null };
  const leadLandings: Partial<Record<HarnessPhase, THREE.Vector3>> = {};
  const tailPoints: Partial<Record<HarnessPhase, THREE.Vector3>> = {};

  orderedPhases.forEach((phase, phaseIndex) => {
    const slots = slotsByPhase[phase];
    const zPlane = zBase - phaseIndex * zStep;
    const parts: THREE.BufferGeometry[] = [];
    for (let index = 0; index < slots.length - 1; index += 1) {
      const neighbours = slots[index + 1] - slots[index] === 1;
      parts.push(crossover(
        leadAt(spec.coilLeads.finish, slots[index]),
        leadAt(spec.coilLeads.start, slots[index + 1]),
        neighbours ? zHop : zPlane,
      ));
    }
    // The drive lead enters the first coil at its start.
    const firstStart = leadAt(spec.coilLeads.start, slots[0]);
    const landAngle = terminalAngle + (phaseIndex - (orderedPhases.length - 1) / 2) * 0.1;
    leadLandings[phase] = polar(terminalRadius, landAngle, zTerminal);
    const lead = new THREE.CatmullRomCurve3([
      firstStart,
      atZ(firstStart, zPlane),
      polar((radius + terminalRadius) / 2, (Math.atan2(firstStart.y, firstStart.x) + landAngle) / 2, zPlane),
      polar(terminalRadius, landAngle, zTerminal),
    ], false, 'centripetal');
    parts.push(tubeAlong(lead, lead.getLength(), leadRadius));
    // The last coil's finish leaves for the star point.
    const lastFinish = leadAt(spec.coilLeads.finish, slots[slots.length - 1]);
    parts.push(tubeAlong(new THREE.LineCurve3(lastFinish, atZ(lastFinish, zPlane)), Math.abs(lastFinish.z - zPlane), leadRadius));
    phaseGeometries[phase] = mergeGeometries(parts, false) ?? null;
    parts.forEach((part) => part.dispose());
    tailPoints[phase] = atZ(lastFinish, zPlane);
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
        (tail.z + star.z) / 2 - 1.2 * blockScale,
      );
      const link = new THREE.QuadraticBezierCurve3(tail, control, star);
      parts.push(tubeAlong(link, link.getLength(), leadRadius * 0.9));
    });
    const junction = new THREE.BoxGeometry(7 * blockScale, 4.6 * blockScale, 4.6 * blockScale);
    junction.rotateZ(starAngle);
    junction.translate(star.x, star.y, star.z);
    parts.push(junction);
    neutralGeometry = mergeGeometries(parts, false) ?? null;
    parts.forEach((part) => part.dispose());
  }

  const terminalGeometry = new THREE.BoxGeometry(13 * blockScale, 7 * blockScale, 5.2 * blockScale);
  terminalGeometry.rotateZ(terminalAngle + Math.PI / 2);
  const terminalCenter = polar(terminalRadius, terminalAngle, zTerminal - 0.4 * blockScale);
  terminalGeometry.translate(terminalCenter.x, terminalCenter.y, terminalCenter.z);

  return { phaseGeometries, neutralGeometry, terminalGeometry, leadLandings, leadRadius };
}

export interface DistributedCoilSpec {
  /** Centre angles of the two slots the coil's sides sit in, in radians. */
  slotInAngle: number;
  slotOutAngle: number;
  /** Radial band each side fills in its slot, bore side first, in millimetres. */
  inBand: [number, number];
  outBand: [number, number];
  /** Half the angular width the bundle may take in a slot, in radians. */
  slotHalfAngle: number;
  /** Half the lamination stack length, in millimetres. */
  stackHalf: number;
  /** +1 when the yoke is outside the slots (inner rotor), -1 when it is inside them. */
  yokeSide: 1 | -1;
}

const DISTRIBUTED_MAX_ROWS = 5;
const DISTRIBUTED_COLUMNS = 2;

/**
 * One wire loop of a distributed coil: straight through one slot, over the end
 * of the stack to the other slot, back through it, and home over the far end.
 * The end turn is a diamond: it leaves along the axis, runs round at one radial
 * level to its knuckle, steps a level towards the yoke there and comes down on
 * the far side. Coils one slot apart then pass over and under each other, as a
 * real lap winding's end turns do, where plain arches would cut through.
 */
class DistributedCoilCurve extends THREE.Curve<THREE.Vector3> {
  private readonly sideLength: number;
  private readonly turnLength: number;

  constructor(
    private readonly inAngle: number,
    private readonly outAngle: number,
    private readonly inRadius: number,
    private readonly outRadius: number,
    private readonly stackHalf: number,
    private readonly rise: number,
    private readonly step: number,
  ) {
    super();
    const arc = Math.abs(outAngle - inAngle) * (inRadius + outRadius) / 2;
    this.sideLength = stackHalf * 2;
    this.turnLength = Math.hypot(arc, rise * 2) + Math.abs(step);
  }

  private endTurn(t: number, end: 1 | -1, target: THREE.Vector3): THREE.Vector3 {
    // Front goes in → out, rear comes back out → in; both leave and arrive along the axis.
    const along = end === 1 ? t : 1 - t;
    const ease = 0.5 - 0.5 * Math.cos(Math.PI * along);
    const angle = this.inAngle + (this.outAngle - this.inAngle) * ease;
    const knuckle = THREE.MathUtils.smoothstep(along, 0.38, 0.62);
    const settle = 1 - THREE.MathUtils.smoothstep(along, 0.82, 1);
    const radius = this.inRadius + (this.outRadius - this.inRadius) * knuckle + this.step * knuckle * settle;
    // A flat-topped arch: up off the stack quickly, then level round to the far slot.
    const z = end * (this.stackHalf + this.rise * Math.sin(Math.PI * along) ** 0.55);
    return target.set(Math.cos(angle) * radius, Math.sin(angle) * radius, z);
  }

  getPoint(t: number, target = new THREE.Vector3()): THREE.Vector3 {
    const total = (this.sideLength + this.turnLength) * 2;
    let distance = (((t % 1) + 1) % 1) * total;
    if (distance < this.sideLength) {
      return target.set(Math.cos(this.inAngle) * this.inRadius, Math.sin(this.inAngle) * this.inRadius, -this.stackHalf + distance);
    }
    distance -= this.sideLength;
    if (distance < this.turnLength) return this.endTurn(distance / this.turnLength, 1, target);
    distance -= this.turnLength;
    if (distance < this.sideLength) {
      return target.set(Math.cos(this.outAngle) * this.outRadius, Math.sin(this.outAngle) * this.outRadius, this.stackHalf - distance);
    }
    distance -= this.sideLength;
    return this.endTurn(distance / this.turnLength, -1, target);
  }
}

/**
 * Build one distributed coil as a small bundle of wire loops, in the stator's
 * own frame (no rotation to apply). Caller owns disposal.
 */
export function buildDistributedCoil(spec: DistributedCoilSpec): { geometry: THREE.BufferGeometry; strandCount: number; axialOverhang: number } {
  // The short way round from one slot to the other.
  let sweep = (spec.slotOutAngle - spec.slotInAngle) % (Math.PI * 2);
  if (sweep > Math.PI) sweep -= Math.PI * 2;
  if (sweep <= -Math.PI) sweep += Math.PI * 2;
  const bandDepth = Math.min(Math.abs(spec.inBand[1] - spec.inBand[0]), Math.abs(spec.outBand[1] - spec.outBand[0]));
  const middleRadius = (spec.inBand[0] + spec.inBand[1] + spec.outBand[0] + spec.outBand[1]) / 4;
  const slotWidth = middleRadius * spec.slotHalfAngle * 2;
  // Wires sized to sit side by side across the slot, then stacked as deep as the band allows:
  // a tight bundle, as wound wire packs, in place of a few loose strands.
  const wireRadius = THREE.MathUtils.clamp(Math.min(slotWidth / (DISTRIBUTED_COLUMNS * 2), bandDepth / 2) * 0.9, 0.25, 2.6);
  const rows = THREE.MathUtils.clamp(Math.floor(bandDepth / (wireRadius * 2.05)), 1, DISTRIBUTED_MAX_ROWS);
  const pitch = wireRadius * 2.05;
  const arc = Math.abs(sweep) * middleRadius;
  // End turns held close to the stack, as a formed and laced winding sits: just enough
  // height for the bundle to turn and for the coils that cross it to pass.
  const lowest = wireRadius * 5;
  const rise = THREE.MathUtils.clamp(arc * 0.15, lowest, Math.max(lowest, middleRadius * 0.2));
  // Sides in different radial halves of their slots (two layers) already change level at the knuckle.
  const sameBand = Math.abs((spec.inBand[0] + spec.inBand[1]) - (spec.outBand[0] + spec.outBand[1])) < bandDepth * 0.5;
  const step = sameBand ? spec.yokeSide * (rows * pitch + wireRadius) : 0;
  const strands: THREE.BufferGeometry[] = [];
  const bandSign = (band: [number, number]) => Math.sign(band[1] - band[0]) || 1;
  for (let row = 0; row < rows; row += 1) {
    const stacked = (row - (rows - 1) / 2) * pitch;
    const inRadius = (spec.inBand[0] + spec.inBand[1]) / 2 + bandSign(spec.inBand) * stacked;
    const outRadius = (spec.outBand[0] + spec.outBand[1]) / 2 + bandSign(spec.outBand) * stacked;
    for (let column = 0; column < DISTRIBUTED_COLUMNS; column += 1) {
      const offset = ((column - (DISTRIBUTED_COLUMNS - 1) / 2) * pitch) / middleRadius;
      const curve = new DistributedCoilCurve(
        spec.slotInAngle + offset,
        spec.slotInAngle + sweep + offset,
        inRadius,
        outRadius,
        spec.stackHalf,
        // Outer rows reach a little further, so the bundle keeps its shape round the end.
        rise + row * wireRadius * 1.1,
        step,
      );
      strands.push(new THREE.TubeGeometry(curve, 72, wireRadius, 6, true));
    }
  }
  const geometry = mergeGeometries(strands, false) ?? new THREE.BufferGeometry();
  strands.forEach((strand) => strand.dispose());
  return { geometry, strandCount: strands.length, axialOverhang: rise + rows * wireRadius * 1.1 + wireRadius };
}
