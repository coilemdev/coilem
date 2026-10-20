"""Shared contracts for the performance outputs: d/q flux linkage, losses,
the flux-linkage map, the torque-speed envelope and the efficiency map.

These models fix field names, units and conventions before the features that
fill them are built, so each can be developed and reviewed on its own.

Conventions:
  * Currents are peak phase amplitudes in amperes (not RMS).
  * The d/q transform is amplitude-invariant (Park), the same convention as
    `backend.machine_constants`: T = 1.5 · P · (λd · iq − λq · id), where P is
    the pole-pair count.
  * The current angle γ follows `SolveParams.current_angle_deg`: electrical
    degrees from the q-axis, positive advancing toward flux weakening, so
    id = −I · sin γ and iq = I · cos γ.
  * Flux linkages are per-phase peak amplitudes in webers.
  * Speeds are mechanical shaft speeds in rpm; powers are in watts.
  * A peak phase-voltage limit is `modulation_index_max · dc_bus_V / 2`;
    2/√3 is the linear limit of space-vector modulation.
"""

from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

CURRENT_ANGLE_CONVENTION = "q_axis_gamma_flux_weakening_positive"
DQ_TRANSFORM = "amplitude_invariant_park"
SVPWM_LINEAR_MODULATION_LIMIT = 2.0 / math.sqrt(3.0)

# Absolute slack for checks that compare rounded or solver-reported values.
_SUM_TOLERANCE_W = 0.05
_DQ_CURRENT_TOLERANCE_A = 1e-6

CurrentAngleConvention = Literal["q_axis_gamma_flux_weakening_positive"]
DqTransform = Literal["amplitude_invariant_park"]
# Every performance output is either checked against a reference or says it is not.
OutputStatus = Literal["qualified", "experimental", "unavailable"]
# How a drive picks the current for a torque below the limits: the smallest
# current (MTPA, then field weakening and MTPV) or the least total loss.
DriveControl = Literal["mtpa", "least_loss"]


def dq_currents(current_peak_A: float, gamma_deg: float) -> tuple[float, float]:
    """Return (id, iq) in peak amperes for a current magnitude and angle γ."""
    gamma = math.radians(gamma_deg)
    return -current_peak_A * math.sin(gamma), current_peak_A * math.cos(gamma)


def dq_torque_Nm(
    pole_pairs: int,
    lambda_d_Wb: float,
    lambda_q_Wb: float,
    i_d_A: float,
    i_q_A: float,
) -> float:
    """Electromagnetic torque from d/q flux linkages and currents."""
    return 1.5 * pole_pairs * (lambda_d_Wb * i_q_A - lambda_q_Wb * i_d_A)


def _check_dq_currents(current_peak_A: float, gamma_deg: float, i_d_A: float, i_q_A: float) -> None:
    expected_d, expected_q = dq_currents(current_peak_A, gamma_deg)
    tolerance = _DQ_CURRENT_TOLERANCE_A * max(1.0, current_peak_A)
    if abs(i_d_A - expected_d) > tolerance or abs(i_q_A - expected_q) > tolerance:
        raise ValueError(
            "i_d_A and i_q_A must follow id = -I·sin(γ), iq = I·cos(γ) for the stated current and angle"
        )


class DqFluxLinkage(BaseModel):
    """Loaded d/q flux linkage at one operating point, with the torque it implies."""

    current_angle_convention: CurrentAngleConvention = CURRENT_ANGLE_CONVENTION
    transform: DqTransform = DQ_TRANSFORM
    i_d_A: float
    i_q_A: float
    lambda_d_Wb: float
    lambda_q_Wb: float
    torque_dq_Nm: float = Field(description="1.5 · P · (λd · iq − λq · id) from the loaded flux linkages")
    torque_agreement_pct: Optional[float] = Field(
        default=None,
        description="Solver average torque as a percentage of torque_dq_Nm; about 100 for any machine",
    )
    current_angle_deg: Optional[float] = Field(
        default=None, description="Measured γ = atan2(−id, iq), from the currents the solve applied"
    )
    lambda_pm_Wb: Optional[float] = Field(default=None, ge=0, description="No-load (magnet) flux linkage amplitude")
    apparent_L_d_H: Optional[float] = Field(default=None, description="(λd − λpm) / id at this point; None when id ≈ 0")
    apparent_L_q_H: Optional[float] = Field(default=None, description="λq / iq at this point; None when iq ≈ 0")
    positions: int = Field(default=0, ge=0, description="Loaded rotor positions averaged")
    d_axis_source: Literal["no_load_flux_linkage", "applied_current_angle"] = Field(
        default="no_load_flux_linkage",
        description=(
            "How the d-axis was placed: from the no-load flux linkage (an independent check of the current angle), "
            "or from the applied currents and the commanded current angle when the run had no no-load sweep"
        ),
    )


