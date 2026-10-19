"""Loaded Magneto controls on published Pyleecan and corrected Prius meshes."""

import argparse
import copy
import gzip
import hashlib
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from backend.custom_materials import CustomSteel
from backend.magneto2d_adapter import build_magneto2d_command, ensure_magneto2d_binary
from backend.solver_environment import solver_process_environment
from tools.pyleecan_prius_mesh_compare import artifact_for, parse


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def record_current_provenance(artifact, currents):
    provenance = artifact["physics_contract"].setdefault("provenance", {})
    provenance["current_density_source"] = "signed_phase_currents_and_meshed_coil_areas"
    provenance["element_current_density_sources"] = ["explicit_signed_phase_current"] * len(artifact["mesh"]["triangles"])
    provenance["phase_current_A"] = np.asarray(currents, dtype=float).tolist()


def assign_currents(artifact, currents):
    """Explicit signed ampere turns divided by each actual meshed coil-side area."""
    currents = np.asarray(currents, dtype=float)
    if currents.shape != (3,) or not np.isfinite(currents).all() or abs(currents.sum()) > 1e-8:
        raise ValueError("Three finite balanced phase currents required")
    mesh = artifact["mesh"]
    xy = np.asarray(mesh["nodes"], dtype=float) * 1e-3
    tri = np.asarray(mesh["triangles"], dtype=int)
    a = xy[tri[:, 1]] - xy[tri[:, 0]]
    b = xy[tri[:, 2]] - xy[tri[:, 0]]
    area = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) / 2
    ids = np.asarray(artifact["element_region_ids"])
    assignments = {}
    audit = []
    for region in artifact["physics_contract"]["regions"]:
        density = 0.0
        if region["kind"] == "SlotWinding":
            winding = region["winding"]
            if winding["layers"] != 1 or winding["parallel_paths"] != 1:
                raise ValueError("This reference requires one layer and one series path")
            selected = ids == region["id"]
            slot_area = float(area[selected].sum())
            if slot_area <= 0:
                raise ValueError("Empty winding region")
            sign = 1 if winding["direction"] == "in" else -1
            amp_turns = sign * winding["turns_per_coil"] * winding["turn_fraction"] * currents["ABC".index(winding["phase"])]
            density = float(amp_turns / slot_area)
            region["current_density_a_per_m2"] = density
            audit.append({"region": region["id"], "phase": winding["phase"], "area_m2": slot_area,
                          "ampere_turns": float(amp_turns), "density_A_per_m2": density})
        assignments[region["id"]] = density
    artifact["element_current_density_a_per_m2"] = [assignments[x] for x in ids]
    if not math.isclose(float(np.dot(artifact["element_current_density_a_per_m2"], area)), 0, abs_tol=1e-7):
        raise ValueError("Net axial current does not cancel")
    record_current_provenance(artifact, currents)
    return audit


