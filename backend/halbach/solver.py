"""End-to-end Halbach adapter around the production Magneto2D field CLI."""

from __future__ import annotations

import concurrent.futures
import ctypes
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.magneto2d_adapter import ensure_magneto2d_binary
from backend.solver_environment import solver_process_environment

from .geometry import PlanarEmGeometryArtifact, build_planar_geometry
from .gmsh_adapter import (
    HalbachMeshArtifact,
    build_magnetostatic_problem,
    canonical_json_bytes,
    generate_halbach_mesh,
)
from .materials import ResolvedMagnetMaterial, resolve_magnet_material
from .models import HalbachArrayConfig
from .postprocess import build_halbach_report, field_comparison_metrics

ROOT = Path(__file__).resolve().parents[2]
PROBLEM_SCHEMA = json.loads(
    (ROOT / "schemas" / "v1" / "magnetostatic_problem.schema.json").read_text(
        encoding="utf-8"
    )
)
FIELD_REPORT_SCHEMA = json.loads(
    (ROOT / "schemas" / "v1" / "field_solution_report.schema.json").read_text(
        encoding="utf-8"
    )
)
HALBACH_CONFIG_SCHEMA = json.loads(
    (ROOT / "schemas" / "v1" / "halbach_array_config.schema.json").read_text(
        encoding="utf-8"
    )
)
HALBACH_REPORT_SCHEMA = json.loads(
    (ROOT / "schemas" / "v1" / "halbach_solution_report.schema.json").read_text(
        encoding="utf-8"
    )
)
HALBACH_SCHEMA_REGISTRY = Registry().with_resource(
    "https://coilem.com/schemas/v1/halbach_array_config.schema.json",
    Resource.from_contents(HALBACH_CONFIG_SCHEMA),
).with_resource(
    "halbach_array_config.schema.json",
    Resource.from_contents(HALBACH_CONFIG_SCHEMA),
).with_resource(
    "https://coilem.com/schemas/v1/magnetostatic_problem.schema.json",
    Resource.from_contents(PROBLEM_SCHEMA),
)

ProgressCallback = Callable[[str, float], None]


@dataclass(frozen=True)
class HalbachSolveArtifacts:
    configuration: HalbachArrayConfig
    material: ResolvedMagnetMaterial
    geometry: PlanarEmGeometryArtifact
    mesh: HalbachMeshArtifact
    magnetostatic_problem: dict[str, Any]
    magnetostatic_problem_sha256: str
    generic_field_report: dict[str, Any]
    halbach_report: dict[str, Any]


def _emit(callback: ProgressCallback | None, stage: str, fraction: float) -> None:
    if callback is not None:
        callback(stage, fraction)