class WindingResistance(BaseModel):
    """Phase resistance, mean turn length and slot fill of the stator winding.

    Turns follow coilEM's convention: ``turns_per_coil`` is the conductor count
    of one slot, so a phase has slot_count · turns_per_coil / 6 series turns,
    divided among its parallel paths.
    """

    wire_source: Literal["specified", "derived"]
    conductor: Literal["copper", "aluminum"]
    strand_diameter_mm: float = Field(gt=0)
    strands_in_hand: int = Field(ge=1)
    turn_copper_area_mm2: float = Field(gt=0)
    conductors_per_slot: int = Field(ge=1)
    series_turns_per_phase: float = Field(gt=0, description="All turns of one phase, before division into paths")
    parallel_paths: int = Field(ge=1)
    slot_area_mm2: float = Field(gt=0, description="Gross slot polygon area of one slot")
    copper_fill: float = Field(ge=0, description="Bare copper area over the gross slot area")
    copper_fill_limit: float = Field(gt=0, lt=1)
    wire_fill: Optional[float] = Field(default=None, ge=0, description="Insulated wire area over the slot area, when the build is known")
    fits: bool
    stack_length_mm: float = Field(gt=0)
    end_turn_length_mm: float = Field(gt=0, description="Conductor length of one end turn, at one end of the stack")
    mean_turn_length_mm: float = Field(gt=0)
    active_fraction: float = Field(gt=0, le=1, description="Share of each turn inside the stack")
    phase_resistance_20C_ohm: float = Field(gt=0)
    temperature_coefficient_per_K: float = Field(gt=0, description="R(T) = R20 · (1 + coefficient · (T - 20))")
    winding_temperature_C: float = Field(ge=-50.0, le=250.0)
    phase_resistance_ohm: float = Field(gt=0, description="At winding_temperature_C")
    notes: list[str] = Field(default_factory=list)


class LossBreakdown(BaseModel):
    """Losses and efficiency at the solved operating point.

    The solved torque is the electromagnetic torque. Iron and mechanical loss
    act as a drag on the rotor, so the shaft delivers
    P_shaft = T_em · ω − P_iron − P_mech, and the electrical input is
    P_in = P_shaft + total loss = T_em · ω + P_copper.
    """

    speed_rpm: float = Field(ge=0)
    phase_current_rms_A: float = Field(ge=0)
    electromagnetic_torque_Nm: float
    shaft_torque_Nm: float
    electromagnetic_power_W: float
    phase_resistance_ohm: float = Field(ge=0)
    winding_temperature_C: float = Field(ge=-50.0, le=250.0)
    copper_loss_W: float = Field(ge=0)
    copper_active_loss_W: float = Field(ge=0, description="I²R in the stack length")
    copper_end_winding_loss_W: float = Field(ge=0, description="I²R in the end turns")
    iron_loss_W: Optional[float] = Field(default=None, ge=0)
    iron_hysteresis_loss_W: Optional[float] = Field(default=None, ge=0)
    iron_eddy_loss_W: Optional[float] = Field(default=None, ge=0)
    iron_loss_status: OutputStatus
    iron_loss_status_reason: Optional[str] = None
    mechanical_loss_W: float = Field(default=0.0, ge=0, description="User input; 0 when not stated")
    total_loss_W: float = Field(ge=0)
    shaft_power_W: float
    input_power_W: float
    efficiency_pct: Optional[float] = Field(default=None, ge=0, le=100)
    efficiency_status: OutputStatus = "unavailable"
    efficiency_status_reason: Optional[str] = None

    @model_validator(mode="after")
    def parts_must_add_up(self):
        if abs(self.copper_active_loss_W + self.copper_end_winding_loss_W - self.copper_loss_W) > _SUM_TOLERANCE_W:
            raise ValueError("copper_active_loss_W + copper_end_winding_loss_W must equal copper_loss_W")
        if self.iron_loss_W is None:
            if self.iron_loss_status != "unavailable":
                raise ValueError("iron_loss_status must be 'unavailable' when iron_loss_W is missing")
        elif self.iron_hysteresis_loss_W is not None and self.iron_eddy_loss_W is not None:
            if abs(self.iron_hysteresis_loss_W + self.iron_eddy_loss_W - self.iron_loss_W) > _SUM_TOLERANCE_W:
                raise ValueError("iron_hysteresis_loss_W + iron_eddy_loss_W must equal iron_loss_W")
        expected_total = self.copper_loss_W + (self.iron_loss_W or 0.0) + self.mechanical_loss_W
        if abs(self.total_loss_W - expected_total) > _SUM_TOLERANCE_W:
            raise ValueError("total_loss_W must equal copper + iron + mechanical loss")
        if abs(self.input_power_W - self.shaft_power_W - self.total_loss_W) > _SUM_TOLERANCE_W:
            raise ValueError("input_power_W must equal shaft_power_W + total_loss_W")
        if self.efficiency_pct is None and self.efficiency_status != "unavailable":
            raise ValueError("efficiency_status must be 'unavailable' when efficiency_pct is missing")
        return self


