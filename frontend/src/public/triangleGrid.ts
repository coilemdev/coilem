/**
 * A uniform grid over triangles' bounding boxes, for finding the triangles
 * under a point or inside a rectangle without visiting the whole mesh: the
 * field arrows (fieldArrows.ts), the magnifier and the element probe use it.
 * Cells are sized for about two triangles each on average; a large triangle
 * is listed in every cell its box meets.
 */

/** A model-space rectangle, mm (y up). */
export interface GridRect {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export interface TriangleGrid {
  count: number;
  /** Each item's box, packed minX, minY, maxX, maxY. */
  boxes: Float64Array;
  minX: number;
  minY: number;
  cellSize: number;
  columns: number;
  rows: number;
  /** Items whose box meets cell c are cellItems[cellStart[c] .. cellStart[c + 1]). */
  cellStart: Int32Array;
  cellItems: Int32Array;
  /** The last rectangle query to list each item, so a query lists it once. */
  listedBy: Int32Array;
  queries: number;
}

/** Index `count` items by their boxes (packed minX, minY, maxX, maxY); null when there are none. */
export function buildTriangleGrid(boxes: Float64Array, count: number): TriangleGrid | null {
  if (count <= 0) return null;
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (let item = 0; item < count; item += 1) {
    minX = Math.min(minX, boxes[item * 4]);
    minY = Math.min(minY, boxes[item * 4 + 1]);
    maxX = Math.max(maxX, boxes[item * 4 + 2]);
    maxY = Math.max(maxY, boxes[item * 4 + 3]);
  }
  if (![minX, minY, maxX, maxY].every(Number.isFinite)) return null;
  const width = Math.max(maxX - minX, 1e-9);
  const height = Math.max(maxY - minY, 1e-9);
  const cellSize = Math.max(Math.sqrt((width * height) / count) * 1.4, 1e-6);
  const columns = Math.max(1, Math.ceil(width / cellSize));
  const rows = Math.max(1, Math.ceil(height / cellSize));
  const cellOf = (value: number, origin: number, limit: number) => (
    Math.min(limit - 1, Math.max(0, Math.floor((value - origin) / cellSize)))
  );
  const spans = new Int32Array(count * 4);
  const cellStart = new Int32Array(columns * rows + 1);
  for (let item = 0; item < count; item += 1) {
    const column0 = cellOf(boxes[item * 4], minX, columns);
    const row0 = cellOf(boxes[item * 4 + 1], minY, rows);
    const column1 = cellOf(boxes[item * 4 + 2], minX, columns);
    const row1 = cellOf(boxes[item * 4 + 3], minY, rows);
    spans.set([column0, column1, row0, row1], item * 4);
    for (let row = row0; row <= row1; row += 1) {
      for (let column = column0; column <= column1; column += 1) cellStart[row * columns + column + 1] += 1;
    }
  }
  for (let cell = 0; cell < columns * rows; cell += 1) cellStart[cell + 1] += cellStart[cell];
  const cellItems = new Int32Array(cellStart[columns * rows]);
  const filled = cellStart.slice(0, columns * rows);
  for (let item = 0; item < count; item += 1) {
    const [column0, column1, row0, row1] = spans.subarray(item * 4, item * 4 + 4);
    for (let row = row0; row <= row1; row += 1) {
      for (let column = column0; column <= column1; column += 1) {
        const cell = row * columns + column;
        cellItems[filled[cell]] = item;
        filled[cell] += 1;
      }
    }
  }
  return {
    count,
    boxes,
    minX,
    minY,
    cellSize,
    columns,
    rows,
    cellStart,
    cellItems,
    listedBy: new Int32Array(count),
    queries: 0,
  };
}

/** The cell holding a point, or -1 outside the grid (its far edges fall in the last cell). */
export function triangleGridCell(grid: TriangleGrid, x: number, y: number): number {
  const column = Math.floor((x - grid.minX) / grid.cellSize);
  const row = Math.floor((y - grid.minY) / grid.cellSize);
  if (!(column >= 0 && row >= 0 && column <= grid.columns && row <= grid.rows)) return -1;
  return Math.min(grid.rows - 1, row) * grid.columns + Math.min(grid.columns - 1, column);
}

/** Every item whose box meets the rectangle, each once. */
export function triangleGridItemsInRect(grid: TriangleGrid, rect: GridRect): number[] {
  const items: number[] = [];
  const column0 = Math.max(0, Math.floor((rect.minX - grid.minX) / grid.cellSize));
  const row0 = Math.max(0, Math.floor((rect.minY - grid.minY) / grid.cellSize));
  const column1 = Math.min(grid.columns - 1, Math.floor((rect.maxX - grid.minX) / grid.cellSize));
  const row1 = Math.min(grid.rows - 1, Math.floor((rect.maxY - grid.minY) / grid.cellSize));
  if (column0 > column1 || row0 > row1) return items;
  grid.queries += 1;
  const query = grid.queries;
  const { boxes, listedBy } = grid;
  for (let row = row0; row <= row1; row += 1) {
    for (let column = column0; column <= column1; column += 1) {
      const cell = row * grid.columns + column;
      for (let entry = grid.cellStart[cell]; entry < grid.cellStart[cell + 1]; entry += 1) {
        const item = grid.cellItems[entry];
        if (listedBy[item] === query) continue;
        listedBy[item] = query;
        if (
          boxes[item * 4] <= rect.maxX && boxes[item * 4 + 2] >= rect.minX
          && boxes[item * 4 + 1] <= rect.maxY && boxes[item * 4 + 3] >= rect.minY
        ) items.push(item);
      }
    }
  }
  return items;
}
