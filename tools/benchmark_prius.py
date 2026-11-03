"""Measure the versioned Prius references through the normal public solve pipeline.

Run from a source checkout: python -m tools.benchmark_prius --out <directory>.
The optional --curve and --refinement runs retain the actual modified requests.
Pyleecan and FEMM are optional reference producers, not runtime dependencies.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from backend.benchmark_suite.contract import now, read, run_lock, sha, write
from backend.local_paths import redact_local_paths
from backend.magneto2d_adapter import _magneto2d_env_overrides, ensure_magneto2d_binary
from backend.public_policy import parse_public_motor_config
from backend.reference_models import prius
from tools.prius_benchmark_contract import (
    SCHEMA,
    capture_identity,
    freeze_inputs,
    grading_inputs,
    selection_identity,
    verify_completed_job,
    verify_identity,
    verify_registered_identity,
)

ROOT = Path(__file__).resolve().parents[1]


def current_identity():
    return capture_identity(ROOT, ensure_magneto2d_binary())


@contextmanager
def runtime_environment(destination):
    values = {"COILEM_USER_DATA_ROOT": str(destination / "runtime"),
              "COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS": "1", "COILEM_MAGNETO2D_PERSIST_SUMMARY_ARTIFACTS": "1"}
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def solve_config(config, progress):
    from backend.solver import Magneto2DSolver

    return Magneto2DSolver(launch_surface=True).solve(config, on_progress=progress)


def jobs(curve=False, refinement=False):
    from backend.reference_models.prius import case_config

    tutorial = case_config("prius-2004-tutorial-bemf-v1")
    loaded = case_config("prius-2004-loaded-torque-v1")
    yield "tutorial-bemf-100", tutorial
    yield "loaded-torque-32", loaded
    if curve:
        for angle in range(60, 181, 10):
            config = case_config("prius-2004-loaded-torque-v1")
            config["solve_params"].update(current_angle_deg=angle, rotor_step_deg=22.5)
            config["solve_options"]["back_emf"] = False
            yield f"curve-{angle}-16", config
    if refinement:
        for density, step, name in [("normal", 5.625, "angular-64"), ("fine", 11.25, "mesh-fine-32")]:
            config = case_config("prius-2004-loaded-torque-v1")
            config["solve_params"].update(mesh_density=density, rotor_step_deg=step)
            config["solve_options"]["back_emf"] = False
            yield name, config


def collect_job(name, cfg, folder, expected):
    write(folder / "request.json", cfg.model_dump(mode="json"))
    write(folder / "environment.json", _magneto2d_env_overrides(cfg))
    print(f"Starting {name}", flush=True)
    last_update = 0.0

    def progress(position, total, torque, stage, angle=None, *rest):
        nonlocal last_update
        update = time.monotonic()
        if update - last_update > 25 or position == total:
            print(f"{name}: {stage} {position}/{total}, electrical angle {angle}", flush=True)
            last_update = update

    started = time.monotonic()
    result = solve_config(cfg, progress)
    elapsed = time.monotonic() - started
    # Reject changed code/executables immediately after solving, before retaining
    # a potentially misleading completed result. The caller checks again after
    # archiving, before committing this job to the registration.
    verify_identity(expected, current_identity())
    raw = result.model_dump(mode="json")
    write(folder / "result-original.json", raw)
    portable = json.loads(redact_local_paths(json.dumps(raw)))
    portable["solve_metadata"]["solve_cache_dir"] = None
    write(folder / "result.json", portable)
    wave = result.back_emf_waveform
    ab = np.asarray(wave.phase_a_V) - np.asarray(wave.phase_b_V)
    metrics = {"mean_torque_Nm": result.summary.avg_torque_Nm, "elapsed_s": elapsed,
               "loaded_actual_positions": result.solve_metadata.rotor_positions,
               "line_ab_sampled_rms_V": float(np.sqrt(np.mean(ab**2))) if cfg.solve_options.back_emf else None,
               "line_ab_sampled_peak_V": float(np.max(abs(ab))) if cfg.solve_options.back_emf else None,
               "phase_neutral_fundamental_rms_V": result.summary.back_emf_fundamental_V if cfg.solve_options.back_emf else None}
    cache = Path(result.solve_metadata.solve_cache_dir) if result.solve_metadata.solve_cache_dir else None
    artifacts = []
    if cache and cache.is_dir():
        archive = folder / "retained"
        archive.mkdir()
        for path in sorted(cache.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(cache)
            compressed = archive / (relative.as_posix() + ".gz")
            compressed.parent.mkdir(parents=True, exist_ok=True)
            with path.open("rb") as src, gzip.open(compressed, "wb") as dst:
                shutil.copyfileobj(src, dst)
            artifacts.append({"file": relative.as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    write(folder / "artifact-index.json", artifacts)
    return {"job": name, "case_id": cfg.reference_case, "request_sha256": sha(folder / "request.json"),
            "result_sha256": sha(folder / "result.json"), "result_original_sha256": sha(folder / "result-original.json"),
            "environment_sha256": sha(folder / "environment.json"), "artifact_index_sha256": sha(folder / "artifact-index.json"),
            "environment": _magneto2d_env_overrides(cfg), "request": cfg.model_dump(mode="json"),
            "metrics": metrics, "torque_waveform": raw["torque_waveform"], "back_emf_waveform": raw["back_emf_waveform"],
            "solve_metadata": portable["solve_metadata"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--curve", action="store_true", default=None, help="All thirteen current angles, sixteen actual full-cycle positions each")
    ap.add_argument("--refinement", action="store_true", default=None, help="Separate angular and mesh controls at Phi0=140 degrees")
    ap.add_argument("--only", help="Run one named job (useful for sequential reproduction)")
    ap.add_argument("--resume", action="store_true", help="Verify and resume the saved selection in --out")
    args = ap.parse_args(argv)
    destination = args.out.resolve()
    if destination.is_relative_to(ROOT):
        ap.error("Keep benchmark output outside the source checkout")
    if not args.resume:
        destination.mkdir(parents=True, exist_ok=False)
    elif not (destination / "registration.json").is_file():
        ap.error("--resume needs an existing v2 registration in --out")
    with run_lock(destination), runtime_environment(destination):
        registration = read(destination / "registration.json") if args.resume else None
        if registration is not None and registration["schema"] != SCHEMA:
            raise ValueError("Legacy registrations cannot resume: their executable and grading inputs were not frozen")
        options = {"curve": bool(args.curve), "refinement": bool(args.refinement), "only": args.only}
        if registration is not None:
            for key in options:
                supplied = getattr(args, key)
                saved = registration["selection"][key]
                if supplied is not None and supplied != saved:
                    raise ValueError("Resume selection differs from the registered jobs")
                options[key] = saved
        selected = [(name, parse_public_motor_config(body)) for name, body in jobs(options["curve"], options["refinement"])
                    if not options["only"] or name == options["only"]]
        if not selected:
            ap.error("--only does not match a selected job")
        selection = {**options, "jobs": [{"job": name, "request": cfg.model_dump(mode="json")} for name, cfg in selected]}
        expected = current_identity()
        if expected["dirty"]:
            raise ValueError("A clean committed checkout is required before collecting fields")
        if registration is None:
            frozen = freeze_inputs(ROOT, destination)
            verify_identity(expected, current_identity())
            registration = {
                "schema": SCHEMA, "started_utc": now(), "identity": expected,
                "source_commit": expected["commit"], "source_dirty": False,
                "source_sha256": {**expected["source_files"], **expected["collector_source_sha256"]},
                "binary_sha256": expected["binary_sha256"], "platform": expected["platform"],
                "python": expected["python"], "dependencies": expected["dependencies"],
                "source_machine_sha256": prius.source()["source_machine_sha256"], "geometry_asset_sha256": prius.geometry_asset_sha256(),
                "scope": "Development-candidate software reproduction; final v0.5.0 candidate rerun remains required",
                "qualified": False, "selection": selection, "frozen_inputs": frozen, "jobs": [],
                "job_states": {name: {"status": "PENDING", "attempts": []} for name, _ in selected},
                "status": "RUNNING", "complete": False,
            }
        else:
            verify_registered_identity(registration)
            verify_identity(registration["identity"], expected)
            if selection_identity(selection) != selection_identity(registration["selection"]):
                raise ValueError("Resume requests differ from the registered jobs")
            grading_inputs(destination, registration)
            completed = {job["job"] for job in registration["jobs"]}
            if len(completed) != len(registration["jobs"]) or completed - {name for name, _ in selected}:
                raise ValueError("Invalid completed job selection")
            for job in registration["jobs"]:
                verify_completed_job(destination, job, expected)
                if registration["job_states"][job["job"]]["status"] != "COMPLETE":
                    raise ValueError("Completed job state differs from its retained result")
        grading_inputs(destination, registration)
        registration.update(status="RUNNING", complete=False)
        write(destination / "registration.json", registration)
        completed = {job["job"] for job in registration["jobs"]}
        for name, cfg in selected:
            if name in completed:
                print(f"Verified completed {name}; skipping fields", flush=True)
                continue
            state = registration["job_states"][name]
            if state["status"] == "RUNNING":
                state["attempts"][-1].update(status="INTERRUPTED", finished_utc=now())
            relative = f"jobs/{name}/attempt-{len(state['attempts']) + 1}"
            attempt = {"directory": relative, "status": "RUNNING", "started_utc": now()}
            state["attempts"].append(attempt)
            state["status"] = "RUNNING"
            write(destination / "registration.json", registration)
            try:
                before = current_identity()
                verify_identity(expected, before)
                folder = destination / relative
                folder.mkdir(parents=True, exist_ok=False)
                entry = collect_job(name, cfg, folder, expected)
                after = current_identity()
                verify_identity(expected, after)
                grading_inputs(destination, registration)
                entry.update(directory=relative, identity_before=before, identity_after=after)
                registration["jobs"].append(entry)
                state["status"] = "COMPLETE"
                attempt.update(status="COMPLETE", finished_utc=now())
                write(destination / "registration.json", registration)
                print(f"Completed {name}: {entry['metrics']}", flush=True)
            except BaseException as error:
                registration["jobs"] = [job for job in registration["jobs"] if job["job"] != name]
                attempt.update(status="FAILED", finished_utc=now(), error=redact_local_paths(str(error)))
                state["status"] = "FAILED"
                registration.update(status="FAILED", complete=False)
                write(destination / "registration.json", registration)
                raise
        verify_identity(expected, current_identity())
        grading_inputs(destination, registration)
        registration.update(status="COMPLETE", complete=True, finished_utc=now())
        write(destination / "registration.json", registration)


if __name__ == "__main__":
    main()
