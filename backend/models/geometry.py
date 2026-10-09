"""Data contracts for motor geometry. """

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .errors import ErrorResponse


class GeometryRegion(BaseModel):
    """A single geometric region for SVG rendering."""

    region_type: str = Field(
        ...,
        description="Region type: stator_yoke, stator_tooth, slot, magnet_n, magnet_s, rotor_core, airgap, shaft, winding_symbol",
    )
    points: list[list[float]] = Field(
        ..., description="Polygon vertices [[x, y], ...] in mm"
    )
    fill: str = Field(..., description="Hex color for SVG fill")
    label: str = Field(..., description="Human-readable label")
    text_label: Optional[str] = Field(default=None, description="Optional text to render at region center (e.g. N/S for magnets)")
    text_position: Optional[list[float]] = Field(default=None, description="[x, y] position for text_label in mm")


class WindingSlot(BaseModel):
    """Winding assignment for a single slot."""

    slot_index: int = Field(..., ge=0, description="Slot index (0-based)")
    phase: Literal["A", "B", "C"] = Field(..., description="Phase A, B, or C")
    direction: Literal["in", "out"] = Field(..., description="Winding direction")
    layer: int = Field(default=1, ge=1, le=2, description="Winding layer (1 or 2)")


class WindingCoil(BaseModel):
    """One physical coil: the pair of slot sides its conductors occupy.

    ``winding_layout`` tags whole slots with a phase; this is the coil-level
    connectivity that a physical winding actually has, so renderers can draw
    tooth-wrapped coils and end turns instead of guessing the pairing.
    """

    coil_index: int = Field(..., ge=0, description="Coil index (0-based)")
    phase: Literal["A", "B", "C"] = Field(..., description="Phase A, B, or C")
    polarity: Literal[1, -1] = Field(
        ..., description="+1 when the slot_in side carries 'in' current"
    )
    slot_in: int = Field(..., ge=0, description="Slot holding the going-in side")
    slot_out: int = Field(..., ge=0, description="Slot holding the return side")
    tooth_wound: bool = Field(
        ...,
        description="True when the coil wraps the single tooth between slot_in and slot_out (concentrated winding)",
    )
    layer: int = Field(default=1, ge=1, le=2, description="Winding layer (1 or 2)")


class GeometryPreview(BaseModel):
    """Complete geometry preview response for SVG rendering."""

    regions: list[GeometryRegion] = Field(
        ..., description="List of geometric regions"
    )
    winding_layout: list[WindingSlot] = Field(
        ..., description="Winding slot assignments"
    )
    winding_coils: list[WindingCoil] = Field(
        default=[], description="Coil-level connectivity (slot pairs per coil)"
    )
    metadata: dict = Field(
        ...,
        description="Metadata: stator_od_mm, rotor_od_mm, airgap_mm, pole_count, slot_count, topology",
    )
    validation_errors: list["ErrorResponse"] = Field(
        default=[], description="Geometry validation errors if any"
    )
    generation_time_ms: float = Field(
        ..., description="Time to generate preview in milliseconds"
    )
