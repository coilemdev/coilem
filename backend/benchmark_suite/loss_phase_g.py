"""Benchmark Phase G: losses.

Phase G checks the loss numbers of a full-motor solve on four motors, each at
no load and at one load, at 1500 and 3000 rpm: 16 operating points.

* **Stator iron loss, DC copper loss and phase resistance** are solved through
  the public Python client and graded against the FEMM records collected on
  2026-11-17 (``references/femm-stator-copper-20261117``).
* **Rotor iron loss** is solved for the same eight motor and load pairs over a
  full mechanical turn of 384 rotor positions. It is graded on its own checks
  (the turn closes on itself, and the loss stops changing as the number of
  positions is doubled from 96 to 192 to 384) and, where a FEMM rotor record is
  stored under ``references/femm-rotor`` (tools/phase_g_femm), against FEMM at
  384 positions.

Phase G is separate from the registered A-F suite: it does not change that
suite, its references or its gates, and ``coilem benchmark`` does not run it.
The numbers that define it are in ``benchmarks/g-v2.0/benchmark_spec.json`` and
are frozen. Grading reads only the stored record, so it can be repeated
without solving anything.
"""

from __future__ import annotations

import errno
import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager, nullcontext
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = "benchmarks/g-v2.0"
SPEC = f"{PROTOCOL}/benchmark_spec.json"
RESULTS = f"{PROTOCOL}/results/coilem.json"
STATOR_KEYS = ("iron_hysteresis_loss_W", "iron_eddy_loss_W", "iron_loss_W")
COPPER_KEYS = ("copper_loss_W", "phase_resistance_ohm")
ROTOR_KEYS = ("hysteresis_W", "lamination_eddy_W", "total_W")
LABELS = {"iron_hysteresis_loss_W": "Stator hysteresis", "iron_eddy_loss_W": "Stator lamination eddy",
          "iron_loss_W": "Stator iron", "copper_loss_W": "DC copper", "phase_resistance_ohm": "Phase resistance",
          "hysteresis_W": "Rotor hysteresis", "lamination_eddy_W": "Rotor lamination eddy", "total_W": "Rotor iron"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def spec() -> dict:
    return json.loads((ROOT / SPEC).read_text(encoding="utf-8"))


def spec_sha256() -> str:
    return _sha256(ROOT / SPEC)


def _checked(relative: str, sha256: str) -> Path:
    """A registered file, refused when its bytes are not the registered ones."""
    path = ROOT / PROTOCOL / relative
    if _sha256(path) != sha256:
        raise ValueError(f"{PROTOCOL}/{relative} is not the registered file")
    return path


def fixture(row: dict) -> dict:
    """The motor request of a case or of a rotor history."""
    return json.loads(_checked(row["fixture"], row["fixture_sha256"]).read_text(encoding="utf-8"))


def reference(case_row: dict) -> dict:
    """The FEMM stator and copper values of a case."""
    record = json.loads(_checked(case_row["reference"], case_row["reference_sha256"]).read_text(encoding="utf-8"))
    result = record["result"]
    if record["case_id"] != case_row["id"] or result["speed_rpm"] != case_row["speed_rpm"]:
        raise ValueError(f"The reference for {case_row['id']} is for another operating point")
    return {key: float(result["values"][key]) for key in (*STATOR_KEYS, *COPPER_KEYS)}


def stator_values(summary: dict) -> dict:
    """The five graded numbers of a solved result."""
    iron = summary["iron_loss"]
    if iron["status"] == "unavailable":
        raise ValueError(f"Stator iron loss is unavailable: {iron.get('status_reason')}")
    values = {key: float(iron[key]) for key in STATOR_KEYS}
    values.update(copper_loss_W=float(summary["loss_breakdown"]["copper_loss_W"]),
                  phase_resistance_ohm=float(summary["winding_resistance"]["phase_resistance_ohm"]))
    if any(not math.isfinite(value) or value < 0 for value in values.values()):
        raise ValueError("A loss value is missing, negative or not finite")
    return values


def _limit(key: str, reference_value: float, gates: dict) -> float:
    if key in COPPER_KEYS:
        return max(1e-12, gates["copper_relative"] * abs(reference_value))
    return max(gates["absolute_W"], gates["reference_relative"] * abs(reference_value))


def grade_stator(values: dict, reference_values: dict, gates: dict) -> dict:
    """Each stator and copper number against FEMM: 10% or 1 mW for iron loss, 1% for copper and resistance."""
    rows = {}
    for key in (*STATOR_KEYS, *COPPER_KEYS):
        expected, got = reference_values[key], values[key]
        limit = _limit(key, expected, gates)
        rows[key] = {"coilem": got, "femm": expected, "difference": got - expected,
                     "difference_pct": 100 * (got - expected) / expected if expected else None,
                     "limit": limit, "status": "PASS" if abs(got - expected) <= limit else "FAIL"}
    return {"status": "PASS" if all(row["status"] == "PASS" for row in rows.values()) else "FAIL", "values": rows}


def rotor_references() -> dict[str, dict]:
    """The FEMM rotor records under references/femm-rotor (tools/phase_g_femm), by history.

    A record collected for another specification is refused rather than ignored.
    """
    directory = ROOT / PROTOCOL / "references" / "femm-rotor"
    found = {}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema") != "coilem.phase_g_rotor_reference/v1" or record.get("spec_sha256") != spec_sha256():
            raise ValueError(f"{path.name} is not a rotor reference for this Phase G specification")
        if path.stem != record["history"]:
            raise ValueError(f"{path.name} holds the reference of {record['history']}")
        found[record["history"]] = record
    return found


def grade_rotor_reference(values: dict, reference: dict, speed_rpm: int, gates: dict) -> dict:
    """coilEM's rotor loss at 384 positions against FEMM's: each component within 10% of FEMM or 1 mW."""
    femm = reference["speeds"][str(speed_rpm)][str(spec()["rotor"]["positions"])]
    rows = {}
    for key in ROTOR_KEYS:
        expected, got = femm[key], values[key]
        limit = max(gates["absolute_W"], gates["reference_relative"] * abs(expected))
        rows[key] = {"coilem": got, "femm": expected, "difference": got - expected,
                     "difference_pct": 100 * (got - expected) / expected if expected else None,
                     "limit": limit, "status": "PASS" if abs(got - expected) <= limit else "FAIL"}
    return {"solver": reference["solver"], "status": "PASS" if all(row["status"] == "PASS" for row in rows.values()) else "FAIL",
            "values": rows}


def grade_rotor(history: dict, speed_rpm: int, gates: dict, reference: dict | None = None) -> dict:
    """Rotor iron loss at one speed: the turn closes, and each registered doubling of the positions (96 to 192 to 384)
    changes it by under 5% or 1 mW.

    Every registered position count is needed: a missing one fails the steps it belongs to, and so the history.
    With a FEMM record, the 384-position loss is also graded against it (``reference``); without that row it fails.
    """
    rotor = spec()["rotor"]
    counts, finest = rotor["position_counts"], str(rotor["positions"])
    closure = history["closure"]
    closed = closure["max_T"] <= gates["closure_max_T"] and closure["rms_T"] <= gates["closure_rms_T"]
    by_positions = history["speeds"].get(str(speed_rpm), {})
    missing = [count for count in counts if str(count) not in by_positions]
    steps = []
    for coarse, fine in zip(counts, counts[1:]):
        if coarse in missing or fine in missing:
            steps.append({"from": coarse, "to": fine, "changes": None, "status": "FAIL"})
            continue
        changes = {}
        for key in ROTOR_KEYS:
            finer, change = by_positions[str(fine)][key], by_positions[str(fine)][key] - by_positions[str(coarse)][key]
            limit = max(gates["absolute_W"], gates["angular_relative"] * abs(finer))
            changes[key] = {"change_W": change, "limit_W": limit, "status": "PASS" if abs(change) <= limit else "FAIL"}
        steps.append({"from": coarse, "to": fine, "changes": changes,
                      "status": "PASS" if all(row["status"] == "PASS" for row in changes.values()) else "FAIL"})
    passed = closed and not missing and all(step["status"] == "PASS" for step in steps)
    values = dict(by_positions[finest]) if finest in by_positions else None
    if reference is None:
        against = None
    elif values is None:
        against = {"solver": reference["solver"], "status": "FAIL", "values": None}
    else:
        against = grade_rotor_reference(values, reference, speed_rpm, gates)
    graded = {"status": "PASS" if passed else "FAIL", "closure": "PASS" if closed else "FAIL", "angular_steps": steps,
              "values": values, "reference": against}
    return (graded | {"missing_positions": missing}) if missing else graded


def compare(result: dict) -> dict:
    """Grade a stored record. Reads nothing but the record, the spec and the registered references."""
    registered = spec()
    gates = registered["gates"]
    histories = {row["id"]: row for row in result.get("rotor_histories", [])}
    solved = {row["id"]: row for row in result["cases"]}
    femm_rotor = rotor_references()
    rows = []
    for case_row in registered["cases"]:
        entry = {"id": case_row["id"], "stator": None, "rotor": None}
        if case_row["id"] in solved:
            entry["stator"] = grade_stator(solved[case_row["id"]]["stator"], reference(case_row), gates)
        if case_row["rotor_history"] in histories:
            entry["rotor"] = grade_rotor(histories[case_row["rotor_history"]], case_row["speed_rpm"], gates,
                                         femm_rotor.get(case_row["rotor_history"]))
        rows.append(entry)

    def count(part: str, against_femm: bool = False) -> dict:
        tally = {"PASS": 0, "FAIL": 0, "NOT_RUN": 0}
        for row in rows:
            graded = row[part] and (row[part]["reference"] if against_femm else row[part])
            tally[graded["status"] if graded else "NOT_RUN"] += 1
        return tally

    solvers = sorted({reference["solver"] for reference in femm_rotor.values()})
    return {"cases": rows, "stator_copper_vs_femm": count("stator"), "rotor_own_checks": count("rotor"),
            "rotor_vs_femm": count("rotor", against_femm=True),
            "rotor_reference": (f"Rotor iron loss is graded against {' and '.join(solvers)} for "
                                f"{len(femm_rotor)} of {len(registered['rotor_histories'])} motor and load pairs."
                                if femm_rotor else "No FEMM rotor record is stored; rotor loss is not graded against another solver.")}


# -- Solving -----------------------------------------------------------------------------------------------


def solve_stator(case_row: dict) -> dict:
    """One operating point through the public Python client, as a user script would solve it."""
    import os

    import coilem
    from backend.field_artifacts import SOLVE_CACHE_ROOT_ENV

    cache = tempfile.mkdtemp(prefix="coilem-phase-g-")
    previous = os.environ.get(SOLVE_CACHE_ROOT_ENV)
    os.environ[SOLVE_CACHE_ROOT_ENV] = cache
    started = time.perf_counter()
    try:
        result = coilem.solve(fixture(case_row))
    finally:
        # One solve keeps about 2 GB of fields. The benchmark needs only the numbers.
        shutil.rmtree(cache, ignore_errors=True)
        if previous is None:
            os.environ.pop(SOLVE_CACHE_ROOT_ENV, None)
        else:
            os.environ[SOLVE_CACHE_ROOT_ENV] = previous
    metadata = result.metadata
    return {"id": case_row["id"], "stator": stator_values(result.summary),
            "mean_torque_Nm": result.average_torque_Nm,
            "electrical_positions": metadata.get("rotor_positions"),
            "nonlinear_worst_tolerance_ratio": metadata.get("nonlinear_worst_tolerance_ratio"),
            "wall_time_s": round(time.perf_counter() - started, 1)}


def rotor_history(samples, *, speed_rpm: float, direction: int):
    """The rotor-steel field of every solved position of the turn, followed element by element."""
    from backend.rotor_iron_loss import RotorSamplingPlan, rotor_flux_history

    turn = samples[:-1]
    return rotor_flux_history(RotorSamplingPlan(float(speed_rpm), len(turn), direction), turn)


def rotor_losses(native_config, history, *, speed_rpm: float, positions: int) -> dict:
    """Rotor iron loss from every n-th solved position, at any speed: the fields do not depend on speed."""
    from backend.rotor_iron_loss import RotorFluxHistory, RotorSamplingPlan, harmonic_rotor_iron_loss
    from backend.rotor_loss_solver import MATERIAL

    solved = history.plan.positions
    if solved % positions:
        raise ValueError(f"{positions} positions do not divide the {solved} solved")
    stride = solved // positions
    subset = RotorFluxHistory(RotorSamplingPlan(float(speed_rpm), positions, history.plan.direction),
                              history.bx_t[::stride], history.by_t[::stride], history.area_m2,
                              history.reference_element_index, history.distinct_meshes)
    estimate = harmonic_rotor_iron_loss(subset, material=MATERIAL, stack_length_m=native_config.stator.stack_length_mm * 1e-3)
    return {"hysteresis_W": estimate.hysteresis_W, "lamination_eddy_W": estimate.lamination_eddy_W, "total_W": estimate.total_W}


def solve_rotor(history_row: dict, *, workers: int = 4, on_progress=None) -> dict:
    """One motor and load: a full turn solved once, then reduced at each speed and position count."""
    from backend.models import MotorConfig
    from backend.rotor_loss_solver import record_from_samples, rotor_field_samples
    from backend.solver import _clockwise_excitation_config

    rotor = spec()["rotor"]
    config = MotorConfig.model_validate(fixture(history_row))
    # The app solves a clockwise rotor in the solver's own counter-clockwise frame. Do as it does.
    native = _clockwise_excitation_config(config)
    started = time.perf_counter()
    native, plan, samples = rotor_field_samples(native, direction=-1, workers=workers, on_progress=on_progress)
    product = record_from_samples(native, plan, samples)
    history = rotor_history(samples, speed_rpm=plan.speed_rpm, direction=plan.direction)
    speeds = {str(speed): {str(count): rotor_losses(native, history, speed_rpm=speed, positions=count)
                           for count in rotor["position_counts"]} for speed in rotor["evaluation_speeds_rpm"]}
    return {"id": history_row["id"], "rotor_layout": config.rotor_layout, "positions": plan.positions,
            "collection_speed_rpm": plan.speed_rpm, "rotor_core_elements": int(len(samples[0].bx_t)),
            "rotor_iron_mass_kg": product.rotor_iron_mass_kg,
            "closure": {"max_T": product.endpoint_max_component_difference_T, "rms_T": product.endpoint_rms_component_difference_T},
            "product_record_W": {"hysteresis_W": product.rotor_hysteresis_loss_W,
                                 "lamination_eddy_W": product.rotor_lamination_eddy_loss_W, "total_W": product.rotor_iron_loss_W},
            "share_above_validated_frequency": product.share_above_validated_frequency,
            "share_above_validated_flux_density": product.share_above_validated_flux_density,
            "speeds": speeds, "wall_time_s": round(time.perf_counter() - started, 1)}


# -- The work folder ---------------------------------------------------------------------------------------

WORK_SCHEMA = "coilem.phase_g_work/v1"
WORK_MANIFEST = "candidate.json"
# Held locked by the run solving into the folder, and removed when it ends (``work_lock``).
WORK_LOCK = ".phase-g-run.lock"
# The Python sources and data a solve runs. The native solver is named by its executable's hash instead.
SOURCE_TREES = ("backend", "coilem", "materials")
SOURCE_SUFFIXES = (".py", ".json", ".csv")
WORK_LABELS = {"protocol_version": "the Phase G protocol", "spec_sha256": "the Phase G specification",
               "coilem_version": "the coilEM version", "source.commit": "the source commit",
               "source.modified": "local changes to the sources", "source.sha256": "the Python sources",
               "solver_sha256": "the Magneto2D executable"}


class WorkFolderError(ValueError):
    """A work folder holding points that this build did not solve."""


class WorkFolderBusy(WorkFolderError):
    """A work folder another Phase G run is solving into."""


# What a refused non-blocking lock raises: EWOULDBLOCK/EAGAIN from flock, EACCES from msvcrt.locking.
_LOCK_HELD = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}


