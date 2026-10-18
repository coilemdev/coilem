import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

// The field view fits the motor beside the flux legend: it moves left at full
// size first, and shrinks only when it already sits at the left edge. Each
// label is checked against the circle at that label's height.
const { motorFitWidthBesideLegend, FIELD_LEGEND_GAP_PX } = await importTypeScriptModule(
  new URL('../src/public/fieldLegendFit.ts', import.meta.url),
);

// The motor circle in a box of the given width, centred, full view height.
const circle = (boxWidth, height) => ({ cx: boxWidth / 2, cy: height / 2, r: Math.min(boxWidth, height) / 2 });
const clearance = (boxWidth, height, part) => {
  const { cx, cy, r } = circle(boxWidth, height);
  const dy = cy < part.top ? part.top - cy : cy > part.bottom ? cy - part.bottom : 0;
  return dy >= r ? Infinity : part.left - (cx + Math.sqrt(r * r - dy * dy));
};

// The Solve tab's legend as measured on a 413 × 398 view: px from the right edge
// and the label's top and bottom (heading, Fixed/Fit view, > 2.0 T, two ticks,
// three value labels, the bar).
const legendAt = (width) => [
  [145, 22, 30], [82, 31, 58], [73, 66, 80], [94, 110, 124], [94, 155, 169],
  [58, 84, 104], [58, 222, 242], [58, 360, 380], [24, 84, 380],
].map(([fromRight, top, bottom]) => ({ left: width - fromRight, top, bottom }));

// Wide views: the centred motor already clears every label, the circle's
// narrow top passing under the heading in the corner.
assert.equal(motorFitWidthBesideLegend(900, 442, legendAt(900)), null);
assert.equal(motorFitWidthBesideLegend(700, 442, legendAt(700)), null);

// Narrower views: the motor clears every label by the gap, as large as it can.
for (const [width, height] of [[600, 442], [560, 442], [413, 398], [340, 356], [300, 356]]) {
  const parts = legendAt(width);
  const box = motorFitWidthBesideLegend(width, height, parts);
  assert.ok(box !== null && box < width, `${width}px: the motor moves`);
  const tightest = Math.min(...parts.map((part) => clearance(box, height, part)));
  assert.ok(tightest >= FIELD_LEGEND_GAP_PX - 0.01, `${width}px: clear by ${tightest}`);
  assert.ok(Math.min(...parts.map((part) => clearance(box + 1, height, part))) < FIELD_LEGEND_GAP_PX, `${width}px: as wide as it can be`);
}

// At 560 px it only moves left: full height, no shrinking. At 413 px it also
// shrinks, but stays far larger than fitting beside the legend's widest label.
assert.equal(Math.min(motorFitWidthBesideLegend(560, 442, legendAt(560)), 442), 442);
assert.ok(motorFitWidthBesideLegend(413, 398, legendAt(413)) > 413 - 145 - FIELD_LEGEND_GAP_PX + 30);

// A label up in the corner costs less room than one beside the circle's middle.
const corner = motorFitWidthBesideLegend(413, 398, [{ left: 413 - 145, top: 22, bottom: 30 }]);
const middle = motorFitWidthBesideLegend(413, 398, [{ left: 413 - 145, top: 190, bottom: 210 }]);
assert.ok(corner > middle, `corner ${corner} > middle ${middle}`);

// A legend below the view (the Results page) or none at all moves nothing.
assert.equal(motorFitWidthBesideLegend(600, 400, [{ left: 0, top: 410, bottom: 430 }]), null);
assert.equal(motorFitWidthBesideLegend(600, 400, []), null);
assert.equal(motorFitWidthBesideLegend(0, 400, legendAt(0)), null);

console.log('field legend fit checks passed');
