"""Strict v1 configuration models for the linear Halbach application."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import HalbachLinearSettings, HalbachUnits, MagnetInput

LINEAR_QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "density": "coarse",
        "outer_padding_factor": 1.5,
        "minimum_elements_across_magnet": 3,
        "samples_per_period": 24,
        "tolerance": 1.0e-7,
    },
    "standard": {
        "density": "normal",
        "outer_padding_factor": 2.5,
        "minimum_elements_across_magnet": 6,
        "samples_per_period": 64,
        "tolerance": 1.0e-8,
    },
    "fine": {
        "density": "fine",
        "outer_padding_factor": 3.5,
        "minimum_elements_across_magnet": 10,
        "samples_per_period": 128,
        "tolerance": 1.0e-9,
    },
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LinearHalbachGeometryConfig(_StrictModel):
    block_width: float = Field(gt=0.0)
    magnet_height: float = Field(gt=0.0)
    out_of_plane_depth: float = Field(gt=0.0)
    period_count: int = Field(default=4, ge=1, le=16)
    block_gap: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_geometry(self) -> "LinearHalbachGeometryConfig":
        values = (
            self.block_width,
            self.magnet_height,
            self.out_of_plane_depth,
            self.block_gap,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("linear geometry values must be finite")
        if self.block_gap >= self.block_width:
            raise ValueError(
                "geometry.block_gap must be less than geometry.block_width"
            )
        return self

    @property
    def block_count(self) -> int:
        return 4 * self.period_count

    @property
    def wavelength(self) -> float:
        return 4.0 * (self.block_width + self.block_gap)

    @property
    def active_length(self) -> float:
        return (
            self.block_count * self.block_width
            + (self.block_count - 1) * self.block_gap
        )


class LinearHalbachArrayPattern(_StrictModel):
    strong_side: Literal["positive_y", "negative_y"] = "positive_y"
    phase_deg: float = 0.0

    @model_validator(mode="after")
    def validate_phase(self) -> "LinearHalbachArrayPattern":
        if not math.isfinite(self.phase_deg):
            raise ValueError("array.phase_deg must be finite")
        return self


class LinearHalbachSampleRegion(_StrictModel):
    probe_offset: float = Field(default=5.0, gt=0.0)
    edge_exclusion_periods: int = Field(default=1, ge=0, le=7)
    samples_per_period: int = Field(default=64, ge=8, le=512)


class LinearHalbachMeshSettings(_StrictModel):
    density: Literal["coarse", "normal", "fine"] = "normal"
    outer_padding_factor: float = Field(default=2.5, ge=0.5, le=10.0)
    minimum_elements_across_magnet: int = Field(default=6, ge=2, le=40)
    corner_refinement: bool = True


class LinearHalbachSolveSettings(_StrictModel):
    quality: Literal["quick", "standard", "fine", "custom"] = "standard"
    mesh: LinearHalbachMeshSettings = Field(
        default_factory=LinearHalbachMeshSettings
    )
    linear: HalbachLinearSettings = Field(default_factory=HalbachLinearSettings)
    field_line_count: int = Field(default=18, ge=0, le=200)


class LinearHalbachArrayConfig(_StrictModel):
    kind: Literal["linear_halbach_array_config"] = "linear_halbach_array_config"
    version: Literal["1.0"] = "1.0"
    units: HalbachUnits = Field(default_factory=HalbachUnits)
    geometry: LinearHalbachGeometryConfig
    array: LinearHalbachArrayPattern = Field(
        default_factory=LinearHalbachArrayPattern
    )
    magnet: MagnetInput
    sample_region: LinearHalbachSampleRegion = Field(
        default_factory=LinearHalbachSampleRegion
    )
    solve: LinearHalbachSolveSettings = Field(
        default_factory=LinearHalbachSolveSettings
    )

    @model_validator(mode="before")
    @classmethod
    def populate_period_dependent_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        geometry = values.get("geometry")
        if not isinstance(geometry, dict):
            return values
        period_count = geometry.get("period_count", 4)
        sample_region = values.get("sample_region")
        samples = dict(sample_region) if isinstance(sample_region, dict) else {}
        if (
            "edge_exclusion_periods" not in samples
            and isinstance(period_count, int)
        ):
            samples["edge_exclusion_periods"] = 1 if period_count >= 3 else 0
        values["sample_region"] = samples
        return values

    @model_validator(mode="after")
    def validate_cross_field_relationships(self) -> "LinearHalbachArrayConfig":
        if self.solve.quality != "custom":
            preset = LINEAR_QUALITY_PRESETS[self.solve.quality]
            self.solve.mesh.density = preset["density"]
            self.solve.mesh.outer_padding_factor = preset[
                "outer_padding_factor"
            ]
            self.solve.mesh.minimum_elements_across_magnet = preset[
                "minimum_elements_across_magnet"
            ]
            self.solve.mesh.corner_refinement = True
            self.solve.linear.tolerance = preset["tolerance"]
            self.sample_region.samples_per_period = preset[
                "samples_per_period"
            ]
        retained_periods = (
            self.geometry.period_count
            - 2 * self.sample_region.edge_exclusion_periods
        )
        if retained_periods <= 0:
            raise ValueError(
                "sample_region.edge_exclusion_periods must leave at least one "
                "complete magnetic period"
            )
        padding_mm = (
            self.solve.mesh.outer_padding_factor
            * self.geometry.wavelength
        )
        if self.sample_region.probe_offset >= padding_mm:
            raise ValueError(
                "sample_region.probe_offset must be inside the modeled outer "
                f"boundary ({padding_mm:g} mm from the magnet face)"
            )
        return self


def canonical_linear_halbach_config() -> LinearHalbachArrayConfig:
    """Return the checked-in four-period linear Halbach fixture."""

    return LinearHalbachArrayConfig.model_validate(
        {
            "kind": "linear_halbach_array_config",
            "version": "1.0",
            "units": {"length": "mm", "angle": "deg"},
            "geometry": {
                "block_width": 10.0,
                "magnet_height": 10.0,
                "out_of_plane_depth": 100.0,
                "period_count": 4,
                "block_gap": 0.0,
            },
            "array": {
                "strong_side": "positive_y",
                "phase_deg": 0.0,
            },
            "magnet": {
                "source": "catalog",
                "grade": "N42",
                "temperature_c": 20.0,
            },
            "sample_region": {
                "probe_offset": 5.0,
                "edge_exclusion_periods": 1,
                "samples_per_period": 64,
            },
            "solve": {
                "quality": "standard",
                "mesh": {
                    "density": "normal",
                    "outer_padding_factor": 2.5,
                    "minimum_elements_across_magnet": 6,
                    "corner_refinement": True,
                },
                "linear": {
                    "solver": "direct",
                    "pcg_preconditioner": "incomplete_cholesky",
                    "tolerance": 1.0e-8,
                    "max_iterations": 5000,
                },
                "field_line_count": 18,
            },
        }
    )
