/**
 * Geometry for the Layout view's parallel-paths wiring: each phase's branches as
 * series chains of coils between the phase terminal and neutral, in px.
 *
 * A chain that fits the width is one row, as it always was. A longer one wraps
 * like a snake (boustrophedon): row 1 runs left to right, row 2 right to left, and
 * so on, each row starting under the coil the row before ended on, with a U-turn
 * jumper at the row end. A lone branch ends wherever its last row does, so its
 * neutral can be on the left. With several, the neutral bus on the right joins
 * them, so a branch whose last row ends on the left returns under that row to the
 * bus rather than crossing the terminal bus on the left.
 */

export const COIL_W = 52;
export const COIL_H = 20;
export const JUMPER = 18;
/** Row pitch between branches, and between the rows of one wrapped branch. */
export const BRANCH_ROW = 32;
export const TURN_ROW = 28;
/** Room for the "path n" gutter, so the label cannot sit on the terminal bus. */
export const LABEL_GUTTER = 46;
/** Lead length either side of the chain, long enough to carry a current label. */
export const LEAD = 34;
/** Band above the rows for the incoming current and the neutral marker. */
export const TOP_BAND = 15;
const RIGHT_MARGIN = 16;
/** How far a U-turn reaches past its row end, and the radius of its corners. */
export const TURN_REACH = 10;
const TURN_RADIUS = 6;
/** How far below its last row a branch returns to the neutral bus, clear of the coils. */
export const RETURN_DROP = 16;
/** Fewest coils a row holds; narrower than that, the wiring scrolls sideways. */
export const MIN_COILS_PER_ROW = 2;
/** The phase tag (22 px) and the row gap (8 px) beside each wiring, in styles.css. */
export const PHASE_TAG_SPACE = 30;

const PITCH = COIL_W + JUMPER;

/**
 * Coils split into `pathCount` branches, evenly, in slot order.
 *
 * The solver models parallel paths only as a divisor on branch current — it has no
 * branch topology — so this grouping is the conventional reading rather than
 * something read back from the model, and the view says so. When the count does not
 * divide the coils the remainder is left over, which is the case the caller warns
 * about.
 */
export function branchesForPhase<T extends { slot_in: number }>(coils: T[], pathCount: number): T[][] {
  const ordered = [...coils].sort((a, b) => a.slot_in - b.slot_in);
  const paths = Math.max(1, Math.floor(pathCount));
  if (paths <= 1 || ordered.length === 0) return [ordered];
  const per = Math.floor(ordered.length / paths);
  if (per < 1) return ordered.map((coil) => [coil]);
  const groups: T[][] = [];
  for (let index = 0; index < paths; index += 1) {
    groups.push(ordered.slice(index * per, (index + 1) * per));
  }
  const remainder = ordered.slice(paths * per);
  if (remainder.length) groups.push(remainder);
  return groups;
}

/** Width of a wiring whose longest row holds `coils` coils. */
export function wiringWidth(coils: number): number {
  const chain = coils * COIL_W + Math.max(0, coils - 1) * JUMPER;
  return LABEL_GUTTER + LEAD + chain + LEAD + RIGHT_MARGIN;
}

/** How many coils fit one row of a wiring `availableWidth` px wide; unmeasured, no limit. */
export function coilsPerRow(availableWidth: number | null): number {
  if (availableWidth === null || !Number.isFinite(availableWidth)) return Infinity;
  return Math.max(MIN_COILS_PER_ROW, Math.floor((availableWidth - wiringWidth(1)) / PITCH) + 1);
}

/**
 * A branch of `count` coils as the fewest rows of at most `perRow`, as even as
 * they go and longest first, so a wrapped branch does not trail one coil on its
 * own line.
 */
export function rowLengths(count: number, perRow: number): number[] {
  if (count <= 0) return [];
  const rows = Math.max(1, Math.ceil(count / Math.max(1, perRow)));
  const base = Math.floor(count / rows);
  const extra = count % rows;
  return Array.from({ length: rows }, (_, row) => base + (row < extra ? 1 : 0));
}

export interface WiringCoil {
  /** Left edge and centre line of the coil's box. */
  x: number;
  y: number;
  row: number;
  /** +1 where the row runs left to right, -1 right to left. */
  direction: 1 | -1;
}

export interface WiringBranch {
  /** In series order, terminal end first. */
  coils: WiringCoil[];
  /** The join from each coil to the next: a jumper along a row, a U-turn at its end. */
  joins: string[];
  leadIn: string;
  leadOut: string;
  rows: number;
  startY: number;
  endY: number;
  /** Where the branch meets neutral: a lone branch can end on the left. */
  neutralSide: 'left' | 'right';
  /** True when the branch ends on the left and returns under its last row to the bus. */
  returns: boolean;
}

export interface WiringLabel {
  x: number;
  y: number;
  anchor: 'start' | 'middle' | 'end';
}

export interface PhaseWiringLayout {
  width: number;
  height: number;
  terminalX: number;
  chainX: number;
  neutralX: number;
  branches: WiringBranch[];
  /** The junctions every branch shares; none for a lone branch. */
  terminalBus: { x: number; y1: number; y2: number } | null;
  neutralBus: { x: number; y1: number; y2: number } | null;
  totalCurrentLabel: WiringLabel;
  neutralLabel: WiringLabel;
  /** True when any branch wraps onto more than one row. */
  wrapped: boolean;
}

