import assert from 'node:assert/strict';
import { importTypeScriptModule } from './import-typescript-module.mjs';

const { cloneDefaultConfig } = await importTypeScriptModule(new URL('../src/public/model.ts', import.meta.url));
const { analysisSummary, setAnalysisOption, hasTorqueResult, hasBackEmfResult, defaultResultPlot } = await importTypeScriptModule(new URL('../src/public/analysisOptions.ts', import.meta.url));
const { asPublicConfig } = await importTypeScriptModule(new URL('../src/public/publicRequest.ts', import.meta.url));
const { applyPublicSolvePreset } = await importTypeScriptModule(new URL('../src/public/solvePlan.ts', import.meta.url));
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
assert.equal(defaultResultPlot({ ...result, summary: { ...result.summary, back_emf_fundamental_V: null }, torque_speed_analysis: {} }), 'performance');
assert.throws(() => parseDesignFile(JSON.stringify({ ...mapOnly, torque_speed_analysis: {
  ...mapOnly.torque_speed_analysis, limits: { ...mapOnly.torque_speed_analysis.limits, dc_bus_V: -5 },
} })), /Invalid torque–speed map settings/);
console.log('Analysis defaults, selection, standalone requests, roundtrip and result availability pass.');
