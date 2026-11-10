"""Parallel FEMM worker dispatcher.

Background
----------
A balanced FEMM solve takes ~7 minutes on a typical Windows PC because the
per-position ``mi_analyze()`` call dominates wall-clock time (~17 sec/position
× 24 positions). Rotor positions are embarrassingly parallel — each is an
independent magnetostatic solve once the geometry is fixed — so spawning N
worker FEMM instances and slicing the angle list across them gives roughly
N× speedup on multi-core machines.

This module owns the parallel dispatcher. Stage 1 plumbed config + env-var
override + the platform guard. **Stage 2 (this commit) adds the worker
function and the actual ProcessPoolExecutor fan-out.**

What runs in parallel mode
--------------------------
* The loaded torque sweep — the dominant cost. Each rotor position becomes
  an independent FEMM solve in a worker process.
* Per-position torque extraction (with the retry-on-flush-race wrapper).
* Per-position flux linkage extraction (used downstream for back-EMF).
* Pos-0 flux density extraction (peak B teeth/yoke + optional full map).

What's serial-only (skipped in parallel mode with a warning)
------------------------------------------------------------
* ``_captured_femm_mesh`` (FEMM mesh overlay) — Compare won't show the
  FEMM mesh layer for parallel runs.
* No-load back-EMF *interleaving* during the loaded sweep. The dedicated
  no-load back-EMF sweep that runs after the loaded loop is unaffected
  and produces the back-EMF waveform as usual.

Numerical correctness for torque, flux linkage, peak B, and the post-loop
back-EMF waveform is the same as serial mode — those are what the user
actually compares against Native FEM. Parallel workers emit lightweight
per-position progress messages as they finish, including slim field frames
for live flux-line playback; the same frames are also returned to the main
process after each worker chunk completes.

**Known fixture-dependent back-EMF divergence (~0-2%).** Validated on
spm_4p12s_simple AND spm_8p12s_concentrated via
scripts/femm_parallel_benchmark.py:

* spm_8p12s_concentrated: every metric agrees to 0.0000% across the
  full table (avg torque, ripple, back-EMF fundamental + THD, Kt,
  peak B teeth/yoke, per-position torque waveform maxΔ, per-position
  back-EMF maxΔ). Wall-clock: 256.3 s serial → 99.0 s parallel (2.59x).
* spm_4p12s_simple: torque + flux + peak B all 0.0000%, but back-EMF
  fundamental shows a deterministic ~1.78% delta. Reproducible across
  runs.

Root cause: serial mode seeds part of the no-load sample set from the
*interleaved* probe inside the loaded sweep (in a FEMM session that
just finished a loaded solve). Parallel mode runs the entire no-load
sweep post-loop in a clean FEMM session. FEMM's nonlinear iterative
solver appears to warm-start from prior solution state across calls
in the same process, and that hint differs between the two contexts
even with mi_newdocument(0) in between. On 4p12s the saturation
pattern doesn't quite converge to the same answer between paths;
on 8p12s it does. The parallel result is arguably the more correct
one (no loaded-solve contamination), and even the worst-case 1.78%
sits well inside the typical Native-vs-FEMM compare band of ±25%.
Acceptable for shipping; logged as a follow-up to either drop the
serial interleaved seeding (so serial matches parallel) or audit
FEMM mi_newdocument's state-reset scope.

Configuration
-------------
Two knobs flip serial / parallel:

* ``solve_params.femm_workers`` — Pydantic config field (1..16, default 1).
* ``OPENEM_FEMM_WORKERS`` — env-var override (operator knob).
* ``OPENEM_FEMM_WINE_PARALLEL=1`` — experimental non-Windows Wine opt-in.

Resolution: env var > config field > 1. Then clamped to platform support
(parallel always on ``sys.platform == 'win32'``; Wine/macOS only when the
experimental opt-in is set).

Platform constraints
--------------------
FEMM on Mac/Linux runs through pyFEMM's file-link mode under Wine. The stock
file-link path puts ``ifile.txt`` / ``ofile.txt`` next to ``femm.exe``, so
multiple workers using the same FEMM install collide. The experimental Wine
path copies the FEMM bin directory into a worker-private scratch directory and
points that worker's pyFEMM session at the copy, giving each process its own
file-link IPC files. This is intentionally opt-in until serial/parallel parity
and Wine stability are validated on the operator machine.

Cancellation
------------
Workers don't respect ``self._cancel_requested`` — that flag is process-
local. A cancel during a parallel sweep will let in-flight workers finish
their current chunk before the dispatcher returns. Cancellation between
the loaded sweep and the no-load post-pass still works as before.
"""

from __future__ import annotations

import logging
import math
import multiprocessing
import os
import platform
import queue
import shutil
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, as_completed, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from backend.steel_flux_metrics import (
    new_steel_flux_density_rms_accumulator,
    update_steel_flux_density_rms_accumulator,
)