def _lock(descriptor: int) -> None:
    """Lock an open file for this process without waiting; OSError when another holder has it."""
    if os.name == "nt":
        import msvcrt

        # A mandatory lock on the first byte: any other handle, in this process or another, is refused it. The file
        # is empty, and locking past its end is allowed.
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _still_at(descriptor: int, path: Path) -> bool:
    try:
        return os.path.samestat(os.fstat(descriptor), os.stat(path))
    except FileNotFoundError:
        return False


@contextmanager
def work_lock(work: Path):
    """Hold a work folder for one run: no other Phase G run can open, discard, resume or write into it meanwhile.

    The lock is the operating system's, on ``WORK_LOCK`` in the folder, held open for the whole run, so it goes
    when the process ends however it ends. A second run is refused at once (``WorkFolderBusy``); it never waits.
    The file is removed when the run ends, so a finished folder holds only its points and ``candidate.json``.
    """
    work.mkdir(parents=True, exist_ok=True)
    path = work / WORK_LOCK
    busy = WorkFolderBusy(f"Another Phase G run is using the work folder {work}: it holds {WORK_LOCK} there. Only one "
                          "run can use a work folder at a time, so nothing in it was changed. Wait for that run to "
                          "finish or stop it, or use another work folder.")
    for _attempt in range(5):
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            _lock(descriptor)
        except OSError as error:
            os.close(descriptor)
            if error.errno in _LOCK_HELD:
                raise busy from None
            raise
        # POSIX only: a run that was ending removed the file between this open and this lock, so the lock is on a
        # file no longer in the folder and another run may hold the new one. Windows cannot remove an open file.
        if os.name == "nt" or _still_at(descriptor, path):
            break
        os.close(descriptor)
    else:
        raise busy
    try:
        yield path
    finally:
        if os.name == "nt":
            import msvcrt

            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(descriptor)
            try:
                path.unlink()
            except OSError:
                pass  # Another run opened it after the unlock and holds it now; the file is that run's.
        else:
            # Removed while still locked, so a run that opened it before cannot lock it and still find it here.
            # Closing releases the lock.
            if _still_at(descriptor, path):
                path.unlink(missing_ok=True)
            os.close(descriptor)


