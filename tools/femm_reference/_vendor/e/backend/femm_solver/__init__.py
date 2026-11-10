"""FEMM-based electromagnetic solver.

Sprint 3 implementation with:
- Wine-compatible file paths (S2-01)
- Incremental geometry: magnets + slots + winding current (S2-02)
- Torque vs. angle rotor sweep with periodicity (S2-03)
- Back-EMF from flux linkage derivative (S2-04)

Sprint 4 additions:
- S4-01: No-load back-EMF sweep with proper voltage scaling
- S4-02: Cogging torque extraction from no-load sweep
- S4-03: Nonlinear steel loading from FEMM library
- S4-06: Debug artifact capture
- S4-11: original SPM solver correctness with q-axis current override
- S4-12: Flux map grid extraction

Refactored in Sprint 6: Split into mixins for maintainability.
- femm_geometry.py: Drawing motor geometry in FEMM
- femm_extraction.py: Extracting results from solved FEMM problems
- femm_postprocess.py: Waveform tiling, back-EMF, THD, efficiency
"""

from __future__ import annotations

import contextlib
import inspect
import io
import logging
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np

from backend.femm_extraction import (
    FEMMExtractionMixin,
    FEMMTorqueExtractionError,
    _read_femm_mesh_from_disk,
)
from backend.femm_geometry import FEMMGeometryMixin
from backend.femm_parallel import (
    WORKER_PROCESS_ENV_VAR as _FEMM_PARALLEL_WORKER_ENV_VAR,
)
from backend.femm_parallel import (
    resolve_worker_count as _resolve_femm_worker_count,
)
from backend.femm_parallel import (
    solve_positions_parallel as _solve_positions_parallel,
)
from backend.femm_postprocess import FEMMPostprocessMixin
from backend.femm_utils import (
    check_femm_installation,
    check_wine_installation,
    get_femm_steel_material_name,
    get_material_properties,
    get_platform_info,
)
from backend.field_artifacts import (
    airgap_record_stats,
    airgap_trace_profile_from_records,
    sample_airgap_records_evenly,
    write_airgap_records_artifact,
    write_field_line_frame_artifact,
)
from backend.geometry_drawer import (
    MotorGeometry,
    compute_geometry,
    get_wine_compatible_path,
)
from backend.logging_utils import log_event, tagged_log
from backend.machine_constants import compute_machine_constants
from backend.material_contract import load_electrical_steel_curve
from backend.models import (
    BackEMFWaveform,
    FemmMeshSummary,
    FieldLineFrame,
    FluxDensityMap,
    MotorConfig,
    Node,
    PhaseCurrentWaveform,
    SlotExcitationContribution,
    SlotExcitationFrame,
    SolveMetadata,
    SolveOptionsConfig,
    SolveResult,
    SolveSummary,
    TorqueWaveform,
)
from backend.solver_contract import SolveCancelledError, Solver
from backend.steel_flux_metrics import (
    finalize_steel_flux_density_rms,
    merge_steel_flux_density_rms_accumulator,
    new_steel_flux_density_rms_accumulator,
    update_steel_flux_density_rms_accumulator,
)
from backend.sweep_planning import is_uniform_full_cycle_grid
from backend.thermal.magnet_temperature import resolve_manual_magnet_temperature_C
from backend.torque_metrics import torque_at_q_axis_nm

# Configure logging
logger = logging.getLogger(__name__)

_FEMM_STREAM_RAW_FIELD_MESH_ENV = "OPENEM_FEMM_STREAM_RAW_FIELD_MESH"
_FEMM_ALLOW_VSHAPE_PARALLEL_ENV = "OPENEM_FEMM_ALLOW_VSHAPE_PARALLEL"
_FEMM_LIVE_AIRGAP_BRBT_BIN_COUNT = 180


def _is_vshape_ipm_config(config: MotorConfig) -> bool:
    rotor = getattr(config, "rotor", None)
    return (
        getattr(config, "topology", None) == "IPM"
        and getattr(rotor, "ipm_topology", None) in {"v_shape", "pyleecan_holem50"}
    )


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_femm_workers_for_config(config: MotorConfig, requested_workers: int) -> int:
    effective_workers = _resolve_femm_worker_count(requested_workers)
    if effective_workers <= 1 or not _is_vshape_ipm_config(config):
        return effective_workers
    if _env_flag_enabled(_FEMM_ALLOW_VSHAPE_PARALLEL_ENV):
        logger.warning(
            "[FEMM-PAR] %s is set; allowing %d parallel FEMM workers on "
            "V-shape IPM despite the known reference-torque corruption risk.",
            _FEMM_ALLOW_VSHAPE_PARALLEL_ENV,
            effective_workers,
        )
        return effective_workers
    logger.warning(
        "[FEMM-PAR] Forcing serial FEMM for V-shape IPM. Parallel FEMM "
        "corrupts the V-shape IPM reference torque; set %s=1 only for "
        "diagnostic reproduction of that failure.",
        _FEMM_ALLOW_VSHAPE_PARALLEL_ENV,
    )
    return 1


def _should_stream_femm_raw_field_mesh() -> bool:
    """Return true only for diagnostic FEMM live frames with raw mesh arrays."""

    return os.environ.get(_FEMM_STREAM_RAW_FIELD_MESH_ENV) == "1"


def _diagnostic_magnet_br_scale() -> float:
    raw = os.environ.get("OPENEM_MAGNET_BR_SCALE")
    if raw is None:
        return 1.0
    try:
        value = float(raw.strip())
    except ValueError:
        return 1.0
    return value if math.isfinite(value) and value >= 0.0 else 1.0


def _emit_femm_solver_timing(
    on_progress: Any,
    key: str,
    label: str,
    elapsed_ms: float,
) -> None:
    """Emit an authoritative FEMM phase timing event through the SSE callback."""

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
        0,
        0,
        None,
        "solver_timing",
        None,
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


_FEMM_PARALLEL_CRITICAL_TIMING_LABELS = {
    "femm_worker_init_open": "FEMM worker init + open",
    "femm_worker_model_setup": "FEMM model setup",
    "femm_worker_mesh_create": "FEMM mesh creation",
    "femm_worker_analyze": "FEMM mi_analyze",
    "femm_worker_settle_wait": "FEMM settle waits",
    "femm_worker_load_solution": "FEMM load solution",
    "femm_worker_postprocessor_probe": "FEMM postprocessor probe",
    "femm_worker_numeric_extraction": "FEMM numeric extraction",
    "femm_worker_slot_excitation": "FEMM slot excitation",
    "femm_worker_field_frame": "FEMM field-frame extraction",
    "femm_worker_flux_density": "FEMM flux-density extraction",
    "femm_worker_document_close": "FEMM document close",
    "femm_worker_teardown": "FEMM worker teardown",
}


def _femm_parallel_critical_worker_timing_rows(
    parallel_results: list[Any],
    parallel_elapsed_ms: float,
) -> list[tuple[str, str, float]]:
    """Return wall-attribution rows for the slowest parallel FEMM worker."""

    by_worker: dict[int, dict[str, float]] = {}
    for result in parallel_results:
        worker_id_raw = getattr(result, "worker_id", None)
        timings = getattr(result, "worker_timings_ms", None)
        if not isinstance(worker_id_raw, int) or not isinstance(timings, dict):
            continue
        worker_timings = by_worker.setdefault(worker_id_raw, {})
        for key, value in timings.items():
            if key not in _FEMM_PARALLEL_CRITICAL_TIMING_LABELS:
                continue
            try:
                elapsed_ms = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(elapsed_ms) or elapsed_ms <= 0:
                continue
            worker_timings[key] = worker_timings.get(key, 0.0) + elapsed_ms

    if not by_worker:
        return []

    critical_worker_id, critical_timings = max(
        by_worker.items(),
        key=lambda item: sum(item[1].values()),
    )
    critical_total_ms = sum(critical_timings.values())
    if critical_total_ms <= 0:
        return []

    logger.info(
        "[FEMM-PAR] critical worker=%d attributed %.1f ms of %.1f ms "
        "parallel wall time",
        critical_worker_id,
        critical_total_ms,
        parallel_elapsed_ms,
    )

    rows: list[tuple[str, str, float]] = []
    for key, label in _FEMM_PARALLEL_CRITICAL_TIMING_LABELS.items():
        elapsed_ms = critical_timings.get(key, 0.0)
        if elapsed_ms > 0:
            rows.append((f"{key}_critical", label, elapsed_ms))

    overhead_ms = parallel_elapsed_ms - critical_total_ms
    if overhead_ms > 1.0:
        rows.append(
            (
                "femm_parallel_pool_overhead",
                "FEMM worker pool overhead",
                overhead_ms,
            )
        )
    return rows


def _looks_like_stale_femm_response(command: str, exc: Exception) -> bool:
    """Return True when FEMM answered this command with an older Lua error."""
    msg = str(exc)
    current_fn = command.split("(", 1)[0].strip()

    # FEMM includes the failing Lua snippet in many parser errors. If the
    # snippet references a different command payload than the one we just
    # sent, pyFEMM read a stale ofile.txt response from a prior command. This
    # catches same-function stale replies, for example an old
    # mi_addmaterial("SingleSlotCoil", ...) error surfacing during a UI mesh
    # preview that is currently sending mi_addmaterial("Coil_s0", ...).
    if current_fn and f"flput({current_fn}" in msg:
        current_first_arg_match = re.search(r"\(\s*[\"']([^\"']+)[\"']", command)
        current_first_arg = current_first_arg_match.group(1) if current_first_arg_match else ""
        if current_first_arg and current_first_arg in msg:
            return False
        normalized_command = command.replace(",", " ")
        if normalized_command not in msg:
            return True

    if "attempt to call global" in msg:
        match = re.search(r"attempt to call global [`']([^`']+)[`']", msg)
        if match is None:
            return False

        failed_fn = match.group(1)
        if failed_fn and current_fn and failed_fn != current_fn:
            return True

    return False


def _femm_scalar_response(value: Any, command: str) -> float:
    """Normalize pyFEMM scalar responses from COM and Wine filelink modes."""
    original = value
    while isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise TypeError(
                f"{command} returned {type(original).__name__} with "
                f"{len(value)} values; expected a scalar"
            )
        value = value[0]
    try:
        scalar = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{command} returned {type(original).__name__}; expected a scalar"
        ) from exc
    if not math.isfinite(scalar):
        raise ValueError(f"{command} returned non-finite value {scalar!r}")
    return scalar


def _femm_int_response(value: Any, command: str) -> int:
    """Normalize pyFEMM integer count responses from COM and Wine filelink modes."""
    return int(_femm_scalar_response(value, command))


def _femm_postprocessor_mesh_counts(
    femm: Any,
    *,
    pos_idx: int | None = None,
    mech_angle: float | None = None,
    elec_angle: float | None = None,
    retries: int = 3,
) -> tuple[int, int]:
    """Return FEMM postprocessor mesh counts, retrying Wine filelink empties."""
    label = "FEMM postprocessor"
    if pos_idx is not None:
        label = f"FEMM postprocessor at position {pos_idx}"
    angle_label = ""
    if mech_angle is not None and elec_angle is not None:
        angle_label = f" (mech={mech_angle:.2f}°, elec={elec_angle:.2f}°)"

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            num_elements = _femm_int_response(
                femm.mo_numelements(), "mo_numelements"
            )
            num_nodes = _femm_int_response(femm.mo_numnodes(), "mo_numnodes")
            if num_elements <= 0 or num_nodes <= 0:
                raise ValueError(
                    f"invalid mesh counts: nodes={num_nodes}, elements={num_elements}"
                )
            return num_elements, num_nodes
        except Exception as exc:  # noqa: BLE001 - preserve FEMM/pyFEMM context
            last_exc = exc
            if attempt >= retries:
                break
            delay_s = 0.5 * (attempt + 1)
            _solve_trace(
                f"{label}{angle_label} mesh-count probe failed on attempt "
                f"{attempt + 1}/{retries + 1}: {exc}; reloading solution"
            )
            try:
                femm.mo_close()
            except Exception:
                pass
            time.sleep(delay_s)
            femm.mi_loadsolution()
            time.sleep(0.3)
            try:
                femm.mo_shownames()
            except Exception:
                pass

    assert last_exc is not None
    raise last_exc


def _solve_trace(msg: str) -> None:
    """Emit a SOLVE_TRACE breadcrumb through the column-formatted logger.

    These breadcrumbs pinpoint *exactly* where a FEMM solve crashes or
    hangs. If FEMM briefly opens and closes without the UI surfacing
    an error, the last SOLVE_TRACE line in the backend log is the
    last step the solver completed before the failure — use it to
    triage Wine/FEMM-specific crashes.
    """
    log_event("SOLVE_TRACE", msg, level="DEBUG")


def _finite_difference_waveform(values: list[float], dx: float, *, periodic: bool) -> list[float]:
    """Mirror magneto2d's finite-difference helper for FEMM diagnostic sweeps."""
    if not values:
        return []
    if not math.isfinite(dx) or abs(dx) <= 1.0e-12:
        return [0.0 for _ in values]
    if len(values) == 1:
        return [0.0]
    if len(values) == 2:
        slope = (values[1] - values[0]) / dx
        return [slope, slope]

    out: list[float] = []
    n = len(values)
    for idx in range(n):
        if periodic:
            prev_value = values[(idx + n - 1) % n]
            next_value = values[(idx + 1) % n]
            out.append((next_value - prev_value) / (2.0 * dx))
        elif idx == 0:
            out.append((values[1] - values[0]) / dx)
        elif idx + 1 == n:
            out.append((values[n - 1] - values[n - 2]) / dx)
        else:
            out.append((values[idx + 1] - values[idx - 1]) / (2.0 * dx))
    return out


def _tile_loaded_waveform_for_reporting(solve_quality: str | None, sweep_elec_deg: float) -> bool:
    """Return True when FEMM should expand a loaded waveform to 360 degrees.

    Preset partial sweeps keep the historical FEMM behavior for dashboards and
    quick-look reports. Explicit custom partial sweeps are usually QA harness
    windows (for example ``--rotor-sweep-deg 90``), so their serialized FEMM
    waveform must stay on the same angle grid as native.
    """
    if sweep_elec_deg >= 360.0 - 1.0e-6:
        return True
    return solve_quality != "custom"


