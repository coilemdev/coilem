"""Public-safe Cylindrical Halbach design, mesh, solve, and export routes."""

from __future__ import annotations

import json
import math
import queue
import threading
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, ValidationError

from backend.halbach.exports import (
    design_png,
    design_svg,
    generic_field_report_json,
    halbach_report_json,
    magnetostatic_problem_json,
    report_pdf,
    samples_csv,
)
from backend.halbach.geometry import (
    AXIAL_END_EFFECTS_NOTICE,
    build_planar_geometry,
)
from backend.halbach.gmsh_adapter import (
    build_magnetostatic_problem,
    generate_halbach_mesh,
)
from backend.halbach.linear_geometry import (
    LINEAR_MODEL_NOTICE,
    build_linear_planar_geometry,
)
from backend.halbach.linear_gmsh_adapter import (
    build_linear_magnetostatic_problem,
    generate_linear_halbach_mesh,
)
from backend.halbach.linear_models import LinearHalbachArrayConfig
from backend.halbach.linear_solver import solve_linear_halbach
from backend.halbach.materials import resolve_magnet_material
from backend.halbach.models import HalbachArrayConfig
from backend.halbach.postprocess import segmented_analytical_factor
from backend.halbach.solver import (
    HALBACH_REPORT_SCHEMA,
    HALBACH_SCHEMA_REGISTRY,
    solve_halbach,
)

router = APIRouter(prefix="/halbach", tags=["halbach"])


def halbach_capability_payload() -> dict[str, Any]:
    return {
        "available": True,
        "array_types": ["cylindrical", "linear"],
        "field_modes": ["internal"],
        "multipole_orders": [1],
        "segment_shapes": ["annular_wedge", "rectangular_block"],
        "segment_count_range": [4, 64],
        "linear": {
            "blocks_per_period": 4,
            "period_count_range": [1, 16],
            "strong_sides": ["positive_y", "negative_y"],
            "finite_in_plane": True,
        },
        "solver": "magneto2d_field",
        "axial_end_effects_modeled": False,
    }


def _design_health(
    config: HalbachArrayConfig,
    *,
    material: Any,
) -> dict[str, Any]:
    pitch = 360.0 / config.geometry.segment_count
    coverage = 1.0 - config.geometry.segment_gap_angle / pitch
    ideal = material.remanence_t * math.log(
        config.geometry.outer_radius / config.geometry.inner_radius
    )
    segmentation, analytical_coverage = segmented_analytical_factor(
        config.geometry.segment_count,
        config.geometry.segment_gap_angle,
    )
    magnet_area = (
        0.5
        * (config.geometry.outer_radius**2 - config.geometry.inner_radius**2)
        * math.radians(360.0 - config.geometry.segment_count * config.geometry.segment_gap_angle)
    )
    volume = magnet_area * config.geometry.axial_length * 1.0e-9
    warnings: list[dict[str, str]] = [
        {
            "code": "INFINITE_LENGTH_2D_MODEL",
            "field": "geometry.axial_length",
            "message": AXIAL_END_EFFECTS_NOTICE,
        }
    ]
    if config.geometry.segment_count < 8:
        warnings.append(
            {
                "code": "COARSE_SEGMENTATION",
                "field": "geometry.segment_count",
                "message": "Fewer than 8 segments is a visibly coarse Halbach approximation.",
            }
        )
    if config.geometry.segment_gap_angle > 0.05 * pitch:
        warnings.append(
            {
                "code": "LARGE_ANGULAR_GAP",
                "field": "geometry.segment_gap_angle",
                "message": "The angular gap exceeds 5% of the segment pitch.",
            }
        )
    aspect_ratio = config.geometry.axial_length / (
        2.0 * config.geometry.outer_radius
    )
    if aspect_ratio < 2.0:
        warnings.append(
            {
                "code": "AXIAL_END_EFFECTS_LIKELY",
                "field": "geometry.axial_length",
                "message": "Length / outer diameter is below 2; axial end effects are likely material.",
            }
        )
    if material.density_kg_per_m3 is None:
        warnings.append(
            {
                "code": "MASS_UNAVAILABLE",
                "field": "magnet.density_kg_per_m3",
                "message": "Custom material density is missing, so mass is unavailable.",
            }
        )
    if not material.coercivity_margin_eligible:
        warnings.append(
            {
                "code": "DEMAG_MARGIN_INELIGIBLE",
                "field": "magnet",
                "message": "Only an audited intrinsic H_cj may drive a screening margin.",
            }
        )
    return {
        "ready_to_solve": True,
        "errors": [],
        "warnings": warnings,
        "checks": [
            {"label": "Radius ratio", "value": config.geometry.outer_radius / config.geometry.inner_radius},
            {"label": "Length / outer diameter", "value": aspect_ratio},
            {"label": "Angular magnet coverage", "value": coverage},
            {"label": "ROI / bore radius", "value": config.sample_region.radius / config.geometry.inner_radius},
        ],
        "analytics": {
            "ideal_continuous_bore_field_t": ideal,
            "segmented_bore_field_estimate_t": (
                ideal * segmentation * analytical_coverage
            ),
            "magnet_area_mm2": magnet_area,
            "magnet_volume_m3": volume,
            "magnet_mass_kg": (
                volume * material.density_kg_per_m3
                if material.density_kg_per_m3 is not None
                else None
            ),
        },
    }


