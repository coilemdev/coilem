"""Steady-state thermal contracts; separate from the guarded EM configuration."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CORE_REASON = "Uncalibrated estimate under stated cooling assumptions; no bench qualification."
ROTOR_REASON = ("Heat-transfer estimate including any supplied heat. Rotor/magnet eddy-current heat is not calculated; "
                "its unknown contribution may raise temperatures. No bench qualification.")
ThermalStatus = Literal["experimental", "unavailable"]


class ThermalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CalibrationSource(ThermalModel):
    measurement: str = Field(min_length=1)
    operating_point: str = Field(min_length=1)
    cooling: str = Field(min_length=1)


class MechanicalHeatSplit(ThermalModel):
    bearings: float = Field(ge=0, le=1)
    housing: float = Field(ge=0, le=1)
    rotor: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def must_assign_all_heat(self):
        if not math.isclose(self.bearings + self.housing + self.rotor, 1.0, abs_tol=1e-9):
            raise ValueError("Mechanical heat fractions must sum to one")
        return self


class ThermalInputs(ThermalModel):
    cooling: Literal["still_air", "forced_air", "liquid_jacket"]
    ambient_C: float = Field(gt=-273.15, le=200)
    # Presets name the boundary; coefficients are always supplied, never inferred
    # from the name. These also permit measured operating-point-specific values.
    housing_h_W_m2K: float = Field(gt=0)
    end_space_h_W_m2K: float = Field(gt=0)
    airgap_h_W_m2K: float = Field(gt=0)
    coefficient_source: str = Field(min_length=1)
    housing_thickness_mm: float = Field(gt=0)
    slot_liner_mm: float = Field(gt=0)
    contact_m2K_W: float = Field(gt=0)
    bearing_to_housing_K_W: float = Field(gt=0)
    rotor_to_bearing_K_W: float = Field(gt=0)
    # Outer-rotor motors only: from the stator hub, through the mount, to the
    # surroundings. There the outside coefficient above applies to the rotor shell,
    # and the housing thickness is unused.
    mount_to_ambient_K_W: float | None = Field(default=None, gt=0)
    # Initial, editable engineering assumptions, not material qualification.
    steel_k_W_mK: float = Field(default=20.0, gt=0)
    conductor_k_W_mK: float = Field(default=385.0, gt=0)
    housing_k_W_mK: float = Field(default=205.0, gt=0)
    magnet_k_W_mK: float = Field(default=8.0, gt=0)
    impregnation_k_W_mK: float = Field(default=0.2, gt=0)
    liner_k_W_mK: float = Field(default=0.2, gt=0)
    slot_k_model: Literal["series_lower_bound", "user"] = "series_lower_bound"
    slot_k_W_mK: float | None = Field(default=None, gt=0)
    slot_k_source: str | None = None
    end_winding_exposed_fraction: float = Field(default=1, gt=0, le=1)
    extra_rotor_heat_to_magnets_fraction: float = Field(default=0, ge=0, le=1)
    mechanical_split: MechanicalHeatSplit | None = None
    extra_rotor_heat_W: float = Field(default=0, ge=0)
    calibration_multiplier: float = Field(default=1, gt=0)
    calibration_source: CalibrationSource | None = None
    insulation_class: Literal["A", "B", "F", "H"]
    hotspot_allowance_K: float = Field(ge=0)
    # Legacy input retained for saved records/API compatibility. It does not
    # establish loss-model validity and no longer gates heat-transfer estimates.
    magnet_frequency_limit_Hz: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def calibration_needs_evidence(self):
        if self.slot_k_model == "user" and (self.slot_k_W_mK is None or not self.slot_k_source):
            raise ValueError("User slot conductivity needs its value and source")
        if self.slot_k_model == "series_lower_bound" and self.slot_k_W_mK is not None:
            raise ValueError("Set slot_k_model to user when supplying a conductivity")
        if self.calibration_multiplier != 1 and self.calibration_source is None:
            raise ValueError("A calibration multiplier needs its measurement, operating point and cooling")
        return self


class ThermalLink(ThermalModel):
    a: str
    b: str
    resistance_K_W: float = Field(gt=0)
    assumption: str = Field(min_length=1)


class ThermalSlab(ThermalModel):
    """Uniform-generation slab: distinct spatial mean and two surface ports.

    resistance_K_W is the full surface-to-surface L/(k*A), not a mean-path
    resistance. The exact steady three-terminal relation is assembled as one
    element; it must not be split into ordinary positive-resistance links.
    """

    mean: str
    a: str
    b: str
    resistance_K_W: float = Field(gt=0)
    assumption: str = Field(min_length=1)


class ThermalNetwork(ThermalModel):
    nodes: list[str] = Field(min_length=1)
    links: list[ThermalLink]
    fixed_C: dict[str, float]
    heat_W: dict[str, float]
    slabs: list[ThermalSlab] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_network(self):
        names = set(self.nodes)
        if len(names) != len(self.nodes) or not self.fixed_C:
            raise ValueError("Nodes must be unique and the network needs a fixed-temperature boundary")
        if not set(self.fixed_C).issubset(names) or not set(self.heat_W).issubset(names):
            raise ValueError("Boundary and heat nodes must exist")
        if any(not math.isfinite(t) or t <= -273.15 for t in self.fixed_C.values()):
            raise ValueError("Invalid boundary temperature")
        if any(not math.isfinite(q) or q < 0 for q in self.heat_W.values()):
            raise ValueError("Heat must be finite and nonnegative")
        if any(self.heat_W.get(n, 0) != 0 for n in self.fixed_C):
            raise ValueError("Heat must be assigned to an unknown-temperature node")
        if any(link.a not in names or link.b not in names or link.a == link.b for link in self.links):
            raise ValueError("Each link needs two different existing nodes")
        if any(len({slab.mean, slab.a, slab.b}) != 3 or not {slab.mean, slab.a, slab.b}.issubset(names)
               for slab in self.slabs):
            raise ValueError("Each slab needs three different existing mean/surface nodes")
        return self


class ThermalNodeResult(ThermalModel):
    temperature_C: float | None = None
    heat_W: float = Field(ge=0)
    status: ThermalStatus = "experimental"
    status_reason: str = CORE_REASON
    limit_C: float | None = None
    margin_K: float | None = None

    @model_validator(mode="after")
    def values_follow_status(self):
        if not self.status_reason or (self.status == "unavailable") != (self.temperature_C is None):
            raise ValueError("Thermal status must agree with temperature availability")
        return self


class CopperFeedback(ThermalModel):
    """Fixed-current copper equilibrium, also nested inside magnet-map coupling."""

    method: Literal["linear_equilibrium_v1"] = "linear_equilibrium_v1"
    status: Literal["experimental"] = "experimental"
    status_reason: str = "Separate active/end winding resistance feedback; current, iron loss and thermal paths held fixed."
    reference_temperature_C: Literal[20] = 20
    temperature_coefficient_per_K: float = Field(ge=0)
    phase_current_rms_A: float = Field(ge=0)
    phase_resistance_20C_ohm: float = Field(gt=0)
    phase_resistance_ohm: float = Field(gt=0)
    reference_copper_loss_W: float = Field(ge=0)
    copper_active_loss_W: float = Field(ge=0)
    copper_end_winding_loss_W: float = Field(ge=0)
    copper_loss_W: float = Field(ge=0)
    loop_gain: float = Field(ge=0, lt=1)
    temperature_residual_K: float = Field(ge=0)
    wire_source: Literal["specified", "derived"]


class RotorHeating(ThermalModel):
    """Recorded heat scope, never a claim that omitted losses are physically zero."""

    basis: Literal["heat_transfer_only", "heat_transfer_plus_supplied_heat"]
    additional_heat_W: float = Field(ge=0)
    mechanical_heat_to_rotor_W: float = Field(ge=0)
    internal_loss_status: Literal["not_modelled"] = "not_modelled"
    status_reason: str = ROTOR_REASON


class ThermalResult(ThermalModel):
    kind: Literal["steady_state_thermal"] = "steady_state_thermal"
    schema_version: Literal[1] = 1
    status: ThermalStatus = "experimental"
    status_reason: str = CORE_REASON
    inputs: ThermalInputs
    nodes: dict[str, ThermalNodeResult] = Field(default_factory=dict)
    baseline_without_extra_rotor_C: dict[str, float] | None = None
    network: ThermalNetwork | None = None
    total_heat_W: float | None = None
    rejected_heat_W: float | None = None
    energy_balance_error_W: float | None = None
    hottest_node: str | None = None
    calibrated: bool = False
    copper_feedback: CopperFeedback | None = None
    rotor_heating: RotorHeating | None = None
    notes: list[str] = Field(default_factory=list)
