"""Performance, analytical-crosscheck, and slotless/loaded diagnostic models.

Extracted from backend/models.py during Sprint 27 Track 1C; class bodies verbatim.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .field import FieldLinePlot


class LossBreakdown(BaseModel):
    """Detailed motor loss breakdown at rated operating point."""

    copper_loss_W: float = Field(..., ge=0, description="I²R copper losses in Watts (3-phase total)")
    core_loss_W: float = Field(..., ge=0, description="Iron core losses in Watts (Steinmetz model)")
    hysteresis_loss_W: float = Field(..., ge=0, description="Hysteresis component of core loss")
    eddy_current_loss_W: float = Field(..., ge=0, description="Eddy current component of core loss")
    total_loss_W: float = Field(..., ge=0, description="Total electrical losses in Watts")
    mechanical_power_W: float = Field(..., ge=0, description="Shaft output power in Watts")
    input_power_W: float = Field(..., ge=0, description="Electrical input power in Watts")
    stator_core_mass_kg: float = Field(..., ge=0, description="Stator iron mass used for core loss")
    rotor_core_mass_kg: float = Field(..., ge=0, description="Rotor iron mass (informational)")
    phase_resistance_ohm: float = Field(..., ge=0, description="Estimated per-phase winding resistance")
    active_copper_loss_W: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Copper I²R assigned to conductors inside the active stack. This is "
            "the copper source consumed by the 2D cross-section thermal solve."
        ),
    )
    end_winding_copper_loss_W: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Copper I²R assigned to axial end turns. Retained for the hybrid "
            "end-region network and never smeared into the 2D active stack."
        ),
    )
    active_copper_fraction: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Active conductor length divided by mean-turn length; used to split "
            "total copper I²R between the 2D stack and unresolved end windings."
        ),
    )
    # Immutable EM-result fingerprint for thermal freshness (S49 review P1).
    # Optional so legacy results still deserialize; thermal API rejects when absent.
    em_result_identity: Optional[dict] = Field(
        default=None,
        description=(
            "Immutable operating-point / mesh identity stamped at EM solve time. "
            "Thermal refuses untagged or mismatched breakdowns."
        ),
    )


class WeightInertia(BaseModel):
    """Motor weight breakdown and rotor inertia estimate."""

    stator_core_kg: float = Field(..., ge=0, description="Stator iron mass (yoke + teeth)")
    rotor_core_kg: float = Field(..., ge=0, description="Rotor iron mass")
    magnet_kg: float = Field(..., ge=0, description="Total magnet mass")
    copper_kg: float = Field(..., ge=0, description="Total winding copper/aluminum mass")
    total_mass_kg: float = Field(..., ge=0, description="Total active motor mass")
    rotor_inertia_kg_m2: float = Field(..., ge=0, description="Rotor moment of inertia about shaft axis")
    stack_length_mm: float = Field(..., ge=0, description="Axial stack length")
    active_volume_cm3: float = Field(..., ge=0, description="Active volume (stator OD envelope)")


class DemagCheck(BaseModel):
    """Demagnetization risk assessment at rated operating point."""

    magnet_operating_B_T: float = Field(..., description="Estimated magnet operating flux density [T]")
    magnet_knee_B_T: float = Field(..., description="B at knee point of B-H curve [T]")
    remanence_T: float = Field(..., ge=0, description="Magnet remanence Br [T]")
    coercivity_kA_m: float = Field(..., description="Intrinsic coercivity Hci [kA/m]")
    demagnetization_margin_pct: float = Field(..., description="Margin above knee as % of Br")
    risk_level: str = Field(..., description="Risk level: safe, marginal, or at_risk")
    # S48-03: optional temperature context. Absent ⇒ room-temp catalog props.
    magnet_temperature_C: float | None = Field(
        default=None,
        description="Magnet temperature used for Br(T)/Hc(T) derating [C]",
    )
    remanence_room_temp_T: float | None = Field(
        default=None,
        description="Catalog Br at reference temperature before derating [T]",
    )
    knee_crossed: bool = Field(
        default=False,
        description="True when operating B is at or below the knee (irreversible demag risk)",
    )


class SlotFillCheck(BaseModel):
    """Slot fill factor feasibility check."""

    slot_area_mm2: float = Field(..., ge=0, description="Available slot area [mm²]")
    wire_area_mm2: float = Field(..., ge=0, description="Total conductor cross-section [mm²]")
    fill_factor: float = Field(..., ge=0, description="Computed fill factor (wire/slot)")
    max_fill_factor: float = Field(default=0.65, description="Maximum feasible fill factor")
    feasible: bool = Field(..., description="Whether winding physically fits")
    conductors_per_slot: int = Field(..., ge=0, description="Total conductors per slot")


class ThermalEstimate(BaseModel):
    """Steady-state lumped-parameter thermal estimate."""

    winding_temp_C: float = Field(..., description="Estimated winding hot-spot temperature [C]")
    stator_core_temp_C: float = Field(..., description="Estimated stator iron temperature [C]")
    magnet_temp_C: float = Field(..., description="Estimated magnet temperature [C]")
    ambient_temp_C: float = Field(default=40.0, description="Assumed ambient temperature [C]")
    winding_temp_rise_K: float = Field(..., ge=0, description="Winding temperature rise above ambient [K]")
    max_continuous_current_A: float = Field(..., ge=0, description="Max current for class H (180C) limit [A]")
    insulation_class: str = Field(default="H", description="Insulation class used for thermal limit")
    thermal_margin_K: float = Field(..., description="Margin to insulation limit [K], negative = over limit")


class TorqueSpeedEnvelope(BaseModel):
    """Torque-speed characteristic curve with constant-torque and field-weakening regions."""

    method: str = Field(default="solver_current_sweep", description="How this torque-speed data was generated")
    speed_rpm: list[float] = Field(..., description="Speed points in RPM")
    torque_Nm: list[float] = Field(..., description="Maximum torque at each speed point")
    power_W: list[float] = Field(..., description="Mechanical power at each speed point")
    base_speed_rpm: float = Field(..., ge=0, description="Base speed (end of constant-torque region)")
    max_speed_rpm: float = Field(..., ge=0, description="Maximum speed (end of field-weakening)")
    peak_power_W: float = Field(..., ge=0, description="Peak mechanical power")
    rated_torque_Nm: float = Field(..., ge=0, description="Torque in constant-torque region")


class AnalyticalCrosscheck(BaseModel):
    """Independent analytical cross-check of solver results.

    Computed from first-principles magnetic circuit theory (not FEA).
    Provides user-facing confidence that the solver output is physically
    plausible. Each metric includes the analytical prediction, the solver
    value, and the deviation percentage.
    """

    torque_analytical_Nm: float = Field(..., description="Analytical torque prediction [Nm]")
    torque_solver_Nm: float = Field(..., description="Solver torque result [Nm]")
    torque_deviation_pct: float = Field(..., description="Torque deviation (solver vs analytical) [%]")
    back_emf_analytical_V: float = Field(..., description="Analytical back-EMF prediction [V]")
    back_emf_solver_V: Optional[float] = Field(default=None, description="Solver back-EMF result [V]")
    back_emf_deviation_pct: Optional[float] = Field(default=None, description="Back-EMF deviation [%]")
    airgap_flux_density_T: float = Field(..., description="Analytical airgap flux density [T]")
    peak_b_teeth_analytical_T: Optional[float] = Field(default=None, description="Analytical peak tooth flux density [T]")
    peak_b_teeth_solver_T: Optional[float] = Field(default=None, description="Solver peak tooth flux density [T]")
    peak_b_teeth_deviation_pct: Optional[float] = Field(default=None, description="Peak B teeth deviation [%]")
    peak_b_yoke_analytical_T: Optional[float] = Field(default=None, description="Analytical peak yoke flux density [T]")
    peak_b_yoke_solver_T: Optional[float] = Field(default=None, description="Solver peak yoke flux density [T]")
    peak_b_yoke_deviation_pct: Optional[float] = Field(default=None, description="Peak B yoke deviation [%]")
    thd_analytical_pct: Optional[float] = Field(default=None, description="Analytical THD from winding harmonics [%]")
    thd_solver_pct: Optional[float] = Field(default=None, description="Solver THD from FFT [%]")
    thd_deviation_pct: Optional[float] = Field(default=None, description="THD deviation [%]")
    winding_factor: float = Field(..., description="Fundamental winding factor k_w1")
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Overall confidence: high (<15%), medium (15-35%), low (>35%)"
    )
    warnings: list[str] = Field(default=[], description="Specific deviation warnings")


class DiagnosticSeriesPoint(BaseModel):
    """One compared diagnostic sample versus rotor angle."""

    mechanical_angle_deg: float = Field(..., description="Rotor mechanical angle [deg]")
    electrical_angle_deg: float = Field(..., description="Rotor electrical angle [deg]")
    torque_Nm: float = Field(..., description="Torque at this angle [N·m]")
    a_z_wb_per_m: Optional[float] = Field(
        default=None,
        description="Vector potential A_z at the diagnostic probe [Wb/m]",
    )
    b_x_t: Optional[float] = Field(
        default=None,
        description="Cartesian B_x component at the diagnostic probe [T]",
    )
    b_y_t: Optional[float] = Field(
        default=None,
        description="Cartesian B_y component at the diagnostic probe [T]",
    )
    b_r_t: float = Field(..., description="Radial flux-density component at the diagnostic probe [T]")
    b_t_t: float = Field(..., description="Tangential flux-density component at the diagnostic probe [T]")


class DiagnosticSeries(BaseModel):
    """All diagnostic samples from one solver."""

    solver_name: str = Field(..., description="Solver label")
    points: list[DiagnosticSeriesPoint] = Field(
        ..., min_length=2, description="Samples over the diagnostic angle sweep"
    )
    field_line_plot: Optional[FieldLinePlot] = Field(
        default=None,
        description="Optional field-line snapshot taken at the diagnostic snapshot angle",
    )


class SlotlessContourTorqueDiagnostic(BaseModel):
    """Native contour-torque diagnostics captured for the slotless workflow."""

    mid_gap_torque_nm: float = Field(..., description="Mid-gap contour torque in N·m")
    inner_torque_nm: float = Field(..., description="Inner full-coverage contour torque in N·m")
    outer_torque_nm: float = Field(..., description="Outer full-coverage contour torque in N·m")
    contour_radius_mm: float = Field(..., ge=0, description="Primary mid-gap contour radius in mm")
    notes: str = Field(..., description="Human-readable multi-radius contour diagnostics")


class SlotlessContourSamplePoint(BaseModel):
    """One circumferential sample taken around the slotless airgap contour."""

    contour_angle_deg: float = Field(..., ge=0, le=360, description="Circumferential sample angle in mechanical degrees")
    a_z_wb_per_m: Optional[float] = Field(
        default=None,
        description="Vector potential sample at the contour point [Wb/m]",
    )
    b_x_t: Optional[float] = Field(
        default=None,
        description="Cartesian B_x component at the contour point [T]",
    )
    b_y_t: Optional[float] = Field(
        default=None,
        description="Cartesian B_y component at the contour point [T]",
    )
    b_r_t: float = Field(..., description="Radial flux-density component at the contour point [T]")
    b_t_t: float = Field(..., description="Tangential flux-density component at the contour point [T]")
    br_bt_t2: float = Field(..., description="Pointwise B_r · B_t product at the contour point [T²]")
    torque_contribution_nm: float = Field(
        ...,
        description="Incremental contour torque contribution from this sample [N·m]",
    )
    cumulative_torque_nm: float = Field(
        ...,
        description="Running cumulative contour torque integral through this sample [N·m]",
    )


class SlotlessContourComparison(BaseModel):
    """Full circumferential contour comparison for the slotless diagnostic."""

    radius_mm: float = Field(..., gt=0, description="Contour radius in mm")
    sample_count: int = Field(..., ge=3, description="Number of samples around the contour")
    magneto2d_points: list[SlotlessContourSamplePoint] = Field(
        ...,
        min_length=3,
        description="Native FEM nodal-smoothed contour samples around the full airgap",
    )
    magneto2d_element_points: Optional[list[SlotlessContourSamplePoint]] = Field(
        default=None,
        description="Native FEM element-constant contour samples around the full airgap",
    )
    magneto2d_az_derived_points: Optional[list[SlotlessContourSamplePoint]] = Field(
        default=None,
        description="Native FEM contour samples derived from interpolated A_z gradients",
    )
    femm_points: list[SlotlessContourSamplePoint] = Field(
        ...,
        min_length=3,
        description="FEMM reference contour samples around the full airgap",
    )


class MultiRadiusSlottingDeltaSummary(BaseModel):
    """Slotting-delta mismatch summary evaluated across multiple airgap radii."""

    radius_mm: float = Field(..., gt=0, description="Contour radius in mm")
    airgap_position_pct: float = Field(
        ...,
        ge=0,
        le=100,
        description="Normalized airgap position from rotor-side magnet surface (0) to stator bore (100)",
    )
    magneto2d_delta_br_rms_t: float = Field(..., ge=0, description="RMS native slotting delta in B_r at this radius [T]")
    femm_delta_br_rms_t: float = Field(..., ge=0, description="RMS FEMM slotting delta in B_r at this radius [T]")
    magneto2d_delta_bt_rms_t: float = Field(..., ge=0, description="RMS native slotting delta in B_t at this radius [T]")
    femm_delta_bt_rms_t: float = Field(..., ge=0, description="RMS FEMM slotting delta in B_t at this radius [T]")
    magneto2d_delta_brbt_rms_t2: float = Field(..., ge=0, description="RMS native slotting delta in B_r·B_t at this radius [T²]")
    femm_delta_brbt_rms_t2: float = Field(..., ge=0, description="RMS FEMM slotting delta in B_r·B_t at this radius [T²]")
    delta_br_rms_error_pct: Optional[float] = Field(
        default=None,
        ge=0,
        description="RMS error of slotting delta in B_r relative to FEMM at this radius [%]",
    )
    delta_bt_rms_error_pct: Optional[float] = Field(
        default=None,
        ge=0,
        description="RMS error of slotting delta in B_t relative to FEMM at this radius [%]",
    )
    delta_brbt_rms_error_pct: Optional[float] = Field(
        default=None,
        ge=0,
        description="RMS error of slotting delta in B_r·B_t relative to FEMM at this radius [%]",
    )
    peak_delta_delta_bt_t: float = Field(
        ...,
        ge=0,
        description="Peak absolute difference between native and FEMM slotting delta in B_t at this radius [T]",
    )


class DiagnosticPeakBComparison(BaseModel):
    """Apples-to-apples point-sampled peak-B comparison for diagnostics."""

    magneto2d_peak_b_teeth_point_t: float = Field(
        ..., ge=0, description="Native point-sampled peak tooth flux density [T]"
    )
    magneto2d_peak_b_yoke_point_t: float = Field(
        ..., ge=0, description="Native point-sampled peak yoke flux density [T]"
    )
    magneto2d_peak_b_teeth_robust_t: float = Field(
        ..., ge=0, description="Native robust regional peak tooth flux density [T]"
    )
    magneto2d_peak_b_yoke_robust_t: float = Field(
        ..., ge=0, description="Native robust regional peak yoke flux density [T]"
    )
    femm_peak_b_teeth_point_t: float = Field(
        ..., ge=0, description="FEMM point-sampled peak tooth flux density [T]"
    )
    femm_peak_b_yoke_point_t: float = Field(
        ..., ge=0, description="FEMM point-sampled peak yoke flux density [T]"
    )


class SlotlessNoLoadDiagnostic(BaseModel):
    """No-load comparison payload for debug UI."""

    mode: Literal["slotless_noload", "slotted_noload"] = Field(
        default="slotless_noload",
        description="Diagnostic mode identifier",
    )
    probe_radius_mm: float = Field(..., gt=0, description="Probe radius in mm")
    probe_angle_deg: float = Field(..., ge=0, le=360, description="Probe angle in mechanical degrees")
    snapshot_mechanical_angle_deg: float = Field(
        ..., ge=0, le=360, description="Angle used for field-line snapshot comparison"
    )
    magneto2d: DiagnosticSeries = Field(..., description="Native FEM diagnostic series")
    femm: DiagnosticSeries = Field(..., description="FEMM reference diagnostic series")
    slotless_baseline_magneto2d: Optional[DiagnosticSeries] = Field(
        default=None,
        description="Optional slotless native baseline captured alongside slotted no-load diagnostics",
    )
    slotless_baseline_femm: Optional[DiagnosticSeries] = Field(
        default=None,
        description="Optional slotless FEMM baseline captured alongside slotted no-load diagnostics",
    )
    magneto2d_contour_torque: Optional[SlotlessContourTorqueDiagnostic] = Field(
        default=None,
        description="Optional native contour-torque diagnostics for the snapshot angle",
    )
    contour_comparison: Optional[SlotlessContourComparison] = Field(
        default=None,
        description="Optional full circumferential contour comparison at the snapshot angle",
    )
    slotless_baseline_contour_comparison: Optional[SlotlessContourComparison] = Field(
        default=None,
        description="Optional slotless baseline contour comparison captured alongside slotted no-load diagnostics",
    )
    multi_radius_slotting_delta: Optional[list[MultiRadiusSlottingDeltaSummary]] = Field(
        default=None,
        description="Optional multi-radius slotting-delta mismatch summary for slotted no-load diagnostics",
    )


class LoadedFieldDiagnostic(BaseModel):
    """Loaded field comparison payload for debug UI."""

    mode: Literal["loaded_field"] = Field(
        default="loaded_field",
        description="Diagnostic mode identifier",
    )
    probe_radius_mm: float = Field(..., gt=0, description="Probe radius in mm")
    probe_angle_deg: float = Field(..., ge=0, le=360, description="Probe angle in mechanical degrees")
    snapshot_mechanical_angle_deg: float = Field(
        ..., ge=0, le=360, description="Angle used for field-line snapshot comparison"
    )
    magneto2d: DiagnosticSeries = Field(..., description="Native FEM diagnostic series")
    femm: DiagnosticSeries = Field(..., description="FEMM reference diagnostic series")
    magneto2d_contour_torque: Optional[SlotlessContourTorqueDiagnostic] = Field(
        default=None,
        description="Optional native contour-torque diagnostics for the snapshot angle",
    )
    snapshot_peak_b_comparison: Optional[DiagnosticPeakBComparison] = Field(
        default=None,
        description="Optional loaded-angle peak-B comparison using FEMM-like point samples",
    )
    contour_comparison: Optional[SlotlessContourComparison] = Field(
        default=None,
        description="Optional full circumferential contour comparison at the snapshot angle",
    )
