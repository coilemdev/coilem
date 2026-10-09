"""One-sided field metrics for a finite rectangular linear Halbach array."""

from __future__ import annotations

from typing import Any

from .linear_geometry import (
    LINEAR_MODEL_NOTICE,
    LinearPlanarGeometryArtifact,
)
from .linear_gmsh_adapter import LinearHalbachMeshArtifact
from .linear_models import LinearHalbachArrayConfig
from .materials import ResolvedMagnetMaterial
from .postprocess import (
    _contour_segments,
    _reverse_field_metrics,
    _sample,
    _statistics,
)
from .postprocess import _TriangleLocator as TriangleLocator


def _line_samples(
    *,
    y_mm: float,
    x_start_mm: float,
    x_end_mm: float,
    sample_count: int,
    locator: TriangleLocator,
    fields: list[dict[str, float]],
) -> list[dict[str, float]]:
    if sample_count < 2:
        raise ValueError("linear Halbach probe line requires at least two samples")
    return [
        _sample(
            locator,
            fields,
            x_start_mm
            + (x_end_mm - x_start_mm) * index / (sample_count - 1),
            y_mm,
        )
        for index in range(sample_count)
    ]


def _line_metrics(samples: list[dict[str, float]]) -> dict[str, Any]:
    return {
        "b_magnitude_t": _statistics(
            [sample["b_magnitude_t"] for sample in samples]
        ),
        "bx_t": _statistics([sample["bx_t"] for sample in samples]),
        "by_t": _statistics([sample["by_t"] for sample in samples]),
    }


def linear_field_comparison_metrics(
    config: LinearHalbachArrayConfig,
    geometry: LinearPlanarGeometryArtifact,
    mesh: LinearHalbachMeshArtifact,
    field_report: dict[str, Any],
) -> dict[str, float]:
    """Return boundary-sensitivity headline values."""

    fields = field_report["solution"]["element_fields"]
    locator = TriangleLocator(mesh.nodes_mm, mesh.triangles)
    probes = geometry.metadata["probe_lines"]
    count = (
        probes["retained_periods"]
        * config.sample_region.samples_per_period
        + 1
    )
    working = _line_samples(
        y_mm=probes["working_y_mm"],
        x_start_mm=probes["x_min_mm"],
        x_end_mm=probes["x_max_mm"],
        sample_count=count,
        locator=locator,
        fields=fields,
    )
    leakage = _line_samples(
        y_mm=probes["leakage_y_mm"],
        x_start_mm=probes["x_min_mm"],
        x_end_mm=probes["x_max_mm"],
        sample_count=count,
        locator=locator,
        fields=fields,
    )
    return {
        "working_rms_b_t": _statistics(
            [sample["b_magnitude_t"] for sample in working]
        )["rms"],
        "leakage_rms_b_t": _statistics(
            [sample["b_magnitude_t"] for sample in leakage]
        )["rms"],
    }


