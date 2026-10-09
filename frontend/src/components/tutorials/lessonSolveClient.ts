import React from 'react';
import type {
  AirgapTaxFieldData,
  CurrentFieldData,
  FieldForceData,
  FieldForceMagnetData,
  FieldForceMotorData,
  FieldForceWireData,
  FieldLineFrameArtifactPayload,
  FollowFluxFieldData,
  FollowFluxOptions,
  IronSaturationFieldData,
  IronSaturationSpmToothFieldData,
  IronSaturationToothFieldData,
  LessonOneFieldCompositionResult,
  LessonOneFieldCompositionSource,
  LinearMotorCapstoneFieldData,
  MeshPreviewData,
  RotatingFieldMotorFrameData,
  RotatingFieldMotorSweepData,
  RotatingFieldSweepData,
  RotorChaseFieldData,
  RotorChaseFieldSource,
  RotorChaseSourceKind,
  SolveProgress,
  ThreePhaseMotorFieldComponent,
  ThreePhaseMotorFrameData,
  ThreePhaseMotorSweepData,
  TutorialLessonOneDesignOptions,
  TutorialLessonOneSolveOptions,
  TutorialLessonOneSolveResult,
} from './lessonSolveTypes';

/**
 * Every solver call the tutorial lessons make, as an injected port.
 *
 * The lessons are shared between the private workspace and the public app, so
 * they cannot reach into a concrete API module. The host application supplies
 * an implementation through `LessonSolveClientContext`; the signatures below
 * mirror the host's functions exactly (optional params stand in for the
 * defaults those functions already apply).
 */
export interface LessonSolveClient {
  /** Chapter 1 capstone — a four-pole moving-coil linear actuator. */
  fetchLinearMotorCapstoneSolve(
    currentA: number,
    airgapMm: number,
    magnetOrientations: readonly number[],
    windingSpacingMm: number,
  ): Promise<LinearMotorCapstoneFieldData>;

  /** Lesson 1 — follow the flux. */
  fetchFollowFluxSolve(options?: FollowFluxOptions): Promise<FollowFluxFieldData>;

  /** Lesson 2 — the airgap tax. */
  fetchAirgapTaxSolve(airgapMm: number): Promise<AirgapTaxFieldData>;

  /** Lesson 2 — the magnetic circuit (reuses the lesson-1 solve pipeline). */
  cancelSolve(): Promise<void>;
  fetchSolveFieldFrameArtifact(artifactId: string): Promise<FieldLineFrameArtifactPayload>;
  fetchTutorialLessonOneMeshPreview(options?: TutorialLessonOneDesignOptions): Promise<MeshPreviewData>;
  fetchLessonOneFieldComposition(
    source: LessonOneFieldCompositionSource,
    options?: TutorialLessonOneSolveOptions,
  ): Promise<LessonOneFieldCompositionResult>;
  solveTutorialLessonOneStream(
    options: TutorialLessonOneSolveOptions,
    onProgress: (progress: SolveProgress) => void,
    onComplete: (result: TutorialLessonOneSolveResult) => void,
    onError: (error: { error_code: string; message: string; suggestion?: string }) => void,
  ): AbortController;

  /** Lesson 3 — current makes a field. */
  fetchCurrentFieldSolve(currentA: number): Promise<CurrentFieldData>;

  /** Lesson 4 — iron saturation. */
  fetchIronSaturationSolve(currentA: number): Promise<IronSaturationFieldData>;
  fetchIronSaturationToothSolve(currentA: number): Promise<IronSaturationToothFieldData>;
  fetchIronSaturationSpmToothSolve(currentA: number): Promise<IronSaturationSpmToothFieldData>;

  /** Lesson 5 — field + current = force. */
  fetchFieldForceSolve(currentA: number, poleGapMm?: number): Promise<FieldForceData>;
  fetchFieldForceMotorSolve(
    currentA: number,
    loopAngleDeg: number,
    poleGapMm?: number,
  ): Promise<FieldForceMotorData>;
  fetchFieldForceWireSolve(currentA: number, poleGapMm?: number): Promise<FieldForceWireData>;
  fetchFieldForceMagnetSolve(poleGapMm?: number): Promise<FieldForceMagnetData>;

  /** Lesson 6 — the rotor chases the field. */
  fetchRotorChaseSolve(
    fieldSource: RotorChaseFieldSource,
    rotorAngleDeg: number,
    poleGapMm?: number,
    sourceKind?: RotorChaseSourceKind,
    sourceCurrentA?: number,
  ): Promise<RotorChaseFieldData>;

  /** Lesson 7 — the rotating field. */
  fetchRotatingFieldSweep(peakCurrentA?: number): Promise<RotatingFieldSweepData>;
  fetchRotatingFieldMotorSweep(
    peakCurrentA?: number,
    fieldComponent?: 'combined' | 'stator' | 'rotor',
  ): Promise<RotatingFieldMotorSweepData>;
  fetchRotatingFieldMotorGeometry(): Promise<RotatingFieldMotorFrameData>;

  /** Lesson 8 — the three-phase motor. */
  fetchThreePhaseMotorSweep(
    peakCurrentA?: number,
    fieldComponent?: ThreePhaseMotorFieldComponent,
  ): Promise<ThreePhaseMotorSweepData>;
  fetchThreePhaseMotorGeometry(): Promise<ThreePhaseMotorFrameData>;
}

export const LessonSolveClientContext = React.createContext<LessonSolveClient | null>(null);

/** Read the host-supplied solver port. Throws when a lesson renders unwrapped. */
export function useLessonSolveClient(): LessonSolveClient {
  const client = React.useContext(LessonSolveClientContext);
  if (!client) {
    throw new Error(
      'Tutorial lessons need a LessonSolveClientContext.Provider supplying a LessonSolveClient.',
    );
  }
  return client;
}
