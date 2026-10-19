import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The Layout view's parallel-paths wiring: a chain that fits stays one row; a
// longer one snakes (row 1 left to right, row 2 back), with U-turns at the row
// ends, the terminal at its start and neutral at its end.
const {
  BRANCH_ROW,
  COIL_H,
  COIL_W,
  JUMPER,
  LEAD,
  MIN_COILS_PER_ROW,
  RETURN_DROP,
  TOP_BAND,
  TURN_REACH,
  TURN_ROW,
  branchesForPhase,
  coilsPerRow,
  layoutPhaseWiring,
  rowLengths,
  wiringWidth,
} = await importTypeScriptModule(new URL('../src/public/windingWiring.ts', import.meta.url));

const coils = (count) => Array.from({ length: count }, (_, index) => ({ slot_in: (index * 5) % count, id: index }));
const numbers = (path) => [...path.matchAll(/-?\d+(?:\.\d+)?/g)].map(Number);
/** The points a wire passes through: its "M x y" start, then each H / V / A step's end. */
const walk = (path) => {
  const values = numbers(path);
  let [x, y] = values;
  const points = [[x, y]];
  for (const step of path.matchAll(/([HVA])\s*([^HVAM]*)/g)) {
    const args = numbers(step[2]);
    if (step[1] === 'H') x = args[0];
    else if (step[1] === 'V') y = args[0];
    else [x, y] = args.slice(-2);
    points.push([x, y]);
  }
  return points;
};
const ends = (path) => {
  const points = walk(path);
  return { start: points[0], end: points[points.length - 1] };
};
const near = (a, b, label) => assert.ok(Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9, `${label}: ${a} != ${b}`);

// Branches split evenly in slot order; the remainder is left over; 1 path is one chain.
assert.deepEqual(branchesForPhase(coils(12), 1).map((branch) => branch.length), [12]);
assert.deepEqual(branchesForPhase(coils(12), 2).map((branch) => branch.length), [6, 6]);
assert.deepEqual(branchesForPhase(coils(14), 4).map((branch) => branch.length), [3, 3, 3, 3, 2]);
assert.deepEqual(branchesForPhase(coils(3), 4).map((branch) => branch.length), [1, 1, 1]);
assert.deepEqual(branchesForPhase(coils(6), 2)[0].map((coil) => coil.slot_in), [0, 1, 2]);

// The fewest rows that fit, as even as they go, longest first.
assert.deepEqual(rowLengths(12, 7), [6, 6]);
assert.deepEqual(rowLengths(13, 7), [7, 6]);
assert.deepEqual(rowLengths(15, 7), [5, 5, 5]);
assert.deepEqual(rowLengths(4, Infinity), [4]);

// Width: as many coils as fit, never fewer than the minimum, no limit unmeasured.
assert.equal(coilsPerRow(null), Infinity);
for (const available of [300, 452, 500, 640, 777, 1150]) {
  const perRow = coilsPerRow(available);
  assert.ok(wiringWidth(perRow) <= available, `${available}px: ${perRow} coils fit`);
  assert.ok(wiringWidth(perRow + 1) > available, `${available}px: one more would not`);
}
assert.equal(coilsPerRow(100), MIN_COILS_PER_ROW);

