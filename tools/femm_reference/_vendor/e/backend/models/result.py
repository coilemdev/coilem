"""Solve summary, metadata, and the top-level SolveResult envelope.

Extracted from backend/models.py during Sprint 27 Track 1C; class bodies verbatim.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .diagnostics import (
    AnalyticalCrosscheck,
    DemagCheck,
    LoadedFieldDiagnostic,
    LossBreakdown,
    SlotFillCheck,
    SlotlessNoLoadDiagnostic,
    ThermalEstimate,
    TorqueSpeedEnvelope,
    WeightInertia,
)
from .field import (
    FieldLineFrame,
    FieldLinePlot,
    FieldMovieManifest,
    SlotExcitationContribution,
    SlotExcitationFrame,
)
from .mesh import FemmMeshSummary, FluxDensityMap
from .waveforms import (
    BackEMFHarmonicAnalysis,
    BackEMFWaveform,
    PhaseCurrentWaveform,
    TorqueWaveform,
)


class SolveSummary(BaseModel):
    """High-level performance metrics from solve."""

    avg_torque_Nm: float = Field(..., description="Average torque in N·m")
    avg_torque_energy_fd_Nm: Optional[float] = Field(
        default=None,
        description=(
            "Average finite-difference torque from magnetic potential energy over the sampled sweep."
        ),
    )
    avg_torque_coenergy_fd_Nm: Optional[float] = Field(
        default=None,
        description="Average finite-difference torque from magnetic co-energy over the sampled sweep.",
    )
    # Sprint 25 instrumentation: FD torque decomposed by energy component.
    # On a consistent loaded solve, avg_torque_energy_fd_Nm should equal
    # `avg_torque_field_fd_Nm − avg_torque_pm_source_work_fd_Nm − avg_torque_current_source_work_fd_Nm`.
    # Whichever component fails to pick up the load DC is the one to fix.
    avg_torque_field_fd_Nm: Optional[float] = Field(
        default=None,
        description=(
            "Diagnostic: avg of dE_field/dtheta. Should track the field-energy contribution "
            "to the torque (positive for motoring on a typical SPM)."
        ),
    )
    avg_torque_pm_source_work_fd_Nm: Optional[float] = Field(
        default=None,
        description=(
            "Diagnostic: avg of d(pm_source_work)/dtheta. Captures how the PM-bound-current "
            "source-work term varies with rotor angle."
        ),
    )
    avg_torque_current_source_work_fd_Nm: Optional[float] = Field(
        default=None,
        description=(
            "Diagnostic: avg of d(current_source_work)/dtheta. Should be the dominant DC "
            "contributor on loaded runs; ~0 on no-load."
        ),
    )
    torque_q_axis_Nm: Optional[float] = Field(
        default=None,
        description=(
            "Loaded torque sample nearest q-axis alignment in N·m. For SPM this is "
            "the sample closest to 0 electrical degrees, distinct from full-sweep average torque."
        ),
    )
    torque_ripple_pct: float = Field(..., ge=0, description="Torque ripple in %")
    cogging_torque_Nm: Optional[float] = Field(default=None, description="Cogging torque in N·m")
    back_emf_fundamental_V: float = Field(..., ge=0, description="Back-EMF fundamental in V")
    back_emf_thd_pct: Optional[float] = Field(
        default=None,
        ge=0,
        description="Headline phase-A Back-EMF THD through H12 in % for versioned analyses",
    )
    back_emf_thd_h6_pct: Optional[float] = Field(
        default=None,
        ge=0,
        description="Legacy phase-A Back-EMF THD through H6 in %",
    )
    back_emf_thd_h12_pct: Optional[float] = Field(
        default=None,
        ge=0,
        description="Phase-A Back-EMF THD through H12 in %",
    )
    back_emf_thd_h24_pct: Optional[float] = Field(
        default=None,
        ge=0,
        description="Extended phase-A Back-EMF THD through H24 in %",
    )
    back_emf_line_thd_h12_pct: Optional[float] = Field(
        default=None,
        ge=0,
        description="Line-to-line AB Back-EMF THD through H12 in %",
    )
    back_emf_line_thd_h24_pct: Optional[float] = Field(
        default=None,
        ge=0,
        description="Line-to-line AB Back-EMF THD through H24 in %",
    )
    # Derived machine constants (see backend/machine_constants.py for formulas
    # and conventions). All three are optional — None when the solve regime
    # (no-load or DC) leaves them undefined rather than zero.
    Kt_Nm_per_A: Optional[float] = Field(
        default=None,
        description=(
            "Torque constant: avg_torque / current_amplitude, Nm per peak phase amp."
        ),
    )
    Ke_Vs_per_rad_mech: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Voltage constant: peak-L-N back-EMF fundamental / mechanical angular speed, V·s/rad."
        ),
    )
    lambda_pm_Wb: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Peak PM flux linkage fundamental amplitude per phase, Wb. Equals Ke / pole_pairs."
        ),
    )
    peak_flux_density_teeth_T: float = Field(
        ..., ge=0, description="Peak flux density in teeth in Tesla"
    )
    peak_flux_density_yoke_T: float = Field(
        ..., ge=0, description="Peak flux density in yoke in Tesla"
    )
    rms_flux_density_teeth_T: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Area-weighted RMS flux density in stator teeth in Tesla, when "
            "computed from stored field-frame element data."
        ),
    )
    rms_flux_density_yoke_T: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Area-weighted RMS flux density in stator yoke in Tesla, when "
            "computed from stored field-frame element data."
        ),
    )
    efficiency_pct: Optional[float] = Field(
        default=None, ge=0, description="Efficiency estimate in %"
    )
    loss_breakdown: Optional[LossBreakdown] = Field(
        default=None, description="Detailed loss breakdown (S8-01)"
    )
    weight_inertia: Optional[WeightInertia] = Field(
        default=None, description="Weight breakdown and rotor inertia (S8-02)"
    )
    torque_speed_envelope: Optional[TorqueSpeedEnvelope] = Field(
        default=None, description="Torque-speed characteristic curve (S8-03)"
    )
    thermal_estimate: Optional[ThermalEstimate] = Field(
        default=None, description="Steady-state thermal estimate (S8-04)"
    )
    demag_check: Optional[DemagCheck] = Field(
        default=None, description="Demagnetization risk assessment (S8-05)"
    )
    slot_fill_check: Optional[SlotFillCheck] = Field(
        default=None, description="Slot fill factor feasibility (S8-06)"
    )
    slot_excitation_contributions: Optional[list[SlotExcitationContribution]] = Field(
        default=None,
        description=(
            "Per-slot ampere-turn breakdown for the loaded operating point. "
            "Populated by both native (magneto2d) and FEMM. Used by the "
            "Compare view's slot excitation panel to surface current-side "
            "scaling discrepancies between solvers."
        ),
    )
    solve_time_s: float = Field(..., ge=0, description="Solve time in seconds")


class SolveMetadata(BaseModel):
    """Metadata about the solve run."""

    solver_name: str = Field(..., description="Solver name and version")
    mesh_element_count: int = Field(..., ge=100, description="Number of mesh elements")
    rotor_positions: int = Field(..., ge=2, description="Number of rotor positions")
    timestamp: datetime = Field(..., description="ISO 8601 timestamp of solve")
    current_amplitude_A: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1000 * 2**0.5,
        description=(
            "Resolved peak phase current used for this solve [A]. The upper "
            "bound includes the public input contract's 1000 A RMS maximum."
        ),
    )
    excitation_mode: Optional[str] = Field(
        default=None,
        description="Resolved stator excitation mode for this solve.",
    )
    current_amplitude_convention: Optional[str] = Field(
        default=None,
        description="Meaning of current_amplitude_A: peak, rms, or plateau.",
    )
    commutation_advance_deg: Optional[float] = Field(
        default=None,
        description="Six-step commutation advance in public electrical degrees.",
    )
    phase_connection: Optional[str] = Field(
        default=None,
        description="Resolved terminal phase connection.",
    )
    excitation_convention_version: Optional[str] = Field(
        default=None,
        description="Version of the exact excitation table and angle convention.",
    )
    loaded_cycle_complete: Optional[bool] = Field(
        default=None,
        description=(
            "Whether the loaded torque/current waveform is a uniform complete "
            "electrical cycle. Populated for ideal six-step results."
        ),
    )
    rated_speed_rpm: Optional[int] = Field(
        default=None,
        ge=0,
        le=30000,
        description="Operating speed used for this solve [RPM]",
    )
    motor_input_dc_bus_V: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=2000.0,
        description="Motor inverter DC-link voltage used for voltage-headroom reporting [Vdc]",
    )
    solve_cache_dir: Optional[str] = Field(default=None, description="Path to solve cache directory with .fem files")
    pipeline_stage: Optional[Literal["field_solve", "postprocess"]] = Field(
        default=None,
        description=(
            "Pipeline stage that produced this result. 'field_solve' means the "
            "FEA fields were solved in this run; 'postprocess' means cached "
            "field reports were reused and only result extraction was rebuilt."
        ),
    )
    postprocess_source_cache_dir: Optional[str] = Field(
        default=None,
        description="Source solve cache directory reused for postprocess-only result rebuilds",
    )
    postprocess_time_s: Optional[float] = Field(
        default=None,
        ge=0,
        description="Wall time spent rebuilding result metrics from cached field reports",
    )
    solve_time_s: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Actual wall time for the field solve/run in seconds. Duplicated "
            "from summary.solve_time_s so run-history records can mine timing "
            "without unpacking the full summary payload."
        ),
    )
    mesher: Optional[str] = Field(
        default=None,
        description=(
            "Mesher backend used for this solve. New native solves use 'gmsh'; "
            "None for non-magneto2d solvers."
        ),
    )
    mesh_density: Optional[str] = Field(
        default=None,
        description="Mesh density preset used for this solve, when exposed by the solver.",
    )
    mesh_source: Optional[str] = Field(
        default=None,
        description=(
            "Mesh source used for this solve. Magneto2D uses 'native' by default "
            "or 'femm' when solving on an imported FEMM mesh."
        ),
    )
    mesh_source_detail: Optional[str] = Field(
        default=None,
        description=(
            "More specific mesh construction path, such as 'geometry_ir' for "
            "Gmsh meshes generated from Geometry IR."
        ),
    )
    geometry_ir_version: Optional[str] = Field(
        default=None,
        description="Geometry IR schema/version used to build the mesh, when applicable.",
    )
    rotor_rotation_model: Optional[str] = Field(
        default=None,
        description=(
            "Rotor-position handling used for the field solve, e.g. "
            "'fixed_mesh' or 'remesh_per_step' for Magneto2D."
        ),
    )
    torque_method: Optional[
        Literal[
            "arkkio",
            "contour",
            "mst",
            "energy_fd",
            "coenergy_fd",
            "weighted_stress",
            "weighted_stress_centered",
        ]
    ] = Field(
        default=None,
        description="Torque extractor used for the app-facing torque waveform.",
    )
    nonlinear_tolerance: Optional[float] = Field(
        default=None,
        gt=0.0,
        lt=1.0,
        description="Magneto2D nonlinear convergence tolerance used for the field solve.",
    )
    topology: Optional[str] = Field(
        default=None,
        description="The rotor/stator topology name (e.g. 'SPM', 'IPM').",
    )
    physics_contract_version: Optional[str] = Field(
        default=None,
        description="Version of the imported physics contract used, if any.",
    )
    region_source: Optional[str] = Field(
        default=None,
        description="Provenance source for geometry regions.",
    )
    current_source: Optional[str] = Field(
        default=None,
        description="Provenance source for current density.",
    )
    magnetization_source: Optional[str] = Field(
        default=None,
        description="Provenance source for magnet magnetization.",
    )
    material_source: Optional[str] = Field(
        default=None,
        description="Provenance source for imported material assignment.",
    )
    solver_lane_reason: Optional[str] = Field(
        default=None,
        description=(
            "Why solve routing moved this run off the selected solver lane, "
            "e.g. the native Magneto2D support gap that sent a distributed-"
            "winding config to FEMM. None when the run stayed on the "
            "originally selected lane."
        ),
    )


class SolveResult(BaseModel):
    """Complete solve result."""

    summary: SolveSummary = Field(..., description="Performance summary")
    torque_waveform: TorqueWaveform = Field(..., description="Torque waveform")
    phase_current_waveform: Optional[PhaseCurrentWaveform] = Field(
        default=None,
        description="Exact terminal phase currents aligned to the loaded torque waveform.",
    )
    cogging_torque_waveform: Optional[TorqueWaveform] = Field(
        default=None,
        description="Optional zero-current cogging torque waveform over one cogging period",
    )
    back_emf_waveform: BackEMFWaveform = Field(..., description="Back-EMF waveform")
    back_emf_harmonic_analysis: Optional[BackEMFHarmonicAnalysis] = Field(
        default=None,
        description=(
            "Versioned no-load Back-EMF spectrum derived directly from periodic "
            "flux-linkage samples"
        ),
    )
    flux_density_map: Optional[FluxDensityMap] = Field(default=None, description="Flux density map")
    field_line_plot: Optional[FieldLinePlot] = Field(
        default=None,
        description="Solved mesh and A_z contour geometry for field-line rendering",
    )
    field_line_frames: Optional[list[FieldLineFrame]] = Field(
        default=None,
        description=(
            "Optional per-angle solved field frames for Compare's visual "
            "solver parity panel. Large report bundles may include these; "
            "browser localStorage intentionally slims them out."
        ),
    )
    field_movie: Optional[FieldMovieManifest] = Field(
        default=None,
        description=(
            "Backend-packaged field heatmap movie. Frames are pre-rasterized "
            "to WebP/PNG with a uniform colormap so the frontend can replay "
            "without flicker and without rebuilding raster frames in the browser."
        ),
    )
    field_line_movie: Optional[FieldMovieManifest] = Field(
        default=None,
        description=(
            "Backend-packaged field-line movie. Frames are pre-rasterized "
            "to transparent WebP/PNG so playback can use cached image frames "
            "instead of rebuilding contour SVG paths from field artifacts."
        ),
    )
    slot_excitation_frames: Optional[list[SlotExcitationFrame]] = Field(
        default=None,
        description=(
            "Optional per-angle slot excitation frames for Compare's "
            "matched-angle current-mapping panel."
        ),
    )
    femm_mesh: Optional[FemmMeshSummary] = Field(
        default=None,
        description="Optional FEMM mesh triangulation captured during solve; used for mesh overlay visualization",
    )
    solve_metadata: SolveMetadata = Field(..., description="Solve metadata")
    analytical_crosscheck: Optional[AnalyticalCrosscheck] = Field(
        default=None,
        description="Independent analytical cross-check of key metrics (computed from first-principles, not FEA)",
    )
    slotless_noload_diagnostic: Optional[SlotlessNoLoadDiagnostic] = Field(
        default=None,
        description="Optional no-load comparison payload for debug workflows",
    )
    loaded_field_diagnostic: Optional[LoadedFieldDiagnostic] = Field(
        default=None,
        description="Optional loaded field comparison payload for debug workflows",
    )
    thermal_loss_map: Optional[dict] = Field(
        default=None,
        description=(
            "Per-triangle heat-source artifact (thermal_loss_map/v2) derived "
            "from this EM solve. Active-stack copper feeds 2D FEA; end-winding "
            "copper remains explicit for the pending hybrid end network."
        ),
    )
    core_loss_density_w_per_m3: Optional[list[float]] = Field(
        default=None,
        description=(
            "Per-triangle stator core-loss density [W/m³] from magneto2d fixed-mesh "
            "sweeps (opt-in via OPENEM_MAGNETO2D_EMIT_CORE_LOSS_DENSITY / "
            "OPENEM_THERMAL_ENABLED). Intensive; sector-invariant."
        ),
    )