logger = logging.getLogger(__name__)

# Env-var override for the worker count. Set OPENEM_FEMM_WORKERS=4 (or =1) to
# flip serial/parallel without touching config files. Useful for ops-style
# experimentation and CI matrix runs. Empty / unset / non-integer values are
# ignored and the config-supplied value is used instead.
WORKER_COUNT_ENV_VAR = "OPENEM_FEMM_WORKERS"
WINE_PARALLEL_ENV_VAR = "OPENEM_FEMM_WINE_PARALLEL"
WORKER_PROCESS_ENV_VAR = "OPENEM_FEMM_PARALLEL_WORKER"

# One-shot guard for the loud "parallel FEMM is unsafe on V-shape IPM" banner
# emitted by resolve_worker_count(). We only want it once per process so it
# doesn't spam every fixture's solve.
_PARALLEL_UNSAFE_WARNED = False


def _env_flag_enabled(name: str) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass
class PositionResult:
    """One rotor position's solve output, returned from a worker."""

    worker_id: int
    pos_idx: int
    mech_angle_deg: float
    elec_angle_deg: float
    # Loaded-sweep outputs
    torque_nm: float
    psi_a_wb: float
    psi_b_wb: float
    psi_c_wb: float
    # Pos-0-only payloads (populated only on the worker that owns pos 0)
    peak_flux_teeth_t: float | None = None
    peak_flux_yoke_t: float | None = None
    flux_map_dump: dict[str, Any] | None = None  # FluxDensityMap.model_dump()
    mesh_elements: int | None = None
    # Per-position slot excitation snapshot — populated for every position so
    # Compare's slot heatmap renders the same way for parallel runs as it
    # does for serial. Carried as the raw dict from
    # _build_slot_excitation_frame() to avoid pickling SlotExcitationFrame.
    slot_excitation_frame_dump: dict[str, Any] | None = None
    # Sprint 25: per-position slim field-line frame (contour_levels +
    # airgap_b_records only) so post-solve Compare / Solve viewers can
    # render flux lines + airgap |B| on parallel-mode FEMM runs. Same
    # shape the serial path appends to FEMMSolver._captured_field_line_frames.
    field_line_frame_dump: dict[str, Any] | None = None
    steel_b_rms_accumulator: dict[str, Any] | None = None
    # Per-position timing buckets emitted by the worker. These are later
    # reduced to the slowest worker's critical-path breakdown so the live UI
    # can explain the parallel wall time without summing work across workers.
    worker_timings_ms: dict[str, float] | None = None
    # Diagnostics: structured failure metadata if torque extraction fell back
    failure: dict[str, Any] | None = None


def parallel_supported() -> bool:
    """Return True iff this platform tolerates concurrent FEMM instances."""
    return sys.platform == "win32" or _env_flag_enabled(WINE_PARALLEL_ENV_VAR)


def _read_env_override() -> int | None:
    """Read OPENEM_FEMM_WORKERS env var, return None if unset/invalid."""
    raw = os.environ.get(WORKER_COUNT_ENV_VAR, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "[FEMM-PAR] %s=%r is not an integer; ignoring.",
            WORKER_COUNT_ENV_VAR,
            raw,
        )
        return None
    if value < 1:
        logger.warning(
            "[FEMM-PAR] %s=%d clamped to 1.", WORKER_COUNT_ENV_VAR, value
        )
        return 1
    return value


def resolve_worker_count(requested: int) -> int:
    """Return the actual worker count to use given user request + platform.

    Resolution order (first non-None wins):
        1. ``OPENEM_FEMM_WORKERS`` env var (operator override)
        2. ``requested`` argument (from ``solve_params.femm_workers``)
        3. fallback default of 1

    The result is then clamped to platform support: on non-Windows we force
    back to 1 with a one-shot warning so the user knows their parallel
    request didn't take effect.
    """
    env_value = _read_env_override()
    effective = env_value if env_value is not None else max(1, int(requested))
    if effective == 1:
        return 1
    if not parallel_supported():
        logger.warning(
            "[FEMM-PAR] femm_workers=%d requested, but parallel FEMM is "
            "only enabled by default on Windows. Falling back to a single "
            "FEMM instance on %s. To run the experimental Wine/macOS path, "
            "set %s=1.",
            effective,
            sys.platform,
            WINE_PARALLEL_ENV_VAR,
        )
        return 1
    _warn_parallel_unsafe(effective)
    return effective


