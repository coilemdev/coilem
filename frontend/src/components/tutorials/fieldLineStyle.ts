/**
 * Stroke styling buckets for field-line overlays, ordered weakest → strongest.
 *
 * Extracted out of motor-viewport/meshOverlayUtils.ts so the shared tutorial
 * tree owns it; meshOverlayUtils re-exports it for its existing consumers.
 */
export const FIELD_LINE_STRENGTH_PALETTE = [
  { stroke: 'rgba(219, 234, 254, 0.26)', widthScale: 0.72, opacity: 0.40 },
  { stroke: 'rgba(191, 219, 254, 0.34)', widthScale: 0.82, opacity: 0.48 },
  { stroke: 'rgba(147, 197, 253, 0.46)', widthScale: 0.92, opacity: 0.58 },
  { stroke: 'rgba(96, 165, 250, 0.58)', widthScale: 1.02, opacity: 0.68 },
  { stroke: 'rgba(59, 130, 246, 0.70)', widthScale: 1.10, opacity: 0.76 },
  { stroke: 'rgba(37, 99, 235, 0.82)', widthScale: 1.18, opacity: 0.84 },
];
