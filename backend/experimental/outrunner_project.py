"""Strict, portable frozen-reference .coilem inputs; no inner-rotor coercion."""
from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.experimental.femm_outrunner import ASSET_SHA256, FIXTURE_ID, SOURCE_SHA256, source


class OutrunnerAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    unique_samples: Literal[48, 96, 192, 384] = 48
    gap_size_mm: Literal[0.05, 0.025, 0.0125] = 0.05
    speed_rpm: float = Field(default=1000, gt=0, le=100000)
    loaded_currents_A: list[float] = Field(default_factory=lambda: [0, 4, -4], min_length=3, max_length=3)
    nonlinear_tolerance: Literal[1e-5, 1e-6] = 1e-5
    material_law: Literal["source_points_piecewise_linear_in_plane_fill/v1"] = "source_points_piecewise_linear_in_plane_fill/v1"
    mesh_policy: Literal["outrunner_source_gap_interfaces/v2"] = "outrunner_source_gap_interfaces/v2"

    @model_validator(mode="after")
    def balanced(self):
        if not all(math.isfinite(x) and abs(x) <= 20 for x in self.loaded_currents_A) or abs(sum(self.loaded_currents_A)) > 1e-10:
            raise ValueError("Three finite balanced currents, each within +/-20 A, are required")
        return self


class OutrunnerProject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["coilem_frozen_reference"] = "coilem_frozen_reference"
    format_version: Literal[1] = 1
    name: str = Field(default="FEMM LRK outrunner 12s/14p", min_length=1, max_length=120)
    fixture_id: Literal["femm_lrk_12s14p_v1"] = FIXTURE_ID
    source_sha256: str = SOURCE_SHA256
    fixture_asset_sha256: str = ASSET_SHA256
    coordinate_convention: Literal["source_native_CCW_outer_rotor"] = "source_native_CCW_outer_rotor"
    fixture_data: dict[str, Any] = Field(default_factory=lambda: source())
    analysis: OutrunnerAnalysis = Field(default_factory=OutrunnerAnalysis)

    @model_validator(mode="after")
    def verify_frozen_inputs(self):
        if self.source_sha256 != SOURCE_SHA256 or self.fixture_asset_sha256 != ASSET_SHA256 or self.fixture_data != source():
            raise ValueError("The frozen fixture geometry, materials, winding map, and source identities must match the audited asset")
        return self


class OutrunnerRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: OutrunnerProject
    analysis: Literal["source_point", "loaded_torque", "noload_bemf", "both"] = "both"
