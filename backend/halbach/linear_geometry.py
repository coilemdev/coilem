"""Finite rectangular geometry for a four-block-per-period Halbach array."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from .linear_models import LinearHalbachArrayConfig

LINEAR_MODEL_NOTICE = (
    "2D Magneto2D field extruded for visualization · not a 3D FEM result"
)


@dataclass(frozen=True)
class LinearPlanarRegion:
    id: str
    kind: str
    material_key: str
    area_mm2: float
    bounds_mm: tuple[float, float, float, float]
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
            "area_mm2": self.area_mm2,
            "bounds_mm": list(self.bounds_mm),
            "source_key": self.source_key,
            "magnetization_xy": (
                list(self.magnetization_xy)
                if self.magnetization_xy is not None
                else None
            ),
            "magnetization_angle_deg": self.magnetization_angle_deg,
            "feature_tags": list(self.feature_tags),
            "boundary_tags": list(self.boundary_tags),
        }


@dataclass(frozen=True)
class LinearPlanarGeometryArtifact:
    contract_version: str
    application_kind: str
    coordinate_unit: str
    domain_bounds_mm: tuple[float, float, float, float]
    active_bounds_mm: tuple[float, float, float, float]
    regions: tuple[LinearPlanarRegion, ...]
    feature_tags: dict[str, tuple[str, ...]]
    area_closure_error_mm2: float
    geometry_hash: str
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "application_kind": self.application_kind,
            "coordinate_unit": self.coordinate_unit,
            "domain_bounds_mm": list(self.domain_bounds_mm),
            "active_bounds_mm": list(self.active_bounds_mm),
            "regions": [region.as_dict() for region in self.regions],
            "feature_tags": {
                key: list(value)
                for key, value in sorted(self.feature_tags.items())
            },
            "area_closure_error_mm2": self.area_closure_error_mm2,
            "geometry_hash": self.geometry_hash,
            "metadata": self.metadata,
        }


def block_magnetization_angle_deg(
    config: LinearHalbachArrayConfig,
    index: int,
) -> float:
    """Return block remanence angle for a left-to-right block index.

    Magnetization progressing counter-clockwise by 90 degrees as x increases
    reinforces the positive-y side. Reversing that progression reinforces the
    negative-y side.
    """

    if not 0 <= index < config.geometry.block_count:
        raise IndexError(
            f"block index {index} is outside [0, {config.geometry.block_count})"
        )
    rotation_sign = 1.0 if config.array.strong_side == "positive_y" else -1.0
    return (config.array.phase_deg + rotation_sign * 90.0 * index) % 360.0


def block_bounds_mm(
    config: LinearHalbachArrayConfig,
    index: int,
) -> tuple[float, float, float, float]:
    """Return xmin, ymin, xmax, ymax for a left-to-right block."""

    if not 0 <= index < config.geometry.block_count:
        raise IndexError(
            f"block index {index} is outside [0, {config.geometry.block_count})"
        )
    geometry = config.geometry
    xmin = (
        -0.5 * geometry.active_length
        + index * (geometry.block_width + geometry.block_gap)
    )
    return (
        xmin,
        -0.5 * geometry.magnet_height,
        xmin + geometry.block_width,
        0.5 * geometry.magnet_height,
    )


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_linear_planar_geometry(
    config: LinearHalbachArrayConfig,
    *,
    remanence_t: float,
    material_key: str,
) -> LinearPlanarGeometryArtifact:
    """Build a finite magnet row inside a rectangular air domain."""

    geometry = config.geometry
    padding = (
        config.solve.mesh.outer_padding_factor * geometry.wavelength
    )
    active_bounds = (
        -0.5 * geometry.active_length,
        -0.5 * geometry.magnet_height,
        0.5 * geometry.active_length,
        0.5 * geometry.magnet_height,
    )
    domain_bounds = (
        active_bounds[0] - padding,
        active_bounds[1] - padding,
        active_bounds[2] + padding,
        active_bounds[3] + padding,
    )
    regions: list[LinearPlanarRegion] = []
    magnet_area = geometry.block_width * geometry.magnet_height
    for index in range(geometry.block_count):
        angle = block_magnetization_angle_deg(config, index)
        angle_rad = math.radians(angle)
        regions.append(
            LinearPlanarRegion(
                id=f"magnet_{index:03d}",
                kind="permanent_magnet",
                material_key=material_key,
                area_mm2=magnet_area,
                bounds_mm=block_bounds_mm(config, index),
                source_key=f"linear_halbach_block_{index:03d}",
                magnetization_xy=(
                    remanence_t * math.cos(angle_rad),
                    remanence_t * math.sin(angle_rad),
                ),
                magnetization_angle_deg=angle,
                feature_tags=(
                    "material_interface",
                    "permanent_magnet_edge",
                    "critical_corner",
                ),
            )
        )

    domain_area = (
        (domain_bounds[2] - domain_bounds[0])
        * (domain_bounds[3] - domain_bounds[1])
    )
    exterior_area = domain_area - geometry.block_count * magnet_area
    regions.append(
        LinearPlanarRegion(
            id="exterior_air",
            kind="exterior_air",
            material_key="air",
            area_mm2=exterior_area,
            bounds_mm=domain_bounds,
            source_key=None,
            magnetization_xy=None,
            magnetization_angle_deg=None,
            feature_tags=(
                "far_field",
                "working_probe",
                "leakage_probe",
            ),
            boundary_tags=("az_zero",),
        )
    )
    feature_tags = {
        "magnet_interfaces": (
            "material_interface",
            "permanent_magnet_edge",
        ),
        "magnet_corners": ("critical_corner",),
        "working_probe": ("working_probe",),
        "leakage_probe": ("leakage_probe",),
        "outer_rectangle": ("far_field", "dirichlet_boundary"),
    }
    modeled_area = sum(region.area_mm2 for region in regions)
    identity_payload = {
        "contract_version": "linear_planar_em_geometry/1.0",
        "application_kind": "linear_halbach_array",
        "coordinate_unit": "mm",
        "domain_bounds_mm": domain_bounds,
        "active_bounds_mm": active_bounds,
        "regions": [
            {
                "id": region.id,
                "kind": region.kind,
                "area_mm2": region.area_mm2,
                "bounds_mm": region.bounds_mm,
                "feature_tags": region.feature_tags,
                "boundary_tags": region.boundary_tags,
            }
            for region in regions
        ],
        "feature_tags": feature_tags,
    }
    retained_periods = (
        geometry.period_count
        - 2 * config.sample_region.edge_exclusion_periods
    )
    # A finite row with gaps is one terminal gap shorter than P complete
    # repeating cells. Deriving probes from the magnet silhouette would
    # therefore shorten every sampled interval by one block gap. Keep the
    # evaluation interval centered and exactly periodic instead.
    probe_half_width = 0.5 * retained_periods * geometry.wavelength
    probe_xmin = -probe_half_width
    probe_xmax = probe_half_width
    working_y = (
        active_bounds[3] + config.sample_region.probe_offset
        if config.array.strong_side == "positive_y"
        else active_bounds[1] - config.sample_region.probe_offset
    )
    leakage_y = (
        active_bounds[1] - config.sample_region.probe_offset
        if config.array.strong_side == "positive_y"
        else active_bounds[3] + config.sample_region.probe_offset
    )
    return LinearPlanarGeometryArtifact(
        contract_version="linear_planar_em_geometry/1.0",
        application_kind="linear_halbach_array",
        coordinate_unit="mm",
        domain_bounds_mm=domain_bounds,
        active_bounds_mm=active_bounds,
        regions=tuple(regions),
        feature_tags=feature_tags,
        area_closure_error_mm2=modeled_area - domain_area,
        geometry_hash=_canonical_hash(identity_payload),
        metadata={
            "block_count": geometry.block_count,
            "blocks_per_period": 4,
            "period_count": geometry.period_count,
            "wavelength_mm": geometry.wavelength,
            "active_length_mm": geometry.active_length,
            "padding_mm": padding,
            "strong_side": config.array.strong_side,
            "phase_deg": config.array.phase_deg,
            "probe_lines": {
                "x_min_mm": probe_xmin,
                "x_max_mm": probe_xmax,
                "working_y_mm": working_y,
                "leakage_y_mm": leakage_y,
                "retained_periods": retained_periods,
            },
            "out_of_plane_depth_mm": geometry.out_of_plane_depth,
            "out_of_plane_depth_affects_field_problem": False,
            "out_of_plane_end_effects_modeled": False,
            "model_notice": LINEAR_MODEL_NOTICE,
        },
    )
