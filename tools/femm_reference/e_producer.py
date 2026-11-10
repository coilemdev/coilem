"""Batched cogging positions with the original Phase E lowering, meshes and audits."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

from tools.femm_reference import phase_e, runtime

WORKSPACE = runtime.PACKAGE.parents[1]
TIMINGS = runtime.DATA / "jobs.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def library():
    return phase_e


def identity():
    return runtime.identity("e")


def cases():
    base = library()
    suite, registered = base.inputs()
    timings = json.loads(TIMINGS.read_text())
    result = {}
    for i, row in enumerate(timings["e_jobs"]):
        case_id = row["case_id"]
        case = registered[case_id]
        raw = base.read(base.PUBLIC / case["jobs"][0]["fixture"])
        period = 180 * math.gcd(raw["stator"]["slot_count"], raw["rotor"]["pole_count"]) / raw["stator"]["slot_count"]
        result[f"e{i:02d}"] = {
            "phase": "E",
            "case_id": case_id,
            "kind": row["kind"],
            "mesh_scale": 1.0 if row["kind"] == "normal" else 0.5,
            "original_request": case["jobs"][0],
            "positions": [
                {
                    "id": f"cogging-{index:02d}",
                    "stage": "cogging",
                    "index": index,
                    "electrical_angle_deg": index * period / 24,
                    "estimated_s": row["estimated_s"],
                }
                for index in range(25)
            ],
        }
    return result


def context(case_id):
    base = library()
    case = cases()[case_id]
    spec, registered = base.inputs()
    Solver, Model, geometry, curve, magnets, femm, pilot, v3 = base.load_adapter()
    raw = base.read(base.PUBLIC / case["original_request"]["fixture"])
    config = Model.model_validate(raw)
    for key in tuple(os.environ):
        if key != "COILEM_FEMM_BIN" and key.startswith(("COILEM_", "OPENEM_", "FEMM_")):
            os.environ.pop(key)
    magnet = spec["material_contract"]["magnets"][config.materials.magnet_grade]
    os.environ["OPENEM_MAGNET_BR_SCALE"] = str(magnet["Br_T"] / magnets[config.materials.magnet_grade]["remanence_T"])
    geom = geometry(config)
    from backend.femm_geometry import _femm_airgap_width_mm

    gap_target = min(0.25, _femm_airgap_width_mm(geom) / 4) * case["mesh_scale"]
    os.environ["FEMM_AIRGAP_MESHSIZE_MM"] = str(gap_target)
    assert curve("M350-50A").sha256 == spec["material_contract"]["curve_sha256"]
    config.solve_params.current_amplitude_A = 0.0
    assert config.solve_params.mesh_density == "normal"
    return base, case, registered[case["case_id"]], config, geom, magnet, gap_target, Solver, femm, pilot, v3


def prepare(case_id):
    base, case, registered, config, geom, magnet, gap, Solver, femm, pilot, v3 = context(case_id)
    assert not v3.regions(config, geom).validation_report().issues
    return {
        "original_request": registered["jobs"][0],
        "reference_config_zero_current": config.model_dump(mode="json"),
        "gap_target_mm": gap,
        "positions": case["positions"],
        "field_solves_executed": 0,
    }


@contextmanager
def open_batch(case_id, directory, prepared):
    base, case, registered, config, geom, magnet, gap, Solver, femm, pilot, v3 = context(case_id)
    from backend.femm_extraction import _parse_femm_block_label_metadata

    if prepared["reference_config_zero_current"] != config.model_dump(mode="json") or prepared["gap_target_mm"] != gap:
        raise ValueError("E preflight request or mesh changed")
    automation = pilot.Automation(directory)
    pairs = config.rotor.pole_count / 2
    try:

        def measure(position, output):
            index, angle = position["index"], position["electrical_angle_deg"]
            if case["positions"][index] != position:
                raise ValueError("E position differs from original registered grid")
            started = time.perf_counter()
            model = output / "model.fem"
            automation.open(1)
            try:
                solver = Solver()
                solver._last_geom = geom
                offset = -math.radians(angle / pairs)
                solver._last_rotor_offset_rad = offset
                solver._setup_problem(femm, config, geom)
                femm.mi_probdef(0, "millimeters", "planar", 1e-8, config.stator.stack_length_mm, 30, 0)
                solver._draw_full_geometry(femm, config, geom, rotor_offset_deg=math.degrees(offset))
                winding = v3.winding_regions(config, geom)
                for region in winding:
                    point = v3.label_point(region)
                    femm.mi_addblocklabel(*point)
                    femm.mi_selectlabel(*point)
                    solver._set_femm_blockprop(femm, "Coil", config, geom, "slot")
                    femm.mi_clearselected()
                solver._apply_boundary(femm, geom)
                femm.mi_saveas(str(model))
                labels = _parse_femm_block_label_metadata(str(model))
                assert labels and all(abs(label["current_density_a_per_m2"] or 0.0) < 1e-15 for label in labels)
                expected_hc = magnet["Br_T"] / (magnet["mu_r"] * 4 * math.pi * 1e-7)
                coercivities = [float(v) for v in re.findall(r"<H_c>\s*=\s*([-+\d.eE]+)", model.read_text(encoding="latin-1"))]
                magnetic = [v for v in coercivities if v > 0]
                assert len(magnetic) == len(geom.magnets) + 1
                assert all(math.isclose(v, expected_hc, rel_tol=1e-12) for v in magnetic)
                solve_started = time.perf_counter_ns()
                femm.mi_createmesh()
                femm.mi_analyze(1)
                answer = model.with_suffix(".ans")
                assert answer.is_file() and answer.stat().st_size > 0
                femm.mi_loadsolution()
                elements, nodes = int(femm.mo_numelements()), int(femm.mo_numnodes())
                assert elements > 0 and nodes > 0
                torque = float(solver._extract_torque(femm))
                assert math.isfinite(torque)
                audits = []
                for region in winding:
                    femm.mo_clearblock()
                    femm.mo_selectblock(*v3.label_point(region))
                    current = float(femm.mo_blockintegral(7))
                    area = float(femm.mo_blockintegral(5)) * 1e6
                    assert abs(current) <= 1e-10
                    assert abs(area - region.area_mm2) <= max(1e-5, region.area_mm2 * 0.005)
                    audits.append(
                        {"region_id": region.region_id, "integrated_current_A": current, "area_mm2": area, "expected_area_mm2": region.area_mm2}
                    )
                femm.mo_clearblock()
                point = {
                    "index": index,
                    "electrical_angle_deg": angle,
                    "mechanical_angle_deg": angle / pairs,
                    "raw_femm_mechanical_angle_deg": -angle / pairs,
                    "raw_femm_torque_Nm": torque,
                    "torque_Nm": -torque,
                    "mesh_elements": elements,
                    "mesh_nodes": nodes,
                    "field_and_mesh_s": (time.perf_counter_ns() - solve_started) / 1e9,
                    "wall_s": time.perf_counter() - started,
                    "source_audit": audits,
                    "material_blocks": labels,
                    "magnet_coercivities_A_per_m": magnetic,
                    "fem_sha256": sha(model),
                    "ans_sha256": sha(answer),
                }
                femm.mo_close()
                femm.mi_close()
                return point, sorted(p for p in output.iterdir() if p.is_file())
            finally:
                femm.closefemm()

        yield measure
    finally:
        automation.close()


def assemble(case_id, points, prepared):
    base = library()
    case = cases()[case_id]
    _, registered = base.inputs()
    expected = case["positions"]
    assert [p["index"] for p in points] == list(range(25))
    assert [p["electrical_angle_deg"] for p in points] == [p["electrical_angle_deg"] for p in expected]
    metrics = base.summary([p["torque_Nm"] for p in points])
    floor = registered[case["case_id"]]["cogging_floor_Nm"]
    return {
        "status": "COMPLETE",
        "phase": "E",
        "case_id": case["case_id"],
        "validation_status": "REVIEW_REQUIRED",
        "execution_identity": identity(),
        "input_sha256": case["original_request"]["input_sha256"],
        "metrics": metrics,
        "field_solves_executed": len(points),
        "self_checks": {
            "reference_cogging_period": "PASS" if metrics["endpoint_mismatch_Nm"] <= floor else "FAIL",
            "reference_cogging_mean": "PASS" if abs(metrics["mean_Nm"]) <= floor else "FAIL",
        },
        "result": {
            "summary": {"cogging_torque_Nm": metrics["peak_to_peak_Nm"]},
            "cogging_torque_waveform": {
                "electrical_angle_deg": [p["electrical_angle_deg"] for p in expected],
                "mechanical_angle_deg": [p["mechanical_angle_deg"] for p in points],
                "torque_Nm": [p["torque_Nm"] for p in points],
            },
            "solve_metadata": {
                "femm_version": "4.2",
                "torque_method": "weighted_stress_tensor",
                "precision": 1e-8,
                "min_angle_deg": 30,
                "airgap_mesh_size_mm": prepared["gap_target_mm"],
                "mesh_element_count": [p["mesh_elements"] for p in points],
                "normalization": "theta_FEMM=-theta_public; torque_public=-torque_FEMM",
            },
        },
    }