/** Invariants every layout keeps, wrapped or not. */
function checkLayout(lengths, perRow, label) {
  const layout = layoutPhaseWiring(lengths, perRow);
  const all = layout.branches.flatMap((branch) => branch.coils);
  assert.equal(layout.branches.length, lengths.length, `${label}: one layout per branch`);
  layout.branches.forEach((branch, index) => {
    const name = `${label} branch ${index + 1}`;
    assert.equal(branch.coils.length, lengths[index], `${name}: every coil placed`);
    assert.ok(branch.coils.every((coil) => coil.x >= layout.chainX && coil.x + COIL_W <= layout.neutralX - LEAD), `${name}: coils between the leads`);
    // Row 1 left to right, row 2 back, and so on.
    branch.coils.forEach((coil) => assert.equal(coil.direction, coil.row % 2 === 0 ? 1 : -1, `${name}: rows alternate`));
    // The terminal lead reaches the first coil, the neutral lead leaves the last.
    if (branch.coils.length) {
      const first = branch.coils[0];
      const last = branch.coils[branch.coils.length - 1];
      near(ends(branch.leadIn).start, [layout.terminalX, branch.startY], `${name}: starts at the terminal`);
      near(ends(branch.leadIn).end, [first.x, first.y], `${name}: lead into the first coil`);
      const exit = last.direction > 0 ? last.x + COIL_W : last.x;
      near(ends(branch.leadOut).start, [exit, last.y], `${name}: lead out of the last coil`);
      near(ends(branch.leadOut).end, [branch.neutralSide === 'right' ? layout.neutralX : layout.terminalX, branch.endY], `${name}: ends at neutral`);
      assert.equal(branch.rows, Math.max(...branch.coils.map((coil) => coil.row)) + 1);
      assert.ok(branch.coils.filter((coil) => coil.row === 0).length <= Math.max(MIN_COILS_PER_ROW, perRow), `${name}: rows hold no more than fit`);
      if (branch.returns) {
        // Ends on the left with a bus to reach: down past its last row and back under it.
        assert.equal(last.direction, -1, `${name}: only a branch that ends on the left returns`);
        assert.equal(branch.endY, last.y + RETURN_DROP);
        assert.ok(branch.endY - COIL_H / 2 > last.y, `${name}: the return runs below the last row's coils`);
        assert.ok(walk(branch.leadOut).every(([x]) => x >= last.x - TURN_REACH && x <= layout.neutralX), `${name}: the return stays inside the leads`);
      } else if (branch.coils.length) {
        assert.equal(branch.endY, last.y);
      }
    }
    // Each join leaves one coil's exit edge and arrives at the next coil's entry edge.
    branch.joins.forEach((join, joinIndex) => {
      const from = branch.coils[joinIndex];
      const to = branch.coils[joinIndex + 1];
      near(ends(join).start, [from.direction > 0 ? from.x + COIL_W : from.x, from.y], `${name} join ${joinIndex + 1}: leaves its coil`);
      near(ends(join).end, [to.direction > 0 ? to.x : to.x + COIL_W, to.y], `${name} join ${joinIndex + 1}: reaches the next`);
      if (from.row !== to.row) {
        // A U-turn drops one row, straight under, and stays clear of both buses.
        assert.equal(to.row, from.row + 1, `${name}: U-turns go one row down`);
        assert.equal(to.x, from.x, `${name}: the next row starts under the last coil`);
        const points = walk(join);
        const reach = from.direction > 0 ? Math.max(...points.map(([x]) => x)) : Math.min(...points.map(([x]) => x));
        assert.equal(reach, from.direction > 0 ? from.x + COIL_W + TURN_REACH : from.x - TURN_REACH, `${name}: the U-turn bulges out past the row end`);
        assert.ok(points.every(([, y]) => y >= from.y && y <= to.y), `${name}: the U-turn stays between its rows`);
        assert.ok(reach > layout.terminalX + 12 && reach < layout.neutralX - 12, `${name}: U-turn clear of the buses (${reach})`);
      }
    });
    if (index > 0) {
      assert.ok(branch.startY - layout.branches[index - 1].endY >= BRANCH_ROW, `${name}: below the branch before`);
    }
  });
  // No two coils overlap.
  for (let i = 0; i < all.length; i += 1) {
    for (let j = i + 1; j < all.length; j += 1) {
      const apart = Math.abs(all[i].x - all[j].x) >= COIL_W + JUMPER || Math.abs(all[i].y - all[j].y) >= COIL_H + 8;
      assert.ok(apart, `${label}: coils ${i + 1} and ${j + 1} overlap`);
    }
  }
  // Everything inside the drawing, below the current label band.
  assert.ok(all.every((coil) => coil.y - COIL_H / 2 >= TOP_BAND && coil.y + COIL_H / 2 <= layout.height), `${label}: inside the drawing`);
  // With several branches the buses join them, and every branch reaches the neutral bus.
  if (lengths.length > 1) {
    assert.ok(layout.branches.every((branch) => branch.neutralSide === 'right'), `${label}: every branch ends at the neutral bus`);
    assert.ok(layout.branches.every((branch) => branch.returns === (branch.rows % 2 === 0)), `${label}: even-row branches return`);
    assert.deepEqual(layout.terminalBus, { x: layout.terminalX, y1: layout.branches[0].startY, y2: layout.branches.at(-1).startY });
    assert.deepEqual(layout.neutralBus, { x: layout.neutralX, y1: layout.branches[0].endY, y2: layout.branches.at(-1).endY });
  } else {
    assert.equal(layout.terminalBus, null);
    assert.equal(layout.neutralBus, null);
    assert.equal(layout.branches[0].returns, false, `${label}: a lone branch ends where its last row does`);
  }
  return layout;
}

// Short chains look as they always did: SPM 8p/12s, 2 paths (2 coils a branch).
for (const perRow of [Infinity, coilsPerRow(400), coilsPerRow(1180)]) {
  const layout = checkLayout([2, 2], perRow, '8p/12s, 2 paths');
  assert.equal(layout.wrapped, false);
  assert.equal(layout.width, 46 + LEAD + 2 * COIL_W + JUMPER + LEAD + 16);
  assert.equal(layout.height, TOP_BAND + 2 * BRANCH_ROW);
  assert.deepEqual(layout.branches.map((branch) => branch.coils.map((coil) => [coil.x, coil.y])), [
    [[80, 31], [150, 31]],
    [[80, 63], [150, 63]],
  ]);
  assert.deepEqual(layout.totalCurrentLabel, { x: 46, y: TOP_BAND - 4, anchor: 'middle' });
  assert.deepEqual(layout.neutralLabel, { x: layout.neutralX, y: TOP_BAND - 4, anchor: 'middle' });
}

