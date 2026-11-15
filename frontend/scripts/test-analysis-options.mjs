import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));
const { analysisSummary, analysisPositions, setAnalysisOption, hasTorqueResult, hasBackEmfResult, defaultResultPlot } = await importTypeScriptModule(new URL('../src/public/analysisOptions.ts', import.meta.url));
const { asPublicConfig } = await importTypeScriptModule(new URL('../src/public/publicRequest.ts', import.meta.url));
const { applyPublicSolvePreset, ensureLossesFullCycle } = await importTypeScriptModule(new URL('../src/public/solvePlan.ts', import.meta.url));
const { parseDesignFile } = await importTypeScriptModule(new URL('../src/public/designFile.ts', import.meta.url));

let config = cloneDefaultConfig();
assert.equal(analysisSummary(config), 'Torque · Back EMF');
assert.equal(config.solve_options.cogging_torque, false);
assert.equal(config.solve_options.losses_efficiency, false);
assert.equal(config.solve_options.torque_speed_envelope, false);
config = setAnalysisOption(config, 'torque_sweep', false);
assert.equal(analysisSummary(config), 'Back EMF');
config = setAnalysisOption(config, 'back_emf', false);
config = setAnalysisOption(config, 'cogging_torque', true);
config = setAnalysisOption(config, 'losses_efficiency', true);
assert.equal(analysisSummary(config), 'Cogging · Losses & efficiency');
{
  // The map line counts only the solves a run will do: stored points are reused.
  const mapped = setAnalysisOption(setAnalysisOption(cloneDefaultConfig(), 'back_emf', false), 'torque_speed_envelope', true);
  const positions = (map) => analysisPositions(mapped, { sweep_positions: 17, analysis_positions: { torque_sweep: 17 }, torque_speed_map: map }, 'magneto2d');
  assert.equal(positions({ solves: 29, positions_per_point: 12 }), 'Torque 17 · Map 29 solves');
  assert.equal(positions({ solves: 29, solves_remaining: 29, positions_per_point: 12 }), 'Torque 17 · Map 29 solves');
  assert.equal(positions({ solves: 29, solves_remaining: 11, positions_per_point: 12 }), 'Torque 17 · Map 11 of 29 solves');
  assert.equal(positions({ solves: 29, solves_remaining: 0, positions_per_point: 12 }), 'Torque 17 · Map stored');
}
// Losses keep the chosen plan; only the request is widened to a full cycle at the plan's step.
const lossPlan = c => [c.solve_params.solve_quality, c.solve_params.rotor_sweep_range_deg, c.solve_params.rotor_step_deg, c.solve_params.mesh_density];
for (const [preset, request] of [['quick', ['custom', 360, 15, 'coarse']], ['standard', ['custom', 360, 7.5, 'normal']], ['fine', ['fine', 360, 7.5, 'fine']]]) {
  const planned = applyPublicSolvePreset(config, preset, { rotor_sweep_range_deg: preset === 'fine' ? 360 : 60, rotor_step_deg: 7.5 });
  assert.equal(planned.solve_params.solve_quality, preset, 'losses do not rewrite the chosen plan');
  assert.deepEqual(lossPlan(asPublicConfig(planned)), request, `${preset} requests solve a full cycle at the plan's own step`);
  assert.equal(planned.solve_params.solve_quality, preset, 'request preparation must not mutate stored settings');
}
const withBackEmf = setAnalysisOption(config, 'back_emf', true);
assert.equal(asPublicConfig(withBackEmf).solve_params.solve_quality, 'standard', 'Standard with Back EMF already solves a full cycle');
assert.equal(asPublicConfig(withBackEmf).solve_options.thd_analysis, true, 'and keeps its harmonic analysis');
const customLosses = structuredClone(config);
Object.assign(customLosses.solve_params, { solve_quality: 'custom', rotor_sweep_range_deg: 60, rotor_step_deg: 2 });
assert.deepEqual(lossPlan(asPublicConfig(customLosses)), ['custom', 360, 2, 'normal']);
const request = asPublicConfig(config);
assert.equal(ensureLossesFullCycle(request), request, 'already normalized settings remain stable');
assert.deepEqual(lossPlan(asPublicConfig(config, 'elmer')), lossPlan(config), 'unsupported Elmer analyses do not promote its sweep');
assert.deepEqual(lossPlan(parseDesignFile(JSON.stringify(config)).config), lossPlan(config), 'files open with the plan they were saved with');
const disabled = setAnalysisOption(config, 'losses_efficiency', false);
assert.deepEqual(lossPlan(asPublicConfig(disabled)), lossPlan(config));
assert.equal(asPublicConfig(config).solve_options.thd_analysis, false);
const fine = applyPublicSolvePreset(config, 'fine', { rotor_sweep_range_deg: 360, rotor_step_deg: 7.5 });
assert.equal(fine.solve_options.thd_analysis, false, 'changing accuracy must not re-enable Back EMF');
assert.equal(analysisSummary(config, 'elmer'), 'Select analyses');
assert.equal(asPublicConfig(config, 'elmer').solve_options.losses_efficiency, false);
assert.equal(asPublicConfig(config, 'elmer').solve_options.cogging_torque, false);

