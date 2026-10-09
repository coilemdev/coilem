"""Result models for the public Magneto2D solve boundary."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .field import FieldLineFrame, FieldLinePlot, FieldMovieManifest, SlotExcitationContribution, SlotExcitationFrame
from .mesh import FluxDensityMap
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
    slot_excitation_contributions: list[SlotExcitationContribution] | None = None
    solve_time_s: float = Field(ge=0)


class SolveMetadata(BaseModel):
    solver_environment: dict | None = Field(default=None, description="Recorded native environment policy and request-derived options")
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
    rated_speed_rpm: int | None = Field(default=None, ge=0, le=30000)
    motor_input_dc_bus_V: float | None = Field(default=None, ge=1, le=2000)
    solve_cache_dir: str | None = None
    pipeline_stage: Literal["field_solve", "postprocess"] | None = None
    postprocess_source_cache_dir: str | None = None
    postprocess_time_s: float | None = Field(default=None, ge=0)
    solve_time_s: float | None = Field(default=None, ge=0)
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
    solve_metadata: SolveMetadata
