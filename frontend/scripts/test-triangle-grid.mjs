import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The field view finds elements under the pointer and inside the magnifier
// through a grid over their bounding boxes (triangleGrid.ts), not by visiting
// every element: the magnifier redraws only what it shows.
const {
  buildTriangleGrid,
  triangleGridCell,
  triangleGridItemsInRect,
} = await importTypeScriptModule(new URL('../src/public/triangleGrid.ts', import.meta.url));

// A fixed scatter of small and large triangles' boxes over 100 × 60 mm.
let seed = 7;
const random = () => {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return seed / 2147483648;
};
const count = 2000;
const boxes = new Float64Array(count * 4);
for (let item = 0; item < count; item += 1) {
  const size = item % 50 === 0 ? 20 * random() : 1.5 * random();
  const x = -50 + 100 * random();
  const y = -30 + 60 * random();
  boxes.set([x, y, x + size, y + size * 0.7], item * 4);
}
const grid = buildTriangleGrid(boxes, count);
assert.ok(grid);
assert.equal(buildTriangleGrid(new Float64Array(0), 0), null);

// A rectangle lists exactly the boxes that meet it, each once.
const meets = (item, rect) => boxes[item * 4] <= rect.maxX && boxes[item * 4 + 2] >= rect.minX
  && boxes[item * 4 + 1] <= rect.maxY && boxes[item * 4 + 3] >= rect.minY;
for (const rect of [
  { minX: -5, minY: -5, maxX: 5, maxY: 5 },
  { minX: 30, minY: 10, maxX: 80, maxY: 60 },
  { minX: -200, minY: -200, maxX: 200, maxY: 200 },
  { minX: 120, minY: 0, maxX: 130, maxY: 1 },
  { minX: -10.3, minY: 2.2, maxX: -10.1, maxY: 2.4 },
]) {
  const listed = triangleGridItemsInRect(grid, rect);
  assert.equal(new Set(listed).size, listed.length, 'no item twice');
  const expected = Array.from({ length: count }, (_, item) => item).filter((item) => meets(item, rect));
  assert.deepEqual([...listed].sort((a, b) => a - b), expected, JSON.stringify(rect));
}

// A point's cell lists every box that holds the point; outside the grid there is none.
for (let trial = 0; trial < 200; trial += 1) {
  const x = -50 + 100 * random();
  const y = -30 + 60 * random();
  const cell = triangleGridCell(grid, x, y);
  assert.ok(cell >= 0);
  const inCell = new Set(grid.cellItems.slice(grid.cellStart[cell], grid.cellStart[cell + 1]));
  for (let item = 0; item < count; item += 1) {
    if (meets(item, { minX: x, minY: y, maxX: x, maxY: y })) assert.ok(inCell.has(item), `item ${item} at ${x}, ${y}`);
  }
}
assert.equal(triangleGridCell(grid, 500, 0), -1);
assert.equal(triangleGridCell(grid, 0, -500), -1);

console.log('triangle grid: rectangle and point lookups match a full scan');