def build_linear_halbach_report(
    *,
    config: LinearHalbachArrayConfig,
    geometry: LinearPlanarGeometryArtifact,
    mesh: LinearHalbachMeshArtifact,
    material: ResolvedMagnetMaterial,
    magnetostatic_problem: dict[str, Any],
    problem_hash: str,
    field_report: dict[str, Any],
    timings_ms: dict[str, float],
    peak_memory_bytes: int | None,
    convergence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the strict linear Halbach solution report."""

    solution = field_report["solution"]
    fields = solution["element_fields"]
    az_nodal = [float(value) for value in solution["az_nodal"]]
    if len(fields) != len(mesh.triangles):
        raise ValueError(
            "generic field report element count does not match linear "
            "Halbach mesh"
        )
    if len(az_nodal) != len(mesh.nodes_mm):
        raise ValueError(
            "generic field report node count does not match linear "
            "Halbach mesh"
        )

    locator = TriangleLocator(mesh.nodes_mm, mesh.triangles)
    probes = geometry.metadata["probe_lines"]
    sample_count = (
        probes["retained_periods"]
        * config.sample_region.samples_per_period
        + 1
    )
    working_samples = _line_samples(
        y_mm=probes["working_y_mm"],
        x_start_mm=probes["x_min_mm"],
        x_end_mm=probes["x_max_mm"],
        sample_count=sample_count,
        locator=locator,
        fields=fields,
    )
    leakage_samples = _line_samples(
        y_mm=probes["leakage_y_mm"],
        x_start_mm=probes["x_min_mm"],
        x_end_mm=probes["x_max_mm"],
        sample_count=sample_count,
        locator=locator,
        fields=fields,
    )
    working_metrics = _line_metrics(working_samples)
    leakage_metrics = _line_metrics(leakage_samples)
    working_magnitude = working_metrics["b_magnitude_t"]
    leakage_magnitude = leakage_metrics["b_magnitude_t"]
    working_rms = working_magnitude["rms"]
    leakage_rms = leakage_magnitude["rms"]
    ripple_ppm = (
        1.0e6 * working_magnitude["peak_to_peak"] / working_magnitude["mean"]
        if abs(working_magnitude["mean"]) > 1.0e-15
        else None
    )
    leakage_ratio = (
        leakage_rms / working_rms if abs(working_rms) > 1.0e-15 else None
    )
    suppression_ratio = (
        working_rms / leakage_rms if abs(leakage_rms) > 1.0e-15 else None
    )

    magnet_area_mm2 = (
        config.geometry.block_count
        * config.geometry.block_width
        * config.geometry.magnet_height
    )
    magnet_volume_m3 = (
        magnet_area_mm2
        * config.geometry.out_of_plane_depth
        * 1.0e-9
    )
    magnet_mass_kg = (
        magnet_volume_m3 * material.density_kg_per_m3
        if material.density_kg_per_m3 is not None
        else None
    )
    reverse_field = _reverse_field_metrics(
        geometry,
        mesh,
        fields,
        material,
    )
    reverse_blocks = []
    for row in reverse_field.pop("segments"):
        block = dict(row)
        block["block_id"] = block.pop("segment_id")
        reverse_blocks.append(block)
    reverse_field["blocks"] = reverse_blocks

    generic_timings = solution.get("timings", {})
    timing_report = {
        **timings_ms,
        "generic_preparation": float(
            generic_timings.get("preparation_ms", 0.0)
        ),
        "generic_assembly": float(
            generic_timings.get("assembly_ms", 0.0)
        ),
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
    generic_energy = float(
        solution["energy_per_unit_depth"]["magnetic_field_j_per_m"]
    )
    report = {
        "openem_schema_kind": "linear_halbach_solution_report",
        "openem_schema_version": "1.0",
        "model": {
            "dimensionality": "2d",
            "formulation": "planar_az",
            "assumption": "finite_xy_infinite_out_of_plane",
            "finite_array_end_fringing_modeled": True,
            "out_of_plane_end_effects_modeled": False,
            "out_of_plane_depth_usage": [
                "design_preview",
                "volume_and_mass",
                "extruded_2d_estimates",
            ],
            "notice": LINEAR_MODEL_NOTICE,
        },
        "configuration": config.model_dump(mode="json", exclude_none=True),
        "geometry": geometry.as_dict(),
        "mesh": mesh.preview_payload(),
        "artifacts": {
            "magnetostatic_problem_sha256": problem_hash,
            "generic_field_report_input_sha256": field_report.get(
                "openem_provenance",
                {},
            ).get("fixture_sha256"),
            "geometry_hash": geometry.geometry_hash,
            "mesh_hash": mesh.mesh_hash,
        },
        "working_field": {
            **working_metrics,
            "headline": "RMS field magnitude on the enhanced-side probe line",
            "strong_side": config.array.strong_side,
            "line_y_mm": probes["working_y_mm"],
            "x_start_mm": probes["x_min_mm"],
            "x_end_mm": probes["x_max_mm"],
            "probe_offset_mm": config.sample_region.probe_offset,
            "edge_exclusion_periods": (
                config.sample_region.edge_exclusion_periods
            ),
            "sample_count": len(working_samples),
            "ripple_ppm": ripple_ppm,
            "convergence": convergence or {},
        },
        "leakage_field": {
            **leakage_metrics,
            "headline": "RMS field magnitude on the weak-side probe line",
            "line_y_mm": probes["leakage_y_mm"],
            "x_start_mm": probes["x_min_mm"],
            "x_end_mm": probes["x_max_mm"],
            "probe_offset_mm": config.sample_region.probe_offset,
            "edge_exclusion_periods": (
                config.sample_region.edge_exclusion_periods
            ),
            "sample_count": len(leakage_samples),
        },
        "one_sidedness": {
            "leakage_ratio_rms": leakage_ratio,
            "suppression_ratio": suppression_ratio,
            "ratio_definition": "leakage_rms_b / working_rms_b",
            "suppression_definition": "working_rms_b / leakage_rms_b",
        },
        "magnet": {
            "area_mm2": magnet_area_mm2,
            "volume_m3": magnet_volume_m3,
            "mass_kg": magnet_mass_kg,
            "material": material.as_dict(),
            "blocks": [
                {
                    "block_id": region.id,
                    "bounds_mm": list(region.bounds_mm),
                    "magnetization_angle_deg": (
                        region.magnetization_angle_deg
                    ),
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
                generic_energy
                * config.geometry.out_of_plane_depth
                * 1.0e-3
            ),
            "label": "extruded 2D estimate",
        },
        "timings_ms": timing_report,
        "peak_memory_bytes": peak_memory_bytes,
        "samples": {
            "working": working_samples,
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
                "bx",
                "by",
                "az",
                "contours",
                "field_lines",
                "vectors",
            ],
        },
        "magnetostatic_problem": magnetostatic_problem,
        "generic_field_report": field_report,
        "warnings": [
            LINEAR_MODEL_NOTICE,
            *(
                [
                    "Only one magnetic period is present; finite in-plane end "
                    "fringing dominates the probe-line metrics."
                ]
                if config.geometry.period_count == 1
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
                    "Working-side RMS field is near zero, so the leakage ratio "
                    "is undefined."
                ]
                if leakage_ratio is None
                else []
            ),
            *(
                [
                    "Weak-side RMS field is near zero, so the suppression ratio "
                    "is undefined."
                ]
                if suppression_ratio is None
                else []
            ),
        ],
    }
    forbidden_cylindrical_keys = {
        "bore_field",
        "external_leakage",
        "inner_radius",
        "outer_radius",
        "segment_count",
    }
    if forbidden_cylindrical_keys & set(report):
        raise AssertionError(
            "linear Halbach report leaked cylindrical-only top-level fields"
        )
    return report
