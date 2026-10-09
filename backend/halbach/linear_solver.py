"""End-to-end adapter for finite rectangular linear Halbach arrays."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .linear_geometry import (
    LinearPlanarGeometryArtifact,
    build_linear_planar_geometry,
)
from .linear_gmsh_adapter import (
    LinearHalbachMeshArtifact,
    build_linear_magnetostatic_problem,
    generate_linear_halbach_mesh,
)
from .linear_models import LinearHalbachArrayConfig
from .linear_postprocess import (
    build_linear_halbach_report,
    linear_field_comparison_metrics,
)
from .materials import ResolvedMagnetMaterial, resolve_magnet_material
from .solver import (
    FIELD_REPORT_SCHEMA,
    PROBLEM_SCHEMA,
    _run_field_problem,
)

ROOT = Path(__file__).resolve().parents[2]
LINEAR_HALBACH_CONFIG_SCHEMA = json.loads(
    (
        ROOT
        / "schemas"
        / "v1"
        / "linear_halbach_array_config.schema.json"
    ).read_text(encoding="utf-8")
)
LINEAR_HALBACH_REPORT_SCHEMA = json.loads(
    (
        ROOT
        / "schemas"
        / "v1"
        / "linear_halbach_solution_report.schema.json"
    ).read_text(encoding="utf-8")
)
LINEAR_HALBACH_SCHEMA_REGISTRY = (
    Registry()
    .with_resource(
        (
            "https://coilem.com/schemas/v1/"
            "linear_halbach_array_config.schema.json"
        ),
        Resource.from_contents(LINEAR_HALBACH_CONFIG_SCHEMA),
    )
    .with_resource(
        "linear_halbach_array_config.schema.json",
        Resource.from_contents(LINEAR_HALBACH_CONFIG_SCHEMA),
    )
    .with_resource(
        "https://coilem.com/schemas/v1/magnetostatic_problem.schema.json",
        Resource.from_contents(PROBLEM_SCHEMA),
    )
    .with_resource(
        "magnetostatic_problem.schema.json",
        Resource.from_contents(PROBLEM_SCHEMA),
    )
)

ProgressCallback = Callable[[str, float], None]
FieldRunner = Callable[
    [dict[str, Any]],
    tuple[dict[str, Any], int | None],
]


@dataclass(frozen=True)
class LinearHalbachSolveArtifacts:
    configuration: LinearHalbachArrayConfig
    material: ResolvedMagnetMaterial
    geometry: LinearPlanarGeometryArtifact
    mesh: LinearHalbachMeshArtifact
    magnetostatic_problem: dict[str, Any]
    magnetostatic_problem_sha256: str
    generic_field_report: dict[str, Any]
    linear_halbach_report: dict[str, Any]

    @property
    def halbach_report(self) -> dict[str, Any]:
        """Compatibility alias for route dispatchers."""

        return self.linear_halbach_report


def _emit(
    callback: ProgressCallback | None,
    stage: str,
    fraction: float,
) -> None:
    if callback is not None:
        callback(stage, fraction)


def solve_linear_halbach(
    config: LinearHalbachArrayConfig | dict[str, Any],
    *,
    progress_callback: ProgressCallback | None = None,
    artifact_directory: Path | None = None,
    field_runner: FieldRunner | None = None,
) -> LinearHalbachSolveArtifacts:
    """Validate, mesh, solve, and postprocess one linear Halbach design."""

    total_started = time.perf_counter()
    _emit(progress_callback, "Validating linear array", 0.03)
    validation_started = time.perf_counter()
    resolved_config = (
        config
        if isinstance(config, LinearHalbachArrayConfig)
        else LinearHalbachArrayConfig.model_validate(config)
    )
    material = resolve_magnet_material(resolved_config.magnet)
    validation_finished = time.perf_counter()

    _emit(progress_callback, "Building rectangular cross-section", 0.12)
    geometry_started = time.perf_counter()
    geometry = build_linear_planar_geometry(
        resolved_config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    geometry_finished = time.perf_counter()

    _emit(progress_callback, "Generating rectangular Gmsh mesh", 0.25)
    mesh = generate_linear_halbach_mesh(resolved_config, geometry)

    _emit(progress_callback, "Assigning block magnetization", 0.48)
    lowering_started = time.perf_counter()
    problem, problem_hash = build_linear_magnetostatic_problem(
        resolved_config,
        geometry,
        mesh,
        magnet_mu_r=material.relative_permeability,
    )
    Draft202012Validator(PROBLEM_SCHEMA).validate(problem)
    lowering_finished = time.perf_counter()

    _emit(progress_callback, "Solving Magneto2D field", 0.55)
    solve_started = time.perf_counter()
    if field_runner is None:
        field_report, peak_memory = _run_field_problem(
            problem,
            artifact_directory=artifact_directory,
        )
    else:
        field_report, peak_memory = field_runner(problem)
        Draft202012Validator(FIELD_REPORT_SCHEMA).validate(field_report)
    solve_finished = time.perf_counter()

    convergence: dict[str, Any] = {}
    sensitivity_elapsed_ms = 0.0
    if resolved_config.solve.quality == "fine":
        _emit(progress_callback, "Checking boundary sensitivity", 0.80)
        sensitivity_started = time.perf_counter()
        sensitivity_config = resolved_config.model_copy(deep=True)
        sensitivity_config.solve.quality = "custom"
        sensitivity_config.solve.mesh.outer_padding_factor *= 1.25
        sensitivity_directory = (
            artifact_directory / "boundary_sensitivity"
            if artifact_directory is not None
            else None
        )
        sensitivity = solve_linear_halbach(
            sensitivity_config,
            artifact_directory=sensitivity_directory,
            field_runner=field_runner,
        )
        primary = linear_field_comparison_metrics(
            resolved_config,
            geometry,
            mesh,
            field_report,
        )
        sensitivity_report = sensitivity.linear_halbach_report
        sensitivity_working = float(
            sensitivity_report["working_field"]["b_magnitude_t"]["rms"]
        )
        sensitivity_leakage = float(
            sensitivity_report["leakage_field"]["b_magnitude_t"]["rms"]
        )
        working = primary["working_rms_b_t"]
        leakage = primary["leakage_rms_b_t"]
        convergence = {
            "boundary_sensitivity_rerun": True,
            "requested_outer_padding_factor": (
                resolved_config.solve.mesh.outer_padding_factor
            ),
            "enlarged_outer_padding_factor": (
                sensitivity_config.solve.mesh.outer_padding_factor
            ),
            "working_rms_change_pct": (
                100.0 * (sensitivity_working - working) / working
                if abs(working) > 1.0e-15
                else None
            ),
            "leakage_rms_change_pct": (
                100.0 * (sensitivity_leakage - leakage) / leakage
                if abs(leakage) > 1.0e-15
                else None
            ),
            "enlarged_problem_sha256": (
                sensitivity.magnetostatic_problem_sha256
            ),
            "enlarged_mesh_hash": sensitivity.mesh.mesh_hash,
            "enlarged_peak_memory_bytes": (
                sensitivity_report["peak_memory_bytes"]
            ),
        }
        sensitivity_elapsed_ms = (
            time.perf_counter() - sensitivity_started
        ) * 1000.0

    _emit(progress_callback, "Sampling working and leakage lines", 0.88)
    postprocess_started = time.perf_counter()
    timings = {
        "configuration_validation": (
            validation_finished - validation_started
        )
        * 1000.0,
        "linear_planar_geometry_contract": (
            geometry_finished - geometry_started
        )
        * 1000.0,
        "gmsh_cad": mesh.cad_time_ms,
        "gmsh_mesh_generation": mesh.mesh_generation_time_ms,
        "gmsh_total": mesh.gmsh_time_ms,
        "field_problem_lowering": (
            lowering_finished - lowering_started
        )
        * 1000.0,
        "generic_field_process": (
            solve_finished - solve_started
        )
        * 1000.0,
        "boundary_sensitivity_rerun": sensitivity_elapsed_ms,
    }
    report = build_linear_halbach_report(
        config=resolved_config,
        geometry=geometry,
        mesh=mesh,
        material=material,
        magnetostatic_problem=problem,
        problem_hash=problem_hash,
        field_report=field_report,
        timings_ms=timings,
        peak_memory_bytes=peak_memory,
        convergence=convergence,
    )
    postprocess_finished = time.perf_counter()
    report["timings_ms"]["linear_halbach_postprocessing"] = (
        postprocess_finished - postprocess_started
    ) * 1000.0
    report["timings_ms"]["total_wall"] = (
        postprocess_finished - total_started
    ) * 1000.0
    Draft202012Validator(
        LINEAR_HALBACH_REPORT_SCHEMA,
        registry=LINEAR_HALBACH_SCHEMA_REGISTRY,
    ).validate(report)
    _emit(progress_callback, "Preparing linear Halbach report", 1.0)
    return LinearHalbachSolveArtifacts(
        configuration=resolved_config,
        material=material,
        geometry=geometry,
        mesh=mesh,
        magnetostatic_problem=problem,
        magnetostatic_problem_sha256=problem_hash,
        generic_field_report=field_report,
        linear_halbach_report=report,
    )
