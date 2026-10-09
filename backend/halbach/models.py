"""Strict v1 configuration models for the cylindrical Halbach application."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from backend.material_catalog import MAGNET_PROPERTIES

CATALOG_TEMPERATURE_RANGES_C: dict[str, tuple[float, float]] = {
    "N35": (-40.0, 180.0),
    "N42": (-40.0, 180.0),
    "N48": (-40.0, 180.0),
    "N52": (-40.0, 180.0),
    "N48SH": (-40.0, 200.0),
    "Prius_2004_NdFeB": (-40.0, 180.0),
    "Ferrite_Y30": (-40.0, 250.0),
}

QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "density": "coarse",
        "outer_boundary_radius_factor": 3.0,
        "minimum_elements_across_magnet": 3,
        "radial_samples": 17,
        "angular_samples": 48,
        "tolerance": 1.0e-7,
    },
    "standard": {
        "density": "normal",
        "outer_boundary_radius_factor": 4.0,
        "minimum_elements_across_magnet": 6,
        "radial_samples": 31,
        "angular_samples": 96,
        "tolerance": 1.0e-8,
    },
    "fine": {
        "density": "fine",
        "outer_boundary_radius_factor": 6.0,
        "minimum_elements_across_magnet": 10,
        "radial_samples": 61,
        "angular_samples": 192,
        "tolerance": 1.0e-9,
    },
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HalbachUnits(_StrictModel):
    length: Literal["mm"] = "mm"
    angle: Literal["deg"] = "deg"


class HalbachGeometryConfig(_StrictModel):
    inner_radius: float = Field(gt=0.0)
    outer_radius: float = Field(gt=0.0)
    axial_length: float = Field(gt=0.0)
    segment_count: int = Field(default=16, ge=4, le=64)
    segment_gap_angle: float = Field(default=0.0, ge=0.0)
    segment_start_angle: float = 0.0

    @model_validator(mode="after")
    def validate_geometry_relationships(self) -> "HalbachGeometryConfig":
        values = (
            self.inner_radius,
            self.outer_radius,
            self.axial_length,
            self.segment_gap_angle,
            self.segment_start_angle,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("geometry values must be finite")
        if self.outer_radius <= self.inner_radius:
            raise ValueError("geometry.outer_radius must be greater than geometry.inner_radius")
        half_pitch = 180.0 / self.segment_count
        if self.segment_gap_angle >= half_pitch:
            raise ValueError(
                "geometry.segment_gap_angle must be less than half the segment pitch "
                f"({half_pitch:g} deg for {self.segment_count} segments)"
            )
        return self


class HalbachArrayPattern(_StrictModel):
    field_mode: Literal["internal"] = "internal"
    multipole_order: Literal[1] = 1
    field_direction: float = 0.0

    @model_validator(mode="after")
    def validate_finite_direction(self) -> "HalbachArrayPattern":
        if not math.isfinite(self.field_direction):
            raise ValueError("array.field_direction must be finite")
        return self


class CatalogMagnetInput(_StrictModel):
    source: Literal["catalog"]
    grade: Literal[
        "N35",
        "N42",
        "N48",
        "N52",
        "N48SH",
        "Ferrite_Y30",
        "Prius_2004_NdFeB",
    ] = "N42"
    temperature_c: float = Field(default=20.0, ge=-40.0, le=250.0)

    @model_validator(mode="after")
    def validate_catalog_row(self) -> "CatalogMagnetInput":
        if self.grade not in MAGNET_PROPERTIES:
            raise ValueError(f"magnet.grade is not present in the material catalog: {self.grade}")
        return self

    @field_validator("temperature_c")
    @classmethod
    def validate_catalog_temperature(
        cls,
        value: float,
        info: ValidationInfo,
    ) -> float:
        if not math.isfinite(value):
            raise ValueError("magnet.temperature_c must be finite")
        grade = info.data.get("grade", "N42")
        minimum_c, maximum_c = CATALOG_TEMPERATURE_RANGES_C[grade]
        if not minimum_c <= value <= maximum_c:
            raise ValueError(
                f"magnet.temperature_c for {grade} must be in "
                f"[{minimum_c:g}, {maximum_c:g}] degC"
            )
        return value


class CustomMagnetInput(_StrictModel):
    source: Literal["custom"]
    name: str = Field(min_length=1, max_length=160)
    remanence_t: float = Field(gt=0.0)
    relative_permeability: float = Field(default=1.05, ge=1.0)
    intrinsic_coercivity_a_per_m: float | None = Field(default=None, gt=0.0)
    density_kg_per_m3: float | None = Field(default=None, gt=0.0)
    reference_temperature_c: float | None = None
    temperature_c: float | None = None
    alpha_br_per_k: float | None = None
    alpha_hcj_per_k: float | None = None
    source_note: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_custom_temperature_contract(self) -> "CustomMagnetInput":
        numeric_values = (
            self.remanence_t,
            self.relative_permeability,
            self.intrinsic_coercivity_a_per_m,
            self.density_kg_per_m3,
            self.reference_temperature_c,
            self.temperature_c,
            self.alpha_br_per_k,
            self.alpha_hcj_per_k,
        )
        if not all(value is None or math.isfinite(value) for value in numeric_values):
            raise ValueError("custom magnet numeric values must be finite")
        if self.temperature_c is not None and self.reference_temperature_c is None:
            raise ValueError(
                "magnet.reference_temperature_c is required when magnet.temperature_c is set"
            )
        if self.alpha_br_per_k is not None and (
            self.temperature_c is None or self.reference_temperature_c is None
        ):
            raise ValueError(
                "magnet.alpha_br_per_k requires magnet.temperature_c and "
                "magnet.reference_temperature_c"
            )
        if self.alpha_hcj_per_k is not None and (
            self.temperature_c is None or self.reference_temperature_c is None
        ):
            raise ValueError(
                "magnet.alpha_hcj_per_k requires magnet.temperature_c and "
                "magnet.reference_temperature_c"
            )
        return self


MagnetInput = Annotated[
    CatalogMagnetInput | CustomMagnetInput,
    Field(discriminator="source"),
]


class HalbachSampleRegion(_StrictModel):
    radius: float = Field(gt=0.0)
    radial_samples: int = Field(default=31, ge=5, le=201)
    angular_samples: int = Field(default=96, ge=16, le=720)
    leakage_probe_radius: float = Field(gt=0.0)


class HalbachMeshSettings(_StrictModel):
    density: Literal["coarse", "normal", "fine"] = "normal"
    outer_boundary_radius_factor: float = Field(default=4.0, ge=2.0, le=12.0)
    minimum_elements_across_magnet: int = Field(default=6, ge=2, le=40)
    corner_refinement: bool = True


class HalbachLinearSettings(_StrictModel):
    solver: Literal["direct", "pcg"] = "direct"
    pcg_preconditioner: Literal["incomplete_cholesky", "jacobi"] = (
        "incomplete_cholesky"
    )
    tolerance: float = Field(default=1.0e-8, gt=0.0, lt=1.0)
    max_iterations: int = Field(default=5000, ge=1, le=1_000_000)


class HalbachSolveSettings(_StrictModel):
    quality: Literal["quick", "standard", "fine", "custom"] = "standard"
    mesh: HalbachMeshSettings = Field(default_factory=HalbachMeshSettings)
    linear: HalbachLinearSettings = Field(default_factory=HalbachLinearSettings)
    field_line_count: int = Field(default=18, ge=0, le=200)


class HalbachArrayConfig(_StrictModel):
    kind: Literal["halbach_array_config"] = "halbach_array_config"
    version: Literal["1.0"] = "1.0"
    units: HalbachUnits = Field(default_factory=HalbachUnits)
    geometry: HalbachGeometryConfig
    array: HalbachArrayPattern = Field(default_factory=HalbachArrayPattern)
    magnet: MagnetInput
    sample_region: HalbachSampleRegion
    solve: HalbachSolveSettings = Field(default_factory=HalbachSolveSettings)

    @model_validator(mode="before")
    @classmethod
    def populate_geometry_dependent_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        geometry = values.get("geometry")
        if not isinstance(geometry, dict):
            return values
        inner_radius = geometry.get("inner_radius")
        outer_radius = geometry.get("outer_radius")
        sample_region = values.get("sample_region")
        samples = dict(sample_region) if isinstance(sample_region, dict) else {}
        if "radius" not in samples and isinstance(inner_radius, (int, float)):
            samples["radius"] = 0.8 * inner_radius
        if "leakage_probe_radius" not in samples and isinstance(
            outer_radius, (int, float)
        ):
            samples["leakage_probe_radius"] = 1.5 * outer_radius
        values["sample_region"] = samples
        return values

    @model_validator(mode="after")
    def validate_cross_field_relationships(self) -> "HalbachArrayConfig":
        if self.solve.quality != "custom":
            preset = QUALITY_PRESETS[self.solve.quality]
            self.solve.mesh.density = preset["density"]
            self.solve.mesh.outer_boundary_radius_factor = preset[
                "outer_boundary_radius_factor"
            ]
            self.solve.mesh.minimum_elements_across_magnet = preset[
                "minimum_elements_across_magnet"
            ]
            self.solve.mesh.corner_refinement = True
            self.solve.linear.tolerance = preset["tolerance"]
            self.sample_region.radial_samples = preset["radial_samples"]
            self.sample_region.angular_samples = preset["angular_samples"]
        if self.sample_region.radius > 0.95 * self.geometry.inner_radius:
            raise ValueError(
                "sample_region.radius must be no greater than 95% of "
                "geometry.inner_radius"
            )
        if self.sample_region.leakage_probe_radius <= self.geometry.outer_radius:
            raise ValueError(
                "sample_region.leakage_probe_radius must be greater than "
                "geometry.outer_radius"
            )
        outer_boundary = (
            self.solve.mesh.outer_boundary_radius_factor * self.geometry.outer_radius
        )
        if self.sample_region.leakage_probe_radius >= outer_boundary:
            raise ValueError(
                "sample_region.leakage_probe_radius must be inside the modeled "
                f"outer boundary ({outer_boundary:g} mm)"
            )
        return self


def canonical_halbach_config() -> HalbachArrayConfig:
    """Return the checked-in 16-segment product fixture."""

    return HalbachArrayConfig.model_validate(
        {
            "kind": "halbach_array_config",
            "version": "1.0",
            "units": {"length": "mm", "angle": "deg"},
            "geometry": {
                "inner_radius": 25.0,
                "outer_radius": 50.0,
                "axial_length": 100.0,
                "segment_count": 16,
                "segment_gap_angle": 0.0,
                "segment_start_angle": 0.0,
            },
            "array": {
                "field_mode": "internal",
                "multipole_order": 1,
                "field_direction": 0.0,
            },
            "magnet": {
                "source": "catalog",
                "grade": "N42",
                "temperature_c": 20.0,
            },
            "sample_region": {
                "radius": 20.0,
                "radial_samples": 31,
                "angular_samples": 96,
                "leakage_probe_radius": 75.0,
            },
            "solve": {
                "quality": "standard",
                "mesh": {
                    "density": "normal",
                    "outer_boundary_radius_factor": 4.0,
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
