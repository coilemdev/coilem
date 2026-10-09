"""Motor solver orchestration, cached report mapping and cancellation."""

import copy
import hashlib
import inspect
import json
import math
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Literal, Protocol, cast, overload

from backend import field_artifacts
from backend.field_lines import build_field_line_plot
from backend.geometry_drawer import (
    compute_3phase_current_density_for_rotor_elec,
)
from backend.gmsh_mesh_rotation import (
    derive_congruent_solve_report,
    gmsh_mesh_reuse_enabled,
    gmsh_solve_reuse_enabled,
    rebake_solve_mesh_artifact_currents,
    rotate_solve_mesh_artifact,
    slot_congruence_groups,
    slot_current_pattern_matches,
)
from backend.gmsh_solver import run_gmsh_mesh_preview
from backend.machine_constants import compute_machine_constants
from backend.magneto2d_adapter import (
    Magneto2DUnsupportedError,
    build_magneto2d_payload,
    cancel_active_magneto2d_processes,
    estimate_magneto2d_cogging_positions,
    estimate_magneto2d_nonlinear_tolerance,
    estimate_magneto2d_sweep_angle_grid,
    estimate_magneto2d_sweep_positions,
    get_cached_solve_mesh_artifact,
    require_magneto2d_supported,
    run_magneto2d_batch_reports,
    run_magneto2d_report,
)
from backend.mesh_evidence import build_solve_mesh_evidence
from backend.models import (
    BackEMFWaveform,
    MotorConfig,
    PhaseCurrentWaveform,
    SolveMetadata,
    SolveOptionsConfig,
    SolveResult,
    SolveSummary,
    TorqueWaveform,
)
from backend.solver_contract import SolveCancelledError, Solver
from backend.solver_environment import solver_setting
from backend.steel_flux_metrics import steel_flux_density_rms_from_frames
from backend.sweep_planning import (
    cogging_angle_grid as shared_cogging_angle_grid,
)
from backend.sweep_planning import (
    full_cycle_back_emf_angle_grid as shared_full_cycle_back_emf_angle_grid,
)
from backend.sweep_planning import is_uniform_full_cycle_grid
from backend.topology_provenance import build_mesh_signature_payload
from backend.torque_metrics import torque_at_q_axis_nm as _torque_at_q_axis_nm

# The solver interface is core-owned; private implementations share it.

REPO_ROOT = Path(__file__).resolve().parents[1]








def _per_angle_grid_key(angle_deg: float) -> int:
    return int(round(float(angle_deg) * 1_000_000.0))


def _full_cycle_back_emf_angle_grid(
    config: MotorConfig,
    loaded_angles_elec_deg: list[float],
) -> list[float]:
    """Full-cycle no-load angle grid for per-angle mesh Back-EMF signoff."""
    return shared_full_cycle_back_emf_angle_grid(config, loaded_angles_elec_deg)


def _cogging_angle_grid(config: MotorConfig) -> list[float]:
    """One electrical cogging period for per-angle no-load torque extraction."""
    raw_step = solver_setting("MAGNETO2D_COGGING_STEP_DEG")
    try:
        step_deg = float(raw_step) if raw_step is not None else 1.0
    except ValueError:
        step_deg = 1.0
    return shared_cogging_angle_grid(config, step_deg=step_deg)


