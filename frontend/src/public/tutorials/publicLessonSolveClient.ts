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
} from '../../components/tutorials/lessonSolveTypes';
import type { LessonSolveClient } from '../../components/tutorials/lessonSolveClient';
import { PUBLIC_API_BASE } from '../api';

/**
 * The public app's implementation of the tutorial solver port.
 *
 * Same calls as the private workspace's adapter, but every request goes to
 * PUBLIC_API_BASE, which resolvePublicApiBase() has already constrained to a
 * loopback host — the public build never talks to a remote solver.
 *
 * Query parameter names and defaults are deliberately identical to the private
 * client (src/api/client.ts) because both hit the same backend routes; the public
 * ones are served by backend/public_routes/tutorials.py. If a default changes on
 * one side the lesson silently solves a different geometry, so
 * scripts/test-public-lesson-api.mjs pins the two sets against each other.
 */

async function getJson<T>(url: string, what: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detailBody = body && typeof body === 'object'
      ? (body as { message?: string; detail?: string | { message?: string } })
      : null;
    const detail = detailBody?.message
      ?? (typeof detailBody?.detail === 'string'
        ? detailBody.detail
        : detailBody?.detail?.message);
    throw new Error(detail || `${what} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function followFluxQuery(options: FollowFluxOptions = {}): string {
  const params = new URLSearchParams({
    steel_return: String(options.steelReturn ?? false),
    steel_shape: options.steelShape ?? 'bar',
    steel_center_x_mm: String(options.steelCenterXMm ?? 28),
    steel_center_y_mm: String(options.steelCenterYMm ?? 0),
    magnet_center_x_mm: String(options.magnetCenterXMm ?? 0),
    magnet_center_y_mm: String(options.magnetCenterYMm ?? 0),
    magnet_angle_deg: String(options.magnetAngleDeg ?? 0),
    magnet2_enabled: String(options.magnet2Enabled ?? false),
    magnet2_center_x_mm: String(options.magnet2CenterXMm ?? 44),
    magnet2_center_y_mm: String(options.magnet2CenterYMm ?? 0),
    magnet2_angle_deg: String(options.magnet2AngleDeg ?? 0),
    steel_angle_deg: String(options.steelAngleDeg ?? 0),
    mesh_density: options.meshDensity ?? 'normal',
  });
  return params.toString();
}

function lessonOneQuery(
  options?: TutorialLessonOneSolveOptions | TutorialLessonOneDesignOptions,
): string {
  const params = new URLSearchParams();
  if (options && 'phaseCurrentA' in options && options.phaseCurrentA !== undefined) {
    params.set('phase_current_a', String(options.phaseCurrentA));
  }
  if (options && 'currentAngleDeg' in options && options.currentAngleDeg !== undefined) {
    params.set('current_angle_deg', String(options.currentAngleDeg));
  }
  if (options?.airgapMm !== undefined) params.set('airgap_mm', String(options.airgapMm));
  if (options?.magnetArcPct !== undefined) params.set('magnet_arc_pct', String(options.magnetArcPct));
  if (options?.magnetThicknessMm !== undefined) {
    params.set('magnet_thickness_mm', String(options.magnetThicknessMm));
  }
  if (options?.meshDensity !== undefined) params.set('mesh_density', options.meshDensity);
  return params.toString();
}

export const publicLessonSolveClient: LessonSolveClient = {
  fetchLinearMotorCapstoneSolve(currentA, airgapMm, magnetOrientations, windingSpacingMm) {
    if (magnetOrientations.length !== 4) {
      return Promise.reject(new Error('Linear-capstone solve requires four magnet orientations.'));
    }
    const params = new URLSearchParams({
      current_a: String(currentA),
      airgap_mm: String(airgapMm),
      winding_spacing_mm: String(windingSpacingMm),
    });
    magnetOrientations.forEach((orientation, index) => {
      params.set(`magnet_${index + 1}`, String(orientation));
    });
    return getJson<LinearMotorCapstoneFieldData>(
      `${PUBLIC_API_BASE}/tutorials/chapter-1-capstone/solve?${params.toString()}`,
      'Linear-capstone solve',
    );
  },

  fetchFollowFluxSolve(options: FollowFluxOptions = {}) {
    return getJson<FollowFluxFieldData>(
      `${PUBLIC_API_BASE}/tutorials/follow-the-flux/solve?${followFluxQuery(options)}`,
      'Follow-the-flux solve',
    );
  },

  fetchAirgapTaxSolve(airgapMm: number) {
    const params = new URLSearchParams({ airgap_mm: String(airgapMm) });
    return getJson<AirgapTaxFieldData>(
      `${PUBLIC_API_BASE}/tutorials/airgap-tax/solve?${params.toString()}`,
      'Airgap-tax solve',
    );
  },

  async cancelSolve() {
    await fetch(`${PUBLIC_API_BASE}/solve/cancel`, { method: 'POST' });
  },

  fetchSolveFieldFrameArtifact(artifactId: string) {
    return getJson<FieldLineFrameArtifactPayload>(
      `${PUBLIC_API_BASE}/solve/field-frame/${encodeURIComponent(artifactId)}`,
      'Field frame fetch',
    );
  },

  fetchTutorialLessonOneMeshPreview(options?: TutorialLessonOneDesignOptions) {
    const query = lessonOneQuery(options);
    return getJson<MeshPreviewData>(
      `${PUBLIC_API_BASE}/tutorials/lesson-1/mesh-preview${query ? `?${query}` : ''}`,
      'Lesson mesh preview',
    );
  },

  fetchLessonOneFieldComposition(
    source: LessonOneFieldCompositionSource,
    options?: TutorialLessonOneSolveOptions,
  ) {
    const query = lessonOneQuery(options);
    return getJson<LessonOneFieldCompositionResult>(
      `${PUBLIC_API_BASE}/tutorials/lesson-1/field-composition/${source}${query ? `?${query}` : ''}`,
      source === 'armature' ? 'Lesson stator-only field solve' : 'Lesson rotor-only field solve',
    );
  },

  solveTutorialLessonOneStream(
    options: TutorialLessonOneSolveOptions,
    onProgress: (progress: SolveProgress) => void,
    onComplete: (result: TutorialLessonOneSolveResult) => void,
    onError: (error: { error_code: string; message: string; suggestion?: string }) => void,
  ) {
    const controller = new AbortController();
    const query = lessonOneQuery(options);
    const url = `${PUBLIC_API_BASE}/tutorials/lesson-1/solve/stream${query ? `?${query}` : ''}`;

    (async () => {
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok || !response.body) {
          throw new Error(`Lesson solve failed: ${response.status}`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let eventType = '';

        // The backend emits "event: <type>\ndata: <json>\n\n" — the type is on the
        // `event:` line and is NOT a field of the JSON payload
        // (backend/public_routes/solve.py:239). Dispatching on a `type` key inside
        // the payload therefore matches nothing, and the lesson hangs with the solve
        // running server-side. Line-oriented parse, same shape as the private client
        // in src/api/client.ts:2349, so the two stay comparable.
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          // Keep the trailing fragment: a chunk boundary can split a line.
          buffer = lines.pop() || '';
          for (const rawLine of lines) {
            const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ') && eventType) {
              const payload = line.slice(6);
              try {
                const data = JSON.parse(payload) as Record<string, unknown>;
                if (eventType === 'progress') {
                  onProgress(data as unknown as SolveProgress);
                } else if (eventType === 'complete') {
                  onComplete(data as unknown as TutorialLessonOneSolveResult);
                } else if (eventType === 'error') {
                  onError({
                    error_code: String(data.error_code ?? 'SOLVER_ERROR'),
                    message: String(data.message ?? 'Lesson solve failed'),
                    suggestion: data.suggestion ? String(data.suggestion) : undefined,
                  });
                }
              } catch (parseError) {
                // A truncated progress frame is survivable; a truncated terminal
                // event is not — surface it rather than hanging.
                if (eventType === 'complete' || eventType === 'error') {
                  onError({
                    error_code: 'STREAM_PARSE_ERROR',
                    message: parseError instanceof Error
                      ? `Could not parse lesson ${eventType} event: ${parseError.message}`
                      : `Could not parse lesson ${eventType} event.`,
                  });
                }
              }
              eventType = '';
            }
          }
        }
      } catch (caught) {
        if (controller.signal.aborted) return;
        onError({
          error_code: 'SOLVER_ERROR',
          message: caught instanceof Error ? caught.message : 'Lesson solve failed',
        });
      }
    })();

    return controller;
  },

  fetchCurrentFieldSolve(currentA: number) {
    const params = new URLSearchParams({ current_a: String(currentA) });
    return getJson<CurrentFieldData>(
      `${PUBLIC_API_BASE}/tutorials/current-field/solve?${params.toString()}`,
      'Current-field solve',
    );
  },

  fetchIronSaturationSolve(currentA: number) {
    const params = new URLSearchParams({ current_a: String(currentA) });
    return getJson<IronSaturationFieldData>(
      `${PUBLIC_API_BASE}/tutorials/iron-saturation/solve?${params.toString()}`,
      'Iron-saturation solve',
    );
  },

  fetchIronSaturationToothSolve(currentA: number) {
    const params = new URLSearchParams({ current_a: String(currentA) });
    return getJson<IronSaturationToothFieldData>(
      `${PUBLIC_API_BASE}/tutorials/iron-saturation/tooth/solve?${params.toString()}`,
      'Iron-tooth solve',
    );
  },

  fetchIronSaturationSpmToothSolve(currentA: number) {
    const params = new URLSearchParams({ current_a: String(currentA) });
    return getJson<IronSaturationSpmToothFieldData>(
      `${PUBLIC_API_BASE}/tutorials/iron-saturation/spm-tooth/solve?${params.toString()}`,
      'SPM-tooth solve',
    );
  },

  fetchFieldForceSolve(currentA: number, poleGapMm = 8) {
    const params = new URLSearchParams({
      current_a: String(currentA),
      pole_gap_mm: String(poleGapMm),
    });
    return getJson<FieldForceData>(
      `${PUBLIC_API_BASE}/tutorials/field-force/solve?${params.toString()}`,
      'Field-force solve',
    );
  },

  fetchFieldForceMotorSolve(currentA: number, loopAngleDeg: number, poleGapMm = 8) {
    const params = new URLSearchParams({
      current_a: String(currentA),
      loop_angle_deg: String(loopAngleDeg),
      pole_gap_mm: String(poleGapMm),
    });
    return getJson<FieldForceMotorData>(
      `${PUBLIC_API_BASE}/tutorials/field-force/motor/solve?${params.toString()}`,
      'Motor-effect FEM solve',
    );
  },

  fetchFieldForceWireSolve(currentA: number, poleGapMm = 8) {
    const params = new URLSearchParams({
      current_a: String(currentA),
      pole_gap_mm: String(poleGapMm),
    });
    return getJson<FieldForceWireData>(
      `${PUBLIC_API_BASE}/tutorials/field-force/wire-only/solve?${params.toString()}`,
      'Field-force wire solve',
    );
  },

  fetchFieldForceMagnetSolve(poleGapMm = 8) {
    const params = new URLSearchParams({ pole_gap_mm: String(poleGapMm) });
    return getJson<FieldForceMagnetData>(
      `${PUBLIC_API_BASE}/tutorials/field-force/magnet-only/solve?${params.toString()}`,
      'Field-force magnet solve',
    );
  },

  fetchRotorChaseSolve(
    fieldSource: RotorChaseFieldSource,
    rotorAngleDeg: number,
    poleGapMm = 8,
    sourceKind: RotorChaseSourceKind = 'pm',
    sourceCurrentA = 0,
  ) {
    const params = new URLSearchParams({
      field_source: fieldSource,
      rotor_angle_deg: String(rotorAngleDeg),
      pole_gap_mm: String(poleGapMm),
      source_kind: sourceKind,
      source_current_a: String(sourceCurrentA),
    });
    return getJson<RotorChaseFieldData>(
      `${PUBLIC_API_BASE}/tutorials/rotor-chase/solve?${params.toString()}`,
      'Rotor-chase solve',
    );
  },

  fetchRotatingFieldSweep(peakCurrentA = 8) {
    const params = new URLSearchParams({ peak_current_a: String(peakCurrentA) });
    return getJson<RotatingFieldSweepData>(
      `${PUBLIC_API_BASE}/tutorials/rotating-field/sweep?${params.toString()}`,
      'Rotating-field sweep',
    );
  },

  fetchRotatingFieldMotorSweep(
    peakCurrentA = 8,
    fieldComponent: 'combined' | 'stator' | 'rotor' = 'combined',
  ) {
    const params = new URLSearchParams({
      peak_current_a: String(peakCurrentA),
      field_component: fieldComponent,
    });
    return getJson<RotatingFieldMotorSweepData>(
      `${PUBLIC_API_BASE}/tutorials/rotating-field/motor-sweep?${params.toString()}`,
      'Rotating-field motor sweep',
    );
  },

  fetchRotatingFieldMotorGeometry() {
    return getJson<RotatingFieldMotorFrameData>(
      `${PUBLIC_API_BASE}/tutorials/rotating-field/motor-geometry`,
      'Rotating-field motor geometry',
    );
  },

  fetchThreePhaseMotorSweep(
    peakCurrentA = 8,
    fieldComponent: ThreePhaseMotorFieldComponent = 'combined',
  ) {
    const params = new URLSearchParams({
      peak_current_a: String(peakCurrentA),
      field_component: fieldComponent,
    });
    return getJson<ThreePhaseMotorSweepData>(
      `${PUBLIC_API_BASE}/tutorials/three-phase-motor/sweep?${params.toString()}`,
      'Three-phase motor sweep',
    );
  },

  fetchThreePhaseMotorGeometry() {
    return getJson<ThreePhaseMotorFrameData>(
      `${PUBLIC_API_BASE}/tutorials/three-phase-motor/geometry`,
      'Three-phase motor geometry',
    );
  },
};
