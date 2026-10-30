"""Result models for the public Magneto2D solve boundary."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .field import FieldLineFrame, FieldLinePlot, FieldMovieManifest, SlotExcitationContribution, SlotExcitationFrame
from .mesh import FluxDensityMap
from .performance import DqFluxLinkage, LossBreakdown
from .waveforms import (
    BackEMFHarmonicAnalysis,
    BackEMFWaveform,
    PhaseCurrentWaveform,
    TorqueWaveform,
)


class SolveSummary(BaseModel):
    avg_torque_Nm: float
    avg_torque_energy_fd_Nm: float | None = None
    avg_torque_coenergy_fd_Nm: float | None = None
    avg_torque_field_fd_Nm: float | None = None
    avg_torque_pm_source_work_fd_Nm: float | None = None
    avg_torque_current_source_work_fd_Nm: float | None = None
    torque_q_axis_Nm: float | None = None
    torque_ripple_pct: float = Field(ge=0)
    cogging_torque_Nm: float | None = None
    back_emf_fundamental_V: float = Field(ge=0)
    back_emf_thd_pct: float | None = Field(default=None, ge=0)
    Kt_Nm_per_A: float | None = None
    Ke_Vs_per_rad_mech: float | None = Field(default=None, ge=0)
    lambda_pm_Wb: float | None = Field(default=None, ge=0)
    peak_flux_density_teeth_T: float = Field(ge=0)
    peak_flux_density_yoke_T: float = Field(ge=0)
    rms_flux_density_teeth_T: float | None = Field(default=None, ge=0)
    rms_flux_density_yoke_T: float | None = Field(default=None, ge=0)
    dq_flux_linkage: DqFluxLinkage | None = None
    loss_breakdown: LossBreakdown | None = None
    slot_excitation_contributions: list[SlotExcitationContribution] | None = None
    solve_time_s: float = Field(ge=0)


class NonlinearConvergence(BaseModel):
    """One position's accepted field solve; reused records describe its source."""

    method: Literal["picard", "newton", "linear"]
    iterations: int = Field(ge=1)
    max_iterations: int = Field(ge=1)
    stage_iterations: list[int]
    stage_iteration_cap: int = Field(ge=1)
    raw_max_residual: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    scaled_residual: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    rhs_scaled_residual: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    initial_rhs_scaled_residual: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    absolute_residual_floor: float | None = Field(default=None, gt=0, lt=1, allow_inf_nan=False)
    residual_definition: str
    tolerance: float = Field(ge=0, lt=1, allow_inf_nan=False)
    stopping_test: str
    solution_reused: bool = False
    fallback_from: str | None = None


class NonlinearToleranceSetting(BaseModel):
    """A recorded threshold, labelled by method and residual definition."""

    method: Literal["picard", "newton"]
    residual_definition: str
    tolerance: float = Field(gt=0, lt=1, allow_inf_nan=False)
    absolute_residual_floor: float | None = Field(default=None, gt=0, lt=1, allow_inf_nan=False)


class SolveMetadata(BaseModel):
    solver_environment: dict | None = Field(default=None, description="Recorded native environment policy and request-derived options")
    reference_model: dict | None = None
    solver_name: str
    mesh_element_count: int = Field(ge=100)
    rotor_positions: int = Field(ge=2)
    timestamp: datetime
    current_amplitude_A: float | None = Field(default=None, ge=0, le=1000)
    excitation_mode: str | None = None
    current_amplitude_convention: str | None = None
    commutation_advance_deg: float | None = None
    phase_connection: str | None = None
    excitation_convention_version: str | None = None
    loaded_cycle_complete: bool | None = None
    back_emf_computed: bool | None = Field(default=None, description="Whether this run computed the no-load back-EMF sweep")
    rated_speed_rpm: int | None = Field(default=None, ge=0, le=30000)
    motor_input_dc_bus_V: float | None = Field(default=None, ge=1, le=2000)
    magnet_temperature_C: float | None = Field(default=None, ge=-50, le=300)
    magnet_remanence_T: float | None = Field(default=None, gt=0, description="Br used by the solve, after temperature derating")
    magnet_intrinsic_coercivity_kA_m: float | None = Field(
        default=None, gt=0, description="Hcj used by the solve, after temperature derating"
    )
    winding_temperature_C: float | None = Field(default=None, ge=-50, le=250)
    solve_cache_dir: str | None = None
    pipeline_stage: Literal["field_solve", "postprocess"] | None = None
    postprocess_source_cache_dir: str | None = None
    postprocess_time_s: float | None = Field(default=None, ge=0)
    solve_time_s: float | None = Field(default=None, ge=0)
    solver_cpu_time_s: float | None = Field(
        default=None,
        ge=0,
        description="Sum of every rotor position's solver process time; positions run in parallel",
    )
    mesher: str | None = None
    mesh_density: str | None = None
    mesh_source: str | None = None
    mesh_source_detail: str | None = None
    geometry_ir_version: str | None = None
    rotor_rotation_model: str | None = None
    torque_method: Literal[
        "arkkio",
        "contour",
        "mst",
        "energy_fd",
        "coenergy_fd",
        "weighted_stress",
        "weighted_stress_centered",
    ] | None = None
    nonlinear_tolerance: float | None = Field(default=None, gt=0, lt=1)
    nonlinear_tolerance_method: Literal["picard", "newton"] | None = None
    nonlinear_tolerance_settings: list[NonlinearToleranceSetting] | None = None
    solve_quality: Literal["quick", "standard", "fine", "custom"] | None = None
    nonlinear_max_iterations_used: int | None = Field(default=None, ge=1)
    nonlinear_median_iterations: float | None = Field(default=None, ge=1)
    nonlinear_worst_final_mismatch: float | None = Field(default=None, ge=0)
    nonlinear_worst_tolerance_ratio: float | None = Field(default=None, ge=0)
    nonlinear_residual_definitions: list[str] | None = None
    topology: str | None = None
    physics_contract_version: str | None = None
    region_source: str | None = None
    current_source: str | None = None
    magnetization_source: str | None = None
    material_source: str | None = None
    solver_lane_reason: str | None = None


class SolveResult(BaseModel):
    summary: SolveSummary
    torque_waveform: TorqueWaveform
    phase_current_waveform: PhaseCurrentWaveform | None = None
    cogging_torque_waveform: TorqueWaveform | None = None
    back_emf_waveform: BackEMFWaveform
    back_emf_harmonic_analysis: BackEMFHarmonicAnalysis | None = None
    flux_density_map: FluxDensityMap | None = None
    field_line_plot: FieldLinePlot | None = None
    field_line_frames: list[FieldLineFrame] | None = None
    field_movie: FieldMovieManifest | None = None
    field_line_movie: FieldMovieManifest | None = None
    slot_excitation_frames: list[SlotExcitationFrame] | None = None
    loaded_nonlinear_iterations: list[int] | None = None
    no_load_nonlinear_iterations: list[int] | None = None
    loaded_nonlinear_convergence: list[NonlinearConvergence | None] | None = None
    no_load_nonlinear_convergence: list[NonlinearConvergence | None] | None = None
    solve_metadata: SolveMetadata