def _linear_design_health(
    config: LinearHalbachArrayConfig,
    *,
    material: Any,
) -> dict[str, Any]:
    geometry = config.geometry
    magnet_area = geometry.block_count * geometry.block_width * geometry.magnet_height
    volume = magnet_area * geometry.out_of_plane_depth * 1.0e-9
    height_to_wavelength = geometry.magnet_height / geometry.wavelength
    probe_to_wavelength = config.sample_region.probe_offset / geometry.wavelength
    retained_periods = (
        geometry.period_count - 2 * config.sample_region.edge_exclusion_periods
    )
    warnings: list[dict[str, str]] = [
        {
            "code": "FINITE_2D_EXTRUSION_MODEL",
            "field": "geometry.out_of_plane_depth",
            "message": LINEAR_MODEL_NOTICE,
        }
    ]
    if geometry.period_count < 3:
        warnings.append(
            {
                "code": "SHORT_FINITE_ARRAY",
                "field": "geometry.period_count",
                "message": (
                    "Fewer than 3 periods leaves little center span that is "
                    "independent of finite-array end fringing."
                ),
            }
        )
    if config.sample_region.edge_exclusion_periods == 0:
        warnings.append(
            {
                "code": "END_FRINGING_INCLUDED_IN_METRICS",
                "field": "sample_region.edge_exclusion_periods",
                "message": (
                    "The probe-line metrics include the finite-array ends; "
                    "exclude at least one period for a center-field comparison."
                ),
            }
        )
    if geometry.block_gap > 0.05 * geometry.block_width:
        warnings.append(
            {
                "code": "LARGE_BLOCK_GAP",
                "field": "geometry.block_gap",
                "message": "The block gap exceeds 5% of the block width.",
            }
        )
    if material.density_kg_per_m3 is None:
        warnings.append(
            {
                "code": "MASS_UNAVAILABLE",
                "field": "magnet.density_kg_per_m3",
                "message": "Custom material density is missing, so mass is unavailable.",
            }
        )
    return {
        "ready_to_solve": True,
        "errors": [],
        "warnings": warnings,
        "checks": [
            {"label": "Magnet height / wavelength", "value": height_to_wavelength},
            {"label": "Probe offset / wavelength", "value": probe_to_wavelength},
            {"label": "Retained center periods", "value": retained_periods},
            {
                "label": "Block gap / block width",
                "value": geometry.block_gap / geometry.block_width,
            },
        ],
        "analytics": {
            "block_count": geometry.block_count,
            "wavelength_mm": geometry.wavelength,
            "active_length_mm": geometry.active_length,
            "magnet_area_mm2": magnet_area,
            "magnet_volume_m3": volume,
            "magnet_mass_kg": (
                volume * material.density_kg_per_m3
                if material.density_kg_per_m3 is not None
                else None
            ),
        },
    }


