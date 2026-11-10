"""New batched execution identity over the unchanged sealed Phase F field functions."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from tools.femm_reference import hub, phase_f
from tools.femm_reference import runtime as runtime_module

runtime = runtime_module

WORKSPACE = runtime.PACKAGE.parents[1]
LRK = runtime.DATA / "inherited_lrk.json"
CONFIG = runtime.DATA / "jobs.json"
TIMINGS = CONFIG


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def library():
    return phase_f, hub


def identity():
    return runtime.identity("f")


def cases():
    settings = read(CONFIG)
    historical = settings["f_jobs"]
    result = {}
    for alias, job in settings["f_jobs"].items():
        positions = [
            {"id": f"{stage}-{i:02d}", "stage": stage, "index": i, "electrical_angle_deg": i * 7.5, "estimated_s": historical[alias]["estimated_s"]}
            for stage in ("loaded", "noload")
            for i in range(48)
        ]
        result[alias] = {"phase": "F", "request": job, "positions": positions}
    return result


def context(case_id):
    job = cases()[case_id]["request"]
    base, hub = library()
    runtime = base.load_runtime()
    config, spec, registered, steel = base.input_contract(runtime, job["case_id"])
    return job, base, hub, runtime, config, spec, registered, steel


def prepare(case_id):
    job, base, hub, runtime, config, spec, registered, steel = context(case_id)
    preflight = (
        hub.preflight(base, runtime, config, steel, job["bulk_mesh_mm"])
        if job["bulk_mesh_mm"] is not None
        else base.preflight(runtime, config, steel, "production", job["airgap_mesh_scale"])
    )
    return {
        "preflight": preflight,
        "original_request": registered,
        "material_contract": spec["material_contract"],
        "inherited_lrk": base.inherited_lrk(LRK),
        "derivative_policy": base.DERIVATIVE_POLICY,
        "field_solves_executed": 0,
    }


@contextmanager
def open_batch(case_id, directory, prepared):
    job, base, hub, runtime, config, spec, registered, steel = context(case_id)
    if prepared["original_request"] != registered or prepared["material_contract"] != spec["material_contract"]:
        raise ValueError("Prepared request or material contract changed")
    if prepared["inherited_lrk"] != base.inherited_lrk(LRK):
        raise ValueError("Inherited LRK evidence changed")
    automation = runtime["lrk"].Automation(directory)
    try:
        automation.open(1)
        session = base.actual_session_identity(automation, read(runtime_module.DATA / "femm-binaries.json"))

        def measure(position, output):
            started = time.perf_counter()
            stage, index, theta = position["stage"], position["index"], position["electrical_angle_deg"]
            if stage not in ("loaded", "noload") or base.GRID[index] != theta:
                raise ValueError("F position differs from original registered grid")
            ir, native = base.rotated_ir(runtime, config, theta)
            currents = base.driver_vector(runtime, config, theta, "production") if stage == "loaded" else (0.0, 0.0, 0.0)
            stem = f"{stage}-{index:02d}"
            base.write(output / (stem + "-ir.json"), dataclasses.asdict(ir))
            settings = (
                hub.lower(base, automation.femm, runtime, config, ir, currents, steel, job["bulk_mesh_mm"])
                if job["bulk_mesh_mm"] is not None
                else base.lower_model(automation.femm, runtime, config, ir, currents, steel, job["airgap_mesh_scale"])
            )
            model = output / (stem + ".fem")
            automation.femm.mi_saveas(str(model))
            base.write(output / (stem + "-settings.json"), settings)
            automation.femm.mi_analyze(1)
            automation.femm.mi_loadsolution()
            point = {
                "stage": stage,
                "index": index,
                "electrical_angle_deg": theta,
                "native_mechanical_angle_deg": native,
                "commanded_terminal_current_A": currents,
                "settings": settings,
                **base.extract(automation.femm, config, ir, settings, currents),
                "model_sha256": sha(model),
                "answer_sha256": sha(model.with_suffix(".ans")),
                "runtime_s": time.perf_counter() - started,
                "owned_session": session,
            }
            automation.femm.mo_close()
            automation.femm.mi_close()
            return point, sorted(p for p in output.iterdir() if p.is_file())

        yield measure
    finally:
        try:
            if automation.sessions:
                automation.femm.closefemm()
        finally:
            automation.close()


def assemble(case_id, points, prepared):
    job, base, hub, runtime, config, spec, registered, steel = context(case_id)
    result, checks, derivative = base.assemble_result(config, points, job["case_id"])
    if job["bulk_mesh_mm"] is not None:
        result["solve_metadata"].update(
            other_mesh_size_mm=job["bulk_mesh_mm"],
            base_other_mesh_size_mm=0.25,
            magnet_and_pocket_mesh_size_mm=0.15,
            mesh_variant_recipe=hub.recipe(job["bulk_mesh_mm"]),
        )
    return {
        "status": "COMPLETE",
        "case_id": job["case_id"],
        "phase": "F",
        "full_reference_complete": True,
        "validation_status": "REVIEW_REQUIRED",
        "execution_identity": identity(),
        "input_sha256": registered["input_sha256"],
        "request_bindings": job["requests"],
        "result": result,
        "self_checks": checks,
        "derivative_evidence": derivative,
        "inherited_lrk": prepared["inherited_lrk"],
        "field_solves_executed": len(points),
    }
