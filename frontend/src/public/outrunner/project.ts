import bundledProject from './lrk_12s14p.coilem?raw';

export interface OutrunnerProject {
  kind: 'coilem_frozen_reference';
  format_version: 1;
  name: string;
  fixture_id: string;
  source_sha256: string;
  fixture_asset_sha256: string;
  coordinate_convention: 'source_native_CCW_outer_rotor';
  fixture_data: Record<string, unknown>;
  analysis: {
    accuracy_plan: 'preview' | 'standard' | 'high_accuracy' | 'custom';
    unique_samples: 24 | 48 | 96 | 192 | 384;
    gap_size_mm: 0.1 | 0.05 | 0.025 | 0.0125;
    bulk_size_mm: 0.5 | 0.25 | 0.125;
    speed_rpm: number;
    loaded_currents_A: number[];
    excitation_mode: 'fixed_phase_currents' | 'sinusoidal' | 'ideal_six_step_120';
    current_amplitude_A: number;
    current_amplitude_convention: 'rms' | 'peak' | 'plateau';
    current_angle_deg: number;
    commutation_advance_deg: number;
    nonlinear_tolerance: 0.00001 | 0.000001;
    material_law: string;
    mesh_policy: string;
  };
}

export const BENCHMARK_OUTRUNNER_PROJECT = normalizeOutrunnerProject(JSON.parse(bundledProject) as OutrunnerProject);
export const DEFAULT_OUTRUNNER_PROJECT: OutrunnerProject = {
  ...BENCHMARK_OUTRUNNER_PROJECT, name: 'LRK outrunner 12s/14p',
  analysis: { ...BENCHMARK_OUTRUNNER_PROJECT.analysis, excitation_mode: 'ideal_six_step_120', current_amplitude_convention: 'plateau' },
};

export function normalizeOutrunnerProject(project: OutrunnerProject): OutrunnerProject {
  const analysis = { ...project.analysis };
  analysis.excitation_mode ??= 'fixed_phase_currents';
  analysis.current_amplitude_A ??= 4;
  analysis.current_amplitude_convention ??= 'peak';
  analysis.current_angle_deg ??= 0;
  analysis.commutation_advance_deg ??= 0;
  if (analysis.bulk_size_mm === undefined) analysis.bulk_size_mm = 0.25;
  if (!analysis.accuracy_plan) {
    analysis.accuracy_plan = analysis.unique_samples === 48 && analysis.gap_size_mm === .05 && analysis.bulk_size_mm === .25
      && analysis.nonlinear_tolerance === 1e-5 ? 'standard' : 'custom';
  }
  return { ...project, analysis };
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
  return JSON.stringify(value) ?? 'null';
}

export function sameOutrunnerProject(left: OutrunnerProject, right: OutrunnerProject): boolean {
  return canonical(normalizeOutrunnerProject(left)) === canonical(normalizeOutrunnerProject(right));
}

/** Recognize this envelope before the ordinary motor parser can apply defaults. */
export function parseOutrunnerProject(text: string): OutrunnerProject | null {
  let raw = JSON.parse(text) as Partial<OutrunnerProject>;
  if (raw?.kind !== 'coilem_frozen_reference') return null;
  const pinned = DEFAULT_OUTRUNNER_PROJECT;
  if (raw.format_version !== 1 || raw.fixture_id !== pinned.fixture_id
    || raw.source_sha256 !== pinned.source_sha256 || raw.fixture_asset_sha256 !== pinned.fixture_asset_sha256
    || raw.coordinate_convention !== pinned.coordinate_convention || !raw.fixture_data || !raw.analysis
    || typeof raw.name !== 'string' || !raw.name.trim()) {
    throw new Error('The frozen reference identity or required settings are missing or unsupported.');
  }
  raw = normalizeOutrunnerProject(raw as OutrunnerProject);
  const analysis = raw.analysis!;
  if (![24, 48, 96, 192, 384].includes(analysis.unique_samples) || ![0.1, 0.05, 0.025, 0.0125].includes(analysis.gap_size_mm)
    || ![0.5, 0.25, 0.125].includes(analysis.bulk_size_mm) || !['preview', 'standard', 'high_accuracy', 'custom'].includes(analysis.accuracy_plan)
    || !Number.isFinite(analysis.speed_rpm) || analysis.speed_rpm <= 0 || analysis.speed_rpm > 100000
    || !Array.isArray(analysis.loaded_currents_A) || analysis.loaded_currents_A.length !== 3
    || !analysis.loaded_currents_A.every((value) => Number.isFinite(value) && Math.abs(value) <= 20)
    || Math.abs(analysis.loaded_currents_A.reduce((sum, value) => sum + value, 0)) > 1e-10
    || ![1e-5, 1e-6].includes(analysis.nonlinear_tolerance)
    || !['fixed_phase_currents', 'sinusoidal', 'ideal_six_step_120'].includes(analysis.excitation_mode)
    || !Number.isFinite(analysis.current_amplitude_A) || analysis.current_amplitude_A < 0 || analysis.current_amplitude_A > 20
    || !['rms', 'peak', 'plateau'].includes(analysis.current_amplitude_convention)
    || !Number.isFinite(analysis.current_angle_deg) || Math.abs(analysis.current_angle_deg) > 180
    || !Number.isFinite(analysis.commutation_advance_deg) || Math.abs(analysis.commutation_advance_deg) > 180
    || (analysis.excitation_mode === 'ideal_six_step_120' && analysis.current_amplitude_convention !== 'plateau')
    || (analysis.excitation_mode === 'sinusoidal' && (analysis.current_amplitude_convention === 'plateau'
      || analysis.current_amplitude_A*(analysis.current_amplitude_convention === 'rms' ? Math.SQRT2 : 1) > 20+1e-10))
    || analysis.material_law !== pinned.analysis.material_law || analysis.mesh_policy !== pinned.analysis.mesh_policy) {
    throw new Error('The reference analysis settings are invalid or unsupported.');
  }
  return raw as OutrunnerProject;
}

export function downloadReferenceFile(name: string, data: unknown, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2) + '\n'], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
