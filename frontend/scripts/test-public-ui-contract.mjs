import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, '..');
const readOptionalSource = async (relativePath) => {
  try {
    return await readFile(path.join(frontendRoot, relativePath), 'utf8');
  } catch (error) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
};
const appSource = await readFile(path.join(frontendRoot, 'src/public/App.tsx'), 'utf8');
const mainSource = await readFile(path.join(frontendRoot, 'src/public/main.tsx'), 'utf8');
const workspaceSource = await readFile(path.join(frontendRoot, 'src/public/CoilEmWorkspace.tsx'), 'utf8');
const bldcChartSource = await readFile(path.join(frontendRoot, 'src/public/BldcTorqueCurrentChart.tsx'), 'utf8');
const exampleDesignsSource = await readFile(path.join(frontendRoot, 'src/public/exampleDesigns.ts'), 'utf8');
const runComparisonSource = await readFile(path.join(frontendRoot, 'src/public/PublicRunComparison.tsx'), 'utf8');
const materialWorkspaceSource = await readFile(
  path.join(frontendRoot, 'src/public/MaterialWorkspace.tsx'),
  'utf8',
);
const modelSource = await readFile(path.join(frontendRoot, 'src/public/model.ts'), 'utf8');
const dimensionsSource = await readFile(path.join(frontendRoot, 'src/public/dimensionAnnotations.ts'), 'utf8');
const motorCanvasSource = await readFile(path.join(frontendRoot, 'src/public/MotorCanvas.tsx'), 'utf8');
const meshQualitySource = await readFile(path.join(frontendRoot, 'src/public/meshQuality.ts'), 'utf8');
const solvePlanSource = await readFile(path.join(frontendRoot, 'src/public/solvePlan.ts'), 'utf8');
const solveProgressSource = await readFile(path.join(frontendRoot, 'src/public/solveProgress.ts'), 'utf8');
const viewportNavigationSource = await readFile(path.join(frontendRoot, 'src/public/ViewportNavigation.tsx'), 'utf8');
const motorThreeSource = await readFile(path.join(frontendRoot, 'src/public/PublicMotor3D.tsx'), 'utf8');
const landingSource = await readFile(path.join(frontendRoot, 'src/public/PublicLanding.tsx'), 'utf8');
const landingWorkflowHeroSource = await readFile(
  path.join(frontendRoot, 'src/components/LandingWorkflowHero.tsx'),
  'utf8',
);
const landingHalbachPreviewSource = await readFile(
  path.join(frontendRoot, 'src/components/landing-3d/LandingHalbachPreview.tsx'),
  'utf8',
);
const landingPreviewModeControlSource = await readFile(
  path.join(frontendRoot, 'src/components/landing-3d/LandingPreviewModeControl.tsx'),
  'utf8',
);
const landingHalbachMeshFixture = JSON.parse(await readFile(
  path.join(frontendRoot, 'src/components/landing-3d/hero_linear_halbach_mesh.gmsh.json'),
  'utf8',
));
const landingHalbachFieldFixture = JSON.parse(await readFile(
  path.join(frontendRoot, 'src/components/landing-3d/hero_linear_halbach_field.magneto2d.json'),
  'utf8',
));
const templateSelectorSource = await readOptionalSource('src/components/TemplateSelector.tsx');
const topBarSource = await readOptionalSource('src/components/TopBar.tsx');
const landingThreeSource = await readFile(path.join(frontendRoot, 'src/components/landing-3d/Landing3DPreview.tsx'), 'utf8');
const halbachWorkspaceSource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/HalbachWorkspace.tsx'),
  'utf8',
);
const halbachTwoSource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/Halbach2DViewport.tsx'),
  'utf8',
);
const halbachThreeSource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/Halbach3DViewer.tsx'),
  'utf8',
);
const linearHalbachWorkspaceSource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/LinearHalbachWorkspace.tsx'),
  'utf8',
);
const linearHalbachTwoSource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/LinearHalbach2DViewport.tsx'),
  'utf8',
);
const linearHalbachThreeSource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/LinearHalbach3DViewer.tsx'),
  'utf8',
);
const halbachApiSource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/api.ts'),
  'utf8',
);
const halbachTypesSource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/types.ts'),
  'utf8',
);
const halbachGeometrySource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/geometry.ts'),
  'utf8',
);
const halbachPoleRenderingSource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/poleRendering.ts'),
  'utf8',
);
const halbachStyleSource = await readFile(
  path.join(frontendRoot, 'src/public/halbach/halbach.css'),
  'utf8',
);
const waveformSource = await readFile(path.join(frontendRoot, 'src/public/WaveformChart.tsx'), 'utf8');
const fieldResultSource = await readFile(path.join(frontendRoot, 'src/public/FieldResultPlot.tsx'), 'utf8');
const solvedFieldSource = await readFile(path.join(frontendRoot, 'src/public/SolvedFieldViewer.tsx'), 'utf8');
const playbackContractSource = await readFile(path.join(frontendRoot, 'src/public/fieldPlaybackContract.ts'), 'utf8');
const playbackTimingSource = await readFile(path.join(frontendRoot, 'src/public/fieldPlaybackTiming.ts'), 'utf8');
const playbackRasterizerSource = await readFile(path.join(frontendRoot, 'src/public/fieldPlaybackRasterizer.ts'), 'utf8');
const playbackWorkerSource = await readFile(path.join(frontendRoot, 'src/public/fieldPlaybackWorker.ts'), 'utf8');
const apiSource = await readFile(path.join(frontendRoot, 'src/public/api.ts'), 'utf8');
const guidedSource = await readFile(path.join(frontendRoot, 'src/public/GuidedSetup.tsx'), 'utf8');
const guidedRepairSource = await readFile(
  path.join(frontendRoot, 'src/public/guidedConfigRepair.ts'),
  'utf8',
);
const styleSource = await readFile(path.join(frontendRoot, 'src/public/styles.css'), 'utf8');
const windingLayoutSource = await readFile(
  path.join(frontendRoot, 'src/public/WindingLayoutView.tsx'),
  'utf8',
);
const viteSource = await readFile(path.join(frontendRoot, 'vite.public.config.ts'), 'utf8');