@router.post("/preview")
def preview(config: HalbachArrayConfig) -> dict[str, Any]:
    material = resolve_magnet_material(config.magnet)
    geometry = build_planar_geometry(
        config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    return {
        "kind": "halbach_preview",
        "version": "1.0",
        "configuration": config.model_dump(mode="json"),
        "geometry": geometry.as_dict(),
        "material": material.as_dict(),
        "design_health": _design_health(config, material=material),
    }


@router.post("/linear/preview")
def linear_preview(config: LinearHalbachArrayConfig) -> dict[str, Any]:
    material = resolve_magnet_material(config.magnet)
    geometry = build_linear_planar_geometry(
        config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    return {
        "kind": "linear_halbach_preview",
        "version": "1.0",
        "configuration": config.model_dump(mode="json"),
        "geometry": geometry.as_dict(),
        "material": material.as_dict(),
        "design_health": _linear_design_health(config, material=material),
    }


@router.post("/mesh-preview")
def mesh_preview(config: HalbachArrayConfig) -> dict[str, Any]:
    material = resolve_magnet_material(config.magnet)
    geometry = build_planar_geometry(
        config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    mesh = generate_halbach_mesh(config, geometry)
    _problem, problem_hash = build_magnetostatic_problem(
        config, geometry, mesh, magnet_mu_r=material.relative_permeability
    )
    return {
        **mesh.preview_payload(),
        "geometry_hash": geometry.geometry_hash,
        "magnetostatic_problem_sha256": problem_hash,
    }


@router.post("/linear/mesh-preview")
def linear_mesh_preview(config: LinearHalbachArrayConfig) -> dict[str, Any]:
    material = resolve_magnet_material(config.magnet)
    geometry = build_linear_planar_geometry(
        config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    mesh = generate_linear_halbach_mesh(config, geometry)
    _problem, problem_hash = build_linear_magnetostatic_problem(
        config,
        geometry,
        mesh,
        magnet_mu_r=material.relative_permeability,
    )
    return {
        **mesh.preview_payload(),
        "geometry_hash": geometry.geometry_hash,
        "magnetostatic_problem_sha256": problem_hash,
    }


@router.post("/solve/validate")
def solve_validate(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        config = HalbachArrayConfig.model_validate(payload)
        material = resolve_magnet_material(config.magnet)
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            errors = [
                {
                    "field": ".".join(str(part) for part in error.get("loc", ())),
                    "message": error.get("msg", "Invalid configuration"),
                    "type": error.get("type", "value_error"),
                }
                for error in exc.errors()
            ]
        else:
            errors = [
                {
                    "field": "",
                    "message": str(exc),
                    "type": "value_error",
                }
            ]
        return {
            "valid": False,
            "errors": errors,
            "warnings": [],
        }
    health = _design_health(config, material=material)
    return {
        "valid": True,
        "errors": [],
        "warnings": health["warnings"],
        "design_health": health,
        "solver_lane": "magneto2d_field",
    }


@router.post("/linear/solve/validate")
def linear_solve_validate(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        config = LinearHalbachArrayConfig.model_validate(payload)
        material = resolve_magnet_material(config.magnet)
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            errors = [
                {
                    "field": ".".join(str(part) for part in error.get("loc", ())),
                    "message": error.get("msg", "Invalid configuration"),
                    "type": error.get("type", "value_error"),
                }
                for error in exc.errors()
            ]
        else:
            errors = [
                {
                    "field": "",
                    "message": str(exc),
                    "type": "value_error",
                }
            ]
        return {"valid": False, "errors": errors, "warnings": []}
    health = _linear_design_health(config, material=material)
    return {
        "valid": True,
        "errors": [],
        "warnings": health["warnings"],
        "design_health": health,
        "solver_lane": "magneto2d_field",
    }


@router.post("/solve")
def solve(config: HalbachArrayConfig) -> dict[str, Any]:
    artifacts = solve_halbach(config)
    return artifacts.halbach_report


@router.post("/linear/solve")
def linear_solve(config: LinearHalbachArrayConfig) -> dict[str, Any]:
    artifacts = solve_linear_halbach(config)
    return artifacts.linear_halbach_report


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


@router.post("/solve/stream")
def solve_stream(config: HalbachArrayConfig) -> StreamingResponse:
    def events():
        messages: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()

        def progress(stage: str, fraction: float) -> None:
            messages.put(
                (
                    "progress",
                    {"stage": stage, "fraction": fraction, "percent": round(fraction * 100.0, 1)},
                )
            )

        def worker() -> None:
            try:
                artifacts = solve_halbach(config, progress_callback=progress)
                messages.put(("complete", artifacts.halbach_report))
            except Exception as exc:  # route converts worker failures to SSE
                messages.put(
                    (
                        "error",
                        {
                            "error_code": "HALBACH_SOLVE_FAILED",
                            "message": str(exc),
                        },
                    )
                )

        thread = threading.Thread(target=worker, name="halbach-solve", daemon=True)
        thread.start()
        while True:
            event, payload = messages.get()
            yield _sse(event, payload)
            if event in {"complete", "error"}:
                break

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/linear/solve/stream")
def linear_solve_stream(config: LinearHalbachArrayConfig) -> StreamingResponse:
    def events():
        messages: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()

        def progress(stage: str, fraction: float) -> None:
            messages.put(
                (
                    "progress",
                    {
                        "stage": stage,
                        "fraction": fraction,
                        "percent": round(fraction * 100.0, 1),
                    },
                )
            )

        def worker() -> None:
            try:
                artifacts = solve_linear_halbach(
                    config,
                    progress_callback=progress,
                )
                messages.put(("complete", artifacts.linear_halbach_report))
            except Exception as exc:  # route converts worker failures to SSE
                messages.put(
                    (
                        "error",
                        {
                            "error_code": "LINEAR_HALBACH_SOLVE_FAILED",
                            "message": str(exc),
                        },
                    )
                )

        thread = threading.Thread(
            target=worker,
            name="linear-halbach-solve",
            daemon=True,
        )
        thread.start()
        while True:
            event, payload = messages.get()
            yield _sse(event, payload)
            if event in {"complete", "error"}:
                break

    return StreamingResponse(events(), media_type="text/event-stream")


class HalbachExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report: dict[str, Any]


@router.post("/export/{export_kind}")
def export_report(
    export_kind: Literal["report", "problem", "field", "csv", "svg", "png", "pdf"],
    request: HalbachExportRequest,
) -> Response:
    report = request.report
    validation_errors = sorted(
        Draft202012Validator(
            HALBACH_REPORT_SCHEMA,
            registry=HALBACH_SCHEMA_REGISTRY,
        ).iter_errors(report),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if validation_errors:
        first = validation_errors[0]
        field = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Halbach report at {field}: {first.message}",
        )
    if report.get("model", {}).get("axial_end_effects_modeled") is not False:
        raise HTTPException(
            status_code=400,
            detail="Halbach export requires axial_end_effects_modeled=false.",
        )
    if AXIAL_END_EFFECTS_NOTICE not in report.get("model", {}).get("notice", ""):
        raise HTTPException(
            status_code=400,
            detail="Halbach export is missing the permanent axial-end-effect notice.",
        )
    try:
        if export_kind == "report":
            body, content_type, filename = (
                halbach_report_json(report),
                "application/json",
                "halbach-solution-report.json",
            )
        elif export_kind == "problem":
            body, content_type, filename = (
                magnetostatic_problem_json(report),
                "application/json",
                "magnetostatic-problem.json",
            )
        elif export_kind == "field":
            body, content_type, filename = (
                generic_field_report_json(report),
                "application/json",
                "field-solution-report.json",
            )
        elif export_kind == "csv":
            body, content_type, filename = (
                samples_csv(report),
                "text/csv; charset=utf-8",
                "halbach-field-samples.csv",
            )
        elif export_kind == "svg":
            body, content_type, filename = (
                design_svg(report),
                "image/svg+xml",
                "halbach-field-plot.svg",
            )
        elif export_kind == "png":
            body, content_type, filename = (
                design_png(report),
                "image/png",
                "halbach-field-plot.png",
            )
        else:
            body, content_type, filename = (
                report_pdf(report),
                "application/pdf",
                "halbach-report.pdf",
            )
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
