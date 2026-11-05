"""Local experimental UI adapter using the unchanged generic Magneto2D core."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

import numpy as np

from backend.experimental.femm_outrunner import build_field_problem, phase_linkage, source
from backend.experimental.outrunner_geometry import build_ir, generate_native_mesh
from backend.experimental.outrunner_project import OutrunnerProject, OutrunnerRunRequest
from backend.experimental.outrunner_stress import weighted_stress_torque
from backend.experimental.outrunner_sweep import PERIOD_DEG, SweepCase, bemf, fundamental
from backend.magneto2d_adapter import ensure_magneto2d_binary, start_native_process, track_native_process
from backend.resources import source_checkout_root
from backend.solve_workspace import user_data_root
from backend.solver_environment import solver_process_environment

_LOCK = threading.Lock()
_ACTIVE: dict[str, threading.Event] = {}


def enabled() -> bool:
    return os.environ.get("COILEM_EXPERIMENTAL_OUTRUNNER") == "1" and source_checkout_root() is not None


def _root() -> Path:
    return user_data_root()/"experimental"/"femm-outrunner"


def _folder(run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid experimental run identifier")
    return _root()/run_id


def _write(path: Path, data: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, allow_nan=False, indent=2)+"\n", encoding="utf-8")
    temp.replace(path)


def preview(project: OutrunnerProject) -> dict:
    regions = []
    for region in build_ir().regions:
        if region.kind == "Airgap":
            continue
        loops = []
        for loop in region.loops:
            points = []
            for segment in loop.segments:
                if segment.kind == "line":
                    points.append([segment.start.x_mm, segment.start.y_mm])
                else:
                    center, radius, sweep = segment.center, segment.radius_mm, segment.sweep_deg
                    assert center is not None and radius is not None and sweep is not None
                    start = math.atan2(segment.start.y_mm-center.y_mm, segment.start.x_mm-center.x_mm)
                    for angle in np.linspace(start, start+math.radians(sweep), max(2, math.ceil(abs(sweep)/0.5)), endpoint=False):
                        points.append([center.x_mm+radius*math.cos(angle), center.y_mm+radius*math.sin(angle)])
            loops.append(points)
        label = source()["labels"][int(region.region_id.removeprefix("source_block_"))]
        regions.append({"id": region.region_id, "kind": region.kind, "loops": loops, "phase": label["circuit"],
                        "signed_turns": label["signed_turns"], "material": label["material"]})
    return {"fixture_id": project.fixture_id, "regions": regions, "outer_radius_mm": 15.39,
            "pole_count": 14, "slot_count": 12, "stack_length_mm": 10, "airgap_mm": 0.2}


def _solve_case(case: SweepCase, project: OutrunnerProject, binary: Path, folder: Path, cancel: threading.Event) -> dict:
    folder.mkdir()
    start = time.monotonic()
    mesh = generate_native_mesh(case.angle_ccw_deg, project.analysis.gap_size_mm)
    if cancel.is_set():
        raise InterruptedError("Cancelled")
    problem = build_field_problem(mesh, tuple(case.currents_A), case.angle_ccw_deg)
    problem["options"]["nonlinear"]["tolerance"] = project.analysis.nonlinear_tolerance
    input_path, output_path = folder/"problem.json", folder/"field.json"
    input_path.write_text(json.dumps(problem, allow_nan=False), encoding="utf-8")
    mesh_path = folder/"mesh.json"
    mesh_path.write_text(json.dumps({"nodes_mm": mesh.nodes_mm.tolist(), "triangles": mesh.triangles.tolist(),
                                    "label_ids": mesh.label_ids.tolist(), "dirichlet_nodes": mesh.dirichlet_nodes.tolist(),
                                    "provenance": mesh.provenance}, allow_nan=False), encoding="utf-8")
    process = start_native_process([str(binary), str(input_path), "--mode", "field", "-o", str(output_path)],
                                   cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=solver_process_environment())
    with track_native_process(process):
        try:
            while True:
                if cancel.is_set():
                    raise InterruptedError("Cancelled")
                if time.monotonic()-start > 300:
                    raise TimeoutError("Experimental point exceeded 300 seconds")
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            (folder/"stdout.txt").write_text(stdout)
            (folder/"stderr.txt").write_text(stderr)
            if process.returncode:
                raise RuntimeError(f"Magneto2D failed: {stderr[-1000:]}")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    solution = json.loads(output_path.read_text())["solution"]
    if not solution["convergence"]["converged"]:
        raise RuntimeError("Nonconverged field")
    az = np.asarray(solution["az_nodal"])
    stress = weighted_stress_torque(mesh, az)
    row = {"case": case.to_dict(), "outer_rotor_torque_Nm": stress["outer_rotor_torque_Nm"],
           "phase_linkage_Wb": phase_linkage(mesh, az).tolist(), "convergence": solution["convergence"],
           "weighted_stress": stress, "nodes": len(mesh.nodes_mm), "elements": len(mesh.triangles),
           "elapsed_s": time.monotonic()-start, "raw_sha256": {}}
    for path in (input_path, output_path, mesh_path):
        raw = path.read_bytes()
        row["raw_sha256"][path.name] = hashlib.sha256(raw).hexdigest()
        with gzip.open(path.with_suffix(path.suffix+".gz"), "wb", compresslevel=3) as stream:
            stream.write(raw)
        path.unlink()
    _write(folder/"result.json", row)
    return row


def _curves(rows: list[dict], project: OutrunnerProject) -> dict:
    result = {}
    for family in ("loaded", "noload"):
        selected = [r for r in rows if r["case"]["family"] == family]
        if not selected:
            continue
        flux = np.asarray([r["phase_linkage_Wb"] for r in selected])
        curve = {"angles_mechanical_ccw_deg": [r["case"]["angle_ccw_deg"] for r in selected],
                 "angles_electrical_deg": [r["case"]["angle_ccw_deg"]*7 for r in selected],
                 "torque_Nm": [r["outer_rotor_torque_Nm"] for r in selected], "phase_linkage_Wb": flux.tolist()}
        if family == "noload" and len(selected) == project.analysis.unique_samples+1:
            e = bemf(flux[:-1], project.analysis.speed_rpm)
            curve["bemf_phase_V"] = e.tolist()
            curve["bemf_line_to_line_V"] = (e-np.roll(e, -1, axis=1)).tolist()
            curve["bemf_phase_fundamental"] = fundamental(e)
            curve["bemf_central4_V"] = bemf(flux[:-1], project.analysis.speed_rpm, "central4").tolist()
            curve["linkage_closure_Wb"] = (flux[-1]-flux[0]).tolist()
        result[family] = curve
    return result


def _worker(run_id: str, request: OutrunnerRunRequest, cancel: threading.Event) -> None:
    folder = _folder(run_id)
    rows: list[dict] = []
    cases = []
    count = request.project.analysis.unique_samples
    if request.analysis == "source_point":
        cases.append(SweepCase("source_point", 0, tuple(request.project.analysis.loaded_currents_A), "source_point", "full"))
    for family in ("loaded", "noload"):
        if request.analysis not in ("both", "loaded_torque" if family == "loaded" else "noload_bemf"):
            continue
        currents = tuple(request.project.analysis.loaded_currents_A) if family == "loaded" else (0, 0, 0)
        cases.extend(SweepCase(f"{family}_{i:04d}", PERIOD_DEG*i/count, currents, family) for i in range(count+1))
    state = {"run_id": run_id, "status": "RUNNING", "completed": 0, "total": len(cases), "qualification": "DIAGNOSTIC_ONLY"}
    _write(folder/"state.json", state)
    try:
        binary = ensure_magneto2d_binary().resolve()
        binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
        identity_path = folder/"identity.json"
        identity = {"binary_sha256": binary_sha, "source_sha256": request.project.source_sha256,
                    "asset_sha256": request.project.fixture_asset_sha256}
        if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
            raise ValueError("Resume requires the identical binary and frozen fixture")
        _write(identity_path, identity)
        for case in cases:
            if cancel.is_set():
                raise InterruptedError("Cancelled")
            case_folder = folder/case.id
            if (case_folder/"result.json").exists():
                row = json.loads((case_folder/"result.json").read_text())
                if row["case"] != json.loads(json.dumps(case.to_dict())):
                    raise ValueError("Stored request differs")
                for name, expected in row["raw_sha256"].items():
                    with gzip.open(case_folder/(name+".gz"), "rb") as stream:
                        if hashlib.sha256(stream.read()).hexdigest() != expected:
                            raise ValueError("Stored raw field evidence changed")
            else:
                if case_folder.exists():
                    case_folder.rename(case_folder.with_name(case.id+f"_interrupted_{time.time_ns()}"))
                row = _solve_case(case, request.project, binary, case_folder, cancel)
            rows.append(row)
            state.update(completed=len(rows), rows=rows, curves=_curves(rows, request.project))
            _write(folder/"state.json", state)
        state["status"] = "COMPLETE"
    except InterruptedError:
        state["status"] = "CANCELLED"
    except Exception as exc:
        state.update(status="ERROR", error=str(exc))
    finally:
        _write(folder/"state.json", state)
        with _LOCK:
            _ACTIVE.pop(run_id, None)


def start(request: OutrunnerRunRequest, run_id: str | None = None) -> dict:
    with _LOCK:
        if _ACTIVE:
            raise ValueError("An experimental outrunner analysis is already running")
        if run_id:
            folder = _folder(run_id)
            saved = OutrunnerRunRequest.model_validate_json((folder/"request.json").read_text())
            if saved != request:
                raise ValueError("Resume requires the original saved design and analysis")
        else:
            run_id = uuid.uuid4().hex
            folder = _folder(run_id)
            folder.mkdir(parents=True)
            _write(folder/"project.coilem", request.project.model_dump())
            _write(folder/"request.json", request.model_dump())
        cancel = threading.Event()
        _ACTIVE[run_id] = cancel
        _write(folder/"state.json", {"run_id": run_id, "status": "QUEUED", "completed": 0, "total": 0})
        threading.Thread(target=_worker, args=(run_id, request, cancel), daemon=True).start()
    return {"run_id": run_id, "status": "QUEUED"}


def status(run_id: str) -> dict:
    state = json.loads((_folder(run_id)/"state.json").read_text())
    with _LOCK:
        if state["status"] in ("QUEUED", "RUNNING") and run_id not in _ACTIVE:
            state["status"] = "INTERRUPTED"
    return state


def cancel(run_id: str) -> dict:
    _folder(run_id)
    with _LOCK:
        if run_id in _ACTIVE:
            _ACTIVE[run_id].set()
    return status(run_id)
