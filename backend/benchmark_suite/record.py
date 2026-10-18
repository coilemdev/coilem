"""Published per-platform benchmark records and the policy for matching one (#71).

A record is the compact outcome of one complete run: each case's verdict, its
gate statuses and the measured values behind its numerical gates. A run
matches a record when verdicts and gate statuses are identical and every value
agrees within ``TOLERANCES``. Records are matched by physics-source hashes,
not Git, so an installed package can be checked against a record measured at
an earlier commit whose physics is unchanged.
"""

from __future__ import annotations

import math
import os
import platform
from datetime import datetime

from backend.benchmark_suite.contract import CHECKOUT, DATA_ROOT, ROOT, machine_name, read, sha
from backend.benchmark_suite.physics import (
    BUILD_INFO_KEY,
    PHYSICS_DATA_SOURCES,
    PHYSICS_PYTHON_SOURCES,
    solver_source_hashes,
)
from backend.resources import BENCHMARK_RECORDS_DIR, stamped_build_info

RECORD_SCHEMA = "coilem.benchmark_record/v1"
# (relative, absolute floor) per value. At 738d951 the macOS arm64 and Windows
# x86_64 meshes differed by a few elements. That moved mean torque by up to
# 0.19% (0.012 N·m), the back-EMF fundamental by up to 0.007% and the
# back-EMF peak by up to 0.63%, and changed no gate status. Each tolerance is
# about 2.5 times that spread; the floors cover values near zero, such as
# no-load torque.
TOLERANCES = {
    "mean_torque_Nm": (0.005, 0.001),
    "back_emf_fundamental_V": (0.0005, 0.001),
    "back_emf_peak_V": (0.015, 0.001),
}
VALUE_LABELS = {
    "mean_torque_Nm": ("mean torque", "N·m"),
    "back_emf_fundamental_V": ("back-EMF fundamental", "V"),
    "back_emf_peak_V": ("back-EMF peak", "V"),
}
EVALUATED = ("PASS", "YELLOW", "FAIL")


def platform_key(system=None, machine=None):
    """``macos-arm64``, ``windows-x86_64``, ``linux-x86_64``: one record per key."""

    system = (system or platform.system()).lower()
    machine = (machine or machine_name()).lower()
    system = {"darwin": "macos"}.get(system, system)
    machine = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64", "win32": "x86"}.get(machine, machine)
    return f"{system}-{machine}"


def identity_platform_key(identity):
    system = identity["platform"].split("-", 1)[0]
    return platform_key(system, identity["machine"])


def gate_statuses(evaluation):
    gates = evaluation.get("gates") or {}
    if isinstance(gates, dict):
        return dict(gates)
    return {gate["id"]: gate["status"] for gate in gates}


def gated_values(row):
    """The measured values behind a case's numerical gates, keyed ``[stage.]name``."""

    if row["status"] not in EVALUATED:
        return {}
    measurements = row["measurements"]
    if row["phase"] == "D":
        # fsum is exact, so the mean is the same on every Python version
        # (3.12 changed how sum() rounds floats).
        return {
            f"{stage}.mean_torque_Nm": math.fsum(result["torque_Nm"]) / len(result["torque_Nm"])
            for stage, result in sorted(measurements.items())
        }
    result = measurements["native"]
    return {
        "mean_torque_Nm": result["summary"]["avg_torque_Nm"],
        "back_emf_fundamental_V": result["summary"]["back_emf_fundamental_V"],
        "back_emf_peak_V": max(abs(v) for v in result["back_emf_waveform"]["phase_a_V"]),
    }


def case_record(row):
    return {
        "phase": row["phase"],
        "status": row["status"],
        "gates": gate_statuses(row["evaluation"]),
        "values": gated_values(row),
    }


def _seconds(job):
    if not job.get("started_at") or not job.get("completed_at"):
        return None
    return (datetime.fromisoformat(job["completed_at"]) - datetime.fromisoformat(job["started_at"])).total_seconds()


def case_runtimes(manifest):
    """Wall time per case from a run manifest, for estimates; None when a job lacks times."""

    totals = {}
    for job in manifest["jobs"]:
        if job["status"] == "UNSUPPORTED":
            continue
        seconds = _seconds(job)
        previous = totals.get(job["case_id"], 0.0)
        totals[job["case_id"]] = None if seconds is None or previous is None else round(previous + seconds, 1)
    return totals


def build_record(summary, *, source, physics_files, runtimes=None, evaluation_note=None):
    """The compact record of a complete, non-smoke run evaluated against the frozen reference."""

    run = summary["run"]
    identity = run["identity"]
    if run.get("smoke") or run["status"] not in ("COMPLETE", "COMPLETE_WITH_ERRORS"):
        raise ValueError("Only a complete, full-grid run can be published as a record")
    if any(row["reference_mode"] != "FROZEN_REFERENCE" for row in summary["rows"] if row["status"] in EVALUATED):
        raise ValueError("Every evaluated case must be compared with the frozen reference")
    return {
        "schema": RECORD_SCHEMA,
        "platform": identity_platform_key(identity),
        "source": source,
        "measured_commit": identity["commit"],
        "environment": {key: identity[key] for key in ("platform", "machine", "python", "dependencies")},
        "suite_sha256": run["selection"]["spec_sha256"],
        "reference_bundle_sha256": run["selection"]["bundle_sha256"],
        **({"evaluation": evaluation_note} if evaluation_note else {}),
        "physics_files": physics_files,
        "case_runtime_s": runtimes if runtimes is not None else case_runtimes(run),
        "cases": {row["id"]: case_record(row) for row in sorted(summary["rows"], key=lambda row: row["id"])},
    }


