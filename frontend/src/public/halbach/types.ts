export type HalbachQuality = 'quick' | 'standard' | 'fine' | 'custom';
export type HalbachMeshDensity = 'coarse' | 'normal' | 'fine';
export type HalbachResultView =
  | 'magnitude'
  | 'parallel'
  | 'perpendicular'
  | 'az'
  | 'vectors';

export type HalbachViewportMode = 'geometry' | 'mesh' | 'field';

export interface HalbachCatalogMagnet {
  source: 'catalog';
  grade: 'N35' | 'N42' | 'N48' | 'N52' | 'N48SH' | 'Ferrite_Y30' | 'Prius_2004_NdFeB';
  temperature_c: number;
}

export interface HalbachCustomMagnet {
  source: 'custom';
  name: string;
  remanence_t: number;
  relative_permeability: number;
  intrinsic_coercivity_a_per_m?: number;
  density_kg_per_m3?: number;
  reference_temperature_c?: number;
  temperature_c?: number;
  alpha_br_per_k?: number;
  alpha_hcj_per_k?: number;
  source_note: string;
}

export interface HalbachArrayConfig {
  kind: 'halbach_array_config';
  version: '1.0';
  units: {
    length: 'mm';
    angle: 'deg';
  };
  geometry: {
    inner_radius: number;
    outer_radius: number;
    axial_length: number;
    segment_count: number;
    segment_gap_angle: number;
    segment_start_angle: number;
  };
  array: {
    field_mode: 'internal';
    multipole_order: 1;
    field_direction: number;
  };
  magnet: HalbachCatalogMagnet | HalbachCustomMagnet;
  sample_region: {
    radius: number;
    radial_samples: number;
    angular_samples: number;
    leakage_probe_radius: number;
  };
  solve: {
    quality: HalbachQuality;
    mesh: {
      density: HalbachMeshDensity;
      outer_boundary_radius_factor: number;
      minimum_elements_across_magnet: number;
      corner_refinement: boolean;
    };
    linear: {
      solver: 'direct';
      tolerance: number;
      max_iterations: number;
    };
  };
}

export interface LinearHalbachArrayConfig {
  kind: 'linear_halbach_array_config';
  version: '1.0';
  units: {
    length: 'mm';
    angle: 'deg';
  };
  geometry: {
    block_width: number;
    magnet_height: number;
    out_of_plane_depth: number;
    period_count: number;
    block_gap: number;
  };
  array: {
    strong_side: 'positive_y' | 'negative_y';
    phase_deg: number;
  };
  magnet: HalbachCatalogMagnet | HalbachCustomMagnet;
  sample_region: {
    probe_offset: number;
    edge_exclusion_periods: number;
    samples_per_period: number;
  };
  solve: {
    quality: HalbachQuality;
    mesh: {
      density: HalbachMeshDensity;
      outer_padding_factor: number;
      minimum_elements_across_magnet: number;
      corner_refinement: boolean;
    };
    linear: {
      solver: 'direct' | 'pcg';
      pcg_preconditioner?: 'incomplete_cholesky' | 'jacobi';
      tolerance: number;
      max_iterations: number;
    };
    field_line_count?: number;
  };
}

export type HalbachDesignConfig = HalbachArrayConfig | LinearHalbachArrayConfig;

export const HALBACH_QUALITY_PRESETS = {
  quick: {
    density: 'coarse',
    outerBoundaryRadiusFactor: 3,
    minimumElementsAcrossMagnet: 3,
    radialSamples: 17,
    angularSamples: 48,
    tolerance: 1e-7,
  },
  standard: {
    density: 'normal',
    outerBoundaryRadiusFactor: 4,
    minimumElementsAcrossMagnet: 6,
    radialSamples: 31,
    angularSamples: 96,
    tolerance: 1e-8,
  },
  fine: {
    density: 'fine',
    outerBoundaryRadiusFactor: 6,
    minimumElementsAcrossMagnet: 10,
    radialSamples: 61,
    angularSamples: 192,
    tolerance: 1e-9,
  },
} as const;

