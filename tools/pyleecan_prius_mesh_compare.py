"""Magneto control on the exact Pyleecan/FEMM mesh, not a geometry refit."""

import argparse
import hashlib
import json
import math
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

import numpy as np

from backend.custom_materials import SteelImportRequest, import_steel
from backend.magneto2d_adapter import build_magneto2d_command, ensure_magneto2d_binary
from backend.solver_environment import solver_process_environment


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def parse(fem):
    s = fem.read_text(encoding="latin-1")
    blocks = []
    for text in re.findall(r"<BeginBlock>(.*?)<EndBlock>", s, re.S):
        fields = {k: v.strip().strip('"') for k, v in re.findall(r"<(.*?)>\s*=\s*([^\n]+)", text)}
        bh = text.split("<BHPoints>")[1].splitlines()
        fields["bh"] = [[float(v) for v in row.split()] for row in bh[1:] if row.strip()]
        blocks.append(fields)
    circuits = [re.search(r'<CircuitName>\s*=\s*"(.*?)"', t)[1] for t in re.findall(r"<BeginCircuit>(.*?)<EndCircuit>", s, re.S)]
    labels = [[float(v) for v in row.split()] for row in s.split("[NumBlockLabels]")[1].splitlines()[1:] if row.strip()]
    ans = fem.with_suffix(".ans").read_text(encoding="latin-1").splitlines()
    i = ans.index("[Solution]") + 1
    n = int(ans[i])
    i += 1
    nodes = np.array([[float(v) for v in line.split()[:3]] for line in ans[i : i + n]])
    i += n
    ntri = int(ans[i])
    i += 1
    elements = np.array([[int(v) for v in line.split()[:4]] for line in ans[i : i + ntri]])
    assert "[LengthUnits] =  meters" in s
    return blocks, circuits, labels, nodes, elements