def load_records(directory=None):
    directory = directory or DATA_ROOT / BENCHMARK_RECORDS_DIR
    records = {}
    for path in sorted(directory.glob("*.json")):
        record = read(path)
        if record.get("schema") != RECORD_SCHEMA:
            raise ValueError(f"Unsupported benchmark record: {path.name}")
        records[record["platform"]] = record
    return records


def select_record(records, key=None):
    """This platform's record, else one for the same processor architecture, marked cross-platform."""

    key = key or platform_key()
    if key in records:
        return records[key], False
    architecture = key.split("-", 1)[1]
    for other, record in sorted(records.items()):
        if other.split("-", 1)[1] == architecture:
            return record, True
    return None, False


def installed_physics_hashes():
    """``{repository path: sha256}`` for what this installation runs; ``None`` where it cannot be checked.

    Python and material sources are hashed as installed. The solver's Rust
    sources come from the checkout, or from the build identity stamped into an
    installed package. ``COILEM_MAGNETO2D_BINARY`` replaces the solver, so its
    sources are then unverified.
    """

    from backend.magneto2d_adapter import MAGNETO2D_BINARY_ENV

    hashes = {path: sha(ROOT / path) if (ROOT / path).is_file() else None for path in PHYSICS_PYTHON_SOURCES}
    hashes.update({path: sha(DATA_ROOT / path) if (DATA_ROOT / path).is_file() else None for path in PHYSICS_DATA_SOURCES})
    if os.environ.get(MAGNETO2D_BINARY_ENV):
        solver = {}
    elif CHECKOUT is not None:
        solver = solver_source_hashes(CHECKOUT)
    else:
        solver = (stamped_build_info() or {}).get(BUILD_INFO_KEY) or {}
    return hashes, solver


def check_physics(record):
    """Whether this installation runs the physics sources the record measured."""

    hashes, solver = installed_physics_hashes()
    differs, unverified = [], []
    for path, expected in sorted(record["physics_files"].items()):
        actual = hashes[path] if path in hashes else solver.get(path)
        if actual is None:
            unverified.append(path)
        elif actual != expected:
            differs.append(path)
    # A solver file the build has but the record lacks is a change too.
    differs.extend(sorted(set(solver) - set(record["physics_files"])))
    status = "DIFFERS" if differs else "UNVERIFIED" if unverified else "MATCH"
    return {"status": status, "files": len(record["physics_files"]), "differs": differs, "unverified": unverified}


def within(value, expected, name):
    relative, floor = TOLERANCES[name.rsplit(".", 1)[-1]]
    tolerance = max(floor, relative * abs(expected))
    return abs(value - expected) <= tolerance, tolerance


def compare_case(row, recorded):
    if recorded is None:
        return {"match": False, "differences": ["not in the record"], "values": {}}
    differences = []
    if row["status"] != recorded["status"]:
        differences.append(f"verdict {row['status']}, record {recorded['status']}")
    gates = gate_statuses(row["evaluation"])
    for gate in sorted(set(gates) | set(recorded["gates"])):
        if gates.get(gate) != recorded["gates"].get(gate):
            differences.append(f"gate {gate} {gates.get(gate, 'absent')}, record {recorded['gates'].get(gate, 'absent')}")
    values = {}
    measured = gated_values(row)
    for name in sorted(set(measured) | set(recorded["values"])):
        value, expected = measured.get(name), recorded["values"].get(name)
        if value is None or expected is None or not math.isfinite(value):
            differences.append(f"{name} {'missing' if value is None else value}, record {'missing' if expected is None else expected}")
            continue
        ok, tolerance = within(value, expected, name)
        values[name] = {"value": value, "record": expected, "tolerance": tolerance, "within": ok}
        if not ok:
            differences.append(f"{name} {value:.6g}, record {expected:.6g} (tolerance ±{tolerance:.3g})")
    return {"match": not differences, "differences": differences, "values": values}


def compare_run(rows, record, *, cross_platform=False, physics=None):
    """Match each selected case against the record; the overall status names the weakest link."""

    if record is None:
        return {"status": "NO_RECORD", "platform": platform_key(), "cases": {}}
    cases = {row["id"]: compare_case(row, record["cases"].get(row["id"])) for row in rows}
    matched = sum(case["match"] for case in cases.values())
    physics = physics or check_physics(record)
    if physics["status"] == "DIFFERS":
        status = "NOT_COMPARABLE"
    else:
        status = "MATCH" if matched == len(cases) else "DIFFERS"
    return {
        "status": status,
        "platform": platform_key(),
        "record": {key: record[key] for key in ("platform", "source", "measured_commit", "environment")},
        "cross_platform": cross_platform,
        "physics": physics,
        "matched": matched,
        "compared": len(cases),
        "cases": cases,
    }