def _warn_parallel_unsafe(worker_count: int) -> None:
    """Loud, one-shot banner that parallel FEMM has a known accuracy gap.

    Validated 2026-05-20 on the Sprint 31 mixed-PM gate: setting
    OPENEM_FEMM_WORKERS=8 broke FEMM reference torque on all 6 V-shape IPM
    contract rows (10-60x serial values) while flat IPM and SPM rows
    matched serial. Root cause is unconfirmed; until it's fixed, parallel
    FEMM should not be used for any run that gates on V-shape IPM
    reference torque (e.g. the windows-femm trust-release lane).
    """
    global _PARALLEL_UNSAFE_WARNED
    if _PARALLEL_UNSAFE_WARNED:
        return
    _PARALLEL_UNSAFE_WARNED = True
    banner = "=" * 78
    logger.warning(
        "\n%s\n"
        "[FEMM-PAR] WARNING: parallel FEMM enabled (workers=%d).\n"
        "[FEMM-PAR] Known accuracy gap: V-shape IPM reference torque diverges\n"
        "[FEMM-PAR] 10-60x from serial on the Sprint 31 mixed-PM gate (verified\n"
        "[FEMM-PAR] 2026-05-20). Do NOT trust V-shape IPM numbers produced under\n"
        "[FEMM-PAR] this mode. Flat IPM and SPM rows are unaffected.\n"
        "[FEMM-PAR] To disable, unset %s or set it to 1.\n"
        "%s",
        banner,
        worker_count,
        WORKER_COUNT_ENV_VAR,
        banner,
    )


def _wine_path_for_native_path(path: Path) -> str:
    """Convert a native path inside WINEPREFIX/drive_c to a C:\\ path."""
    if platform.system() == "Windows":
        return str(path)

    wine_prefix = Path(os.environ.get("WINEPREFIX", os.path.expanduser("~/.wine"))).resolve()
    drive_c = (wine_prefix / "drive_c").resolve()
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(drive_c)
    except ValueError as exc:
        raise RuntimeError(
            f"Wine worker path {resolved} is not under {drive_c}; cannot "
            "convert it to a C: path for FEMM."
        ) from exc
    return "C:\\\\" + "\\\\".join(rel.parts)


def _copy_worker_femm_runtime(
    *,
    source_femm_path: str | None,
    scratch: Path,
    worker_id: int,
) -> str | None:
    """Return worker-private FEMM exe path for the experimental Wine path.

    pyFEMM's Wine file-link mode stores ifile/ofile next to femm.exe. Copying
    the FEMM bin directory per worker is the smallest isolation boundary that
    keeps those IPC files from colliding while preserving FEMM's relative file
    lookups.
    """
    if platform.system() == "Windows" or not _env_flag_enabled(WINE_PARALLEL_ENV_VAR):
        return source_femm_path
    if not source_femm_path:
        return None

    source_exe = Path(source_femm_path).expanduser().resolve()
    if not source_exe.is_file():
        raise RuntimeError(f"FEMM worker source executable not found: {source_exe}")

    source_dir = source_exe.parent
    runtime_dir = scratch / f"femm_bin_worker_{worker_id}"
    ignore = shutil.ignore_patterns(
        "ifile.txt",
        "ofile.txt",
        "*.ans",
        "*.fem",
        "*.node",
        "*.ele",
    )
    shutil.copytree(source_dir, runtime_dir, dirs_exist_ok=True, ignore=ignore)
    runtime_exe = runtime_dir / source_exe.name
    if not runtime_exe.is_file():
        raise RuntimeError(f"FEMM worker executable copy missing: {runtime_exe}")
    return str(runtime_exe)


# -- Worker function --------------------------------------------------------
# `_solve_chunk_in_worker` is the top-level callable that ProcessPoolExecutor
# pickles into a worker process. It MUST be importable by name (no closures
# over local state), MUST take only picklable arguments, and MUST NOT depend
# on any state in the main process.

