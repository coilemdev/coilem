"""Measure the versioned Prius references through the normal public solve pipeline.

Run from a source checkout: python -m tools.benchmark_prius --out <directory>.
The optional --curve and --refinement runs retain the actual modified requests.
Pyleecan and FEMM are optional reference producers, not runtime dependencies.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--curve", action="store_true", help="All thirteen current angles, sixteen actual full-cycle positions each")
    ap.add_argument("--refinement", action="store_true", help="Separate angular and mesh controls at Phi0=140 degrees")
    ap.add_argument("--only", help="Run one named job (useful for sequential reproduction)")
    args = ap.parse_args()
    destination = args.out.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    # Isolate this run's raw artifacts and caches from the user's normal app.
    os.environ["COILEM_USER_DATA_ROOT"] = str(destination / "runtime")
    os.environ["COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS"] = "1"
    os.environ["COILEM_MAGNETO2D_PERSIST_SUMMARY_ARTIFACTS"] = "1"
    from backend.benchmark_suite.physics import physics_sources
    from backend.local_paths import redact_local_paths
    from backend.magneto2d_adapter import _magneto2d_env_overrides, ensure_magneto2d_binary
    from backend.public_policy import parse_public_motor_config
    from backend.reference_models import prius
    from backend.solver import Magneto2DSolver

    sources = {*physics_sources(ROOT), "backend/reference_models/prius.py", "backend/reference_models/pyleecan_prius_2004.json",
               "backend/reference_models/pyleecan_prius_2004_config.json", "backend/models/config.py", "backend/public_policy.py",
               "backend/topology_provenance.py", "tools/benchmark_prius.py"}
    binary = ensure_magneto2d_binary()
    hashes = {name: digest(ROOT / name) for name in sorted(sources)}
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).decode().splitlines()
    registration = {
        "schema": "coilem.pyleecan_prius_app_benchmark/v1", "started_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        "source_dirty": bool(status), "worktree_status": status, "source_sha256": hashes,
        "binary_sha256": digest(binary), "platform": platform.platform(), "python": platform.python_version(),
        "dependencies": {name: importlib.metadata.version(name) for name in ("gmsh", "numpy", "pydantic")},
        "source_machine_sha256": prius.source()["source_machine_sha256"], "geometry_asset_sha256": prius.geometry_asset_sha256(),
        "scope": "Development-candidate software reproduction; final v0.4.0 candidate rerun remains required",
        "qualified": False, "jobs": [],
    }
    write(destination / "registration.json", registration)
    selected = [(name, body) for name, body in jobs(args.curve, args.refinement) if not args.only or name == args.only]
    if not selected:
        ap.error("--only does not match a selected job")
    for name, body in selected:
        cfg = parse_public_motor_config(body)
        folder = destination / name
        folder.mkdir()
        write(folder / "request.json", cfg.model_dump(mode="json"))
        write(folder / "environment.json", _magneto2d_env_overrides(cfg))
        print(f"Starting {name}", flush=True)
        last_update = 0.0

        def progress(position, total, torque, stage, angle=None, *rest):
            nonlocal last_update
            now = time.monotonic()
            if now - last_update > 25 or position == total:
                print(f"{name}: {stage} {position}/{total}, electrical angle {angle}", flush=True)
                last_update = now

        started = time.monotonic()
        result = Magneto2DSolver(launch_surface=True).solve(cfg, on_progress=progress)
        elapsed = time.monotonic() - started
        raw = result.model_dump(mode="json")
        # Keep the original result locally; the portable copy removes local cache paths.
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
                    import shutil
                    shutil.copyfileobj(src, dst)
                artifacts.append({"file": relative.as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)})
        write(folder / "artifact-index.json", artifacts)
        entry = {"job": name, "case_id": cfg.reference_case, "request_sha256": digest(folder / "request.json"),
                 "result_sha256": digest(folder / "result.json"), "artifact_index_sha256": digest(folder / "artifact-index.json"),
                 "environment": _magneto2d_env_overrides(cfg), "request": cfg.model_dump(mode="json"),
                 "metrics": metrics, "torque_waveform": raw["torque_waveform"], "back_emf_waveform": raw["back_emf_waveform"],
                 "solve_metadata": portable["solve_metadata"]}
        registration["jobs"].append(entry)
        write(destination / "registration.json", registration)
        print(f"Completed {name}: {metrics}", flush=True)
    if any(digest(ROOT / name) != sha for name, sha in hashes.items()):
        raise RuntimeError("Measured physics sources changed while the benchmark ran")
    registration["complete"] = True
    registration["finished_utc"] = datetime.now(timezone.utc).isoformat()
    write(destination / "registration.json", registration)


if __name__ == "__main__":
    main()
