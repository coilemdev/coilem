"""Measure one public native job. No reference solver, adapter or installation discovery."""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

from tools.benchmark_suite.contract import ROOT, canonical, identity, now, read, run_lock, sha, write


def compact(result):
    metadata = result["solve_metadata"]
    torque = result["torque_waveform"]
    return {
        **{
            k: metadata.get(k)
            for k in ("solver_name", "mesh_element_count", "mesh_density", "mesh_source", "torque_method", "loaded_cycle_complete", "solve_time_s")
        },
        "electrical_angle_deg": [a % 360 for a in torque["electrical_angle_deg"]],
        "torque_Nm": torque["torque_Nm"],
        **{
            k: {**result[k], "electrical_angle_deg": [a % 360 for a in result[k]["electrical_angle_deg"]]}
            for k in ("phase_current_waveform", "back_emf_waveform")
            if result.get(k)
        },
    }


def measure(args):
    request = read(args.request)
    start = time.perf_counter()
    data = {"schema": "coilem.native_measurement/v1", "started_at": now(), "request_sha256": sha(args.request)}
    try:
        from backend.public_policy import parse_public_solve_request
        from backend.solver import Magneto2DSolver
        from backend.solver_environment import ISOLATED_RUNTIME

        if not ISOLATED_RUNTIME:
            raise ValueError("Public request-only solver environment is required")
        binary = ROOT / request["binary"]
        before = identity(binary)
        if before != request["identity"] or canonical(request["config"]) != request["config_sha256"]:
            raise ValueError("Registered runtime or request changed")
        config, _, solver = parse_public_solve_request(request["config"])
        if solver != "magneto2d":
            raise ValueError("This suite measures only public Magneto2D")
        measured = Magneto2DSolver(launch_surface=True).solve(config, on_progress=lambda *a, **k: print(*a[:4], flush=True))
        data["result"] = measured.model_dump(
            mode="json", include={"summary", "torque_waveform", "back_emf_waveform", "phase_current_waveform", "solve_metadata"}
        )
        data["resolved_config"] = config.model_dump(mode="json")
        data["identity_before"] = before
        data["identity_after"] = identity(binary)
        if data["identity_after"] != before:
            raise ValueError("Runtime changed during solve")
        imports = {}
        for name, module in tuple(sys.modules.items()):
            if (name == "backend" or name.startswith("backend.")) and getattr(module, "__file__", None):
                path = Path(module.__file__).resolve()
                if not path.is_relative_to(ROOT):
                    raise ValueError(f"Backend import outside candidate checkout: {name}")
                relative = path.relative_to(ROOT).as_posix()
                if sha(path) != before["source_files"][relative]:
                    raise ValueError(f"Imported source changed: {name}")
                imports[name] = {"path": relative, "sha256": sha(path)}
        data.update(status="COMPLETE", backend_imports=imports)
    except Exception as exc:
        data.update(status="ERROR", error=str(exc), traceback=traceback.format_exc())
    data.update(completed_at=now(), runtime_s=time.perf_counter() - start)
    write(args.output, data)
    return 0 if data["status"] == "COMPLETE" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with run_lock(args.output.parent):
        if args.output.exists():
            raise ValueError("Refusing to overwrite an existing native measurement")
        return measure(args)


if __name__ == "__main__":
    raise SystemExit(main())