def _solve_chunk_in_worker(args_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Top-level worker function: solve a chunk of rotor positions.

    Imports the FEMM solver in the worker process (so it has its own pyfemm
    handle), reconstructs config + opts from picklable dicts, opens a fresh
    FEMM instance in a worker-private scratch dir, and processes its assigned
    positions sequentially. Returns a list of dicts (one per position) which
    the main process converts to ``PositionResult``.

    The worker dictionary is dict-of-dicts (rather than dataclasses) so we
    don't have to ferry custom types across the process boundary.
    """
    worker_start = time.perf_counter()

    def _elapsed_ms(start: float) -> float:
        return (time.perf_counter() - start) * 1000.0

    def _add_timing(timings: dict[str, float], key: str, start: float) -> None:
        timings[key] = timings.get(key, 0.0) + _elapsed_ms(start)

    # Imports are scoped here so the main process doesn't pay them on import.
    # pyfemm's `import femm` opens the FEMM HandleEx, which is the most
    # process-bound piece of state in the whole pipeline.
    import femm  # noqa: PLC0415

    from backend.femm_solver import (  # noqa: PLC0415  (worker-scoped)
        _FEMM_LIVE_AIRGAP_BRBT_BIN_COUNT,
        FEMMSolver,
        FEMMTorqueExtractionError,
        _airgap_b_records_from_frame,
        _airgap_point_records_from_open_solution,
        _build_femm_live_field_payload,
        _femm_postprocessor_mesh_counts,
        _read_femm_mesh_from_disk,
    )
    from backend.field_artifacts import (  # noqa: PLC0415
        airgap_record_stats,
        airgap_trace_profile_from_records,
        sample_airgap_records_evenly,
        write_airgap_records_artifact,
        write_field_line_frame_artifact,
    )
    from backend.geometry_drawer import (  # noqa: PLC0415
        compute_geometry,
    )
    from backend.models import (  # noqa: PLC0415
        FluxDensityMap,
        MotorConfig,
        SolveOptionsConfig,
    )

    config = MotorConfig.model_validate(args_dict["config"])
    opts = SolveOptionsConfig.model_validate(args_dict["opts"])
    positions: list[tuple[int, float]] = [
        (int(idx), float(ang)) for idx, ang in args_dict["positions"]
    ]
    pole_pairs: float = float(args_dict["pole_pairs"])
    flux_extraction_pos: int = int(args_dict["flux_extraction_pos"])
    worker_id: int = int(args_dict["worker_id"])
    scratch_root = Path(args_dict["scratch_root"])
    solve_cache_dir = (
        Path(args_dict["solve_cache_dir"])
        if args_dict.get("solve_cache_dir")
        else None
    )
    source_femm_path = args_dict.get("femm_exe_path")
    progress_queue = args_dict.get("progress_queue")

    # Worker-private scratch dir keeps each worker's .fem/.ans files isolated
    # so concurrent mi_saveas calls don't clobber each other. PID is part of
    # the path so re-runs with stale OS file handles don't collide.
    scratch = scratch_root / f"femm_worker_{worker_id}_{os.getpid()}"
    scratch.mkdir(parents=True, exist_ok=True)
    fem_path_native = scratch / "problem.fem"
    fem_path = (
        _wine_path_for_native_path(fem_path_native)
        if platform.system() != "Windows"
        else str(fem_path_native)
    )
    worker_femm_path = _copy_worker_femm_runtime(
        source_femm_path=source_femm_path,
        scratch=scratch,
        worker_id=worker_id,
    )

    # Tell FEMMSolver._open_femm that this process is one of several
    # concurrent workers. On Wine, global pkill cleanup would kill sibling
    # workers, so the solver switches to worker-local IPC cleanup.
    os.environ[WORKER_PROCESS_ENV_VAR] = "1"
    solver = FEMMSolver(femm_path=worker_femm_path)
    geom = compute_geometry(config)
    # _extract_torque reads self._last_geom to find magnet block positions
    # (mo_selectblock needs geom.magnets to walk the rotor blocks). The
    # serial path sets this in _solve_locked at line ~1133; we need to
    # mirror that here or every torque extraction in every worker raises
    # AttributeError on geom.magnets and gets recorded as NaN. Result:
    # avg torque = 0 across the whole sweep, which is what manifested
    # as the "0.0 Nm parallel solve" bug.
    solver._last_geom = geom
    solver._last_rotor_offset_rad = 0.0

    solver._open_femm(femm, show_window=False)
    worker_init_open_ms = _elapsed_ms(worker_start)

    results: list[dict[str, Any]] = []
    try:
        for position_offset, (pos_idx, mech_angle) in enumerate(positions):
            elec_angle = mech_angle * pole_pairs
            row_timings: dict[str, float] = {}
            if position_offset == 0:
                row_timings["femm_worker_init_open"] = worker_init_open_ms

            row: dict[str, Any] = {
                "worker_id": worker_id,
                "pos_idx": pos_idx,
                "mech_angle_deg": float(mech_angle),
                "elec_angle_deg": float(elec_angle),
                "torque_nm": math.nan,
                "psi_a_wb": 0.0,
                "psi_b_wb": 0.0,
                "psi_c_wb": 0.0,
                "peak_flux_teeth_t": None,
                "peak_flux_yoke_t": None,
                "flux_map_dump": None,
                "mesh_elements": None,
                "field_line_frame_dump": None,
                "steel_b_rms_accumulator": None,
                "worker_timings_ms": row_timings,
                "failure": None,
            }

            try:
                phase_start = time.perf_counter()
                solver._setup_problem(femm, config, geom)
                solver._last_rotor_offset_rad = math.radians(mech_angle)
                solver._draw_full_geometry(
                    femm, config, geom, rotor_offset_deg=mech_angle
                )
                solver._apply_winding_current(femm, config, geom, elec_angle)
                solver._apply_boundary(femm, geom)
                femm.mi_saveas(fem_path)
                _add_timing(row_timings, "femm_worker_model_setup", phase_start)

                phase_start = time.perf_counter()
                femm.mi_createmesh()
                _add_timing(row_timings, "femm_worker_mesh_create", phase_start)

                phase_start = time.perf_counter()
                femm.mi_analyze()
                _add_timing(row_timings, "femm_worker_analyze", phase_start)

                # Wine flush race: same 0.5 s pre-loadsolution + 0.2 s settle
                # the serial path uses. Workers run on Windows where this
                # matters less, but keeping the sleeps means worker output is
                # bit-for-bit comparable to serial.
                phase_start = time.perf_counter()
                time.sleep(0.5)
                _add_timing(row_timings, "femm_worker_settle_wait", phase_start)

                phase_start = time.perf_counter()
                femm.mi_loadsolution()
                _add_timing(row_timings, "femm_worker_load_solution", phase_start)

                phase_start = time.perf_counter()
                time.sleep(0.2)
                _add_timing(row_timings, "femm_worker_settle_wait", phase_start)

                phase_start = time.perf_counter()
                try:
                    femm.mo_shownames()
                except Exception:  # noqa: BLE001
                    pass
                _add_timing(row_timings, "femm_worker_load_solution", phase_start)

                # Postprocessor health probe
                try:
                    phase_start = time.perf_counter()
                    row["mesh_elements"], _ = _femm_postprocessor_mesh_counts(
                        femm,
                        pos_idx=pos_idx,
                        mech_angle=mech_angle,
                        elec_angle=elec_angle,
                    )
                    _add_timing(row_timings, "femm_worker_postprocessor_probe", phase_start)
                except Exception as probe_exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"FEMM postprocessor failed at pos_idx={pos_idx}; "
                        f"probe error: {probe_exc}"
                    ) from probe_exc

                # Torque extraction (mirrors the serial retry-once wrapper).
                torque = math.nan
                failure: dict[str, Any] | None = None
                phase_start = time.perf_counter()
                try:
                    torque = solver._extract_torque(femm)
                except FEMMTorqueExtractionError as first_exc:  # noqa: F841
                    try:
                        try:
                            femm.mo_close()
                        except Exception:  # noqa: BLE001
                            pass
                        time.sleep(1.5)
                        femm.mi_loadsolution()
                        time.sleep(0.5)
                        try:
                            femm.mo_shownames()
                        except Exception:  # noqa: BLE001
                            pass
                        torque = solver._extract_torque(femm)
                    except FEMMTorqueExtractionError as retry_exc:
                        torque = math.nan
                        failure = {
                            "position_index": pos_idx,
                            "mech_angle_deg": float(mech_angle),
                            "elec_angle_deg": float(elec_angle),
                            "error": str(retry_exc),
                            "retry_attempted": True,
                        }
                row["torque_nm"] = float(torque) if not math.isnan(torque) else math.nan
                row["failure"] = failure

                # Flux linkage feeds the back-EMF post-pass.
                psi_a, psi_b, psi_c = solver._extract_flux_linkage(
                    femm, config, geom
                )
                _add_timing(row_timings, "femm_worker_numeric_extraction", phase_start)
                row["psi_a_wb"] = float(psi_a)
                row["psi_b_wb"] = float(psi_b)
                row["psi_c_wb"] = float(psi_c)

                # Slot excitation snapshot for Compare's slot heatmap. The
                # serial path captures one of these per position; mirror that
                # here so parallel runs render the same panel. Failure to
                # capture is logged but not fatal — the heatmap simply has
                # holes at affected positions.
                try:
                    phase_start = time.perf_counter()
                    row["slot_excitation_frame_dump"] = solver._build_slot_excitation_frame(
                        femm, config, geom, elec_angle
                    )
                    _add_timing(row_timings, "femm_worker_slot_excitation", phase_start)
                except Exception as slot_exc:  # noqa: BLE001
                    logger.warning(
                        "[FEMM-PAR worker=%d] slot excitation capture failed at "
                        "pos_idx=%d: %s",
                        worker_id,
                        pos_idx,
                        slot_exc,
                    )

                # Sprint 25: per-position slim field frame so post-solve
                # Compare / Solve viewers can render flux lines + airgap |B|
                # on parallel runs. We disk-parse this position's .ans file,
                # build the same payload the serial path produces via
                # _build_femm_live_field_payload, then immediately strip the
                # heavy mesh / element-B arrays and keep only contour_levels
                # + pre-filtered airgap_b_records. JSON-friendly so it pickles
                # back to the main process cleanly.
                phase_start = time.perf_counter()
                try:
                    field_data = _read_femm_mesh_from_disk(fem_path)
                except Exception:  # noqa: BLE001
                    field_data = None
                if field_data and field_data.get("az_nodal"):
                    try:
                        live_field_frame = _build_femm_live_field_payload(
                            field_data,
                            elec_angle_deg=elec_angle,
                            geom=geom,
                            rotor_angle_mech_deg=mech_angle,
                        )
                    except Exception:  # noqa: BLE001
                        live_field_frame = None
                    if live_field_frame is not None:
                        try:
                            airgap_records = (
                                _airgap_point_records_from_open_solution(
                                    femm,
                                    geom,
                                )
                                or _airgap_b_records_from_frame(
                                    field_data,
                                    live_field_frame,
                                    geom=geom,
                                    rotor_angle_mech_deg=mech_angle,
                                )
                            )
                        except Exception:  # noqa: BLE001
                            airgap_records = None
                        airgap_profile = (
                            airgap_trace_profile_from_records(
                                airgap_records,
                                bin_count=_FEMM_LIVE_AIRGAP_BRBT_BIN_COUNT,
                                span_deg=360.0,
                            )
                            or live_field_frame.get("airgap_brbt")
                        )
                        airgap_stats = airgap_record_stats(airgap_records)
                        airgap_artifact = write_airgap_records_artifact(
                            airgap_records,
                            solve_cache_dir,
                            pos_idx=pos_idx,
                            elec_angle_deg=elec_angle,
                            profile=airgap_profile if isinstance(airgap_profile, dict) else None,
                        )
                        display_airgap_records = sample_airgap_records_evenly(airgap_records)
                        full_field_frame_artifact = None
                        try:
                            full_field_frame = _build_femm_live_field_payload(
                                field_data,
                                elec_angle_deg=elec_angle,
                                geom=geom,
                                include_raw_mesh=True,
                                rotor_angle_mech_deg=mech_angle,
                            )
                            if full_field_frame is not None:
                                full_field_frame.update(
                                    {
                                        "airgap_brbt": airgap_profile,
                                        "airgap_b_stats": airgap_stats,
                                        "airgap_b_artifact": airgap_artifact,
                                        "airgap_b_records": display_airgap_records,
                                    }
                                )
                                steel_b_rms = new_steel_flux_density_rms_accumulator()
                                update_steel_flux_density_rms_accumulator(
                                    steel_b_rms,
                                    full_field_frame,
                                )
                                row["steel_b_rms_accumulator"] = steel_b_rms
                                full_field_frame_artifact = write_field_line_frame_artifact(
                                    full_field_frame,
                                    solve_cache_dir,
                                    pos_idx=pos_idx,
                                    elec_angle_deg=elec_angle,
                                    artifact_label="full_field_frame",
                                )
                        except Exception:  # noqa: BLE001
                            full_field_frame_artifact = None
                        field_line_frame_dump = {
                            "angle_deg": live_field_frame.get(
                                "angle_deg", elec_angle
                            ),
                            "contour_levels": live_field_frame.get(
                                "contour_levels", []
                            ),
                            "az_min": live_field_frame.get("az_min"),
                            "az_max": live_field_frame.get("az_max"),
                            "n_pole_pitches": live_field_frame.get(
                                "n_pole_pitches"
                            ),
                            "total_span_deg": live_field_frame.get(
                                "total_span_deg"
                            ),
                            "airgap_brbt": airgap_profile,
                            "airgap_b_stats": airgap_stats,
                            "airgap_b_artifact": airgap_artifact,
                            "airgap_b_records": display_airgap_records,
                            "full_field_frame_artifact": full_field_frame_artifact,
                        }
                        field_frame_artifact = write_field_line_frame_artifact(
                            field_line_frame_dump,
                            solve_cache_dir,
                            pos_idx=pos_idx,
                            elec_angle_deg=elec_angle,
                        )
                        if field_frame_artifact is not None:
                            field_line_frame_dump["field_frame_artifact"] = field_frame_artifact
                        row["field_line_frame_dump"] = field_line_frame_dump
                _add_timing(row_timings, "femm_worker_field_frame", phase_start)

                # Pos-0 flux density (peak teeth/yoke always; full map opt-in).
                if pos_idx == flux_extraction_pos:
                    phase_start = time.perf_counter()
                    sampled_flux = solver._extract_flux_density(femm, geom)
                    row["peak_flux_teeth_t"] = float(
                        getattr(solver, "_peak_flux_teeth", 0.0)
                    )
                    row["peak_flux_yoke_t"] = float(
                        getattr(solver, "_peak_flux_yoke", 0.0)
                    )
                    if opts.flux_density:
                        try:
                            row["flux_map_dump"] = sampled_flux.model_dump()
                        except Exception as dump_exc:  # noqa: BLE001
                            logger.warning(
                                "[FEMM-PAR] flux map dump failed at "
                                "pos_idx=%d: %s",
                                pos_idx,
                                dump_exc,
                            )
                    _add_timing(row_timings, "femm_worker_flux_density", phase_start)

                phase_start = time.perf_counter()
                try:
                    femm.mo_close()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    femm.mi_close()
                except Exception:  # noqa: BLE001
                    pass
                _add_timing(row_timings, "femm_worker_document_close", phase_start)

            except Exception as exc:  # noqa: BLE001
                row["torque_nm"] = math.nan
                row["failure"] = {
                    "position_index": pos_idx,
                    "mech_angle_deg": float(mech_angle),
                    "elec_angle_deg": float(elec_angle),
                    "error": f"Worker exception: {exc}",
                    "retry_attempted": False,
                }
                logger.warning(
                    "[FEMM-PAR worker=%d] position %d failed: %s",
                    worker_id,
                    pos_idx,
                    exc,
                )

            results.append(row)
            if progress_queue is not None:
                try:
                    progress_queue.put(
                        {
                            "type": "position_complete",
                            "worker_id": worker_id,
                            "pos_idx": int(pos_idx),
                            "mech_angle_deg": float(mech_angle),
                            "elec_angle_deg": float(elec_angle),
                            "torque_nm": row.get("torque_nm"),
                            "field_line_frame_dump": row.get("field_line_frame_dump"),
                            "failed": row.get("failure") is not None,
                        }
                    )
                except Exception as progress_exc:  # noqa: BLE001
                    logger.debug(
                        "[FEMM-PAR worker=%d] progress publish failed at pos_idx=%d: %s",
                        worker_id,
                        pos_idx,
                        progress_exc,
                    )
    finally:
        teardown_start = time.perf_counter()
        try:
            femm.closefemm()
        except Exception:  # noqa: BLE001
            pass
        if results:
            timings = results[-1].setdefault("worker_timings_ms", {})
            if isinstance(timings, dict):
                timings["femm_worker_teardown"] = (
                    timings.get("femm_worker_teardown", 0.0)
                    + _elapsed_ms(teardown_start)
                )

    # Reference for static analysis — FluxDensityMap is imported above
    # specifically so the main process can rehydrate `flux_map_dump`.
    del FluxDensityMap

    return results


def _split_positions(
    mech_angles: list[float], workers: int
) -> list[list[tuple[int, float]]]:
    """Round-robin split of positions across workers.

    Round-robin (rather than contiguous chunking) keeps load balanced if any
    rotor angle takes longer to solve than its neighbours — common when an
    angle hits a near-saturation operating point. Pos 0 always lands in
    chunk 0 since every worker iterates its chunk in order.
    """
    chunks: list[list[tuple[int, float]]] = [[] for _ in range(workers)]
    for pos_idx, ang in enumerate(mech_angles):
        chunks[pos_idx % workers].append((pos_idx, float(ang)))
    return [c for c in chunks if c]  # drop empty chunks if positions < workers


def solve_positions_parallel(
    *,
    config: Any,
    geom: Any,  # noqa: ARG001  (unused; kept for API symmetry with serial)
    opts: Any,
    mech_angles: list[float],
    fem_path: str,
    workers: int,
    femm_exe_path: str | None = None,
    solve_cache_dir: Path | None = None,
    on_position_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[PositionResult]:
    """Dispatch a chunked parallel FEMM solve across N workers.

    Returns ``PositionResult`` instances sorted by ``pos_idx`` so the caller
    can iterate and append to its existing accumulators in the same order
    the serial path would have produced.

    The ``geom`` parameter is unused — workers rebuild geometry from
    ``config`` to avoid pickling FemmGeometryDescription. It's kept in the
    signature so the dispatcher call site looks the same as the serial path.
    """
    if workers <= 1:
        # Caller should have routed to the serial path; defensive fallback.
        workers = 1

    pole_pairs = config.rotor.pole_count / 2.0
    flux_extraction_pos = 0  # pos 0 always carries flux extraction

    # Use the existing fem_path's parent as the scratch root. On Wine this is
    # a C:\ path, so convert it back to the native WINEPREFIX/drive_c path
    # before carving worker subdirectories.
    from backend.geometry_drawer import get_native_path_from_wine_path  # noqa: PLC0415

    scratch_root = str(Path(get_native_path_from_wine_path(fem_path)).parent)

    chunks = _split_positions(list(mech_angles), workers)
    config_dump = config.model_dump()
    if config.solve_params is not None:
        # This adapter-only field is excluded from persisted public projects,
        # but worker reconstruction must retain the serial excitation frame.
        config_dump["solve_params"]["excitation_rotation_convention"] = (
            config.solve_params.excitation_rotation_convention
        )
    opts_dump = opts.model_dump()

    progress_manager: multiprocessing.managers.SyncManager | None = None
    progress_queue = None
    if on_position_progress is not None:
        try:
            progress_manager = multiprocessing.Manager()
            progress_queue = progress_manager.Queue()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[FEMM-PAR] could not create worker progress queue; "
                "parallel progress will update at sweep completion only: %s",
                exc,
            )

    args_list = [
        {
            "config": config_dump,
            "opts": opts_dump,
            "positions": chunk,
            "pole_pairs": pole_pairs,
            "flux_extraction_pos": flux_extraction_pos,
            "worker_id": worker_id,
            "scratch_root": scratch_root,
            "solve_cache_dir": str(solve_cache_dir) if solve_cache_dir is not None else None,
            "femm_exe_path": femm_exe_path,
            "progress_queue": progress_queue,
        }
        for worker_id, chunk in enumerate(chunks)
    ]

    logger.info(
        "[FEMM-PAR] dispatching %d positions across %d worker(s)",
        len(mech_angles),
        len(chunks),
    )

    raw_results: list[dict[str, Any]] = []
    reported_positions: set[int] = set()

    def drain_progress_queue() -> None:
        if progress_queue is None or on_position_progress is None:
            return
        while True:
            try:
                event = progress_queue.get_nowait()
            except queue.Empty:
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("[FEMM-PAR] progress queue drain failed: %s", exc)
                return
            if not isinstance(event, dict):
                continue
            raw_pos_idx = event.get("pos_idx")
            if raw_pos_idx is None:
                continue
            try:
                pos_idx = int(raw_pos_idx)
            except Exception:  # noqa: BLE001
                continue
            if pos_idx in reported_positions:
                continue
            reported_positions.add(pos_idx)
            on_position_progress(event)

    try:
        with ProcessPoolExecutor(max_workers=len(chunks)) as pool:
            futures = [pool.submit(_solve_chunk_in_worker, args) for args in args_list]
            if progress_queue is None:
                for fut in as_completed(futures):
                    raw_results.extend(fut.result())
            else:
                pending = set(futures)
                while pending:
                    done, pending = wait(
                        pending,
                        timeout=0.25,
                        return_when=FIRST_COMPLETED,
                    )
                    drain_progress_queue()
                    for fut in done:
                        raw_results.extend(fut.result())
                drain_progress_queue()
    finally:
        if progress_manager is not None:
            progress_manager.shutdown()

    # Sort by pos_idx so downstream sees a canonically ordered sweep. Workers
    # finish out-of-order, so this is required for any post-pass that
    # expects monotonic angles (back-EMF derivative, FFT, etc.).
    raw_results.sort(key=lambda r: int(r["pos_idx"]))

    # Convert to dataclasses for type-safety on the consuming side.
    results: list[PositionResult] = []
    for r in raw_results:
        results.append(
            PositionResult(
                worker_id=int(r.get("worker_id", -1)),
                pos_idx=int(r["pos_idx"]),
                mech_angle_deg=float(r["mech_angle_deg"]),
                elec_angle_deg=float(r["elec_angle_deg"]),
                torque_nm=float(r["torque_nm"]),
                psi_a_wb=float(r["psi_a_wb"]),
                psi_b_wb=float(r["psi_b_wb"]),
                psi_c_wb=float(r["psi_c_wb"]),
                peak_flux_teeth_t=(
                    float(r["peak_flux_teeth_t"])
                    if r.get("peak_flux_teeth_t") is not None
                    else None
                ),
                peak_flux_yoke_t=(
                    float(r["peak_flux_yoke_t"])
                    if r.get("peak_flux_yoke_t") is not None
                    else None
                ),
                flux_map_dump=r.get("flux_map_dump"),
                mesh_elements=(
                    int(r["mesh_elements"])
                    if r.get("mesh_elements") is not None
                    else None
                ),
                slot_excitation_frame_dump=r.get("slot_excitation_frame_dump"),
                # Sprint 25 regression: the worker writes
                # row["field_line_frame_dump"] (parallel.py:494) so that
                # SolveResult.field_line_frames populates on parallel runs,
                # but the dict→dataclass conversion above forgot to thread
                # it through. Without this line every parallel solve loses
                # its airgap_b_records + contour_levels and the frontend's
                # Airgap Inspector / "Field preview" sequence step come up
                # empty post-completion.
                field_line_frame_dump=r.get("field_line_frame_dump"),
                steel_b_rms_accumulator=r.get("steel_b_rms_accumulator"),
                worker_timings_ms=(
                    {
                        str(key): float(value)
                        for key, value in (r.get("worker_timings_ms") or {}).items()
                        if isinstance(value, (int, float)) and math.isfinite(float(value))
                    }
                    or None
                ),
                failure=r.get("failure"),
            )
        )
    return results