// Save/import preserves standalone selections and opt-in analyses.
const reopened = parseDesignFile(JSON.stringify({ ...config, name: 'Standalone analysis' })).config;
assert.deepEqual(reopened.solve_options, config.solve_options);

const result = { summary: { avg_torque_Nm: null, back_emf_fundamental_V: 12 }, solve_metadata: { torque_sweep_computed: false, back_emf_computed: true } };
assert.equal(hasTorqueResult(result), false);
assert.equal(hasBackEmfResult(result), true);
assert.equal(defaultResultPlot(result), 'back-emf');
assert.equal(defaultResultPlot({ ...result, summary: { ...result.summary, back_emf_fundamental_V: null, cogging: {} }, cogging_torque_waveform: {} }), 'cogging');
const mapOnly = setAnalysisOption({ ...cloneDefaultConfig(), solve_options: { ...cloneDefaultConfig().solve_options,
  torque_sweep: false, back_emf: false, thd_analysis: false } }, 'torque_speed_envelope', true);
assert.equal(analysisSummary(mapOnly), 'Torque–speed map');
assert.equal(mapOnly.torque_speed_analysis.preset, 'preview');
assert.equal(mapOnly.torque_speed_analysis.limits.peak_current_A, 60 * Math.SQRT2);
assert.equal(asPublicConfig(mapOnly).solve_options.torque_sweep, false);
assert.equal(asPublicConfig(mapOnly).solve_options.back_emf, false);
assert.equal(asPublicConfig(mapOnly, 'elmer').solve_options.torque_speed_envelope, false);
assert.equal(analysisSummary(mapOnly, 'elmer'), 'Select analyses');
const reopenedMap = parseDesignFile(JSON.stringify(mapOnly)).config;
assert.equal(reopenedMap.solve_options.torque_speed_envelope, true);
assert.deepEqual(reopenedMap.torque_speed_analysis, mapOnly.torque_speed_analysis);
const deselected = setAnalysisOption(reopenedMap, 'torque_speed_envelope', false);
assert.equal(asPublicConfig(deselected).torque_speed_analysis, null, 'unticked maps are omitted from the solve request');
assert.deepEqual(deselected.torque_speed_analysis, reopenedMap.torque_speed_analysis, 'the design keeps settings for a later requested map');
assert.deepEqual(asPublicConfig(setAnalysisOption(deselected, 'torque_speed_envelope', true)).torque_speed_analysis, reopenedMap.torque_speed_analysis);
assert.equal(defaultResultPlot({ ...result, summary: { ...result.summary, back_emf_fundamental_V: null }, torque_speed_analysis: {} }), 'performance');
assert.throws(() => parseDesignFile(JSON.stringify({ ...mapOnly, torque_speed_analysis: {
  ...mapOnly.torque_speed_analysis, limits: { ...mapOnly.torque_speed_analysis.limits, dc_bus_V: -5 },
} })), /Invalid torque–speed map settings/);
console.log('Analysis defaults, selection, standalone requests, roundtrip and result availability pass.');
