/** Step-after paths, split by conducting state without shifting transitions. */
export function currentStepSegments(
  angles: number[],
  values: number[],
  x: (angle: number) => number,
  y: (value: number) => number,
  cycleEndX?: number,
): Array<{ conducting: boolean; path: string }> {
  const segments: Array<{ conducting: boolean; path: string }> = [];
  let current: { conducting: boolean; path: string } | undefined;
  for (let index = 0; index < values.length; index += 1) {
    const conducting = Math.abs(values[index]) > 1e-9;
    const px = x(angles[index]).toFixed(2);
    const py = y(values[index]).toFixed(2);
    if (!current) {
      current = { conducting, path: `M ${px} ${py}` };
    } else if (current.conducting !== conducting) {
      current.path += ` H ${px}`;
      segments.push(current);
      current = {
        conducting,
        path: `M ${px} ${y(values[index - 1]).toFixed(2)} V ${py}`,
      };
    } else {
      current.path += ` H ${px} V ${py}`;
    }
  }
  if (current) {
    if (cycleEndX !== undefined) current.path += ` H ${cycleEndX.toFixed(2)}`;
    segments.push(current);
  }
  return segments;
}