// SPM 6p/36s, 1 path: 12 coils. Wide enough, one row; in a narrower panel, a snake.
const wide = checkLayout([12], coilsPerRow(1150), '6p/36s, 1 path, wide');
assert.equal(wide.wrapped, false);
assert.equal(wide.width, wiringWidth(12));

const available = 640;
const snake = checkLayout([12], coilsPerRow(available), '6p/36s, 1 path, 640px');
assert.equal(snake.wrapped, true);
assert.ok(snake.width <= available, 'the snake fits the panel');
assert.deepEqual(snake.branches[0].coils.map((coil) => coil.row), [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]);
const xs = snake.branches[0].coils.map((coil) => coil.x);
assert.deepEqual(xs.slice(0, 6), [...xs.slice(0, 6)].sort((a, b) => a - b), 'row 1 runs left to right');
assert.deepEqual(xs.slice(6), [...xs.slice(6)].sort((a, b) => b - a), 'row 2 runs right to left');
assert.equal(snake.branches[0].coils[1].y - snake.branches[0].coils[0].y, 0);
assert.equal(snake.branches[0].coils[6].y - snake.branches[0].coils[5].y, TURN_ROW);
assert.match(snake.branches[0].joins[5], / A /, 'the row end is a U-turn');
// One branch over two rows ends on the left: N goes in the gutter, under "path 1".
assert.equal(snake.branches[0].neutralSide, 'left');
assert.deepEqual(snake.neutralLabel, { x: 38, y: snake.branches[0].endY + 3.5, anchor: 'end' });

// 6p/36s, 2 paths (6 coils a branch): one row each when it fits, a snake each when not.
const twoWide = checkLayout([6, 6], coilsPerRow(800), '6p/36s, 2 paths, 800px');
assert.equal(twoWide.wrapped, false);
const twoNarrow = checkLayout([6, 6], coilsPerRow(420), '6p/36s, 2 paths, 420px');
assert.equal(twoNarrow.wrapped, true);
assert.ok(twoNarrow.width <= 420);
assert.deepEqual(twoNarrow.branches.map((branch) => branch.coils.filter((coil) => coil.row === 0).length), [3, 3], 'as many to a row as fit, evened out');
assert.deepEqual(twoNarrow.branches.map((branch) => [branch.rows, branch.returns]), [[2, true], [2, true]]);
assert.ok(twoNarrow.branches[1].startY - BRANCH_ROW >= twoNarrow.branches[0].endY, 'the next branch starts below the return');
// Wrapped, N sits beside the top of the neutral bus, inside the drawing.
assert.deepEqual(twoNarrow.neutralLabel, { x: twoNarrow.neutralX + 5, y: twoNarrow.branches[0].endY + 3.5, anchor: 'start' });
assert.ok(twoNarrow.neutralLabel.x + 6 <= twoNarrow.width, 'N fits the right margin');
// A lone branch ending on the right: N beside its lead's end.
const loneOdd = checkLayout([12], coilsPerRow(436 - 30), '6p/36s, 1 path, 436px');
assert.deepEqual(loneOdd.branches[0].coils.map((coil) => coil.row).join(''), '000011112222');
assert.deepEqual(loneOdd.neutralLabel, { x: loneOdd.neutralX + 5, y: loneOdd.branches[0].endY + 3.5, anchor: 'start' });
const threeRows = checkLayout([12, 12], coilsPerRow(420), '12-coil branches, 420px');
assert.deepEqual(threeRows.branches.map((branch) => [branch.rows, branch.returns]), [[3, false], [3, false]], 'odd rows end on the right, no return');

// The uneven case keeps its left-over branch, wrapped like the others.
const uneven = checkLayout([3, 3, 3, 3, 2], coilsPerRow(250), 'left over');
assert.deepEqual(uneven.branches.map((branch) => branch.rows), [2, 2, 2, 2, 1]);

// A sweep over sizes and widths keeps the invariants.
for (const lengths of [[1], [4], [7], [12], [13], [24], [4, 4], [6, 6], [8, 8], [12, 12], [3, 3, 3, 3, 2], [1, 1, 1], [6, 6, 6, 6]]) {
  for (const width of [null, 260, 330, 420, 520, 640, 760, 900, 1150]) {
    const layout = checkLayout(lengths, coilsPerRow(width), `${lengths.join('+')} at ${width ?? 'unmeasured'}px`);
    if (width !== null && width >= wiringWidth(MIN_COILS_PER_ROW)) assert.ok(layout.width <= width, `${lengths.join('+')} at ${width}px: fits`);
  }
}

// An empty phase still draws a terminal-to-neutral lead.
const empty = layoutPhaseWiring([0], Infinity);
assert.equal(empty.branches[0].coils.length, 0);
near(ends(empty.branches[0].leadOut).end, [empty.neutralX, empty.branches[0].endY], 'empty phase reaches neutral');

console.log('winding wiring checks passed');