def _env_bool(name: str) -> bool | None:
    value = solver_setting(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_positive_int(name: str) -> int | None:
    value = solver_setting(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _magneto2d_python_process_pool_enabled() -> bool:
    explicit = _env_bool("COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL")
    if explicit is not None:
        return explicit
    return platform.system().lower() != "windows"




def _magneto2d_persist_raw_artifacts() -> bool:
    """Keep raw per-angle Magneto2D reports/meshes only for local/debug runs."""

    explicit = _env_bool("COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS")
    if explicit is not None:
        return explicit
    explicit = _env_bool("COILEM_MAGNETO2D_PERSIST_ARTIFACTS")
    if explicit is not None:
        return explicit
    return True


def _magneto2d_persist_summary_artifacts() -> bool:
    explicit = _env_bool("COILEM_MAGNETO2D_PERSIST_SUMMARY_ARTIFACTS")
    if explicit is not None:
        return explicit
    explicit = _env_bool("COILEM_MAGNETO2D_PERSIST_ARTIFACTS")
    if explicit is not None:
        return explicit
    if _env_bool("COILEM_MAGNETO2D_COMPACT_QA_REPORT"):
        return True
    return True


def _magneto2d_prepare_cache_dir() -> bool:
    return _magneto2d_persist_raw_artifacts() or _magneto2d_persist_summary_artifacts()


def _magneto2d_raw_cache_dir(solve_cache_dir: Path | None) -> Path | None:
    if solve_cache_dir is None or not _magneto2d_persist_raw_artifacts():
        return None
    return solve_cache_dir


def _magneto2d_summary_cache_dir(solve_cache_dir: Path | None) -> Path | None:
    if solve_cache_dir is None or not _magneto2d_persist_summary_artifacts():
        return None
    return solve_cache_dir


def _emit_solver_timing(
    on_progress: Any,
    key: str,
    label: str,
    elapsed_ms: float,
    *,
    position: int = 0,
    total: int = 0,
    angle_elec_deg: float | None = None,
) -> None:
    if on_progress is None or not math.isfinite(elapsed_ms) or elapsed_ms <= 0:
        return
    try:
        signature = inspect.signature(on_progress)
    except (TypeError, ValueError):
        signature = None
    if signature is not None:
        positional_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        accepts_varargs = any(
            parameter.kind == inspect.Parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        )
        if not accepts_varargs and len(positional_params) < 10:
            return
    on_progress(
        position,
        total,
        None,
        "solver_timing",
        angle_elec_deg,
        None,
        None,
        None,
        None,
        {
            "timing_key": key,
            "timing_label": label,
            "timing_elapsed_ms": round(float(elapsed_ms), 3),
        },
    )


# Helpers live in a sibling module so this file
# can stay focused on the three Solver classes + dispatch. Star-import
# preserves the bare-name references used inside class bodies.
from backend.solver._helpers import *  # noqa: F401, F403, E402
from backend.solver._helpers import (  # noqa: E402, F401  (re-exports for tests + class bodies)
    _aggregate_per_angle_mesh_sweep,
    _aligned_number_list,
    _attach_field_frame_artifacts,
    _back_emf_from_flux_linkage,
    _close_enough,
    _config_with_phase_current,
    _energy_series,
    _estimate_live_back_emf_at_angle,
    _estimate_nonuniform_derivative,
    _field_line_frame_from_report,
    _field_line_frame_json,
    _field_line_frames_from_cache,
    _field_line_frames_from_reports,
    _finite_difference_waveform,
    _finite_number,
    _finite_number_list,
    _fundamental_peak,
    _optional_result_series,
    _requested_phase_current_peak_a,
    _require_cached_torque_method_available,
    _result_float,
    _select_magneto2d_cogging_series,
    _select_magneto2d_torque_series,
    _slim_captured_field_frame,
    _slim_progress_field_frame,
    _slot_excitation_frame_from_report,
    _slot_excitation_frames_from_cache,
    _slot_excitation_frames_from_reports,
    _torque_ripple_pct,
    _validate_magneto2d_postprocess_cache_matches_config,
    _validated_field_line_frames,
    _validated_slot_excitation_frames,
    _waveform_mean,
)

# --- Imported-mesh per-angle sweep: producer protocol + shared helper ------
#
# FEMM and Gmsh per-angle remesh sweeps used to be two ~170-line near-duplicate
# functions on Magneto2DSolver. The only differences were which mesh preview
# call to invoke, how the artifact was extracted, the progress-label string,
# the cogging/THD rejection message, and the `mesh_label` passed to the
# aggregator. Everything else (no_load grid handling, progress callback shape,
# artifact prefixes, cache-file layout) was identical.
#
# We collapse them behind a small `_MeshProducer` protocol and one shared
# `_solve_with_per_angle_producer_meshes` helper. A welcome side effect is
# that the defense-in-depth "did Rust actually consume the imported mesh?"
# guard — previously FEMM-only — now applies to every producer by
# construction.


class _MeshProducer(Protocol):
    """Per-angle imported-mesh producer.

    Implementations return a `solve_mesh_artifact` dict ready to hand to the
    Rust binary, plus the wall-clock cost of generating it. `source` is the
    label that flows into `mesh_label` for the aggregator and is also the
    substring that the consumed-by-Rust guard expects to see in the report's
    `mesh_info.mesh_density` field — keeping these the same string is what
    lets the guard work across producers.
    """

    source: str
    display_name: str

    def build(
        self,
        config: MotorConfig,
        rotor_angle_mech_deg: float,
    ) -> tuple[dict[str, Any], int]:
        ...




class _GmshMeshProducer:
    source = "gmsh"
    display_name = "Gmsh"

    @staticmethod
    def build(
        config: MotorConfig,
        rotor_angle_mech_deg: float,
    ) -> tuple[dict[str, Any], int]:
        mesh_preview = run_gmsh_mesh_preview(config, rotor_angle_deg=rotor_angle_mech_deg)
        artifact = mesh_preview.get("solve_mesh_artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Gmsh mesh preview did not include a solve mesh artifact")
        generation_time_ms = int(mesh_preview.get("generation_time_ms", 0) or 0)
        return artifact, generation_time_ms


def _clockwise_excitation_config(config: MotorConfig) -> MotorConfig:
    """Mirror the q-axis excitation into Magneto2D's native CCW frame.

    A launch-surface clockwise position ``theta_ui`` is solved at the native
    position ``-theta_ui``. Mirroring only that rotor position is incomplete:
    the native CCW motoring source angle ``theta - 90 + gamma`` would still
    produce CCW torque. The full coordinate reflection is

        -(theta_ui - 90 + gamma) = theta_native + 90 - gamma

    Existing mesh producers resolve source angle as ``theta - 90 + gamma``,
    so the equivalent internal gamma is ``180 - gamma`` modulo 360 degrees.
    Keep this transform isolated to the current-bearing mesh artifact; the
    user config and reported gamma remain unchanged.
    """

    mirrored = config.model_copy(deep=True)
    if mirrored.solve_params is None:
        raise ValueError("magneto2d solve requires solve_params")
    if mirrored.solve_params.excitation_mode == "ideal_six_step_120":
        # Six-step source synthesis is rotor-position based; gamma is not an
        # input. Mark the public frame explicitly and leave the ignored legacy
        # current angle untouched for stable persistence/cache identity.
        mirrored.solve_params.excitation_rotation_convention = "clockwise_positive_ui"
        return mirrored
    gamma_deg = float(mirrored.solve_params.current_angle_deg)
    mirrored_gamma_deg = 180.0 - gamma_deg
    while mirrored_gamma_deg > 180.0:
        mirrored_gamma_deg -= 360.0
    while mirrored_gamma_deg < -180.0:
        mirrored_gamma_deg += 360.0
    mirrored.solve_params.current_angle_deg = mirrored_gamma_deg
    return mirrored


_NATIVE_DIRECTION_TORQUE_METRICS = {
    "contour",
    "arkkio",
    "coenergy_fd",
    "energy_fd",
    "mst",
    "selected",
    "weighted_stress",
    "weighted_stress_centered",
}

_SolveMetadataTorqueMethod = Literal[
    "arkkio",
    "contour",
    "mst",
    "energy_fd",
    "coenergy_fd",
    "weighted_stress",
    "weighted_stress_centered",
]


def _solve_metadata_torque_method(metric: str) -> _SolveMetadataTorqueMethod | None:
    """Narrow a selected torque metric to the persisted metadata contract."""

    if metric == "missing":
        return None
    allowed = {
        "arkkio",
        "contour",
        "mst",
        "energy_fd",
        "coenergy_fd",
        "weighted_stress",
        "weighted_stress_centered",
    }
    if metric not in allowed:
        raise ValueError(f"Unsupported selected torque metric: {metric!r}")
    return cast(_SolveMetadataTorqueMethod, metric)


@overload
def _torque_in_ui_direction(
    value: None,
    *,
    clockwise_positive: bool,
    metric: str = "contour",
) -> None: ...


@overload
def _torque_in_ui_direction(
    value: float,
    *,
    clockwise_positive: bool,
    metric: str = "contour",
) -> float: ...


def _torque_in_ui_direction(
    value: float | None,
    *,
    clockwise_positive: bool,
    metric: str = "contour",
) -> float | None:
    """Map native CCW-positive stress torque to the launch UI convention."""

    if (
        value is not None
        and clockwise_positive
        and metric in _NATIVE_DIRECTION_TORQUE_METRICS
    ):
        return -float(value)
    return value


def _build_gmsh_mesh_in_subprocess(
    config_payload: dict[str, Any],
    rotor_angle_mech_deg: float,
) -> tuple[dict[str, Any], int, float]:
    """Build one Gmsh mesh in a separate Python process."""

    config = MotorConfig.model_validate(config_payload)
    started = time.perf_counter()
    artifact, generation_time_ms = _GmshMeshProducer.build(config, rotor_angle_mech_deg)
    return artifact, generation_time_ms, (time.perf_counter() - started) * 1000.0


def _rotate_gmsh_artifact_for_config(
    artifact: dict[str, Any],
    config: MotorConfig,
    target_rotor_angle_mech_deg: float,
) -> dict[str, Any]:
    """Derive a congruent Gmsh solve-mesh artifact at a new rotor angle.

    The electrical-angle mapping must match the producer exactly
    (see gmsh_solver._current_density_by_ir_region) so a rotated artifact's
    slot current densities are bit-comparable to a freshly meshed one.
    """
    return rotate_solve_mesh_artifact(
        artifact,
        slot_count=config.stator.slot_count,
        target_rotor_angle_mech_deg=target_rotor_angle_mech_deg,
        phase_density_a_per_mm2=lambda elec_deg: compute_3phase_current_density_for_rotor_elec(
            config, elec_deg
        ),
        current_angle_elec_deg_for_mech=lambda rotor_angle_mech_deg: (
            float(rotor_angle_mech_deg) * max(1, int(config.rotor.pole_count) // 2)
        ),
    )


def _rebake_gmsh_artifact_for_config(
    artifact: dict[str, Any],
    config: MotorConfig,
) -> dict[str, Any]:
    """Re-bake a cached Gmsh artifact's slot currents for this config.

    Same-angle companion to _rotate_gmsh_artifact_for_config: the electrical
    angle mapping and phase-density computation must match the producer
    exactly (gmsh_solver._current_density_by_ir_region) so a cache-reused
    artifact's currents are bit-comparable to a freshly meshed one.
    """
    return rebake_solve_mesh_artifact_currents(
        artifact,
        phase_density_a_per_mm2=lambda elec_deg: compute_3phase_current_density_for_rotor_elec(
            config, elec_deg
        ),
        current_angle_elec_deg_for_mech=lambda rotor_angle_mech_deg: (
            float(rotor_angle_mech_deg) * max(1, int(config.rotor.pole_count) // 2)
        ),
    )


# ── Per-angle Gmsh mesh cache (reuse across operating points) ────────
#
# A per-angle solve-mesh artifact depends on geometry + mesh policy + debug
# flags + materials + rotor angle — NOT on current amplitude or advance angle
# (gamma), which are baked as slot current densities and can be rewritten by
# _rebake_gmsh_artifact_for_config. Caching the artifacts lets an MTPA gamma
# sweep (or any repeat solve of unchanged geometry) mesh each rotor angle
# once: gamma point N>1 skips gmsh entirely and only re-bakes currents.
#
# The cache key extends build_mesh_signature_payload (which is deliberately
# current-agnostic, see backend/topology_provenance.py) with config.materials,
# because the artifact's physics contract embeds material keys.
#
# Reuse is ALL-OR-NOTHING per sweep: either every angle in the sweep grid is
# cached (skip the producer entirely) or the sweep builds normally and
# populates the cache. Partial reuse would have to interleave with the
# slot-pitch congruence grouping; all-or-nothing keeps the two mechanisms
# composable and covers the MTPA case exactly.

_PER_ANGLE_GMSH_MESH_CACHE: OrderedDict[tuple[str, int], dict[str, Any]] = OrderedDict()
_PER_ANGLE_GMSH_MESH_CACHE_LOCK = threading.Lock()


def _angle_mesh_cache_enabled() -> bool:
    return solver_setting("COILEM_MAGNETO2D_ANGLE_MESH_CACHE", "1") != "0"


def _angle_mesh_cache_max_entries() -> int:
    raw = solver_setting("COILEM_MAGNETO2D_ANGLE_MESH_CACHE_ENTRIES", "96")
    try:
        return max(0, int(raw))
    except ValueError:
        return 96


def _angle_mesh_cache_scope_key(
    config: MotorConfig,
    *,
    clockwise_positive: bool = False,
) -> str:
    """Hash of everything a cached per-angle mesh depends on except the angle."""
    materials = config.materials
    payload = {
        "signature": build_mesh_signature_payload(config),
        "materials": materials.model_dump(mode="json") if materials is not None else None,
        # Clockwise-positive launch sweeps solve the mirrored rotor positions
        # inside Magneto2D. Keep those artifacts isolated from the native
        # counterclockwise-positive validation cache.
        "rotation_convention": (
            "clockwise_positive_ui"
            if clockwise_positive
            else "counterclockwise_positive_solver"
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _angle_mesh_cache_store(scope: str, angle_key: int, artifact: dict[str, Any]) -> None:
    max_entries = _angle_mesh_cache_max_entries()
    if max_entries <= 0:
        return
    # Deep-copied BEFORE the artifact is handed to solve threads so the
    # cached entry can never see downstream mutation.
    copied = copy.deepcopy(artifact)
    with _PER_ANGLE_GMSH_MESH_CACHE_LOCK:
        _PER_ANGLE_GMSH_MESH_CACHE[(scope, angle_key)] = copied
        _PER_ANGLE_GMSH_MESH_CACHE.move_to_end((scope, angle_key))
        while len(_PER_ANGLE_GMSH_MESH_CACHE) > max_entries:
            _PER_ANGLE_GMSH_MESH_CACHE.popitem(last=False)


def _angle_mesh_cache_take_all(
    scope: str,
    angle_keys: list[int],
) -> dict[int, dict[str, Any]] | None:
    """Return cached base artifacts for EVERY requested angle, or None."""
    with _PER_ANGLE_GMSH_MESH_CACHE_LOCK:
        entries: dict[int, dict[str, Any]] = {}
        for angle_key in angle_keys:
            entry = _PER_ANGLE_GMSH_MESH_CACHE.get((scope, angle_key))
            if entry is None:
                return None
            entries[angle_key] = entry
        for angle_key in angle_keys:
            _PER_ANGLE_GMSH_MESH_CACHE.move_to_end((scope, angle_key))
    return entries


def clear_per_angle_gmsh_mesh_cache() -> None:
    """Test hook: drop all cached per-angle Gmsh artifacts."""
    with _PER_ANGLE_GMSH_MESH_CACHE_LOCK:
        _PER_ANGLE_GMSH_MESH_CACHE.clear()


def _assert_imported_mesh_consumed_by_rust(
    producer: _MeshProducer,
    loaded_report: dict[str, Any],
    *,
    idx: int,
) -> None:
    """Defense-in-depth check that the Rust binary actually consumed the
    imported mesh artifact we sent. If the `--mesh-input` handshake regresses
    or the artifact is malformed, the binary silently falls back to its
    internal mesher and the report's mesh_density reverts to an internal
    label. Without this guard a 3-way config #2 run is silently
    identical to config #3 with mislabeled provenance. Checked only on the
    first sweep position to avoid log noise across the per-angle loop.

    Previously this only protected the FEMM lane; pulling it into the shared
    helper means every producer is covered automatically.
    """
    density = str((loaded_report.get("mesh_info") or {}).get("mesh_density") or "").lower()
    if producer.source not in density:
        raise ValueError(
            f"Magneto2D did not consume the {producer.display_name}-imported "
            f"mesh artifact at sweep position {idx}: expected mesh_density "
            f"containing {producer.source!r}, got {density!r}. The "
            f"--mesh-input handshake with the magneto2d Rust binary may have "
            f"regressed (rebuild with `cd solvers/magneto2d && cargo build "
            f"--release`) or the imported mesh artifact was malformed. This "
            f"guard prevents the 3-way config #2 lane from silently "
            f"producing config #3 (internal mesher) output with mislabeled "
            f"provenance."
        )


def _zero_current_solve_mesh_artifact(solve_mesh_artifact: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of an imported mesh artifact with slot current metadata zeroed."""

    artifact = copy.deepcopy(solve_mesh_artifact)
    current_density = artifact.get("element_current_density_a_per_m2")
    if isinstance(current_density, list):
        artifact["element_current_density_a_per_m2"] = [
            0.0 if value is not None else None
            for value in current_density
        ]

    contract = artifact.get("physics_contract")
    regions = contract.get("regions") if isinstance(contract, dict) else None
    if isinstance(regions, list):
        for region in regions:
            if not isinstance(region, dict) or region.get("kind") != "SlotWinding":
                continue
            if "current_density_a_per_m2" in region:
                region["current_density_a_per_m2"] = 0.0
            winding = region.get("winding")
            if isinstance(winding, dict) and "current_density_a_per_m2" in winding:
                winding["current_density_a_per_m2"] = 0.0

    return artifact


def _config_with_magneto2d_workers(config: MotorConfig, workers: int) -> MotorConfig:
    cloned = config.model_copy(deep=True)
    if cloned.solve_params is not None:
        cloned.solve_params.magneto2d_workers = max(1, int(workers))
    return cloned


def _config_with_gmsh_remesh_per_step(config: MotorConfig) -> MotorConfig:
    solve_params = config.solve_params
    if solve_params is None:
        return config
    topology = str(getattr(config, "topology", "") or "").upper()
    mesh_source = getattr(solve_params, "mesh_source", "native")
    mesher = getattr(solve_params, "mesher", "gmsh")
    rotor_rotation_model = getattr(solve_params, "rotor_rotation_model", "fixed_mesh")
    if (
        topology == "SPM"
        or mesh_source != "native"
        or mesher != "gmsh"
        or rotor_rotation_model == "remesh_per_step"
    ):
        return config

    cloned = config.model_copy(deep=True)
    if cloned.solve_params is not None:
        cloned.solve_params.rotor_rotation_model = "remesh_per_step"
    return cloned


def _per_angle_parallel_workers(producer: _MeshProducer, total_jobs: int) -> int:
    requested = _env_positive_int("COILEM_MAGNETO2D_PER_ANGLE_WORKERS")
    if requested is None or requested <= 1 or total_jobs <= 1:
        return 1
    # Gmsh remesh artifacts are safe to solve in parallel once generated.
    # FEMM/pyFEMM automation is process-global and stays serial here.
    if producer.source != "gmsh":
        return 1
    return min(requested, total_jobs)


def _per_angle_subprocess_workers(parallel_workers: int) -> int:
    requested = _env_positive_int("COILEM_MAGNETO2D_PER_ANGLE_SOLVER_WORKERS")
    if requested is not None:
        return requested
    # The outer Python pool supplies angle-level parallelism. Keep each Rust
    # single-angle subprocess to one worker by default to avoid 8 x 8 thread
    # oversubscription on D8-class instances.
    return 1 if parallel_workers > 1 else (_env_positive_int("COILEM_MAGNETO2D_WORKERS") or 1)


def _imported_mesh_batch_enabled(producer: _MeshProducer, total_jobs: int) -> bool:
    if total_jobs <= 1 or producer.source != "gmsh":
        return False
    # Gmsh imported meshes are process-safe, so batch by default and keep the
    # env var as an escape hatch for single-angle debugging.
    explicit = _env_bool("COILEM_MAGNETO2D_BATCH_IMPORTED_MESH")
    if explicit is not None:
        return explicit
    return True


def _gmsh_imported_mesh_pipeline_enabled(producer: _MeshProducer, total_jobs: int) -> bool:
    if total_jobs <= 1 or producer.source != "gmsh":
        return False
    explicit = _env_bool("COILEM_MAGNETO2D_GMSH_PIPELINE")
    if explicit is not None:
        return explicit
    if _env_bool("COILEM_MAGNETO2D_BATCH_IMPORTED_MESH") is True:
        return False
    return True


def _gmsh_pipeline_worker_count(
    env_name: str,
    total_jobs: int,
    *,
    default: int = 8,
    uses_process_pool: bool = False,
) -> int:
    if uses_process_pool and not _magneto2d_python_process_pool_enabled():
        return 1
    requested = _env_positive_int(env_name)
    host_cpus = os.cpu_count() or default
    workers = requested if requested is not None else min(default, host_cpus)
    return max(1, min(int(workers), max(1, int(total_jobs))))


def _live_field_preview_frame_limit() -> int:
    return _env_positive_int("COILEM_MAGNETO2D_LIVE_FIELD_PREVIEW_FRAMES") or 6


def _should_stream_live_field_frame(index: int, total_positions: int) -> bool:
    limit = max(1, _live_field_preview_frame_limit())
    if total_positions <= limit:
        return True
    if index <= 0 or index >= total_positions - 1:
        return True
    denominator = max(1, limit - 1)
    stride = max(1, (max(1, total_positions - 1) + denominator - 1) // denominator)
    return index % stride == 0


def _live_field_frame_solver_detail() -> dict[str, Any]:
    return {"stream_field_line_frame": True}


def _field_preview_worker_count(total_frames: int, solve_workers: int) -> int:
    if not _magneto2d_python_process_pool_enabled():
        return 1
    requested = _env_positive_int("COILEM_MAGNETO2D_FIELD_PREVIEW_WORKERS")
    default = max(1, int(solve_workers))
    workers = requested if requested is not None else default
    return max(1, min(int(workers), max(1, int(total_frames))))


def _slim_result_field_frame(frame_payload: dict[str, Any]) -> dict[str, Any]:
    result_frame = _slim_captured_field_frame(frame_payload)
    noload_plot = frame_payload.get("noload_plot")
    if isinstance(noload_plot, dict):
        result_frame["noload_plot"] = _slim_captured_field_frame(noload_plot)
    return result_frame


def _build_field_line_frame_in_subprocess(
    idx: int,
    loaded_report: dict[str, Any],
    angle_elec_deg: float,
    noload_report: dict[str, Any] | None,
    solve_cache_dir_text: str | None,
    include_live_frame: bool,
) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
    frame = _field_line_frame_from_report(loaded_report, angle_elec_deg, noload_report)
    if frame is None:
        return idx, None, None

    attached = _attach_field_frame_artifacts(
        [frame],
        solve_cache_dir_text,
        start_idx=idx,
    )
    if attached:
        frame_payload = attached[0].model_dump(mode="json")
    else:
        frame_payload = _field_line_frame_json(frame)
    live_frame = _slim_progress_field_frame(frame_payload) if include_live_frame else None
    return idx, _slim_result_field_frame(frame_payload), live_frame


def _solve_with_per_angle_producer_meshes(
    config: MotorConfig,
    producer: _MeshProducer,
    *,
    solve_cache_dir: Path | None,
    on_progress=None,
    clockwise_positive: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Shared per-angle remesh sweep for imported-mesh producers (FEMM/Gmsh).

    Preserves the report JSON shape, progress-callback positional args, cache
    file layout, and artifact-prefix patterns of the previous per-producer
    helpers — see the original implementations for the rationale behind each
    of those.
    """
    solve_params = config.solve_params
    if solve_params is None:
        raise ValueError("magneto2d solve requires solve_params")
    excitation_config = (
        _clockwise_excitation_config(config)
        if clockwise_positive
        else config
    )
    opts = config.solve_options or SolveOptionsConfig()
    angles_elec_deg = estimate_magneto2d_sweep_angle_grid(config)
    pole_pairs = max(1, config.rotor.pole_count // 2)

    def solver_rotor_angle_mech_deg(ui_angle_elec_deg: float) -> float:
        """Map the public sweep convention onto Magneto2D's native frame.

        coilEM presents increasing electrical and mechanical angles as
        clockwise. Magneto2D and the geometry kernel remain conventional
        counterclockwise-positive, so launch-surface jobs cross the boundary
        with the opposite sign. The signed mechanical angle also flows into
        Gmsh's winding-current bake, which keeps the synchronous stator phase
        aligned with the rotor instead of visually counter-rotating the field.
        """

        direction = -1.0 if clockwise_positive else 1.0
        return direction * float(ui_angle_elec_deg) / pole_pairs

    no_load_angles_elec_deg = (
        _full_cycle_back_emf_angle_grid(config, angles_elec_deg)
        if opts.back_emf or opts.thd_analysis
        else _cogging_angle_grid(config) if opts.cogging_torque else []
    )
    run_no_load = bool(no_load_angles_elec_deg)
    no_load_stage = "noload_sweep" if opts.back_emf or opts.thd_analysis else "magneto2d_cogging"
    no_load_timing_label = "No-load field solve" if opts.back_emf or opts.thd_analysis else "Cogging field solve"
    no_load_solve_kind = "no_load" if opts.back_emf or opts.thd_analysis else "cogging"
    include_no_load_field_frames = bool(
        getattr(solve_params, "stream_noload_field_lines", False)
    )
    no_load_angle_keys = {_per_angle_grid_key(angle) for angle in no_load_angles_elec_deg}
    loaded_angle_keys = {_per_angle_grid_key(angle) for angle in angles_elec_deg}
    no_load_only_angles = [
        angle for angle in no_load_angles_elec_deg
        if _per_angle_grid_key(angle) not in loaded_angle_keys
    ]
    loaded_mesh_evidence_by_key: dict[int, dict[str, Any]] = {}
    noload_mesh_evidence_by_key: dict[int, dict[str, Any]] = {}

    def record_solve_meshes(
        angle_elec_deg: float,
        solve_mesh_artifact: dict[str, Any],
        *,
        loaded: bool,
        noload: bool,
    ) -> None:
        angle_key = _per_angle_grid_key(angle_elec_deg)
        if loaded:
            loaded_mesh_evidence_by_key[angle_key] = build_solve_mesh_evidence(
                solve_mesh_artifact
            )
        if noload:
            noload_mesh_evidence_by_key[angle_key] = build_solve_mesh_evidence(
                _zero_current_solve_mesh_artifact(solve_mesh_artifact)
            )

    def attach_solve_mesh_evidence(sweep_report: dict[str, Any]) -> None:
        sweep_report["comparison_mesh_evidence"] = {
            "schema_version": "openem.magneto2d_mesh_execution_evidence/v1",
            "loaded": [
                loaded_mesh_evidence_by_key[_per_angle_grid_key(angle)]
                for angle in angles_elec_deg
            ],
            "noload": [
                noload_mesh_evidence_by_key[_per_angle_grid_key(angle)]
                for angle in no_load_angles_elec_deg
            ],
        }
    loaded_reports: list[dict[str, Any]] = []
    no_load_reports_by_key: dict[int, dict[str, Any]] = {}
    mesh_generation_time_ms = 0
    # Progress accounting counts EVERY field solve, not just no-load angles
    # outside the loaded grid. On a full-cycle sweep the no-load grid equals
    # the loaded grid, so the old accounting (len(no_load_only_angles) == 0)
    # froze the UI at N/N+1 for the entire back-EMF phase.
    progress_no_load_count = len(no_load_angles_elec_deg) if run_no_load else 0
    total_progress = len(angles_elec_deg) + progress_no_load_count + 1
    no_load_config = (
        _config_with_phase_current(excitation_config, 0.0)
        if run_no_load
        else None
    )
    compact_qa_report = solver_setting("COILEM_MAGNETO2D_COMPACT_QA_REPORT") == "1"
    raw_artifact_dir = None if compact_qa_report else _magneto2d_raw_cache_dir(solve_cache_dir)
    summary_cache_dir = _magneto2d_summary_cache_dir(solve_cache_dir)
    completed_steps = 0
    mesh_progress_label = f"{producer.source}_mesh"

    def emit_timing_delta(
        key: str,
        label: str,
        elapsed_ms: float,
        angle_elec_deg: float | None,
    ) -> None:
        _emit_solver_timing(
            on_progress,
            key,
            label,
            elapsed_ms,
            position=completed_steps,
            total=total_progress,
            angle_elec_deg=angle_elec_deg,
        )

    if _gmsh_imported_mesh_pipeline_enabled(
        producer,
        len(angles_elec_deg) + len(no_load_only_angles),
    ):
        mesh_jobs_by_key: dict[int, dict[str, Any]] = {}
        for idx, angle_elec_deg in enumerate(angles_elec_deg):
            angle_key = _per_angle_grid_key(angle_elec_deg)
            mesh_jobs_by_key[angle_key] = {
                "idx": idx,
                "angle_key": angle_key,
                "angle_elec_deg": float(angle_elec_deg),
                "rotor_angle_mech_deg": solver_rotor_angle_mech_deg(angle_elec_deg),
                "run_loaded": True,
                "run_no_load": False,
                "no_load_progress": False,
            }
        for angle_elec_deg in no_load_angles_elec_deg:
            angle_key = _per_angle_grid_key(angle_elec_deg)
            job = mesh_jobs_by_key.setdefault(
                angle_key,
                {
                    "idx": None,
                    "angle_key": angle_key,
                    "angle_elec_deg": float(angle_elec_deg),
                    "rotor_angle_mech_deg": solver_rotor_angle_mech_deg(angle_elec_deg),
                    "run_loaded": False,
                    "run_no_load": False,
                    "no_load_progress": True,
                },
            )
            job["run_no_load"] = True
            # Every no-load solve emits a progress tick (see total_progress
            # accounting above) so the bar keeps moving through the
            # back-EMF phase instead of stalling on full-cycle grids.
            job["no_load_progress"] = True

        mesh_jobs = [mesh_jobs_by_key[key] for key in sorted(mesh_jobs_by_key)]
        producer_workers = _gmsh_pipeline_worker_count(
            "COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS",
            len(mesh_jobs),
            uses_process_pool=True,
        )
        solve_workers = _gmsh_pipeline_worker_count(
            "COILEM_MAGNETO2D_GMSH_SOLVE_WORKERS",
            len(angles_elec_deg) + len(no_load_angles_elec_deg),
        )
        subprocess_workers = _per_angle_subprocess_workers(solve_workers)
        loaded_solve_config = _config_with_magneto2d_workers(
            excitation_config,
            subprocess_workers,
        )
        noload_solve_config = (
            _config_with_magneto2d_workers(no_load_config, subprocess_workers)
            if no_load_config is not None
            else None
        )
        config_payload = excitation_config.model_dump(mode="json")
        if excitation_config.solve_params is not None:
            config_payload["solve_params"]["excitation_rotation_convention"] = (
                excitation_config.solve_params.excitation_rotation_convention
            )
        loaded_reports_ordered: list[dict[str, Any] | None] = [None] * len(angles_elec_deg)
        solve_futures: dict[
            Future[tuple[str, dict[str, Any], dict[str, Any], float]],
            tuple[str, dict[str, Any]],
        ] = {}
        imported_mesh_checked = False
        pipeline_start = time.perf_counter()
        mesh_done_at = pipeline_start
        loaded_done_at = pipeline_start
        noload_done_at = pipeline_start

        def run_pipeline_solve(
            lane: Literal["loaded", "noload"],
            job: dict[str, Any],
            solve_mesh_artifact: dict[str, Any],
        ) -> tuple[str, dict[str, Any], dict[str, Any], float]:
            solve_config = loaded_solve_config if lane == "loaded" else noload_solve_config
            if solve_config is None:
                raise ValueError("No-load solve job was queued without a no-load config")
            solve_started = time.perf_counter()
            idx = job.get("idx")
            artifact_prefix = (
                f"sweep_pos{int(idx):03d}_{lane}"
                if idx is not None
                else f"noload_angle{int(job['angle_key'])}"
            )
            report = run_magneto2d_report(
                solve_config.model_copy(deep=True),
                sweep=False,
                rotor_angle_deg=float(job["rotor_angle_mech_deg"]),
                solve_mesh_artifact=solve_mesh_artifact,
                persist_artifacts_dir=raw_artifact_dir,
                artifact_prefix=artifact_prefix,
            )
            return lane, job, report, (time.perf_counter() - solve_started) * 1000.0

        def handle_mesh_ready(
            solve_pool: ThreadPoolExecutor,
            job: dict[str, Any],
            solve_mesh_artifact: dict[str, Any],
            generation_time_ms: int,
            *,
            submit_loaded: bool = True,
            submit_no_load: bool = True,
        ) -> None:
            nonlocal mesh_generation_time_ms
            mesh_generation_time_ms += int(generation_time_ms)
            record_solve_meshes(
                float(job["angle_elec_deg"]),
                solve_mesh_artifact,
                loaded=bool(job["run_loaded"]),
                noload=(
                    bool(job["run_no_load"])
                    and noload_solve_config is not None
                ),
            )
            if submit_loaded and bool(job["run_loaded"]):
                loaded_solve_future = solve_pool.submit(
                    run_pipeline_solve,
                    "loaded",
                    job,
                    solve_mesh_artifact,
                )
                solve_futures[loaded_solve_future] = ("loaded", job)
            if (
                submit_no_load
                and bool(job["run_no_load"])
                and noload_solve_config is not None
            ):
                noload_solve_future = solve_pool.submit(
                    run_pipeline_solve,
                    "noload",
                    job,
                    _zero_current_solve_mesh_artifact(solve_mesh_artifact),
                )
                solve_futures[noload_solve_future] = ("noload", job)

        # ── Slot-pitch congruence reuse (Gmsh lane only) ─────────────────
        #
        # Rotor angles that differ by a whole stator slot pitch produce
        # congruent geometry, so one Gmsh mesh serves the whole group via
        # rigid rotation + winding/magnet metadata fixup. Group jobs and
        # only send group bases to the producer; derived members are
        # synthesized in handle_group_mesh_ready.
        derived_jobs_by_base_key: dict[int, list[tuple[dict[str, Any], int]]] = {}
        producer_jobs = mesh_jobs
        if producer.source == "gmsh" and gmsh_mesh_reuse_enabled() and len(mesh_jobs) > 1:
            congruence_groups = slot_congruence_groups(
                mesh_jobs, config.stator.slot_count
            )
            if any(group["derived"] for group in congruence_groups):
                producer_jobs = [group["base"] for group in congruence_groups]
                derived_jobs_by_base_key = {
                    int(group["base"]["angle_key"]): list(group["derived"])
                    for group in congruence_groups
                }
                print(
                    "magneto2d: Gmsh slot-pitch mesh reuse — meshing "
                    f"{len(producer_jobs)} base angles, deriving "
                    f"{sum(len(group['derived']) for group in congruence_groups)} "
                    "congruent angles by rotation "
                    "(COILEM_MAGNETO2D_GMSH_MESH_REUSE=0 to disable)",
                    file=sys.stderr,
                    flush=True,
                )

        # ── Per-angle mesh cache lookup (all-or-nothing over the
        # producer jobs) ─────────────────────────────────────────────────
        #
        # The cache substitutes for the PRODUCER only: it is consulted after
        # slot-pitch congruence grouping so cached base artifacts still flow
        # through handle_group_mesh_ready — derived-angle rotation and
        # congruent SOLUTION reuse compose with cache hits instead of being
        # bypassed. Cached artifacts carry currents from the operating point
        # that built them; _rebake_gmsh_artifact_for_config rewrites them
        # for this config before use.
        cache_scope: str | None = None
        cached_base_artifacts: dict[int, dict[str, Any]] | None = None
        if producer.source == "gmsh" and _angle_mesh_cache_enabled():
            cache_scope = _angle_mesh_cache_scope_key(
                config,
                clockwise_positive=clockwise_positive,
            )
            cached_base_artifacts = _angle_mesh_cache_take_all(
                cache_scope,
                [int(job["angle_key"]) for job in producer_jobs],
            )

        # Mesh-completion progress: one tick per ready solve mesh (base Gmsh
        # build or derived rotation), with running counts in solver_detail so
        # the UI can render a live "Meshing N/M" stage. With the direct
        # linear solver, meshing is the longest visible wall-clock phase, so
        # without these ticks the progress UI sits frozen on "Prepare model"
        # for the whole producer stage.
        meshes_ready_count = 0
        total_mesh_artifacts = len(mesh_jobs)

        def emit_mesh_ready_tick(angle_elec_deg: float) -> None:
            nonlocal meshes_ready_count
            meshes_ready_count += 1
            if on_progress is None:
                return
            try:
                on_progress(
                    completed_steps,
                    total_progress,
                    None,
                    mesh_progress_label,
                    angle_elec_deg,
                    None,
                    None,
                    None,
                    None,
                    {
                        "mesh_completed": meshes_ready_count,
                        "mesh_total": total_mesh_artifacts,
                    },
                )
            except TypeError:
                # Minimal-arity fallback for progress callbacks that predate
                # the solver_detail parameter.
                on_progress(
                    completed_steps,
                    total_progress,
                    None,
                    mesh_progress_label,
                    angle_elec_deg,
                )

        # ── Slot-pitch congruence SOLUTION reuse ─────────────────────────
        #
        # A derived (rotated) artifact's solve IS the base solve rigidly
        # rotated whenever its per-element current densities match the base
        # artifact's — trivially true for the no-load lane, and true for the
        # loaded lane when one slot pitch maps the winding pattern onto
        # itself at the shifted electrical angle (e.g. 8p12s: one slot pitch
        # = 120° elec). For those lanes we skip the Rust solve and synthesize
        # the derived report from the base report when it lands.
        # Keyed by (lane, base angle_key); each entry carries the derived
        # artifact so a failed synthesis can fall back to a real solve.
        solve_reuse_active = (
            gmsh_solve_reuse_enabled()
            and bool(derived_jobs_by_base_key)
            and excitation_config.solve_params is not None
            and excitation_config.solve_params.excitation_mode != "ideal_six_step_120"
        )
        solution_reuse_by_base_key: dict[tuple[str, int], list[dict[str, Any]]] = {}

        def handle_group_mesh_ready(
            solve_pool: ThreadPoolExecutor,
            job: dict[str, Any],
            solve_mesh_artifact: dict[str, Any],
            generation_time_ms: int,
        ) -> None:
            # Populate the per-angle cache BEFORE the artifact is
            # handed to solve threads (store deep-copies internally).
            if cache_scope is not None:
                _angle_mesh_cache_store(
                    cache_scope, int(job["angle_key"]), solve_mesh_artifact
                )
            handle_mesh_ready(solve_pool, job, solve_mesh_artifact, generation_time_ms)
            emit_mesh_ready_tick(float(job["angle_elec_deg"]))
            for derived_job, n_slots in derived_jobs_by_base_key.get(
                int(job["angle_key"]), []
            ):
                rotation_started = time.perf_counter()
                derived_artifact = _rotate_gmsh_artifact_for_config(
                    solve_mesh_artifact,
                    excitation_config,
                    float(derived_job["rotor_angle_mech_deg"]),
                )
                if cache_scope is not None:
                    _angle_mesh_cache_store(
                        cache_scope, int(derived_job["angle_key"]), derived_artifact
                    )
                reuse_loaded = (
                    solve_reuse_active
                    and bool(job["run_loaded"])
                    and bool(derived_job["run_loaded"])
                    and slot_current_pattern_matches(
                        solve_mesh_artifact, derived_artifact
                    )
                )
                reuse_no_load = (
                    solve_reuse_active
                    and bool(job["run_no_load"])
                    and bool(derived_job["run_no_load"])
                    and noload_solve_config is not None
                )
                rotation_delta_deg = float(
                    derived_job["rotor_angle_mech_deg"]
                ) - float(job["rotor_angle_mech_deg"])
                reuse_entry = {
                    "job": derived_job,
                    "artifact": derived_artifact,
                    "n_slots": int(n_slots),
                    "rotation_delta_deg": rotation_delta_deg,
                }
                if reuse_loaded:
                    solution_reuse_by_base_key.setdefault(
                        ("loaded", int(job["angle_key"])), []
                    ).append(reuse_entry)
                if reuse_no_load:
                    solution_reuse_by_base_key.setdefault(
                        ("noload", int(job["angle_key"])), []
                    ).append(reuse_entry)
                handle_mesh_ready(
                    solve_pool,
                    derived_job,
                    derived_artifact,
                    int((time.perf_counter() - rotation_started) * 1000.0),
                    submit_loaded=not reuse_loaded,
                    submit_no_load=not reuse_no_load,
                )
                emit_mesh_ready_tick(float(derived_job["angle_elec_deg"]))

        with ThreadPoolExecutor(max_workers=solve_workers) as solve_pool:
            if cached_base_artifacts is not None:
                print(
                    "magneto2d: per-angle Gmsh mesh cache — reusing "
                    f"{len(producer_jobs)} cached base mesh(es); slot currents "
                    "re-baked for this operating point "
                    "(COILEM_MAGNETO2D_ANGLE_MESH_CACHE=0 to disable)",
                    file=sys.stderr,
                    flush=True,
                )
                for job in producer_jobs:
                    rebake_started = time.perf_counter()
                    solve_mesh_artifact = _rebake_gmsh_artifact_for_config(
                        cached_base_artifacts[int(job["angle_key"])],
                        excitation_config,
                    )
                    handle_group_mesh_ready(
                        solve_pool,
                        job,
                        solve_mesh_artifact,
                        int((time.perf_counter() - rebake_started) * 1000.0),
                    )
            elif producer_workers > 1:
                with ProcessPoolExecutor(max_workers=producer_workers) as mesh_pool:
                    mesh_futures: dict[
                        Future[tuple[dict[str, Any], int, float]],
                        dict[str, Any],
                    ] = {}
                    # Progress is emitted on mesh COMPLETION (see
                    # emit_mesh_ready_tick); submission-time ticks all fire
                    # in the same instant with identical counts and read as
                    # a frozen bar in the UI.
                    for job in producer_jobs:
                        mesh_future = mesh_pool.submit(
                            _build_gmsh_mesh_in_subprocess,
                            config_payload,
                            float(job["rotor_angle_mech_deg"]),
                        )
                        mesh_futures[mesh_future] = job
                    for mesh_future in as_completed(mesh_futures):
                        job = mesh_futures[mesh_future]
                        solve_mesh_artifact, generation_time_ms, _mesh_wall_ms = mesh_future.result()
                        handle_group_mesh_ready(
                            solve_pool,
                            job,
                            solve_mesh_artifact,
                            generation_time_ms,
                        )
            else:
                for job in producer_jobs:
                    mesh_started = time.perf_counter()
                    solve_mesh_artifact, generation_time_ms = producer.build(
                        excitation_config,
                        float(job["rotor_angle_mech_deg"]),
                    )
                    if not generation_time_ms:
                        generation_time_ms = int((time.perf_counter() - mesh_started) * 1000.0)
                    handle_group_mesh_ready(
                        solve_pool,
                        job,
                        solve_mesh_artifact,
                        generation_time_ms,
                    )

            mesh_done_at = time.perf_counter()
            emit_timing_delta(
                f"{producer.source}_mesh",
                f"{producer.display_name} mesh",
                (mesh_done_at - pipeline_start) * 1000.0,
                None,
            )

            if solution_reuse_by_base_key:
                reused_solve_count = sum(
                    len(entries) for entries in solution_reuse_by_base_key.values()
                )
                print(
                    "magneto2d: slot-pitch solution reuse — skipping "
                    f"{reused_solve_count} congruent FEM solve(s); derived "
                    "reports are synthesized from base solves by rotation "
                    "(COILEM_MAGNETO2D_GMSH_SOLVE_REUSE=0 to disable)",
                    file=sys.stderr,
                    flush=True,
                )

            loaded_arrived = 0
            noload_arrived = 0

            def handle_loaded_report(job: dict[str, Any], report: dict[str, Any]) -> None:
                nonlocal loaded_arrived, loaded_done_at, imported_mesh_checked, completed_steps
                angle_elec_deg = float(job["angle_elec_deg"])
                idx = int(job["idx"])
                loaded_reports_ordered[idx] = report
                loaded_done_at = time.perf_counter()
                if idx == 0:
                    _assert_imported_mesh_consumed_by_rust(producer, report, idx=idx)
                    imported_mesh_checked = True
                loaded_arrived += 1
                if on_progress is not None:
                    torque = _finite_number(report.get("results", {}).get("torque_nm"))
                    torque = _torque_in_ui_direction(
                        torque,
                        clockwise_positive=clockwise_positive,
                    )
                    completed_steps += 1
                    on_progress(
                        completed_steps,
                        total_progress,
                        torque,
                        "magneto2d_sweep",
                        angle_elec_deg,
                        None,
                        None,
                        None,
                        None,
                        {
                            "solve_kind": "loaded",
                            "completed_positions": loaded_arrived,
                            "total_positions": len(angles_elec_deg),
                        },
                    )

            def handle_noload_report(job: dict[str, Any], report: dict[str, Any]) -> None:
                nonlocal noload_arrived, noload_done_at, completed_steps
                angle_elec_deg = float(job["angle_elec_deg"])
                noload_done_at = time.perf_counter()
                no_load_reports_by_key[int(job["angle_key"])] = report
                noload_arrived += 1
                if on_progress is not None and bool(job["no_load_progress"]):
                    completed_steps += 1
                    on_progress(
                        completed_steps,
                        total_progress,
                        0.0,
                        no_load_stage,
                        angle_elec_deg,
                        None,
                        None,
                        None,
                        None,
                        {
                            "solve_kind": no_load_solve_kind,
                            "completed_positions": noload_arrived,
                            "total_positions": len(no_load_angles_elec_deg),
                        },
                    )

            def handle_reused_solutions(
                lane: Literal["loaded", "noload"],
                base_job: dict[str, Any],
                base_report: dict[str, Any],
            ) -> None:
                """Synthesize reports for derived angles congruent to a base solve.

                A synthesis failure (unexpected report shape) falls back to a
                real solve of the retained derived artifact, so reuse can only
                speed things up, never change whether a result is produced.
                """
                entries = solution_reuse_by_base_key.pop(
                    (lane, int(base_job["angle_key"])), []
                )
                for entry in entries:
                    derived_job = entry["job"]
                    try:
                        derived_report = derive_congruent_solve_report(
                            base_report,
                            slot_count=config.stator.slot_count,
                            n_slot_pitches=entry["n_slots"],
                            rotation_delta_deg=entry["rotation_delta_deg"],
                            elec_delta_deg=entry["rotation_delta_deg"] * pole_pairs,
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        print(
                            "magneto2d: solution reuse synthesis failed at "
                            f"elec={float(derived_job['angle_elec_deg']):.3f}° "
                            f"({lane}): {exc}; falling back to a real solve",
                            file=sys.stderr,
                            flush=True,
                        )
                        artifact = (
                            entry["artifact"]
                            if lane == "loaded"
                            else _zero_current_solve_mesh_artifact(entry["artifact"])
                        )
                        _lane, _job, derived_report, _elapsed = run_pipeline_solve(
                            lane, derived_job, artifact
                        )
                    if lane == "loaded":
                        handle_loaded_report(derived_job, derived_report)
                    else:
                        handle_noload_report(derived_job, derived_report)

            for solve_future in as_completed(solve_futures):
                lane, job, report, _elapsed_ms = solve_future.result()
                if lane == "loaded":
                    handle_loaded_report(job, report)
                    handle_reused_solutions("loaded", job, report)
                else:
                    handle_noload_report(job, report)
                    handle_reused_solutions("noload", job, report)

        loaded_reports = [report for report in loaded_reports_ordered if report is not None]
        if len(loaded_reports) != len(angles_elec_deg):
            raise ValueError("Parallel Gmsh Magneto2D pipeline did not return all loaded reports")
        if loaded_reports and not imported_mesh_checked:
            _assert_imported_mesh_consumed_by_rust(producer, loaded_reports[0], idx=0)

        solve_done_at = time.perf_counter()
        field_tail_ms = max(0.0, (solve_done_at - mesh_done_at) * 1000.0)
        noload_tail_ms = 0.0
        if run_no_load and noload_done_at > loaded_done_at:
            noload_tail_ms = max(0.0, (noload_done_at - max(loaded_done_at, mesh_done_at)) * 1000.0)
        loaded_tail_ms = max(0.0, field_tail_ms - noload_tail_ms)
        emit_timing_delta(
            "loaded_field_solve",
            "Loaded field solve",
            loaded_tail_ms,
            None,
        )
        if noload_tail_ms > 1.0:
            emit_timing_delta(
                "noload_field_solve",
                no_load_timing_label,
                noload_tail_ms,
                None,
            )

        no_load_reports = (
            [no_load_reports_by_key[_per_angle_grid_key(angle)] for angle in no_load_angles_elec_deg]
            if run_no_load
            else []
        )

        precomputed_field_line_frames: list[dict[str, Any]] | None = None
        if not compact_qa_report:
            field_frame_start = time.perf_counter()
            field_line_frames_ordered: list[dict[str, Any] | None] = [None] * len(loaded_reports)
            live_field_frames_ordered: list[dict[str, Any] | None] = [None] * len(loaded_reports)
            field_frame_jobs: list[
                tuple[int, dict[str, Any], float, dict[str, Any] | None, str | None, bool]
            ] = [
                (
                    idx,
                    loaded_reports[idx],
                    float(angles_elec_deg[idx]),
                    (
                        no_load_reports_by_key.get(_per_angle_grid_key(float(angles_elec_deg[idx])))
                        if include_no_load_field_frames
                        else None
                    ),
                    str(solve_cache_dir) if solve_cache_dir is not None else None,
                    _should_stream_live_field_frame(idx, len(loaded_reports)),
                )
                for idx in range(len(loaded_reports))
            ]

            frame_workers = _field_preview_worker_count(len(loaded_reports), solve_workers)
            if frame_workers > 1 and len(loaded_reports) > 1:
                with ProcessPoolExecutor(max_workers=frame_workers) as frame_pool:
                    frame_futures: list[
                        Future[tuple[int, dict[str, Any] | None, dict[str, Any] | None]]
                    ] = [
                        frame_pool.submit(_build_field_line_frame_in_subprocess, *frame_job)
                        for frame_job in field_frame_jobs
                    ]
                    for frame_future in as_completed(frame_futures):
                        idx, field_line_frame, live_field_frame = frame_future.result()
                        field_line_frames_ordered[idx] = field_line_frame
                        live_field_frames_ordered[idx] = live_field_frame
            else:
                for frame_job in field_frame_jobs:
                    frame_idx, field_line_frame, live_field_frame = _build_field_line_frame_in_subprocess(
                        *frame_job
                    )
                    field_line_frames_ordered[frame_idx] = field_line_frame
                    live_field_frames_ordered[frame_idx] = live_field_frame

            precomputed_field_line_frames = [
                frame for frame in field_line_frames_ordered if frame is not None
            ]
            emit_timing_delta(
                "field_frame_extract",
                "Field preview extraction",
                (time.perf_counter() - field_frame_start) * 1000.0,
                None,
            )

            if on_progress is not None:
                for idx, field_line_frame in enumerate(live_field_frames_ordered):
                    if field_line_frame is None:
                        continue
                    on_progress(
                        completed_steps,
                        total_progress,
                        None,
                        "magneto2d_sweep",
                        float(angles_elec_deg[idx]),
                        None,
                        None,
                        None,
                        field_line_frame,
                        _live_field_frame_solver_detail(),
                    )

        aggregate_start = time.perf_counter()
        sweep_report = _aggregate_per_angle_mesh_sweep(
            config,
            loaded_reports,
            no_load_reports if run_no_load else None,
            angles_elec_deg,
            no_load_angles_elec_deg=no_load_angles_elec_deg if run_no_load else None,
            mesh_generation_time_ms=mesh_generation_time_ms,
            mesh_label=producer.source,
            include_visual_frames=not compact_qa_report,
            include_no_load_field_frames=include_no_load_field_frames,
            precomputed_field_line_frames=precomputed_field_line_frames,
        )
        emit_timing_delta(
            "sweep_aggregation",
            "Sweep aggregation",
            (time.perf_counter() - aggregate_start) * 1000.0,
            None,
        )
        attach_solve_mesh_evidence(sweep_report)
        single_report = loaded_reports[0]

        if summary_cache_dir is not None:
            summary_cache_dir.mkdir(parents=True, exist_ok=True)
            (summary_cache_dir / "sweep_input.json").write_text(
                json.dumps(build_magneto2d_payload(config), indent=2),
                encoding="utf-8",
            )
            (summary_cache_dir / "sweep_report.json").write_text(
                json.dumps(sweep_report, indent=2),
                encoding="utf-8",
            )
            if not compact_qa_report:
                (summary_cache_dir / "single_report.json").write_text(
                    json.dumps(single_report, indent=2),
                    encoding="utf-8",
                )

        return sweep_report, single_report

    if _imported_mesh_batch_enabled(
        producer,
        len(angles_elec_deg) + len(no_load_only_angles),
    ):
        batch_loaded_jobs: list[dict[str, Any]] = []
        for idx, angle_elec_deg in enumerate(angles_elec_deg):
            rotor_angle_mech_deg = solver_rotor_angle_mech_deg(angle_elec_deg)
            if on_progress is not None:
                on_progress(
                    completed_steps,
                    total_progress,
                    None,
                    mesh_progress_label,
                    angle_elec_deg,
                )

            solve_mesh_artifact, gen_ms = producer.build(
                excitation_config,
                rotor_angle_mech_deg,
            )
            mesh_generation_time_ms += gen_ms
            emit_timing_delta(
                f"{producer.source}_mesh",
                f"{producer.display_name} mesh",
                float(gen_ms),
                angle_elec_deg,
            )
            record_solve_meshes(
                angle_elec_deg,
                solve_mesh_artifact,
                loaded=True,
                noload=_per_angle_grid_key(angle_elec_deg) in no_load_angle_keys,
            )
            batch_loaded_jobs.append(
                {
                    "idx": idx,
                    "angle_elec_deg": angle_elec_deg,
                    "rotor_angle_deg": rotor_angle_mech_deg,
                    "solve_mesh_artifact": solve_mesh_artifact,
                }
            )

        def handle_loaded_batch_progress(
            position: int,
            total: int,
            torque: float | None,
            angle_elec_deg: float | None,
            psi_a: float | None,
            psi_b: float | None,
            psi_c: float | None,
            field_line_frame: dict[str, Any] | None = None,
            native_stage: str = "magneto2d_sweep",
            detail: dict[str, Any] | None = None,
        ) -> None:
            if on_progress is None:
                return
            if native_stage != "magneto2d_sweep":
                return
            on_progress(
                completed_steps + position,
                total_progress,
                torque,
                native_stage,
                angle_elec_deg,
                psi_a,
                psi_b,
                psi_c,
                field_line_frame,
                detail,
            )

        loaded_start = time.perf_counter()
        loaded_reports = run_magneto2d_batch_reports(
            excitation_config,
            batch_loaded_jobs,
            keep_first_field_plot=True,
            progress_callback=handle_loaded_batch_progress if on_progress is not None else None,
            persist_artifacts_dir=raw_artifact_dir,
            artifact_prefix="loaded_batch",
        )
        loaded_elapsed_ms = (time.perf_counter() - loaded_start) * 1000.0
        emit_timing_delta(
            "loaded_field_solve",
            "Loaded field solve",
            loaded_elapsed_ms,
            None,
        )
        completed_steps += len(batch_loaded_jobs)
        if loaded_reports:
            _assert_imported_mesh_consumed_by_rust(producer, loaded_reports[0], idx=0)

        batch_no_load_jobs: list[dict[str, Any]] = []
        if no_load_config is not None:
            for job in batch_loaded_jobs:
                angle_elec_deg = float(job["angle_elec_deg"])
                angle_key = _per_angle_grid_key(angle_elec_deg)
                if angle_key in no_load_angle_keys:
                    batch_no_load_jobs.append(
                        {
                            "angle_key": angle_key,
                            "angle_elec_deg": angle_elec_deg,
                            "rotor_angle_deg": float(job["rotor_angle_deg"]),
                            "solve_mesh_artifact": _zero_current_solve_mesh_artifact(job["solve_mesh_artifact"]),
                            # Ticks for every no-load solve — see
                            # total_progress accounting above.
                            "progress": True,
                        }
                    )

            for extra_idx, angle_elec_deg in enumerate(no_load_only_angles):
                rotor_angle_mech_deg = solver_rotor_angle_mech_deg(angle_elec_deg)
                if on_progress is not None:
                    on_progress(
                        completed_steps,
                        total_progress,
                        None,
                        mesh_progress_label,
                        angle_elec_deg,
                    )

                solve_mesh_artifact, gen_ms = producer.build(
                    excitation_config,
                    rotor_angle_mech_deg,
                )
                mesh_generation_time_ms += gen_ms
                emit_timing_delta(
                    f"{producer.source}_mesh",
                    f"{producer.display_name} mesh",
                    float(gen_ms),
                    angle_elec_deg,
                )
                record_solve_meshes(
                    angle_elec_deg,
                    solve_mesh_artifact,
                    loaded=False,
                    noload=True,
                )
                batch_no_load_jobs.append(
                    {
                        "angle_key": _per_angle_grid_key(angle_elec_deg),
                        "angle_elec_deg": angle_elec_deg,
                        "rotor_angle_deg": rotor_angle_mech_deg,
                        "solve_mesh_artifact": _zero_current_solve_mesh_artifact(solve_mesh_artifact),
                        "progress": True,
                        "extra_idx": extra_idx,
                    }
                )

        if batch_no_load_jobs and no_load_config is not None:
            noload_start = time.perf_counter()
            noload_reports = run_magneto2d_batch_reports(
                no_load_config,
                batch_no_load_jobs,
                keep_first_field_plot=False,
                persist_artifacts_dir=raw_artifact_dir,
                artifact_prefix="noload_batch",
            )
            emit_timing_delta(
                "noload_field_solve",
                no_load_timing_label,
                (time.perf_counter() - noload_start) * 1000.0,
                None,
            )
            for job, batch_noload_report in zip(batch_no_load_jobs, noload_reports, strict=True):
                no_load_reports_by_key[int(job["angle_key"])] = batch_noload_report
                if on_progress is not None and bool(job["progress"]):
                    completed_steps += 1
                    on_progress(
                        completed_steps,
                        total_progress,
                        0.0,
                        no_load_stage,
                        float(job["angle_elec_deg"]),
                        None,
                        None,
                        None,
                        None,
                    )

        no_load_reports = (
            [no_load_reports_by_key[_per_angle_grid_key(angle)] for angle in no_load_angles_elec_deg]
            if run_no_load
            else []
        )

        aggregate_start = time.perf_counter()
        sweep_report = _aggregate_per_angle_mesh_sweep(
            config,
            loaded_reports,
            no_load_reports if run_no_load else None,
            angles_elec_deg,
            no_load_angles_elec_deg=no_load_angles_elec_deg if run_no_load else None,
            mesh_generation_time_ms=mesh_generation_time_ms,
            mesh_label=producer.source,
            include_visual_frames=False,
            include_no_load_field_frames=include_no_load_field_frames,
        )
        emit_timing_delta(
            "sweep_aggregation",
            "Sweep aggregation",
            (time.perf_counter() - aggregate_start) * 1000.0,
            None,
        )
        attach_solve_mesh_evidence(sweep_report)
        single_report = loaded_reports[0]

        if summary_cache_dir is not None:
            summary_cache_dir.mkdir(parents=True, exist_ok=True)
            (summary_cache_dir / "sweep_input.json").write_text(
                json.dumps(build_magneto2d_payload(config), indent=2),
                encoding="utf-8",
            )
            (summary_cache_dir / "sweep_report.json").write_text(
                json.dumps(sweep_report, indent=2),
                encoding="utf-8",
            )
            if not compact_qa_report:
                (summary_cache_dir / "single_report.json").write_text(
                    json.dumps(single_report, indent=2),
                    encoding="utf-8",
                )

        return sweep_report, single_report

    parallel_workers = _per_angle_parallel_workers(
        producer,
        len(angles_elec_deg) + len(no_load_only_angles),
    )
    if parallel_workers > 1:
        subprocess_workers = _per_angle_subprocess_workers(parallel_workers)
        loaded_solve_config = _config_with_magneto2d_workers(
            excitation_config,
            subprocess_workers,
        )
        noload_solve_config = (
            _config_with_magneto2d_workers(no_load_config, subprocess_workers)
            if no_load_config is not None
            else None
        )
        parallel_loaded_jobs: list[dict[str, Any]] = []

        for idx, angle_elec_deg in enumerate(angles_elec_deg):
            rotor_angle_mech_deg = solver_rotor_angle_mech_deg(angle_elec_deg)
            if on_progress is not None:
                on_progress(
                    completed_steps,
                    total_progress,
                    None,
                    mesh_progress_label,
                    angle_elec_deg,
                )

            solve_mesh_artifact, gen_ms = producer.build(
                excitation_config,
                rotor_angle_mech_deg,
            )
            mesh_generation_time_ms += gen_ms
            emit_timing_delta(
                f"{producer.source}_mesh",
                f"{producer.display_name} mesh",
                float(gen_ms),
                angle_elec_deg,
            )
            record_solve_meshes(
                angle_elec_deg,
                solve_mesh_artifact,
                loaded=True,
                noload=_per_angle_grid_key(angle_elec_deg) in no_load_angle_keys,
            )
            parallel_loaded_jobs.append(
                {
                    "idx": idx,
                    "angle_elec_deg": angle_elec_deg,
                    "rotor_angle_mech_deg": rotor_angle_mech_deg,
                    "solve_mesh_artifact": solve_mesh_artifact,
                }
            )

        def run_loaded_job(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], float]:
            loaded_start = time.perf_counter()
            loaded_report = run_magneto2d_report(
                loaded_solve_config.model_copy(deep=True),
                sweep=False,
                rotor_angle_deg=float(job["rotor_angle_mech_deg"]),
                solve_mesh_artifact=job["solve_mesh_artifact"],
                persist_artifacts_dir=raw_artifact_dir,
                artifact_prefix=f"sweep_pos{int(job['idx']):03d}_loaded",
            )
            return job, loaded_report, (time.perf_counter() - loaded_start) * 1000.0

        parallel_loaded_reports_ordered: list[dict[str, Any] | None] = [None] * len(parallel_loaded_jobs)
        with ThreadPoolExecutor(max_workers=parallel_workers) as pool:
            loaded_futures: list[Future[tuple[dict[str, Any], dict[str, Any], float]]] = [
                pool.submit(run_loaded_job, job) for job in parallel_loaded_jobs
            ]
            for loaded_future in as_completed(loaded_futures):
                parallel_loaded_job, parallel_loaded_report, loaded_elapsed_ms = loaded_future.result()
                idx = int(parallel_loaded_job["idx"])
                angle_elec_deg = float(parallel_loaded_job["angle_elec_deg"])
                emit_timing_delta(
                    "loaded_field_solve",
                    "Loaded field solve",
                    loaded_elapsed_ms,
                    angle_elec_deg,
                )
                if idx == 0:
                    _assert_imported_mesh_consumed_by_rust(producer, parallel_loaded_report, idx=idx)
                parallel_loaded_reports_ordered[idx] = parallel_loaded_report

                if on_progress is not None:
                    torque = _finite_number(parallel_loaded_report.get("results", {}).get("torque_nm"))
                    torque = _torque_in_ui_direction(
                        torque,
                        clockwise_positive=clockwise_positive,
                    )
                    field_line_frame = None
                    if not compact_qa_report:
                        field_frame_start = time.perf_counter()
                        angle_key = _per_angle_grid_key(angle_elec_deg)
                        field_line_frame = _field_line_frame_from_report(
                            parallel_loaded_report,
                            angle_elec_deg,
                            (
                                no_load_reports_by_key.get(angle_key)
                                if include_no_load_field_frames
                                else None
                            ),
                        )
                        emit_timing_delta(
                            "field_frame_extract",
                            "Field preview extraction",
                            (time.perf_counter() - field_frame_start) * 1000.0,
                            angle_elec_deg,
                        )
                    completed_steps += 1
                    on_progress(
                        completed_steps,
                        total_progress,
                        torque,
                        "magneto2d_sweep",
                        angle_elec_deg,
                        None,
                        None,
                        None,
                        field_line_frame,
                    )

        loaded_reports = [report for report in parallel_loaded_reports_ordered if report is not None]
        if len(loaded_reports) != len(parallel_loaded_jobs):
            raise ValueError("Parallel Magneto2D sweep did not return all loaded reports")

        parallel_no_load_jobs: list[dict[str, Any]] = []
        if noload_solve_config is not None:
            for job in parallel_loaded_jobs:
                angle_elec_deg = float(job["angle_elec_deg"])
                angle_key = _per_angle_grid_key(angle_elec_deg)
                if angle_key in no_load_angle_keys:
                    parallel_no_load_jobs.append(
                        {
                            "angle_key": angle_key,
                            "angle_elec_deg": angle_elec_deg,
                            "rotor_angle_mech_deg": float(job["rotor_angle_mech_deg"]),
                            "solve_mesh_artifact": _zero_current_solve_mesh_artifact(job["solve_mesh_artifact"]),
                            "artifact_prefix": f"sweep_pos{int(job['idx']):03d}_noload",
                            # Ticks for every no-load solve — see
                            # total_progress accounting above.
                            "progress": True,
                        }
                    )

            for extra_idx, angle_elec_deg in enumerate(no_load_only_angles):
                rotor_angle_mech_deg = solver_rotor_angle_mech_deg(angle_elec_deg)
                if on_progress is not None:
                    on_progress(
                        completed_steps,
                        total_progress,
                        None,
                        mesh_progress_label,
                        angle_elec_deg,
                    )

                solve_mesh_artifact, gen_ms = producer.build(
                    excitation_config,
                    rotor_angle_mech_deg,
                )
                mesh_generation_time_ms += gen_ms
                emit_timing_delta(
                    f"{producer.source}_mesh",
                    f"{producer.display_name} mesh",
                    float(gen_ms),
                    angle_elec_deg,
                )
                record_solve_meshes(
                    angle_elec_deg,
                    solve_mesh_artifact,
                    loaded=False,
                    noload=True,
                )
                parallel_no_load_jobs.append(
                    {
                        "angle_key": _per_angle_grid_key(angle_elec_deg),
                        "angle_elec_deg": angle_elec_deg,
                        "rotor_angle_mech_deg": rotor_angle_mech_deg,
                        "solve_mesh_artifact": _zero_current_solve_mesh_artifact(solve_mesh_artifact),
                        "artifact_prefix": f"noload_pos{extra_idx:03d}",
                        "progress": True,
                    }
                )

        def run_noload_job(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], float]:
            if noload_solve_config is None:
                raise ValueError("No-load solve job was queued without a no-load config")
            noload_start = time.perf_counter()
            noload_report = run_magneto2d_report(
                noload_solve_config.model_copy(deep=True),
                sweep=False,
                rotor_angle_deg=float(job["rotor_angle_mech_deg"]),
                solve_mesh_artifact=job["solve_mesh_artifact"],
                persist_artifacts_dir=raw_artifact_dir,
                artifact_prefix=str(job["artifact_prefix"]),
            )
            return job, noload_report, (time.perf_counter() - noload_start) * 1000.0

        if parallel_no_load_jobs:
            with ThreadPoolExecutor(max_workers=min(parallel_workers, len(parallel_no_load_jobs))) as pool:
                noload_futures: list[Future[tuple[dict[str, Any], dict[str, Any], float]]] = [
                    pool.submit(run_noload_job, job) for job in parallel_no_load_jobs
                ]
                for noload_future in as_completed(noload_futures):
                    parallel_noload_job, parallel_noload_report, noload_elapsed_ms = (
                        noload_future.result()
                    )
                    angle_elec_deg = float(parallel_noload_job["angle_elec_deg"])
                    emit_timing_delta(
                        "noload_field_solve",
                        no_load_timing_label,
                        noload_elapsed_ms,
                        angle_elec_deg,
                    )
                    no_load_reports_by_key[int(parallel_noload_job["angle_key"])] = (
                        parallel_noload_report
                    )
                    if on_progress is not None and bool(parallel_noload_job["progress"]):
                        completed_steps += 1
                        on_progress(
                            completed_steps,
                            total_progress,
                            0.0,
                            no_load_stage,
                            angle_elec_deg,
                            None,
                            None,
                            None,
                            None,
                        )

        no_load_reports = (
            [no_load_reports_by_key[_per_angle_grid_key(angle)] for angle in no_load_angles_elec_deg]
            if run_no_load
            else []
        )

        aggregate_start = time.perf_counter()
        sweep_report = _aggregate_per_angle_mesh_sweep(
            config,
            loaded_reports,
            no_load_reports if run_no_load else None,
            angles_elec_deg,
            no_load_angles_elec_deg=no_load_angles_elec_deg if run_no_load else None,
            mesh_generation_time_ms=mesh_generation_time_ms,
            mesh_label=producer.source,
            include_visual_frames=not compact_qa_report,
            include_no_load_field_frames=include_no_load_field_frames,
        )
        emit_timing_delta(
            "sweep_aggregation",
            "Sweep aggregation",
            (time.perf_counter() - aggregate_start) * 1000.0,
            None,
        )
        attach_solve_mesh_evidence(sweep_report)
        single_report = loaded_reports[0]

        if summary_cache_dir is not None:
            summary_cache_dir.mkdir(parents=True, exist_ok=True)
            (summary_cache_dir / "sweep_input.json").write_text(
                json.dumps(build_magneto2d_payload(config), indent=2),
                encoding="utf-8",
            )
            (summary_cache_dir / "sweep_report.json").write_text(
                json.dumps(sweep_report, indent=2),
                encoding="utf-8",
            )
            if not compact_qa_report:
                (summary_cache_dir / "single_report.json").write_text(
                    json.dumps(single_report, indent=2),
                    encoding="utf-8",
                )

        return sweep_report, single_report

    for idx, angle_elec_deg in enumerate(angles_elec_deg):
        rotor_angle_mech_deg = solver_rotor_angle_mech_deg(angle_elec_deg)
        if on_progress is not None:
            on_progress(
                completed_steps,
                total_progress,
                None,
                mesh_progress_label,
                angle_elec_deg,
            )

        solve_mesh_artifact, gen_ms = producer.build(
            excitation_config,
            rotor_angle_mech_deg,
        )
        mesh_generation_time_ms += gen_ms
        emit_timing_delta(
            f"{producer.source}_mesh",
            f"{producer.display_name} mesh",
            float(gen_ms),
            angle_elec_deg,
        )
        record_solve_meshes(
            angle_elec_deg,
            solve_mesh_artifact,
            loaded=True,
            noload=_per_angle_grid_key(angle_elec_deg) in no_load_angle_keys,
        )

        loaded_start = time.perf_counter()
        serial_loaded_report = run_magneto2d_report(
            excitation_config,
            sweep=False,
            rotor_angle_deg=rotor_angle_mech_deg,
            solve_mesh_artifact=solve_mesh_artifact,
            persist_artifacts_dir=raw_artifact_dir,
            artifact_prefix=f"sweep_pos{idx:03d}_loaded",
        )
        emit_timing_delta(
            "loaded_field_solve",
            "Loaded field solve",
            (time.perf_counter() - loaded_start) * 1000.0,
            angle_elec_deg,
        )
        if idx == 0:
            _assert_imported_mesh_consumed_by_rust(producer, serial_loaded_report, idx=idx)
        loaded_reports.append(serial_loaded_report)

        serial_noload_report: dict[str, Any] | None = None
        angle_key = _per_angle_grid_key(angle_elec_deg)
        if no_load_config is not None and angle_key in no_load_angle_keys:
            noload_mesh_artifact = _zero_current_solve_mesh_artifact(solve_mesh_artifact)
            noload_start = time.perf_counter()
            serial_noload_report = run_magneto2d_report(
                no_load_config,
                sweep=False,
                rotor_angle_deg=rotor_angle_mech_deg,
                solve_mesh_artifact=noload_mesh_artifact,
                persist_artifacts_dir=raw_artifact_dir,
                artifact_prefix=f"sweep_pos{idx:03d}_noload",
            )
            emit_timing_delta(
                "noload_field_solve",
                no_load_timing_label,
                (time.perf_counter() - noload_start) * 1000.0,
                angle_elec_deg,
            )
            no_load_reports_by_key[angle_key] = serial_noload_report
            if on_progress is not None:
                # Tick the no-load solve separately so progress accounting
                # matches total_progress (which counts every field solve).
                completed_steps += 1
                on_progress(
                    completed_steps,
                    total_progress,
                    0.0,
                    no_load_stage,
                    angle_elec_deg,
                    None,
                    None,
                    None,
                    None,
                )

        if on_progress is not None:
            torque = _finite_number(serial_loaded_report.get("results", {}).get("torque_nm"))
            torque = _torque_in_ui_direction(
                torque,
                clockwise_positive=clockwise_positive,
            )
            field_line_frame = None
            if not compact_qa_report:
                field_frame_start = time.perf_counter()
                field_line_frame = _field_line_frame_from_report(
                    serial_loaded_report,
                    angle_elec_deg,
                    serial_noload_report if include_no_load_field_frames else None,
                )
                emit_timing_delta(
                    "field_frame_extract",
                    "Field preview extraction",
                    (time.perf_counter() - field_frame_start) * 1000.0,
                    angle_elec_deg,
                )
            completed_steps += 1
            on_progress(
                completed_steps,
                total_progress,
                torque,
                "magneto2d_sweep",
                angle_elec_deg,
                None,
                None,
                None,
                field_line_frame,
            )

    for extra_idx, angle_elec_deg in enumerate(no_load_only_angles):
        rotor_angle_mech_deg = solver_rotor_angle_mech_deg(angle_elec_deg)
        if on_progress is not None:
            on_progress(
                completed_steps,
                total_progress,
                None,
                mesh_progress_label,
                angle_elec_deg,
            )

        solve_mesh_artifact, gen_ms = producer.build(
            excitation_config,
            rotor_angle_mech_deg,
        )
        mesh_generation_time_ms += gen_ms
        emit_timing_delta(
            f"{producer.source}_mesh",
            f"{producer.display_name} mesh",
            float(gen_ms),
            angle_elec_deg,
        )
        record_solve_meshes(
            angle_elec_deg,
            solve_mesh_artifact,
            loaded=False,
            noload=True,
        )

        if no_load_config is not None:
            noload_mesh_artifact = _zero_current_solve_mesh_artifact(solve_mesh_artifact)
            noload_start = time.perf_counter()
            extra_noload_report = run_magneto2d_report(
                no_load_config,
                sweep=False,
                rotor_angle_deg=rotor_angle_mech_deg,
                solve_mesh_artifact=noload_mesh_artifact,
                persist_artifacts_dir=raw_artifact_dir,
                artifact_prefix=f"noload_pos{extra_idx:03d}",
            )
            emit_timing_delta(
                "noload_field_solve",
                no_load_timing_label,
                (time.perf_counter() - noload_start) * 1000.0,
                angle_elec_deg,
            )
            no_load_reports_by_key[_per_angle_grid_key(angle_elec_deg)] = extra_noload_report

        if on_progress is not None:
            completed_steps += 1
            on_progress(
                completed_steps,
                total_progress,
                0.0,
                no_load_stage,
                angle_elec_deg,
                None,
                None,
                None,
                None,
            )

    no_load_reports = (
        [no_load_reports_by_key[_per_angle_grid_key(angle)] for angle in no_load_angles_elec_deg]
        if run_no_load
        else []
    )

    aggregate_start = time.perf_counter()
    sweep_report = _aggregate_per_angle_mesh_sweep(
        config,
        loaded_reports,
        no_load_reports if run_no_load else None,
        angles_elec_deg,
        no_load_angles_elec_deg=no_load_angles_elec_deg if run_no_load else None,
        mesh_generation_time_ms=mesh_generation_time_ms,
        mesh_label=producer.source,
        include_visual_frames=not compact_qa_report,
        include_no_load_field_frames=include_no_load_field_frames,
    )
    emit_timing_delta(
        "sweep_aggregation",
        "Sweep aggregation",
        (time.perf_counter() - aggregate_start) * 1000.0,
        None,
    )
    attach_solve_mesh_evidence(sweep_report)
    single_report = loaded_reports[0]

    if summary_cache_dir is not None:
        summary_cache_dir.mkdir(parents=True, exist_ok=True)
        (summary_cache_dir / "sweep_input.json").write_text(
            json.dumps(build_magneto2d_payload(config), indent=2),
            encoding="utf-8",
        )
        (summary_cache_dir / "sweep_report.json").write_text(
            json.dumps(sweep_report, indent=2),
            encoding="utf-8",
        )
        if not compact_qa_report:
            (summary_cache_dir / "single_report.json").write_text(
                json.dumps(single_report, indent=2),
                encoding="utf-8",
            )

    return sweep_report, single_report


class Magneto2DSolver(Solver):
    """Motor orchestration around native Magneto2D reports."""

    def __init__(self, *, launch_surface: bool = False) -> None:
        self._launch_surface = bool(launch_surface)
        self._cancelled = threading.Event()

    def cancel_active_solve(self) -> None:
        self._cancelled.set()
        cancel_active_magneto2d_processes()

    def _raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            # Also stop children that started while an earlier cancellation
            # raced mesh preparation. The public lane remains claimed until
            # this worker has actually returned.
            cancel_active_magneto2d_processes()
            raise SolveCancelledError("Solve cancelled by user.")

    @staticmethod
    def build_result_from_reports(
        config: MotorConfig,
        sweep_report: dict[str, Any],
        single_report: dict[str, Any],
        *,
        solve_cache_dir: Path | str | None = None,
        pipeline_stage: Literal["field_solve", "postprocess"] = "field_solve",
        postprocess_source_cache_dir: str | None = None,
        postprocess_time_s: float | None = None,
        solve_mesh_artifact: dict[str, Any] | None = None,
        solve_mesh_key: str | None = None,
        launch_surface: bool = False,
    ) -> SolveResult:
        """Map raw Magneto2D reports into the app-facing SolveResult shape.

        This is intentionally pure post-processing: callers may feed it reports
        from a fresh field solve or reports loaded back from a solve cache.
        """
        solve_params = config.solve_params
        if solve_params is None:
            raise ValueError("magneto2d postprocess requires solve_params")

        sweep = sweep_report["sweep"]
        torque_method = solve_params.torque_method
        torque_waveform_nm, avg_torque_nm, torque_metric = _select_magneto2d_torque_series(
            sweep,
            torque_method,
        )
        if launch_surface and torque_metric in _NATIVE_DIRECTION_TORQUE_METRICS:
            torque_waveform_nm = [
                -float(value)
                for value in torque_waveform_nm
            ]
            avg_torque_nm = -float(avg_torque_nm)
        rotor_positions_elec_deg = sweep["rotor_positions_elec_deg"]
        torque_q_axis_nm = _torque_at_q_axis_nm(rotor_positions_elec_deg, torque_waveform_nm)
        expected_torque_len = len(rotor_positions_elec_deg)
        phase_current_waveform = None
        if solve_params.excitation_mode == "ideal_six_step_120":
            phase_current_a = _aligned_number_list(
                sweep.get("phase_current_a_A"), expected_torque_len
            )
            phase_current_b = _aligned_number_list(
                sweep.get("phase_current_b_A"), expected_torque_len
            )
            phase_current_c = _aligned_number_list(
                sweep.get("phase_current_c_A"), expected_torque_len
            )
            if not all(
                len(values) == expected_torque_len
                for values in (phase_current_a, phase_current_b, phase_current_c)
            ):
                raise ValueError(
                    "six-step solve did not return phase-current samples aligned to torque"
                )
            phase_current_waveform = PhaseCurrentWaveform(
                electrical_angle_deg=rotor_positions_elec_deg,
                phase_a_A=phase_current_a,
                phase_b_A=phase_current_b,
                phase_c_A=phase_current_c,
            )
        torque_energy_fd_nm = _aligned_number_list(
            sweep.get("torque_energy_fd_nm"),
            expected_torque_len,
        )
        torque_coenergy_fd_nm = _aligned_number_list(
            sweep.get("torque_coenergy_fd_nm"),
            expected_torque_len,
        )
        if launch_surface:
            torque_energy_fd_nm = [
                -float(value)
                for value in torque_energy_fd_nm
            ]
            torque_coenergy_fd_nm = [
                -float(value)
                for value in torque_coenergy_fd_nm
            ]
        cogging_torque_waveform_nm, cogging_torque_metric = _select_magneto2d_cogging_series(
            sweep,
            torque_method,
        )
        if launch_surface and cogging_torque_metric in _NATIVE_DIRECTION_TORQUE_METRICS:
            cogging_torque_waveform_nm = [
                -float(value)
                for value in cogging_torque_waveform_nm
            ]
        torque_ripple_pct = _torque_ripple_pct(
            torque_waveform_nm,
            avg_torque_nm,
            sweep.get("torque_ripple_pct"),
        )
        single_results = single_report["results"]
        mesh_info = sweep_report["mesh_info"]
        operating_point = sweep_report["operating_point"]
        result_solve_options = config.solve_options or SolveOptionsConfig()
        back_emf_requested = bool(result_solve_options.back_emf or result_solve_options.thd_analysis)
        cogging_requested = bool(result_solve_options.cogging_torque)
        if back_emf_requested:
            no_load_waveform_a = sweep.get("no_load_back_emf_a_physical_v", sweep["back_emf_a_v"])
            no_load_waveform_b = sweep.get("no_load_back_emf_b_physical_v", sweep["back_emf_b_v"])
            no_load_waveform_c = sweep.get("no_load_back_emf_c_physical_v", sweep["back_emf_c_v"])
            back_emf_angles_elec_deg = (
                sweep.get("back_emf_rotor_positions_elec_deg")
                or sweep.get("no_load_rotor_positions_elec_deg")
                or rotor_positions_elec_deg
            )
            # Chained `or` (rather than dict.get with a default) is required
            # because the partial-sweep code path now writes
            # back_emf_fundamental_rms_v = None to signal "fundamental
            # unavailable". dict.get(k, default) returns None in that case
            # (key exists, value is None) and never falls back; `or` correctly
            # skips None and falls through to the peak-voltage fallback so
            # summary fields stay populated.
            emf_fundamental = (
                sweep.get("back_emf_fundamental_rms_v")
                or sweep.get("back_emf_fundamental_v")
                or sweep["back_emf_peak_v"]
            )
            back_emf_thd_pct = sweep.get("back_emf_thd_pct")
            back_emf_harmonic_analysis = sweep.get("back_emf_harmonic_analysis")
        else:
            back_emf_angles_elec_deg = (
                rotor_positions_elec_deg
                if len(rotor_positions_elec_deg) >= 2
                else [0.0, 360.0]
            )
            no_load_waveform_a = [0.0 for _ in back_emf_angles_elec_deg]
            no_load_waveform_b = [0.0 for _ in back_emf_angles_elec_deg]
            no_load_waveform_c = [0.0 for _ in back_emf_angles_elec_deg]
            emf_fundamental = 0.0
            back_emf_thd_pct = None
            back_emf_harmonic_analysis = None

        total_time_s = (sweep["total_time_ms"] + single_report["solve_info"]["total_time_ms"]) / 1000.0
        field_line_plot = build_field_line_plot(single_report)
        field_line_frames = _validated_field_line_frames(sweep_report.get("field_line_frames"))
        if field_line_frames is None:
            field_line_frames = _validated_field_line_frames(
                _field_line_frames_from_cache(
                    solve_cache_dir,
                    rotor_positions_elec_deg,
                )
            )
        field_line_frames = _attach_field_frame_artifacts(
            field_line_frames,
            solve_cache_dir,
        )
        steel_b_rms = steel_flux_density_rms_from_frames(field_line_frames or [])
        slot_excitation_frames = _validated_slot_excitation_frames(sweep_report.get("slot_excitation_frames") or sweep.get("slot_excitation_frames"))
        if slot_excitation_frames is None:
            slot_excitation_frames = _validated_slot_excitation_frames(
                _slot_excitation_frames_from_cache(
                    solve_cache_dir,
                    rotor_positions_elec_deg,
                )
            )
        # These diagnostics describe the excitation that was actually sent to
        # the native solver.  Keep the source angle, phase-current vector, and
        # per-slot contributions in that one native convention; negating only
        # the angle would make the record internally inconsistent.  Public CW
        # conversion is applied to presentation axes and torque separately.
        summary_slot_excitation = single_results.get("slot_excitation_contributions")
        if summary_slot_excitation is None and slot_excitation_frames:
            summary_slot_excitation = [contribution.model_dump(mode="json") for contribution in slot_excitation_frames[0].contributions]
        loss_breakdown = None
        efficiency = None
        weight_inertia = None
        torque_speed_envelope = None
        thermal_estimate = None
        demag_check = None
        slot_fill_check = None

        core_loss_density = sweep.get("core_loss_density_w_per_m3")
        if isinstance(core_loss_density, list):
            core_loss_density = [float(v) for v in core_loss_density]
        else:
            core_loss_density = None

        thermal_loss_map = None

        kt_const, ke_const, lambda_pm_const = compute_machine_constants(
            avg_torque_Nm=avg_torque_nm,
            current_amplitude_A=operating_point["resolved_phase_current_peak_a"],
            back_emf_fundamental_V_rms_LN=emf_fundamental,
            rated_speed_rpm=sweep["rated_speed_rpm"],
            pole_count=config.rotor.pole_count,
        )
        if solve_params.excitation_mode == "ideal_six_step_120":
            # Kt_Nm_per_A is defined for peak sinusoidal phase current. Keep
            # it undefined until a separate BLDC plateau-current constant is
            # introduced and named explicitly.
            kt_const = None


        mesh_source_val = getattr(config.solve_params, "mesh_source", "native")
        mesh_source_detail = mesh_info.get("mesh_source_detail") if isinstance(mesh_info, dict) else None
        geometry_ir_version = mesh_info.get("geometry_ir_version") if isinstance(mesh_info, dict) else None
        physics_contract_version = None
        region_source = "native_generated_mesh"
        current_source = "native_generated_mesh"
        magnetization_source = "native_generated_mesh"
        material_source = "native_generated_mesh"

        if solve_cache_dir:
            try:
                import json
                from pathlib import Path
                cache_path = Path(solve_cache_dir)
                if cache_path.exists():
                    # Prefer the tiny provenance sidecar; the full solve-mesh
                    # artifact carries node/triangle arrays and reaches tens
                    # of megabytes on fine meshes.
                    prov_payload = None
                    preferred_sidecars = [
                        cache_path / "single_provenance.json",
                        cache_path / "sweep_provenance.json",
                    ]
                    sidecar_files = preferred_sidecars + sorted(
                        cache_path.glob("*_provenance.json")
                    )
                    for p in sidecar_files:
                        if p.exists():
                            prov_payload = json.loads(p.read_text(encoding="utf-8"))
                            break
                    if prov_payload is None:
                        # Legacy cache dirs without a sidecar: fall back to
                        # parsing the full solve-mesh artifact.
                        mesh_files = list(cache_path.glob("*_mesh.json"))
                        preferred = [cache_path / "single_mesh.json", cache_path / "sweep_mesh.json"]
                        mesh_file = None
                        for p in preferred:
                            if p.exists():
                                mesh_file = p
                                break
                        if not mesh_file and mesh_files:
                            mesh_file = mesh_files[0]
                        if mesh_file and mesh_file.exists():
                            mesh_data = json.loads(mesh_file.read_text(encoding="utf-8"))
                            contract = mesh_data.get("physics_contract") or {}
                            prov = contract.get("provenance") or {}
                            prov_payload = {
                                "physics_contract_version": contract.get("version"),
                                "region_source": prov.get("region_source"),
                                "current_density_source": prov.get("current_density_source")
                                or prov.get("current_source"),
                                "magnetization_source": prov.get("magnetization_source"),
                                "material_assignment_source": prov.get("material_assignment_source"),
                            }
                    if prov_payload is not None:
                        physics_contract_version = prov_payload.get("physics_contract_version")
                        region_source = prov_payload.get("region_source") or region_source
                        current_source = prov_payload.get("current_density_source") or current_source
                        magnetization_source = prov_payload.get("magnetization_source") or magnetization_source
                        material_source = prov_payload.get("material_assignment_source") or material_source
            except Exception:
                pass

        return SolveResult(
            summary=SolveSummary(
                avg_torque_Nm=avg_torque_nm,
                avg_torque_energy_fd_Nm=_torque_in_ui_direction(
                    _finite_number(sweep.get("avg_torque_energy_fd_nm")),
                    clockwise_positive=launch_surface,
                    metric="energy_fd",
                ),
                avg_torque_coenergy_fd_Nm=_torque_in_ui_direction(
                    _finite_number(sweep.get("avg_torque_coenergy_fd_nm")),
                    clockwise_positive=launch_surface,
                    metric="coenergy_fd",
                ),
                avg_torque_field_fd_Nm=_torque_in_ui_direction(
                    _finite_number(sweep.get("avg_torque_field_fd_nm")),
                    clockwise_positive=launch_surface,
                ),
                avg_torque_pm_source_work_fd_Nm=_torque_in_ui_direction(
                    _finite_number(sweep.get("avg_torque_pm_source_work_fd_nm")),
                    clockwise_positive=launch_surface,
                ),
                avg_torque_current_source_work_fd_Nm=_torque_in_ui_direction(
                    _finite_number(sweep.get("avg_torque_current_source_work_fd_nm")),
                    clockwise_positive=launch_surface,
                ),
                torque_q_axis_Nm=torque_q_axis_nm,
                torque_ripple_pct=torque_ripple_pct,
                cogging_torque_Nm=sweep.get("cogging_torque_nm") if cogging_requested else None,
                back_emf_fundamental_V=emf_fundamental,
                back_emf_thd_pct=back_emf_thd_pct,
                back_emf_thd_h6_pct=sweep.get("back_emf_thd_h6_pct"),
                back_emf_thd_h12_pct=sweep.get("back_emf_thd_h12_pct"),
                back_emf_thd_h24_pct=sweep.get("back_emf_thd_h24_pct"),
                back_emf_line_thd_h12_pct=sweep.get("back_emf_line_thd_h12_pct"),
                back_emf_line_thd_h24_pct=sweep.get("back_emf_line_thd_h24_pct"),
                Kt_Nm_per_A=kt_const,
                Ke_Vs_per_rad_mech=ke_const,
                lambda_pm_Wb=lambda_pm_const,
                peak_flux_density_teeth_T=single_results["peak_b_tooth_t"],
                peak_flux_density_yoke_T=single_results["peak_b_yoke_t"],
                rms_flux_density_teeth_T=steel_b_rms.get("teeth") if steel_b_rms else None,
                rms_flux_density_yoke_T=steel_b_rms.get("yoke") if steel_b_rms else None,
                efficiency_pct=efficiency,
                loss_breakdown=loss_breakdown,
                weight_inertia=weight_inertia,
                torque_speed_envelope=torque_speed_envelope,
                thermal_estimate=thermal_estimate,
                demag_check=demag_check,
                slot_fill_check=slot_fill_check,
                slot_excitation_contributions=summary_slot_excitation,
                solve_time_s=total_time_s,
            ),
            torque_waveform=TorqueWaveform(
                electrical_angle_deg=rotor_positions_elec_deg,
                torque_Nm=torque_waveform_nm,
                torque_energy_fd_Nm=torque_energy_fd_nm or None,
                torque_coenergy_fd_Nm=torque_coenergy_fd_nm or None,
            ),
            phase_current_waveform=phase_current_waveform,
            cogging_torque_waveform=(
                TorqueWaveform(
                    electrical_angle_deg=sweep["cogging_rotor_positions_elec_deg"],
                    torque_Nm=cogging_torque_waveform_nm,
                )
                if cogging_requested
                and sweep.get("cogging_rotor_positions_elec_deg")
                and cogging_torque_waveform_nm
                and len(sweep["cogging_rotor_positions_elec_deg"]) == len(cogging_torque_waveform_nm)
                and len(sweep["cogging_rotor_positions_elec_deg"]) >= 2
                else None
            ),
            back_emf_waveform=BackEMFWaveform(
                electrical_angle_deg=back_emf_angles_elec_deg,
                phase_a_V=no_load_waveform_a,
                phase_b_V=no_load_waveform_b,
                phase_c_V=no_load_waveform_c,
                **(
                    {
                        "line_ab_V": [a - b for a, b in zip(no_load_waveform_a, no_load_waveform_b)],
                        "line_bc_V": [b - c for b, c in zip(no_load_waveform_b, no_load_waveform_c)],
                        "line_ca_V": [c - a for c, a in zip(no_load_waveform_c, no_load_waveform_a)],
                    }
                    if solve_params.excitation_mode == "ideal_six_step_120"
                    else {}
                ),
            ),
            back_emf_harmonic_analysis=back_emf_harmonic_analysis,
            flux_density_map=None,
            field_line_plot=field_line_plot,
            field_line_frames=field_line_frames,
            slot_excitation_frames=slot_excitation_frames,
            solve_metadata=SolveMetadata(
                solver_name="magneto2d-rust-0.3.2",
                solver_environment=single_report.get("solver_environment"),
                mesh_element_count=mesh_info["num_triangles"],
                rotor_positions=len(sweep["rotor_positions_elec_deg"]),
                timestamp=datetime.now(timezone.utc),
                current_amplitude_A=operating_point["resolved_phase_current_peak_a"],
                excitation_mode=(
                    solve_params.excitation_mode
                    if solve_params.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                current_amplitude_convention=(
                    solve_params.current_amplitude_convention
                    if solve_params.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                commutation_advance_deg=(
                    solve_params.commutation_advance_deg
                    if solve_params.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                phase_connection=(
                    solve_params.phase_connection
                    if solve_params.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                excitation_convention_version=(
                    "openem.bldc_six_step/v1"
                    if solve_params.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                loaded_cycle_complete=(
                    is_uniform_full_cycle_grid(rotor_positions_elec_deg)
                    if solve_params.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                rated_speed_rpm=sweep["rated_speed_rpm"],
                motor_input_dc_bus_V=getattr(config.solve_params, "motor_input_dc_bus_V", None),
                solve_cache_dir=str(solve_cache_dir) if solve_cache_dir is not None else None,
                pipeline_stage=pipeline_stage,
                postprocess_source_cache_dir=postprocess_source_cache_dir,
                postprocess_time_s=postprocess_time_s,
                solve_time_s=total_time_s,
                mesher=getattr(config.solve_params, "mesher", "gmsh"),
                mesh_density=getattr(config.solve_params, "mesh_density", None),
                mesh_source=mesh_source_val,
                mesh_source_detail=mesh_source_detail,
                geometry_ir_version=geometry_ir_version,
                rotor_rotation_model=getattr(
                    config.solve_params,
                    "rotor_rotation_model",
                    None,
                ),
                # Record the extractor that actually supplied the public
                # waveform. Selection can fall back for older/incomplete
                # cached reports, so echoing only the request is not valid
                # execution provenance.
                torque_method=_solve_metadata_torque_method(torque_metric),
                nonlinear_tolerance=estimate_magneto2d_nonlinear_tolerance(config),
                topology=config.topology,
                physics_contract_version=physics_contract_version,
                region_source=region_source,
                current_source=current_source,
                magnetization_source=magnetization_source,
                material_source=material_source,
            ),
            thermal_loss_map=thermal_loss_map,
            core_loss_density_w_per_m3=core_loss_density,
        )

    @staticmethod
    def attach_cached_field_line_frames(result: SolveResult) -> SolveResult:
        """Backfill per-angle compare artifacts from a persisted solve cache."""
        angle_grid = result.torque_waveform.electrical_angle_deg
        if not result.field_line_frames:
            frames = _validated_field_line_frames(
                _field_line_frames_from_cache(
                    result.solve_metadata.solve_cache_dir,
                    angle_grid,
                )
            )
            if frames is not None:
                result.field_line_frames = _attach_field_frame_artifacts(
                    frames,
                    result.solve_metadata.solve_cache_dir,
                )
        if (
            result.field_line_frames
            and (
                result.summary.rms_flux_density_teeth_T is None
                or result.summary.rms_flux_density_yoke_T is None
            )
        ):
            steel_b_rms = steel_flux_density_rms_from_frames(result.field_line_frames)
            if steel_b_rms:
                result.summary.rms_flux_density_teeth_T = (
                    result.summary.rms_flux_density_teeth_T
                    if result.summary.rms_flux_density_teeth_T is not None
                    else steel_b_rms.get("teeth")
                )
                result.summary.rms_flux_density_yoke_T = (
                    result.summary.rms_flux_density_yoke_T
                    if result.summary.rms_flux_density_yoke_T is not None
                    else steel_b_rms.get("yoke")
                )
        if not result.slot_excitation_frames:
            slot_frames = _validated_slot_excitation_frames(
                _slot_excitation_frames_from_cache(
                    result.solve_metadata.solve_cache_dir,
                    angle_grid,
                )
            )
            if slot_frames is not None:
                result.slot_excitation_frames = slot_frames
        return result

    def postprocess_from_cache(
        self,
        config: MotorConfig,
        *,
        solve_cache_dir: str | Path,
    ) -> SolveResult:
        """Rebuild a SolveResult from persisted Magneto2D field reports."""
        if config.solve_params is None:
            raise ValueError("magneto2d postprocess requires solve_params")

        cache_dir = Path(solve_cache_dir).expanduser()
        if not cache_dir.is_dir():
            raise ValueError(f"solve cache directory does not exist: {cache_dir}")

        sweep_report_path = cache_dir / "sweep_report.json"
        single_report_path = cache_dir / "single_report.json"
        missing = [str(path.name) for path in (sweep_report_path, single_report_path) if not path.exists()]
        if missing:
            raise ValueError("solve cache is missing raw Magneto2D report(s): " + ", ".join(missing))

        start = time.time()
        try:
            sweep_report = json.loads(sweep_report_path.read_text(encoding="utf-8"))
            single_report = json.loads(single_report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"solve cache contains invalid JSON: {exc}") from exc

        _validate_magneto2d_postprocess_cache_matches_config(
            config,
            sweep_report,
            single_report,
        )
        sweep = sweep_report.get("sweep")
        if isinstance(sweep, dict):
            _require_cached_torque_method_available(
                sweep,
                str(config.solve_params.torque_method),
            )

        return self.build_result_from_reports(
            config,
            sweep_report,
            single_report,
            solve_cache_dir=cache_dir,
            pipeline_stage="postprocess",
            postprocess_source_cache_dir=str(cache_dir),
            postprocess_time_s=time.time() - start,
            launch_surface=self._launch_surface,
        )


    @staticmethod
    def _solve_with_per_angle_gmsh_meshes(
        config: MotorConfig,
        *,
        solve_cache_dir: Path | None,
        on_progress=None,
        clockwise_positive: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Solve each sweep angle on a fresh Gmsh mesh, then assemble a sweep report."""
        return _solve_with_per_angle_producer_meshes(
            config,
            _GmshMeshProducer(),
            solve_cache_dir=solve_cache_dir,
            on_progress=on_progress,
            clockwise_positive=clockwise_positive,
        )

    def solve(
        self,
        config: MotorConfig,
        on_progress=None,
        solve_mesh_key: str | None = None,
    ) -> SolveResult:
        self._raise_if_cancelled()
        original_progress = on_progress

        def checked_progress(*args, **kwargs):
            self._raise_if_cancelled()
            if original_progress is not None:
                return original_progress(*args, **kwargs)

        on_progress = wraps(original_progress)(checked_progress) if original_progress is not None else checked_progress
        config = _config_with_gmsh_remesh_per_step(config)
        require_magneto2d_supported(config)

        solve_cache_dir = self._prepare_solve_cache_dir() if _magneto2d_prepare_cache_dir() else None

        def build_result_from_reports_with_timing(
            sweep_report: dict[str, Any],
            single_report: dict[str, Any],
            *,
            pipeline_stage: Literal["field_solve", "postprocess"] = "field_solve",
            solve_mesh_artifact: dict[str, Any] | None = None,
            solve_mesh_key: str | None = None,
        ) -> SolveResult:
            self._raise_if_cancelled()
            result_start = time.perf_counter()
            result = self.build_result_from_reports(
                config,
                sweep_report,
                single_report,
                solve_cache_dir=_magneto2d_summary_cache_dir(solve_cache_dir),
                pipeline_stage=pipeline_stage,
                solve_mesh_artifact=solve_mesh_artifact,
                solve_mesh_key=solve_mesh_key,
                launch_surface=self._launch_surface,
            )
            _emit_solver_timing(
                on_progress,
                "result_packaging",
                "Result packaging",
                (time.perf_counter() - result_start) * 1000.0,
            )
            return result

        try:
            solve_params = config.solve_params
            if solve_params is None:
                raise ValueError("magneto2d solve requires solve_params")
            mesh_source = getattr(solve_params, "mesh_source", "native")
            mesher = getattr(solve_params, "mesher", "gmsh")
            uses_remesh_per_step = getattr(solve_params, "rotor_rotation_model", "fixed_mesh") == "remesh_per_step"
            per_angle_gmsh_mesh = mesh_source == "native" and mesher == "gmsh" and uses_remesh_per_step
            solve_mesh_artifact = None if uses_remesh_per_step else get_cached_solve_mesh_artifact(solve_mesh_key, config)
            if per_angle_gmsh_mesh:
                sweep_report, single_report = self._solve_with_per_angle_gmsh_meshes(
                    config,
                    solve_cache_dir=solve_cache_dir,
                    on_progress=on_progress,
                    clockwise_positive=self._launch_surface,
                )
                _, progress_avg_torque, progress_torque_metric = _select_magneto2d_torque_series(
                    sweep_report["sweep"],
                    solve_params.torque_method,
                )
                progress_avg_torque = _torque_in_ui_direction(
                    progress_avg_torque,
                    clockwise_positive=self._launch_surface,
                    metric=progress_torque_metric,
                )
                if on_progress is not None:
                    on_progress(
                        estimate_magneto2d_sweep_positions(config) + 1,
                        estimate_magneto2d_sweep_positions(config) + 1,
                        progress_avg_torque,
                        "magneto2d_complete",
                        None,
                    )
                return build_result_from_reports_with_timing(
                    sweep_report,
                    single_report,
                    pipeline_stage="field_solve",
                    solve_mesh_artifact=solve_mesh_artifact if isinstance(solve_mesh_artifact, dict) else None,
                    solve_mesh_key=solve_mesh_key,
                )
            if mesh_source == "native" and mesher == "gmsh" and solve_mesh_artifact is None:
                gmsh_start = time.perf_counter()
                gmsh_mesh = run_gmsh_mesh_preview(config)
                _emit_solver_timing(
                    on_progress,
                    "gmsh_mesh",
                    "Gmsh mesh",
                    (time.perf_counter() - gmsh_start) * 1000.0,
                )
                solve_mesh_artifact = gmsh_mesh.get("solve_mesh_artifact")
                if not isinstance(solve_mesh_artifact, dict):
                    raise ValueError("Gmsh mesh preview did not include a solve mesh artifact")

            sweep_steps = estimate_magneto2d_sweep_positions(config)
            cogging_steps = estimate_magneto2d_cogging_positions(config)
            post_sweep_steps = sweep_steps + cogging_steps
            total_progress_steps = post_sweep_steps + 1
            pole_pairs = max(1, config.rotor.pole_count // 2)
            rated_speed_rpm = solve_params.rated_speed_rpm
            torque_method = solve_params.torque_method
            omega_elec_rad_s = 2.0 * math.pi * rated_speed_rpm / 60.0 * pole_pairs
            noload_flux_linkage_samples: dict[int, tuple[float, float, float, float]] = {}
            emit_live_back_emf = config.solve_options is None or config.solve_options.back_emf
            captured_field_line_frames: list[dict[str, Any]] = []

            def handle_native_progress(
                position: int,
                total: int,
                torque: float | None,
                elec_deg: float | None = None,
                psi_a_wb: float | None = None,
                psi_b_wb: float | None = None,
                psi_c_wb: float | None = None,
                field_line_frame: dict[str, object] | None = None,
                native_stage: str | None = None,
                solver_detail: dict[str, object] | None = None,
            ) -> None:
                if on_progress is None:
                    return

                stage = native_stage or "magneto2d_sweep"
                progress_position = position
                if stage == "magneto2d_cogging":
                    progress_position = sweep_steps + position
                elif stage == "magneto2d_iteration" and solver_detail is not None and solver_detail.get("parent_stage") == "magneto2d_cogging":
                    progress_position = sweep_steps + position

                phase_a_v = phase_b_v = phase_c_v = None
                if (
                    stage == "magneto2d_sweep"
                    and emit_live_back_emf
                    and elec_deg is not None
                    and psi_a_wb is not None
                    and psi_b_wb is not None
                    and psi_c_wb is not None
                ):
                    sample_key = int(round(elec_deg * 1000))
                    noload_flux_linkage_samples[sample_key] = (
                        elec_deg,
                        psi_a_wb,
                        psi_b_wb,
                        psi_c_wb,
                    )
                    live_back_emf = _estimate_live_back_emf_at_angle(
                        sample_key,
                        noload_flux_linkage_samples,
                        omega_elec_rad_s,
                    )
                    if live_back_emf is not None:
                        phase_a_v, phase_b_v, phase_c_v = live_back_emf

                progress_field_line_frame = field_line_frame
                if field_line_frame is not None:
                    frame_payload = dict(field_line_frame)
                    if not isinstance(frame_payload.get("field_frame_artifact"), dict):
                        try:
                            angle_candidate: Any = frame_payload.get(
                                "angle_deg",
                                elec_deg if elec_deg is not None else position,
                            )
                            frame_angle = float(angle_candidate)
                        except (TypeError, ValueError):
                            frame_angle = float(position)
                        artifact_ref = field_artifacts.write_field_line_frame_artifact(
                            frame_payload,
                            _magneto2d_raw_cache_dir(solve_cache_dir),
                            pos_idx=max(0, len(captured_field_line_frames)),
                            elec_angle_deg=frame_angle,
                        )
                        if artifact_ref is not None:
                            frame_payload["field_frame_artifact"] = artifact_ref
                            frame_payload.setdefault("full_field_frame_artifact", artifact_ref)
                    captured_field_line_frames.append(_slim_captured_field_frame(frame_payload))
                    progress_field_line_frame = _slim_progress_field_frame(frame_payload)

                progress_args = (
                    progress_position,
                    total_progress_steps,
                    torque,
                    stage,
                    elec_deg,
                    phase_a_v,
                    phase_b_v,
                    phase_c_v,
                )
                if solver_detail is not None:
                    on_progress(*progress_args, progress_field_line_frame, solver_detail)
                elif progress_field_line_frame is not None:
                    on_progress(*progress_args, progress_field_line_frame)
                else:
                    on_progress(*progress_args)

            if on_progress is not None:
                on_progress(0, total_progress_steps, 0.0, "magneto2d_sweep", None)
            sweep_start = time.perf_counter()
            sweep_report = run_magneto2d_report(
                config,
                sweep=True,
                solve_mesh_artifact=solve_mesh_artifact,
                progress_callback=handle_native_progress if on_progress is not None else None,
                persist_artifacts_dir=_magneto2d_raw_cache_dir(solve_cache_dir),
                artifact_prefix="sweep",
            )
            _emit_solver_timing(
                on_progress,
                "magneto2d_sweep_process",
                "Magneto2D sweep process",
                (time.perf_counter() - sweep_start) * 1000.0,
            )
            _, progress_avg_torque, _ = _select_magneto2d_torque_series(
                sweep_report["sweep"],
                torque_method,
            )
            if on_progress is not None:
                on_progress(post_sweep_steps, total_progress_steps, progress_avg_torque, "magneto2d_single", None)
            single_start = time.perf_counter()
            single_report = run_magneto2d_report(
                config,
                sweep=False,
                solve_mesh_artifact=solve_mesh_artifact,
                persist_artifacts_dir=_magneto2d_raw_cache_dir(solve_cache_dir),
                artifact_prefix="single",
            )
            _emit_solver_timing(
                on_progress,
                "single_field_solve",
                "Single field solve",
                (time.perf_counter() - single_start) * 1000.0,
            )
            if on_progress is not None:
                on_progress(total_progress_steps, total_progress_steps, progress_avg_torque, "magneto2d_complete", None)
        except Magneto2DUnsupportedError as exc:
            raise ValueError(str(exc)) from exc

        result = build_result_from_reports_with_timing(
            sweep_report,
            single_report,
            pipeline_stage="field_solve",
            solve_mesh_artifact=solve_mesh_artifact if isinstance(solve_mesh_artifact, dict) else None,
            solve_mesh_key=solve_mesh_key,
        )
        if captured_field_line_frames:
            result.field_line_frames = _validated_field_line_frames(captured_field_line_frames)
        return result

    @staticmethod
    def _prepare_solve_cache_dir() -> Path | None:
        prefix = "magneto2d-"
        cache_roots = (
            field_artifacts.SOLVE_CACHE_ROOT,
            Path(tempfile.gettempdir()) / "openem" / "solve_cache",
        )
        for solve_cache_base in cache_roots:
            try:
                if solve_cache_base.exists():
                    caches = sorted(
                        (path for path in solve_cache_base.iterdir() if path.is_dir() and path.name.startswith(prefix)),
                        key=lambda path: path.stat().st_mtime,
                        reverse=True,
                    )
                    for stale in caches[10:]:
                        try:
                            shutil.rmtree(stale)
                        except Exception:
                            continue

                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
                candidate = solve_cache_base / f"{prefix}{timestamp}"
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except Exception:
                continue
        return None