/** A U-turn from a row end at `x` down to the next row, bulging to the side the row ran. */
function uTurn(x: number, y1: number, y2: number, side: 1 | -1): string {
  const r = TURN_RADIUS;
  const sweep = side > 0 ? 1 : 0;
  return [
    `M ${x} ${y1}`,
    `H ${x + side * (TURN_REACH - r)}`,
    `A ${r} ${r} 0 0 ${sweep} ${x + side * TURN_REACH} ${y1 + r}`,
    `V ${y2 - r}`,
    `A ${r} ${r} 0 0 ${sweep} ${x + side * (TURN_REACH - r)} ${y2}`,
    `H ${x}`,
  ].join(' ');
}

/** From the left end of a branch's last row, down and back under it to the neutral bus. */
function returnLead(x: number, y1: number, y2: number, neutralX: number): string {
  return uTurn(x, y1, y2, -1).replace(/H \S+$/, `H ${neutralX}`);
}

/** Lay out one phase whose branches hold `branchLengths` coils, at most `perRow` to a row. */
export function layoutPhaseWiring(branchLengths: number[], perRow: number): PhaseWiringLayout {
  const capacity = Math.max(MIN_COILS_PER_ROW, perRow);
  const lengths = branchLengths.length ? branchLengths : [0];
  const shared = lengths.length > 1;
  const rowsOf = lengths.map((count) => rowLengths(count, capacity));
  const columns = Math.max(0, ...rowsOf.flat());
  const terminalX = LABEL_GUTTER;
  const chainX = terminalX + LEAD;
  const neutralX = chainX + columns * COIL_W + Math.max(0, columns - 1) * JUMPER + LEAD;

  let nextY = TOP_BAND + BRANCH_ROW / 2;
  const branches = rowsOf.map((rows): WiringBranch => {
    const startY = nextY;
    const coils: WiringCoil[] = [];
    // Each row starts in the column the last one ended in, so the U-turn drops straight down.
    let column = 0;
    rows.forEach((length, row) => {
      const direction = row % 2 === 0 ? 1 : -1;
      for (let index = 0; index < length; index += 1) {
        if (index > 0) column += direction;
        coils.push({ x: chainX + column * PITCH, y: startY + row * TURN_ROW, row, direction });
      }
    });
    const joins = coils.slice(1).map((next, index) => {
      const coil = coils[index];
      if (coil.row === next.row) {
        return coil.direction > 0
          ? `M ${coil.x + COIL_W} ${coil.y} H ${next.x}`
          : `M ${coil.x} ${coil.y} H ${next.x + COIL_W}`;
      }
      return uTurn(coil.direction > 0 ? coil.x + COIL_W : coil.x, coil.y, next.y, coil.direction);
    });
    const last = coils.length ? coils[coils.length - 1] : undefined;
    const endsLeft = Boolean(last && last.direction < 0);
    const returns = endsLeft && shared;
    const endY = !last ? startY : returns ? last.y + RETURN_DROP : last.y;
    let leadOut = `M ${chainX} ${endY} H ${neutralX}`;
    if (last && !endsLeft) leadOut = `M ${last.x + COIL_W} ${endY} H ${neutralX}`;
    else if (last && returns) leadOut = returnLead(last.x, last.y, endY, neutralX);
    else if (last) leadOut = `M ${last.x} ${endY} H ${terminalX}`;
    nextY = endY + BRANCH_ROW;
    return {
      coils,
      joins,
      leadIn: `M ${terminalX} ${startY} H ${chainX}`,
      leadOut,
      rows: Math.max(1, rows.length),
      startY,
      endY,
      neutralSide: endsLeft && !shared ? 'left' : 'right',
      returns,
    };
  });

  const first = branches[0];
  const lastBranch = branches[branches.length - 1];
  const wrapped = branches.some((branch) => branch.rows > 1);
  // N marks the neutral end. On one row it sits above it, as it always has; once
  // wrapped that spot falls between rows, so it goes beside the end instead: right
  // of the lead or the bus's top, or in the gutter when a lone branch ends on the left.
  let neutralLabel: WiringLabel = { x: neutralX, y: first.endY - 20, anchor: 'middle' };
  if (first.neutralSide === 'left') neutralLabel = { x: terminalX - 8, y: first.endY + 3.5, anchor: 'end' };
  else if (wrapped) neutralLabel = { x: neutralX + 5, y: first.endY + 3.5, anchor: 'start' };
  return {
    width: neutralX + RIGHT_MARGIN,
    height: lastBranch.endY + BRANCH_ROW / 2,
    terminalX,
    chainX,
    neutralX,
    branches,
    terminalBus: shared ? { x: terminalX, y1: first.startY, y2: lastBranch.startY } : null,
    neutralBus: shared ? { x: neutralX, y1: first.endY, y2: lastBranch.endY } : null,
    totalCurrentLabel: { x: terminalX, y: TOP_BAND - 4, anchor: 'middle' },
    neutralLabel,
    wrapped,
  };
}
