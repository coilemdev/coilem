/**
 * Where the Design canvas was left, so coming back from Solve or Results
 * returns to the same view instead of replaying the 3D-to-2D intro.
 *
 * The intro belongs to opening a motor: loading an example or a design file,
 * or starting a design, calls `resetDesignViewMemory` so it plays once more.
 * The Design canvas is unmounted on the other steps, so this lives outside it.
 */
export const designViewMemory = {
  introPlayed: false,
  view: '2d',
  layer: 'none',
  overlays: { dimensions: false, slots: false, teeth: false, windings: false },
};

export function resetDesignViewMemory(): void {
  designViewMemory.introPlayed = false;
  designViewMemory.view = '2d';
  designViewMemory.layer = 'none';
  designViewMemory.overlays = { dimensions: false, slots: false, teeth: false, windings: false };
}