def _write_json(path: Path, value) -> None:
    """Write through a temporary file, so a stopped run leaves the old file or the new one and never part of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _git(*args: str) -> str | None:
    executable = shutil.which("git")
    if executable is None:
        return None
    try:
        completed = subprocess.run([executable, "-C", str(ROOT), *args], capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def source_identity() -> dict:
    """The checkout's commit, whether its solve sources differ from that commit, and the hash of those sources as they are.

    A checkout with local changes is named by its commit and by the bytes of the files it actually runs, so an edit
    between two runs at the same commit still makes another candidate. Without Git, the commit is ``None``.
    """
    files = {path.relative_to(ROOT).as_posix(): _sha256(path)
             for tree in SOURCE_TREES for path in sorted((ROOT / tree).rglob("*"))
             if path.is_file() and path.suffix in SOURCE_SUFFIXES and "__pycache__" not in path.parts}
    status = _git("status", "--porcelain", "--", *SOURCE_TREES, "solvers/magneto2d")
    return {"commit": _git("rev-parse", "HEAD"), "modified": None if status is None else bool(status),
            "sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}


def _solver_binary() -> Path:
    """The Magneto2D executable the solves will run (``COILEM_MAGNETO2D_BINARY``, the packaged one, or a checkout build)."""
    from backend.magneto2d_adapter import ensure_magneto2d_binary

    return ensure_magneto2d_binary()


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def candidate() -> dict:
    """Everything a solved point depends on: specification, fixtures, sources, solver executable and mesher versions."""
    from backend import __version__
    from backend.benchmark_suite.physics import PHYSICS_DEPENDENCIES

    registered = spec()
    fixtures = {row["fixture"]: _sha256(ROOT / PROTOCOL / row["fixture"])
                for row in (*registered["cases"], *registered["rotor_histories"])}
    return {"protocol_version": registered["protocol_version"], "spec_sha256": spec_sha256(), "fixtures": fixtures,
            "coilem_version": __version__, "source": source_identity(), "solver_sha256": _sha256(_solver_binary()),
            "dependencies": {name: _version(name) for name in PHYSICS_DEPENDENCIES}}


def _flat(value: dict, prefix: str = "") -> dict:
    flat = {}
    for key, item in value.items():
        if isinstance(item, dict):
            flat.update(_flat(item, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = item
    return flat


def _differences(kept: dict, current: dict) -> list[str]:
    """What differs between the candidate that solved a folder's points and this one, in words."""
    before, now = _flat(kept), _flat(current)
    changed = [key for key in sorted(set(before) | set(now)) if before.get(key) != now.get(key)]
    described = []
    for key in changed:
        group, _, name = key.partition(".")
        if group == "fixtures":
            continue
        label = WORK_LABELS.get(key) or (f"the {name} version" if group == "dependencies" else key)
        if key.endswith("sha256"):
            described.append(label)
            continue
        described.append(f"{label} ({_shown(key, before.get(key))} there, {_shown(key, now.get(key))} here)")
    fixtures = [key.partition(".")[2] for key in changed if key.startswith("fixtures.")]
    if fixtures:
        described.append(f"the fixtures {', '.join(fixtures)}" if len(fixtures) <= 3 else f"{len(fixtures)} fixtures")
    return described or ["its record of the build"]