def _run_field_problem(
    problem: dict[str, Any],
    *,
    artifact_directory: Path | None = None,
) -> tuple[dict[str, Any], int | None]:
    executable = ensure_magneto2d_binary()
    if artifact_directory is None:
        temporary = tempfile.TemporaryDirectory(prefix="openem-halbach-")
        workdir = Path(temporary.name)
    else:
        temporary = None
        workdir = artifact_directory
        workdir.mkdir(parents=True, exist_ok=True)
    try:
        problem_path = workdir / "magnetostatic_problem.json"
        report_path = workdir / "field_solution_report.json"
        problem_path.write_bytes(canonical_json_bytes(problem))
        process = subprocess.Popen(
            [
                str(executable),
                str(problem_path),
                "--mode",
                "field",
                "-o",
                str(report_path),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=solver_process_environment(),
        )
        peak_memory: int | None = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            communication = executor.submit(process.communicate)
            while not communication.done():
                rss = _process_rss_bytes(process)
                if rss is not None:
                    peak_memory = rss if peak_memory is None else max(peak_memory, rss)
                time.sleep(0.01)
            stdout, stderr = communication.result()
        if process.returncode != 0:
            raise RuntimeError(
                "Magneto2D field solve failed: "
                f"{stderr.strip() or stdout.strip() or process.returncode}"
            )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        Draft202012Validator(FIELD_REPORT_SCHEMA).validate(report)
        input_hash = report.get("openem_provenance", {}).get("fixture_sha256")
        expected_hash = problem_path_identity(problem)
        if input_hash is not None and input_hash != expected_hash:
            raise RuntimeError(
                "Magneto2D input hash does not match the retained canonical "
                "magnetostatic_problem artifact"
            )
        return report, peak_memory
    finally:
        if temporary is not None:
            temporary.cleanup()


def problem_path_identity(problem: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(canonical_json_bytes(problem)).hexdigest()


def _process_rss_bytes(process: subprocess.Popen[str]) -> int | None:
    """Best-effort child RSS without an undeclared runtime dependency."""

    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        try:
            return int(psutil.Process(process.pid).memory_info().rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return None

    if sys.platform != "win32" or not hasattr(process, "_handle"):
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    try:
        success = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(int(process._handle)),  # type: ignore[attr-defined]
            ctypes.byref(counters),
            counters.cb,
        )
    except (AttributeError, OSError, ValueError):
        return None
    return int(counters.WorkingSetSize) if success else None


def solve_halbach(
    config: HalbachArrayConfig | dict[str, Any],
    *,
    progress_callback: ProgressCallback | None = None,
    artifact_directory: Path | None = None,
    field_runner: Callable[
        [dict[str, Any]], tuple[dict[str, Any], int | None]
    ]
    | None = None,
) -> HalbachSolveArtifacts:
    """Validate, mesh, solve, and postprocess one v1 Halbach design."""

    total_started = time.perf_counter()
    _emit(progress_callback, "Validating design", 0.03)
    validation_started = time.perf_counter()
    resolved_config = (
        config
        if isinstance(config, HalbachArrayConfig)
        else HalbachArrayConfig.model_validate(config)
    )
    material = resolve_magnet_material(resolved_config.magnet)
    validation_finished = time.perf_counter()

    _emit(progress_callback, "Building cross-section", 0.12)
    geometry_started = time.perf_counter()
    geometry = build_planar_geometry(
        resolved_config,
        remanence_t=material.remanence_t,
        material_key=material.name,
    )
    geometry_finished = time.perf_counter()

    _emit(progress_callback, "Generating Gmsh mesh", 0.25)
    mesh = generate_halbach_mesh(resolved_config, geometry)

    _emit(progress_callback, "Assigning segment magnetization", 0.48)
    lowering_started = time.perf_counter()
    problem, problem_hash = build_magnetostatic_problem(
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
            problem, artifact_directory=artifact_directory
        )
    else:
        field_report, peak_memory = field_runner(problem)
    solve_finished = time.perf_counter()

    convergence: dict[str, Any] = {}
    if resolved_config.solve.quality == "fine":
        _emit(progress_callback, "Checking outer-boundary sensitivity", 0.80)
        sensitivity_started = time.perf_counter()
        sensitivity_config = resolved_config.model_copy(deep=True)
        sensitivity_config.solve.quality = "custom"
        sensitivity_config.solve.mesh.outer_boundary_radius_factor *= 1.25
        sensitivity_directory = (
            artifact_directory / "boundary_sensitivity"
            if artifact_directory is not None
            else None
        )
        sensitivity = solve_halbach(
            sensitivity_config,
            artifact_directory=sensitivity_directory,
            field_runner=field_runner,
        )
        primary_diagnostics = field_comparison_metrics(
            resolved_config,
            mesh,
            field_report,
        )
        primary_mean = primary_diagnostics["mean_b_parallel_t"]
        sensitivity_report = sensitivity.halbach_report
        sensitivity_mean = float(
            sensitivity_report["bore_field"]["b_parallel_t"]["mean"]
        )
        primary_leakage = primary_diagnostics["leakage_rms_b_t"]
        sensitivity_leakage = float(
            sensitivity_report["external_leakage"]["rms_b_t"]
        )
        convergence = {
            "boundary_sensitivity_rerun": True,
            "requested_outer_boundary_radius_factor": (
                resolved_config.solve.mesh.outer_boundary_radius_factor
            ),
            "enlarged_outer_boundary_radius_factor": (
                sensitivity_config.solve.mesh.outer_boundary_radius_factor
            ),
            "mean_b_parallel_change_pct": (
                100.0 * (sensitivity_mean - primary_mean) / primary_mean
                if abs(primary_mean) > 1.0e-15
                else None
            ),
            "leakage_rms_change_pct": (
                100.0
                * (sensitivity_leakage - primary_leakage)
                / primary_leakage
                if abs(primary_leakage) > 1.0e-15
                else None
            ),
            "enlarged_problem_sha256": (
                sensitivity.magnetostatic_problem_sha256
            ),
            "enlarged_mesh_hash": sensitivity.mesh.mesh_hash,
            "enlarged_peak_memory_bytes": sensitivity_report[
                "peak_memory_bytes"
            ],
        }
        sensitivity_finished = time.perf_counter()

    _emit(progress_callback, "Sampling bore and leakage fields", 0.88)
    postprocess_started = time.perf_counter()
    timings = {
        "configuration_validation": (
            validation_finished - validation_started
        )
        * 1000.0,
        "planar_geometry_contract": (geometry_finished - geometry_started)
        * 1000.0,
        "gmsh_cad": mesh.cad_time_ms,
        "gmsh_mesh_generation": mesh.mesh_generation_time_ms,
        "gmsh_total": mesh.gmsh_time_ms,
        "field_problem_lowering": (lowering_finished - lowering_started)
        * 1000.0,
        "generic_field_process": (solve_finished - solve_started) * 1000.0,
        "boundary_sensitivity_rerun": (
            (sensitivity_finished - sensitivity_started) * 1000.0
            if convergence
            else 0.0
        ),
    }
    report = build_halbach_report(
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
    report["timings_ms"]["halbach_postprocessing"] = (
        postprocess_finished - postprocess_started
    ) * 1000.0
    report["timings_ms"]["total_wall"] = (
        postprocess_finished - total_started
    ) * 1000.0
    Draft202012Validator(
        HALBACH_REPORT_SCHEMA,
        registry=HALBACH_SCHEMA_REGISTRY,
    ).validate(report)
    _emit(progress_callback, "Preparing report", 1.0)
    return HalbachSolveArtifacts(
        configuration=resolved_config,
        material=material,
        geometry=geometry,
        mesh=mesh,
        magnetostatic_problem=problem,
        magnetostatic_problem_sha256=problem_hash,
        generic_field_report=field_report,
        halbach_report=report,
    )
