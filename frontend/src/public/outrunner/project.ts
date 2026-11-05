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
    unique_samples: 48 | 96 | 192 | 384;
    gap_size_mm: 0.05 | 0.025 | 0.0125;
    speed_rpm: number;
    loaded_currents_A: number[];
    nonlinear_tolerance: 0.00001 | 0.000001;
    material_law: string;
    mesh_policy: string;
  };
}

export const DEFAULT_OUTRUNNER_PROJECT = JSON.parse(bundledProject) as OutrunnerProject;

/** Recognize this envelope before the ordinary motor parser can apply defaults. */
export function parseOutrunnerProject(text: string): OutrunnerProject | null {
  const raw = JSON.parse(text) as Partial<OutrunnerProject>;
  if (raw?.kind !== 'coilem_frozen_reference') return null;
  const pinned = DEFAULT_OUTRUNNER_PROJECT;
  if (raw.format_version !== 1 || raw.fixture_id !== pinned.fixture_id
    || raw.source_sha256 !== pinned.source_sha256 || raw.fixture_asset_sha256 !== pinned.fixture_asset_sha256
    || raw.coordinate_convention !== pinned.coordinate_convention || !raw.fixture_data || !raw.analysis
    || typeof raw.name !== 'string' || !raw.name.trim()) {
    throw new Error('The frozen reference identity or required settings are missing or unsupported.');
  }
  const analysis = raw.analysis;
  if (![48, 96, 192, 384].includes(analysis.unique_samples) || ![0.05, 0.025, 0.0125].includes(analysis.gap_size_mm)
    || !Number.isFinite(analysis.speed_rpm) || analysis.speed_rpm <= 0 || analysis.speed_rpm > 100000
    || !Array.isArray(analysis.loaded_currents_A) || analysis.loaded_currents_A.length !== 3
    || !analysis.loaded_currents_A.every((value) => Number.isFinite(value) && Math.abs(value) <= 20)
    || Math.abs(analysis.loaded_currents_A.reduce((sum, value) => sum + value, 0)) > 1e-10
    || ![1e-5, 1e-6].includes(analysis.nonlinear_tolerance)
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
