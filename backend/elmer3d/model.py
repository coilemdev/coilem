"""SI input contract for three-dimensional magnetostatic cases and closed coils."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Material3D(InputModel):
    kind: Literal["linear", "permanent_magnet", "bh_curve"] = "linear"
    relative_permeability: float = Field(default=1.0, gt=0)
    remanence_T: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # B in tesla, H in A/m; preserve the caller's curve without fitting.
    bh_points: list[tuple[float, float]] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_law(self):
        if self.kind != "permanent_magnet" and any(self.remanence_T):
            raise ValueError("remanence_T requires permanent_magnet material")
        if self.kind == "bh_curve":
            if len(self.bh_points) < 2 or self.bh_points[0] != (0.0, 0.0):
                raise ValueError("bh_points must start at (0, 0) and contain at least two points")
            for (b0, h0), (b1, h1) in zip(self.bh_points, self.bh_points[1:]):
                if b1 <= b0 or h1 <= h0:
                    raise ValueError("bh_points must have strictly increasing B and H")
        elif self.bh_points:
            raise ValueError("bh_points requires bh_curve material")
        return self


class Coil3D(InputModel):
    """A meshed solid torus, including its end connections, with a unit-current field."""

    bodies: list[str] = Field(min_length=1)
    normal: tuple[float, float, float]
    turns: int = Field(default=1, gt=0)
    current_A: float = 0.0

    @model_validator(mode="after")
    def check_normal(self):
        if math.sqrt(sum(x * x for x in self.normal)) < 1e-12:
            raise ValueError("coil normal must be nonzero")
        if len(set(self.bodies)) != len(self.bodies):
            raise ValueError("duplicate coil body")
        return self


class Numerics3D(InputModel):
    timeout_s: float = Field(default=600, gt=0, le=86400)
    nonlinear_max_iterations: int = Field(default=100, ge=1, le=1000)
    nonlinear_tolerance: float = Field(default=1e-7, gt=0, lt=1)
    nonlinear_relaxation: float = Field(default=1.0, gt=0, le=1)


class Case3D(InputModel):
    schema_version: Literal["coilem.elmer3d_case/v1"] = "coilem.elmer3d_case/v1"
    mesh_file: Path
    length_units: Literal["m"] = "m"
    # Names must refer to Gmsh physical volumes, not elementary entity tags.
    materials: dict[str, Material3D]
    bodies: dict[str, str]
    outer_boundary: str
    coils: dict[str, Coil3D] = Field(default_factory=dict)
    stress_surface: str | None = None
    torque_origin_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    assumptions: list[str] = Field(default_factory=list)
    numerics: Numerics3D = Field(default_factory=Numerics3D)

    @model_validator(mode="after")
    def check_references(self):
        if not self.bodies or not self.materials:
            raise ValueError("materials and bodies must be nonempty")
        for material in self.bodies.values():
            if material not in self.materials:
                raise ValueError(f"unknown material: {material}")
        used = set()
        for coil in self.coils.values():
            for body in coil.bodies:
                if body not in self.bodies or body in used:
                    raise ValueError(f"unknown or multiply assigned coil body: {body}")
                law = self.materials[self.bodies[body]]
                if law.kind != "linear" or law.relative_permeability != 1.0:
                    raise ValueError("closed coils must have relative permeability 1")
                used.add(body)
        return self
