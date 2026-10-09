"""Elmer implementation of coilEM's solver-neutral 2D motor contract."""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.back_emf_harmonics import (
    analyze_back_emf_harmonics,
    harmonic_limit_for_quality,
)
from backend.field_lines import build_field_line_plot_from_mesh
from backend.gmsh_solver import run_gmsh_mesh_preview
from backend.machine_constants import compute_machine_constants
from backend.magneto2d_adapter import get_magneto2d_winding_support_error
from backend.models import (
    BackEMFWaveform,
    FluxDensityMap,
    MotorConfig,
    Node,
    SolveMetadata,
    SolveOptionsConfig,
    SolveResult,
    SolveSummary,
    TorqueWaveform,
)
from backend.solver_contract import ProgressCallback, Solver
from backend.sweep_planning import (
    cogging_angle_grid,
    full_cycle_back_emf_angle_grid,
    loaded_angle_grid,
)
from backend.torque_metrics import torque_at_q_axis_nm

from .capabilities import ElmerCapabilities, discover_elmer
from .case import ElmerCaseManifest, write_elmer_case
from .errors import ElmerExecutionError, ElmerResultParseError, ElmerUnsupportedError
from .mesh import ElmerMeshManifest, validate_converted_mesh, write_gmsh22
from .process import ElmerProcessRunner, convert_with_elmergrid
from .profile import load_profile
from .results import ElmerPositionResult, parse_position_result

ELMER_ANGLE_WORKERS_ENV = "COILEM_ELMER_ANGLE_WORKERS"
ELMER_RETAIN_ARTIFACTS_ENV = "COILEM_ELMER_RETAIN_ARTIFACTS"
DEFAULT_MAX_ELMER_ANGLE_WORKERS = 4
MAX_ELMER_ANGLE_WORKERS = 16
MAX_RETAINED_ELMER_RUNS = 10
ELMER_RUN_DIR_PREFIX = "elmer_run_"

_LOGGER = logging.getLogger(__name__)