export function withHalbachQualityPreset(
  config: HalbachArrayConfig,
  quality: Exclude<HalbachQuality, 'custom'>,
): HalbachArrayConfig {
  const preset = HALBACH_QUALITY_PRESETS[quality];
  return {
    ...config,
    sample_region: {
      ...config.sample_region,
      radial_samples: preset.radialSamples,
      angular_samples: preset.angularSamples,
    },
    solve: {
      ...config.solve,
      quality,
      mesh: {
        ...config.solve.mesh,
        density: preset.density,
        outer_boundary_radius_factor: preset.outerBoundaryRadiusFactor,
        minimum_elements_across_magnet: preset.minimumElementsAcrossMagnet,
        corner_refinement: true,
      },
      linear: {
        ...config.solve.linear,
        tolerance: preset.tolerance,
      },
    },
  };
}

export const LINEAR_HALBACH_QUALITY_PRESETS = {
  quick: {
    density: 'coarse',
    outerPaddingFactor: 1.5,
    minimumElementsAcrossMagnet: 3,
    samplesPerPeriod: 24,
    tolerance: 1e-7,
  },
  standard: {
    density: 'normal',
    outerPaddingFactor: 2.5,
    minimumElementsAcrossMagnet: 6,
    samplesPerPeriod: 64,
    tolerance: 1e-8,
  },
  fine: {
    density: 'fine',
    outerPaddingFactor: 3.5,
    minimumElementsAcrossMagnet: 10,
    samplesPerPeriod: 128,
    tolerance: 1e-9,
  },
} as const;

export function withLinearHalbachQualityPreset(
  config: LinearHalbachArrayConfig,
  quality: Exclude<HalbachQuality, 'custom'>,
): LinearHalbachArrayConfig {
  const preset = LINEAR_HALBACH_QUALITY_PRESETS[quality];
  return {
    ...config,
    sample_region: {
      ...config.sample_region,
      samples_per_period: preset.samplesPerPeriod,
    },
    solve: {
      ...config.solve,
      quality,
      mesh: {
        ...config.solve.mesh,
        density: preset.density,
        outer_padding_factor: preset.outerPaddingFactor,
        minimum_elements_across_magnet: preset.minimumElementsAcrossMagnet,
        corner_refinement: true,
      },
      linear: {
        ...config.solve.linear,
        tolerance: preset.tolerance,
      },
    },
  };
}

export interface HalbachValidationIssue {
  code?: string;
  field: string;
  message: string;
  type?: string;
}

export interface HalbachDesignHealth {
  ready_to_solve: boolean;
  errors: HalbachValidationIssue[];
  warnings: HalbachValidationIssue[];
  checks: Array<{ label: string; value: number }>;
  analytics: {
    ideal_continuous_bore_field_t: number;
    segmented_bore_field_estimate_t: number;
    magnet_area_mm2: number;
    magnet_volume_m3: number;
    magnet_mass_kg: number | null;
  };
}

export interface HalbachPreview {
  kind: 'halbach_preview';
  version: '1.0';
  configuration: HalbachArrayConfig;
  geometry: Record<string, unknown>;
  material: Record<string, unknown>;
  design_health: HalbachDesignHealth;
}

export interface LinearHalbachDesignHealth {
  ready_to_solve: boolean;
  errors: HalbachValidationIssue[];
  warnings: HalbachValidationIssue[];
  checks: Array<{ label: string; value: number }>;
  analytics: {
    block_count: number;
    wavelength_mm: number;
    active_length_mm: number;
    magnet_area_mm2: number;
    magnet_volume_m3: number;
    magnet_mass_kg: number | null;
  };
}

export interface LinearHalbachPreview {
  kind: 'linear_halbach_preview';
  version: '1.0';
  configuration: LinearHalbachArrayConfig;
  geometry: Record<string, unknown>;
  material: Record<string, unknown>;
  design_health: LinearHalbachDesignHealth;
}

