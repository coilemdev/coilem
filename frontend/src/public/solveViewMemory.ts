import type { FieldArrowDensity } from './fieldArrows';

export type FieldView = 'resultant' | 'pm' | 'armature' | 'stator_pm';
const defaultDensities: Record<FieldView, FieldArrowDensity> = {
  resultant: 'medium', pm: 'medium', armature: 'medium', stator_pm: 'low',
};

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
    showMesh: true,
    magnifier: true,
    showFieldLines: false,
    showMagnets: false,
    showAirgap: false,
    showPoleLabels: false,
    showToothPoles: false,
    showPhases: false,
    // Under Phases the coils are outlined in their phase colours until this is turned off.
    showCoilColors: true,
    fieldLineDensity: defaultDensities,
    playbackRpm: null as number | null,
  },
};
