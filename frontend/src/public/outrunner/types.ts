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
}
export type Analysis = 'source_point' | 'loaded_torque' | 'noload_bemf' | 'both';