class IronLoss(BaseModel):
    """Stator iron loss over one electrical period at the solved operating point."""

    status: OutputStatus
    status_reason: Optional[str] = None
    model: Literal["grade_limit_harmonic_steinmetz"] = "grade_limit_harmonic_steinmetz"
    steel: str
    electrical_frequency_Hz: Optional[float] = Field(default=None, gt=0)
    iron_loss_W: Optional[float] = Field(default=None, ge=0)
    iron_hysteresis_loss_W: Optional[float] = Field(default=None, ge=0)
    iron_eddy_loss_W: Optional[float] = Field(default=None, ge=0)
    iron_teeth_loss_W: Optional[float] = Field(default=None, ge=0)
    iron_yoke_loss_W: Optional[float] = Field(default=None, ge=0)
    stator_iron_mass_kg: Optional[float] = Field(default=None, ge=0)
    share_above_validated_frequency: Optional[float] = Field(default=None, ge=0, le=1)
    share_above_validated_flux_density: Optional[float] = Field(default=None, ge=0, le=1)
    validated_max_frequency_Hz: float = Field(gt=0)
    validated_max_flux_density_T: float = Field(gt=0)

    @model_validator(mode="after")
    def values_follow_status(self):
        values = (self.iron_loss_W, self.iron_hysteresis_loss_W, self.iron_eddy_loss_W, self.stator_iron_mass_kg)
        if self.status == "unavailable":
            if not self.status_reason:
                raise ValueError("unavailable iron loss needs a status_reason")
            if any(value is not None for value in values):
                raise ValueError("unavailable iron loss must not carry values")
            return self
        if any(value is None for value in values) or self.electrical_frequency_Hz is None:
            raise ValueError("an iron-loss estimate needs its loss, mass and frequency values")
        if abs(self.iron_hysteresis_loss_W + self.iron_eddy_loss_W - self.iron_loss_W) > _SUM_TOLERANCE_W:
            raise ValueError("iron_hysteresis_loss_W + iron_eddy_loss_W must equal iron_loss_W")
        return self


class IronLossDensity(BaseModel):
    """Iron loss per kilogram of each element of the result's field_line_plot mesh."""

    mesh: Literal["field_line_plot"] = "field_line_plot"
    element_w_per_kg: list[Optional[float]] = Field(description="None outside the stator iron")
    max_w_per_kg: float = Field(ge=0)
    element_hysteresis_w_per_kg: Optional[list[Optional[float]]] = Field(default=None, description="Hysteresis part of element_w_per_kg")
    element_eddy_w_per_kg: Optional[list[Optional[float]]] = Field(default=None, description="Eddy-current part of element_w_per_kg")

    @model_validator(mode="after")
    def values_must_be_non_negative(self):
        for name in ("element_w_per_kg", "element_hysteresis_w_per_kg", "element_eddy_w_per_kg"):
            values = getattr(self, name)
            if values is None:
                continue
            if any(value is not None and value < 0 for value in values):
                raise ValueError(f"{name} values must be non-negative")
            if len(values) != len(self.element_w_per_kg):
                raise ValueError(f"{name} must have one value per element")
        return self


