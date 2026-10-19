/**
 * Performance outputs as the backend stores them (backend/models/performance.py):
 * d/q flux linkage, losses, the flux-linkage map, the torque-speed envelope
 * and the efficiency map.
 *
 * Currents are peak phase amperes and flux linkages per-phase peak webers, in
 * the amplitude-invariant d/q frame: T = 1.5·P·(λd·iq − λq·id). The current
 * angle γ is measured from the q-axis, positive toward flux weakening, so
 * id = −I·sin γ and iq = I·cos γ. Speeds are mechanical rpm.
 */

export type PerformanceOutputStatus = 'qualified' | 'experimental' | 'unavailable';
export type CurrentAngleConvention = 'q_axis_gamma_flux_weakening_positive';
export type DqTransform = 'amplitude_invariant_park';

export interface WireSpec {
  wire_bare_diameter_mm: number;
  strands_in_hand?: number;
  insulation_build_mm?: number | null;
  end_turn_extension_mm?: number | null;
  slot_fill_limit?: number | null;
}

export interface DqFluxLinkage {
  current_angle_convention: CurrentAngleConvention;
  transform: DqTransform;
  i_d_A: number;
  i_q_A: number;
  lambda_d_Wb: number;
  lambda_q_Wb: number;
  torque_dq_Nm: number;
  torque_agreement_pct?: number | null;
}

export interface LossBreakdown {
  phase_resistance_ohm: number;
  winding_temperature_C: number;
  copper_loss_W: number;
  copper_active_loss_W: number;
  copper_end_winding_loss_W: number;
  iron_loss_W?: number | null;
  iron_hysteresis_loss_W?: number | null;
  iron_eddy_loss_W?: number | null;
  iron_loss_status: PerformanceOutputStatus;
  iron_loss_status_reason?: string | null;
  mechanical_loss_W: number;
  total_loss_W: number;
  shaft_power_W: number;
  input_power_W: number;
  efficiency_pct?: number | null;
}

export interface FluxLinkageMapPoint {
  current_peak_A: number;
  gamma_deg: number;
  i_d_A: number;
  i_q_A: number;
  status: 'ok' | 'failed' | 'pending';
  avg_torque_Nm?: number | null;
  torque_ripple_pct?: number | null;
  lambda_d_Wb?: number | null;
  lambda_q_Wb?: number | null;
  iron_loss_W?: number | null;
  iron_hysteresis_loss_W?: number | null;
  iron_eddy_loss_W?: number | null;
  nonlinear_iterations_max?: number | null;
  nonlinear_residual_max?: number | null;
  error?: string | null;
}

export interface FluxLinkageMap {
  kind: 'flux_linkage_map';
  schema_version: 1;
  current_angle_convention: CurrentAngleConvention;
  transform: DqTransform;
  scope_key: string;
  pole_pairs: number;
  current_peak_A: number[];
  gamma_deg: number[];
  reference_speed_rpm: number;
  magnet_temperature_C?: number | null;
  rotor_positions: number;
  mesh_density: string;
  torque_method?: string | null;
  points: FluxLinkageMapPoint[];
}

export interface DriveLimits {
  dc_bus_V: number;
  modulation_index_max: number;
  peak_current_A: number;
  continuous_current_A?: number | null;
  max_speed_rpm: number;
}

export type TorqueSpeedRegion = 'mtpa' | 'field_weakening' | 'mtpv';

export interface TorqueSpeedCurve {
  limit: 'peak' | 'continuous';
  speed_rpm: number[];
  torque_Nm: number[];
  power_W: number[];
  i_d_A: number[];
  i_q_A: number[];
  phase_voltage_peak_V: number[];
  region: TorqueSpeedRegion[];
  base_speed_rpm: number;
  max_speed_rpm: number;
  peak_power_W: number;
}

export interface TorqueSpeedEnvelope {
  kind: 'torque_speed_envelope';
  schema_version: 1;
  map_scope_key: string;
  limits: DriveLimits;
  phase_resistance_ohm: number;
  winding_temperature_C: number;
  curves: TorqueSpeedCurve[];
  status: PerformanceOutputStatus;
  status_reason?: string | null;
}

/** Matrices have one row per torque_Nm value and one column per speed_rpm value; null is outside the envelope. */
export interface EfficiencyMap {
  kind: 'efficiency_map';
  schema_version: 1;
  map_scope_key: string;
  speed_rpm: number[];
  torque_Nm: number[];
  efficiency_pct: Array<Array<number | null>>;
  copper_loss_W: Array<Array<number | null>>;
  iron_loss_W: Array<Array<number | null>>;
  mechanical_loss_W: number;
  winding_temperature_C: number;
  status: PerformanceOutputStatus;
  status_reason?: string | null;
}
