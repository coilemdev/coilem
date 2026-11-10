/**
 * How the Solve canvas was left, so coming back from Design or Results shows
 * the same thing. The Solve stage is unmounted on the other steps, so this
 * lives outside it (as designViewMemory does for the Design canvas).
 *
 * `stage` belongs to one mesh and result: a new mesh or a new solve opens on
 * its own default tab. `field` holds the field view's layer choices, which are
 * the user's preferences and carry over from one result to the next.
 */
export const solveViewMemory = {
  stage: {
    result: undefined as unknown,
    mesh: undefined as unknown,
    solveView: 'geometry',
    meshDisplayMode: 'geometry',
    showMeshEdges: true,
  },
  field: {
    showHeatmap: true,
    showMesh: false,
    showFieldLines: true,
    showMagnets: true,
    showAirgap: false,
    showPoleLabels: false,
    fieldLineDensity: 'medium',
    playbackRpm: null as number | null,
  },
};
