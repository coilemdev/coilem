"""Halbach-specific metrics derived from a neutral Magneto2D field report."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .geometry import AXIAL_END_EFFECTS_NOTICE, PlanarEmGeometryArtifact
from .gmsh_adapter import HalbachMeshArtifact
from .materials import ResolvedMagnetMaterial
from .models import HalbachArrayConfig

if TYPE_CHECKING:
    from .linear_geometry import LinearPlanarGeometryArtifact
    from .linear_gmsh_adapter import LinearHalbachMeshArtifact

MU_0 = 4.0e-7 * math.pi


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(max(fraction, 0.0), 1.0) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _statistics(values: list[float]) -> dict[str, float]:
    mean = _mean(values)
    rms = math.sqrt(_mean([value * value for value in values]))
    variance = _mean([(value - mean) ** 2 for value in values])
    minimum = min(values)
    maximum = max(values)
    return {
        "mean": mean,
        "rms": rms,
        "standard_deviation": math.sqrt(max(0.0, variance)),
        "minimum": minimum,
        "maximum": maximum,
        "peak_to_peak": maximum - minimum,
    }


def _angle_error_deg(actual_x: float, actual_y: float, target_deg: float) -> float:
    actual = math.degrees(math.atan2(actual_y, actual_x))
    return ((actual - target_deg + 180.0) % 360.0) - 180.0


@dataclass
class _TriangleLocator:
    nodes: tuple[tuple[float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]

    def __post_init__(self) -> None:
        xs = [node[0] for node in self.nodes]
        ys = [node[1] for node in self.nodes]
        self._xmin = min(xs)
        self._ymin = min(ys)
        self._xmax = max(xs)
        self._ymax = max(ys)
        side = max(12, min(160, int(math.sqrt(len(self.triangles)) // 2)))
        self._nx = side
        self._ny = side
        self._dx = max((self._xmax - self._xmin) / side, 1.0e-12)
        self._dy = max((self._ymax - self._ymin) / side, 1.0e-12)
        self._bins: dict[tuple[int, int], list[int]] = {}
        for index, triangle in enumerate(self.triangles):
            points = [self.nodes[node] for node in triangle]
            ix0, iy0 = self._cell(
                min(point[0] for point in points), min(point[1] for point in points)
            )
            ix1, iy1 = self._cell(
                max(point[0] for point in points), max(point[1] for point in points)
            )
            for ix in range(ix0, ix1 + 1):
                for iy in range(iy0, iy1 + 1):
                    self._bins.setdefault((ix, iy), []).append(index)

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        ix = min(self._nx - 1, max(0, int((x - self._xmin) / self._dx)))
        iy = min(self._ny - 1, max(0, int((y - self._ymin) / self._dy)))
        return ix, iy

    def locate(self, x: float, y: float) -> int:
        for triangle_index in self._bins.get(self._cell(x, y), []):
            a, b, c = (
                self.nodes[node_index] for node_index in self.triangles[triangle_index]
            )
            denominator = (b[1] - c[1]) * (a[0] - c[0]) + (
                c[0] - b[0]
            ) * (a[1] - c[1])
            if abs(denominator) <= 1.0e-24:
                continue
            u = (
                (b[1] - c[1]) * (x - c[0])
                + (c[0] - b[0]) * (y - c[1])
            ) / denominator
            v = (
                (c[1] - a[1]) * (x - c[0])
                + (a[0] - c[0]) * (y - c[1])
            ) / denominator
            w = 1.0 - u - v
            if min(u, v, w) >= -1.0e-10:
                return triangle_index
        raise ValueError(f"sample point ({x:g}, {y:g}) lies outside the mesh")


def _sample(
    locator: _TriangleLocator,
    fields: list[dict[str, float]],
    x: float,
    y: float,
) -> dict[str, float]:
    element = locator.locate(x, y)
    field = fields[element]
    return {
        "x_mm": x,
        "y_mm": y,
        "element_index": element,
        "bx_t": float(field["bx"]),
        "by_t": float(field["by"]),
        "b_magnitude_t": float(field["b_mag"]),
    }


def _equal_area_bore_samples(
    config: HalbachArrayConfig,
    locator: _TriangleLocator,
    fields: list[dict[str, float]],
) -> list[dict[str, float]]:
    samples: list[dict[str, float]] = []
    radial_count = config.sample_region.radial_samples
    angular_count = config.sample_region.angular_samples
    radius = config.sample_region.radius
    for radial_index in range(radial_count):
        r = radius * math.sqrt((radial_index + 0.5) / radial_count)
        angular_offset = 0.5 * (radial_index % 2)
        for angular_index in range(angular_count):
            theta = 2.0 * math.pi * (
                angular_index + angular_offset
            ) / angular_count
            samples.append(
                _sample(
                    locator,
                    fields,
                    r * math.cos(theta),
                    r * math.sin(theta),
                )
            )
    return samples


def segmented_analytical_factor(
    segment_count: int,
    segment_gap_angle_deg: float,
) -> tuple[float, float]:
    """Return the wedge-span sinc factor and angular coverage.

    For a gapped array the first-order uniform term integrates over the actual
    magnet span, not the full segment pitch.
    """

    pitch_rad = 2.0 * math.pi / segment_count
    span_rad = pitch_rad - math.radians(segment_gap_angle_deg)
    coverage = span_rad / pitch_rad
    sinc_span = math.sin(span_rad) / span_rad
    return sinc_span, coverage


def _circle_samples(
    *,
    radius_mm: float,
    count: int,
    locator: _TriangleLocator,
    fields: list[dict[str, float]],
) -> list[dict[str, float]]:
    return [
        {
            **_sample(
                locator,
                fields,
                radius_mm * math.cos(2.0 * math.pi * index / count),
                radius_mm * math.sin(2.0 * math.pi * index / count),
            ),
            "angle_deg": 360.0 * index / count,
        }
        for index in range(count)
    ]


def field_comparison_metrics(
    config: HalbachArrayConfig,
    mesh: HalbachMeshArtifact,
    field_report: dict[str, Any],
) -> dict[str, float]:
    """Calculate the two metrics needed by an outer-boundary rerun."""

    fields = field_report["solution"]["element_fields"]
    locator = _TriangleLocator(mesh.nodes_mm, mesh.triangles)
    target_rad = math.radians(config.array.field_direction)
    parallel = (math.cos(target_rad), math.sin(target_rad))
    bore_samples = _equal_area_bore_samples(config, locator, fields)
    mean_parallel = _mean(
        [
            sample["bx_t"] * parallel[0] + sample["by_t"] * parallel[1]
            for sample in bore_samples
        ]
    )
    leakage_samples = _circle_samples(
        radius_mm=config.sample_region.leakage_probe_radius,
        count=config.sample_region.angular_samples,
        locator=locator,
        fields=fields,
    )
    leakage_rms = math.sqrt(
        _mean(
            [
                sample["b_magnitude_t"] * sample["b_magnitude_t"]
                for sample in leakage_samples
            ]
        )
    )
    return {
        "mean_b_parallel_t": mean_parallel,
        "leakage_rms_b_t": leakage_rms,
    }


def _triangle_area(
    nodes: tuple[tuple[float, float], ...], triangle: tuple[int, int, int]
) -> float:
    a, b, c = (nodes[index] for index in triangle)
    return 0.5 * abs(
        (b[0] - a[0]) * (c[1] - a[1])
        - (b[1] - a[1]) * (c[0] - a[0])
    )


def _reverse_field_metrics(
    geometry: PlanarEmGeometryArtifact | LinearPlanarGeometryArtifact,
    mesh: HalbachMeshArtifact | LinearHalbachMeshArtifact,
    fields: list[dict[str, float]],
    material: ResolvedMagnetMaterial,
) -> dict[str, Any]:
    region_lookup = {region.id: region for region in geometry.regions}
    per_segment: dict[str, list[tuple[float, float]]] = {}
    for index, (region_id, triangle, field) in enumerate(
        zip(mesh.element_region_ids, mesh.triangles, fields)
    ):
        region = region_lookup[region_id]
        if region.kind != "permanent_magnet" or region.magnetization_xy is None:
            continue
        brx, bry = region.magnetization_xy
        br_magnitude = math.hypot(brx, bry)
        if br_magnitude <= 0.0:
            continue
        ux, uy = brx / br_magnitude, bry / br_magnitude
        hx = (float(field["bx"]) - brx) / (
            MU_0 * material.relative_permeability
        )
        hy = (float(field["by"]) - bry) / (
            MU_0 * material.relative_permeability
        )
        reverse = max(0.0, -(hx * ux + hy * uy))
        area = _triangle_area(mesh.nodes_mm, triangle)
        per_segment.setdefault(region_id, []).append((reverse, area))
    all_values = [
        reverse for values in per_segment.values() for reverse, _area in values
    ]
    segment_rows = []
    for region_id, values in sorted(per_segment.items()):
        region = region_lookup[region_id]
        reverse_values = [reverse for reverse, _area in values]
        total_area = sum(area for _reverse, area in values)
        area_mean = (
            sum(reverse * area for reverse, area in values) / total_area
            if total_area > 0.0
            else 0.0
        )
        segment_rows.append(
            {
                "segment_id": region_id,
                "magnetization_angle_deg": region.magnetization_angle_deg,
                "reverse_field_mean_a_per_m": area_mean,
                "reverse_field_p99_a_per_m": _percentile(reverse_values, 0.99),
                "reverse_field_max_a_per_m": max(reverse_values),
                "element_count": len(values),
            }
        )
    p99 = _percentile(all_values, 0.99)
    maximum = max(all_values) if all_values else 0.0
    margin = (
        material.coercivity_a_per_m - p99
        if material.coercivity_margin_eligible
        and material.coercivity_a_per_m is not None
        else None
    )
    return {
        "label": "screening diagnostic — not a demagnetization certification",
        "mesh_sensitivity": "p99_headline_maximum_detail",
        "reverse_field_p99_a_per_m": p99,
        "reverse_field_max_a_per_m": maximum,
        "intrinsic_coercivity_margin_a_per_m": margin,
        "margin_eligible": material.coercivity_margin_eligible,
        "margin_ineligible_reason": material.coercivity_ineligible_reason,
        "segments": segment_rows,
    }


def _contour_segments(
    nodes: tuple[tuple[float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    az_nodal: list[float],
    element_fields: list[dict[str, float]],
    *,
    count: int = 18,
) -> list[dict[str, Any]]:
    low = min(az_nodal)
    high = max(az_nodal)
    if count <= 0 or high - low <= 1.0e-18:
        return []
    levels = [low + (high - low) * (index + 1) / (count + 1) for index in range(count)]
    output: list[dict[str, Any]] = []
    for level in levels:
        segments: list[list[float]] = []
        segment_bx: list[float] = []
        segment_by: list[float] = []
        segment_b_magnitude: list[float] = []
        for triangle_index, triangle in enumerate(triangles):
            intersections: list[tuple[float, float]] = []
            for start_index, end_index in ((0, 1), (1, 2), (2, 0)):
                start_node = triangle[start_index]
                end_node = triangle[end_index]
                start_value = az_nodal[start_node]
                end_value = az_nodal[end_node]
                if (start_value < level <= end_value) or (
                    end_value < level <= start_value
                ):
                    fraction = (level - start_value) / (end_value - start_value)
                    start = nodes[start_node]
                    end = nodes[end_node]
                    intersections.append(
                        (
                            start[0] + fraction * (end[0] - start[0]),
                            start[1] + fraction * (end[1] - start[1]),
                        )
                    )
            if len(intersections) == 2:
                segments.append(
                    [
                        intersections[0][0],
                        intersections[0][1],
                        intersections[1][0],
                        intersections[1][1],
                    ]
                )
                field = element_fields[triangle_index]
                segment_bx.append(float(field["bx"]))
                segment_by.append(float(field["by"]))
                segment_b_magnitude.append(float(field["b_mag"]))
        output.append(
            {
                "az_level_t_m": level,
                "segments_mm": segments,
                "segment_bx_t": segment_bx,
                "segment_by_t": segment_by,
                "segment_b_mag_t": segment_b_magnitude,
            }
        )
    return output


def build_halbach_report(
    *,
    config: HalbachArrayConfig,
    geometry: PlanarEmGeometryArtifact,
    mesh: HalbachMeshArtifact,
    material: ResolvedMagnetMaterial,
    magnetostatic_problem: dict[str, Any],
    problem_hash: str,
    field_report: dict[str, Any],
    timings_ms: dict[str, float],
    peak_memory_bytes: int | None,
    convergence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    solution = field_report["solution"]
    fields = solution["element_fields"]
    az_nodal = [float(value) for value in solution["az_nodal"]]
    if len(fields) != len(mesh.triangles):
        raise ValueError("generic field report element count does not match Halbach mesh")
    locator = _TriangleLocator(mesh.nodes_mm, mesh.triangles)
    target_angle = config.array.field_direction
    target_rad = math.radians(target_angle)
    parallel = (math.cos(target_rad), math.sin(target_rad))
    perpendicular = (-parallel[1], parallel[0])

    center = _sample(locator, fields, 0.0, 0.0)
    bore_samples = _equal_area_bore_samples(config, locator, fields)
    for sample in bore_samples:
        sample["b_parallel_t"] = (
            sample["bx_t"] * parallel[0] + sample["by_t"] * parallel[1]
        )
        sample["b_perpendicular_t"] = (
            sample["bx_t"] * perpendicular[0]
            + sample["by_t"] * perpendicular[1]
        )
    parallel_values = [sample["b_parallel_t"] for sample in bore_samples]
    perpendicular_values = [
        sample["b_perpendicular_t"] for sample in bore_samples
    ]
    magnitude_values = [sample["b_magnitude_t"] for sample in bore_samples]
    parallel_stats = _statistics(parallel_values)
    magnitude_stats = _statistics(magnitude_values)
    mean_bx = _mean([sample["bx_t"] for sample in bore_samples])
    mean_by = _mean([sample["by_t"] for sample in bore_samples])

    n = config.geometry.segment_count
    ideal = material.remanence_t * math.log(
        config.geometry.outer_radius / config.geometry.inner_radius
    )
    segmentation_factor, angular_coverage = segmented_analytical_factor(
        n,
        config.geometry.segment_gap_angle,
    )
    segmented = ideal * segmentation_factor * angular_coverage
    delta_segmented_pct = (
        100.0 * (parallel_stats["mean"] - segmented) / segmented
        if abs(segmented) > 1.0e-15
        else None
    )

    leakage_samples = _circle_samples(
        radius_mm=config.sample_region.leakage_probe_radius,
        count=config.sample_region.angular_samples,
        locator=locator,
        fields=fields,
    )
    leakage_magnitudes = [sample["b_magnitude_t"] for sample in leakage_samples]
    leakage_rms = math.sqrt(
        _mean([magnitude * magnitude for magnitude in leakage_magnitudes])
    )
    leakage_mean_bx = _mean([sample["bx_t"] for sample in leakage_samples])
    leakage_mean_by = _mean([sample["by_t"] for sample in leakage_samples])
    leakage_ratio = (
        leakage_rms / abs(parallel_stats["mean"])
        if abs(parallel_stats["mean"]) > 1.0e-15
        else None
    )

    magnet_area_mm2 = sum(
        region.area_mm2
        for region in geometry.regions
        if region.kind == "permanent_magnet"
    )
    magnet_volume_m3 = (
        magnet_area_mm2 * config.geometry.axial_length * 1.0e-9
    )
    magnet_mass_kg = (
        magnet_volume_m3 * material.density_kg_per_m3
        if material.density_kg_per_m3 is not None
        else None
    )
    generic_energy = float(
        solution["energy_per_unit_depth"]["magnetic_field_j_per_m"]
    )
    reverse_field = _reverse_field_metrics(
        geometry, mesh, fields, material
    )
    generic_timings = solution.get("timings", {})
    timing_report = {
        **timings_ms,
        "generic_preparation": float(generic_timings.get("preparation_ms", 0.0)),
        "generic_assembly": float(generic_timings.get("assembly_ms", 0.0)),
        "generic_linear_solve": float(
            generic_timings.get("linear_solve_ms", 0.0)
        ),
        "generic_field_recovery": float(
            generic_timings.get("field_recovery_ms", 0.0)
        ),
        "generic_material_update": float(
            generic_timings.get("material_update_ms", 0.0)
        ),
    }
    report = {
        "openem_schema_kind": "halbach_solution_report",
        "openem_schema_version": "1.0",
        "model": {
            "formulation": "planar_az",
            "assumption": "infinite_length_extruded_2d",
            "axial_end_effects_modeled": False,
            "axial_length_usage": [
                "design_preview",
                "volume_and_mass",
                "extruded_2d_estimates",
            ],
            "notice": AXIAL_END_EFFECTS_NOTICE,
        },
        "configuration": config.model_dump(mode="json", exclude_none=True),
        "geometry": geometry.as_dict(),
        "mesh": mesh.preview_payload(),
        "artifacts": {
            "magnetostatic_problem_sha256": problem_hash,
            "generic_field_report_input_sha256": field_report.get(
                "openem_provenance", {}
            ).get("fixture_sha256"),
            "geometry_hash": geometry.geometry_hash,
            "mesh_hash": mesh.mesh_hash,
        },
        "bore_field": {
            "headline": "Mean bore field in the selected sample region",
            "requested_field_direction_deg": target_angle % 360.0,
            "mean_bx_t": mean_bx,
            "mean_by_t": mean_by,
            "mean_field_direction_error_deg": _angle_error_deg(
                mean_bx, mean_by, target_angle
            ),
            "center": {
                **center,
                "field_direction_error_deg": _angle_error_deg(
                    center["bx_t"], center["by_t"], target_angle
                ),
            },
            "b_parallel_t": parallel_stats,
            "b_perpendicular_rms_t": math.sqrt(
                _mean([value * value for value in perpendicular_values])
            ),
            "b_perpendicular_max_abs_t": max(
                abs(value) for value in perpendicular_values
            ),
            "b_magnitude_t": magnitude_stats,
            "uniformity_ppm": (
                1.0e6
                * parallel_stats["peak_to_peak"]
                / abs(parallel_stats["mean"])
                if abs(parallel_stats["mean"]) > 1.0e-15
                else None
            ),
            "roi_radius_mm": config.sample_region.radius,
            "roi_area_mm2": math.pi * config.sample_region.radius**2,
            "sample_count": len(bore_samples),
            "sampling_rule": (
                "equal_area_polar: "
                "r_j=R*sqrt((j+0.5)/radial_samples); "
                "theta_jk=2*pi*(k+0.5*(j mod 2))/angular_samples; "
                "equal area weight per sample; center evaluated separately"
            ),
            "radial_samples": config.sample_region.radial_samples,
            "angular_samples": config.sample_region.angular_samples,
            "ideal_continuous_estimate_t": ideal,
            "segmentation_factor": segmentation_factor,
            "angular_coverage": angular_coverage,
            "segmented_analytical_estimate_t": segmented,
            "solved_vs_segmented_delta_pct": delta_segmented_pct,
            "convergence": convergence or {},
        },
        "external_leakage": {
            "probe_radius_mm": config.sample_region.leakage_probe_radius,
            "sample_count": len(leakage_samples),
            "rms_b_t": leakage_rms,
            "max_b_t": max(leakage_magnitudes),
            "dominant_field_direction_deg": (
                math.degrees(math.atan2(leakage_mean_by, leakage_mean_bx)) % 360.0
            ),
            "leakage_ratio_rms": leakage_ratio,
        },
        "magnet": {
            "area_mm2": magnet_area_mm2,
            "volume_m3": magnet_volume_m3,
            "mass_kg": magnet_mass_kg,
            "material": material.as_dict(),
            "segments": [
                {
                    "segment_id": region.id,
                    "start_angle_deg": region.start_angle_deg,
                    "end_angle_deg": region.end_angle_deg,
                    "magnetization_angle_deg": region.magnetization_angle_deg,
                    "remanence_t": (
                        list(region.magnetization_xy)
                        if region.magnetization_xy is not None
                        else None
                    ),
                }
                for region in geometry.regions
                if region.kind == "permanent_magnet"
            ],
            "demagnetization_screening": reverse_field,
        },
        "energy": {
            "energy_per_unit_depth_j_per_m": generic_energy,
            "magnetic_energy_extruded_2d_estimate_j": (
                generic_energy * config.geometry.axial_length * 1.0e-3
            ),
            "label": "extruded 2D estimate",
        },
        "timings_ms": timing_report,
        "peak_memory_bytes": peak_memory_bytes,
        "samples": {
            "bore": bore_samples,
            "leakage": leakage_samples,
        },
        "field_data": {
            "nodes_mm": [list(node) for node in mesh.nodes_mm],
            "triangles": [list(triangle) for triangle in mesh.triangles],
            "region_ids": list(mesh.element_region_ids),
            "az_nodal_t_m": az_nodal,
            "element_fields_t": fields,
            "contours": _contour_segments(
                mesh.nodes_mm,
                mesh.triangles,
                az_nodal,
                fields,
                count=config.solve.field_line_count,
            ),
            "available_views": [
                "b_magnitude",
                "b_parallel",
                "b_perpendicular",
                "az",
                "contours",
                "field_lines",
                "vectors",
            ],
        },
        "magnetostatic_problem": magnetostatic_problem,
        "generic_field_report": field_report,
        "warnings": [
            AXIAL_END_EFFECTS_NOTICE,
            *(
                [
                    "Finite design aspect ratio is below 2; axial end effects are "
                    "likely material."
                ]
                if config.geometry.axial_length
                / (2.0 * config.geometry.outer_radius)
                < 2.0
                else []
            ),
            *(
                [
                    (
                        "Catalog coercivity is not audited as intrinsic and cannot "
                        "drive a demagnetization margin."
                        if material.source == "catalog"
                        else "Custom material has no intrinsic coercivity, so a "
                        "demagnetization margin is unavailable."
                    )
                ]
                if not material.coercivity_margin_eligible
                else []
            ),
            *(
                [
                    "Custom material density is missing, so magnet mass is "
                    "unavailable while volume remains valid."
                ]
                if material.density_kg_per_m3 is None
                else []
            ),
            *(
                [
                    "Mean bore field is near zero, so the leakage-to-bore ratio "
                    "is undefined."
                ]
                if leakage_ratio is None
                else []
            ),
        ],
    }
    forbidden_motor_keys = {
        "torque",
        "winding",
        "rpm",
        "back_emf",
        "cogging",
    }
    if forbidden_motor_keys & set(report):
        raise AssertionError("Halbach report leaked motor-only top-level fields")
    return report