def _shown(key: str, value) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)[:10] if key == "source.commit" else str(value)


def _kept_names() -> list[str]:
    registered = spec()
    return [f"stator-{row['id']}" for row in registered["cases"]] + [f"rotor-{row['id']}" for row in registered["rotor_histories"]]


def open_work(work: Path, current: dict, *, discard: bool = False) -> None:
    """Bind a work folder to the candidate about to solve into it.

    The folder's ``candidate.json`` names the build that solved the points kept there. They are reused only by the
    same candidate; another one is refused, so that one build's measurements are never recorded as another's.
    ``discard`` deletes the kept points (and nothing else) first. Call it holding ``work_lock(work)``, as ``run``
    does, so that no other run changes the folder between this check and the last point written.
    """
    manifest = work / WORK_MANIFEST
    kept = [work / f"{name}.json" for name in _kept_names()]
    if discard:
        for path in (*kept, manifest):
            path.unlink(missing_ok=True)
    holds_points = any(path.exists() for path in kept)
    advice = ("Use a new work folder, or run again with --discard-work to delete the points kept there and solve them "
              "again.")
    if manifest.exists() and holds_points:
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
        before = recorded.get("candidate") if recorded.get("schema") == WORK_SCHEMA else None
        if before == current:
            return
        differs = _differences(before, current) if isinstance(before, dict) else ["its record of the build is in another format"]
        raise WorkFolderError(f"The work folder {work} holds points solved by another build. What differs: "
                              f"{'; '.join(differs)}. {advice}")
    if holds_points:
        raise WorkFolderError(f"The work folder {work} holds finished points but no {WORK_MANIFEST} naming the build that "
                              f"solved them. {advice}")
    _write_json(manifest, {"schema": WORK_SCHEMA, "candidate": current})