def _patch_femm_filelink_race(femm_module) -> None:
    """Harden pyFEMM's file-link call against three known failure modes on
    macOS/Wine.

    1. ofile unlink race: pyFEMM occasionally succeeds in reading ofile.txt
       and then raises FileNotFoundError while trying to unlink the same file
       a moment later. That should not fail the solve because the FEMM
       command already completed — we retry the read loop without unlink.

    2. Missing globals after closefemm: pyFEMM's closefemm() does
       `del ifile, ofile` on its module globals. If any callfemm happens
       AFTER that (e.g. a second "Run Solve" attempt where openfemm short-
       circuited, or a teardown that fires twice), Python raises NameError
       in pyFEMM's own callfemm body. Surface a clean, actionable error
       instead of a cryptic "name 'ofile' is not defined".

    3. Zombie-reuse via "FEMM is already open" probe: pyFEMM's openfemm()
       probes for an existing FEMM by writing `flput(0)` to ifile.txt and
       checking ofile.txt within ~10ms. If a prior solve left a zombie FEMM
       alive (pkill failed, Wine process name didn't match, etc.) the zombie
       responds with a stale queued error from its PREVIOUS command. That is
       exactly the "attempt to call global mo_getpointvalues (a nil value) —
       flput(mo_getpointvalues(-X.XXX...))" failure pattern. We replace
       openfemm with a version that ALWAYS launches fresh and uses
       `callfemm('setcurrentdirectory(...)')` as the readiness handshake.
    """
    if getattr(femm_module, "_openem_filelink_patch", False):
        return

    original_callfemm = femm_module.callfemm

    def _require_filelink_globals() -> None:
        """On non-Windows, pyFEMM needs module-level ifile/ofile globals.
        If they are missing, openfemm() has not been called (or closefemm
        wiped them) — give a clear, actionable error."""
        if femm_module.windowsOS:
            return
        if not hasattr(femm_module, "ifile") or not hasattr(femm_module, "ofile"):
            raise RuntimeError(
                "FEMM file-link globals are missing (ifile/ofile). This means "
                "closefemm() was called without a matching openfemm() before "
                "this FEMM command. The solver needs to re-open FEMM. If you "
                "just retried after a failed solve, please try again — the "
                "next Run Solve will call openfemm() fresh."
            )

    def safe_callfemm(myString):
        if femm_module.windowsOS:
            return original_callfemm(myString)

        _require_filelink_globals()

        try:
            return original_callfemm(myString)
        except NameError as exc:
            # pyFEMM's callfemm references bare `ifile`/`ofile` globals.
            # If they were wiped between check-and-call, turn the raw
            # NameError into something a user can act on.
            raise RuntimeError(
                f"FEMM file-link globals disappeared mid-call: {exc}. "
                "Re-open FEMM and retry the solve."
            ) from exc
        except FileNotFoundError as exc:
            if "ofile.txt" not in str(exc):
                raise

            _require_filelink_globals()

            try:
                f = open(femm_module.ifile, mode="wt")
            except Exception:
                f = open(femm_module.ifile, mode="w")

            f.write("flput(" + myString + ")")
            f.close()

            x = False
            while x is False:
                try:
                    f = open(femm_module.ofile, mode="rt")
                    x = (
                        f.readline()
                        .replace("[ ", "[")
                        .replace(" ]", "]")
                        .replace(" ", ",")
                        .replace("I", "1j")
                    )
                    f.close()
                except FileNotFoundError:
                    time.sleep(femm_module.sleeptime)
                    continue
                except OSError as err:
                    print("Error opening with mode rt failed:", err)
                    return

            time.sleep(femm_module.sleeptime)
            try:
                os.unlink(femm_module.ofile)
            except FileNotFoundError:
                pass

            if len(x) == 0:
                x = []
            elif x[0] == "e":
                error_msg = x.replace(",", " ").replace("1j", "I")
                raise Exception(error_msg)
            else:
                x = eval(x)
            if len(x) == 1:
                x = x[0]
            return x
        except Exception as exc:
            if not _looks_like_stale_femm_response(myString, exc):
                raise

            _solve_trace(
                "safe_callfemm: FEMM returned a stale Lua error while "
                f"running {myString!r}; retrying command once. Original "
                f"error: {exc}"
            )
            stale_ofile = getattr(femm_module, "ofile", None)
            if stale_ofile:
                try:
                    if os.path.exists(stale_ofile):
                        os.unlink(stale_ofile)
                except OSError:
                    pass
            time.sleep(max(getattr(femm_module, "sleeptime", 0.01), 0.05))
            return original_callfemm(myString)

    femm_module.callfemm = safe_callfemm
    femm_module._openem_filelink_patch = True

    # Also wrap closefemm so its `del ifile, ofile` cannot be skipped by a
    # raising `callfemm('quit()')` call, AND so a hanging quit() response
    # cannot wedge the solver thread forever.
    #
    # Failure modes addressed here:
    # 1. callfemm('quit()') raises (e.g. FEMM already dead) — we force-
    #    delete the globals so the next openfemm runs the fresh-setup path.
    # 2. callfemm('quit()') HANGS — because the original callfemm polls
    #    ofile.txt forever, and a quitting FEMM may never write it. This
    #    used to manifest as "FEMM briefly opens then closes, UI stuck at
    #    0%": the solver thread is blocked here, solve_future.result()
    #    never returns, and the SSE error event never gets yielded. Fix:
    #    send the quit signal in a best-effort way with a short write-then-
    #    don't-wait pattern, ignore any IPC failure, and reliably return.
    original_closefemm = femm_module.closefemm

    def _fire_and_forget_quit() -> None:
        """Write `flput(quit())` to ifile.txt without waiting for ofile.

        FEMM's quit handler tears down the process without necessarily
        emitting an ofile response, which is why the original callfemm
        loops forever. We just write the command and bail.
        """
        ifile = getattr(femm_module, "ifile", None)
        if not ifile:
            return
        try:
            try:
                f = open(ifile, mode="wt")
            except Exception:
                f = open(ifile, mode="w")
            f.write("flput(quit())")
            f.close()
        except OSError:
            # ifile directory may already be gone — nothing we can do.
            pass

    def safe_closefemm():
        if femm_module.windowsOS:
            try:
                return original_closefemm()
            except Exception:
                if hasattr(femm_module, "HandleToFEMM"):
                    try:
                        delattr(femm_module, "HandleToFEMM")
                    except Exception:
                        pass
                raise

        # Non-Windows: use the fire-and-forget quit, then force-clean the
        # globals. Do NOT call the original closefemm — it can hang on the
        # quit() response wait.
        try:
            _fire_and_forget_quit()
        finally:
            for name in ("ifile", "ofile", "HandleToFEMM"):
                if hasattr(femm_module, name):
                    try:
                        delattr(femm_module, name)
                    except Exception:
                        pass

    femm_module.closefemm = safe_closefemm

    # 3. Monkey-patch openfemm to skip pyFEMM's "FEMM is already open" probe
    #    on non-Windows. The probe writes `flput(0)` to ifile.txt and checks
    #    whether a fresh ofile.txt appears within ~10ms. A zombie FEMM left
    #    behind by a failed prior solve will respond to that probe with a
    #    stale, queued error response from its PREVIOUS command (that's how
    #    we end up with the "attempt to call global `mo_getpointvalues` (a
    #    nil value) — flput(mo_getpointvalues(-X.XXX...))" error surfacing
    #    on the next run's very first mi_probdef call).
    #
    #    Since _kill_stale_femm_processes (called immediately before
    #    openfemm in _open_femm) already guarantees no FEMM/Wine process is
    #    alive and the file-link files have been wiped, it is ALWAYS safe
    #    to launch fresh on non-Windows. We replicate pyFEMM's launch path
    #    verbatim but skip the probe.
    original_openfemm = femm_module.openfemm

    def _resolve_winedir(winepath: str) -> str:
        if winepath:
            if os.path.isdir(winepath):
                return winepath
            if os.path.isfile(winepath):
                return re.sub("wine$", "", winepath)
            raise Exception(
                "Given path for wine does not exist. Please check 'winepath'."
            )
        env_paths = os.getenv("PATH", "").split(":")
        env_paths.extend(
            [
                "/usr/bin",
                "/usr/local/bin",
                "/opt/bin",
                "/opt/local/bin",
                "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin",
            ]
        )
        for k in env_paths:
            if os.path.exists(k + "/wine"):
                return k
        raise Exception(
            "Wine binary not found in default path. Please define a path "
            "as openfemm(winepath='path/to/wine/',femmpath='path/to/femm/')."
        )

    def _resolve_femmdir(femmpath: str) -> str:
        if femmpath:
            if os.path.isdir(femmpath):
                return femmpath
            if os.path.isfile(femmpath):
                return re.sub("femm.exe$", "", femmpath)
            raise Exception(
                "Given path for FEMM does not exist. Please check 'femmpath'."
            )
        home = os.path.expanduser("~")
        rootpaths = [
            home + "/.wine/drive_c/femm42/bin",
            home + "/.wine/drive_c/Program Files/femm42/bin",
            home + "/.wine/drive_c/Progra~1/femm42/bin",
        ]
        for k in rootpaths:
            if os.path.exists(k + "/femm.exe"):
                return k
        raise Exception(
            "FEMM binary not found in default path. Please define a path "
            "as openfemm(femmpath='path/to/femm/')."
        )

    def safe_openfemm(*arg, winepath: str = "", femmpath: str = ""):
        """Drop-in replacement for pyFEMM's openfemm that ALWAYS launches
        a fresh FEMM process on non-Windows.

        Rationale: pyFEMM's original openfemm probes for an existing FEMM
        by writing `flput(0)` to ifile.txt and checking ofile.txt. That probe
        is the root cause of the "mo_getpointvalues ghost response" failure
        pattern — see the detailed comment at the top of this patch.
        """
        if femm_module.windowsOS:
            return original_openfemm(*arg, winepath=winepath, femmpath=femmpath)

        _solve_trace(
            f"safe_openfemm: ALWAYS-FRESH launch path (skipping pyFEMM probe). "
            f"winepath={winepath!r} femmpath={femmpath!r} arg={arg!r}"
        )

        winedir = _resolve_winedir(winepath)
        femmdir = _resolve_femmdir(femmpath)
        _solve_trace(
            f"safe_openfemm: resolved winedir={winedir!r} femmdir={femmdir!r}"
        )

        ifile = femm_module.fixpath(femmdir + "/ifile.txt")
        ofile = femm_module.fixpath(femmdir + "/ofile.txt")

        # Wipe any stale file-link files. Our _kill_stale_femm_processes
        # normally does this first, but do it here too for defence in depth.
        for p in (ifile, ofile):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except OSError:
                pass

        # Set the pyFEMM module globals that callfemm needs.
        femm_module.ifile = ifile
        femm_module.ofile = ofile

        # Launch FEMM fresh. Same command as pyFEMM's openfemm at line 93 of
        # femm/__init__.py — the `&` detaches so we don't block here.
        #
        # MVK_CONFIG_LOG_LEVEL=1 suppresses MoltenVK's 150-line info dump
        # ("supported Vulkan extensions" + GPU details) that otherwise
        # appears once per Wine process — for a 4-worker parallel sweep
        # that's ~600 lines of pure noise interleaved with backend logs.
        # Level 1 keeps real errors visible. WINEDEBUG=fixme-all silences
        # Wine's own "fixme" stubs (e.g. winemenubuilder warnings) without
        # touching err: messages we'd actually want to see.
        wine_exe = femm_module.fixpath(os.path.join(winedir, "wine"))
        femm_exe = femm_module.fixpath(os.path.join(femmdir, "femm.exe"))
        launch_env = os.environ.copy()
        launch_env.update(
            {
                "MVK_CONFIG_LOG_LEVEL": "1",
                "WINEDEBUG": "fixme-all",
            }
        )
        _solve_trace(
            "safe_openfemm: launching — "
            f"MVK_CONFIG_LOG_LEVEL=1 WINEDEBUG=fixme-all {wine_exe} {femm_exe} -filelink"
        )
        subprocess.Popen(
            [wine_exe, femm_exe, "-filelink"],
            cwd=os.getcwd(),
            env=launch_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

        # Handshake: setcurrentdirectory will block in callfemm until FEMM
        # is up and responds. That is our readiness signal — no probe needed.
        _solve_trace(
            "safe_openfemm: handshake — callfemm(setcurrentdirectory) waiting "
            "for FEMM to come up"
        )
        femm_module.callfemm(
            "setcurrentdirectory("
            + femm_module.quote(femm_module.fixpath(os.getcwd()))
            + ")"
        )
        _solve_trace("safe_openfemm: handshake complete — FEMM is ready")

        # Mirror pyFEMM's window-visibility behaviour: show_flag==0 means
        # "show window", which requires a main_restore() after launch.
        if len(arg) == 0 or arg[0] == 0:
            femm_module.main_restore()

    femm_module.openfemm = safe_openfemm


# ── Process-wide FEMM serialization ──────────────────────────────────
# pyFEMM exposes a SINGLE module-global pyFEMM instance per Python
# process — `femm.ifile`, `femm.ofile`, etc. live on the module. Two
# concurrent callers (e.g. the field-preview auto-fetch racing with a
# user-triggered solve) stomp on each other's globals; whoever calls
# closefemm() last wipes the other's IPC pipe mid-call and the second
# call dies with "name 'ofile' is not defined." The fix is to acquire
# this lock around any block that touches FEMM (open/setup/draw/mesh/
# analyze/loadsolution/extract/close). Keep the wait short so stale
# preview work fails fast instead of making the UI look hung.
FEMM_PROCESS_LOCK = threading.RLock()
try:
    FEMM_PROCESS_LOCK_TIMEOUT_SEC = float(os.environ.get("OPENEM_FEMM_LOCK_TIMEOUT_SEC", "15"))
except ValueError:
    FEMM_PROCESS_LOCK_TIMEOUT_SEC = 15.0


class FEMMSolver(FEMMGeometryMixin, FEMMExtractionMixin, FEMMPostprocessMixin, Solver):
    """FEMM-based electromagnetic solver using pyFEMM.

    Sprint 3 implementation with:
    - Wine-compatible file paths (S2-01)
    - Incremental geometry: magnets + slots + winding current (S2-02)
    - Torque vs. angle rotor sweep with periodicity (S2-03)
    - Back-EMF from flux linkage derivative (S2-04)

    Methods are organized into mixins for maintainability:
    - FEMMGeometryMixin: Drawing motor geometry in FEMM
    - FEMMExtractionMixin: Extracting results from solved problems
    - FEMMPostprocessMixin: Waveform tiling, back-EMF, THD, efficiency
    """

    def __init__(self, femm_path: Optional[str] = None, debug_dir: Optional[str] = None):
        """Initialize FEMM solver.

        Args:
            femm_path: Optional path to FEMM installation
            debug_dir: Optional directory for debug artifacts (S4-06)
        """
        self.femm_path = femm_path
        self.femm_available = False
        self.wine_available = False
        self.debug_dir = debug_dir  # S4-06: Debug artifact capture
        self._stator_steel_material_name = "StatorSteel"
        self._rotor_steel_material_name = "RotorSteel"
        self._femm_install_info = {"path": femm_path}
        self._wine_install_info = {"path": None}
        self._solve_state_lock = threading.RLock()
        self._cancel_requested = False
        self._active_femm_session = None
        self._femm_session_open = False
        self._captured_femm_mesh: Optional[dict[str, Any]] = None  # Phase 2: FEMM mesh overlay
        self._linear_steel_mu_rel_override: Optional[float] = None
        self._loaded_steel_materials: dict[str, str] = {}
        self._electrical_steel_material_records: dict[str, dict[str, object]] = {}
        # Per-slot ampere-turn breakdown captured during the loaded sweep.
        # The summary keeps the first snapshot for backward compatibility;
        # slot_excitation_frames keeps every sweep angle for Compare.
        self._captured_slot_excitation: Optional[list[SlotExcitationContribution]] = None
        self._captured_slot_excitation_frames: list[SlotExcitationFrame] = []

        femm_info = check_femm_installation()
        self._femm_install_info = femm_info
        self.femm_available = femm_info["available"]

        if platform.system() != "Windows":
            wine_info = check_wine_installation()
            self._wine_install_info = wine_info
            self.wine_available = wine_info["available"]

        try:
            import femm  # noqa: F401
            self.femm_module = femm
            _patch_femm_filelink_race(self.femm_module)
        except ImportError:
            raise RuntimeError("pyFEMM not installed. Install with: pip install pyfemm")

    def _kill_stale_femm_processes(self, femm) -> None:
        """Nuke any leftover FEMM processes and stale file-link files before
        we start a new solve.

        Rationale: when a prior solve fails mid-IPC, pyFEMM's closefemm() can
        hang (it sends `quit()` and waits for a response file that never
        appears because FEMM is busy crashing). Even when close succeeds, a
        zombie `wine femm.exe` may still be alive or `ifile.txt`/`ofile.txt`
        may contain stale error responses on disk. On the next solve,
        pyFEMM's openfemm probe (writes `flput(0)`, checks if ofile.txt
        appears within 10ms) will see the stale ofile.txt and conclude
        'FEMM is already open' — but that FEMM is in a bad state and the
        FIRST command sent to it returns the PREVIOUS run's error string.
        That's how we end up calling `mi_probdef` and getting back a
        `mo_getpointvalues` error.

        This helper runs on every _open_femm call (non-Windows) to guarantee
        a clean slate. It is intentionally best-effort: failures here must
        not block a solve.
        """
        if platform.system() == "Windows":
            return

        if os.environ.get(_FEMM_PARALLEL_WORKER_ENV_VAR, "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            # Experimental Wine parallel mode gives each worker its own FEMM
            # bin-directory copy, so file-link IPC cleanup can be local. A
            # global pkill here would terminate sibling worker solves.
            femm_path = self.femm_path or self._femm_install_info.get("path")
            if femm_path:
                femm_dir = femm_path
                if os.path.isfile(femm_dir):
                    femm_dir = os.path.dirname(femm_dir)
                for name in ("ifile.txt", "ofile.txt"):
                    p = os.path.join(femm_dir, name)
                    if os.path.exists(p):
                        try:
                            os.unlink(p)
                            _solve_trace(
                                f"_kill_stale_femm_processes: worker-local removed stale {p}"
                            )
                        except OSError as exc:
                            _solve_trace(
                                f"_kill_stale_femm_processes: worker-local failed to remove {p}: {exc!r}"
                            )
            for attr in ("ifile", "ofile", "HandleToFEMM"):
                if hasattr(femm, attr):
                    try:
                        delattr(femm, attr)
                    except AttributeError:
                        pass
            return

        # 1) DISCOVER: ps-dump anything Wine/FEMM-related so we can see in
        # backend logs whether a zombie exists and what its argv looks
        # like. This is the ground-truth we use to diagnose when pkill
        # patterns miss the actual process name.
        try:
            ps_result = subprocess.run(
                ["ps", "ax", "-o", "pid,command"],
                capture_output=True,
                timeout=2.0,
                text=True,
            )
            matching_lines: list[str] = []
            for line in ps_result.stdout.splitlines():
                low = line.lower()
                if any(
                    needle in low
                    for needle in (
                        "femm.exe",
                        "femm42",
                        "filelink",
                        "winedevice",
                        "wineserver",
                        "wine-preloader",
                        "wine64-preloader",
                        "wine64",
                    )
                ):
                    # Skip grep/self matches
                    if "ps ax" in line or "grep" in line:
                        continue
                    matching_lines.append(line.strip())
            if matching_lines:
                _solve_trace(
                    "_kill_stale_femm_processes: pre-kill ps dump "
                    f"({len(matching_lines)} matches):"
                )
                for line in matching_lines:
                    _solve_trace(f"    {line}")
            else:
                _solve_trace(
                    "_kill_stale_femm_processes: pre-kill ps dump — "
                    "no FEMM/Wine processes found"
                )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            _solve_trace(f"_kill_stale_femm_processes: ps dump skipped ({exc!r})")
            matching_lines = []

        # 2) KILL: multiple strategies so we catch whatever name the
        # zombie is using. SIGKILL (-9) because SIGTERM can be ignored
        # by a process that's stuck in Wine's IPC layer.
        #
        # Patterns covered:
        # - femm.exe: direct Windows exe name
        # - femm42: FEMM install dir, present in argv
        # - filelink: Wine launches FEMM with `-filelink` arg
        # - winedevice/wineserver/preloader: Wine helper processes can hold
        #   stale FEMM IPC state even after the main femm.exe process exits
        # - wine.*femm: generic wine launcher with femm in argv
        kill_patterns = (
            "femm\\.exe",
            "femm42",
            "filelink",
            "wine.*femm",
            "winedevice",
            "wineserver",
            "wine-preloader",
            "wine64-preloader",
        )
        killed_any = False
        for pattern in kill_patterns:
            try:
                result = subprocess.run(
                    ["pkill", "-9", "-f", pattern],
                    capture_output=True,
                    timeout=2.0,
                )
                if result.returncode == 0:
                    _solve_trace(
                        f"_kill_stale_femm_processes: pkill -9 -f '{pattern}' killed match"
                    )
                    killed_any = True
            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                _solve_trace(
                    f"_kill_stale_femm_processes: pkill -9 -f '{pattern}' skipped ({exc!r})"
                )

        # 3) Kill-by-PID fallback: if we saw matches in ps but pkill -f
        # didn't catch them (can happen with Wine launcher name mangling),
        # SIGKILL each PID directly.
        if matching_lines and not killed_any:
            for line in matching_lines:
                parts = line.split(None, 1)
                if not parts:
                    continue
                try:
                    pid = int(parts[0])
                except ValueError:
                    continue
                try:
                    kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
                    os.kill(pid, kill_signal)
                    _solve_trace(
                        f"_kill_stale_femm_processes: SIGKILL pid={pid} "
                        f"(cmd={parts[1] if len(parts) > 1 else '?'})"
                    )
                except (ProcessLookupError, PermissionError) as exc:
                    _solve_trace(
                        f"_kill_stale_femm_processes: kill pid={pid} failed ({exc!r})"
                    )

        # Give the kernel a moment to reap the killed processes BEFORE we
        # clear the file-link files — otherwise a dying FEMM can still
        # race us and write a stale ofile.txt after our unlink.
        if killed_any or matching_lines:
            time.sleep(0.3)

        # 4) Delete stale file-link files on disk. pyFEMM's openfemm does
        # this too, but ONLY after it has resolved the femmdir — and the
        # probe race is between that unlink and the freshly-launched FEMM
        # writing its first ofile.txt. Deleting here (before the probe
        # runs) plus giving the OS a moment to flush makes the probe
        # deterministic. Log BOTH the existence and the deletion so we can
        # see in backend logs when a stale ofile.txt was present.
        femm_path = self.femm_path or self._femm_install_info.get("path")
        if femm_path:
            femm_dir = femm_path
            if os.path.isfile(femm_dir):
                femm_dir = os.path.dirname(femm_dir)
            for name in ("ifile.txt", "ofile.txt"):
                p = os.path.join(femm_dir, name)
                existed = os.path.exists(p)
                _solve_trace(
                    f"_kill_stale_femm_processes: {p} existed={existed}"
                )
                if existed:
                    try:
                        os.unlink(p)
                        _solve_trace(f"_kill_stale_femm_processes: removed stale {p}")
                    except OSError as exc:
                        _solve_trace(
                            f"_kill_stale_femm_processes: failed to remove {p}: {exc!r}"
                        )

        # 5) Strip any lingering file-link globals on the pyFEMM module. If
        # the last run exited mid-closefemm (e.g. quit() response never
        # arrived and the thread was killed by cancel), `ifile`/`ofile` may
        # still be set to a now-invalid path. openfemm will reassign them,
        # but clearing first prevents any callfemm racing with a stale value.
        for attr in ("ifile", "ofile", "HandleToFEMM"):
            if hasattr(femm, attr):
                try:
                    delattr(femm, attr)
                    _solve_trace(f"_kill_stale_femm_processes: cleared femm.{attr}")
                except AttributeError:
                    pass

        # 6) Brief settle so the OS flushes the file-system unlinks before
        # pyFEMM's probe writes `flput(0)` and polls for a response.
        time.sleep(0.1)

    def _open_femm(self, femm, show_window: bool) -> None:
        """Open FEMM using explicit Wine/FEMM paths when available.

        The repo's smoke tests are more reliable on macOS when pyFEMM gets the
        Homebrew Wine directory explicitly instead of guessing from PATH.
        Reuse that same startup pattern here so solver runs match the known-good
        automation path.

        Pre-condition (non-Windows): any prior FEMM process and stale
        `ifile.txt`/`ofile.txt` are cleared so pyFEMM's probe cannot mistake
        a zombie process for a live one.

        Post-condition (non-Windows): pyFEMM's module-level `ifile`/`ofile`
        globals MUST be set when this returns. If a previous failed solve
        wiped them via closefemm() and openfemm silently short-circuited for
        any reason, we raise a clear error here instead of letting callfemm
        explode later with an undecipherable NameError.
        """
        # Pre-flight: nuke any zombie FEMM process and stale file-link
        # files. This is the single most effective guard against the
        # "FEMM returns: attempt to call global `mo_getpointvalues`
        # (a nil value)" failure pattern where the first command after
        # openfemm inexplicably gets back the last call's error.
        self._kill_stale_femm_processes(femm)
        show_flag = 0 if show_window else 1
        _solve_trace(f"_open_femm: start show_window={show_window}, show_flag={show_flag}")
        if platform.system() == "Windows":
            # Initialize COM for this thread before calling into pyFEMM.
            # pyFEMM uses win32com.client.Dispatch("femm.ActiveFEMM") which
            # requires CoInitialize() on every thread that touches COM.
            # FastAPI routes run in a threadpool, so the main-thread COM
            # initialization pywin32 does at import time isn't enough — any
            # solve dispatched to a worker thread crashes with HRESULT
            # 0x800401F0 (CO_E_NOTINITIALIZED / "CoInitialize has not been
            # called"). Calling it here is safe to repeat: Windows ref-counts
            # per-thread, and threadpool worker lifetimes bound the refs.
            try:
                import pythoncom  # pywin32, pulled in by pyfemm
                pythoncom.CoInitialize()
                _solve_trace("_open_femm: pythoncom.CoInitialize() ok")
            except Exception as com_exc:  # pragma: no cover - Windows-only path
                _solve_trace(f"_open_femm: pythoncom.CoInitialize failed: {com_exc!r}")
            _solve_trace("_open_femm: platform=Windows, calling femm.openfemm(show_flag)")
            femm.openfemm(show_flag)
            _solve_trace("_open_femm: Windows openfemm returned — done")
            return

        open_kwargs = {}
        wine_path = self._wine_install_info.get("path")
        if wine_path:
            open_kwargs["winepath"] = os.path.dirname(wine_path)

        femm_path = self.femm_path or self._femm_install_info.get("path")
        if femm_path:
            open_kwargs["femmpath"] = femm_path

        _solve_trace(
            f"_open_femm: calling femm.openfemm(show_flag={show_flag}, "
            f"winepath={open_kwargs.get('winepath')}, "
            f"femmpath={open_kwargs.get('femmpath')})"
        )
        # Capture pyFEMM's 'FEMM is already open' stdout print by redirecting
        # during the openfemm call. That message tells us a zombie FEMM was
        # reused instead of a fresh launch — useful for triaging the
        # "mo_getpointvalues ghost response" class of bugs.
        _openfemm_stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(_openfemm_stdout):
                femm.openfemm(show_flag, **open_kwargs)
        finally:
            captured = _openfemm_stdout.getvalue()
            if captured.strip():
                # Re-emit to real stdout so existing log consumers see it,
                # and mirror into the trace stream for easy grep.
                print(captured, end="", flush=True)
                if "FEMM is already open" in captured:
                    _solve_trace(
                        "_open_femm: pyFEMM reported 'FEMM is already open' — "
                        "a zombie FEMM responded to the probe. Our kill step "
                        "did not catch it. Check the pre-kill ps dump above."
                    )
        _solve_trace(
            f"_open_femm: openfemm returned. "
            f"has_ifile={hasattr(femm, 'ifile')}, has_ofile={hasattr(femm, 'ofile')}, "
            f"ifile={getattr(femm, 'ifile', '<unset>')}, "
            f"ofile={getattr(femm, 'ofile', '<unset>')}"
        )

        # Post-condition: ifile/ofile globals must be set. If they aren't,
        # callfemm will raise NameError on the first command — fail fast
        # here with a useful message instead.
        if not hasattr(femm, "ifile") or not hasattr(femm, "ofile"):
            _solve_trace("_open_femm: POST-CONDITION FAILED — ifile/ofile missing")
            raise RuntimeError(
                "openfemm() returned without setting ifile/ofile module "
                "globals. pyFEMM's file-link path is not initialized. Check "
                f"FEMM install (femmpath={open_kwargs.get('femmpath')}) and "
                f"Wine (winepath={open_kwargs.get('winepath')}) — both need "
                "to resolve to valid binaries."
            )
        _solve_trace("_open_femm: post-condition passed — ifile/ofile set")

    def _register_active_femm_session(self, femm) -> None:
        with self._solve_state_lock:
            self._active_femm_session = femm
            self._femm_session_open = True
            self._cancel_requested = False

    def _clear_active_femm_session(self) -> None:
        with self._solve_state_lock:
            self._active_femm_session = None
            self._femm_session_open = False
            self._cancel_requested = False

    def _close_active_femm_session(self) -> None:
        with self._solve_state_lock:
            femm = self._active_femm_session
            session_open = self._femm_session_open

        if not femm or not session_open:
            _solve_trace(
                f"_close_active_femm_session: no-op (femm={bool(femm)}, "
                f"session_open={session_open})"
            )
            return

        _solve_trace("_close_active_femm_session: calling femm.closefemm()")
        try:
            femm.closefemm()
            _solve_trace("_close_active_femm_session: closefemm() returned cleanly")
        except Exception as exc:
            _solve_trace(f"_close_active_femm_session: closefemm() raised: {exc!r}")
            raise
        finally:
            with self._solve_state_lock:
                self._femm_session_open = False

    def _is_cancel_requested(self) -> bool:
        with self._solve_state_lock:
            return self._cancel_requested

    def _raise_if_cancel_requested(self) -> None:
        if self._is_cancel_requested():
            raise SolveCancelledError("Solve cancelled by user")

    def cancel_active_solve(self) -> None:
        with self._solve_state_lock:
            self._cancel_requested = True
            has_active_session = self._active_femm_session is not None and self._femm_session_open

        if not has_active_session:
            return

        try:
            self._close_active_femm_session()
            logger.info("[SOLVE] Cancel requested — closed active FEMM session")
        except Exception as exc:
            logger.warning(f"[SOLVE] Cancel requested but FEMM close failed: {exc}")

    # ── S4-06: Debug artifact capture methods ────────────────────────────

    def _setup_debug_dir(self):
        """Create debug directory if configured (S4-06)."""
        if self.debug_dir:
            Path(self.debug_dir).mkdir(parents=True, exist_ok=True)
            debug_log = Path(self.debug_dir) / "solver.log"
            handler = logging.FileHandler(debug_log)
            handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            logger.addHandler(handler)
            logger.info("[DEBUG] Capturing artifacts to " + str(self.debug_dir))

    def _capture_debug_artifact(self, fem_path: str, ans_path: str):
        """Copy .fem and .ans files to debug_dir (S4-06)."""
        if not self.debug_dir:
            return
        debug_path = Path(self.debug_dir)
        try:
            if os.path.exists(fem_path):
                import shutil
                shutil.copy(fem_path, debug_path / Path(fem_path).name)
                logger.info(f"[DEBUG] Captured .fem file: {Path(fem_path).name}")
            if os.path.exists(ans_path):
                import shutil
                shutil.copy(ans_path, debug_path / Path(ans_path).name)
                logger.info(f"[DEBUG] Captured .ans file: {Path(ans_path).name}")
        except Exception as e:
            logger.warning(f"[DEBUG] Failed to capture debug artifacts: {e}")

    def _load_steel_material(self, femm, material_key: str) -> str:
        """Load a nonlinear steel material into FEMM and return its FEMM name."""
        if material_key in self._loaded_steel_materials:
            return self._loaded_steel_materials[material_key]
        name = self._load_steel_material_uncached(femm, material_key)
        self._loaded_steel_materials[material_key] = name
        return name

    def _load_steel_material_uncached(self, femm, material_key: str) -> str:
        linear_mu_raw: float | str | None = self._linear_steel_mu_rel_override
        if linear_mu_raw is None:
            linear_mu_raw = os.environ.get("OPENEM_MAGNETO2D_LINEAR_STEEL_MU_REL")
        if linear_mu_raw:
            try:
                linear_mu = max(1.0, float(linear_mu_raw))
            except ValueError:
                raise RuntimeError(
                    "OPENEM_MAGNETO2D_LINEAR_STEEL_MU_REL must be numeric"
                ) from None
            material_name = f"coilEM_LinearSteel_mu{linear_mu:g}".replace(".", "p")
            femm.mi_addmaterial(material_name, linear_mu, linear_mu, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
            logger.info(
                f"[MAT] Loaded diagnostic linear steel {material_name} for {material_key}"
            )
            return material_name

        if material_key == "M350-50A":
            curve = load_electrical_steel_curve(material_key)
            material_name = f"coilEM_M350_50A_{curve.sha256[:12]}"
            initial_mu = 1.0
            for b_tesla, h_a_per_m in curve.points:
                if b_tesla > 0.0 and h_a_per_m > 0.0:
                    initial_mu = b_tesla / (4.0 * math.pi * 1e-7 * h_a_per_m)
                    break
            initial_mu = max(1.0, initial_mu)

            femm.mi_addmaterial(
                material_name,
                initial_mu,
                initial_mu,
                0,
                0,
                0,
                0,
                0,
                1,
                0,
                0,
                0,
                0,
                0,
            )
            for b_tesla, h_a_per_m in curve.points:
                femm.mi_addbhpoint(material_name, b_tesla, h_a_per_m)
            self._electrical_steel_material_records[material_key] = {
                **curve.preflight_record(consumer="femm"),
                "solver_material_name": material_name,
            }
            logger.info(
                "[MAT] Loaded checked-in nonlinear B-H curve for %s "
                "(%d points, SHA-256 %s)",
                material_key,
                len(curve.points),
                curve.sha256,
            )
            return material_name

        resolved_material_name = get_femm_steel_material_name(material_key)
        props = get_material_properties(material_key)
        if not resolved_material_name or not props:
            raise RuntimeError(f"Unknown steel material: {material_key}")
        material_name = resolved_material_name

        force_local_bh = os.environ.get("OPENEM_FEMM_FORCE_LOCAL_BH", "").strip() in {
            "1",
            "true",
            "TRUE",
            "yes",
            "YES",
        }

        if material_key in ("M19", "M27", "M36", "1018_steel") and not force_local_bh:
            femm.mi_getmaterial(material_name)
            logger.info(f"[MAT] Loaded FEMM library material {material_name} for {material_key}")
            return material_name

        if force_local_bh:
            material_name = f"coilEM_{material_key}_local"

        bh_curve = props.get("bh_curve", [])
        initial_mu = 1.0
        for b, h in bh_curve:
            if b > 0.0 and h > 0.0:
                initial_mu = b / (4.0 * math.pi * 1e-7 * h)
                break
        initial_mu = max(1.0, initial_mu)

        femm.mi_addmaterial(material_name, initial_mu, initial_mu, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
        for b_tesla, h_a_per_m in bh_curve:
            femm.mi_addbhpoint(material_name, b_tesla, h_a_per_m)
        logger.info(
            f"[MAT] Loaded local nonlinear B-H curve for {material_name} ({material_key}) "
            f"with initial mu_r={initial_mu:.1f}"
        )
        return material_name

    # ── S6-05: Solve cache directory helpers ─────────────────────────────

    def _cleanup_old_solve_caches(self, cache_base_dir: Path, keep_count: int = 3):
        """Delete old solve cache directories, keeping only the newest ones (S6-05).

        Args:
            cache_base_dir: Base directory containing timestamped solve cache directories
            keep_count: Number of recent cache directories to keep (default 3)
        """
        if not cache_base_dir.exists():
            return

        try:
            # List all subdirectories sorted by name (timestamps sort naturally)
            subdirs = sorted(
                [d for d in cache_base_dir.iterdir() if d.is_dir()],
                key=lambda p: p.name,
                reverse=True  # Newest first
            )

            # Delete directories beyond keep_count
            for old_dir in subdirs[keep_count:]:
                try:
                    shutil.rmtree(old_dir)
                    logger.info(f"[CACHE] Deleted old solve cache: {old_dir.name}")
                except Exception as e:
                    logger.warning(f"[CACHE] Failed to delete {old_dir.name}: {e}")
        except Exception as e:
            logger.warning(f"[CACHE] Error during cleanup of {cache_base_dir}: {e}")

    # ── Problem setup ────────────────────────────────────────────────────

    def _setup_problem(self, femm, config: MotorConfig, geom: MotorGeometry):
        """Create new FEMM document with problem definition and materials."""
        self._loaded_steel_materials = {}
        self._electrical_steel_material_records = {}
        femm.newdocument(0)  # magnetics
        femm.mi_probdef(
            0,  # static
            "millimeters",
            "planar",
            1e-8,
            config.stator.stack_length_mm,
        )
        solve_params = config.solve_params
        femm_density = (
            solve_params.mesh_density if solve_params and solve_params.mesh_density else "normal"
        ).lower()
        # Coarse is for quick validation. FEMM's smart mesh can refine far past
        # our relaxed block sizes, so disable it only for this preset.
        femm.mi_smartmesh(0 if femm_density == "coarse" else 1)

        # Add materials
        magnet_props = get_material_properties(config.materials.magnet_grade)

        # Stator/rotor steel — import nonlinear built-in FEMM materials where
        # available, otherwise create a local nonlinear B-H material.
        self._stator_steel_material_name = self._load_steel_material(femm, config.materials.stator_steel)
        self._rotor_steel_material_name = self._load_steel_material(femm, config.materials.rotor_steel)
        for material_key, record in self._electrical_steel_material_records.items():
            record["roles"] = sorted(
                role
                for role, configured_key in (
                    ("stator_steel", config.materials.stator_steel),
                    ("rotor_steel", config.materials.rotor_steel),
                )
                if configured_key == material_key
            )

        # Permanent magnet
        br_scale = _diagnostic_magnet_br_scale()
        Br = (magnet_props.get("remanence_T", 1.3) if magnet_props else 1.3) * br_scale
        mu_r = magnet_props.get("relative_permeability", 1.05) if magnet_props else 1.05
        # Hc = Br / (mu_r * mu_0) in A/m — FEMM expects A/m, NOT kA/m
        Hc = Br / (mu_r * 4 * math.pi * 1e-7)  # A/m
        tagged_log(
            f"[MAT] Magnet: Br={Br:.3f} T, mu_r={mu_r}, "
            f"Hc={Hc:.0f} A/m ({Hc/1000:.1f} kA/m), br_scale={br_scale:.4g}"
        )
        femm.mi_addmaterial("Magnet", mu_r, mu_r, Hc, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)

        # Per-magnet label aliases (cosmetic only — N1, S1, N2, S2, ...).
        # FEMM's post-processor shows the assigned material name as a block
        # label (View → Block Labels). Registering one alias per magnet with
        # identical (mu_r, Hc) gives per-pole text labels for visualization
        # without changing any physics — every magnet solves against the
        # same linear PM model. Stored on self so _draw_full_geometry can
        # pick the right alias per magnet in iteration order.
        self._magnet_label_names: list[str] = []
        n_idx = s_idx = 0
        for mag in geom.magnets:
            if getattr(mag, "side", None):
                name = f"Magnet_{mag.polarity}_{mag.pole_index + 1}_{str(mag.side).capitalize()}"
            elif mag.polarity == "N":
                n_idx += 1
                name = f"Magnet_N_{n_idx}"
            else:
                s_idx += 1
                name = f"Magnet_S_{s_idx}"
            femm.mi_addmaterial(name, mu_r, mu_r, Hc, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
            self._magnet_label_names.append(name)
        if self._magnet_label_names:
            tagged_log(f"[MAT] Per-magnet label aliases: {', '.join(self._magnet_label_names)}")

        # Default the pre-processor view to "show block label names" so that
        # when the saved .fem file is opened in the FEMM GUI, each magnet
        # renders its N1/S1/... alias next to the label dot without the user
        # having to toggle View → Block Labels. Cosmetic only; does not
        # affect the solve or any extracted quantity.
        try:
            femm.mi_shownames()
        except Exception as exc:
            tagged_log(f"[VIEW] mi_shownames() unsupported ({exc}); labels may be hidden by default")

        # Air
        femm.mi_addmaterial("Air", 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
        self._rotor_air_pocket_label_names: list[str] = []
        for pocket in geom.rotor_air_pockets:
            name = f"MagnetPocketAir_{pocket.pocket_index + 1}"
            femm.mi_addmaterial(name, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
            self._rotor_air_pocket_label_names.append(name)
        self._magnet_pocket_air_label_names: list[str] = []
        for mag in geom.magnets:
            if getattr(mag, "pocket_corners_mm", None) is None:
                self._magnet_pocket_air_label_names.append("Air")
                continue
            side = str(getattr(mag, "side", "") or "pocket").capitalize()
            name = f"MagnetPocketAir_{mag.pole_index + 1}_{side}"
            femm.mi_addmaterial(name, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
            self._magnet_pocket_air_label_names.append(name)

        # Coil material (copper, for winding slots)
        femm.mi_addmaterial("Coil", 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)

        # Boundary condition
        femm.mi_addboundprop("ZeroA", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    # ── Main solve method ────────────────────────────────────────────────

    def solve(
        self,
        config: MotorConfig,
        on_progress=None,
        solve_mesh_key: str | None = None,
    ) -> SolveResult:
        """Solve motor configuration using FEMM with rotor sweep.

        Pipeline: config → geometry → mesh → rotor sweep → extract results.
        Sweep exploits 8-pole symmetry: only 90 electrical degrees (45 mech).
        Combined loaded + zero-current solves for torque + back-EMF.

        Args:
            config: Motor configuration
            on_progress: Optional callback(position, total, torque_Nm, stage, elec_deg)
                         called after each step completes. stage is one of:
                         "torque_sweep", "flux_extraction", "noload_sweep".
        """

        # Acquire process-wide FEMM lock so we don't race a concurrent
        # mesh-preview / field-preview that's also touching the same
        # pyFEMM module globals (ifile/ofile). RLock so the same thread
        # can re-enter if any helper inside happens to also acquire.
        # We block here rather than fail-fast so the user's solve always
        # eventually runs once any background preview finishes.
        tagged_log("[FEMM] solve(): acquiring FEMM_PROCESS_LOCK...", flush=True)
        lock_wait_start = time.perf_counter()
        if not FEMM_PROCESS_LOCK.acquire(timeout=FEMM_PROCESS_LOCK_TIMEOUT_SEC):
            raise RuntimeError(
                "Timed out waiting for FEMM lock — another FEMM operation "
                f"held it for >{FEMM_PROCESS_LOCK_TIMEOUT_SEC:.0f}s"
            )
        _emit_femm_solver_timing(
            on_progress,
            "femm_lock_wait",
            "FEMM lock wait",
            (time.perf_counter() - lock_wait_start) * 1000.0,
        )
        tagged_log("[FEMM] solve(): FEMM_PROCESS_LOCK acquired", flush=True)
        previous_linear_steel_mu_rel = self._linear_steel_mu_rel_override
        self._linear_steel_mu_rel_override = (
            config.solve_params.linear_steel_mu_rel
            if config.solve_params is not None
            else None
        )
        try:
            return self._solve_locked(config, on_progress, solve_mesh_key)
        finally:
            self._linear_steel_mu_rel_override = previous_linear_steel_mu_rel
            FEMM_PROCESS_LOCK.release()
            tagged_log("[FEMM] solve(): FEMM_PROCESS_LOCK released", flush=True)

    def _solve_locked(
        self,
        config: MotorConfig,
        on_progress=None,
        solve_mesh_key: str | None = None,
    ) -> SolveResult:
        """Internal solve body — runs while holding FEMM_PROCESS_LOCK.

        The original FEMMSolver.solve body, factored out so the public
        solve() can wrap it in the process-wide lock without changing
        any of the existing pipeline.
        """

        setup_open_start = time.perf_counter()

        # S4-06: Setup debug directory if configured
        self._setup_debug_dir()

        # Phase 2: Reset FEMM mesh capture so re-run doesn't carry stale data
        self._captured_femm_mesh = None
        # Reset per-solve slot excitation snapshots — see __init__ docstring.
        self._captured_slot_excitation = None
        self._captured_slot_excitation_frames = []
        # Sprint 25: accumulate per-angle FEMM field-line frames so Compare /
        # saved snapshots can render flux lines + airgap |B| heatmap on the
        # FEMM side, not just the live-solve viewer. Frames are already
        # built per position and forwarded via SSE; we just keep a copy.
        self._captured_field_line_frames: list[dict[str, Any]] = []
        steel_b_rms_accumulator = new_steel_flux_density_rms_accumulator()

        # S6-02: Resolve selective solve options
        opts = config.solve_options or SolveOptionsConfig()

        start_time = time.time()
        debug_pause = os.environ.get("OPENEM_DEBUG_PAUSE", "").lower() in ("1", "true", "yes")

        # Check platform dependencies
        if platform.system() != "Windows" and not self.wine_available:
            platform_info = get_platform_info()
            hint = "Wine not found. FEMM on macOS/Linux requires Wine."
            if platform_info.get("is_apple_silicon"):
                hint += "\nApple Silicon: brew install --cask wine-stable && softwareupdate --install-rosetta"
            raise RuntimeError(hint)

        femm = self.femm_module
        geom = compute_geometry(config)
        self._last_geom = geom  # Store for use by _extract_torque
        self._last_rotor_offset_rad = 0.0  # Updated each solve position
        self._peak_flux_teeth = 0.0  # Set by _extract_flux_density
        self._peak_flux_yoke = 0.0

        # S6-05: Setup solve cache directory and retention policy
        solve_cache_base = Path.home() / ".openem" / "solve_cache"
        try:
            # Cleanup old cache directories: keep last 3, delete older ones
            self._cleanup_old_solve_caches(solve_cache_base, keep_count=3)
        except Exception as e:
            logger.warning(f"[CACHE] Cleanup failed (non-fatal): {e}")

        # Create timestamped cache directory for this solve
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
        solve_cache_dir: Optional[Path] = None
        try:
            candidate = solve_cache_base / timestamp
            candidate.mkdir(parents=True, exist_ok=True)
            solve_cache_dir = candidate
            logger.info(f"[CACHE] Created solve cache directory: {solve_cache_dir}")
        except Exception as e:
            logger.warning(f"[CACHE] Failed to create cache directory (solve will continue): {e}")

        # S2-01: Use Wine-compatible path for .fem file
        fem_path = get_wine_compatible_path("openem_solve.fem")

        # Sweep parameters from solve_params (user-configurable via quality presets)
        pole_pairs = config.rotor.pole_count // 2
        sp = config.solve_params
        rated_speed_rpm = sp.rated_speed_rpm if sp else 3000
        omega_elec_rad_s = 2.0 * math.pi * rated_speed_rpm / 60.0 * pole_pairs
        # Loaded FEMM policy:
        # - quick: short partial sweep for responsiveness
        # - standard/fine: full 360 electrical degrees so dashboard FFT bins
        #   reflect the real waveform instead of a tiled partial segment
        # - custom: honor the explicit configured range
        #
        # Special case: if the user is running a torque-only solve, prioritize a
        # fast-but-trustworthy harmonic check by solving one full electrical cycle
        # even on preset quick quality. Explicit custom fixtures are left alone
        # so QA harness overrides such as --rotor-sweep-deg 90 stay short.
        torque_only_validation = (
            opts.torque_sweep
            and not opts.back_emf
            and not opts.flux_density
            and not opts.cogging_torque
            and not opts.thd_analysis
        )
        custom_sweep_requested = sp is not None and sp.solve_quality == "custom"
        if torque_only_validation and not custom_sweep_requested:
            sweep_elec_deg = 360.0
        else:
            sweep_elec_deg = sp.effective_femm_loaded_sweep_range_deg() if sp else 60.0
        # Step size resolved from FEMM-specific quality policy so loaded full-
        # cycle parity runs stay practical in the UI.
        step_elec_deg = (
            sp.effective_femm_loaded_step_deg(
                torque_only_validation=torque_only_validation
            )
            if sp
            else 15.0
        )

        # Convert electrical degrees to mechanical degrees
        sweep_mech_deg = sweep_elec_deg / pole_pairs
        step_mech_deg = step_elec_deg / pole_pairs
        num_positions = max(2, int(round(sweep_mech_deg / step_mech_deg)) + 1)

        # When the sweep covers a full electrical period, the final position
        # lands at elec≈360° — physically identical to the 0° solution.
        # Keeping it has three downsides:
        #   1. FEMM re-solves the same problem for nothing (~30 s/position).
        #   2. The endpoint is one of the recurring Wine/pyFEMM
        #      mo_loadsolution flush-race dropout spots (observed on the
        #      8p12s 13:27 run).
        #   3. Downstream FFT (_fft_amplitudes in plot_loaded_solver_compare
        #      and similar) normalises by 2/N assuming canonical N-point
        #      periodic input [0°, step, …, (N-1)·step]. A trailing 360°
        #      duplicate makes that N+1 samples and biases all harmonic
        #      amplitudes by ~1/N.
        # Drop the terminal wrap-around sample so the sweep stays on the
        # half-open interval [0°, 360°). The retry wrapper at the extraction
        # call site handles mid-sweep dropouts; this deals with the endpoint
        # specifically by not solving it at all.
        full_cycle_sweep = sweep_elec_deg >= 360.0 - 1e-6
        if (
            full_cycle_sweep
            and num_positions >= 3
            and abs((num_positions - 1) * step_mech_deg - sweep_mech_deg) < 1e-6
        ):
            num_positions -= 1
            logger.info(
                "[SOLVE] Full-cycle sweep: dropped redundant elec=360° sample "
                "(identical to 0°); sweep now spans [0°, %.2f°) elec across "
                "%d positions",
                sweep_elec_deg,
                num_positions,
            )

        logger.info(
            f"[SOLVE] Quality={sp.solve_quality if sp else 'default'}, "
            f"step={step_elec_deg}° elec, positions={num_positions}"
        )

        mech_angles = [i * step_mech_deg for i in range(num_positions)]
        elec_angles_partial = [a * pole_pairs for a in mech_angles]

        noload_plan_angles: list[float] = []
        interleaved_noload_keys: set[int] = set()
        total_progress_positions = num_positions
        if opts.back_emf or opts.thd_analysis:
            noload_plan_angles = self._build_noload_sweep_angles(
                config,
                thd_analysis=opts.thd_analysis,
            )
            noload_plan_keys = {
                self._angle_bucket_key(angle_deg)
                for angle_deg in noload_plan_angles
            }
            loaded_covers_full_cycle = sweep_elec_deg >= 360.0 - 1e-6
            if loaded_covers_full_cycle:
                interleaved_noload_keys = {
                    self._angle_bucket_key(angle_deg)
                    for angle_deg in elec_angles_partial
                    if self._angle_bucket_key(angle_deg) in noload_plan_keys
                }
            else:
                interleaved_noload_keys = {
                    self._angle_bucket_key(angle_deg)
                    for angle_deg in elec_angles_partial
                }

            remaining_noload_positions = sum(
                1
                for angle_deg in noload_plan_angles
                if self._angle_bucket_key(angle_deg) not in interleaved_noload_keys
            )
            total_progress_positions += remaining_noload_positions

        # Results accumulators
        torque_loaded = []
        # Cogging torque is produced by a dedicated no-load sweep after the
        # loaded leg (see _run_cogging_sweep), not accumulated per loaded
        # position — it must run even when the loaded torque sweep is off.
        cogging_angles_full: list[float] = []
        cogging_full: list[float] = []
        energy_loaded: list[float] = []
        coenergy_loaded: list[float] = []
        # Per-position metadata for rotor angles where FEMM's loaded
        # torque extraction raised (_extract_torque → FEMMTorqueExtractionError).
        # These positions get math.nan entries in torque_loaded; downstream
        # consumers (QA postproc, parity FFT) use this list to distinguish
        # "FEMM dropped samples" from "real solver disagreement".
        loaded_torque_failed_positions: list[dict[str, Any]] = []
        flux_linkage_a = []
        flux_linkage_b = []
        flux_linkage_c = []
        noload_flux_linkage_samples: dict[int, tuple[float, float, float, float]] = {}
        flux_map = FluxDensityMap(nodes=[Node(x=0, y=0)], B_magnitude=[0.0])
        mesh_elements = 0
        mesh_captured_once = False  # Phase 2: Track whether we've captured FEMM mesh

        _solve_trace(
            f"solve: entering try block — num_positions={num_positions}, "
            f"torque_sweep={opts.torque_sweep}, back_emf={opts.back_emf}, "
            f"flux_density={opts.flux_density}, debug_pause={debug_pause}"
        )
        try:
            # Open FEMM once for entire sweep (avoid repeated open/close)
            # When debug_pause is on, show FEMM window so user can screenshot
            _solve_trace("solve: calling _open_femm")
            self._open_femm(femm, show_window=debug_pause)
            _solve_trace("solve: _open_femm returned; registering session")
            self._register_active_femm_session(femm)
            _emit_femm_solver_timing(
                on_progress,
                "femm_setup_open",
                "FEMM setup + open",
                (time.perf_counter() - setup_open_start) * 1000.0,
            )
            self._raise_if_cancel_requested()

            # Resolve serial vs parallel dispatch up front. When
            # femm_workers > 1 (and the platform supports it), spawn N FEMM
            # worker processes that each handle a chunk of rotor positions
            # and return PositionResult dataclasses; the main process then
            # aggregates them into the same accumulators the serial loop
            # would populate. FEMM mesh capture and no-load interleaving are
            # not produced by workers — see the femm_parallel module
            # docstring for the full list of parallel-mode trade-offs.
            # Workers do emit slim field frames so the live viewer can keep
            # showing flux lines.
            requested_workers = int(getattr(config.solve_params, "femm_workers", 1) or 1)
            effective_workers = _resolve_femm_workers_for_config(
                config,
                requested_workers,
            )
            # Cogging runs as its own dedicated no-load sweep after the loaded
            # leg (see the _run_cogging_sweep call below), so it composes with
            # both the serial and parallel loaded-sweep paths.
            if effective_workers > 1 and opts.torque_sweep:
                _solve_trace(
                    f"solve: dispatching parallel sweep "
                    f"(requested={requested_workers}, effective={effective_workers})"
                )
                tagged_log(
                    f"[SOLVE] FEMM parallel sweep: {num_positions} positions "
                    f"across {effective_workers} workers"
                )
                tagged_log(
                    "[SOLVE] Parallel mode skips FEMM mesh capture and "
                    "no-load interleaving during the loaded sweep. Slim "
                    "field-line frames are streamed as worker positions "
                    "complete; per-position field frames + airgap |B| "
                    "records remain captured for post-solve playback.",
                    level="WARNING",
                )
                # In parallel mode the per-position interleaved no-load probe
                # is skipped (workers can't share the noload_flux_linkage_samples
                # dict), so the post-loop _run_noload_sweep ends up covering
                # the *full* noload-plan angle set rather than just the
                # un-seeded subset. Recompute total_progress_positions to
                # reflect that — otherwise the UI shows e.g. "Position 29 / 24"
                # because the noload sweep emits 5 extra progress events
                # against a denominator that assumed they'd be interleaved.
                if (opts.back_emf or opts.thd_analysis) and noload_plan_angles:
                    total_progress_positions = num_positions + len(noload_plan_angles)
                    interleaved_noload_keys = set()  # don't re-seed in parallel
                    noload_flux_linkage_samples.clear()

                # Emit a "started" progress event so the frontend's elapsed
                # timer and position counter leave the initial 0 state. The
                # parallel dispatcher then blocks until all workers finish,
                # so without this the UI would show "ELAPSED 0s · POSITION 0
                # / N" for the entire ~2-min sweep before jumping to N/N.
                if on_progress is not None:
                    on_progress(
                        0,
                        total_progress_positions,
                        0.0,
                        "torque_sweep",
                    )

                completed_parallel_positions: set[int] = set()

                def _on_parallel_position_progress(event: dict[str, Any]) -> None:
                    if on_progress is None:
                        return
                    raw_pos_idx = event.get("pos_idx")
                    if raw_pos_idx is None:
                        return
                    try:
                        pos_idx = int(raw_pos_idx)
                    except Exception:
                        return
                    if pos_idx in completed_parallel_positions:
                        return
                    completed_parallel_positions.add(pos_idx)
                    torque_value = event.get("torque_nm")
                    torque_progress = (
                        float(torque_value)
                        if isinstance(torque_value, (int, float))
                        and math.isfinite(float(torque_value))
                        else None
                    )
                    elec_deg_value = event.get("elec_angle_deg")
                    elec_deg_progress = (
                        float(elec_deg_value)
                        if isinstance(elec_deg_value, (int, float))
                        and math.isfinite(float(elec_deg_value))
                        else None
                    )
                    field_line_frame = event.get("field_line_frame_dump")
                    if not isinstance(field_line_frame, dict):
                        field_line_frame = None
                    on_progress(
                        len(completed_parallel_positions),
                        total_progress_positions,
                        torque_progress,
                        "torque_sweep",
                        elec_deg_progress,
                        None,
                        None,
                        None,
                        field_line_frame,
                    )

                parallel_sweep_start = time.perf_counter()
                parallel_results = _solve_positions_parallel(
                    config=config,
                    geom=geom,
                    opts=opts,
                    mech_angles=list(mech_angles),
                    fem_path=fem_path,
                    workers=effective_workers,
                    femm_exe_path=(
                        self.femm_path or self._femm_install_info.get("path")
                    ),
                    solve_cache_dir=solve_cache_dir,
                    on_position_progress=(
                        _on_parallel_position_progress
                        if on_progress is not None
                        else None
                    ),
                )

                parallel_worker_elapsed_ms = (
                    time.perf_counter() - parallel_sweep_start
                ) * 1000.0
                parallel_timing_rows = _femm_parallel_critical_worker_timing_rows(
                    parallel_results,
                    parallel_worker_elapsed_ms,
                )
                if parallel_timing_rows:
                    for timing_key, timing_label, timing_elapsed_ms in parallel_timing_rows:
                        _emit_femm_solver_timing(
                            on_progress,
                            timing_key,
                            timing_label,
                            timing_elapsed_ms,
                        )
                else:
                    _emit_femm_solver_timing(
                        on_progress,
                        "femm_parallel_worker_solve",
                        "FEMM parallel worker solve",
                        parallel_worker_elapsed_ms,
                    )

                # Aggregate worker output into the same accumulators the
                # serial loop populates so downstream summary code (back-EMF
                # post-pass, SolveResult assembly) sees an identical shape.
                parallel_merge_start = time.perf_counter()
                for r in parallel_results:
                    torque_loaded.append(r.torque_nm)
                    energy_j = getattr(r, "energy_j", None)
                    coenergy_j = getattr(r, "coenergy_j", None)
                    if energy_j is not None and coenergy_j is not None:
                        energy_loaded.append(float(energy_j))
                        coenergy_loaded.append(float(coenergy_j))
                    flux_linkage_a.append(r.psi_a_wb)
                    flux_linkage_b.append(r.psi_b_wb)
                    flux_linkage_c.append(r.psi_c_wb)
                    if r.mesh_elements is not None and int(r.mesh_elements) > 0:
                        if r.pos_idx == 0 or mesh_elements <= 0:
                            mesh_elements = int(r.mesh_elements)
                    if r.failure is not None:
                        loaded_torque_failed_positions.append(r.failure)
                    # Sprint 25: parallel workers now emit slim per-position
                    # field frames — feed them into the same accumulator the
                    # serial path uses so SolveResult.field_line_frames
                    # populates on parallel runs too.
                    field_line_frame_dump = r.field_line_frame_dump
                    if field_line_frame_dump is not None:
                        self._captured_field_line_frames.append(field_line_frame_dump)
                    merge_steel_flux_density_rms_accumulator(
                        steel_b_rms_accumulator,
                        r.steel_b_rms_accumulator,
                    )
                    # Rebuild SlotExcitationFrame from the worker's pickled dict
                    # so Compare's slot heatmap has data on the FEMM side. Each
                    # worker called _build_slot_excitation_frame at its assigned
                    # angle and shipped the resulting dict back; we re-validate
                    # via SlotExcitationFrame(**dump) so the downstream code
                    # (which expects a Pydantic instance) sees the same shape
                    # the serial loop produces.
                    if r.slot_excitation_frame_dump is not None:
                        try:
                            slot_frame = SlotExcitationFrame(
                                **r.slot_excitation_frame_dump
                            )
                            self._captured_slot_excitation_frames.append(slot_frame)
                            if self._captured_slot_excitation is None:
                                self._captured_slot_excitation = list(
                                    slot_frame.contributions
                                )
                        except Exception as slot_exc:
                            logger.warning(
                                "[SOLVE] Parallel slot-excitation rebuild failed "
                                "at pos_idx=%d: %s",
                                r.pos_idx,
                                slot_exc,
                            )
                    if r.pos_idx == 0:
                        if r.peak_flux_teeth_t is not None:
                            self._peak_flux_teeth = r.peak_flux_teeth_t
                        if r.peak_flux_yoke_t is not None:
                            self._peak_flux_yoke = r.peak_flux_yoke_t
                        if r.flux_map_dump is not None:
                            try:
                                flux_map = FluxDensityMap.model_validate(
                                    r.flux_map_dump
                                )
                                if r.mesh_elements is not None:
                                    mesh_elements = int(r.mesh_elements)
                            except Exception as exc:
                                logger.warning(
                                    "[SOLVE] Parallel pos-0 flux map "
                                    "rehydration failed: %s",
                                    exc,
                                )

                _emit_femm_solver_timing(
                    on_progress,
                    "femm_parallel_result_merge",
                    "FEMM parallel result merge",
                    (time.perf_counter() - parallel_merge_start) * 1000.0,
                )

                if on_progress is not None:
                    # Emit a single coarse progress event so the SSE consumer
                    # advances past the loaded sweep even if the worker
                    # progress queue was unavailable or dropped a message.
                    on_progress(
                        num_positions,
                        total_progress_positions,
                        torque_loaded[-1] if torque_loaded else 0.0,
                        "torque_sweep",
                    )

                _solve_trace("solve: parallel sweep aggregated; skipping serial loop")
                # Fall through past the serial loop into the post-loop
                # work (flux density fallback, no-load sweep, etc.) which
                # all run in the main process as before.
            elif opts.torque_sweep:
                _solve_trace(f"solve: starting torque sweep loop ({num_positions} positions)")
                loaded_sweep_start = time.perf_counter()
                for pos_idx, mech_angle in enumerate(mech_angles):
                    _solve_trace(
                        f"solve: pos_idx={pos_idx} start "
                        f"(mech_angle={mech_angle:.3f}°, "
                        f"elec_angle={mech_angle * pole_pairs:.3f}°)"
                    )
                    self._raise_if_cancel_requested()
                    elec_angle = mech_angle * pole_pairs

                    # ── Loaded solve (torque + flux linkage for back-EMF) ────
                    _solve_trace(f"solve: pos_idx={pos_idx} _setup_problem (newdocument)")
                    self._setup_problem(femm, config, geom)  # calls newdocument(0)
                    self._last_rotor_offset_rad = math.radians(mech_angle)
                    _solve_trace(f"solve: pos_idx={pos_idx} _draw_full_geometry")
                    self._draw_full_geometry(femm, config, geom, rotor_offset_deg=mech_angle)
                    _solve_trace(f"solve: pos_idx={pos_idx} _apply_winding_current")
                    self._apply_winding_current(femm, config, geom, elec_angle)
                    _solve_trace(f"solve: pos_idx={pos_idx} _apply_boundary")
                    self._apply_boundary(femm, geom)

                    _solve_trace(f"solve: pos_idx={pos_idx} mi_saveas({fem_path})")
                    femm.mi_saveas(fem_path)

                    # S6-05: Copy .fem file to cache directory
                    if solve_cache_dir is not None:
                        try:
                            cache_filename = f"torque_pos{pos_idx}_{mech_angle:.1f}deg.fem"
                            cache_file_path = solve_cache_dir / cache_filename
                            shutil.copy2(fem_path, cache_file_path)
                        except Exception as e:
                            logger.warning(f"[CACHE] Failed to copy .fem file for position {pos_idx}: {e}")

                    # Debug pause: stop after first geometry so user can screenshot
                    if debug_pause and pos_idx == 0:
                        femm.mi_zoomnatural()  # Fit geometry to window
                        print("\n" + "=" * 60)
                        print("OPENEM_DEBUG_PAUSE: Motor geometry drawn in FEMM.")
                        print("Take your screenshot, then press ENTER to continue solving...")
                        print("=" * 60)
                        input()  # Block until user presses Enter in terminal

                    _solve_trace(f"solve: pos_idx={pos_idx} mi_createmesh")
                    femm.mi_createmesh()
                    _solve_trace(f"solve: pos_idx={pos_idx} mi_analyze")
                    femm.mi_analyze()
                    # Wine-flush race: on macOS/Wine, FEMM writes the .ans file
                    # asynchronously during analyze. If we call mi_loadsolution
                    # before Wine flushes, the postprocessor comes up empty and
                    # every downstream mo_* call raises "nil value". The sleep
                    # must come BEFORE loadsolution, not after it.
                    _solve_trace(f"solve: pos_idx={pos_idx} sleep(0.5) pre-loadsolution")
                    time.sleep(0.5)
                    _solve_trace(f"solve: pos_idx={pos_idx} mi_loadsolution")
                    femm.mi_loadsolution()
                    _solve_trace(f"solve: pos_idx={pos_idx} sleep(0.2) post-loadsolution")
                    time.sleep(0.2)  # Secondary settle after loadsolution

                    # Toggle post-processor block-label names on every rotor
                    # position — each mi_loadsolution opens a fresh post-
                    # processor view whose default state is names-hidden, so
                    # without re-toggling every position, labels only render
                    # on pos_idx == 0. Cheap + idempotent; fires per position.
                    try:
                        femm.mo_shownames()
                    except Exception as exc:
                        if pos_idx == 0:
                            tagged_log(f"[VIEW] mo_shownames() unsupported ({exc})")

                    # ── Postprocessor health probe (loaded sweep) ─────────
                    # If the .ans file never loaded, mo_numelements returns a
                    # Lua nil-value error. Surface it here with a clear error
                    # message instead of letting a downstream mo_getpointvalues
                    # be the visible failure point.
                    try:
                        num_elements, num_nodes = _femm_postprocessor_mesh_counts(
                            femm,
                            pos_idx=pos_idx,
                            mech_angle=mech_angle,
                            elec_angle=elec_angle,
                        )
                        mesh_elements = max(mesh_elements, num_elements)
                        tagged_log(f"[SOLVE] Position {pos_idx}: mesh={num_nodes} nodes, {num_elements} elements")
                    except Exception as probe_exc:
                        raise RuntimeError(
                            f"FEMM postprocessor failed to load at position {pos_idx} "
                            f"(mech_angle={mech_angle:.2f}°, elec_angle={elec_angle:.2f}°). "
                            f"mi_analyze or mi_loadsolution likely failed silently. "
                            f"Probe error: {probe_exc}"
                        ) from probe_exc

                    try:
                        slot_excitation_frame = SlotExcitationFrame(
                            **self._build_slot_excitation_frame(
                                femm,
                                config,
                                geom,
                                elec_angle,
                            )
                        )
                        self._captured_slot_excitation_frames.append(
                            slot_excitation_frame
                        )
                        if self._captured_slot_excitation is None:
                            self._captured_slot_excitation = list(slot_excitation_frame.contributions)
                        _solve_trace(
                            f"solve: FEMM slot excitation frame captured at pos_idx={pos_idx} "
                            f"({len(slot_excitation_frame.contributions)} slots)"
                        )
                    except Exception as slot_exc:
                        tagged_log(
                            f"[FEMM] !! Slot excitation capture failed at position "
                            f"{pos_idx}: {slot_exc}"
                        )

                    # ── Phase 2: Capture FEMM mesh on first solved position ────
                    # The triangulation is fixed for the entire sweep; only rotor
                    # block-rotation transform varies. Capture once to attach to
                    # SolveResult, enabling Analysis + Compare views to render the
                    # FEMM mesh overlay without a separate mesh-preview call.
                    #
                    # IMPORTANT: pass fem_path so _extract_mesh uses the disk
                    # fast path (~100ms parsing the .ans file). The mo_* IPC
                    # fallback iterates 24k+ nodes via Wine file-link round
                    # trips and burns ~240 SECONDS per position — and on top
                    # of that has historically failed with 'not enough values
                    # to unpack' on the first mo_getnode call. The disk path
                    # is both faster and more robust because it reads the .ans
                    # file directly instead of going through pyFEMM IPC.
                    #
                    # ALSO: set mesh_captured_once=True even on failure so we
                    # don't retry every position (the original bug — a 240s
                    # failure × 18 positions = 72 min of wasted compute).
                    if not mesh_captured_once:
                        try:
                            self._captured_femm_mesh = self._extract_mesh(
                                femm, fem_path=fem_path
                            )
                            _solve_trace(f"solve: FEMM mesh captured at pos_idx={pos_idx}")
                        except Exception as mesh_exc:
                            # Mesh capture is a UI-affordance, not a correctness
                            # requirement. Log the failure but continue the solve.
                            tagged_log(f"[FEMM] !! Mesh capture failed at position {pos_idx}: {mesh_exc}")
                            self._captured_femm_mesh = None
                        mesh_captured_once = True

                    # ── Compact live field frame for the Analysis viz ─────────
                    # Parse this position's .ans on the backend, convert the raw
                    # FEMM mesh into contour segments plus compact airgap Br/Bt
                    # bins, and stream only those processed artifacts. FEMM can
                    # retriangulate each rotor position, but repeating 20k+ nodes
                    # and 40k+ triangles through SSE is what crashed Chromium.
                    live_field_frame: dict[str, object] | None = None
                    try:
                        field_data = _read_femm_mesh_from_disk(fem_path)
                        if field_data and field_data.get("az_nodal"):
                            live_field_frame = _build_femm_live_field_payload(
                                field_data,
                                elec_angle_deg=elec_angle,
                                geom=geom,
                                include_raw_mesh=_should_stream_femm_raw_field_mesh(),
                                rotor_angle_mech_deg=mech_angle,
                            )
                            # Sprint 25: keep a copy for SolveResult.field_line_frames
                            # so saved snapshots / Compare have FEMM flux data.
                            # Drop the heavy per-frame mesh fields to keep the
                            # SolveResult JSON parseable in the browser. FEMM
                            # remeshes per position (~24k tris each) so the
                            # full payload is ~1.5 MB/frame × 36 positions =
                            # ~57 MB — enough to crash a Chrome tab on parse.
                            # contour_levels + angle_deg is what flux-line
                            # rendering on Compare actually consumes.
                            #
                            # Also pre-compute the airgap-only |B| records so
                            # the Compare airgap stat cards + trace chart can
                            # render on the FEMM side without the full mesh.
                            if live_field_frame is not None:
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
                                _air_count = len(airgap_records["b_magnitude_t"]) if airgap_records else 0
                                tagged_log(
                                    f"[FEMM-AIRGAP] pos={pos_idx} elec={elec_angle:.1f}deg "
                                    f"airgap_records={_air_count} "
                                    f"artifact={'yes' if airgap_artifact else 'no'}",
                                    flush=True,
                                )
                                full_field_frame_artifact = None
                                try:
                                    full_field_frame = (
                                        dict(live_field_frame)
                                        if live_field_frame.get("nodes_mm")
                                        and live_field_frame.get("triangles")
                                        and live_field_frame.get("element_b_mag_t")
                                        else _build_femm_live_field_payload(
                                            field_data,
                                            elec_angle_deg=elec_angle,
                                            geom=geom,
                                            include_raw_mesh=True,
                                            rotor_angle_mech_deg=mech_angle,
                                        )
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
                                        update_steel_flux_density_rms_accumulator(
                                            steel_b_rms_accumulator,
                                            full_field_frame,
                                        )
                                        full_field_frame_artifact = write_field_line_frame_artifact(
                                            full_field_frame,
                                            solve_cache_dir,
                                            pos_idx=pos_idx,
                                            elec_angle_deg=elec_angle,
                                            artifact_label="full_field_frame",
                                        )
                                except Exception as full_field_exc:
                                    tagged_log(
                                        f"[FEMM-FIELD] full field artifact failed pos={pos_idx}: {full_field_exc}",
                                        flush=True,
                                    )
                                captured_field_frame = {
                                    "angle_deg": live_field_frame.get("angle_deg", elec_angle),
                                    "contour_levels": live_field_frame.get("contour_levels", []),
                                    "az_min": live_field_frame.get("az_min"),
                                    "az_max": live_field_frame.get("az_max"),
                                    "n_pole_pitches": live_field_frame.get("n_pole_pitches"),
                                    "total_span_deg": live_field_frame.get("total_span_deg"),
                                    "airgap_brbt": airgap_profile,
                                    "airgap_b_stats": airgap_stats,
                                    "airgap_b_artifact": airgap_artifact,
                                    "airgap_b_records": display_airgap_records,
                                    "full_field_frame_artifact": full_field_frame_artifact,
                                    # Heavy fields intentionally omitted (nodes_mm,
                                    # triangles, regions, element_b_mag_t,
                                    # element_bx_t, element_by_t). The Pydantic
                                    # FieldLineFrameSnapshot model defaults them
                                    # to empty lists.
                                }
                                field_frame_artifact = write_field_line_frame_artifact(
                                    captured_field_frame,
                                    solve_cache_dir,
                                    pos_idx=pos_idx,
                                    elec_angle_deg=elec_angle,
                                )
                                if field_frame_artifact is not None:
                                    captured_field_frame["field_frame_artifact"] = field_frame_artifact
                                self._captured_field_line_frames.append(captured_field_frame)
                    except Exception as field_exc:
                        # Field viz is optional — failures must not abort the
                        # solve. Log + continue with torque-only progress.
                        tagged_log(
                            f"[FEMM] Live field frame failed at position "
                            f"{pos_idx}: {field_exc}"
                        )

                    # Diagnostic: confirm the payload headed over SSE is compact
                    # in normal GUI solves. Raw mesh arrays are diagnostic-only;
                    # the live UI should consume contours and airgap_brbt bins.
                    if live_field_frame is not None:
                        keys_present = sorted(live_field_frame.keys())
                        contours = live_field_frame.get("contour_levels")
                        airgap_brbt = live_field_frame.get("airgap_brbt")
                        raw_nodes = live_field_frame.get("nodes_mm")
                        raw_tris = live_field_frame.get("triangles")
                        contour_count = len(contours) if isinstance(contours, list) else 0
                        segment_count = sum(
                            len(level.get("segments_mm", []))
                            for level in (contours if isinstance(contours, list) else [])
                            if isinstance(level, dict)
                        )
                        airgap_bins = (
                            len(airgap_brbt.get("bins", []))
                            if isinstance(airgap_brbt, dict)
                            else 0
                        )
                        raw_nodes_count = len(raw_nodes) if isinstance(raw_nodes, list) else 0
                        raw_tris_count = len(raw_tris) if isinstance(raw_tris, list) else 0
                        tagged_log(
                            f"[FEMM] live_field_frame pos={pos_idx} "
                            f"keys={keys_present} "
                            f"contours={contour_count} segments={segment_count} "
                            f"airgap_bins={airgap_bins} "
                            f"raw_nodes={raw_nodes_count} raw_tris={raw_tris_count}"
                        )
                    else:
                        tagged_log(f"[FEMM] live_field_frame pos={pos_idx} is None")

                    # Extract torque via block integral on rotor regions.
                    # Failures are recorded as math.nan rather than 0.0 so
                    # downstream FFT/parity analysis can tell extractor
                    # dropouts apart from real solver disagreement. See
                    # FEMMTorqueExtractionError docstring for the
                    # 2026-04-20 false-alarm that motivated this.
                    #
                    # Retry-once wrapper: on Wine/macOS the .ans file flush
                    # after mi_analyze is asynchronous, so mo_blockintegral
                    # can come up empty on a subset of rotor positions even
                    # after the 0.5 s pre-loadsolution sleep above. Observed
                    # intermittently at θ_elec=40°, 220°, and the 360°
                    # wrap-around sample on 8p12s sweeps (see
                    # scripts/femm_dropout_probe.py for the reproducer). A
                    # single retry that closes the postprocessor, sleeps
                    # longer to let Wine flush, and re-issues
                    # mi_loadsolution recovers the vast majority of these
                    # without touching the mesh or re-analyzing. If the
                    # retry still fails we fall through to the NaN path
                    # unchanged — that signals a deterministic geometry
                    # issue, not a flush race.
                    torque = math.nan
                    try:
                        torque = self._extract_torque(femm)
                    except FEMMTorqueExtractionError as first_exc:
                        logger.warning(
                            "[SOLVE] Position %d: FEMM torque extraction failed on "
                            "first try (mech=%.2f°, elec=%.2f°); retrying after "
                            "postprocessor reload. %s",
                            pos_idx, mech_angle, elec_angle, first_exc,
                        )
                        try:
                            try:
                                femm.mo_close()
                            except Exception:
                                pass
                            # Longer settle than the 0.5 s pre-loadsolution
                            # sleep used on the first pass — gives Wine extra
                            # headroom to flush .ans before we re-open the
                            # postprocessor view.
                            time.sleep(1.5)
                            femm.mi_loadsolution()
                            time.sleep(0.5)
                            try:
                                femm.mo_shownames()
                            except Exception:
                                pass
                            torque = self._extract_torque(femm)
                            logger.info(
                                "[SOLVE] Position %d: retry recovered torque=%.4f Nm "
                                "(mech=%.2f°, elec=%.2f°)",
                                pos_idx, torque, mech_angle, elec_angle,
                            )
                        except FEMMTorqueExtractionError as retry_exc:
                            torque = math.nan
                            loaded_torque_failed_positions.append({
                                "position_index": pos_idx,
                                "mech_angle_deg": float(mech_angle),
                                "elec_angle_deg": float(elec_angle),
                                "error": str(retry_exc),
                                "retry_attempted": True,
                            })
                            logger.warning(
                                "[SOLVE] Position %d: FEMM torque extraction still "
                                "failed after retry (mech=%.2f°, elec=%.2f°); "
                                "recording NaN. %s",
                                pos_idx, mech_angle, elec_angle, retry_exc,
                            )
                    torque_loaded.append(torque)

                    try:
                        energy_j, coenergy_j = self._extract_energy_functionals(
                            femm,
                            config,
                            geom,
                        )
                    except Exception as energy_exc:
                        energy_j = math.nan
                        coenergy_j = math.nan
                        logger.warning(
                            "[SOLVE] Position %d: FEMM energy/coenergy extraction "
                            "failed (mech=%.2f°, elec=%.2f°); omitting FEMM "
                            "energy-FD torque from this solve. %s",
                            pos_idx,
                            mech_angle,
                            elec_angle,
                            energy_exc,
                        )
                    energy_loaded.append(energy_j)
                    coenergy_loaded.append(coenergy_j)

                    # Extract flux linkage per phase for back-EMF
                    psi_a, psi_b, psi_c = self._extract_flux_linkage(femm, config, geom)
                    flux_linkage_a.append(psi_a)
                    flux_linkage_b.append(psi_b)
                    flux_linkage_c.append(psi_c)
                    tagged_log(f"[SOLVE] Position {pos_idx}: torque={torque:.4f} Nm, "
                          f"psi_a={psi_a:.6f}, psi_b={psi_b:.6f}, psi_c={psi_c:.6f}")

                    # Extract flux density from the FIRST torque sweep position
                    # (where the solution is guaranteed to be loaded and working).
                    # This avoids the timing-sensitive separate solve that can fail
                    # on Wine when mo_getpointvalues returns empty/short responses.
                    #
                    # We run this regardless of `opts.flux_density` so the lightweight
                    # tooth/yoke peak samples (~84 mo_getpointvalues calls, sub-second)
                    # always populate `peak_flux_density_teeth_T` / `_yoke_T` for the
                    # Compare dashboard. Native FEM populates these as a side effect of
                    # its postprocess; previously FEMM only did so when the user opted
                    # in to the full flux-density map, which is why FEMM was rendering
                    # 0.000 T while Native showed real numbers in compare.
                    if pos_idx == 0:
                        flux_extraction_announced = on_progress is not None and opts.flux_density
                        if flux_extraction_announced:
                            on_progress(0, 1, 0.0, "flux_extraction")
                        sampled_flux = self._extract_flux_density(femm, geom)
                        if opts.flux_density:
                            flux_map = sampled_flux
                            mesh_elements, _ = _femm_postprocessor_mesh_counts(
                                femm,
                                pos_idx=pos_idx,
                                mech_angle=mech_angle,
                                elec_angle=elec_angle,
                            )
                        if flux_extraction_announced:
                            on_progress(1, 1, 0.0, "flux_extraction")
                        logger.info(f"[FLUX] In-sweep extraction: teeth={self._peak_flux_teeth:.3f} T, "
                                    f"yoke={self._peak_flux_yoke:.3f} T")

                    # Close the loaded solution before optionally seeding the
                    # no-load back-EMF solve at the same electrical angle.
                    try:
                        femm.mo_close()
                        femm.mi_close()
                    except Exception:
                        if self._is_cancel_requested():
                            raise SolveCancelledError("Solve cancelled by user") from None
                        raise

                    phase_a_live = None
                    phase_b_live = None
                    phase_c_live = None
                    sample_key = self._angle_bucket_key(elec_angle)
                    if (opts.back_emf or opts.thd_analysis) and sample_key in interleaved_noload_keys:
                        flux_a_noload, flux_b_noload, flux_c_noload = self._run_single_noload_position(
                            config,
                            geom,
                            femm,
                            elec_angle,
                            solve_cache_dir=solve_cache_dir,
                            cache_prefix=f"noload_seed_pos{pos_idx}",
                        )
                        noload_flux_linkage_samples[sample_key] = (
                            elec_angle,
                            flux_a_noload,
                            flux_b_noload,
                            flux_c_noload,
                        )
                        live_back_emf = self._estimate_live_back_emf_from_flux_linkage(
                            noload_flux_linkage_samples,
                            omega_elec_rad_s,
                            sample_key,
                        )
                        if live_back_emf is not None:
                            phase_a_live, phase_b_live, phase_c_live = live_back_emf

                    # Report progress after the loaded solve, optionally with a
                    # seeded no-load back-EMF sample at the same angle.
                    # live_field_frame (built above from this position's .ans)
                    # gets piped through to the SSE so the Analysis viewport
                    # animates flux lines + |B| heatmap as the sweep progresses
                    # — same UX the native magneto2d sweep provides.
                    if on_progress is not None:
                        on_progress(
                            pos_idx + 1,
                            total_progress_positions,
                            torque,
                            "torque_sweep",
                            elec_angle,
                            phase_a_live,
                            phase_b_live,
                            phase_c_live,
                            live_field_frame,
                        )

                _emit_femm_solver_timing(
                    on_progress,
                    "femm_loaded_sweep",
                    "FEMM loaded sweep",
                    (time.perf_counter() - loaded_sweep_start) * 1000.0,
                )
            else:
                logger.info("[SOLVE] Loaded torque sweep disabled via solve_options.torque_sweep")

            # ── Flux density fallback ────────────────────────────────
            # Primary extraction happens inside the torque sweep (pos 0).
            # Only run a separate solve if the in-sweep extraction failed
            # (both teeth and yoke still at 0.0) or flux_density was off.
            if not opts.flux_density:
                flux_map = FluxDensityMap(nodes=[Node(x=0, y=0)], B_magnitude=[0.0])
            elif self._peak_flux_teeth == 0.0 and self._peak_flux_yoke == 0.0:
                flux_fallback_start = time.perf_counter()
                self._raise_if_cancel_requested()
                logger.warning("[FLUX] In-sweep extraction returned 0 for both teeth and yoke — "
                               "retrying with dedicated solve and longer sleep")
                self._last_rotor_offset_rad = 0.0
                self._setup_problem(femm, config, geom)
                self._draw_full_geometry(femm, config, geom, rotor_offset_deg=0.0)
                self._apply_winding_current(femm, config, geom, 0.0)
                self._apply_boundary(femm, geom)
                femm.mi_saveas(fem_path)

                # S6-05: Copy .fem file to cache directory
                if solve_cache_dir is not None:
                    try:
                        cache_filename = "torque_pos_flux_density.fem"
                        cache_file_path = solve_cache_dir / cache_filename
                        shutil.copy2(fem_path, cache_file_path)
                    except Exception as e:
                        logger.warning(f"[CACHE] Failed to copy flux density .fem file: {e}")

                femm.mi_createmesh()
                femm.mi_analyze()
                # Wine-flush race: sleep BEFORE loadsolution so the .ans file
                # is on disk when FEMM tries to load it.
                time.sleep(1.0)
                femm.mi_loadsolution()
                time.sleep(0.3)

                # Show block-label names in the post-processor view (cosmetic).
                try:
                    femm.mo_shownames()
                except Exception as exc:
                    tagged_log(f"[VIEW] mo_shownames() unsupported ({exc})")

                # Postprocessor health probe before flux-density sampling.
                try:
                    _, _ = _femm_postprocessor_mesh_counts(femm)
                except Exception as probe_exc:
                    raise RuntimeError(
                        "FEMM postprocessor failed to load during flux-density "
                        f"fallback solve. Probe error: {probe_exc}"
                    ) from probe_exc

                flux_map = self._extract_flux_density(femm, geom)
                mesh_elements, _ = _femm_postprocessor_mesh_counts(femm)

                # Close flux extraction docs before no-load sweep
                femm.mo_close()
                femm.mi_close()
                logger.info(f"[FLUX] Fallback extraction: teeth={self._peak_flux_teeth:.3f} T, "
                            f"yoke={self._peak_flux_yoke:.3f} T")
                _emit_femm_solver_timing(
                    on_progress,
                    "femm_flux_fallback",
                    "FEMM flux fallback",
                    (time.perf_counter() - flux_fallback_start) * 1000.0,
                )

            # ── S4-01: No-load sweep for back-EMF with proper voltage scaling ───
            emf_angles = [0.0, 360.0]
            emf_a = [0.0, 0.0]
            emf_b = [0.0, 0.0]
            emf_c = [0.0, 0.0]
            emf_fundamental = 0.0
            emf_thd = None
            emf_harmonic_analysis = None

            if opts.back_emf or opts.thd_analysis:
                logger.info("[SOLVE] Running no-load back-EMF sweep (S4-01)")
                noload_sweep_start = time.perf_counter()
                noload_result = self._run_noload_sweep(
                    config, geom, femm, on_progress, solve_cache_dir,
                    thd_analysis=opts.thd_analysis,
                    seed_samples=noload_flux_linkage_samples,
                    progress_offset=num_positions,
                    progress_total=total_progress_positions,
                )
                self._raise_if_cancel_requested()
                emf_angles = noload_result["waveform"].electrical_angle_deg
                emf_a = noload_result["waveform"].phase_a_V
                emf_b = noload_result["waveform"].phase_b_V
                emf_c = noload_result["waveform"].phase_c_V
                emf_fundamental = noload_result["fundamental_V"]
                emf_thd = noload_result["thd_pct"]
                emf_harmonic_analysis = noload_result["harmonic_analysis"]
                _emit_femm_solver_timing(
                    on_progress,
                    "femm_noload_sweep",
                    "FEMM no-load sweep",
                    (time.perf_counter() - noload_sweep_start) * 1000.0,
                )

            # ── S4-02: Dedicated no-load cogging-torque sweep ──────────────
            # Runs whenever cogging is requested, independent of the loaded
            # torque sweep and back-EMF sweep — cogging is a pure no-load
            # quantity, so it must not be gated behind torque_sweep (that was
            # the regression where "cogging only" produced no samples). FEMM
            # is still open here from the main pipeline.
            if opts.cogging_torque:
                logger.info("[SOLVE] Running no-load cogging-torque sweep (S4-02)")
                cogging_sweep_start = time.perf_counter()
                cogging_result = self._run_cogging_sweep(
                    config,
                    geom,
                    femm,
                    on_progress,
                    solve_cache_dir,
                )
                self._raise_if_cancel_requested()
                cogging_angles_full = cogging_result["electrical_angle_deg"]
                cogging_full = cogging_result["torque_Nm"]
                _emit_femm_solver_timing(
                    on_progress,
                    "femm_cogging_sweep",
                    "FEMM cogging sweep",
                    (time.perf_counter() - cogging_sweep_start) * 1000.0,
                )

            # Close FEMM
            _solve_trace("solve: main pipeline complete — closing FEMM session")
            femm_teardown_start = time.perf_counter()
            self._close_active_femm_session()
            _emit_femm_solver_timing(
                on_progress,
                "femm_teardown",
                "FEMM teardown",
                (time.perf_counter() - femm_teardown_start) * 1000.0,
            )
            self._raise_if_cancel_requested()

        except SolveCancelledError:
            _solve_trace("solve: caught SolveCancelledError — closing and re-raising")
            try:
                self._close_active_femm_session()
            except Exception as close_exc:
                _solve_trace(f"solve: close during cancel raised (swallowed): {close_exc!r}")
            raise
        except Exception as e:
            tb = traceback.format_exc()
            _solve_trace(
                f"solve: caught Exception during solve: {type(e).__name__}: {e}\n"
                f"--- full traceback ---\n{tb}--- end traceback ---"
            )
            try:
                self._close_active_femm_session()
            except Exception as close_exc:
                _solve_trace(
                    f"solve: close during error path raised (swallowed): {close_exc!r}"
                )
            if self._is_cancel_requested():
                _solve_trace("solve: cancel was requested — raising SolveCancelledError")
                raise SolveCancelledError("Solve cancelled by user") from e
            wrapped = RuntimeError(f"FEMM solve failed: {str(e)}")
            _solve_trace(f"solve: raising wrapped RuntimeError: {wrapped}")
            raise wrapped from e
        finally:
            _solve_trace("solve: finally — clearing active FEMM session")
            self._clear_active_femm_session()

        result_packaging_start = time.perf_counter()

        # ── Prepare loaded waveform for reporting ────────────────────────
        energy_full: list[float] | None = None
        coenergy_full: list[float] | None = None
        torque_energy_fd_full: list[float] | None = None
        torque_coenergy_fd_full: list[float] | None = None
        avg_torque_energy_fd: float | None = None
        avg_torque_coenergy_fd: float | None = None
        if torque_loaded:
            tile_loaded_waveform = _tile_loaded_waveform_for_reporting(
                sp.solve_quality if sp else None,
                sweep_elec_deg,
            )
            if tile_loaded_waveform:
                angles_full, torque_full = self._tile_waveform(elec_angles_partial, torque_loaded, pole_pairs)
            else:
                angles_full = list(elec_angles_partial)
                torque_full = list(torque_loaded)
            if (
                len(energy_loaded) == len(torque_loaded)
                and len(coenergy_loaded) == len(torque_loaded)
                and all(math.isfinite(value) for value in energy_loaded)
                and all(math.isfinite(value) for value in coenergy_loaded)
            ):
                if tile_loaded_waveform:
                    _, candidate_energy = self._tile_waveform(elec_angles_partial, energy_loaded, pole_pairs)
                    _, candidate_coenergy = self._tile_waveform(elec_angles_partial, coenergy_loaded, pole_pairs)
                else:
                    candidate_energy = list(energy_loaded)
                    candidate_coenergy = list(coenergy_loaded)
                if len(candidate_energy) == len(angles_full) and len(candidate_coenergy) == len(angles_full):
                    energy_full = candidate_energy
                    coenergy_full = candidate_coenergy
                    if len(angles_full) >= 2:
                        step_elec_full = angles_full[1] - angles_full[0]
                    else:
                        step_elec_full = step_elec_deg
                    dtheta_mech = math.radians(step_elec_full / pole_pairs)
                    periodic_energy_fd = (
                        tile_loaded_waveform
                        and len(angles_full) >= 3
                        and abs(
                            (angles_full[-1] + step_elec_full)
                            - (angles_full[0] + 360.0)
                        )
                        <= max(1.0e-6, abs(step_elec_full) * 1.0e-6)
                    )
                    torque_energy_fd_full = [
                        -value
                        for value in _finite_difference_waveform(
                            energy_full,
                            dtheta_mech,
                            periodic=periodic_energy_fd,
                        )
                    ]
                    torque_coenergy_fd_full = _finite_difference_waveform(
                        coenergy_full,
                        dtheta_mech,
                        periodic=periodic_energy_fd,
                    )
                    avg_torque_energy_fd = float(np.mean(torque_energy_fd_full))
                    avg_torque_coenergy_fd = float(np.mean(torque_coenergy_fd_full))
            # FEMM torque-extractor dropouts are recorded as math.nan by the
            # sweep loop (see loaded_torque_failed_positions). Using plain
            # np.mean here would poison avg_torque with NaN, which then flows
            # through _estimate_efficiency → LossBreakdown, where Pydantic
            # rejects NaN at construction and crashes the whole solve before
            # the QA verdict ever gets a chance to inspect the dropouts.
            # nanmean computes from the surviving samples so the solve
            # completes; the verdict short-circuit in qa_runner/build_qa_report
            # is what turns "dropouts present" into a FAIL downstream.
            with np.errstate(all="ignore"):
                avg_torque = float(np.nanmean(torque_full))
                torque_max = float(np.nanmax(torque_full))
                torque_min = float(np.nanmin(torque_full))
            if not math.isfinite(avg_torque):
                # Every position dropped — no meaningful mean. Zero keeps
                # downstream Pydantic happy; the dropout count in the log
                # (below) and the NaN waveform itself are how the QA gate
                # detects this case.
                avg_torque = 0.0
                torque_max = 0.0
                torque_min = 0.0
            torque_ripple = 0.0
            if abs(avg_torque) > 1e-6 and math.isfinite(torque_max) and math.isfinite(torque_min):
                torque_ripple = float((torque_max - torque_min) / abs(avg_torque) * 100)
        else:
            angles_full = [0.0, 360.0]
            torque_full = [0.0, 0.0]
            avg_torque = 0.0
            torque_ripple = 0.0

        # Summarise FEMM torque-extractor dropouts. Logging here (rather than
        # only per-position above) gives a single grep-able line that names
        # the failure count in the QA subprocess log.
        if loaded_torque_failed_positions:
            n_failed = len(loaded_torque_failed_positions)
            n_total = len(torque_loaded) if torque_loaded else 0
            logger.warning(
                "[SOLVE] FEMM torque extraction dropped %d/%d rotor position(s); "
                "recorded as NaN and excluded from avg_torque. "
                "Downstream QA verdict will short-circuit to FAIL on these.",
                n_failed, n_total,
            )

        # Peak cogging torque (zero-to-peak amplitude). Filter NaN first — a
        # dropped cogging position records math.nan, and max(abs(...)) over a
        # NaN would poison cogging_torque_Nm (a finite float field that
        # Pydantic rejects as NaN, crashing SolveResult construction).
        finite_cogging = [c for c in cogging_full if math.isfinite(c)]
        avg_cogging = float(max(abs(c) for c in finite_cogging)) if finite_cogging else 0.0

        # Note: emf_fundamental and emf_thd already set from no-load sweep (S4-01)
        # (emf_a, emf_b, emf_c, emf_angles from no-load result)

        # Use per-ring maximums set by _extract_flux_density.
        # NOTE: These are 0.0 if the post-solve FEMM query returned no valid
        # samples (e.g. mofile not open after final solve). Do NOT fall back to
        # the airgap ring max — that creates physically-impossible values (>3 T
        # in steel) and was the source of the 26 T display bug.
        peak_flux_teeth = getattr(self, '_peak_flux_teeth', 0.0)
        peak_flux_yoke = getattr(self, '_peak_flux_yoke', 0.0)
        if peak_flux_teeth == 0.0 or peak_flux_yoke == 0.0:
            tagged_log("[FLUX] WARNING: steel flux density extraction returned 0 — "
                  "check mo_getpointvalues errors above. Displaying 0.0 (not an airgap artifact).")
        steel_b_rms = finalize_steel_flux_density_rms(steel_b_rms_accumulator)

        solve_time = time.time() - start_time

        # Compute loss breakdown and efficiency (S8-01)
        efficiency, loss_breakdown = self._estimate_efficiency(
            config, avg_torque, peak_flux_teeth, peak_flux_yoke
        )

        # Weight & inertia (S8-02)
        weight_inertia = self._compute_weight_inertia(config)

        # Torque-speed envelope (S8-03)
        ts_envelope = (
            self._compute_torque_speed_sweep(config, avg_torque)
            if opts.torque_speed_envelope
            else None
        )

        # Thermal estimate (S8-04)
        thermal_estimate = None
        if loss_breakdown is not None:
            thermal_estimate = self._compute_thermal_estimate(config, loss_breakdown)

        # Demagnetization check (S8-05 / S49-06 manual magnet temperature)
        demag_check = self._compute_demag_check(
            config,
            peak_flux_teeth,
            magnet_temperature_C=resolve_manual_magnet_temperature_C(config),
        )

        # Slot fill factor (S8-06)
        slot_fill_check = self._compute_slot_fill_check(config)

        kt_const, ke_const, lambda_pm_const = compute_machine_constants(
            avg_torque_Nm=avg_torque,
            current_amplitude_A=sp.current_amplitude_A if sp else None,
            back_emf_fundamental_V_rms_LN=emf_fundamental,
            rated_speed_rpm=sp.rated_speed_rpm if sp else None,
            pole_count=config.rotor.pole_count,
        )
        phase_current_waveform = None
        if sp is not None and sp.excitation_mode == "ideal_six_step_120":
            from backend.excitation import resolve_phase_current_sample

            phase_current_samples = [
                resolve_phase_current_sample(config, angle).phase_current_a
                for angle in angles_full
            ]
            phase_current_waveform = PhaseCurrentWaveform(
                electrical_angle_deg=angles_full,
                phase_a_A=[sample[0] for sample in phase_current_samples],
                phase_b_A=[sample[1] for sample in phase_current_samples],
                phase_c_A=[sample[2] for sample in phase_current_samples],
            )
            # The existing Kt label is explicitly peak-sinusoidal. Do not
            # silently reuse it for conducting-phase plateau current.
            kt_const = None

        metadata_mesh_elements = int(mesh_elements) if mesh_elements > 0 else 0
        if metadata_mesh_elements <= 0 and self._captured_femm_mesh is not None:
            try:
                metadata_mesh_elements = int(
                    self._captured_femm_mesh.get("num_triangles")
                    or len(self._captured_femm_mesh.get("triangles") or [])
                )
            except Exception:  # noqa: BLE001
                metadata_mesh_elements = 0
        if metadata_mesh_elements <= 0:
            logger.warning(
                "[SOLVE] FEMM mesh element count unavailable; falling back to "
                "legacy placeholder 5000."
            )
            metadata_mesh_elements = 5000

        result = SolveResult(
            summary=SolveSummary(
                avg_torque_Nm=avg_torque,
                avg_torque_energy_fd_Nm=avg_torque_energy_fd,
                avg_torque_coenergy_fd_Nm=avg_torque_coenergy_fd,
                torque_q_axis_Nm=torque_at_q_axis_nm(angles_full, torque_full),
                torque_ripple_pct=torque_ripple,
                cogging_torque_Nm=avg_cogging if opts.cogging_torque else None,
                back_emf_fundamental_V=emf_fundamental,
                back_emf_thd_pct=emf_thd,
                back_emf_thd_h6_pct=(
                    emf_harmonic_analysis.phase_a_thd_h6_pct
                    if emf_harmonic_analysis is not None
                    else None
                ),
                back_emf_thd_h12_pct=(
                    emf_harmonic_analysis.phase_a_thd_h12_pct
                    if emf_harmonic_analysis is not None
                    else None
                ),
                back_emf_thd_h24_pct=(
                    emf_harmonic_analysis.phase_a_thd_h24_pct
                    if emf_harmonic_analysis is not None
                    else None
                ),
                back_emf_line_thd_h12_pct=(
                    emf_harmonic_analysis.line_ab_thd_h12_pct
                    if emf_harmonic_analysis is not None
                    else None
                ),
                back_emf_line_thd_h24_pct=(
                    emf_harmonic_analysis.line_ab_thd_h24_pct
                    if emf_harmonic_analysis is not None
                    else None
                ),
                Kt_Nm_per_A=kt_const,
                Ke_Vs_per_rad_mech=ke_const,
                lambda_pm_Wb=lambda_pm_const,
                peak_flux_density_teeth_T=peak_flux_teeth,
                peak_flux_density_yoke_T=peak_flux_yoke,
                rms_flux_density_teeth_T=steel_b_rms.get("teeth"),
                rms_flux_density_yoke_T=steel_b_rms.get("yoke"),
                efficiency_pct=efficiency,
                loss_breakdown=loss_breakdown,
                weight_inertia=weight_inertia,
                torque_speed_envelope=ts_envelope,
                thermal_estimate=thermal_estimate,
                demag_check=demag_check,
                slot_fill_check=slot_fill_check,
                slot_excitation_contributions=self._captured_slot_excitation,
                solve_time_s=solve_time,
            ),
            torque_waveform=TorqueWaveform(
                electrical_angle_deg=angles_full,
                torque_Nm=torque_full,
                torque_energy_fd_Nm=torque_energy_fd_full,
                torque_coenergy_fd_Nm=torque_coenergy_fd_full,
                energy_potential_J=energy_full,
                energy_coenergy_J=coenergy_full,
            ),
            phase_current_waveform=phase_current_waveform,
            cogging_torque_waveform=(
                TorqueWaveform(
                    electrical_angle_deg=cogging_angles_full,
                    torque_Nm=cogging_full,
                )
                if opts.cogging_torque
                and cogging_full
                and len(cogging_full) == len(cogging_angles_full)
                and len(cogging_full) >= 2
                else None
            ),
            back_emf_waveform=BackEMFWaveform(
                electrical_angle_deg=emf_angles,
                phase_a_V=emf_a,
                phase_b_V=emf_b,
                phase_c_V=emf_c,
                **(
                    {
                        "line_ab_V": [a - b for a, b in zip(emf_a, emf_b)],
                        "line_bc_V": [b - c for b, c in zip(emf_b, emf_c)],
                        "line_ca_V": [c - a for c, a in zip(emf_c, emf_a)],
                    }
                    if sp is not None and sp.excitation_mode == "ideal_six_step_120"
                    else {}
                ),
            ),
            back_emf_harmonic_analysis=emf_harmonic_analysis,
            flux_density_map=flux_map,
            slot_excitation_frames=self._captured_slot_excitation_frames or None,
            field_line_frames=(
                # Sprint 25: per-angle FEMM frames for Compare's solver-vs-solver
                # field-line + airgap |B| panel. Each entry already carries
                # angle_deg + nodes_mm + triangles + regions + element_b_*; the
                # Pydantic FieldLineFrame model accepts the dict shape.
                [FieldLineFrame(**frame) for frame in self._captured_field_line_frames]
                if self._captured_field_line_frames
                else None
            ),
            femm_mesh=(
                # Phase 2: Build FemmMeshSummary from captured mesh if available
                FemmMeshSummary(
                    nodes_mm=self._captured_femm_mesh["nodes_mm"],
                    triangles=self._captured_femm_mesh["triangles"],
                    num_nodes=self._captured_femm_mesh["num_nodes"],
                    num_triangles=self._captured_femm_mesh["num_triangles"],
                )
                if self._captured_femm_mesh is not None
                else None
            ),
            solve_metadata=SolveMetadata(
                solver_name="femm-pyfemm-2.0",
                mesh_element_count=max(100, metadata_mesh_elements),
                rotor_positions=len(torque_full),
                timestamp=datetime.utcnow(),
                current_amplitude_A=sp.current_amplitude_A if sp else None,
                excitation_mode=(
                    sp.excitation_mode
                    if sp is not None and sp.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                current_amplitude_convention=(
                    sp.current_amplitude_convention
                    if sp is not None and sp.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                commutation_advance_deg=(
                    sp.commutation_advance_deg
                    if sp is not None and sp.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                phase_connection=(
                    sp.phase_connection
                    if sp is not None and sp.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                excitation_convention_version=(
                    "openem.bldc_six_step/v1"
                    if sp is not None and sp.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                loaded_cycle_complete=(
                    is_uniform_full_cycle_grid(angles_full)
                    if sp is not None and sp.excitation_mode == "ideal_six_step_120"
                    else None
                ),
                rated_speed_rpm=sp.rated_speed_rpm if sp else None,
                motor_input_dc_bus_V=sp.motor_input_dc_bus_V if sp else None,
                solve_cache_dir=str(solve_cache_dir) if solve_cache_dir is not None else None,
                solve_time_s=solve_time,
                mesh_density=getattr(sp, "mesh_density", None) if sp else None,
                mesh_source=getattr(sp, "mesh_source", None) if sp else None,
                rotor_rotation_model=getattr(sp, "rotor_rotation_model", None) if sp else None,
                # FEMM torque extraction selects the rotor blocks and calls
                # mo_blockintegral(22), FEMM's weighted-stress-tensor torque.
                # Do not echo solve_params.torque_method here; that option is
                # a Magneto2D postprocess selector and defaults to contour.
                torque_method="weighted_stress",
                topology=config.topology,
                physics_contract_version=None,
                region_source="native_generated_mesh",
                current_source="native_generated_mesh",
                magnetization_source="native_generated_mesh",
            ),
        )
        _emit_femm_solver_timing(
            on_progress,
            "femm_result_packaging",
            "FEMM result packaging",
            (time.perf_counter() - result_packaging_start) * 1000.0,
        )
        return result




# Sprint 27 Track 1F Phase 1: streaming/payload helpers were lifted into a
# sibling module. Re-export so existing call sites importing them via
# `from backend.femm_solver import _build_femm_live_field_payload` etc. work.
from backend.femm_solver.streaming import (  # noqa: E402, F401
    _airgap_b_records_from_frame,
    _airgap_point_records_from_open_solution,
    _build_femm_airgap_brbt_profile,
    _build_femm_live_field_payload,
    _classify_femm_triangles_by_centroid,
    _normalize_signed_angle,
    _pack_femm_live_contours,
    _pack_femm_live_float,
    _pack_femm_live_float_list,
    _pack_femm_live_segment,
)


def run_femm_mesh_preview(
    config: MotorConfig,
    *,
    rotor_angle_mech_deg: float = 0.0,
) -> dict[str, Any]:
    """Generate a FEMM mesh preview (mesh geometry only, no field solve).

    Lifecycle: instantiate FEMMSolver → open FEMM → compute geometry →
    setup problem → draw geometry → create mesh → extract mesh → teardown.

    Returns: dict with keys matching MeshPreviewData shape:
    - config_summary: topology, slots, poles, dimensions
    - mesh_info: num_nodes, num_triangles, pole_pitch_deg, etc.
    - nodes_mm: list of [x, y] coordinates in mm
    - triangles: list of [i, j, k] node indices (0-based)
    - generation_time_ms: milliseconds to generate mesh

    Raises: RuntimeError if FEMM setup or mesh creation fails.
    """
    start_time = time.time()
    tagged_log(
        f"[FEMM] mesh-preview start · topology={config.topology} "
        f"· rotor_angle={rotor_angle_mech_deg:.6g}deg mech",
        flush=True,
    )

    # Serialize against any other in-flight FEMM work in this process.
    # See FEMM_PROCESS_LOCK comment for why.
    tagged_log("[FEMM] mesh-preview: acquiring FEMM_PROCESS_LOCK...", flush=True)
    if not FEMM_PROCESS_LOCK.acquire(timeout=FEMM_PROCESS_LOCK_TIMEOUT_SEC):
        raise RuntimeError(
            "Timed out waiting for FEMM lock — another FEMM operation is "
            f"holding it for >{FEMM_PROCESS_LOCK_TIMEOUT_SEC:.0f}s"
        )
    tagged_log("[FEMM] mesh-preview: FEMM_PROCESS_LOCK acquired", flush=True)

    solver = FEMMSolver()
    # _open_femm operates on solver.femm_module (the pyFEMM module imported
    # in __init__) — it returns None. Bind a local `femm` to the module so
    # the rest of this function can call FEMM API methods on it directly,
    # mirroring how solve() at line 1016 keeps a local handle.
    femm = solver.femm_module
    opened = False

    try:
        # Check availability
        if not solver.femm_available:
            raise RuntimeError("FEMM is not available on this host")
        if platform.system() != "Windows" and not solver.wine_available:
            raise RuntimeError("FEMM on macOS/Linux requires Wine")

        # Open FEMM (hidden window). Side effect: launches Wine + femm.exe
        # and primes pyFEMM's filelink globals on the module.
        solver._open_femm(femm, show_window=False)
        opened = True

        # Compute geometry and draw
        geom = compute_geometry(config)
        solver._last_geom = geom

        solver._setup_problem(femm, config, geom)
        solver._last_rotor_offset_rad = math.radians(rotor_angle_mech_deg)
        solver._draw_full_geometry(
            femm,
            config,
            geom,
            rotor_offset_deg=rotor_angle_mech_deg,
        )

        # Apply winding current at the matching electrical angle. Even
        # though we don't care about the field solution here, mi_analyze()
        # silently produces no .ans file when the FEMM circuits are
        # undefined — and without an .ans file, mo_loadsolution +
        # mo_numnodes/mo_getnode all fail with "No magnetics output in
        # focus." Mirrors solve() at line 1248 (pos_idx=0 path).
        pole_pairs = max(1, config.rotor.pole_count // 2)
        rotor_angle_elec_deg = rotor_angle_mech_deg * pole_pairs
        solver._apply_winding_current(femm, config, geom, rotor_angle_elec_deg)

        # Apply boundary conditions (needed before mesh)
        solver._apply_boundary(femm, geom)

        # Save file. get_wine_compatible_path takes a filename string and
        # returns the absolute path FEMM expects (under ~/.wine/drive_c on
        # macOS/Linux, %TEMP%/openem on Windows). Mirrors solve() at line
        # 1085 — don't reinvent with tempfile.TemporaryDirectory; that
        # produces paths Wine can't reach without Z:-drive translation
        # gymnastics, AND passing a Path object into the helper's internal
        # str-concat ("C:\\openem_tmp\\" + filename) raises a PosixPath
        # TypeError.
        fem_path = get_wine_compatible_path("openem_femm_mesh.fem")
        femm.mi_saveas(fem_path)

        # Create mesh
        _solve_trace("mesh-preview: mi_createmesh")
        femm.mi_createmesh()

        # Analyze and load solution so mo_* functions work
        _solve_trace("mesh-preview: mi_analyze")
        femm.mi_analyze()
        time.sleep(1.0)

        _solve_trace("mesh-preview: mi_loadsolution")
        femm.mi_loadsolution()
        time.sleep(0.3)

        # Extract mesh — pass fem_path so the extractor uses the disk
        # fast path (parses .nod/.ele files written by mi_createmesh)
        # instead of N×Wine-IPC mo_getnode round-trips. 50k nodes × ~1ms
        # IPC = 50s vs ~100ms file parse.
        mesh_dict = solver._extract_mesh(femm, fem_path=fem_path)

        # Classify each triangle into a region tag the frontend's
        # MotorViewport understands (airgap / inter_pole_gap / rotor_core /
        # magnet / shaft / stator_yoke / stator_tooth / slot_winding).
        # Without these the FEMM mesh renders without the white airgap and
        # inter-pole shading the native FEM mesh shows. The disk extractor also
        # preserves FEMM block-label metadata when the .fem/.ans pair exposes it.
        regions = _classify_femm_triangles_by_centroid(
            mesh_dict["nodes_mm"],
            mesh_dict["triangles"],
            geom,
            rotor_angle_mech_deg=rotor_angle_mech_deg,
        )

        # Build config_summary
        config_summary = {
            "topology": config.topology,
            "slots": config.stator.slot_count,
            "poles": config.rotor.pole_count,
            "stator_od_mm": config.stator.OD_mm,
            "rotor_od_mm": config.rotor.OD_mm,
            "magnet_thickness_mm": config.rotor.magnet_thickness_mm,
            "stack_length_mm": config.stator.stack_length_mm,
            "rotor_angle_mech_deg": rotor_angle_mech_deg,
            "rotor_angle_elec_deg": rotor_angle_elec_deg,
        }

        # Build mesh_info
        pole_pitch_deg = 360.0 / config.rotor.pole_count
        # FEMM mesh preview draws the complete mechanical machine, not a
        # periodic half-model. Keep this metadata physical so field charts and
        # mesh labels show the same 360° span the user sees.
        n_pole_pitches = config.rotor.pole_count
        total_span_deg = 360.0

        mesh_info = {
            "num_nodes": mesh_dict["num_nodes"],
            "num_triangles": mesh_dict["num_triangles"],
            "pole_pitch_deg": pole_pitch_deg,
            "n_pole_pitches": n_pole_pitches,
            "total_span_deg": total_span_deg,
            "rotor_angle_mech_deg": rotor_angle_mech_deg,
            "rotor_angle_elec_deg": rotor_angle_elec_deg,
            "mesh_density": f"femm_{getattr(config.solve_params, 'mesh_density', 'normal')}",
            "mesh_source": "femm",
        }

        generation_time_ms = int((time.time() - start_time) * 1000)

        result = {
            "config_summary": config_summary,
            "mesh_info": mesh_info,
            "nodes_mm": mesh_dict["nodes_mm"],
            "triangles": mesh_dict["triangles"],
            "regions": regions,
            "n_pole_pitches": n_pole_pitches,
            "total_span_deg": total_span_deg,
            "generation_time_ms": generation_time_ms,
        }
        for key in (
            "element_labels",
            "element_groups",
            "element_label_names",
            "element_magnetization_angles_deg",
            "element_current_density_a_per_m2",
        ):
            if key in mesh_dict:
                result[key] = mesh_dict[key]

        tagged_log(
            f"[FEMM] mesh-preview complete · {mesh_dict['num_nodes']} nodes, "
            f"{mesh_dict['num_triangles']} triangles · {generation_time_ms} ms"
        )
        return result

    except Exception as e:
        tagged_log(f"[FEMM] !! mesh-preview FAILED: {e}")
        raise RuntimeError(f"FEMM mesh preview failed: {e}") from e
    finally:
        if opened:
            # In Wine file-link mode, graceful mo_close/mi_close responses can
            # arrive late and poison the next FEMM command. Mesh preview opens a
            # fresh FEMM process every time, so a direct quit is cleaner here.
            try:
                femm.closefemm()
            except Exception as close_exc:
                tagged_log(f"[FEMM] Warning: closefemm raised: {close_exc}")
        FEMM_PROCESS_LOCK.release()
        tagged_log("[FEMM] mesh-preview: FEMM_PROCESS_LOCK released", flush=True)


def run_femm_field_preview(config: MotorConfig) -> dict[str, Any]:
    """Generate a FEMM field preview (flux lines + per-element |B|, Bx, By).

    Same FEMM lifecycle as ``run_femm_mesh_preview`` — open / setup /
    draw / currents / boundary / mesh / analyze / loadsolution — then
    parses the .ans file once for nodes + triangles + per-node A_z and
    derives the field plot via ``backend.field_lines``. No additional
    Wine IPC after the analyze.

    Returns a dict matching the magneto2d FieldLinePlot envelope so the
    frontend's field-line + |B| heatmap renderer consumes it without
    any code changes.

    Excitation: uses whatever ``config.solve_params.current_amplitude_A``
    is set to, applied at electrical angle 0 (same as mesh-preview). For
    SPM at no-load, the dominant signal is the PM field; loaded plots
    add the armature reaction.
    """
    from backend.field_lines import build_field_line_plot_from_mesh

    start_time = time.time()
    tagged_log(
        f"[FEMM] field-preview start · topology={config.topology}",
        flush=True,
    )

    tagged_log("[FEMM] field-preview: acquiring FEMM_PROCESS_LOCK...", flush=True)
    if not FEMM_PROCESS_LOCK.acquire(timeout=FEMM_PROCESS_LOCK_TIMEOUT_SEC):
        raise RuntimeError(
            "Timed out waiting for FEMM lock — another FEMM operation is "
            f"holding it for >{FEMM_PROCESS_LOCK_TIMEOUT_SEC:.0f}s"
        )
    tagged_log("[FEMM] field-preview: FEMM_PROCESS_LOCK acquired", flush=True)

    solver = FEMMSolver()
    femm = solver.femm_module
    opened = False

    try:
        if not solver.femm_available:
            raise RuntimeError("FEMM is not available on this host")
        if platform.system() != "Windows" and not solver.wine_available:
            raise RuntimeError("FEMM on macOS/Linux requires Wine")

        solver._open_femm(femm, show_window=False)
        opened = True

        geom = compute_geometry(config)
        solver._last_geom = geom
        solver._setup_problem(femm, config, geom)
        solver._draw_full_geometry(femm, config, geom, rotor_offset_deg=0.0)
        solver._last_rotor_offset_rad = 0.0
        solver._apply_winding_current(femm, config, geom, 0.0)
        solver._apply_boundary(femm, geom)

        fem_path = get_wine_compatible_path("openem_femm_field.fem")
        femm.mi_saveas(fem_path)

        _solve_trace("field-preview: mi_createmesh")
        femm.mi_createmesh()
        _solve_trace("field-preview: mi_analyze")
        femm.mi_analyze()
        time.sleep(1.0)
        _solve_trace("field-preview: mi_loadsolution")
        femm.mi_loadsolution()
        time.sleep(0.3)

        # Disk-parse the .ans for nodes + triangles + Az in one pass.
        # _extract_mesh routes through _read_femm_mesh_from_disk which
        # now also captures az_nodal alongside the geometry.
        mesh_dict = solver._extract_mesh(femm, fem_path=fem_path)
        az_nodal = mesh_dict.get("az_nodal")
        if not az_nodal:
            raise RuntimeError(
                "field-preview disk-extract did not return az_nodal — "
                "likely fell back to mo_* IPC path which doesn't carry it"
            )

        regions = _classify_femm_triangles_by_centroid(
            mesh_dict["nodes_mm"],
            mesh_dict["triangles"],
            geom,
            rotor_angle_mech_deg=0.0,
        )

        pole_pitch_deg = 360.0 / config.rotor.pole_count
        # FEMM field preview is a full mechanical model, so expose a full
        # 360° span to match the rendered geometry and Native FEM import path.
        n_pole_pitches = config.rotor.pole_count
        total_span_deg = 360.0

        config_summary = {
            "topology": config.topology,
            "slots": config.stator.slot_count,
            "poles": config.rotor.pole_count,
            "stator_od_mm": config.stator.OD_mm,
            "rotor_od_mm": config.rotor.OD_mm,
            "magnet_thickness_mm": config.rotor.magnet_thickness_mm,
            "stack_length_mm": config.stator.stack_length_mm,
        }
        mesh_info = {
            "num_nodes": mesh_dict["num_nodes"],
            "num_triangles": mesh_dict["num_triangles"],
            "pole_pitch_deg": pole_pitch_deg,
            "n_pole_pitches": n_pole_pitches,
            "total_span_deg": total_span_deg,
            "mesh_density": f"femm_{getattr(config.solve_params, 'mesh_density', 'normal')}",
            "mesh_source": "femm",
        }

        plot = build_field_line_plot_from_mesh(
            config_summary=config_summary,
            mesh_info=mesh_info,
            nodes_mm=mesh_dict["nodes_mm"],
            triangles=mesh_dict["triangles"],
            regions=regions,
            az_nodal=az_nodal,
            n_pole_pitches=n_pole_pitches,
            total_span_deg=total_span_deg,
        )
        if plot is None:
            raise RuntimeError(
                "build_field_line_plot_from_mesh returned None — "
                "likely empty mesh or az_nodal"
            )

        generation_time_ms = int((time.time() - start_time) * 1000)
        # Pydantic FieldLinePlot serializes with its own field names; the
        # frontend FieldLinePlotData consumer already speaks that shape.
        # Inject generation_time_ms outside the model.
        result = plot.model_dump(mode="json", exclude_none=True)
        result["generation_time_ms"] = generation_time_ms

        tagged_log(
            f"[FEMM] field-preview complete · {mesh_dict['num_nodes']} nodes, "
            f"{mesh_dict['num_triangles']} triangles, "
            f"|B|_max={max(plot.element_b_mag_t):.3f} T · {generation_time_ms} ms"
        )
        return result

    except Exception as e:
        tagged_log(f"[FEMM] !! field-preview FAILED: {e}")
        raise RuntimeError(f"FEMM field preview failed: {e}") from e
    finally:
        if opened:
            try:
                femm.mo_close()
            except Exception as close_exc:
                tagged_log(f"[FEMM] Warning: mo_close raised: {close_exc}")
            try:
                femm.mi_close()
            except Exception as close_exc:
                tagged_log(f"[FEMM] Warning: mi_close raised: {close_exc}")
            try:
                femm.closefemm()
            except Exception as close_exc:
                tagged_log(f"[FEMM] Warning: closefemm raised: {close_exc}")
        FEMM_PROCESS_LOCK.release()
        tagged_log("[FEMM] field-preview: FEMM_PROCESS_LOCK released", flush=True)