assert.match(appSource, /previewRequestId/);
assert.match(appSource, /window\.setTimeout\(\(\) => \{/);
assert.match(appSource, /setGeometryStale\(true\)/);
const previewInvalidationBlock = appSource.slice(
  appSource.indexOf('const invalidateGeometryPreview'),
  appSource.indexOf('const prepareMesh'),
);
assert.match(previewInvalidationBlock, /previewRequestId\.current \+= 1/);
assert.match(previewInvalidationBlock, /setGeometryStale\(true\)/);
assert.match(previewInvalidationBlock, /current === 'geometry' \? null : current/);
const updateSectionBlock = appSource.slice(
  appSource.indexOf('const updateSection'),
  appSource.indexOf('const updateTopology'),
);
assert.match(updateSectionBlock, /section !== 'solve_params'/);
assert.match(updateSectionBlock, /invalidateGeometryPreview\(\)/);
const refreshGeometryBlock = appSource.slice(
  appSource.indexOf('const refreshGeometry'),
  appSource.indexOf('useEffect(() => {', appSource.indexOf('const refreshGeometry')),
);
assert.match(refreshGeometryBlock, /const requestId = \+\+previewRequestId\.current/);
assert.match(refreshGeometryBlock, /setGeometryStale\(true\)/);
assert.match(refreshGeometryBlock, /setGeometryStale\(false\)/);
assert.match(appSource, /<CoilEmWorkspace/);
assert.match(appSource, /setView\('solve'\)/);
assert.match(solvePlanSource, /quick: 'coarse'/);
assert.match(solvePlanSource, /standard: 'normal'/);
assert.match(solvePlanSource, /fine: 'fine'/);
assert.match(solvePlanSource, /solve_quality: solvePlan/);
assert.match(solvePlanSource, /mesh_density: PUBLIC_SOLVE_PLAN_MESH_DENSITY\[solvePlan\]/);
assert.match(solvePlanSource, /solve_quality: 'custom'/);
assert.match(solvePlanSource, /rotor_sweep_range_deg: PUBLIC_CUSTOM_SWEEP_RANGE_DEG/);
assert.match(solvePlanSource, /rotor_step_deg: rotorStepDeg/);
assert.doesNotMatch(
  solvePlanSource.slice(
    solvePlanSource.indexOf('export function applyPublicCustomSweep'),
    solvePlanSource.indexOf('export function applyPublicSolvePreset'),
  ),
  /mesh_density:/,
);
assert.match(appSource, /void prepareMesh\(/);
assert.match(appSource, /const refreshSolveValidation = useCallback/);
assert.match(appSource, /void refreshSolveValidation\(config\)/);
assert.match(appSource, /validationChecking=\{validationChecking\}/);
assert.match(appSource, /useState<PublicSolverId>\('magneto2d'\)/);
assert.match(appSource, /elmerCapabilityFromHealth/);
assert.match(appSource, /elmerCapabilityIsReady/);
assert.match(appSource, /feature_enabled: payload\.feature_enabled === true/);
assert.match(appSource, /adapter_ready: payload\.adapter_ready === true/);
assert.match(appSource, /solver: selectedSolver/);
assert.match(appSource, /selectedSolver === 'magneto2d' && preparedMesh\.solve_mesh_key/);
assert.match(appSource, /Elmer remeshes each rotor position/);
const selectSolverBlock = appSource.slice(
  appSource.indexOf('const selectSolver'),
  appSource.indexOf('const updateSolvePlan'),
);
assert.doesNotMatch(selectSolverBlock, /setConfig/, 'Solver selection must not overwrite project settings');
assert.match(workspaceSource, /aria-pressed=\{config\.topology === topology\}/);
assert.match(workspaceSource, /className="workflow-stepper workflow-stepper-inline"/);
assert.match(workspaceSource, /design-workspace workflow-stage-content\$\{designViewportExpanded/);
assert.match(workspaceSource, /className="design-workspace-main"/);
assert.match(workspaceSource, /className="design-workspace-health"/);
assert.match(workspaceSource, /currentGeometryWarnings\(geometry, geometryStale\)/);
assert.match(workspaceSource, /currentToothWidthAdvisory\(geometry, geometryStale\)/);
assert.match(workspaceSource, /'Bore tooth is much narrower' : 'Bore tooth is slightly narrower'/);
assert.match(workspaceSource, /Bore \$\{statorWidths\.boreToothWidthMm\.toFixed\(1\)\} mm · yoke \$\{statorWidths\.toothWidthAtYokeMm/);
assert.match(workspaceSource, /This mild taper is usually acceptable/);
assert.match(workspaceSource, /<HealthPanel[^>]*geometryStale=\{props\.geometryStale\}/);
assert.match(workspaceSource, /className="panel-left public-parameter-panel"/);
assert.match(workspaceSource, /const burialHealth = publicFlatIpmBurialHealth\(config\)/);
assert.match(workspaceSource, /\.\.\.\(burialHealth \? \[burialHealth\] : \[\]\)/);
assert.match(workspaceSource, /burialHealth\?\.blocking !== true/);
assert.match(workspaceSource, /NumberRow label="Bore Tooth Width".*min=\{minimumBoreToothWidthMm\}.*max=\{maximumBoreToothWidthMm\}/);
assert.match(workspaceSource, /NumberRow label="Yoke Tooth Width".*min=\{2\}/);
assert.match(workspaceSource, /label="Outer Bridge"/);
assert.match(workspaceSource, /value=\{config\.rotor\.bridge_thickness_mm\}/);
assert.match(workspaceSource, /onChange=\{set\('rotor', 'bridge_thickness_mm', 'rotor'\)\}/);
assert.match(workspaceSource, /Minimum radial steel between the rotor outer surface and the nearest magnet-pocket corner/);
assert.match(workspaceSource, /\['Outer bridge', `\$\{config\.rotor\.bridge_thickness_mm\} mm`\]/);
assert.match(workspaceSource, /burial depth outer bridge bridge thickness magnet position/);
assert.match(workspaceSource, /Physical Slot Mouth<small>mm · calc/);
assert.match(workspaceSource, /Tooth Body Opening<small>mm · calc/);
assert.match(workspaceSource, /Slot Width at Yoke<small>mm · calc/);
assert.match(workspaceSource, /label="Tooth Shoe"/);
assert.match(workspaceSource, /label="Shoe Height"/);
assert.match(workspaceSource, /label="Shoe Overhang"/);
assert.match(workspaceSource, /role="switch"/);
assert.match(workspaceSource, /statorWidths\.borePitchMm[\s\S]*?\+ toothShoeAdditionMm[\s\S]*?- boundedWidthMm/);
assert.match(workspaceSource, /set\('stator', 'slot_opening_mm', 'advanced'\)\(boreSlotOpeningMm\)/);
assert.match(dimensionsSource, /borePitchMm - boreOpeningMm \+ toothShoeAdditionMm/);
assert.match(dimensionsSource, /label: 'Bore tooth'/);
assert.match(dimensionsSource, /label: 'Yoke tooth'/);
assert.match(dimensionsSource, /label: 'Bore opening'/);
assert.match(dimensionsSource, /label: 'Slot at yoke'/);
assert.doesNotMatch(dimensionsSource, /label: 'Tooth width'/);
assert.match(workspaceSource, /className="param-row public-param-row public-derived-row"><span className="param-label">Coverage/);
assert.match(styleSource, /\.public-derived-row strong \{ width: 78px;[^}]*text-align: right; \}/);
assert.match(workspaceSource, /Choose a supported steel/);
assert.match(workspaceSource, /This project uses an unavailable steel/);
assert.match(workspaceSource, /Converting changes the material model and predicted results/);
assert.match(workspaceSource, />Convert project to M350-50A</);
assert.match(workspaceSource, /Material not supported/);
assert.match(appSource, /const convertProjectSteelToM350 = useCallback/);
assert.match(appSource, /stator_steel: 'M350-50A'/);
assert.match(appSource, /rotor_steel: 'M350-50A'/);
assert.match(appSource, /save a new \.coilem file to preserve the conversion/);
assert.match(workspaceSource, /public-solve-workspace\$\{resizingRunPlan[\s\S]*?solveViewportExpanded/);
assert.match(workspaceSource, /className="public-solve-setup-scroll"/);
assert.match(workspaceSource, /className="public-solve-footer"/);
assert.match(workspaceSource, /function ExcitationRunPlanPreview/);
assert.match(workspaceSource, /runPlanSinePath/);
assert.match(workspaceSource, /runPlanSixStepPath/);
assert.match(workspaceSource, /<ExcitationRunPlanPreview config=\{config\} \/>/);
assert.match(workspaceSource, /Six-step BLDC/);
assert.match(workspaceSource, /Two phases on · one phase floating · wye/);
assert.match(styleSource, /\.public-excitation-preview-plot \.phase-a/);
assert.match(styleSource, /\.public-excitation-preview-plot \.phase-b/);
assert.match(styleSource, /\.public-excitation-preview-plot \.phase-c/);
const solveFooterIndex = workspaceSource.indexOf('className="public-solve-footer"');
const runActionIndex = workspaceSource.indexOf("busy === 'solve' ? 'public-cancel-btn' : 'public-run-btn'");
const runPlanIndex = workspaceSource.indexOf('className="public-run-plan"');
assert.ok(solveFooterIndex >= 0 && runActionIndex > solveFooterIndex && runActionIndex < runPlanIndex, 'Run analysis belongs in the left solve footer');
assert.match(workspaceSource, /export type PublicWorkflowStep = 'design' \| 'solve' \| 'report'/);
assert.match(workspaceSource, /\{ id: 'report', label: 'Results', available: resultReady \}/);
assert.match(workspaceSource, /Full results →/);
assert.doesNotMatch(workspaceSource, /\{ id: 'report', label: 'Report'/);
assert.doesNotMatch(workspaceSource, /id: 'mesh'/);
assert.match(workspaceSource, /Continue to Solve/);
assert.doesNotMatch(workspaceSource, /Continue Setup: Mesh/);
assert.match(workspaceSource, /Ready to solve/);
assert.match(workspaceSource, /Valid to solve · review design/);
assert.match(workspaceSource, /checks passed/);
assert.doesNotMatch(workspaceSource, /public-score-ring/);
assert.match(workspaceSource, /Advanced options/);
assert.match(workspaceSource, /aria-label="Electromagnetic solver"/);
assert.match(workspaceSource, /Elmer FEM/);
assert.match(workspaceSource, /elmerAvailable \? `Version \$\{elmerCapability\.solver_version/);
assert.match(workspaceSource, /&& elmerCapability\.adapter_ready/);
assert.match(workspaceSource, /Qualified Elmer 26\.2 profile/);
assert.match(workspaceSource, /magnetoCompositionAvailable=\{selectedSolver === 'magneto2d'\}/);
assert.match(workspaceSource, /Prepare mesh/);
assert.match(workspaceSource, /Regenerate mesh/);
assert.match(workspaceSource, /className="results-dashboard public-report-stage"/);
assert.match(workspaceSource, /className="public-saved-run"/);
const reportStageIndex = workspaceSource.indexOf('className="results-dashboard public-report-stage"');
const savedRunPanelIndex = workspaceSource.indexOf('{savedRunPanel}', reportStageIndex);
const reportMetricsIndex = workspaceSource.indexOf('className="metric-grid wide"', reportStageIndex);
assert.ok(
  savedRunPanelIndex > reportStageIndex && savedRunPanelIndex < reportMetricsIndex,
  'Saved locally panel belongs directly beneath the This run header controls',
);
assert.match(workspaceSource, />Download PDF</);
assert.match(workspaceSource, />Download CSV</);
assert.match(workspaceSource, />Open result folder</);
assert.match(workspaceSource, />Save replayable run package</);
assert.match(workspaceSource, /completed \$\{result\.saved_run\.completed_at\}/);
assert.match(workspaceSource, />Open project</);
assert.match(workspaceSource, />Rerun settings</);
assert.match(workspaceSource, />Compare runs</);
assert.match(workspaceSource, /PublicRunComparison/);
assert.match(workspaceSource, /elmerCapability\.feature_enabled && <div className="public-setup-section public-solver-section">/);
assert.match(workspaceSource, /aria-label="Previous runs"/);
assert.match(workspaceSource, /Review or compare completed analyses without starting another solve/);
assert.match(workspaceSource, /<PublicRunComparison manageRuns/);
assert.match(workspaceSource, /Manage previous runs/);
assert.match(workspaceSource, /needsRunStorageRecovery\(props\.error\)/);
assert.match(runComparisonSource, /aria-label="Local run storage"/);
assert.match(runComparisonSource, /Saved results stay on this computer and are never removed automatically/);
assert.match(runComparisonSource, /Delete an older saved or incomplete run below/);
assert.match(runComparisonSource, /Delete permanently/);
assert.match(runComparisonSource, /record\.status === 'running'/);
assert.match(apiSource, /export function deletePublicRun/);
assert.match(apiSource, /confirm_run_id: runId/);
assert.match(styleSource, /\.public-run-storage-meter/);
assert.match(workspaceSource, /aria-label="Example designs"/);
assert.match(workspaceSource, /PUBLIC_EXAMPLE_OPTIONS\.map/);
assert.match(workspaceSource, /public-project-submenu-trigger/);
assert.match(workspaceSource, />Motor examples</);
assert.match(workspaceSource, />Field examples</);
assert.match(workspaceSource, /onOpenHalbach/);
if (topBarSource !== null) {
  assert.match(topBarSource, /onOpenHalbach/);
  assert.match(topBarSource, /Halbach array/);
  assert.match(topBarSource, /Field design/);
}
assert.match(appSource, /createPublicExampleDesign\(exampleId\)/);
assert.match(exampleDesignsSource, /id: 'spm-8p12s'/);
assert.match(exampleDesignsSource, /id: 'ipm-10p-v-shape-medium'/);
assert.match(exampleDesignsSource, /id: 'ipm-14p-flat-buried-large'/);
assert.match(exampleDesignsSource, /id: 'spm-24p-small'/);
assert.match(styleSource, /\.public-project-examples-menu/);
for (const fixtureName of [
  'validation_ipm_10p_v_shape_medium.openem',
  'validation_ipm_14p_flat_buried_large.openem',
  'validation_spm_24p_small.openem',
]) {
  const bundledFixture = JSON.parse(await readFile(path.join(frontendRoot, 'src/public/examples', fixtureName), 'utf8'));
  const referenceFixture = JSON.parse(await readFile(path.join(frontendRoot, '../references/benchmark_configs', fixtureName), 'utf8'));
  assert.deepEqual(bundledFixture, referenceFixture, `${fixtureName} public copy must match the validation fixture`);
}
assert.match(runComparisonSource, /Compare two completed Magneto2D analyses/);
assert.match(runComparisonSource, /run\.status === 'complete' && isMagneto2dRun\(run\)/);
assert.match(runComparisonSource, /listPublicRuns/);
assert.match(runComparisonSource, /if \(!records\.length\) return/);
assert.match(runComparisonSource, /return changed \? next : previous/);
assert.match(runComparisonSource, /angles: right\.result\.torque_waveform\.electrical_angle_deg/);
assert.match(runComparisonSource, /id: 'run-a'/);
assert.match(runComparisonSource, /function percentDelta/);
assert.match(runComparisonSource, /percentage\.toFixed\(1\)/);
assert.match(runComparisonSource, /metric\.deltaUnit \|\| metric\.unit/);
assert.match(runComparisonSource, /percentDelta\(leftValue, rightValue\)/);
assert.match(runComparisonSource, /phase_a_V/);
assert.match(runComparisonSource, /phase_b_V/);
assert.match(runComparisonSource, /phase_c_V/);
assert.match(runComparisonSource, /Three-phase back EMF comparison/);
assert.match(runComparisonSource, /groupLabel: `Run A/);
assert.match(runComparisonSource, /groupLabel: `Run B/);
assert.match(runComparisonSource, /legendLabel: 'Phase A'/);
assert.match(runComparisonSource, /shared positions/);
assert.match(runComparisonSource, /solverLabel\(run\.solver_name\)/);
assert.match(runComparisonSource, /public-run-compare-identities/);
assert.match(runComparisonSource, /solverLabel\(left\.result\.solve_metadata\.solver_name\)/);
assert.match(runComparisonSource, /solverLabel\(right\.result\.solve_metadata\.solver_name\)/);
assert.match(runComparisonSource, /toggleableSeries/);
assert.match(runComparisonSource, /hiddenSeriesKeys=\{hiddenSeriesKeys\}/);
assert.match(runComparisonSource, /Descriptive run comparison/);
assert.match(runComparisonSource, /not a solver-validation verdict/);
assert.match(runComparisonSource, /aria-label="Run comparison metric differences"/);
assert.doesNotMatch(runComparisonSource, /Solver parity/);
assert.doesNotMatch(runComparisonSource, /Elmer/);
assert.match(waveformSource, /item\.angles \|\| angles/);
assert.match(waveformSource, /pathFor\(item\.angles, item\.values\)/);
assert.match(waveformSource, /aria-pressed=\{visible\}/);
assert.match(waveformSource, /visible && plottedSeries\.length === 1/);
assert.match(waveformSource, /samplingLabel \|\|/);
assert.match(waveformSource, /periodicAxisEnd/);
assert.match(waveformSource, /inferredEnd - 360/);
assert.match(waveformSource, /axisMaxX\.toFixed\(0\)/);
assert.match(waveformSource, /strokeDasharray=\{item\.dashArray\}/);
assert.match(waveformSource, /const renderedSeries = \[\.\.\.plottedSeries\]\.sort/);
assert.match(waveformSource, /renderedSeries\.map/);
assert.match(waveformSource, /chart-label chart-unit-label/);
assert.match(waveformSource, /x=\{margin\.left\} y="12"/);
assert.match(waveformSource, /public-waveform-legend-row/);
assert.match(waveformSource, /group\.entries\.map/);
assert.match(styleSource, /\.public-waveform-legend button\[aria-pressed="false"\]/);
assert.match(styleSource, /\.public-waveform-legend-row \{ display: grid;/);
assert.doesNotMatch(runComparisonSource, /pdf-compare/);
assert.match(apiSource, /report\.\$\{exportKind\}/);
assert.match(apiSource, /package\.zip/);
assert.match(appSource, /requires explicit new solve|explicitly start a new analysis/);
assert.match(apiSource, /\/runs\/\$\{encodeURIComponent\(projectSlug\)\}/);
assert.match(workspaceSource, /aria-label="Motor view mode"/);
assert.match(workspaceSource, /PublicMotor3D/);
assert.match(workspaceSource, /window\.requestAnimationFrame\(animate\)/);
assert.match(workspaceSource, /DESIGN_INTRO_DURATION_MS/);
assert.match(workspaceSource, /DESIGN_INTRO_CROSSFADE_START/);
assert.match(workspaceSource, /introCameraProgress/);
assert.match(workspaceSource, /public-design-intro-status/);
assert.match(workspaceSource, /finishDesignIntro\('3d'\)/);
assert.match(workspaceSource, /aria-label="Exploded view amount"/);
assert.match(workspaceSource, /setExplodedAmount/);
assert.match(motorThreeSource, /RoomEnvironment/);
assert.match(motorThreeSource, /MeshPhysicalMaterial/);
assert.match(motorThreeSource, /teethGroup/);
assert.match(motorThreeSource, /deriveStatorSectionWidths\(config\)/);
assert.match(motorThreeSource, /statorWidths\.boreToothWidthMm/);
assert.match(motorThreeSource, /statorWidths\.toothWidthAtYokeMm/);
assert.match(motorThreeSource, /function shoedToothShape/);
assert.match(motorThreeSource, /config\.stator\.tooth_shoe_enabled/);
assert.match(motorThreeSource, /statorWidths\.boreToothWidthMm - 2 \* shoeOverhang/);
assert.match(motorThreeSource, /coilBoreRadius = shoulderRadius/);
assert.match(motorThreeSource, /coilToothHalfInner = shoulderHalf/);
assert.match(motorThreeSource, /toothShape = taperedToothShape/);
assert.match(motorThreeSource, /registerRadialExplosion/);
assert.match(motorThreeSource, /displayedExplosion/);
assert.match(motorThreeSource, /crossSectionCameraPosition/);
const rotorFaceTextureBlock = motorThreeSource.match(/function makeRotorFaceTexture[\s\S]*?\n}/)?.[0] ?? '';
assert.match(rotorFaceTextureBlock, /const gridStep = 24/);
assert.match(rotorFaceTextureBlock, /context\.moveTo\(position, 0\)/);
assert.match(rotorFaceTextureBlock, /context\.moveTo\(0, position\)/);
assert.doesNotMatch(rotorFaceTextureBlock, /context\.arc\(/);
assert.match(motorThreeSource, /\[materials\.rotor, materials\.rotorFace, materials\.rotorFace\]/);
assert.match(motorThreeSource, /let fullExplosionAutoFitApplied = false/);
assert.match(motorThreeSource, /normalized > 0\.92 && !fullExplosionAutoFitApplied/);
assert.match(motorThreeSource, /fullExplosionAutoFitApplied = true/);
assert.match(motorCanvasSource, /inter_pole_air\|ipm_pocket/);
assert.match(motorCanvasSource, /export type PublicMagnetPolarityView = 'dominant' \| 'split'/);
assert.match(motorCanvasSource, /magnetPolarityView === 'split'/);
assert.match(workspaceSource, /aria-label="Magnet polarity display"/);
assert.match(workspaceSource, /public-winding-key/);
assert.match(workspaceSource, /⊙ out · ⊗ in/);
assert.match(workspaceSource, /useState<PublicCanvasLayer>\('none'\)/);
assert.doesNotMatch(workspaceSource, /setCanvasLayer\('dimensions'\)/);
assert.match(workspaceSource, /'Dominant pole'/);
assert.match(workspaceSource, /'Split view'/);
assert.match(workspaceSource, /useState<PublicMagnetPolarityView>\('dominant'\)/);
assert.match(workspaceSource, /The FEM magnet remains one region/);
assert.match(workspaceSource, /config\.topology === 'SPM'/);
assert.match(motorCanvasSource, /computeSpmMagnetPolarityHalves/);
assert.match(motorCanvasSource, /isSpmMagnet \|\| isVShapeMagnet/);
assert.match(motorThreeSource, /function vShapeMagnetPlacement/);
assert.match(motorThreeSource, /for \(const sideSign of \[1, -1\] as const\)/);
assert.match(motorThreeSource, /placement\.effectiveLengthMm/);
assert.match(motorThreeSource, /magnetUnit\.rotation\.z = placement\.axisAngleRad/);
assert.match(motorThreeSource, /publicFlatIpmMagnetCenterRadiusMm\(config\)/);
assert.doesNotMatch(motorThreeSource, /rotorRadius \* 0\.67/);
assert.match(motorThreeSource, /DEFAULT_HIDDEN_PARTS[^;]*\['endcaps'\]/);
assert.doesNotMatch(motorThreeSource, /id: 'opposite-poles', label: 'Opposite poles'/);
assert.match(motorThreeSource, /id: 'airgap', label: 'Air gap'/);
assert.match(motorThreeSource, /airgap: \[airgap\]/);
assert.ok(
  [
    "id: 'endcaps'",
    "id: 'stator'",
    "id: 'windings'",
    "id: 'airgap'",
    "id: 'magnets'",
    "id: 'rotor'",
    "id: 'bearings'",
    "id: 'shaft'",
  ].every((token, index, order) => (
    index === 0 || motorThreeSource.indexOf(order[index - 1]) < motorThreeSource.indexOf(token)
  )),
  '3D part toggles must run from the outer housing on the left to the inner rotor on the right',
);
assert.doesNotMatch(motorThreeSource, /oppositePoleBodies|hidden\.has\('opposite-poles'\)/);
assert.match(motorThreeSource, /bearings: \[driveBearingGroup, rearBearingGroup\]/);
assert.match(motorThreeSource, /shaft: \[shaftGroup\]/);
assert.match(motorThreeSource, /interface BearingAnimationRig extends HousingBuild/);
assert.match(motorThreeSource, /outerRace\.name = 'bearing-outer-race-fixed'/);
assert.match(motorThreeSource, /bearing\.innerRace\.rotation\.z = shaftAngle/);
assert.match(motorThreeSource, /bearing\.cage\.rotation\.z = shaftAngle \* bearing\.cageRatio/);
assert.match(motorThreeSource, /ballSpinner\.rotation\.z = -shaftAngle \* bearing\.ballRollRatio/);
assert.match(motorThreeSource, /syncBearingKinematics\(bearingRigs, rotorGroup\.rotation\.z\)/);
assert.match(motorThreeSource, /const magnetSplitRadius = \(magnetInnerRadius \+ magnetOuterRadius\) \/ 2/);
assert.match(motorThreeSource, /sectorShape\(magnetSplitRadius, magnetOuterRadius, magnetHalfSpan\)/);
assert.match(motorThreeSource, /sectorShape\(magnetInnerRadius, magnetSplitRadius, magnetHalfSpan\)/);
assert.match(motorThreeSource, /magnetDepth \/ 2/);
assert.match(motorThreeSource, /airgapHalf\.position\.y = -sideSign \* magnetDepth \/ 4/);
assert.match(motorThreeSource, /oppositeHalf\.position\.y = sideSign \* magnetDepth \/ 4/);
assert.match(motorThreeSource, /northAtAirgap \? materials\.oppositeSouth : materials\.oppositeNorth/);
assert.doesNotMatch(motorThreeSource, /new THREE\.PlaneGeometry\(\s*placement\.effectiveLengthMm/);
assert.match(motorThreeSource, /side: THREE\.BackSide/);
assert.match(motorThreeSource, /const pocketsGroup = new THREE\.Group\(\)/);
assert.match(motorThreeSource, /rotorCoreGroup\.add\(pocketsGroup\)/);
assert.match(motorThreeSource, /const magnetAxialDepth = stackDepth \* 0\.92/);
assert.match(motorThreeSource, /const pocketAxialDepth = stackDepth \* 0\.98/);
assert.match(motorThreeSource, /placement\.effectiveLengthMm \+ pocketClearance \* 2/);
assert.match(motorThreeSource, /magnetDepth \+ pocketClearance \* 2/);
assert.match(motorThreeSource, /pocketsGroup\.add\(pocket\)/);
assert.match(motorThreeSource, /Lamination cavity and insertion clearance around the buried magnet/);
assert.match(motorThreeSource, /const airgapGeometry = annulusGeometry\(/);
assert.doesNotMatch(motorThreeSource, /new THREE\.TorusGeometry/);
assert.match(motorThreeSource, /statorGroup\.position\.z = -4\.25 \* station/);
assert.match(motorThreeSource, /windingsGroup\.position\.z = -2\.75 \* station/);
assert.match(motorThreeSource, /airgap\.position\.z = -1\.25 \* station/);
assert.match(motorThreeSource, /magnetsGroup\.position\.z = 1\.25 \* station/);
assert.match(motorThreeSource, /rotorCoreGroup\.position\.z = 2\.55 \* station/);
assert.match(motorThreeSource, /const station = stackDepth \* 1\.12 \* eased/);
const easedExplosionAt70Percent = 0.7 * 0.7 * (3 - 2 * 0.7);
const airgapToMagnetCentersAt70Percent = (1.25 - -1.25) * 1.12 * easedExplosionAt70Percent;
const airgapAndMagnetHalfDepths = (0.96 + 0.82) / 2;
assert.ok(
  airgapToMagnetCentersAt70Percent - airgapAndMagnetHalfDepths >= 1.2,
  'air gap and magnets must have at least 120% stack-depth clearance by 70% explode',
);
assert.match(styleSource, /public-viewport-stage-3d/);
assert.match(styleSource, /public-design-intro-status/);
assert.match(workspaceSource, /<MaterialAssignmentStrip/);
assert.match(workspaceSource, /<MaterialBehaviorView/);
assert.match(workspaceSource, /'assignment', 'Assignment'/);
assert.match(workspaceSource, /'behavior', 'Behavior'/);
assert.match(workspaceSource, /const showPlayback = mode === 'geometry'[\s\S]*viewportMode === '2d' \|\| viewportMode === '3d'/);
assert.match(workspaceSource, /showPlayback && <span className="vc-group public-playback"/);
assert.match(workspaceSource, /nextMode === 'materials' \|\| nextMode === 'layout'\) setIsAnimating\(false\)/);
assert.doesNotMatch(workspaceSource, /public-material-view-card/);
assert.match(materialWorkspaceSource, /Material assignment/);
assert.match(materialWorkspaceSource, /Select an assignment to highlight it in the motor/);
assert.match(materialWorkspaceSource, /Static nonlinear B–H curve/);
assert.match(materialWorkspaceSource, /knee ·/);
assert.match(materialWorkspaceSource, /solver extrapolation/);
assert.match(materialWorkspaceSource, /Source table: 0–\{chart\.sourceLimitPoint\?\.\[1\]\.toFixed\(2\)\} T/);
assert.match(materialWorkspaceSource, /effective μr/);
assert.match(materialWorkspaceSource, /No hysteresis loop/);
assert.match(materialWorkspaceSource, /Generic Steinmetz loss estimate/);
assert.match(materialWorkspaceSource, /linear recoil approximation/);
assert.match(materialWorkspaceSource, /No demagnetization check/);
assert.match(materialWorkspaceSource, /Current out of plane/);
assert.match(materialWorkspaceSource, /Current into plane/);
assert.match(materialWorkspaceSource, /\[168, 88\], \[192, 88\]/);
assert.match(materialWorkspaceSource, /\[168, 160\], \[192, 160\]/);
assert.match(materialWorkspaceSource, /Applied-current regions · no B–H curve/);
assert.match(materialWorkspaceSource, /CONTINUOUS STATOR YOKE/);
assert.match(materialWorkspaceSource, /SHARED TOOTH/);
assert.match(materialWorkspaceSource, /SLOT OPENING/);
assert.match(materialWorkspaceSource, /outer yoke and bore-facing surface are drawn as concentric arcs/);
assert.match(materialWorkspaceSource, /M30 32 Q280 -12 530 32 L505 222 Q280 178 55 222 Z/);
assert.match(materialWorkspaceSource, /openings face the air gap \/ rotor/);
assert.match(materialWorkspaceSource, /neighboring slots on either side[\s\S]*of one shared tooth/);
assert.doesNotMatch(materialWorkspaceSource, /M80 55 C180 55 160 205/);
assert.match(materialWorkspaceSource, /Model hash/);
assert.match(styleSource, /\.public-material-assignment-strip/);
assert.match(styleSource, /\.public-material-assignment-grid \{[^}]*repeat\(4, minmax\(0, 1fr\)\)/s);
assert.match(styleSource, /\.public-material-behavior-view/);
// The Layout view moved out of CoilEmWorkspace into its own component, so assert
// the new wiring: the workspace mounts it, and the view still names itself and
// draws the two things only it can show — the slot strip and the parallel paths.
assert.match(workspaceSource, /<WindingLayoutView/);
assert.match(workspaceSource, /public-viewport-expand/);
assert.match(workspaceSource, /Expand motor view/);
assert.match(workspaceSource, /Restore side panels/);
assert.match(workspaceSource, /is-viewport-expanded/);
assert.match(workspaceSource, /solveViewportExpanded/);
assert.match(workspaceSource, /expandControl=/);
assert.match(windingLayoutSource, /cond\.\/slot/);
assert.match(windingLayoutSource, /turns\/path/);
assert.match(windingLayoutSource, /className="wl-paths-info"/);
assert.match(windingLayoutSource, /How the solver reads this/);
assert.match(windingLayoutSource, /Winding layout/);
assert.match(windingLayoutSource, /wl-slots/);
assert.match(windingLayoutSource, /Parallel paths/);
assert.match(workspaceSource, /public-component-detail-card/);
assert.match(workspaceSource, /Selected component/);
assert.match(workspaceSource, /public-component-canvas-label/);
assert.match(workspaceSource, /public-design-edit-toast/);
assert.match(workspaceSource, /onUndoDesignEdit/);
assert.match(workspaceSource, /onComponentSelect=\{setSelectedComponent\}/);
assert.match(workspaceSource, /value=\{searchQuery\}/);
assert.match(workspaceSource, /onMeshSettingChange\('mesh_density', choice\.value\)/);
assert.match(workspaceSource, /checked=\{config\.solve_params\.corner_refinement\}/);
assert.match(workspaceSource, /onMeshSettingChange\('corner_refinement', event\.target\.checked\)/);
assert.doesNotMatch(workspaceSource, /defaultChecked/);
assert.match(workspaceSource, /onSolvePlanChange\(plan\.value\)/);
assert.match(workspaceSource, />Custom\.\.\.<\/span>/);
assert.match(workspaceSource, /label="Step Size \(° elec\)"/);
assert.match(workspaceSource, /PUBLIC_CUSTOM_SWEEP_DEFAULT_STEP_DEG/);
assert.match(workspaceSource, /360° electrical sweep/);
assert.doesNotMatch(workspaceSource, /EMF \+ THD/);
assert.match(workspaceSource, /className="public-custom-sweep-estimate" aria-live="polite"/);
assert.match(styleSource, /\.public-custom-sweep-body \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\) minmax\(118px, \.95fr\)/);
assert.match(workspaceSource, /\(recoveryTarget \?\? advancedOptionsRef\.current\)\?\.scrollIntoView/);
assert.match(workspaceSource, /block: recoveryTarget \? 'center' : 'start'/);
assert.match(workspaceSource, /ref=\{advancedOptionsRef\} className="public-advanced-options"/);
assert.match(modelSource, /SolveQuality = 'quick' \| 'standard' \| 'fine' \| 'custom'/);
assert.match(workspaceSource, /label: 'Preview'/);
assert.match(workspaceSource, /label: 'Standard'/);
assert.match(workspaceSource, /label: 'High accuracy'/);
assert.match(workspaceSource, /recommended: true/);
assert.match(workspaceSource, /meshLabel: 'Coarse mesh'/);
assert.match(workspaceSource, /meshLabel: 'Medium mesh'/);
assert.match(workspaceSource, /meshLabel: 'Fine mesh'/);
assert.match(workspaceSource, /onSolveSettingChange\('current_amplitude_A', value\)/);
assert.match(workspaceSource, /onSolveSettingChange\('rated_speed_rpm', value\)/);
assert.match(workspaceSource, /public-advanced-section public-advanced-mesh-section/);
assert.match(workspaceSource, /public-advanced-section public-advanced-controls-section/);
assert.match(workspaceSource, /public-advanced-section public-advanced-output-section/);
assert.match(workspaceSource, /public-advanced-body[\s\S]*?Mesh preparation[\s\S]*?Electromagnetic controls[\s\S]*?Generated outputs[\s\S]*?<\/details>/);
assert.doesNotMatch(workspaceSource, /public-advanced-fixed/);
assert.doesNotMatch(workspaceSource, /<span>Solver<\/span><strong>Magneto2D<\/strong>/);
assert.match(workspaceSource, /public-output-chips/);
assert.match(workspaceSource, /Three-phase back EMF/);
assert.doesNotMatch(workspaceSource, /Include cogging torque sweep/);
assert.doesNotMatch(workspaceSource, />Cogging</);
assert.doesNotMatch(workspaceSource, /<SelectRow[^>]*label="Torque method"/);
assert.match(workspaceSource, /<dt>Torque method<\/dt><dd>WST<\/dd>/);
assert.match(workspaceSource, /onSolveSettingChange\('nonlinear_solver'/);
assert.match(workspaceSource, /Picard \(recommended\)/);
assert.match(workspaceSource, /Newton \(experimental\)/);
assert.doesNotMatch(workspaceSource, /<SelectRow[^>]*label="Linear solver"/);
assert.match(workspaceSource, /<dt>Linear solver<\/dt><dd>Direct Cholesky<\/dd>/);
assert.match(workspaceSource, /onSolveSettingChange\('current_amplitude_convention'/);
assert.match(workspaceSource, /onSolveSettingChange\('current_angle_deg'/);
assert.match(workspaceSource, /public-report-plot-tabs/);
assert.match(workspaceSource, /label: 'Phase A'/);
assert.match(workspaceSource, /label: 'Phase B'/);
assert.match(workspaceSource, /label: 'Phase C'/);
assert.match(workspaceSource, />Field map</);
assert.match(workspaceSource, /<FieldResultPlot plot=\{fieldPlot\}/);
assert.match(workspaceSource, /Field solution/);
assert.match(workspaceSource, /<SolvedFieldViewer/);
assert.match(workspaceSource, /const solveViewportSwitch = \(/);
assert.match(workspaceSource, /<SolvedFieldViewer[\s\S]*?viewControls=\{solveViewportSwitch\}[\s\S]*?config=\{config\}[\s\S]*?geometry=\{geometry\}/);
assert.match(workspaceSource, /showConfigurationLabel=\{false\}/);
assert.match(workspaceSource, /enableDesignIntro\?: boolean/);
assert.match(workspaceSource, /enableDesignIntro = true/);
assert.match(workspaceSource, /const designIntroEnabled = enableDesignIntro && mode === 'geometry'/);
assert.match(workspaceSource, /showConfigurationLabel=\{false\}[\s\S]*?enableDesignIntro=\{false\}/);
assert.equal((workspaceSource.match(/enableDesignIntro=\{false\}/g) ?? []).length, 1);
assert.match(styleSource, /\.public-solve-view-switch \{[^}]*top: 6px; left: 16px;/);
assert.doesNotMatch(styleSource, /\.public-solve-view-switch \{[^}]*left: 50%/);
assert.match(workspaceSource, /Requested linear solver/);
assert.match(workspaceSource, /Direct Cholesky/);
assert.match(workspaceSource, /Torque method/);
assert.match(modelSource, /corner_refinement: true/);
assert.match(modelSource, /solve_quality: 'standard'/);
assert.match(modelSource, /mesh_density: 'normal'/);
assert.match(modelSource, /torque_method: 'weighted_stress'/);
assert.match(modelSource, /nonlinear_solver: 'picard'/);
assert.match(modelSource, /linear_solver_preconditioner: 'direct'/);
assert.match(modelSource, /cogging_torque_waveform\?/);
assert.match(modelSource, /field_line_plot\?: PublicFieldLinePlot/);
assert.match(workspaceSource, /Geometry overlay/);
assert.match(workspaceSource, /Element edges/);
assert.match(workspaceSource, /Quality heatmap/);
assert.match(workspaceSource, /Weak elements/);
assert.match(workspaceSource, /What does element quality mean\?/);
assert.match(workspaceSource, /Triangle shape, not accuracy/);
assert.match(workspaceSource, /1 for an ideal equilateral triangle to 0 for a collapsed triangle/);
assert.match(workspaceSource, /public-quality-shape-scale/);
assert.match(workspaceSource, /role="tooltip"/);
assert.match(workspaceSource, /Required ≥/);
assert.match(workspaceSource, /Ready to run/);
assert.match(workspaceSource, /public-run-consequence/);
assert.match(workspaceSource, /public-derived-operating-point/);
assert.match(workspaceSource, /public-mesh-quality-summary/);
assert.match(workspaceSource, /open=\{analysisDetailsOpen\}/);
assert.match(workspaceSource, /open=\{elementQualityDetailsOpen\}/);
assert.match(workspaceSource, /setAnalysisDetailsOpen\(!resultAvailable\)/);
assert.match(workspaceSource, /setElementQualityDetailsOpen\(!resultAvailable\)/);
assert.match(styleSource, /\.public-run-plan-section > summary::after \{[\s\S]*?content: '▼';[\s\S]*?rotate\(-90deg\);/);
assert.match(styleSource, /\.public-run-plan-section\[open\] > summary::after \{[\s\S]*?rotate\(0\);/);
assert.match(styleSource, /\.public-advanced-options > summary::after \{[^}]*font-size: 8px;[^}]*content: '▼';[^}]*rotate\(-90deg\);/);
assert.match(styleSource, /\.public-advanced-options\[open\] > summary::after \{[^}]*rotate\(0\);/);
assert.doesNotMatch(styleSource, /\.public-advanced-options > summary::after \{[^}]*content: '⌄'/);
assert.match(styleSource, /\.public-result-metrics dd \{[^}]*color: var\(--text-primary\);[^}]*font: 800 11px/);
assert.match(styleSource, /\.public-result-metrics dd \{ font-size: 12px; \}/);
assert.match(workspaceSource, /torque_ripple_pct\)\} %/);
assert.match(workspaceSource, /back_emf_thd_pct\)\} %/);
assert.doesNotMatch(workspaceSource, /(?:torque_ripple_pct|back_emf_thd_pct)\)\}%/);
assert.doesNotMatch(workspaceSource, /Validate on run/i);
assert.doesNotMatch(workspaceSource, /Local update/);
assert.doesNotMatch(motorCanvasSource, /title="Use the mouse wheel to zoom; drag to pan when zoomed"/);
assert.match(meshQualitySource, /2 \* Math\.sqrt\(3\) \* doubledArea/);
assert.match(meshQualitySource, /min_quality_threshold/);
assert.doesNotMatch(motorCanvasSource, /\[\.\.\.meshHitsRef\.current\]\.reverse\(\)/);
assert.match(motorCanvasSource, /displayMode === 'problems'/);
assert.match(fieldResultSource, /Flux-density field map/);
assert.match(fieldResultSource, />Heatmap</);
assert.match(fieldResultSource, />Field lines</);
assert.match(fieldResultSource, /public-field-result-airgap-overlay/);
assert.match(fieldResultSource, /hasAirgapOverlay/);
assert.match(fieldResultSource, /prepareMagnetOverlay/);
assert.match(fieldResultSource, /public-field-result-magnet is-/);
assert.match(fieldResultSource, /public-field-result-magnet-label/);
assert.match(fieldResultSource, /deriveMagneticPolarityCues\(statorPolarityProfile, poles, 'stator'\)/);
assert.match(fieldResultSource, /public-field-result-stator-pole is-/);
assert.match(fieldResultSource, /public-field-result-pm-overlay.*is-reference/);
assert.match(fieldResultSource, /Letter inside magnet · inactive PM/);
assert.match(fieldResultSource, /Color badge · stator pole/);
assert.match(fieldResultSource, /\{cue\.label\}ₛ/);
assert.match(fieldResultSource, /<rect x=\{x - 2\.2\} y=\{y - 1\.45\} width="4\.4" height="2\.9" rx="1\.1" \/>/);
assert.match(fieldResultSource, /useViewportNavigation/);
assert.match(fieldResultSource, /ViewportNavigationControls/);
assert.match(fieldResultSource, /public-viewport-navigation-content/);
assert.match(fieldResultSource, /public-field-result-overlay-world/);
assert.match(fieldResultSource, /Math\.min\(FIELD_RASTER_SIZE \/ viewWidth, FIELD_RASTER_SIZE \/ viewHeight\)/);
assert.match(fieldResultSource, /sampleDirectionCues/);
assert.match(fieldResultSource, /segment_bx_t/);
assert.match(fieldResultSource, /segment_by_t/);
assert.match(fieldResultSource, /public-field-direction-cue/);
assert.match(fieldResultSource, /Math\.atan2\(-cue\.dy, cue\.dx\)/);
assert.match(fieldResultSource, /Waiting for samples|Completed Magneto2D solution/);
assert.match(fieldResultSource, /visibleLayerLabel/);
assert.match(fieldResultSource, /probeEnabled\?: boolean/);
assert.match(fieldResultSource, /\|\| !probeEnabled/);
assert.match(solvedFieldSource, /probeEnabled=\{!playing && Boolean\(exactVectorPlot\)\}/);
assert.match(solvedFieldSource, /disabled=\{!densityAdjustable\}/);
assert.match(solvedFieldSource, /Playback uses medium field-line density/);
assert.match(materialWorkspaceSource, /<MaterialCurveChart key=\{model\.id\} model=\{model\}/);
assert.match(styleSource, /\.public-field-result-base \{[^}]*stroke: rgba\(255,255,255,\.018\)/s);
assert.match(styleSource, /\.public-field-result-line \{[^}]*stroke: #ffd166[^}]*stroke-width: \.28[^}]*opacity: 1[^}]*drop-shadow\(0 0 \.45px rgba\(255,145,0,\.9\)\)/s);
assert.match(styleSource, /\.public-field-result-magnet\.is-north \{ fill: #ef4444; \}/);
assert.match(styleSource, /\.public-field-result-magnet\.is-south \{ fill: #3b82f6; \}/);
assert.match(styleSource, /\.public-field-result-magnet-label \{[^}]*stroke-width: \.07;[^}]*font-size: 2px;[^}]*font-weight: 750;/s);
assert.match(styleSource, /\.public-field-result-stator-pole\.is-north rect \{ fill: rgba\(127,29,29,\.86\); stroke: #fb7185; \}/);
assert.match(styleSource, /\.public-field-result-stator-pole\.is-south rect \{ fill: rgba\(30,58,138,\.86\); stroke: #60a5fa; \}/);
assert.match(styleSource, /\.public-field-result-pm-overlay\.is-reference \{ opacity: \.4; \}/);
assert.match(styleSource, /\.public-field-result-stator-pole rect \{[^}]*stroke-width: \.16;[^}]*vector-effect: non-scaling-stroke;/s);
assert.match(styleSource, /\.public-field-pole-legend \{/);
assert.match(solvedFieldSource, /<details className="public-field-summary">[\s\S]*?<summary>Field details<\/summary>[\s\S]*?className="public-field-summary-panel"/);
assert.doesNotMatch(solvedFieldSource, /<details className="public-field-summary" open/);
assert.match(styleSource, /\.public-field-summary \{[^}]*position: absolute[^}]*left: 0;[^}]*pointer-events: auto;/s);
assert.match(styleSource, /\.public-field-summary > summary \{[^}]*border-radius: 0 999px 999px 0;/s);
assert.match(styleSource, /\.public-field-summary-panel \{[^}]*border-left: 2px solid var\(--accent-primary\)/s);
assert.match(styleSource, /\.public-field-direction-cue path \{/);
assert.match(styleSource, /@keyframes public-field-direction-flow/);
assert.match(styleSource, /animation: public-field-direction-flow 2\.2s ease-in-out infinite/);
assert.match(styleSource, /\.public-solved-field-toolbar \{[^}]*grid-template-columns: auto minmax\(0,1fr\) auto/s);
assert.match(styleSource, /\.public-solved-field-toolbar \.public-solve-view-switch,[\s\S]*?gap: 5px; padding: 0; border: 0; background: transparent;/);
assert.match(styleSource, /\.public-solved-field-toolbar \.public-solve-view-switch button,[\s\S]*?border-radius: 999px; background: rgba\(10,12,17,\.62\);/);
assert.match(styleSource, /\.public-solved-field-toolbar \.public-field-source-controls button::before \{[^}]*border-radius: 50%;[^}]*content: '';/);
assert.match(styleSource, /\.public-solved-field-toolbar \.public-field-source-controls button\[aria-pressed="true"\]::before \{[^}]*background: var\(--text-accent\);/);
assert.match(styleSource, /\.public-solved-field-toolbar \.public-field-source-controls button strong \{ font-weight: 600; \}/);
assert.match(styleSource, /\.public-solved-field-toolbar \.public-field-layer-controls button > i \{[^}]*border-radius: 50%;/);
assert.match(styleSource, /\.public-solved-field-toolbar \.public-field-layer-controls button\[aria-pressed="true"\] > i \{[^}]*background: var\(--text-accent\);[^}]*box-shadow: none;/);
assert.match(styleSource, /\.public-solved-field-canvas \.public-field-result-canvas > canvas \{ position: absolute; inset: 0; \}/);
assert.match(fieldResultSource, /className="is-mid">\{\(\(displayMinB \+ displayMaxB\) \/ 2\)\.toFixed\(3\)\}/);
assert.match(styleSource, /\.public-solved-field-canvas \.public-field-result-legend \{[^}]*top: 112px[^}]*right: 0[^}]*bottom: 18px[^}]*width: 10px/s);
assert.match(styleSource, /\.public-solved-field-canvas \.public-field-result-legend > span \{[^}]*position: absolute[^}]*right: 14px/s);
assert.match(styleSource, /\.public-solved-field-canvas \.public-field-result-legend \.is-min \{ bottom: 0; \}/);
assert.match(styleSource, /\.public-solved-field-canvas \.public-field-result-legend \.is-mid \{ top: 50%; transform: translateY\(-50%\); \}/);
assert.match(styleSource, /\.public-solved-field-canvas \.public-field-result-legend \.is-max \{ top: 0; \}/);
assert.match(styleSource, /\.public-solved-field-canvas \.public-field-result-legend small \{ display: none; \}/);
assert.match(styleSource, /\.public-solved-field-canvas \.public-field-result-legend i \{[^}]*position: absolute[^}]*inset: 0[^}]*background-color: #1b8eb7[^}]*linear-gradient\(to top/s);
assert.match(styleSource, /\.public-field-range-control \{/);
assert.match(styleSource, /\.public-field-probe \{/);
assert.match(styleSource, /@container \(max-width: 1040px\)/);
assert.doesNotMatch(styleSource, /\.public-solved-field-viewer:has\(\.public-field-layer-menu\[open\]\) \.public-viewport-nav-controls/);
assert.doesNotMatch(styleSource, /\.public-solved-field-viewer:has\(\.public-field-layer-menu\[open\]\) \.public-field-result-legend/);
assert.match(styleSource, /@container \(max-width: 720px\)/);
assert.match(solvedFieldSource, />Resultant</);
assert.match(solvedFieldSource, />PM only</);
assert.match(solvedFieldSource, />Stator only</);
assert.match(solvedFieldSource, />Flux density</);
assert.match(solvedFieldSource, />Airgap</);
assert.match(solvedFieldSource, />Field lines</);
assert.match(solvedFieldSource, /'PM reference' : 'Magnets'/);
assert.match(solvedFieldSource, />Pole labels</);
assert.match(solvedFieldSource, /fieldLineDensity/);
assert.match(solvedFieldSource, /Line density/);
assert.match(solvedFieldSource, /FIELD_LINE_DENSITY_STOPS/);
assert.match(solvedFieldSource, /type="range"[\s\S]*?aria-label="Field-line density"/);
assert.match(solvedFieldSource, /<span>Low<\/span><span>Med<\/span><span>High<\/span>/);
assert.match(solvedFieldSource, /\{showFieldLines && renderDensityControl\(\)\}/);
assert.match(solvedFieldSource, /\{showFieldLines && renderDensityControl\(true\)\}/);
assert.doesNotMatch(solvedFieldSource, /<select[^>]*Field-line density/);
assert.match(solvedFieldSource, /showAirgap=\{showAirgap\}/);
assert.match(solvedFieldSource, /airgapInnerRadiusMm=\{rotorAirgapBoundaryRadiusMm\(config\)\}/);
assert.match(solvedFieldSource, /showMagnetPolarityLabels=\{showPoleLabels\}/);
assert.match(solvedFieldSource, /colorRangeMode=\{colorRangeMode\}/);
assert.match(solvedFieldSource, /fieldPlaybackSweepMaxT\(playbackFrames, source\)/);
assert.match(fieldResultSource, />\s*Sweep\s*<\/button>/);
assert.match(fieldResultSource, /All solved rotor positions/);
assert.match(fieldResultSource, />\s*View\s*<\/button>/);
assert.match(fieldResultSource, /fieldRangeForViewport\(prepared\.triangleRecords/);
assert.match(fieldResultSource, /Visible zoomed viewport/);
assert.match(solvedFieldSource, /describeProbe=\{describeProbe\}/);
assert.match(fieldResultSource, /element_bx_t/);
assert.match(fieldResultSource, /element_by_t/);
assert.match(solvedFieldSource, /viewControls: ReactNode/);
assert.match(solvedFieldSource, /\{viewControls\}/);
assert.match(solvedFieldSource, /className="public-field-layer-menu"/);
assert.match(solvedFieldSource, /className="public-field-playback-meta"/);
assert.match(solvedFieldSource, /className="public-field-physics-info"/);
assert.match(solvedFieldSource, /Solving the zero-remanence rotor sweep locally/);
assert.match(solvedFieldSource, /className="public-field-stream-status"/);
assert.match(solvedFieldSource, /Live Magneto2D stator field/);
assert.match(solvedFieldSource, /Previous resultant field · waiting for first stator frame/);
assert.match(styleSource, /\.public-field-stream-status/);
assert.doesNotMatch(solvedFieldSource, /className="public-field-loading-visual"/);
assert.doesNotMatch(styleSource, /public-field-loading-spin/);
assert.doesNotMatch(solvedFieldSource, /className="public-field-physics-note"/);
assert.match(solvedFieldSource, /showMagnets=\{showMagnets\}/);
assert.match(solvedFieldSource, /magnetReference=\{source === 'armature'\}/);
assert.match(solvedFieldSource, /showPolarityLegend=\{source === 'armature' && showPoleLabels\}/);
assert.match(solvedFieldSource, /showStatorPolarity=\{source === 'armature' && showPoleLabels\}/);
assert.match(solvedFieldSource, /nearestAirgapProfile/);
assert.match(solvedFieldSource, /armature\?\.airgap_profiles \?\? \[\]/);
assert.match(solvedFieldSource, /airgap_brbt: airgapProfile\?\.airgap_brbt \?\? solvedFrame\?\.airgap_brbt \?\? null/);
assert.match(solvedFieldSource, /const statorPolarityRotationDeg = source === 'armature'/);
assert.match(solvedFieldSource, /\? -mechanicalAngleDeg/);
assert.match(solvedFieldSource, /statorPolarityRotationDeg=\{statorPolarityRotationDeg\}/);
assert.match(fieldResultSource, /cue\.angleDeg \+ statorPolarityRotationDeg/);
assert.match(solvedFieldSource, /Solved rotor position/);
assert.match(solvedFieldSource, /setPlaying/);
assert.match(solvedFieldSource, /retainedPlot/);
assert.match(solvedFieldSource, /frameRequestsRef/);
assert.match(solvedFieldSource, /warmFieldResultPlot/);
assert.match(solvedFieldSource, /requestIdleCallback/);
assert.match(solvedFieldSource, /publicFieldPlaybackBufferFrames/);
assert.match(solvedFieldSource, /publicFieldPlaybackCacheFrames/);
assert.match(solvedFieldSource, /playbackLookaheadFrameIndices/);
assert.match(solvedFieldSource, /IDLE_BUFFER_FRAMES/);
assert.match(playbackTimingSource, /return publicFieldPlaybackBufferFrames\(rpm\) \+ 1/);
assert.match(solvedFieldSource, /const angleFrames = resultantFrames\.length > 0 \? resultantFrames : armatureFrames/);
assert.match(solvedFieldSource, /const streamingArmatureFrame = source === 'armature' && armatureBusy/);
assert.match(solvedFieldSource, /const electricalAngleDeg = streamingArmatureFrame\?\.angle_deg/);
assert.doesNotMatch(solvedFieldSource, /counterclockwisePlaybackFrames|frames\.slice\(1\)\.reverse\(\)|solvedElectricalAngleDeg - 360/);
assert.match(solvedFieldSource, /Play field clockwise/);
assert.match(solvedFieldSource, /<small>Electrical<\/small>/);
assert.match(solvedFieldSource, /CW · \{bufferStatus\}/);
assert.doesNotMatch(solvedFieldSource, /MAX_CACHED_FRAMES/);
assert.match(solvedFieldSource, /window\.requestAnimationFrame\(animate\)/);
assert.match(solvedFieldSource, /advancePlaybackElectricalAngle/);
assert.match(solvedFieldSource, /nearestPlaybackFrameIndex/);
assert.match(solvedFieldSource, /playbackCycleSpanDeg/);
assert.match(solvedFieldSource, /normalizePlaybackElectricalAngle/);
assert.match(solvedFieldSource, /playbackSliderRef\.current\.value/);
assert.match(solvedFieldSource, /step="any"/);
assert.match(solvedFieldSource, /for \(const preloadIndex of playbackLookaheadIndices\)/);
assert.match(solvedFieldSource, /Playback speed \(RPM\)/);
assert.doesNotMatch(solvedFieldSource, /PLAYBACK_RATES|PlaybackRate|Field playback speed/);
assert.match(playbackTimingSource, /PUBLIC_FIELD_PLAYBACK_MIN_RPM = 1/);
assert.match(playbackTimingSource, /PUBLIC_FIELD_PLAYBACK_MAX_RPM = 100/);
assert.match(playbackTimingSource, /PUBLIC_FIELD_PLAYBACK_DEFAULT_RPM = 18/);
assert.match(playbackTimingSource, /PUBLIC_FIELD_PLAYBACK_PRESENTATION_FPS = 60/);
assert.match(playbackTimingSource, /if \(rpm >= 60\) return 14/);
assert.match(playbackTimingSource, /if \(rpm >= 15\) return 10/);
assert.match(solvedFieldSource, /const cacheLimit = publicFieldPlaybackCacheFrames\(playbackRpm\)/);
assert.match(styleSource, /\.public-field-playback-rpm/);
assert.match(styleSource, /\.public-field-playback \{[^}]*grid-template-columns: 38px minmax\(180px,1fr\) 176px minmax\(238px,auto\) 28px/);
assert.match(styleSource, /\.public-field-playback-rpm \{[^}]*min-height: 38px/);
assert.match(styleSource, /\.public-field-playback-meta \{[^}]*display: grid[^}]*grid-template-columns: auto auto/);
assert.match(styleSource, /\.public-field-position-control > span,/);
assert.match(solvedFieldSource, /Buffering next frame/);
assert.match(solvedFieldSource, /DETAIL_VIEWPORT_SCALE/);
assert.match(solvedFieldSource, /detailRequestRef/);
assert.match(solvedFieldSource, /replaceDetailRaster/);
assert.match(solvedFieldSource, /renderDetail\(source, descriptor\.playback_frame\)/);
assert.match(solvedFieldSource, /Prefer exact solver vectors for a stopped, zoomed frame/);
assert.match(solvedFieldSource, /loadNumericalDetail\(\)\.then/);
assert.match(solvedFieldSource, /loadedNumericalDetail \|\| detailRequestRef\.current !== requestId/);
assert.match(solvedFieldSource, /highResolutionPlot=\{exactVectorPlot\}/);
assert.match(solvedFieldSource, /onViewportScaleSettled=\{setFieldViewportScale\}/);
assert.match(fieldResultSource, /preparedFieldPlotCache/);
assert.match(fieldResultSource, /cachedFieldPlot/);
assert.match(fieldResultSource, /FIELD_RASTER_SIZE/);
assert.match(fieldResultSource, /DETAIL_RENDER_SCALE/);
assert.match(fieldResultSource, /useVectorDetail/);
assert.match(fieldResultSource, /baseScale \* navigation\.scale/);
assert.match(fieldResultSource, /navigation\.pan\.x \* pixelRatio/);
assert.match(fieldResultSource, /onViewportScaleSettled/);
assert.match(fieldResultSource, /context\.imageSmoothingQuality = 'high'/);
assert.match(fieldResultSource, /canvas\.dataset\.renderMode = 'vector-detail'/);
assert.match(fieldResultSource, /\? 'detail-raster'/);
assert.match(fieldResultSource, /renderedLayers/);
assert.match(fieldResultSource, /context\.drawImage/);
assert.match(motorCanvasSource, /useViewportNavigation/);
assert.match(motorCanvasSource, /ViewportNavigationControls/);
assert.match(motorCanvasSource, /navigation\.scale/);
assert.match(motorCanvasSource, /navigation\.pan\.x/);
assert.match(viewportNavigationSource, /onWheel/);
assert.match(viewportNavigationSource, /Math\.exp\(-event\.deltaY \* 0\.0012\)/);
assert.match(viewportNavigationSource, /setPointerCapture/);
assert.match(viewportNavigationSource, /releasePointerCapture/);
assert.match(viewportNavigationSource, /PAN_UNLOCK_SCALE/);
assert.match(viewportNavigationSource, /const MIN_SCALE = 0\.5/);
assert.match(viewportNavigationSource, /const DEFAULT_SCALE = 1/);
assert.match(viewportNavigationSource, /useState\(DEFAULT_SCALE\)/);
assert.match(viewportNavigationSource, /setScale\(DEFAULT_SCALE\)/);
assert.match(viewportNavigationSource, /anchor\.x - \(anchor\.x - current\.x\) \* ratio/);
assert.match(viewportNavigationSource, /fitSubject = 'motor'/);
assert.match(viewportNavigationSource, /Fit \$\{fitSubject\} to view/);
assert.match(styleSource, /\.public-viewport-navigation\.is-pannable \{ cursor: grab; \}/);
assert.match(styleSource, /\.public-viewport-nav-controls \{/);
assert.match(styleSource, /\.public-coilem-shell \.design-workspace\.is-viewport-expanded \{[^}]*padding: 0;/);
assert.match(styleSource, /\.public-coilem-shell \.design-workspace\.is-viewport-expanded \.public-parameter-panel,[\s\S]*?\.design-workspace-health \{ display: none; \}/);
assert.match(styleSource, /\.public-solve-workspace\.is-viewport-expanded \.public-solve-setup,[\s\S]*?\.public-run-plan \{ display: none; \}/);
assert.match(styleSource, /\.design-workspace\.is-viewport-expanded \.public-3d-part-toggles,[\s\S]*?\.public-solve-workspace\.is-viewport-expanded \.public-3d-part-toggles \{[\s\S]*?top: 16px;[\s\S]*?left: 112px;/);
assert.match(styleSource, /\.public-viewport-expand \{/);
assert.match(styleSource, /\.public-motor-viewport \.viewport-bottom-bar \{[^}]*bottom: 0;/);
assert.match(styleSource, /\.public-winding-layout \.wl-scroll,[\s\S]*?width: min\(100%, 1180px\);[\s\S]*?margin-inline: auto;/);
assert.match(styleSource, /\.public-winding-layout \.wl-strip \{[^}]*margin-inline: auto;/);
assert.match(styleSource, /\.public-winding-layout \.wl-chips \{[^}]*flex: 1 0 100%;[^}]*flex-wrap: nowrap;/);
assert.match(styleSource, /\.public-winding-layout \.wl-paths-content \{[^}]*flex-wrap: wrap;/);
assert.match(styleSource, /\.public-winding-layout \.wl-paths-info \{[^}]*max-width: 240px;/);
assert.match(styleSource, /\.public-winding-layout \.wl-phase-row \{[^}]*justify-content: center;/);
assert.match(playbackRasterizerSource, /navigator\.hardwareConcurrency/);
assert.match(playbackRasterizerSource, /new Worker\(new URL\('\.\/fieldPlaybackWorker\.ts'/);
assert.match(playbackRasterizerSource, /\/solve\/playback-frame\//);
assert.match(playbackRasterizerSource, /createImageBitmap/);
assert.match(playbackRasterizerSource, /renderRasterLayers/);
assert.match(playbackRasterizerSource, /renderDetail/);
assert.match(playbackRasterizerSource, /composition\.detail/);
assert.match(playbackRasterizerSource, /vectorCues: composition\.vector_cues \?\? \[\]/);
assert.match(playbackWorkerSource, /new OffscreenCanvas/);
assert.match(playbackWorkerSource, /const MEDIUM_CONTOUR_LEVEL_STRIDE = 2/);
assert.match(playbackWorkerSource, /index % MEDIUM_CONTOUR_LEVEL_STRIDE === 0/);
assert.match(playbackWorkerSource, /segment_bx_t/);
assert.match(playbackWorkerSource, /segment_by_t/);
assert.match(playbackWorkerSource, /vectorCues/);
assert.match(playbackWorkerSource, /transferToImageBitmap/);
assert.match(playbackWorkerSource, /Field frame request failed with HTTP/);
assert.doesNotMatch(playbackWorkerSource, /synthetic|interpolat/i);
assert.match(modelSource, /coilem\.field_playback\.v1/);
assert.match(modelSource, /coilem\.field_playback\.v2/);
assert.match(modelSource, /layered-webp-v1/);
assert.match(modelSource, /layered-raster-v1/);
assert.match(solvedFieldSource, /playbackDescriptors/);
assert.match(solvedFieldSource, /normalizeFieldPlaybackManifest/);
assert.match(playbackContractSource, /NormalizedFieldPlaybackSequence/);
assert.match(playbackContractSource, /manifest\.schema_version === 'coilem\.field_playback\.v1'/);
assert.match(playbackContractSource, /manifest\.schema_version !== 'coilem\.field_playback\.v2'/);
assert.match(playbackContractSource, /layerIdForRole\(layers, 'geometry'\)/);
assert.match(playbackContractSource, /layerIdForRole\(layers, 'scalar'\)/);
assert.match(playbackContractSource, /layerIdForRole\(layers, 'contours'\)/);
assert.match(playbackContractSource, /visual\.detail_layers/);
assert.match(playbackContractSource, /manifest\.numerical_snapshots\.length === manifest\.frames\.length/);
assert.match(playbackContractSource, /numerical_artifact: numericalSnapshots\[index\]/);
assert.match(solvedFieldSource, /frame\.numerical_artifact\?\.artifact_id \?\? composition\.base\.artifact_id/);
assert.doesNotMatch(playbackContractSource, /synthetic|interpolat/i);
assert.match(modelSource, /magneto2d_exact_br_zero/);
assert.match(solvedFieldSource, /Loading solved field frame/);
assert.match(apiSource, /getPublicFieldFrame/);
assert.match(apiSource, /runPublicArmatureField/);
assert.match(apiSource, /streamPublicArmatureField/);
assert.match(apiSource, /\/solve\/field-composition\/armature\/stream/);
assert.match(waveformSource, /export interface WaveformSeries/);
assert.match(motorCanvasSource, /isRotorRegion/);
assert.match(motorCanvasSource, /windingToken/);
assert.match(motorCanvasSource, /pointInPolygon/);
assert.match(motorCanvasSource, /componentSelectionFromRegion/);
assert.match(motorCanvasSource, /rotatePoint\(point, -rotorAngleDeg\)/);
assert.match(motorCanvasSource, /const rotorAngleRad = -rotorAngleDeg \* Math\.PI \/ 180/);
assert.match(motorCanvasSource, /const rotateRotor = isRotorRegion\(region\)/);
assert.match(motorCanvasSource, /drawMesh\(\s*context,\s*mesh,\s*rect\.width,\s*rect\.height,\s*rotorAngleDeg,\s*navigation\.scale/s);
assert.match(motorCanvasSource, /const uniqueEdges = new Set<string>\(\)/);
assert.match(motorCanvasSource, /triangleEdges\.forEach/);
assert.doesNotMatch(motorCanvasSource, /edgeStride/);
assert.match(motorThreeSource, /buildWindingHarness/);
assert.match(motorThreeSource, /Star point \(wye\)/);
assert.match(motorThreeSource, /Drive lead terminal/);
assert.match(workspaceSource, /Open design file/);
assert.match(workspaceSource, /Save design file/);
assert.match(workspaceSource, /public-project-menu/);
assert.match(appSource, /parseDesignFile/);
assert.match(appSource, /cogging_torque: false/);
assert.match(appSource, /thd_analysis: thdAnalysis/);
assert.match(appSource, /solve_quality === 'standard'/);
assert.match(appSource, /solve_quality === 'fine'/);
assert.match(appSource, /saveDesignFileAs/);
assert.match(styleSource, /\.public-project-menu/);
assert.match(motorThreeSource, /OrbitControls/);
assert.match(motorThreeSource, /THREE\.Raycaster/);
assert.match(motorThreeSource, /publicMotorSelection/);
assert.match(motorThreeSource, /applyExplosion\(displayedExplosion\)/);
assert.match(motorThreeSource, /shaftGroup\.position\.z = 4\.25 \* station/);
assert.match(motorThreeSource, /rotation\.z = -rotorAngleDeg/);
assert.match(motorThreeSource, /Interactive 3D motor view/);
assert.match(motorThreeSource, /flat_buried_magnet_shape === 'legacy_arc'/);
assert.match(motorThreeSource, /Legacy curved magnet/);
assert.match(workspaceSource, /progressPercent/);
assert.match(workspaceSource, /Live solve status/);
assert.match(workspaceSource, /Waiting for samples/);
assert.match(workspaceSource, /Analysis is still running/);
assert.match(workspaceSource, /Building torque, Back-EMF, field plots/);
assert.match(workspaceSource, /Building waveform from solved fields/);
assert.match(workspaceSource, /BackEMFHarmonicSpectrum/);
assert.match(workspaceSource, /H1–H/);
assert.match(workspaceSource, /Line AB THD H12/);
assert.match(workspaceSource, /periodic no-load flux-linkage DFT/);
assert.match(workspaceSource, /progress-track\$\{finalizing \? ' indeterminate'/);
assert.match(workspaceSource, /window\.setInterval/);
assert.match(workspaceSource, /is-running/);
assert.match(solveProgressSource, /packaging_results/);
assert.match(solveProgressSource, /saving_run/);
assert.match(solveProgressSource, /solver_timing/);
assert.match(workspaceSource, /Three-phase back EMF/);
assert.match(workspaceSource, /state === 'live' \? 'Live' : 'Completed'/);
assert.match(workspaceSource, /const yTickValues = \[maxY, yMiddle, minY\]/);
assert.match(workspaceSource, /public-live-chart-y-value/);
assert.match(workspaceSource, /formatCompactAxisValue\(tickValue, ySpan\)/);
assert.match(workspaceSource, /\(\(maxY - value\) \/ ySpan\)/);
assert.doesNotMatch(workspaceSource, /Math\.max\(maxY - minY, 1\)/);
assert.match(styleSource, /\.public-live-chart svg \.public-live-chart-y-value/);
assert.match(workspaceSource, /Completed solver results/);
assert.match(workspaceSource, /Completed result plots/);
assert.match(workspaceSource, /state="complete" label="Torque"/);
assert.match(workspaceSource, /state="complete" label="Three-phase back EMF"/);
assert.doesNotMatch(workspaceSource, /state="complete" label="Cogging torque"/);
assert.match(workspaceSource, /Resize completed results panel/);
assert.match(workspaceSource, /role="separator"/);
assert.match(workspaceSource, /window\.addEventListener\('pointermove', handlePointerMove\)/);
assert.match(workspaceSource, /onKeyDown=\{handleRunPlanResizeKey\}/);
assert.match(workspaceSource, /const RUN_PLAN_ACTIVE_WIDTH = 440/);
assert.match(workspaceSource, /setRunPlanWidth\(\(currentWidth\) => Math\.max/);
assert.match(workspaceSource, /runPlanScrollRef\.current\?\.scrollTo/);
assert.match(workspaceSource, /onClick=\{busy === 'solve' \? onCancelSolve : handleStartSolve\}/);
assert.match(workspaceSource, /solveInProgress \? ' is-run-plan-focused'/);
assert.match(styleSource, /\.public-run-plan-resizer/);
assert.match(styleSource, /cursor: col-resize/);
assert.match(styleSource, /\.public-run-plan \{[\s\S]*?width \.32s cubic-bezier/);
assert.match(styleSource, /\.public-solve-workspace\.is-run-plan-focused \.public-run-plan/);
assert.match(appSource, /\['magneto2d_sweep', 'torque_sweep'\]\.includes\(nextProgress\.stage\)/);
assert.match(appSource, /setLiveSamples/);
assert.match(appSource, /const solveRequestId = useRef\(0\)/);
assert.match(appSource, /const solveResultBeforeRun = useRef<\{ value: SolveResult \| null \} \| null>\(null\)/);
assert.match(appSource, /solveResultBeforeRun\.current = \{ value: result \}/);
assert.match(appSource, /restoreSolveResultBeforeRun/);
const cancelSolveBlock = appSource.slice(
  appSource.indexOf('const cancelSolve'),
  appSource.indexOf('const reset ='),
);
assert.match(cancelSolveBlock, /solveRequestId\.current \+= 1/);
assert.match(cancelSolveBlock, /The previous completed result is still available/);
assert.match(workspaceSource, /Local backend/);
assert.doesNotMatch(workspaceSource, /Loopback API · no account required/);
assert.match(appSource, /issue\.suggestion/);
assert.match(workspaceSource, /connectionStatus === 'checking'/);
assert.match(appSource, /const \[showLanding, setShowLanding\] = useState\(true\)/);
assert.match(appSource, /<PublicLanding/);
assert.match(appSource, /const \[blankDesign, setBlankDesign\] = useState\(false\)/);
assert.match(appSource, /setDesignName\('New Design'\)/);
assert.match(appSource, /setGeometry\(null\)/);
assert.match(appSource, /workflowDisabled/);
assert.match(workspaceSource, />New Design</);
assert.match(workspaceSource, /workflowDisabled \|\| \(!step\.available && !active\)/);
assert.match(workspaceSource, /aria-label="Blank design canvas"/);
assert.match(workspaceSource, /solveAvailable=\{!props\.blankDesign\}/);
assert.match(workspaceSource, /const \[draftValue, setDraftValue\] = useState\(\(\) => String\(value\)\)/);
assert.match(workspaceSource, /onBlur=\{commitDraft\}/);
assert.match(workspaceSource, /event\.key === 'Enter'/);
assert.doesNotMatch(workspaceSource, /onChange=\{\(event\) => onChange\(Number\(event\.target\.value\)\)\}/);
assert.match(landingSource, /LandingWorkflowHero/);
if (templateSelectorSource !== null) {
  assert.match(templateSelectorSource, /LandingWorkflowHero/);
}
assert.match(landingWorkflowHeroSource, /data-active-workflow=\{workflow\}/);
assert.match(landingWorkflowHeroSource, /aria-label="Design workflow"/);
assert.match(landingWorkflowHeroSource, /aria-pressed=\{isMotor\}/);
assert.match(landingWorkflowHeroSource, /aria-pressed=\{!isMotor\}/);
assert.match(landingWorkflowHeroSource, /Electric Motor<br \/>Design,<br \/><em>Simplified<\/em>/);
assert.match(landingWorkflowHeroSource, /Halbach Array<br \/>Design,<br \/><em>Simplified<\/em>/);
assert.match(landingWorkflowHeroSource, /Motor designs/);
assert.match(landingWorkflowHeroSource, /Halbach arrays/);
assert.match(landingWorkflowHeroSource, /Landing3DPreview/);
assert.match(landingWorkflowHeroSource, /LandingHalbachPreview/);
assert.match(landingHalbachPreviewSource, /LinearHalbach3DViewer/);
assert.match(landingHalbachPreviewSource, /presentation="hero"/);
assert.match(landingHalbachPreviewSource, /LandingPreviewModeControl/);
assert.doesNotMatch(landingHalbachPreviewSource, /LIVE 3D · LINEAR ARRAY/);
assert.doesNotMatch(landingHalbachPreviewSource, /Flux focused to the \+Y side/);
assert.match(landingHalbachPreviewSource, /out_of_plane_depth: 12/);
assert.match(landingHalbachPreviewSource, /AUTO_ADVANCE_MS = 2_600/);
assert.match(landingHalbachPreviewSource, /'geometry'/);
assert.match(landingHalbachPreviewSource, /'mesh'/);
assert.match(landingHalbachPreviewSource, /'field'/);
assert.match(landingHalbachPreviewSource, /prefers-reduced-motion: reduce/);
assert.match(landingHalbachPreviewSource, /viewportMode={viewportMode}/);
assert.match(landingHalbachPreviewSource, /showFieldLines={activeMode === 'field'}/);
assert.match(landingHalbachPreviewSource, /hero_linear_halbach_mesh\.gmsh\.json/);
assert.match(landingHalbachPreviewSource, /hero_linear_halbach_field\.magneto2d\.json/);
assert.match(landingHalbachPreviewSource, /data-mesh-source={previewData\?\.mesh\.mesh_info\.mesh_source}/);
assert.match(landingHalbachPreviewSource, /showMeshOverlay={activeMode === 'field'}/);
assert.match(landingHalbachPreviewSource, /onPointerLeave=\{\(\) => setIsOrbiting\(false\)\}/);
assert.match(landingThreeSource, /LandingPreviewModeControl/);
assert.doesNotMatch(landingThreeSource, /setInterval|AUTO_ADVANCE_MS/);
assert.match(landingThreeSource, /stage\.requestFullscreen/);
assert.match(landingThreeSource, /onDoubleClick=\{handleStageDoubleClick\}/);
assert.match(landingThreeSource, /Open fullscreen motor view/);
assert.match(landingThreeSource, /aria-label="Explode motor assembly"/);
assert.match(landingThreeSource, /baseZ \+ phaseProgress \* targetOffsetZ/);
assert.match(landingThreeSource, /stator: \[0, 0\.18\][\s\S]*?windings: \[0\.18, 0\.36\][\s\S]*?airgap: \[0\.36, 0\.54\][\s\S]*?magnets: \[0\.54, 0\.72\][\s\S]*?rotor: \[0\.72, 0\.80\]/);
assert.match(landingThreeSource, /motorGroup\.scale\.setScalar\(assemblyScale\)/);
assert.match(landingThreeSource, /setLoadError\(true\);[\s\S]*?setActiveStep\(0\)/);
assert.doesNotMatch(landingThreeSource, /landing-3d-report/);
assert.doesNotMatch(linearHalbachThreeSource, /Math\.max\(320, host\.clientHeight\)/);
assert.match(linearHalbachThreeSource, /if \(width <= 0 \|\| height <= 0\) return/);
assert.match(landingPreviewModeControlSource, /label: 'Geometry'/);
assert.match(landingPreviewModeControlSource, /label: 'Mesh'/);
assert.match(landingPreviewModeControlSource, /label: 'Field'/);
assert.match(landingPreviewModeControlSource, /aria-pressed={mode\.id === activeMode}/);
assert.equal(landingHalbachMeshFixture.provenance.mesh_engine, 'Gmsh');
assert.equal(landingHalbachMeshFixture.mesh_info.mesh_source, 'gmsh_occ');
assert.equal(landingHalbachMeshFixture.mesh_info.mesh_density, 'normal');
assert.equal(landingHalbachMeshFixture.mesh_info.minimum_elements_across_magnet, 6);
assert.equal(landingHalbachMeshFixture.mesh_info.outer_padding_factor, 2.5);
assert.equal(landingHalbachMeshFixture.mesh_info.gmsh_version, '4.15.2');
assert.equal(landingHalbachMeshFixture.mesh_qa.all_triangles_mapped_once, true);
assert.equal(landingHalbachMeshFixture.mesh_qa.area_relative_error, 0);
assert.ok(landingHalbachMeshFixture.nodes_mm.length > 6_000);
assert.ok(landingHalbachMeshFixture.triangles.length > 12_000);
assert.equal(
  landingHalbachMeshFixture.regions.length,
  landingHalbachMeshFixture.triangles.length,
);
assert.match(landingHalbachMeshFixture.mesh_hash, /^[0-9a-f]{64}$/);
assert.equal(landingHalbachFieldFixture.provenance.solver, 'Magneto2D');
assert.equal(landingHalbachFieldFixture.provenance.mesh_engine, 'Gmsh');
assert.equal(
  landingHalbachFieldFixture.provenance.mesh_hash,
  landingHalbachMeshFixture.mesh_hash,
);
assert.equal(
  landingHalbachFieldFixture.provenance.problem_sha256,
  landingHalbachMeshFixture.magnetostatic_problem_sha256,
);
assert.equal(
  landingHalbachFieldFixture.field_data.element_fields_t.length,
  landingHalbachMeshFixture.triangles.length,
);
assert.equal(
  landingHalbachFieldFixture.field_data.az_nodal_t_m.length,
  landingHalbachMeshFixture.nodes_mm.length,
);
assert.equal(landingHalbachFieldFixture.field_data.contours.length, 18);
assert.ok(landingHalbachFieldFixture.working_field.b_magnitude_t.rms > 0.39);
assert.ok(landingHalbachFieldFixture.leakage_field.b_magnitude_t.rms < 0.053);
assert.match(landingWorkflowHeroSource, /Linear Halbach array preview/);
assert.match(linearHalbachThreeSource, /presentation\?: 'workspace' \| 'hero'/);
assert.match(linearHalbachThreeSource, /presentation === 'hero' \? ' is-hero-presentation'/);
assert.match(landingWorkflowHeroSource, /Design a Halbach array/);
assert.doesNotMatch(landingSource, /magnetic-applications/);
assert.doesNotMatch(halbachStyleSource, /\.magnetic-applications/);
assert.match(appSource, /<HalbachWorkspace/);
assert.match(appSource, /setShowHalbachWorkspace\(true\)/);
assert.match(halbachWorkspaceSource, /data-testid="halbach-workspace"/);
assert.match(halbachWorkspaceSource, /className="logo public-logo-button"/);
assert.match(halbachWorkspaceSource, /className="project-chip"/);
assert.match(halbachWorkspaceSource, /workflow-stepper workflow-stepper-inline/);
assert.match(halbachWorkspaceSource, /className=\{`halbach-ready-card/);
assert.match(halbachStyleSource, /--halbach-deep: var\(--bg-app/);
assert.match(halbachStyleSource, /--halbach-green: var\(--accent-primary/);
assert.match(halbachStyleSource, /\.halbach-stage-panel \{[\s\S]*var\(--bg-canvas/);
assert.match(halbachStyleSource, /\.halbach-viewport-bottom-bar/);
assert.match(halbachStyleSource, /font-family: var\(--font-family/);
assert.match(halbachWorkspaceSource, /1\. Cylinder geometry/);
assert.match(halbachWorkspaceSource, /2\. Field pattern/);
assert.match(halbachWorkspaceSource, /3\. Magnet material/);
assert.match(halbachWorkspaceSource, /4\. Sample region/);
assert.match(halbachWorkspaceSource, /5\. Advanced geometry/);
assert.match(halbachWorkspaceSource, /Show magnetization arrows/);
assert.match(halbachWorkspaceSource, /Show ROI and leakage overlays/);
assert.match(halbachWorkspaceSource, /Continue to Solve/);
assert.match(halbachWorkspaceSource, /Run Magneto2D solve/);
assert.match(halbachWorkspaceSource, /<h2>Magneto2D<\/h2>/);
assert.doesNotMatch(halbachWorkspaceSource, /Magneto2D 2D/);
assert.match(halbachWorkspaceSource, /Halbach JSON/);
assert.match(halbachWorkspaceSource, /Problem JSON/);
assert.match(halbachWorkspaceSource, /Field JSON/);
assert.match(halbachWorkspaceSource, /Samples CSV/);
assert.match(halbachWorkspaceSource, /Field SVG/);
assert.match(halbachWorkspaceSource, /Field PNG/);
assert.match(halbachWorkspaceSource, /Report PDF/);
assert.match(halbachWorkspaceSource, /B parallel/);
assert.match(halbachWorkspaceSource, /B perpendicular/);
assert.match(halbachGeometrySource, /return 2 \* segmentCenterDeg - fieldDirectionDeg/);
assert.match(halbachGeometrySource, /halbachMagnetizationAngleDeg\(/);
assert.match(halbachTwoSource, /halbachDisplaySegments\(config\)/);
assert.match(halbachTwoSource, /useViewportNavigation/);
assert.match(halbachTwoSource, /ViewportNavigationControls/);
assert.match(halbachTwoSource, /#ffd166/);
assert.match(halbachTwoSource, /segment_bx_t/);
assert.match(halbachTwoSource, /window\.devicePixelRatio.*navigation\.scale/s);
assert.match(halbachTwoSource, /new ResizeObserver\(draw\)/);
assert.match(halbachTwoSource, /fieldArrowCanvasRef/);
assert.match(halbachTwoSource, /window\.requestAnimationFrame\(draw\)/);
assert.match(halbachTwoSource, /canvas\.dataset\.animationState/);
assert.match(halbachTwoSource, /halbach-requested-field-overlay/);
assert.match(halbachTwoSource, /requestedFieldScreenRotationDeg/);
assert.match(halbachTwoSource, /requestedLabelRotationDeg > 90/);
assert.match(halbachTwoSource, /requestedLabelRotationDeg < -90/);
assert.match(halbachStyleSource, /\.halbach-requested-field-label/);
assert.match(halbachStyleSource, /--halbach-pole-north:\s*#cf4d51/);
assert.match(halbachStyleSource, /--halbach-pole-south:\s*#3978ad/);
assert.match(halbachStyleSource, /\.halbach-pole-legend/);
assert.match(halbachTwoSource, /showTwoTonePoles/);
assert.match(halbachTwoSource, /halbachWedgeCentroid\(/);
assert.match(halbachTwoSource, /red = N face/);
assert.match(halbachTwoSource, /blue = S face/);
assert.match(halbachThreeSource, /clipHalbachPoleHalf\(/);
assert.match(halbachThreeSource, /poleHalves/);
assert.match(halbachThreeSource, /red = N face/);
assert.match(halbachThreeSource, /blue = S face/);
assert.match(halbachPoleRenderingSource, /halbachWedgeCentroid/);
assert.match(halbachPoleRenderingSource, /normal\[0\] \* \(point\[0\] - origin\[0\]\)/);
assert.match(halbachWorkspaceSource, /Halbach visualization mode/);
assert.match(halbachWorkspaceSource, /\['geometry', 'Geometry'\]/);
assert.match(halbachWorkspaceSource, /\['mesh', 'Mesh'\]/);
assert.match(halbachWorkspaceSource, /\['field', 'Field solution'\]/);
assert.match(halbachWorkspaceSource, /Halbach field solution overlays/);
assert.match(halbachWorkspaceSource, />Flux density<\/button>/);
assert.match(halbachWorkspaceSource, />Field lines<\/button>/);
assert.match(halbachWorkspaceSource, /Halbach field-line density/);
assert.doesNotMatch(halbachWorkspaceSource, /<option value="field-lines"/);
assert.match(halbachTwoSource, /Draw every visible element into one connected path/);
assert.doesNotMatch(halbachTwoSource, /mesh\.triangles\.length \/ 22000/);
assert.match(halbachStyleSource, /\.halbach-field-legend/);
assert.match(halbachStyleSource, /\.halbach-field-layer-menu/);
assert.match(halbachStyleSource, /--halbach-zoom-control-width:\s*141px/);
assert.match(
  halbachStyleSource,
  /\.halbach-field-layer-menu[\s\S]*?right:\s*calc\([\s\S]*?--halbach-viewport-shell-padding[\s\S]*?--halbach-zoom-control-width[\s\S]*?--halbach-viewport-control-gap[\s\S]*?\)/,
);
assert.match(halbachWorkspaceSource, /Corner refinement/);
assert.match(halbachWorkspaceSource, /corner_size_mm/);
assert.match(halbachThreeSource, /halbachDisplaySegments\(config\)/);
assert.match(halbachThreeSource, /ViewportNavigationControls/);
assert.match(halbachThreeSource, /OrbitControls/);
assert.match(halbachThreeSource, /ExtrudeGeometry/);
assert.match(halbachThreeSource, /Cutaway/);
assert.match(halbachThreeSource, /Radial explode/);
assert.match(halbachThreeSource, /2D field extrusion/);
assert.match(halbachWorkspaceSource, /Axial outputs stale/);
assert.match(halbachWorkspaceSource, /disabled=\{axialOutputsStale\}/);
assert.match(halbachThreeSource, /onSelectSegment\(hit \? Number\(hit\.object\.userData\.segmentIndex\) : null\)/);
assert.match(linearHalbachWorkspaceSource, /useState<ViewDimension>\('2d'\)/);
assert.match(linearHalbachWorkspaceSource, /<h2>Magneto2D<\/h2>/);
assert.doesNotMatch(linearHalbachWorkspaceSource, /Magneto2D 2D/);
assert.match(linearHalbachWorkspaceSource, /<LinearHalbach3DViewer/);
assert.match(linearHalbachWorkspaceSource, />2D<\/button>/);
assert.match(linearHalbachWorkspaceSource, />3D<\/button>/);
assert.match(linearHalbachWorkspaceSource, /viewDimension === '2d'/);
assert.match(linearHalbachWorkspaceSource, /viewDimension\.toUpperCase\(\)/);
assert.match(linearHalbachWorkspaceSource, /Linear Halbach field-line density/);
assert.match(linearHalbachWorkspaceSource, /setFieldLineDensity/);
assert.match(linearHalbachWorkspaceSource, /<span>Low<\/span><span>Med<\/span><span>High<\/span>/);
assert.match(linearHalbachWorkspaceSource, /source_note: 'User-entered material parameters\.'/);
assert.match(linearHalbachWorkspaceSource, /Material source note/);
assert.match(linearHalbachWorkspaceSource, /next\.solve\.quality = 'custom'/);
assert.match(
  linearHalbachWorkspaceSource,
  /'samples_per_period',[\s\S]*?next\.solve\.quality = 'custom'/,
);
assert.match(linearHalbachTwoSource, /fieldArrowCanvasRef/);
assert.match(linearHalbachTwoSource, /segment_bx_t/);
assert.match(linearHalbachTwoSource, /window\.requestAnimationFrame\(draw\)/);
assert.match(linearHalbachTwoSource, /canvas\.dataset\.animationState/);
assert.match(linearHalbachTwoSource, /context\.textBaseline = labelIsAbove \? 'bottom' : 'top'/);
assert.match(linearHalbachTwoSource, /labelIsAbove \? -8 : 8/);
assert.match(linearHalbachTwoSource, /retainedPeriods \* wavelength \/ 2/);
assert.match(linearHalbachTwoSource, /expandBoundsForZoomOut/);
assert.match(linearHalbachTwoSource, /navigation\.scale < 1/);
assert.match(linearHalbachTwoSource, /data-zoom-rendering=\{semanticZoomOut \? 'expanded-domain' : 'transform'\}/);
assert.match(linearHalbachTwoSource, /Math\.max\(1, navigation\.scale\)/);
assert.match(linearHalbachTwoSource, /HALBACH_POLE_NORTH_FALLBACK/);
assert.match(linearHalbachTwoSource, /HALBACH_POLE_SOUTH_FALLBACK/);
assert.match(linearHalbachTwoSource, /showTwoTonePoles/);
assert.match(linearHalbachTwoSource, /context\.rotate\(-alpha\)/);
assert.match(linearHalbachTwoSource, /aria-label="Linear Halbach pole color legend"/);
assert.match(linearHalbachTwoSource, /red = N face/);
assert.match(linearHalbachTwoSource, /blue = S face/);
assert.match(linearHalbachThreeSource, /new THREE\.ExtrudeGeometry/);
assert.match(linearHalbachThreeSource, /config\.geometry\.out_of_plane_depth/);
assert.match(linearHalbachThreeSource, /report\.field_data/);
assert.match(linearHalbachThreeSource, /data-field-source/);
assert.match(linearHalbachThreeSource, /data-solve-dimensionality="2d"/);
assert.match(linearHalbachThreeSource, /data-extrusion-axis="z"/);
assert.match(linearHalbachThreeSource, /data-default-orientation="tabletop"/);
assert.match(linearHalbachThreeSource, /data-display-rotation-x-deg="-90"/);
assert.match(linearHalbachThreeSource, /modelGroup\.rotation\.x = -Math\.PI \/ 2/);
assert.match(linearHalbachThreeSource, /Tabletop · X array/);
assert.match(linearHalbachThreeSource, /sampledDirectionCues/);
assert.match(linearHalbachThreeSource, /fieldLineDensity === 'low'/);
assert.doesNotMatch(linearHalbachThreeSource, /linear-halbach-3d-model-badge/);
assert.doesNotMatch(linearHalbachWorkspaceSource, /<div className="halbach-model-notice"/);
assert.match(
  linearHalbachWorkspaceSource,
  /className="halbach-fidelity-card">\{LINEAR_HALBACH_MODEL_NOTICE\}/,
);
assert.match(
  halbachTypesSource,
  /2D Magneto2D field extruded for visualization · not a 3D FEM result/,
);
assert.match(linearHalbachThreeSource, /OrbitControls/);
assert.match(linearHalbachThreeSource, /Section at XY solve plane/);
assert.match(linearHalbachThreeSource, /retainedPeriods \* wavelength \/ 2/);
assert.match(linearHalbachThreeSource, /selectedMagnetRef/);
assert.match(linearHalbachThreeSource, /event\.key === 'Escape'/);
assert.doesNotMatch(linearHalbachThreeSource, /\bbz\b|B_z/);
assert.match(halbachApiSource, /\/halbach\/solve\/stream/);
assert.match(halbachApiSource, /\/halbach\/export\/\$\{kind\}/);
assert.match(halbachTypesSource, /axial end effects are not included/);
assert.match(landingWorkflowHeroSource, /Experimental 2D FEM/);
assert.match(landingWorkflowHeroSource, /Source-built preview/);
assert.doesNotMatch(landingThreeSource, /landing-3d-steps/);
assert.doesNotMatch(landingThreeSource, /aria-label="Workflow steps"/);
assert.doesNotMatch(landingThreeSource, /Preparing native mesh/);
assert.doesNotMatch(landingThreeSource, /Solving electromagnetic fields/);
assert.doesNotMatch(workspaceSource, />In progress</);
assert.match(landingWorkflowHeroSource, /https:\/\/github\.com\/coilemdev\/coilem/);
assert.match(mainSource, /\.\.\/styles\/variables\.css/);
assert.match(mainSource, /\.\.\/styles\/templateselector\.css/);
assert.match(mainSource, /dataset\.skin = 'fable'/);
assert.match(styleSource, /:focus-visible/);
assert.match(styleSource, /prefers-reduced-motion/);
assert.match(styleSource, /progress-track\.indeterminate/);
assert.match(styleSource, /--public-glass/);
assert.match(styleSource, /\.public-landing/);
assert.match(styleSource, /\.public-coilem-shell/);
assert.doesNotMatch(`${appSource}\n${mainSource}\n${workspaceSource}\n${styleSource}`, /OpenEm|public-openem|openem-amber/);
assert.match(styleSource, /\.public-parameter-panel/);
assert.match(styleSource, /\.public-motor-viewport/);
assert.match(styleSource, /html, body, #root \{[^}]*width: 100%/);
assert.match(styleSource, /\.public-coilem-shell \.logo-mark \{[^}]*width: 34px;[^}]*height: 34px/);
assert.match(styleSource, /\.public-coilem-shell \.logo-word \{ font-size: 20px; \}/);
assert.match(viteSource, /\.\/src\/public/);
assert.match(viteSource, /publicDir:\s*fileURLToPath\(new URL\('\.\/public'/);
assert.doesNotMatch(viteSource, /\.\/src\/main\.tsx/);

// Double-layer tooth-coil 2D winding display: each slot splits into two
// half-wedges owned by the adjacent tooth coils, with ⊙/⊗ side markers.
assert.match(motorCanvasSource, /const TOOTH_PHASE_SEQUENCE = \['A', 'C', 'B'\] as const/);
assert.match(motorCanvasSource, /toothIndex % 2 === 0 \? '\+' : '-'/);
assert.match(motorCanvasSource, /toothCoilSidesForSlot/);
assert.match(motorCanvasSource, /clipPolygonToHalfPlane/);
assert.match(motorCanvasSource, /drawCurrentMarker/);
assert.match(motorCanvasSource, /region\.region_type === 'winding_symbol'\) return/);
assert.match(motorCanvasSource, /windingType = 'concentrated'/);
assert.match(workspaceSource, /windingType=\{config\.winding\.type\}/);
// The legend moved into the Layout view with the card it lived on, and it no longer
// mentions +/- because that view marks direction with the glyphs themselves, not
// signs. What matters is that the glyphs are still explained somewhere.
assert.match(windingLayoutSource, /⊙ out of page · ⊗ into page/);
assert.match(modelSource, /toothIndex\?: number/);

// Guided setup coach: landing entry, data-guide anchors, and step coach.
assert.match(landingWorkflowHeroSource, /Start a design/);
assert.match(appSource, /<PublicGuidedSetup/);
assert.match(appSource, /setGuidedActive\(guided\)/);
assert.match(appSource, /const nextConfig = cloneDefaultConfig\(\)/);
assert.match(appSource, /topology=\{config\.topology\}/);
assert.match(appSource, /guidedDesignSection=\{guidedDesignSection\}/);
assert.match(appSource, /onDesignSectionChange=\{revealGuidedDesignSection\}/);
assert.match(appSource, /guidedVisitedSectionsRef/);
assert.match(appSource, /repairGuidedSection\(config, section\)/);
assert.match(appSource, /guidedActive && visitedSection/);
assert.match(appSource, /onDesignSectionVisit=\{visitGuidedDesignSection\}/);
assert.match(workspaceSource, /onDesignSectionVisit\(section\)/);
assert.match(workspaceSource, /onSectionChange\(section, field, value, visitedSection\)/);
assert.match(guidedRepairSource, /Repair only the section the coach is about to reveal/);
assert.match(guidedRepairSource, /nearestBalancedPoleCount/);
assert.match(guidedRepairSource, /maximumRotorOd/);
assert.match(guidedRepairSource, /maximumToothWidth/);
assert.match(guidedRepairSource, /terminalCoilsPerPhase/);
assert.match(appSource, /GUIDED_IPM_LAYOUT_PRESETS/);
assert.match(appSource, /v_shape:[\s\S]*?magnet_width_mm: 28[\s\S]*?v_angle_deg: 40[\s\S]*?v_depth_mm: 30[\s\S]*?inner_web_thickness_mm: 6/);
assert.match(appSource, /\.\.\.GUIDED_IPM_LAYOUT_PRESETS\[selectedIpmLayout\]/);
assert.doesNotMatch(appSource, /guidedActive\s*&&\s*section === 'rotor'\s*&&\s*field === 'ipm_topology'/);
assert.match(workspaceSource, /data-guide="topology-selector"/);
assert.match(workspaceSource, /data-guide="ipm-layout-selector"/);
assert.match(workspaceSource, /label: 'Flat \/ buried'/);
assert.match(workspaceSource, /label: 'V-shape'/);
assert.ok(
  workspaceSource.indexOf('data-guide="ipm-layout-selector"')
    < workspaceSource.indexOf('<ParameterSectionBlock id="stator"'),
  'IPM layout selection must appear before stator geometry',
);
assert.doesNotMatch(workspaceSource, /<SelectRow label="Rotor Layout"/);
assert.match(workspaceSource, /data-guide=\{`section-\$\{id\}`\}/);
assert.match(workspaceSource, /data-guide-active=\{active \? 'true' : 'false'\}/);
assert.match(workspaceSource, /setActiveSection\(guidedDesignSection \?\? null\)/);
assert.match(workspaceSource, /data-guide="design-continue"/);
assert.match(workspaceSource, /data-guide="solve-plan"/);
assert.match(workspaceSource, /data-guide="solve-run"/);
assert.match(workspaceSource, /data-guide="open-report"/);
assert.match(workspaceSource, /Review source and limitations/);
assert.match(workspaceSource, /Review material provenance/);
assert.match(workspaceSource, /<summary>Model assumptions<\/summary>/);
assert.match(workspaceSource, />Phase current</);
assert.match(workspaceSource, />Rated speed</);
assert.match(workspaceSource, /Ideal six-step \(120°\)/);
assert.match(workspaceSource, /Conducting phase current/);
assert.match(workspaceSource, /A plateau/);
assert.match(workspaceSource, /Commutation advance/);
assert.match(workspaceSource, /Phase connection: Wye \(MVP\)/);
assert.match(workspaceSource, /no PWM, switching ripple, Hall timing, dead time, or ESC dynamics/);
assert.match(workspaceSource, /Phase-neutral/);
assert.match(workspaceSource, /Line-line/);
assert.match(workspaceSource, /IdealSixStepCommand/);
const sixStepCommandSource = workspaceSource.slice(
  workspaceSource.indexOf('function IdealSixStepCommand()'),
  workspaceSource.indexOf('function needsRunStorageRecovery('),
);
const sixStepSectors = [...sixStepCommandSource.matchAll(/\['([^']*)',/g)].map((match) => match[1]);
assert.deepEqual(sixStepSectors, ['S1', 'S2', 'S3', 'S4', 'S5', 'S6'],
  'the exported six-step panel must retain all six distinct sector labels and React keys');
assert.match(sixStepCommandSource, /<li key=\{sector\}><strong>\{sector\}<\/strong>/);
assert.match(bldcChartSource, /public-bldc-sector/);
assert.match(bldcChartSource, /Accessible waveform data/);
assert.match(bldcChartSource, /role="region"/);
assert.match(bldcChartSource, /stepSegments/);
assert.match(bldcChartSource, /public-bldc-open-phase/);
assert.match(bldcChartSource, /showTorque, setShowTorque] = useState\(true\)/);
assert.match(bldcChartSource, /showPhaseCurrents, setShowPhaseCurrents] = useState\(true\)/);
assert.match(bldcChartSource, /role="group" aria-label="Visible waveform groups"/);
assert.match(bldcChartSource, /aria-pressed=\{showTorque\}/);
assert.match(bldcChartSource, /aria-pressed=\{showPhaseCurrents\}/);
assert.match(bldcChartSource, /disabled=\{showTorque && !showPhaseCurrents\}/);
assert.match(bldcChartSource, /disabled=\{showPhaseCurrents && !showTorque\}/);
assert.match(bldcChartSource, /showTorque && <path d=\{torquePath\}/);
assert.match(bldcChartSource, /showPhaseCurrents && \[phaseA, phaseB, phaseC\]/);
assert.match(runComparisonSource, /Excitation identity/);
assert.match(appSource, /excitationDraftRef/);
assert.match(workspaceSource, /designName=\{props\.designName \?\? null\}/);
assert.match(guidedSource, /PUBLIC_GUIDED_STOPS/);
assert.match(guidedSource, /target: 'topology-selector'/);
assert.match(guidedSource, /target: 'ipm-layout-selector'/);
assert.match(guidedSource, /stop\.id !== 'ipm-layout'/);
assert.match(guidedSource, /stop\.id === 'topology' && topology === 'IPM'/);
assert.match(guidedSource, /'section-stator'/);
assert.match(guidedSource, /'solve-plan'/);
assert.match(guidedSource, /'solve-run'/);
assert.match(guidedSource, /'open-report'/);
assert.match(guidedSource, /prefers-reduced-motion/);
assert.match(guidedSource, /Exit guided setup/);
assert.match(guidedSource, /className="public-guided-next"/);
assert.match(guidedSource, /onClick=\{handleNext\}/);
assert.match(guidedSource, /stop\.id === 'solve-run' && !resultReady/);
assert.match(guidedSource, /onDesignSectionChange\(designSectionForStop\(nextStop\)\)/);
assert.match(guidedSource, /setAdjustmentMessage\(null\);[\s\S]*?\[activeStep\]/);
assert.match(guidedSource, /onWorkflowStepChange\(nextStop\.step\)/);
assert.match(guidedSource, /stop\.id === 'report'\) onWorkflowStepChange\('report'\)/);
assert.doesNotMatch(guidedSource, /public-guided-hint/);
assert.doesNotMatch(guidedSource, /actionHint:/);
assert.match(guidedSource, /data-guide-active="true"/);
assert.match(styleSource, /\.public-guided-highlight/);
assert.match(styleSource, /\.public-guided-card/);

// 2D lighting pass and the drive-end shaft convention.
assert.match(motorCanvasSource, /shadedRegionFill/);
assert.match(motorCanvasSource, /REGION_SHADING/);
assert.match(motorCanvasSource, /soft-light/);
assert.match(motorCanvasSource, /ANNULAR_REGIONS/);
assert.match(motorThreeSource, /shaftFrontOverhang/);

console.log('public UI contract audit passed');