def artifact_for(fem, electrical, *, expected_remanence_t=1.24):
    blocks, circuits, labels, nodes, elements = parse(fem)
    triangles = elements[:, :3]
    counts = Counter(tuple(sorted((int(t[j]), int(t[(j + 1) % 3])))) for t in triangles for j in range(3))
    boundary = sorted({n for edge, owners in counts.items() if owners == 1 for n in edge if np.linalg.norm(nodes[n, :2]) > 0.13})
    assert boundary and np.max(np.abs(nodes[boundary, 2])) < 1e-12
    assert len(boundary) < len(nodes)
    regions = []
    grades = {}
    for b in blocks:
        if b["bh"]:
            steel = import_steel(
                SteelImportRequest(
                    name="Pyleecan M400-50A",
                    source="Published Pyleecan Toyota_Prius.json, exact FEMM B-H points",
                    csv_text="B_T,H_A_per_m\n" + "\n".join(f"{v[0]:.17g},{v[1]:.17g}" for v in b["bh"]),
                )
            )
            grades[b["BlockName"]] = steel
    assert len({g.id for g in grades.values()}) == 1
    steel = next(iter(grades.values()))
    for idx, label in enumerate(labels):
        block = blocks[int(label[2]) - 1]
        name = block["BlockName"]
        entry = {"id": f"label-{idx}", "kind": "Airgap", "material": "air", "motion_group": "stationary"}
        if float(block["H_c"]):
            assert math.isclose(float(block["H_c"]) * float(block["Mu_x"]) * 4 * math.pi * 1e-7, expected_remanence_t, rel_tol=1e-12)
            entry.update(kind="Magnet", material="magnet:Prius_2004_NdFeB", motion_group="rotor", magnetization_angle_deg=label[5] - 3.75)
        elif name in grades:
            rotor = "Rotor" in name
            entry.update(
                kind="RotorCore" if rotor else "StatorTooth",
                material="steel:" + ("rotor:" if rotor else "stator:") + steel.id,
                motion_group="rotor" if rotor else "stationary",
            )
        elif int(label[4]) > 0:
            circuit = circuits[int(label[4]) - 1]
            phase = "ABC"[int(circuit[-1])]
            assert abs(label[7]) == 9
            theta = math.atan2(label[1], label[0]) % (2 * math.pi)
            slot = int(theta / (2 * math.pi / 48)) % 48
            direction = "in" if label[7] > 0 else "out"
            entry.update(
                kind="SlotWinding",
                material="conductor:copper",
                current_density_a_per_m2=0,
                winding={
                    "phase": phase,
                    "direction": direction,
                    "slot_index": slot,
                    "layer": 1,
                    "turn_fraction": 1,
                    "turns_per_coil": 9,
                    "layers": 1,
                    "parallel_paths": 1,
                },
            )
        regions.append(entry)
    ids = [int(v) for v in elements[:, 3]]
    assert min(ids) == 0 and max(ids) < len(regions)
    assert sum(r["kind"] == "SlotWinding" for r in regions) == 48
    assert sum(r["kind"] == "Magnet" for r in regions) == 16
    mesh = {
        "nodes": (
            nodes[:, :2] @ np.array([[math.cos(math.pi / 48), -math.sin(math.pi / 48)], [math.sin(math.pi / 48), math.cos(math.pi / 48)]]) * 1000
        ).tolist(),
        "triangles": triangles.tolist(),
        "regions": [regions[i]["kind"] for i in ids],
        "boundary_nodes": boundary,
        "sector_edge_pairs": [],
        "info": {
            "num_nodes": len(nodes),
            "num_triangles": len(triangles),
            "pole_pitch_deg": 45,
            "n_pole_pitches": 8,
            "total_span_deg": 360,
            "angular_divisions": 0,
            "radial_rings": 0,
            "mesh_density": "Pyleecan-FEMM",
            "mesh_source": "unknown",
            "radial_layers": [],
            "airgap_inner_radius_mm": 80.2,
            "airgap_outer_radius_mm": 80.95,
            "magnet_outer_radius_mm": 80.2,
            "stator_inner_radius_mm": 80.95,
            "stator_slot_outer_radius_mm": 115.25,
            "stator_outer_radius_mm": 134.62,
        },
    }
    artifact = {
        "mesh": mesh,
        "element_region_ids": [regions[i]["id"] for i in ids],
        "rotor_angle_mech_deg": electrical / 4,
        "element_magnetization": [regions[i].get("magnetization_angle_deg") for i in ids],
        "element_current_density_a_per_m2": [0 for _ in ids],
        "physics_contract": {
            "version": "magneto2d_imported_physics/v0",
            "topology_hint": "IPM",
            "motion": {"rotor_angle_mech_deg": electrical / 4, "rotor_state": "baked_in_mesh"},
            "boundary_policy": {"outer_boundary": "dirichlet_az_zero", "sector_edges": "none"},
            "regions": regions,
            "provenance": {"producer": "Pyleecan 1.5.0 / FEMM 4.2", "same_mesh_control": True},
        },
    }
    # Independent extraction on FEMM's nodal A, using the actual circuit and turn labels.
    a = nodes[triangles[:, 1], :2] - nodes[triangles[:, 0], :2]
    b = nodes[triangles[:, 2], :2] - nodes[triangles[:, 0], :2]
    area = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) / 2
    az = nodes[triangles, 2].mean(axis=1)
    link = np.zeros(3)
    for idx, r in enumerate(regions):
        if r["kind"] == "SlotWinding":
            sel = elements[:, 3] == idx
            w = r["winding"]
            link["ABC".index(w["phase"])] += (1 if w["direction"] == "in" else -1) * 9 * 0.08382 * np.sum(az[sel] * area[sel]) / sum(area[sel])
    return artifact, steel, link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--femm", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--native-input", type=Path, required=True)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=args.resume)
    binary = ensure_magneto2d_binary()
    baseline = json.loads(args.native_input.read_text(encoding="utf-8"))
    reference_registration = json.loads((args.femm / "registration.json").read_text())
    speed_rpm = reference_registration["speed_rpm"]
    if not float(speed_rpm).is_integer() or speed_rpm <= 0:
        raise ValueError("The native input requires a positive integer speed in rpm")
    baseline["solve_params"]["rated_speed_rpm"] = int(speed_rpm)
    # The template supplies CLI options, not geometry provenance. Geometry,
    # materials and source assignments come from the saved Pyleecan/FEMM case.
    baseline.pop("openem_provenance", None)
    if baseline["solve_params"]["current_amplitude_A"] != 0:
        raise ValueError("Reference comparison requires explicit zero current")
    options = {
        "MAGNETO2D_NONLINEAR_TOL": "1e-8",
        "MAGNETO2D_NEWTON_TOL": "1e-9",
        "MAGNETO2D_NONLINEAR_MAX_ITER": "200",
        "RAYON_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MAGNETO2D_LINEAR_SOLVER": "direct",
        "MAGNETO2D_PCG_PRECONDITIONER": "ic0",
    }
    registration = {
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "options": options,
        "limits": {
            "relative_phase_linkage": 0.02,
            "relative_LL_RMS": 0.02,
            "relative_LL_sampled_peak": 0.03,
            "relative_FEMM_extraction": 1e-8,
            "native_nonlinear_residual": 1e-8,
        },
        "global_coordinate_rotation_deg": -3.75,
        "coordinate_policy": (
            "Rigidly rotate the complete Pyleecan mesh and magnetization vectors "
            "to align its half-slot-shifted origin with native slot centers; no physical change."
        ),
        "physics": "Exact FEMM nodes/triangles/material labels/magnet directions/zero sources/outer Dirichlet boundary; inner boundary natural.",
    }
    registration["FEMM_registration_sha256"] = hashlib.sha256((args.femm / "registration.json").read_bytes()).hexdigest()
    if args.resume:
        assert json.loads((args.out / "registration.json").read_text()) == registration, "Resume registration mismatch"
    else:
        write(args.out / "registration.json", registration)
    rows = []
    for src in sorted(p for p in args.femm.glob("pose-*") if (p / "result.json").exists()):
        source = json.loads((src / "result.json").read_text())
        e = source["electrical_angle_deg"]
        case = args.out / src.name
        if args.resume and (case / "result.json").exists():
            old = json.loads((case / "result.json").read_text())
            assert old["report_sha256"] == hashlib.sha256((case / "report.json").read_bytes()).hexdigest()
            assert old["source_FEMM_ans_sha256"] == source["ans_sha256"]
            rows.append(old)
            continue
        case.mkdir()
        artifact, steel, parsed_flux = artifact_for(src / "motor.fem", e)
        request = json.loads(json.dumps(baseline))
        request["materials"].update(
            stator_steel=steel.id, rotor_steel=steel.id, custom_steels={steel.id: steel.model_dump(mode="json")}, magnet_grade="Prius_2004_NdFeB"
        )
        request["stator"].update(ID_mm=161.9, OD_mm=269.24, stack_length_mm=83.82)
        request["rotor"].update(OD_mm=160.4)
        write(case / "input.json", request)
        write(case / "mesh.json", artifact)
        cmd = build_magneto2d_command(
            case / "input.json", case / "report.json", rotor_angle_deg=e / 4, solve_mesh_path=case / "mesh.json", executable=binary
        )
        t = time.monotonic()
        p = subprocess.run(cmd, cwd=case, capture_output=True, text=True, env=solver_process_environment(options), timeout=180)
        (case / "stdout.log").write_text(p.stdout, encoding="utf-8")
        (case / "stderr.log").write_text(p.stderr, encoding="utf-8")
        if p.returncode:
            raise RuntimeError(f"Magneto failed at {e}; retained stderr: {case}")
        report = json.loads((case / "report.json").read_text())
        flux = [report["results"][f"flux_linkage_{c}_wb"] for c in "abc"]
        _, _, _, femm_nodes, _ = parse(src / "motor.fem")
        az_relative = float(np.linalg.norm(np.asarray(report["field_plot"]["az_nodal"]) - femm_nodes[:, 2]) / np.linalg.norm(femm_nodes[:, 2]))
        residual = report["solve_info"]["nonlinear_residual_history"][-1]
        assert residual < 1e-8
        row = {
            "index": source["index"],
            "source_FEMM_ans_sha256": source["ans_sha256"],
            "electrical_angle_deg": e,
            "phase_linkage_Wb": flux,
            "FEMM_circuit_linkage_Wb": source["phase_linkage_Wb"],
            "FEMM_Az_integrated_linkage_Wb": parsed_flux.tolist(),
            "linkage_relative_difference": float(
                np.linalg.norm(np.array(flux) - source["phase_linkage_Wb"]) / np.linalg.norm(source["phase_linkage_Wb"])
            ),
            "FEMM_extraction_relative_difference": float(
                np.linalg.norm(parsed_flux - source["phase_linkage_Wb"]) / np.linalg.norm(source["phase_linkage_Wb"])
            ),
            "relative_nodal_Az_difference": az_relative,
            "nonlinear_residual": residual,
            "elapsed_s": time.monotonic() - t,
            "mesh_sha256": hashlib.sha256((case / "mesh.json").read_bytes()).hexdigest(),
            "report_sha256": hashlib.sha256((case / "report.json").read_bytes()).hexdigest(),
        }
        rows.append(row)
        write(case / "result.json", row)
        write(args.out / "waveform.json", rows)
        print(
            f"Magneto {len(rows)}: {e:g} deg, flux difference {100 * row['linkage_relative_difference']:.4f}%, "
            f"extraction difference {100 * row['FEMM_extraction_relative_difference']:.6f}%",
            flush=True,
        )
    write(
        args.out / "completion.json",
        {"points": len(rows), "complete": len(rows) == json.loads((args.femm / "registration.json").read_text())["points"]},
    )


if __name__ == "__main__":
    main()
