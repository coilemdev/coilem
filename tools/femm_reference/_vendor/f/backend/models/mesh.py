"""Data contracts for motor mesh. """

from pydantic import BaseModel, Field, field_validator


class Node(BaseModel):
    """Spatial node for flux density map."""

    x: float = Field(..., description="X-coordinate in mm")
    y: float = Field(..., description="Y-coordinate in mm")


class FluxDensityMap(BaseModel):
    """Spatial map of magnetic flux density."""

    nodes: list[Node] = Field(..., min_length=1, description="Spatial nodes in mm")
    B_magnitude: list[float] = Field(
        ..., min_length=1, description="Flux density magnitudes in Tesla (each >= 0)"
    )

    @field_validator("B_magnitude")
    @classmethod
    def b_magnitude_length_matches_nodes(cls, v, info):
        """B_magnitude array must match nodes array length and all values >= 0."""
        # Check values are non-negative
        for i, val in enumerate(v):
            if val < 0:
                raise ValueError(f"B_magnitude[{i}] must be >= 0, got {val}")
        # Check length matches nodes
        if info.data and "nodes" in info.data:
            if len(v) != len(info.data["nodes"]):
                raise ValueError(
                    "B_magnitude length must match nodes length"
                )
        return v


class MeshConfigSummary(BaseModel):
    """Shared mesh/plot config summary for frontend rendering."""

    topology: str = Field(..., description="Motor topology")
    slots: int = Field(..., ge=1, description="Number of stator slots")
    poles: int = Field(..., ge=1, description="Number of rotor poles")
    stator_od_mm: float = Field(..., ge=0, description="Stator outer diameter [mm]")
    rotor_od_mm: float = Field(..., ge=0, description="Rotor outer diameter [mm]")
    magnet_thickness_mm: float = Field(..., ge=0, description="Magnet thickness [mm]")
    stack_length_mm: float = Field(..., ge=0, description="Stack length [mm]")


class MeshPlotInfo(BaseModel):
    """Basic mesh metadata for viewer overlays."""

    num_nodes: int = Field(..., ge=1, description="Number of mesh nodes")
    num_triangles: int = Field(..., ge=1, description="Number of mesh triangles")
    pole_pitch_deg: float = Field(..., gt=0, description="Pole pitch [deg]")
    n_pole_pitches: int = Field(..., ge=1, description="Modeled pole pitches")
    total_span_deg: float = Field(..., gt=0, description="Modeled angular span [deg]")