def _emit_progress(callback: ProgressCallback | None, **payload: Any) -> None:
    if callback is None:
        return
    callback(
        int(payload.get("position", 0)),
        int(payload.get("total", 0)),
        payload.get("torque_Nm"),
        str(payload.get("stage", "torque_sweep")),
        payload.get("angle_deg"),
        None,
        None,
        None,
        None,
        payload.get("solver_detail"),
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _torque_in_output_frame(torque_nm: float, *, launch_surface: bool) -> float:
    """Convert Elmer's native CCW-positive torque to the public UI frame."""

    return -float(torque_nm) if launch_surface else float(torque_nm)


def _clockwise_excitation_config(config: MotorConfig) -> MotorConfig:
    """Mirror synchronous current excitation into the public clockwise frame."""

    mirrored = config.model_copy(deep=True)
    if mirrored.solve_params is None:
        raise ElmerUnsupportedError("Elmer requires solve_params")
    gamma_deg = float(mirrored.solve_params.current_angle_deg)
    mirrored_gamma_deg = 180.0 - gamma_deg
    while mirrored_gamma_deg > 180.0:
        mirrored_gamma_deg -= 360.0
    while mirrored_gamma_deg < -180.0:
        mirrored_gamma_deg += 360.0
    mirrored.solve_params.current_angle_deg = mirrored_gamma_deg
    return mirrored


def _remaining_external_timeout(deadline: float, position_limit_s: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0.0:
        raise ElmerExecutionError("Elmer run exceeded its overall timeout")
    return min(position_limit_s, remaining)


def resolve_elmer_angle_workers(
    angle_count: int,
    *,
    logical_cpu_count: int | None = None,
) -> int:
    """Resolve bounded outer-loop parallelism for independent rotor angles.

    Each Elmer position remains a serial direct solve. The adaptive default
    uses at most half of the host's logical CPUs and is capped at four so the
    backend, serialized Gmsh preparation, and UI retain headroom. The
    environment override is operational rather than part of the hashed
    numerical profile because it does not change the solved physics.
    """

    if angle_count <= 0:
        return 1
    raw_override = os.environ.get(ELMER_ANGLE_WORKERS_ENV, "").strip()
    if raw_override:
        try:
            requested = int(raw_override)
        except ValueError as exc:
            raise ElmerExecutionError(
                f"{ELMER_ANGLE_WORKERS_ENV} must be a positive integer"
            ) from exc
        if requested < 1:
            raise ElmerExecutionError(
                f"{ELMER_ANGLE_WORKERS_ENV} must be a positive integer"
            )
        return min(angle_count, requested, MAX_ELMER_ANGLE_WORKERS)

    cpus = logical_cpu_count if logical_cpu_count is not None else (os.cpu_count() or 1)
    adaptive = max(1, int(cpus) // 2)
    return min(angle_count, adaptive, DEFAULT_MAX_ELMER_ANGLE_WORKERS)


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _prune_elmer_run_dirs(root: Path, *, keep: int) -> None:
    """Best-effort pruning for retained Elmer cases under a dedicated root."""

    try:
        runs = sorted(
            (
                path
                for path in root.iterdir()
                if path.is_dir() and path.name.startswith(ELMER_RUN_DIR_PREFIX)
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in runs[max(0, keep) :]:
        try:
            shutil.rmtree(stale)
        except OSError:
            _LOGGER.warning("Could not prune retained Elmer run directory %s", stale)


def _ripple(values: list[float], average: float) -> float:
    if not values or abs(average) <= 1.0e-12:
        return 0.0
    return (max(values) - min(values)) / abs(average) * 100.0


def _finite_difference(values: list[float], step_rad: float, *, periodic: bool) -> list[float]:
    if len(values) < 2 or step_rad <= 0.0:
        raise ElmerResultParseError("Back-EMF linkage grid has fewer than two usable samples")
    out: list[float] = []
    for index in range(len(values)):
        if periodic:
            derivative = (
                values[(index + 1) % len(values)] - values[(index - 1) % len(values)]
            ) / (2.0 * step_rad)
        elif index == 0:
            derivative = (values[1] - values[0]) / step_rad
        elif index + 1 == len(values):
            derivative = (values[-1] - values[-2]) / step_rad
        else:
            derivative = (values[index + 1] - values[index - 1]) / (2.0 * step_rad)
        out.append(derivative)
    return out


def _back_emf(values: list[float], angles_deg: list[float], omega_electrical: float) -> list[float]:
    if len(values) != len(angles_deg) or len(values) < 2:
        raise ElmerResultParseError("Back-EMF linkage and angle grids do not align")
    step_rad = math.radians(angles_deg[1] - angles_deg[0])
    periodic = len(angles_deg) >= 3 and abs((angles_deg[-1] + math.degrees(step_rad)) - 360.0) <= 1.0e-6
    return [omega_electrical * value for value in _finite_difference(values, step_rad, periodic=periodic)]


def _harmonic_peak(values: list[float], angles_deg: list[float], harmonic: int) -> float:
    if len(values) != len(angles_deg) or len(values) < 3:
        return 0.0
    real = sum(value * math.cos(math.radians(harmonic * angle)) for angle, value in zip(angles_deg, values, strict=True))
    imag = sum(value * math.sin(math.radians(harmonic * angle)) for angle, value in zip(angles_deg, values, strict=True))
    return math.hypot(real, imag) * 2.0 / len(values)


def _thd(values: list[float], angles_deg: list[float]) -> float | None:
    fundamental = _harmonic_peak(values, angles_deg, 1)
    if fundamental <= 1.0e-12:
        return None
    harmonics_sq = sum(_harmonic_peak(values, angles_deg, order) ** 2 for order in range(2, 7))
    return math.sqrt(harmonics_sq) / fundamental * 100.0


def _area_weighted_steel_rms(results: list[ElmerPositionResult]) -> tuple[float | None, float | None]:
    accumulators = {
        "stator_tooth": [0.0, 0.0],
        "stator_yoke": [0.0, 0.0],
    }
    for result in results:
        for triangle, region, b_value in zip(
            result.triangles,
            result.regions,
            result.element_b_magnitude_t,
            strict=True,
        ):
            if region not in accumulators:
                continue
            i, j, k = triangle
            x1, y1 = result.nodes_mm[i]
            x2, y2 = result.nodes_mm[j]
            x3, y3 = result.nodes_mm[k]
            area = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) * 0.5
            accumulators[region][0] += b_value * b_value * area
            accumulators[region][1] += area
    values = []
    for key in ("stator_tooth", "stator_yoke"):
        sum_sq, area = accumulators[key]
        values.append(math.sqrt(sum_sq / area) if area > 0.0 else None)
    return values[0], values[1]


class ElmerSolver(Solver):
    """External-process Elmer FEM solver with remesh-per-angle motion."""

    def __init__(
        self,
        *,
        capabilities: ElmerCapabilities | None = None,
        run_root: str | Path | None = None,
        launch_surface: bool = False,
        retain_artifacts: bool | None = None,
    ) -> None:
        self.capabilities = capabilities or discover_elmer()
        self.profile, self.profile_sha256 = load_profile()
        self.run_root = Path(run_root).resolve() if run_root is not None else None
        self._launch_surface = bool(launch_surface)
        self.retain_artifacts = (
            bool(retain_artifacts)
            if retain_artifacts is not None
            else self.run_root is not None or _env_flag_enabled(ELMER_RETAIN_ARTIFACTS_ENV)
        )
        self._runner = ElmerProcessRunner(max_log_bytes=int(self.profile["max_log_bytes"]))

    def cancel_active_solve(self) -> None:
        self._runner.cancel()

    def _validate_config(self, config: MotorConfig, solve_mesh_key: str | None) -> None:
        self.capabilities.require_available()
        if solve_mesh_key:
            raise ElmerUnsupportedError(
                "Elmer remesh-per-step does not reuse solve_mesh_key artifacts yet"
            )
        if config.solve_params is None:
            raise ElmerUnsupportedError("Elmer requires solve_params")
        if config.solve_params.excitation_mode == "ideal_six_step_120":
            raise ElmerUnsupportedError(
                "Ideal six-step excitation uses the built-in Magneto2D solver in the MVP"
            )
        if str(config.topology).upper() not in {"SPM", "IPM"}:
            raise ElmerUnsupportedError("Elmer v1 supports radial-flux SPM and IPM only")
        if int(config.rotor.pole_count) % 2:
            raise ElmerUnsupportedError("Elmer v1 requires an even rotor pole count")
        if str(config.topology).upper() == "IPM":
            ipm_topology = str(config.rotor.ipm_topology or "flat_buried")
            if ipm_topology not in {
                "flat_buried",
                "v_shape",
                "pyleecan_holem50",
            }:
                raise ElmerUnsupportedError(
                    "Elmer v1 supports flat-buried, V-shape, and "
                    "Pyleecan HoleM50 IPM only; "
                    f"got {ipm_topology!r}"
                )
            if config.rotor.flux_barrier_count or config.rotor.barrier_widths_mm:
                raise ElmerUnsupportedError(
                    "Elmer v1 does not support explicit flux-barrier fields"
                )
        winding_error = get_magneto2d_winding_support_error(config)
        if winding_error:
            raise ElmerUnsupportedError(winding_error.replace("Magneto2D", "Elmer"))
        torque_method = config.solve_params.torque_method
        explicit_torque = "torque_method" in config.solve_params.model_fields_set
        if explicit_torque and torque_method != "arkkio":
            raise ElmerUnsupportedError(
                f"Elmer v1 supports torque_method='arkkio', got {torque_method!r}"
            )
        if config.solve_params.mesh_source != "native" or config.solve_params.mesher != "gmsh":
            raise ElmerUnsupportedError(
                "Elmer v1 requires native full-machine Gmsh geometry; "
                "imported and sector-boundary meshes are not supported"
            )
        if config.solve_params.rotor_rotation_model != "remesh_per_step":
            raise ElmerUnsupportedError(
                "Elmer v1 requires rotor_rotation_model='remesh_per_step'"
            )
        if config.solve_params.slot_sidewall_refinement:
            raise ElmerUnsupportedError(
                "Elmer v1 does not support slot_sidewall_refinement"
            )
        if config.solve_params.linear_steel_mu_rel is not None:
            raise ElmerUnsupportedError("Elmer v1 does not accept a linear steel override")
        if config.solve_params.nonlinear_solver != "picard":
            raise ElmerUnsupportedError(
                "Elmer v1 uses the frozen Picard nonlinear profile and does not support "
                f"nonlinear_solver={config.solve_params.nonlinear_solver!r}"
            )
        requested_iterations = config.solve_params.max_nonlinear_iterations
        qualified_iterations = int(self.profile["nonlinear_solver"]["max_iterations"])
        if (
            requested_iterations is not None
            and int(requested_iterations) != qualified_iterations
        ):
            raise ElmerUnsupportedError(
                "Elmer v1 uses the frozen nonlinear iteration limit "
                f"{qualified_iterations}; got {requested_iterations}"
            )
        if config.solve_params.linear_solver_preconditioner != "direct":
            raise ElmerUnsupportedError(
                "Elmer v1 uses the frozen direct linear solver profile"
            )
        if config.solve_params.field_composition_source != "resultant":
            raise ElmerUnsupportedError(
                "Elmer v1 does not implement armature-only field composition"
            )
        if config.solve_params.magnet_temperature_C is not None:
            raise ElmerUnsupportedError(
                "Elmer v1 does not implement magnet-temperature derating"
            )
        if config.materials.stator_steel != "M350-50A" or config.materials.rotor_steel != "M350-50A":
            raise ElmerUnsupportedError("Elmer v1 requires M350-50A stator and rotor steel")
        solve_options = config.solve_options or SolveOptionsConfig()
        if not solve_options.torque_sweep:
            raise ElmerUnsupportedError(
                "Elmer v1 requires torque_sweep=true; a no-load-only result contract is not implemented"
            )
        if solve_options.torque_speed_envelope:
            raise ElmerUnsupportedError(
                "Elmer v1 does not implement torque_speed_envelope"
            )

    def _new_run_dir(self) -> Path:
        if self.run_root is not None:
            root = self.run_root
        else:
            configured = os.environ.get("COILEM_ELMER_RUN_ROOT")
            root = (
                Path(configured).expanduser().resolve()
                if configured
                else Path(tempfile.gettempdir()) / "openem" / "elmer_runs"
            )
        root.mkdir(parents=True, exist_ok=True)
        _prune_elmer_run_dirs(root, keep=MAX_RETAINED_ELMER_RUNS - 1)
        return Path(tempfile.mkdtemp(prefix=ELMER_RUN_DIR_PREFIX, dir=root))

    def _cleanup_successful_run(self, run_dir: Path) -> bool:
        if self.retain_artifacts:
            return False
        try:
            shutil.rmtree(run_dir)
        except OSError:
            _LOGGER.warning("Could not clean successful Elmer run directory %s", run_dir)
            return False
        return True

    def _solve_position(
        self,
        config: MotorConfig,
        *,
        angle_electrical_deg: float,
        position_dir: Path,
        stage: str,
        position: int,
        total: int,
        on_progress: ProgressCallback | None,
        deadline: float,
        mesh_executor: ThreadPoolExecutor | None = None,
    ) -> ElmerPositionResult:
        assert self.capabilities.grid_path is not None
        assert self.capabilities.solver_path is not None
        pole_pairs = max(1, int(config.rotor.pole_count) // 2)
        rotation_direction = -1.0 if self._launch_surface else 1.0
        angle_mechanical_deg = (
            rotation_direction * float(angle_electrical_deg) / pole_pairs
        )
        position_dir.mkdir(parents=True, exist_ok=False)
        _emit_progress(
            on_progress,
            stage=stage,
            position=position,
            total=total,
            angle_deg=angle_electrical_deg,
            solver_detail={"solver": "elmer", "elmer_stage": "mesh"},
        )
        _remaining_external_timeout(deadline, float(self.profile["position_timeout_seconds"]))
        if mesh_executor is None:
            preview = run_gmsh_mesh_preview(config, rotor_angle_deg=angle_mechanical_deg)
        else:
            # Gmsh owns process-global native state. A single executor keeps
            # every mesh call serialized and on one stable OS thread across
            # loaded, no-load, and cogging lanes while Elmer processes run in
            # parallel on the angle workers.
            preview = mesh_executor.submit(
                run_gmsh_mesh_preview,
                config,
                rotor_angle_deg=angle_mechanical_deg,
            ).result()
        artifact = preview["solve_mesh_artifact"]
        gmsh_path = position_dir / "motor.msh"
        mesh_manifest: ElmerMeshManifest = write_gmsh22(
            artifact,
            gmsh_path,
            expected_rotor_angle_mech_deg=angle_mechanical_deg,
            minimum_airgap_radial_layers=int(self.profile["minimum_airgap_radial_layers"]),
        )
        _emit_progress(
            on_progress,
            stage=stage,
            position=position,
            total=total,
            angle_deg=angle_electrical_deg,
            solver_detail={"solver": "elmer", "elmer_stage": "mesh_convert"},
        )
        mesh_dir = position_dir / "mesh"
        convert_with_elmergrid(
            self._runner,
            grid_path=self.capabilities.grid_path,
            gmsh_path=gmsh_path,
            mesh_dir=mesh_dir,
            timeout_s=_remaining_external_timeout(
                deadline,
                min(60.0, float(self.profile["position_timeout_seconds"])),
            ),
        )
        converted_names = validate_converted_mesh(mesh_dir, mesh_manifest)
        case_manifest: ElmerCaseManifest = write_elmer_case(
            config=config,
            solve_mesh_artifact=artifact,
            mesh_manifest=mesh_manifest,
            converted_names=converted_names,
            case_dir=position_dir,
            profile=self.profile,
        )
        detail_stage = {
            "torque_sweep": "loaded_solve",
            "noload_sweep": "noload_solve",
            "cogging_sweep": "cogging_solve",
        }[stage]
        _emit_progress(
            on_progress,
            stage=stage,
            position=position,
            total=total,
            angle_deg=angle_electrical_deg,
            solver_detail={"solver": "elmer", "elmer_stage": detail_stage},
        )
        process_result = self._runner.run(
            [self.capabilities.solver_path],
            cwd=position_dir,
            timeout_s=_remaining_external_timeout(
                deadline,
                float(self.profile["position_timeout_seconds"]),
            ),
            log_prefix="elmersolver",
        )
        vtu_candidates = sorted(position_dir.rglob("case*.vtu"))
        if not vtu_candidates:
            raise ElmerResultParseError(f"Elmer produced no VTU under {position_dir}")
        result = parse_position_result(
            config=config,
            solve_mesh_artifact=artifact,
            case_manifest=case_manifest,
            stdout=process_result.stdout,
            vtu_path=vtu_candidates[-1],
        )
        (position_dir / "position_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "openem.elmer_position/v1",
                    "angle_electrical_deg": angle_electrical_deg,
                    "angle_mechanical_deg": angle_mechanical_deg,
                    "stage": stage,
                    "torque_nm": result.torque_nm,
                    "nodal_force_torque_nm": result.nodal_force_torque_nm,
                    "solve_mesh_evidence": result.solve_mesh_evidence,
                    "profile_sha256": self.profile_sha256,
                    "capabilities": self.capabilities.health_payload(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        _emit_progress(
            on_progress,
            stage=stage,
            position=position,
            total=total,
            angle_deg=angle_electrical_deg,
            torque_Nm=result.torque_nm,
            solver_detail={
                "solver": "elmer",
                "elmer_stage": "position_complete",
                "elapsed_s": process_result.elapsed_s,
            },
        )
        return result

    def _run_grid(
        self,
        config: MotorConfig,
        *,
        angles: list[float],
        root: Path,
        stage: str,
        on_progress: ProgressCallback | None,
        deadline: float,
        worker_count: int | None = None,
        angle_executor: ThreadPoolExecutor | None = None,
        mesh_executor: ThreadPoolExecutor | None = None,
    ) -> list[ElmerPositionResult]:
        if not angles:
            return []
        workers = worker_count or resolve_elmer_angle_workers(len(angles))
        workers = max(1, min(int(workers), len(angles), MAX_ELMER_ANGLE_WORKERS))
        ordered_results: list[ElmerPositionResult | None] = [None] * len(angles)
        progress_lock = threading.Lock()
        completed_positions = 0

        _emit_progress(
            on_progress,
            stage=stage,
            position=0,
            total=len(angles),
            solver_detail={
                "solver": "elmer",
                "elmer_stage": "parallel_start",
                "angle_workers": workers,
            },
        )

        def worker_progress(
            _position: int,
            total: int,
            torque_nm: float | None,
            progress_stage: str = stage,
            angle_deg: float | None = None,
            _phase_a_v: float | None = None,
            _phase_b_v: float | None = None,
            _phase_c_v: float | None = None,
            _field_line_frame: dict[str, Any] | None = None,
            solver_detail: dict[str, Any] | None = None,
        ) -> None:
            nonlocal completed_positions
            detail = dict(solver_detail or {})
            detail["angle_workers"] = workers
            with progress_lock:
                if detail.get("elmer_stage") == "position_complete":
                    completed_positions += 1
                _emit_progress(
                    on_progress,
                    stage=progress_stage,
                    position=completed_positions,
                    total=total,
                    angle_deg=angle_deg,
                    torque_Nm=(
                        _torque_in_output_frame(
                            torque_nm,
                            launch_surface=self._launch_surface,
                        )
                        if torque_nm is not None
                        else None
                    ),
                    solver_detail=detail,
                )

        futures: dict[Future[ElmerPositionResult], int] = {}
        next_index = 0
        owns_angle_executor = angle_executor is None
        executor = angle_executor or ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="openem-elmer-angle",
        )

        def submit(index: int) -> None:
            angle = angles[index]
            future = executor.submit(
                self._solve_position,
                config,
                angle_electrical_deg=angle,
                position_dir=root / f"pos_{index:04d}",
                stage=stage,
                position=index + 1,
                total=len(angles),
                on_progress=worker_progress,
                deadline=deadline,
                mesh_executor=mesh_executor,
            )
            futures[future] = index

        try:
            while next_index < len(angles) and len(futures) < workers:
                submit(next_index)
                next_index += 1

            while futures:
                done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                for future in done:
                    index = futures.pop(future)
                    ordered_results[index] = future.result()
                    if next_index < len(angles):
                        submit(next_index)
                        next_index += 1
        except BaseException:
            self._runner.cancel()
            for future in futures:
                future.cancel()
            raise
        finally:
            if owns_angle_executor:
                executor.shutdown(wait=True, cancel_futures=True)

        if any(result is None for result in ordered_results):
            raise ElmerExecutionError("Elmer parallel sweep completed with missing angle results")
        return [result for result in ordered_results if result is not None]

    def solve(
        self,
        config: MotorConfig,
        on_progress: ProgressCallback | None = None,
        solve_mesh_key: str | None = None,
    ) -> SolveResult:
        self._runner.reset()
        self._validate_config(config, solve_mesh_key)
        started = time.monotonic()
        deadline = started + float(self.profile["run_timeout_seconds"])
        run_dir = self._new_run_dir()
        solve_options = config.solve_options or SolveOptionsConfig()
        loaded_config = (
            _clockwise_excitation_config(config)
            if self._launch_surface
            else config
        )
        loaded_angles = loaded_angle_grid(config)
        loaded_workers = resolve_elmer_angle_workers(len(loaded_angles))
        pool_workers = resolve_elmer_angle_workers(MAX_ELMER_ANGLE_WORKERS)
        angle_executor = ThreadPoolExecutor(
            max_workers=pool_workers,
            thread_name_prefix="openem-elmer-angle",
        )
        mesh_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="openem-elmer-gmsh",
        )
        try:
            loaded_results = self._run_grid(
                loaded_config,
                angles=loaded_angles,
                root=run_dir / "loaded",
                stage="torque_sweep",
                on_progress=on_progress,
                deadline=deadline,
                worker_count=loaded_workers,
                angle_executor=angle_executor,
                mesh_executor=mesh_executor,
            )
            no_load_results: list[ElmerPositionResult] = []
            no_load_angles: list[float] = []
            no_load_workers = 0
            if solve_options.back_emf or solve_options.thd_analysis:
                no_load_angles = full_cycle_back_emf_angle_grid(config, loaded_angles)
                no_load_workers = resolve_elmer_angle_workers(len(no_load_angles))
                assert config.solve_params is not None
                no_load_config = loaded_config.model_copy(
                    update={
                        "solve_params": config.solve_params.model_copy(
                            update={"current_amplitude_A": 0.0, "torque_method": "arkkio"}
                        )
                    }
                )
                no_load_results = self._run_grid(
                    no_load_config,
                    angles=no_load_angles,
                    root=run_dir / "noload",
                    stage="noload_sweep",
                    on_progress=on_progress,
                    deadline=deadline,
                    worker_count=no_load_workers,
                    angle_executor=angle_executor,
                    mesh_executor=mesh_executor,
                )

            cogging_results: list[ElmerPositionResult] = []
            cogging_angles = cogging_angle_grid(config)
            cogging_workers = 0
            if cogging_angles:
                cogging_workers = resolve_elmer_angle_workers(len(cogging_angles))
                assert config.solve_params is not None
                cogging_config = loaded_config.model_copy(
                    update={
                        "solve_params": config.solve_params.model_copy(
                            update={"current_amplitude_A": 0.0, "torque_method": "arkkio"}
                        )
                    }
                )
                cogging_results = self._run_grid(
                    cogging_config,
                    angles=cogging_angles,
                    root=run_dir / "cogging",
                    stage="cogging_sweep",
                    on_progress=on_progress,
                    deadline=deadline,
                    worker_count=cogging_workers,
                    angle_executor=angle_executor,
                    mesh_executor=mesh_executor,
                )
        except BaseException:
            self._runner.cancel()
            raise
        finally:
            angle_executor.shutdown(wait=True, cancel_futures=True)
            mesh_executor.shutdown(wait=True, cancel_futures=True)

        torques = [
            _torque_in_output_frame(
                item.torque_nm,
                launch_surface=self._launch_surface,
            )
            for item in loaded_results
        ]
        cogging_torques = [
            _torque_in_output_frame(
                item.torque_nm,
                launch_surface=self._launch_surface,
            )
            for item in cogging_results
        ]
        average_torque = _mean(torques)
        if no_load_results:
            flux_a = [item.flux_linkage_a_wb for item in no_load_results]
            flux_b = [item.flux_linkage_b_wb for item in no_load_results]
            flux_c = [item.flux_linkage_c_wb for item in no_load_results]
            assert config.solve_params is not None
            omega_mech = 2.0 * math.pi * config.solve_params.rated_speed_rpm / 60.0
            omega_electrical = omega_mech * max(1, config.rotor.pole_count // 2)
            voltage_a = _back_emf(flux_a, no_load_angles, omega_electrical)
            voltage_b = _back_emf(flux_b, no_load_angles, omega_electrical)
            voltage_c = _back_emf(flux_c, no_load_angles, omega_electrical)
            fundamental_rms = _harmonic_peak(voltage_a, no_load_angles, 1) / math.sqrt(2.0)
            harmonic_analysis = (
                analyze_back_emf_harmonics(
                    angles_elec_deg=no_load_angles,
                    phase_a_flux_linkage_Wb=flux_a,
                    phase_b_flux_linkage_Wb=flux_b,
                    phase_c_flux_linkage_Wb=flux_c,
                    electrical_angular_speed_rad_s=omega_electrical,
                    max_harmonic=harmonic_limit_for_quality(config.solve_params.solve_quality),
                )
                if solve_options.thd_analysis
                else None
            )
            back_emf_thd = (
                harmonic_analysis.phase_a_thd_h12_pct
                if harmonic_analysis is not None
                else None
            )
            if harmonic_analysis is not None:
                fundamental_rms = harmonic_analysis.harmonics[0].phase_a_rms_V
        else:
            no_load_angles = loaded_angles
            voltage_a = [0.0] * len(no_load_angles)
            voltage_b = [0.0] * len(no_load_angles)
            voltage_c = [0.0] * len(no_load_angles)
            fundamental_rms = 0.0
            back_emf_thd = None
            harmonic_analysis = None

        first = loaded_results[0]
        field_plot = build_field_line_plot_from_mesh(
            config_summary={
                "topology": config.topology,
                "slots": config.stator.slot_count,
                "poles": config.rotor.pole_count,
                "stator_od_mm": config.stator.OD_mm,
                "rotor_od_mm": config.rotor.OD_mm,
                "magnet_thickness_mm": config.rotor.magnet_thickness_mm,
                "stack_length_mm": config.stator.stack_length_mm,
            },
            mesh_info={
                "num_nodes": len(first.nodes_mm),
                "num_triangles": len(first.triangles),
                "pole_pitch_deg": 360.0 / config.rotor.pole_count,
                "n_pole_pitches": config.rotor.pole_count,
                "total_span_deg": 360.0,
            },
            nodes_mm=first.nodes_mm,
            triangles=first.triangles,
            regions=first.regions,
            az_nodal=first.az_nodal,
            n_pole_pitches=config.rotor.pole_count,
            total_span_deg=360.0,
        )
        rms_teeth, rms_yoke = _area_weighted_steel_rms(loaded_results)
        peak_teeth = max(result.peak_b_tooth_t for result in loaded_results)
        peak_yoke = max(result.peak_b_yoke_t for result in loaded_results)
        assert config.solve_params is not None
        current_peak = float(config.solve_params.current_amplitude_A)
        if config.solve_params.current_amplitude_convention == "rms":
            current_peak *= math.sqrt(2.0)
        kt, ke, lambda_pm = compute_machine_constants(
            avg_torque_Nm=average_torque,
            current_amplitude_A=current_peak,
            back_emf_fundamental_V_rms_LN=fundamental_rms,
            rated_speed_rpm=config.solve_params.rated_speed_rpm,
            pole_count=config.rotor.pole_count,
        )
        elapsed = time.monotonic() - started
        solver_version = self.capabilities.solver_version or "unknown"
        result = SolveResult(
            summary=SolveSummary(
                avg_torque_Nm=average_torque,
                torque_q_axis_Nm=torque_at_q_axis_nm(loaded_angles, torques),
                torque_ripple_pct=_ripple(torques, average_torque),
                cogging_torque_Nm=max(
                    (abs(value) for value in cogging_torques), default=0.0
                )
                if cogging_results
                else None,
                back_emf_fundamental_V=fundamental_rms,
                back_emf_thd_pct=back_emf_thd,
                back_emf_thd_h6_pct=(
                    harmonic_analysis.phase_a_thd_h6_pct if harmonic_analysis else None
                ),
                back_emf_thd_h12_pct=(
                    harmonic_analysis.phase_a_thd_h12_pct if harmonic_analysis else None
                ),
                back_emf_thd_h24_pct=(
                    harmonic_analysis.phase_a_thd_h24_pct if harmonic_analysis else None
                ),
                back_emf_line_thd_h12_pct=(
                    harmonic_analysis.line_ab_thd_h12_pct if harmonic_analysis else None
                ),
                back_emf_line_thd_h24_pct=(
                    harmonic_analysis.line_ab_thd_h24_pct if harmonic_analysis else None
                ),
                Kt_Nm_per_A=kt,
                Ke_Vs_per_rad_mech=ke,
                lambda_pm_Wb=lambda_pm,
                peak_flux_density_teeth_T=peak_teeth,
                peak_flux_density_yoke_T=peak_yoke,
                rms_flux_density_teeth_T=rms_teeth,
                rms_flux_density_yoke_T=rms_yoke,
                slot_excitation_contributions=None,
                solve_time_s=elapsed,
            ),
            torque_waveform=TorqueWaveform(
                electrical_angle_deg=loaded_angles,
                torque_Nm=torques,
            ),
            cogging_torque_waveform=TorqueWaveform(
                electrical_angle_deg=cogging_angles,
                torque_Nm=cogging_torques,
            )
            if len(cogging_results) >= 2
            else None,
            back_emf_waveform=BackEMFWaveform(
                electrical_angle_deg=no_load_angles,
                phase_a_V=voltage_a,
                phase_b_V=voltage_b,
                phase_c_V=voltage_c,
            ),
            back_emf_harmonic_analysis=harmonic_analysis,
            flux_density_map=FluxDensityMap(
                nodes=[Node(x=point[0], y=point[1]) for point in first.nodes_mm],
                B_magnitude=first.nodal_b_magnitude_t,
            )
            if solve_options.flux_density
            else None,
            field_line_plot=field_plot if solve_options.flux_density else None,
            solve_metadata=SolveMetadata(
                solver_name=f"elmerfem-{solver_version}",
                mesh_element_count=len(first.triangles),
                rotor_positions=len(loaded_angles),
                timestamp=datetime.now(timezone.utc),
                current_amplitude_A=current_peak,
                rated_speed_rpm=config.solve_params.rated_speed_rpm,
                motor_input_dc_bus_V=config.solve_params.motor_input_dc_bus_V,
                solve_cache_dir=str(run_dir),
                pipeline_stage="field_solve",
                solve_time_s=elapsed,
                mesher="gmsh",
                mesh_density=config.solve_params.mesh_density,
                mesh_source="native",
                mesh_source_detail="geometry_ir_elmergrid",
                geometry_ir_version="geometry_ir/v0",
                rotor_rotation_model="remesh_per_step",
                torque_method="arkkio",
                nonlinear_tolerance=float(self.profile["nonlinear_solver"]["convergence_tolerance"]),
                topology=config.topology,
                physics_contract_version=str(self.profile["physics_contract_version"]),
                region_source="geometry_ir",
                current_source="geometry_ir_winding_table",
                magnetization_source="geometry_ir",
                material_source="material_contract",
            ),
        )
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "openem.elmer_run/v1",
                    "profile": self.profile,
                    "profile_sha256": self.profile_sha256,
                    "capabilities": self.capabilities.health_payload(),
                    "parallelism": {
                        "strategy": "bounded_external_angle_workers/v1",
                        "gmsh_api": "dedicated_thread_serialized",
                        "loaded_angle_workers": loaded_workers,
                        "noload_angle_workers": no_load_workers,
                        "cogging_angle_workers": cogging_workers,
                        "environment_override": os.environ.get(ELMER_ANGLE_WORKERS_ENV),
                    },
                    "rotation_convention": (
                        "clockwise_positive_ui"
                        if self._launch_surface
                        else "counterclockwise_positive_solver"
                    ),
                    "loaded_angles_electrical_deg": loaded_angles,
                    "noload_angles_electrical_deg": no_load_angles if no_load_results else [],
                    "cogging_angles_electrical_deg": cogging_angles,
                    "nodal_force_torque_witness_nm": [
                        item.nodal_force_torque_nm for item in loaded_results
                    ],
                    "mesh_evidence": {
                        "loaded": [item.solve_mesh_evidence for item in loaded_results],
                        "noload": [item.solve_mesh_evidence for item in no_load_results],
                        "cogging": [item.solve_mesh_evidence for item in cogging_results],
                    },
                    "extractors": {
                        "torque": "elmer_stdout_air_gap_torque/v1",
                        "torque_witness": "elmer_calcfields_component_torque/v1",
                        "field": "elmer_vtu_az_gradient/v1",
                        "flux_linkage": "openem_area_averaged_az/v1",
                        "back_emf": "openem_periodic_central_difference/v1",
                        "back_emf_harmonics": "periodic_flux_linkage_dft/v1",
                    },
                    "elapsed_s": elapsed,
                    "result": result.model_dump(mode="json"),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        _emit_progress(
            on_progress,
            stage="postprocess",
            position=len(loaded_angles),
            total=len(loaded_angles),
            solver_detail={"solver": "elmer", "elmer_stage": "complete"},
        )
        if self._cleanup_successful_run(run_dir):
            result.solve_metadata.solve_cache_dir = None
        return result