class FluxLinkageMapPoint(BaseModel):
    """One solved (|I|, γ) point of a flux-linkage map."""

    current_peak_A: float = Field(ge=0)
    gamma_deg: float = Field(ge=-180.0, le=180.0)
    i_d_A: float
    i_q_A: float
    status: Literal["ok", "failed", "pending"]
    avg_torque_Nm: Optional[float] = None
    torque_ripple_pct: Optional[float] = Field(default=None, ge=0)
    lambda_d_Wb: Optional[float] = None
    lambda_q_Wb: Optional[float] = None
    iron_loss_W: Optional[float] = Field(default=None, ge=0, description="At the map's reference speed")
    iron_hysteresis_loss_W: Optional[float] = Field(default=None, ge=0)
    iron_eddy_loss_W: Optional[float] = Field(default=None, ge=0)
    nonlinear_iterations_max: Optional[int] = Field(default=None, ge=0)
    nonlinear_residual_max: Optional[float] = Field(default=None, ge=0)
    error: Optional[str] = None

    @model_validator(mode="after")
    def currents_and_results_must_be_consistent(self):
        _check_dq_currents(self.current_peak_A, self.gamma_deg, self.i_d_A, self.i_q_A)
        if self.status == "ok" and (self.avg_torque_Nm is None or self.lambda_d_Wb is None or self.lambda_q_Wb is None):
            raise ValueError("an 'ok' map point needs avg_torque_Nm, lambda_d_Wb and lambda_q_Wb")
        if self.status == "failed" and not self.error:
            raise ValueError("a 'failed' map point needs an error message")
        return self


class FluxLinkageMap(BaseModel):
    """Loaded flux linkage, torque and iron loss over a grid of current magnitudes and angles."""

    kind: Literal["flux_linkage_map"] = "flux_linkage_map"
    schema_version: Literal[1] = 1
    current_angle_convention: CurrentAngleConvention = CURRENT_ANGLE_CONVENTION
    transform: DqTransform = DQ_TRANSFORM
    scope_key: str = Field(
        min_length=16,
        description="Hash of everything that would invalidate the points: geometry, materials, mesh and solve settings",
    )
    pole_pairs: int = Field(ge=1)
    current_peak_A: list[float] = Field(min_length=1)
    gamma_deg: list[float] = Field(min_length=1)
    reference_speed_rpm: float = Field(gt=0, description="Speed at which the points' iron loss was computed")
    magnet_temperature_C: Optional[float] = Field(default=None, ge=-50.0, le=300.0)
    rotor_positions: int = Field(ge=2)
    mesh_density: str
    torque_method: Optional[str] = None
    points: list[FluxLinkageMapPoint]

    @model_validator(mode="after")
    def points_must_lie_on_the_grid(self):
        for name, axis in (("current_peak_A", self.current_peak_A), ("gamma_deg", self.gamma_deg)):
            if any(later <= earlier for earlier, later in zip(axis, axis[1:])):
                raise ValueError(f"{name} must be strictly increasing")
        currents, gammas = set(self.current_peak_A), set(self.gamma_deg)
        seen: set[tuple[float, float]] = set()
        for point in self.points:
            key = (point.current_peak_A, point.gamma_deg)
            if point.current_peak_A not in currents or point.gamma_deg not in gammas:
                raise ValueError(f"map point {key} is not on the grid")
            if key in seen:
                raise ValueError(f"map point {key} appears more than once")
            seen.add(key)
        return self


class DriveLimits(BaseModel):
    """Inverter and current limits that bound the torque-speed envelope."""

    dc_bus_V: float = Field(ge=1.0, le=2000.0)
    modulation_index_max: float = Field(
        default=SVPWM_LINEAR_MODULATION_LIMIT,
        gt=0,
        le=SVPWM_LINEAR_MODULATION_LIMIT,
        description="Peak phase-voltage limit = modulation_index_max · dc_bus_V / 2",
    )
    peak_current_A: float = Field(gt=0, le=5000.0, description="Peak phase current for the peak curve")
    continuous_current_A: Optional[float] = Field(
        default=None, gt=0, le=5000.0, description="Peak phase current for the continuous curve"
    )
    max_speed_rpm: float = Field(gt=0, le=100000.0)

    @model_validator(mode="after")
    def continuous_must_not_exceed_peak(self):
        if self.continuous_current_A is not None and self.continuous_current_A > self.peak_current_A:
            raise ValueError("continuous_current_A must not exceed peak_current_A")
        return self