def override_steel(request, artifact, steel):
    """Change both steel roles and their imported region references, without remeshing."""
    steel = CustomSteel.model_validate(steel)
    previous = {role: request["materials"][f"{role}_steel"] for role in ("stator", "rotor")}
    selected = []
    counts = {role: 0 for role in previous}
    for region in artifact["physics_contract"]["regions"]:
        if region["material"].startswith("steel:"):
            _, role, material = region["material"].split(":", 2)
            if role not in previous or material != previous[role]:
                raise ValueError("Steel region disagrees with the source input")
            selected.append((region, role))
            counts[role] += 1
    if not all(counts.values()):
        raise ValueError("Both stator and rotor steel regions are required")
    for region, role in selected:
        region["material"] = f"steel:{role}:{steel.id}"
    request["materials"].update(stator_steel=steel.id, rotor_steel=steel.id)
    request["materials"].setdefault("custom_steels", {})[steel.id] = steel.model_dump(mode="json")
    return {"previous_steel": previous, "replacement": steel.model_dump(mode="json"), "region_counts": counts}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--femm", type=Path, required=True)
    ap.add_argument("--native-input", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--corrected-baseline", type=Path)
    ap.add_argument("--steel-from", type=Path, help="Use only the common custom stator/rotor steel from this input JSON")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    steel_override = None
    if args.steel_from:
        if not args.corrected_baseline:
            ap.error("--steel-from requires --corrected-baseline for the controlled fixture comparison")
        materials = json.loads(args.steel_from.read_text())["materials"]
        if materials["stator_steel"] != materials["rotor_steel"]:
            ap.error("--steel-from requires the same custom steel in both roles")
        steel_override = CustomSteel.model_validate(materials["custom_steels"][materials["stator_steel"]])
    args.out.mkdir(parents=True, exist_ok=args.resume)
    registration = json.loads((args.femm / "registration.json").read_text())
    binary = ensure_magneto2d_binary()
    options = {
        "MAGNETO2D_NONLINEAR_TOL": "1e-8", "MAGNETO2D_NEWTON_TOL": "1e-9",
        "MAGNETO2D_NONLINEAR_MAX_ITER": "200", "MAGNETO2D_LINEAR_SOLVER": "direct",
        "MAGNETO2D_PCG_PRECONDITIONER": "ic0", "RAYON_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
        "COILEM_MAGNET_BR_SCALE": ".96",
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_TORQUE": "1",
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_PRIMARY": "1",
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_AIRGAP_ONLY": "1",
        "COILEM_MAGNETO2D_WEIGHTED_STRESS_ELEMENT_B": "1",
    }
    identity = {
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "FEMM_registration_sha256": hashlib.sha256((args.femm / "registration.json").read_bytes()).hexdigest(),
        "model": "corrected" if args.corrected_baseline else "published-pyleecan",
        "options": options, "expected_poses": registration["points"] * len(registration["current_angles_deg"]),
        "angle_policy": (
            "Published Pyleecan rotor/current axes; corrected geometry d-axis zero at 285 electrical degrees, "
            "established independently by no-load flux (phase A offset +75 degrees). No torque fit."
        ),
        "limits": {"relative_nodal_Az": .005, "relative_phase_linkage": .005,
                   "mean_solver_torque_relative": .02, "mean_torque_sampling_change": .01,
                   "nonlinear_residual": 1e-8},
    }
    if steel_override:
        identity["model"] = "corrected-steel-control"
        identity["steel_override"] = {
            "replacement": steel_override.model_dump(mode="json"),
            "source_input_sha256": hashlib.sha256(args.steel_from.read_bytes()).hexdigest(),
            "policy": "Replace only stator/rotor steel and material references; reuse the exact corrected mesh and all other inputs",
        }
    if args.resume:
        assert json.loads((args.out / "registration.json").read_text()) == identity
    else:
        write(args.out / "registration.json", identity)
    template = json.loads(args.native_input.read_text())
    template.pop("openem_provenance", None)
    rows = []
    for src in sorted(args.femm.glob("phi-*/pose-*/result.json")):
        source = json.loads(src.read_text())
        case = args.out / src.parent.parent.name / src.parent.name
        if args.resume and (case / "result.json").exists():
            rows.append(json.loads((case / "result.json").read_text()))
            continue
        if shutil.disk_usage(args.out).free < .6 * 2**30:
            raise RuntimeError("Insufficient disk headroom")
        case.mkdir(parents=True, exist_ok=False)
        request = copy.deepcopy(template)
        if args.corrected_baseline:
            electrical = (285 + source["time_electrical_angle_deg"]) % 360
            baseline = args.corrected_baseline / f"2d-fine-e{electrical:03g}"
            artifact = json.loads(gzip.decompress((baseline / "mesh.json.gz").read_bytes()))
            request = json.loads((baseline / "input.json").read_text())
            request.pop("openem_provenance", None)
            parsed_flux = None
            femm_nodes = None
        else:
            electrical = source["rotor_angle_mech_deg"] * 4
            artifact, steel, parsed_flux = artifact_for(src.parent / "motor.fem", electrical, expected_remanence_t=1.1904)
            request["materials"].update(stator_steel=steel.id, rotor_steel=steel.id,
                                        custom_steels={steel.id: steel.model_dump(mode="json")})
            _, _, _, femm_nodes, _ = parse(src.parent / "motor.fem")
        audit = assign_currents(artifact, source["phase_current_A"])
        steel_audit = override_steel(request, artifact, steel_override) if steel_override else None
        request["solve_params"].update(current_amplitude_A=250, current_amplitude_convention="peak",
                                       current_angle_deg=source["current_angle_deg"], rated_speed_rpm=2000)
        request["solve_options"].update(torque_sweep=True, back_emf=False)
        write(case / "input.json", request)
        (case / "mesh.json").write_text(json.dumps(artifact, separators=(",", ":")), encoding="utf-8")
        command = build_magneto2d_command(case / "input.json", case / "report.json", rotor_angle_deg=electrical / 4,
                                         solve_mesh_path=case / "mesh.json", executable=binary)
        t = time.monotonic()
        p = subprocess.run(command, cwd=case, capture_output=True, text=True, env=solver_process_environment(options), timeout=240)
        (case / "stdout.log").write_text(p.stdout, encoding="utf-8")
        (case / "stderr.log").write_text(p.stderr, encoding="utf-8")
        if p.returncode:
            raise RuntimeError(f"Native solve failed: {case}")
        report = json.loads((case / "report.json").read_text())
        result = report["results"]
        flux = np.array([result[f"flux_linkage_{x}_wb"] for x in "abc"])
        residual = report["solve_info"]["nonlinear_residual_history"][-1]
        assert residual < 1e-8
        row = {
            "index": source["index"], "current_angle_deg": source["current_angle_deg"],
            "time_electrical_angle_deg": source["time_electrical_angle_deg"],
            "rotor_angle_mech_deg": electrical / 4, "phase_current_A": source["phase_current_A"],
            "phase_linkage_Wb": flux.tolist(), "torque_Nm": result["torque_weighted_stress_nm"],
            "torque_arkkio_Nm": result["torque_arkkio_nm"], "torque_contour_Nm": result["torque_contour_az_nm"],
            "nonlinear_residual": residual, "elapsed_s": time.monotonic() - t,
            "nodes": len(artifact["mesh"]["nodes"]), "elements": len(artifact["mesh"]["triangles"]),
            "ampere_turn_audit": audit,
            "source_FEMM_ans_sha256": source["ans_sha256"],
            "mesh_sha256": hashlib.sha256((case / "mesh.json").read_bytes()).hexdigest(),
            "report_sha256": hashlib.sha256((case / "report.json").read_bytes()).hexdigest(),
        }
        if steel_audit:
            row["steel_override_audit"] = steel_audit
        if not args.corrected_baseline:
            row.update(
                FEMM_torque_Nm=source["torque_Nm"],
                relative_nodal_Az=float(
                    np.linalg.norm(np.asarray(report["field_plot"]["az_nodal"]) - femm_nodes[:, 2]) / np.linalg.norm(femm_nodes[:, 2])
                ),
                relative_phase_linkage=float(np.linalg.norm(flux - source["phase_linkage_Wb"]) / np.linalg.norm(source["phase_linkage_Wb"])),
                relative_FEMM_linkage_extraction=float(
                    np.linalg.norm(parsed_flux - source["phase_linkage_Wb"]) / np.linalg.norm(source["phase_linkage_Wb"])
                ),
            )
        for filename in ("mesh.json", "report.json"):
            path = case / filename
            with gzip.open(str(path) + ".gz", "wb") as stream:
                stream.write(path.read_bytes())
            path.unlink()
        write(case / "result.json", row)
        rows.append(row)
        write(args.out / "waveform.json", rows)
        print(
            f"Magneto {identity['model']} {len(rows)} phi={source['current_angle_deg']:g}, "
            f"pose={source['index']}, torque={row['torque_Nm']:.4f} Nm", flush=True,
        )
    write(args.out / "waveform.json", rows)
    write(args.out / "completion.json", {"poses": len(rows), "complete": len(rows) == identity["expected_poses"]})


if __name__ == "__main__":
    main()