def run(*, only: str | None = None, rotor: bool = True, workers: int = 4, work: Path | None = None, discard: bool = False,
        log=print) -> dict:
    """Solve the registered points. A finished point is kept in ``work`` so a stopped run continues.

    Only the candidate that solved the kept points continues them (``open_work``); ``discard`` deletes them first.
    The folder is held (``work_lock``) from before that check until the result is assembled, so a second run is
    refused rather than discarding, resuming or writing points in it meanwhile.
    """
    with work_lock(work) if work is not None else nullcontext():
        registered = spec()
        current = candidate()
        if work is not None:
            open_work(work, current, discard=discard)

        def kept(name: str, solve):
            path = work / f"{name}.json" if work is not None else None
            if path is not None and path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            value = solve()
            if path is not None:
                _write_json(path, value)
            return value

        cases, histories = [], []
        for case_row in registered["cases"]:
            if only and case_row["motor"] != only:
                continue
            log(f"stator and copper: {case_row['id']}")
            cases.append(kept(f"stator-{case_row['id']}", lambda row=case_row: solve_stator(row)))
        for history_row in registered["rotor_histories"] if rotor else []:
            if only and history_row["motor"] != only:
                continue
            log(f"rotor, {registered['rotor']['positions']} positions: {history_row['id']}")
            histories.append(kept(f"rotor-{history_row['id']}", lambda row=history_row: solve_rotor(row, workers=workers)))
        return {"schema": "coilem.phase_g_result/v1", "protocol_version": registered["protocol_version"],
                "spec_sha256": spec_sha256(), "coilem_version": current["coilem_version"],
                "candidate": {key: current[key] for key in ("source", "solver_sha256", "dependencies")},
                "cases": cases, "rotor_histories": histories}
