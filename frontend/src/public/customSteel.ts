import type { MaterialCatalog, MotorConfig, PublicMaterialModel } from './model';

export interface CustomSteel {
  id: string;
  name: string;
  source: string;
  lamination_thickness_mm: number | null;
  bh_curve: Array<[number, number]>;
  curve_sha256: string;
}

export type SteelTarget = 'stator' | 'rotor' | 'both';

export function parseCustomSteels(value: unknown): Record<string, CustomSteel> {
  if (value === undefined) return {};
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length > 16) {
    throw new Error('Expected at most 16 embedded custom steel definitions.');
  }
  const materials: Record<string, CustomSteel> = {};
  for (const [id, raw] of Object.entries(value)) {
    const item = raw as CustomSteel | null;
    if (!/^custom:[a-f0-9]{64}$/.test(id) || !item || item.id !== id
      || typeof item.name !== 'string' || !item.name.trim() || item.name.length > 120
      || typeof item.source !== 'string' || !item.source.trim() || item.source.length > 500
      || typeof item.curve_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(item.curve_sha256)
      || (item.lamination_thickness_mm !== null && (typeof item.lamination_thickness_mm !== 'number'
        || !Number.isFinite(item.lamination_thickness_mm) || item.lamination_thickness_mm <= 0 || item.lamination_thickness_mm > 10))
      || !Array.isArray(item.bh_curve) || item.bh_curve.length < 3 || item.bh_curve.length > 4096) {
      throw new Error('Invalid embedded custom steel definition. Reimport its CSV.');
    }
    item.bh_curve.forEach((point, index) => {
      if (!Array.isArray(point) || point.length !== 2 || point.some((v) => typeof v !== 'number' || !Number.isFinite(v))) {
        throw new Error(`Custom steel point ${index + 1} must contain two finite numbers.`);
      }
      const [b, h] = point;
      if (b < 0 || b > 5 || h < 0 || h > 1e7 || (index === 0 && (b !== 0 || h !== 0))) {
        throw new Error('Custom steel must start at (0,0), with B in 0–5 T and H in 0–10,000,000 A/m.');
      }
      if (index > 0) {
        const [previousB, previousH] = item.bh_curve[index - 1];
        const mu = b / (4 * Math.PI * 1e-7 * h);
        if (b <= previousB || h <= previousH || mu < 1 || mu > 1e6) {
          throw new Error(`Custom steel point ${index + 1}: B and H must increase and use valid steel units.`);
        }
      }
    });
    materials[id] = {
      id, name: item.name, source: item.source, lamination_thickness_mm: item.lamination_thickness_mm,
      curve_sha256: item.curve_sha256, bh_curve: item.bh_curve.map(([b, h]) => [b, h]),
    };
  }
  return materials;
}

export function steelDisplayName(config: MotorConfig, id: string): string {
  return config.materials.custom_steels?.[id]?.name ?? id;
}

export function customSteelModel(material: CustomSteel): PublicMaterialModel {
  const last = material.bh_curve[material.bh_curve.length - 1];
  return {
    id: material.id, display_name: `${material.name} · Custom`, kind: 'electrical_steel',
    model_kind: 'nonlinear_bh', model_revision: 'user-supplied/v1', model_hash: material.id.slice(7),
    properties: {
      initial_relative_permeability: material.bh_curve[1][0] / (4 * Math.PI * 1e-7 * material.bh_curve[1][1]),
      curve_min_T: 0, curve_max_T: last[0], curve_max_H_A_per_m: last[1],
      source_description: material.source,
      ...(material.lamination_thickness_mm === null ? {} : { lamination_thickness_mm: material.lamination_thickness_mm }),
    },
    capabilities: { material_curve: true, saturation_visualization: true, hysteresis_loop: false,
      demagnetization_assessment: false, temperature_dependence: false, core_loss: false },
    curve: { x_quantity: 'field_strength', x_unit: 'A/m', x_scale: 'log1p', y_quantity: 'flux_density', y_unit: 'T',
      points: material.bh_curve.map(([b, h]) => [h, b]) },
    limitations: [`Source: ${material.source}`, 'User-supplied data; not a bundled validation reference.',
      `Data ends at ${last[0]} T. Higher fields use linear extrapolation of the final segment.`,
      'Core-loss, hysteresis and temperature data are not included.'],
  };
}

export function projectMaterialCatalog(catalog: MaterialCatalog, config: MotorConfig): MaterialCatalog {
  const custom = Object.values(config.materials.custom_steels ?? {});
  return { ...catalog, steels: ['M350-50A', ...custom.map((item) => item.id)],
    models: { ...catalog.models, ...Object.fromEntries(custom.map((item) => [item.id, customSteelModel(item)])) } };
}