class TorqueSpeedCurve(BaseModel):
    """One limit curve of the envelope, sampled at increasing speed."""

    limit: Literal["peak", "continuous"]
    speed_rpm: list[float] = Field(min_length=2)
    torque_Nm: list[float]
    power_W: list[float]
    i_d_A: list[float]
    i_q_A: list[float]
    phase_voltage_peak_V: list[float]
    region: list[Literal["mtpa", "field_weakening", "mtpv"]]
    base_speed_rpm: float = Field(ge=0)
    max_speed_rpm: float = Field(ge=0)
    peak_power_W: float = Field(ge=0)

    @model_validator(mode="after")
    def samples_must_align(self):
        length = len(self.speed_rpm)
        for name in ("torque_Nm", "power_W", "i_d_A", "i_q_A", "phase_voltage_peak_V", "region"):
            if len(getattr(self, name)) != length:
                raise ValueError(f"{name} must have one value per speed_rpm sample")
        if any(later <= earlier for earlier, later in zip(self.speed_rpm, self.speed_rpm[1:])):
            raise ValueError("speed_rpm must be strictly increasing")
        return self


class TorqueSpeedEnvelope(BaseModel):
    """Peak and continuous torque-speed curves derived from a flux-linkage map."""

    kind: Literal["torque_speed_envelope"] = "torque_speed_envelope"
    schema_version: Literal[1] = 1
    map_scope_key: str = Field(min_length=16, description="scope_key of the flux-linkage map it was derived from")
    limits: DriveLimits
    phase_resistance_ohm: float = Field(ge=0)
    winding_temperature_C: float = Field(ge=-50.0, le=250.0)
    curves: list[TorqueSpeedCurve] = Field(min_length=1)
    status: OutputStatus
    status_reason: Optional[str] = None


class EfficiencyMap(BaseModel):
    """Efficiency and losses over the torque-speed plane.

    Each matrix has one row per torque_Nm value and one column per speed_rpm
    value; None marks points outside the envelope.
    """

    kind: Literal["efficiency_map"] = "efficiency_map"
    schema_version: Literal[1] = 1
    map_scope_key: str = Field(min_length=16)
    speed_rpm: list[float] = Field(min_length=2)
    torque_Nm: list[float] = Field(min_length=2)
    efficiency_pct: list[list[Optional[float]]]
    copper_loss_W: list[list[Optional[float]]]
    iron_loss_W: list[list[Optional[float]]]
    phase_current_rms_A: Optional[list[list[Optional[float]]]] = Field(
        default=None, description="The least-loss phase current at each point, rms"
    )
    current_angle_deg: Optional[list[list[Optional[float]]]] = Field(
        default=None, description="Its current angle γ: 0° all q-axis, positive toward field weakening"
    )
    mechanical_loss_W: float = Field(default=0.0, ge=0)
    winding_temperature_C: float = Field(ge=-50.0, le=250.0)
    control: DriveControl = "mtpa"
    status: OutputStatus = "experimental"
    status_reason: Optional[str] = None

    @model_validator(mode="after")
    def matrices_must_match_axes(self):
        for name, axis in (("speed_rpm", self.speed_rpm), ("torque_Nm", self.torque_Nm)):
            if any(later <= earlier for earlier, later in zip(axis, axis[1:])):
                raise ValueError(f"{name} must be strictly increasing")
        rows, columns = len(self.torque_Nm), len(self.speed_rpm)
        for name in ("efficiency_pct", "copper_loss_W", "iron_loss_W", "phase_current_rms_A", "current_angle_deg"):
            matrix = getattr(self, name)
            if matrix is None:
                continue
            if len(matrix) != rows or any(len(row) != columns for row in matrix):
                raise ValueError(f"{name} must have {rows} rows of {columns} values")
        for row in self.efficiency_pct:
            for value in row:
                if value is not None and not 0.0 <= value <= 100.0:
                    raise ValueError("efficiency_pct values must lie between 0 and 100")
        return self
