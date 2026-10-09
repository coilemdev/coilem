"""Analytical non-motor planar geometry for a segmented Halbach cylinder."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from .models import HalbachArrayConfig

AXIAL_END_EFFECTS_NOTICE = (
    "2D cross-section extruded over the design length — axial end effects are "
    "not included."
)


@dataclass(frozen=True)
class PlanarRegion:
    id: str
    kind: str
    material_key: str
    start_angle_deg: float | None
    end_angle_deg: float | None
    area_mm2: float
    orientation: str
    source_key: str | None
    magnetization_xy: tuple[float, float] | None
    magnetization_angle_deg: float | None
    feature_tags: tuple[str, ...]
    boundary_tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "material_key": self.material_key,
            "start_angle_deg": self.start_angle_deg,
            "end_angle_deg": self.end_angle_deg,
            "area_mm2": self.area_mm2,
            "orientation": self.orientation,
            "source_key": self.source_key,
            "magnetization_xy": (
                list(self.magnetization_xy) if self.magnetization_xy is not None else None
            ),
            "magnetization_angle_deg": self.magnetization_angle_deg,
            "feature_tags": list(self.feature_tags),
            "boundary_tags": list(self.boundary_tags),
        }


@dataclass(frozen=True)
class PlanarEmGeometryArtifact:
    contract_version: str
    application_kind: str
    coordinate_unit: str
    inner_radius_mm: float
    outer_radius_mm: float
    outer_boundary_radius_mm: float
    regions: tuple[PlanarRegion, ...]
    feature_tags: dict[str, tuple[str, ...]]
    area_closure_error_mm2: float
    geometry_hash: str
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "application_kind": self.application_kind,
            "coordinate_unit": self.coordinate_unit,
            "inner_radius_mm": self.inner_radius_mm,
            "outer_radius_mm": self.outer_radius_mm,
            "outer_boundary_radius_mm": self.outer_boundary_radius_mm,
            "regions": [region.as_dict() for region in self.regions],
            "feature_tags": {
                key: list(value) for key, value in sorted(self.feature_tags.items())
            },
            "area_closure_error_mm2": self.area_closure_error_mm2,
            "geometry_hash": self.geometry_hash,
            "metadata": self.metadata,
        }


def segment_angles(config: HalbachArrayConfig, index: int) -> tuple[float, float, float]:
    """Return magnet wedge start, end, and center angles in degrees."""

    pitch = 360.0 / config.geometry.segment_count
    center = config.geometry.segment_start_angle + (index + 0.5) * pitch
    half_span = 0.5 * (pitch - config.geometry.segment_gap_angle)
    return center - half_span, center + half_span, center


def magnetization_angle_deg(config: HalbachArrayConfig, index: int) -> float:
    """Return the remanence angle for the requested CCW internal field.

    For the repository's +x/+y coordinate convention, increasing the
    requested bore-field angle requires subtracting that angle from the
    twice-spatial-angle Halbach pattern.
    """

    _, _, center = segment_angles(config, index)
    return 2.0 * center - config.array.field_direction


def _normalize_hash_value(value: Any) -> Any:
    """Remove platform-level libm noise from geometry identity payloads."""

    if isinstance(value, float):
        rounded = round(value, 12)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, dict):
        return {key: _normalize_hash_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_hash_value(item) for item in value]
    return value


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        _normalize_hash_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_planar_geometry(
    config: HalbachArrayConfig,
    *,
    remanence_t: float,
    material_key: str,
) -> PlanarEmGeometryArtifact:
    """Build the schedule-safe planar geometry contract.

    The contract is deliberately independent of the motor ``GeometryIR``.  A
    Halbach-specific Gmsh adapter consumes it, but downstream work sees only
    the stable ``magnetostatic_problem`` v1 artifact.
    """

    ri = config.geometry.inner_radius
    ro = config.geometry.outer_radius
    rb = config.solve.mesh.outer_boundary_radius_factor * ro
    n = config.geometry.segment_count
    pitch = 360.0 / n
    gap = config.geometry.segment_gap_angle
    annulus_factor = 0.5 * (ro * ro - ri * ri)
    magnet_area_each = annulus_factor * math.radians(pitch - gap)
    gap_area_each = annulus_factor * math.radians(gap)
    regions: list[PlanarRegion] = [
        PlanarRegion(
            id="bore_air",
            kind="bore_air",
            material_key="air",
            start_angle_deg=None,
            end_angle_deg=None,
            area_mm2=math.pi * ri * ri,
            orientation="counter_clockwise",
            source_key=None,
            magnetization_xy=None,
            magnetization_angle_deg=None,
            feature_tags=("bore_roi",),
        )
    ]
    for index in range(n):
        start, end, _ = segment_angles(config, index)
        alpha = magnetization_angle_deg(config, index)
        alpha_rad = math.radians(alpha)
        regions.append(
            PlanarRegion(
                id=f"magnet_{index:02d}",
                kind="permanent_magnet",
                material_key=material_key,
                start_angle_deg=start,
                end_angle_deg=end,
                area_mm2=magnet_area_each,
                orientation="counter_clockwise",
                source_key=f"halbach_segment_{index:02d}",
                magnetization_xy=(
                    remanence_t * math.cos(alpha_rad),
                    remanence_t * math.sin(alpha_rad),
                ),
                magnetization_angle_deg=alpha % 360.0,
                feature_tags=(
                    "material_interface",
                    "critical_curve",
                    "permanent_magnet_edge",
                    "critical_corner",
                ),
            )
        )
        if gap > 0.0:
            gap_start = end
            gap_end = start + pitch
            regions.append(
                PlanarRegion(
                    id=f"gap_air_{index:02d}",
                    kind="gap_air",
                    material_key="air",
                    start_angle_deg=gap_start,
                    end_angle_deg=gap_end,
                    area_mm2=gap_area_each,
                    orientation="counter_clockwise",
                    source_key=None,
                    magnetization_xy=None,
                    magnetization_angle_deg=None,
                    feature_tags=("critical_gap", "material_interface"),
                )
            )
    regions.append(
        PlanarRegion(
            id="exterior_air",
            kind="exterior_air",
            material_key="air",
            start_angle_deg=None,
            end_angle_deg=None,
            area_mm2=math.pi * (rb * rb - ro * ro),
            orientation="counter_clockwise",
            source_key=None,
            magnetization_xy=None,
            magnetization_angle_deg=None,
            feature_tags=("far_field",),
            boundary_tags=("az_zero",),
        )
    )
    modeled_area = sum(region.area_mm2 for region in regions)
    domain_area = math.pi * rb * rb
    closure_error = modeled_area - domain_area
    feature_tags = {
        "bore_magnet_interface": (
            "material_interface",
            "critical_curve",
            "bore_roi_boundary",
        ),
        "magnet_outer_arc": ("material_interface", "critical_curve"),
        "segment_radial_edges": (
            "permanent_magnet_edge",
            "critical_corner",
            "material_interface",
        ),
        "segment_gap_air": ("critical_gap", "material_interface"),
        "exterior_air": ("far_field",),
        "outer_circle": ("far_field", "dirichlet_boundary"),
    }
    identity_payload = {
        "contract_version": "planar_em_geometry/1.0",
        "application_kind": "halbach_array",
        "coordinate_unit": "mm",
        "inner_radius_mm": ri,
        "outer_radius_mm": ro,
        "outer_boundary_radius_mm": rb,
        "regions": [region.as_dict() for region in regions],
        "feature_tags": feature_tags,
    }
    return PlanarEmGeometryArtifact(
        contract_version="planar_em_geometry/1.0",
        application_kind="halbach_array",
        coordinate_unit="mm",
        inner_radius_mm=ri,
        outer_radius_mm=ro,
        outer_boundary_radius_mm=rb,
        regions=tuple(regions),
        feature_tags=feature_tags,
        area_closure_error_mm2=closure_error,
        geometry_hash=_canonical_hash(identity_payload),
        metadata={
            "full_model_degrees": 360.0,
            "segment_count": n,
            "segment_pitch_deg": pitch,
            "segment_gap_angle_deg": gap,
            "axial_length_mm": config.geometry.axial_length,
            "axial_length_affects_field_problem": False,
            "axial_end_effects_modeled": False,
            "model_notice": AXIAL_END_EFFECTS_NOTICE,
        },
    )


def tessellated_region_loop(
    artifact: PlanarEmGeometryArtifact,
    region_id: str,
    *,
    arc_steps: int = 16,
) -> list[tuple[float, float]]:
    """Return a CCW loop for area/orientation tests and SVG preview."""

    region = next(region for region in artifact.regions if region.id == region_id)
    if region.start_angle_deg is None or region.end_angle_deg is None:
        raise ValueError(f"region {region_id!r} is not an annular wedge")
    start = math.radians(region.start_angle_deg)
    end = math.radians(region.end_angle_deg)
    ri = artifact.inner_radius_mm
    ro = artifact.outer_radius_mm
    outer = [
        (
            ro * math.cos(start + (end - start) * step / arc_steps),
            ro * math.sin(start + (end - start) * step / arc_steps),
        )
        for step in range(arc_steps + 1)
    ]
    inner = [
        (
            ri * math.cos(end - (end - start) * step / arc_steps),
            ri * math.sin(end - (end - start) * step / arc_steps),
        )
        for step in range(arc_steps + 1)
    ]
    return outer + inner


def signed_polygon_area(points: list[tuple[float, float]]) -> float:
    return 0.5 * sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )
