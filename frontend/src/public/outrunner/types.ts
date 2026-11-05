export interface Curve {
  angles_electrical_deg: number[];
  torque_Nm: number[];
  phase_linkage_Wb: number[][];
  bemf_phase_V?: number[][];
  bemf_line_to_line_V?: number[][];
  bemf_phase_fundamental?: { peak: number[] };
}
export interface RunState {
  run_id: string; status: string; completed: number; total: number; error?: string;
  curves?: { loaded?: Curve; noload?: Curve };
  rows?: Array<{ outer_rotor_torque_Nm: number; phase_linkage_Wb: number[] }>;
  elapsed_s?: number;
  stage?: string;
  current_angle_ccw_deg?: number;
  estimated_remaining_range_s?: [number, number];
  estimate?: RunEstimate;
}
export type Analysis = 'source_point' | 'loaded_torque' | 'noload_bemf' | 'both';

export interface RunEstimate {
  positions: number;
  total_range_s: [number, number];
  point_range_s: [number, number];
  basis: string;
  observed_points: number;
  plans: Record<'preview' | 'standard' | 'high_accuracy', {
    label: string; accuracy_plan: 'preview' | 'standard' | 'high_accuracy'; unique_samples: 24 | 48 | 96;
    gap_size_mm: .1 | .05 | .025; bulk_size_mm: .5 | .25; nonlinear_tolerance: .00001 | .000001;
  }>;
}