export interface HalbachMeshPreview {
  nodes_mm: Array<[number, number]>;
  triangles: Array<[number, number, number]>;
  regions: string[];
  physical_groups: Record<string, Record<string, unknown>>;
  feature_physical_groups: Record<string, Record<string, unknown>>;
  mesh_info: Record<string, boolean | number | string>;
  mesh_qa: Record<string, number | boolean | Record<string, number>>;
  mesh_hash: string;
  geometry_hash: string;
  magnetostatic_problem_sha256: string;
}

export type LinearHalbachMeshPreview = HalbachMeshPreview;

export interface HalbachFieldSample {
  x_mm: number;
  y_mm: number;
  angle_deg?: number | null;
  bx_t: number;
  by_t: number;
  b_magnitude_t: number;
  b_parallel_t: number;
  b_perpendicular_t: number;
  az_wb_per_m?: number;
  element_index: number;
}

export interface HalbachContourLevel {
  az_level_t_m: number;
  segments_mm: Array<[number, number, number, number]>;
  segment_bx_t?: number[];
  segment_by_t?: number[];
  segment_b_mag_t?: number[];
}

export interface HalbachReport {
  openem_schema_kind: 'halbach_solution_report';
  openem_schema_version: '1.0';
  configuration: HalbachArrayConfig;
  model: {
    dimensionality: '2d';
    formulation: string;
    axial_end_effects_modeled: false;
    notice: string;
  };
  bore_field: {
    requested_field_direction_deg: number;
    mean_bx_t: number;
    mean_by_t: number;
    center: HalbachFieldSample & { field_direction_error_deg: number };
    mean_field_direction_error_deg: number;
    b_magnitude_t: MetricStatistics;
    b_parallel_t: MetricStatistics;
    b_perpendicular_rms_t: number;
    b_perpendicular_max_abs_t: number;
    uniformity_ppm: number | null;
    ideal_continuous_estimate_t: number;
    segmented_analytical_estimate_t: number;
  };
  external_leakage: {
    probe_radius_mm: number;
    rms_b_t: number;
    max_b_t: number;
    leakage_ratio_rms: number | null;
  };
  magnet: {
    volume_m3: number;
    mass_kg: number | null;
    material: Record<string, unknown>;
    demagnetization_screening: Record<string, unknown>;
  };
  samples: {
    bore: HalbachFieldSample[];
    leakage: HalbachFieldSample[];
  };
  field_data: {
    nodes_mm: Array<[number, number]>;
    triangles: Array<[number, number, number]>;
    region_ids: string[];
    element_fields_t: Array<{ bx: number; by: number; b_mag: number }>;
    az_nodal_t_m: number[];
    contours?: HalbachContourLevel[];
    available_views: string[];
  };
  timings_ms: Record<string, number>;
  peak_memory_bytes: number | null;
  artifacts: Record<string, unknown>;
  magnetostatic_problem: Record<string, unknown>;
  generic_field_report: Record<string, unknown>;
  warnings: string[];
}

export interface LinearHalbachFieldSample {
  x_mm: number;
  y_mm: number;
  bx_t: number;
  by_t: number;
  b_magnitude_t: number;
  element_index: number;
}

export interface LinearHalbachReport {
  openem_schema_kind: 'linear_halbach_solution_report';
  openem_schema_version: '1.0';
  configuration: LinearHalbachArrayConfig;
  model: {
    dimensionality: '2d';
    formulation: string;
    assumption: 'finite_xy_infinite_out_of_plane';
    finite_array_end_fringing_modeled: true;
    out_of_plane_end_effects_modeled: false;
    out_of_plane_depth_usage: string[];
    notice: string;
  };
  working_field: {
    b_magnitude_t: MetricStatistics;
    bx_t: MetricStatistics;
    by_t: MetricStatistics;
    ripple_ppm: number | null;
    line_y_mm: number;
    sample_count: number;
    x_start_mm?: number;
    x_end_mm?: number;
  };
  leakage_field: {
    b_magnitude_t: MetricStatistics;
    bx_t: MetricStatistics;
    by_t: MetricStatistics;
    line_y_mm: number;
    sample_count: number;
    x_start_mm?: number;
    x_end_mm?: number;
  };
  one_sidedness: {
    leakage_ratio_rms: number | null;
    suppression_ratio: number | null;
  };
  magnet: {
    volume_m3: number;
    mass_kg: number | null;
    material: Record<string, unknown>;
    blocks?: Array<Record<string, unknown>>;
    demagnetization_screening?: Record<string, unknown>;
  };
  samples: {
    working: LinearHalbachFieldSample[];
    leakage: LinearHalbachFieldSample[];
  };
  field_data: {
    nodes_mm: Array<[number, number]>;
    triangles: Array<[number, number, number]>;
    region_ids: string[];
    element_fields_t: Array<{ bx: number; by: number; b_mag: number }>;
    az_nodal_t_m: number[];
    contours?: HalbachContourLevel[];
    available_views: string[];
  };
  timings_ms: Record<string, number>;
  peak_memory_bytes: number | null;
  artifacts: Record<string, unknown>;
  magnetostatic_problem: Record<string, unknown>;
  generic_field_report: Record<string, unknown>;
  warnings: string[];
}

export interface MetricStatistics {
  mean: number;
  rms: number;
  standard_deviation: number;
  minimum: number;
  maximum: number;
  peak_to_peak: number;
}

export interface HalbachProjectFile {
  openem_schema_version: number;
  project_kind: 'halbach_array';
  name: string;
  halbach_config: HalbachArrayConfig;
}

export interface LinearHalbachProjectFile {
  openem_schema_version: number;
  project_kind: 'halbach_array';
  name: string;
  halbach_config: LinearHalbachArrayConfig;
}

export interface HalbachSolveProgress {
  stage: string;
  fraction: number;
  percent: number;
}

export const HALBACH_AXIAL_NOTICE =
  '2D cross-section extruded over the design length — axial end effects are not included.';

export const LINEAR_HALBACH_MODEL_NOTICE =
  '2D Magneto2D field extruded for visualization · not a 3D FEM result';

export function cloneDefaultHalbachConfig(): HalbachArrayConfig {
  return {
    kind: 'halbach_array_config',
    version: '1.0',
    units: { length: 'mm', angle: 'deg' },
    geometry: {
      inner_radius: 25,
      outer_radius: 50,
      axial_length: 100,
      segment_count: 16,
      segment_gap_angle: 0,
      segment_start_angle: 0,
    },
    array: {
      field_mode: 'internal',
      multipole_order: 1,
      field_direction: 0,
    },
    magnet: {
      source: 'catalog',
      grade: 'N42',
      temperature_c: 20,
    },
    sample_region: {
      radius: 20,
      radial_samples: 31,
      angular_samples: 96,
      leakage_probe_radius: 75,
    },
    solve: {
      quality: 'standard',
      mesh: {
        density: 'normal',
        outer_boundary_radius_factor: 4,
        minimum_elements_across_magnet: 6,
        corner_refinement: true,
      },
      linear: {
        solver: 'direct',
        tolerance: 1e-8,
        max_iterations: 5000,
      },
    },
  };
}

export function cloneDefaultLinearHalbachConfig(): LinearHalbachArrayConfig {
  return {
    kind: 'linear_halbach_array_config',
    version: '1.0',
    units: { length: 'mm', angle: 'deg' },
    geometry: {
      block_width: 10,
      magnet_height: 10,
      out_of_plane_depth: 100,
      period_count: 4,
      block_gap: 0,
    },
    array: {
      strong_side: 'positive_y',
      phase_deg: 0,
    },
    magnet: {
      source: 'catalog',
      grade: 'N42',
      temperature_c: 20,
    },
    sample_region: {
      probe_offset: 5,
      edge_exclusion_periods: 1,
      samples_per_period: 64,
    },
    solve: {
      quality: 'standard',
      mesh: {
        density: 'normal',
        outer_padding_factor: 2.5,
        minimum_elements_across_magnet: 6,
        corner_refinement: true,
      },
      linear: {
        solver: 'direct',
        pcg_preconditioner: 'incomplete_cholesky',
        tolerance: 1e-8,
        max_iterations: 5000,
      },
      field_line_count: 18,
    },
  };
}
