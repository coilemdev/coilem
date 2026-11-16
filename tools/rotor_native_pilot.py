"""Bounded #306 native field collector: explicit excitation, fresh solves, raw evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from pathlib import Path

import numpy as np

from backend.field_lines import generate_element_b_components
from backend.geometry_drawer import compute_3phase_slot_ampere_turns_for_rotor_elec
from backend.gmsh_solver import run_gmsh_mesh_preview
from backend.iron_loss import FieldFrame, _locate
from backend.magneto2d_adapter import run_magneto2d_report
from backend.models import MotorConfig
from backend.rotor_iron_loss import sample_rotor_field
from backend.solver import _clockwise_excitation_config, _rotate_gmsh_artifact_for_config

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"
PREFLIGHT_POSES = (0.0, -0.9375, -22.5, -360.0, 0.0)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name+f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temporary.replace(path)


def material_query_points():
    angles = np.deg2rad(np.arange(96)*3.75+0.317)
    return np.concatenate([np.column_stack((radius*np.cos(angles), radius*np.sin(angles)))
                           for radius in (7.3, 14.7, 21.9, 26.3)])


def field_sample(report, mechanical_angle_deg):
    if report["mesh_info"]["total_span_deg"] != 360 or report["field_plot"]["total_span_deg"] != 360:
        raise ValueError("native pilot requires full-machine fields")
    plot = report["field_plot"]
    bx, by = generate_element_b_components(plot["nodes_mm"], plot["triangles"], plot["az_nodal"])
    frame = FieldFrame(np.asarray(plot["nodes_mm"], dtype=float), np.asarray(plot["triangles"], dtype=int),
                       plot["regions"], np.asarray(bx), np.asarray(by))
    return sample_rotor_field(frame, mechanical_angle_deg=mechanical_angle_deg, coordinate_frame="global")


def query_sample(sample, points):
    indices = _locate(np.asarray(points), sample.corners_mm)
    if np.any(indices < 0):
        raise ValueError("native material query left the laminated rotor domain")
    return np.column_stack((sample.bx_t[indices], sample.by_t[indices]))


def audit_excitation(artifact, config, mechanical_angle_deg):
    if artifact["rotor_angle_mech_deg"] != mechanical_angle_deg:
        raise ValueError("native mesh pose differs from the requested signed angle")
    if artifact["physics_contract"]["motion"]["rotor_angle_mech_deg"] != mechanical_angle_deg:
        raise ValueError("native physics contract pose differs from its mesh")
    expected = compute_3phase_slot_ampere_turns_for_rotor_elec(config, mechanical_angle_deg*config.rotor.pole_count/2)
    windings = []
    for region in artifact["physics_contract"]["regions"]:
        if region["kind"] != "SlotWinding":
            continue
        winding = region["winding"]
        if winding["area_mm2"] <= 0 or winding["turn_fraction"] <= 0:
            raise ValueError("native winding has invalid area or turn share")
        actual = winding["current_density_a_per_m2"]*winding["area_mm2"]*1e-6
        requested = expected[winding["phase"]]*winding["turn_fraction"]*(1 if winding["direction"] == "in" else -1)
        if abs(actual-requested) > max(1e-8, 1e-10*abs(requested)):
            raise ValueError("native winding ampere-turns do not match the requested excitation")
        windings.append({"region": region["id"], "phase": winding["phase"], "direction": winding["direction"],
                         "area_mm2": winding["area_mm2"], "current_density_A_m2": winding["current_density_a_per_m2"],
                         "actual_ampere_turns": actual, "expected_ampere_turns": requested})
    if len(windings) != config.stator.slot_count:
        raise ValueError("bounded single-layer fixture has unexpected winding regions")
    return {"native_rotor_mechanical_deg": mechanical_angle_deg, "native_gamma_deg": config.solve_params.current_angle_deg,
            "phase_ampere_turns": expected, "windings": windings, "gate": "PASS"}


def validate_convergence(convergence, expected_tolerance):
    if convergence["tolerance"] != expected_tolerance:
        raise ValueError("native solver did not report the expected stopping tolerance")
    if convergence["solution_reused"] or not (convergence["scaled_residual"] <= convergence["tolerance"]
                                            or convergence["rhs_scaled_residual"] <= convergence["absolute_residual_floor"]):
        raise ValueError("native solve was reused or did not meet its explicit convergence tolerance")


def source_identity(binary):
    files = [Path(__file__).resolve()]
    files += sorted((ROOT / "backend").rglob("*.py"))
    files += sorted((ROOT / "solvers/magneto2d/src").rglob("*.rs"))
    files += [ROOT / "solvers/magneto2d/Cargo.toml", ROOT / "solvers/magneto2d/Cargo.lock"]
    import gmsh
    import pydantic
    return {"source_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in files},
            "binary_sha256": sha(binary), "python": platform.python_version(),
            "numpy": np.__version__, "pydantic": pydantic.__version__, "gmsh": gmsh.__version__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--positions", type=int, default=384)
    parser.add_argument("--mesh", choices=("normal", "fine", "very_fine"), default="normal")
    parser.add_argument("--excitation-frame", choices=("public-clockwise", "native-ccw"), default="public-clockwise")
    parser.add_argument("--expected-nonlinear-tolerance", type=float, default=1e-5,
                        help="Assert the native custom-quality stopping tolerance; no shell override")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shard", default="0/1")
    args = parser.parse_args()
    if (args.positions < 32 or args.positions % 4 or not 0 < args.expected_nonlinear_tolerance < 1
            or (args.limit is not None and args.limit < 1)):
        parser.error("invalid angular grid or nonlinear tolerance")
    shard, shards = map(int, args.shard.split("/"))
    if not 0 <= shard < shards or (args.preflight and shards != 1):
        parser.error("invalid shard or preflight partition")
    for key in tuple(os.environ):
        if key.startswith(("COILEM_", "OPENEM_", "MAGNETO2D_", "FEMM_", "GMSH_")):
            os.environ.pop(key)
    directory = args.out.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.environ["COILEM_MAGNETO2D_BINARY"] = str(args.binary.resolve())
    os.environ["COILEM_USER_DATA_ROOT"] = str(directory / "user-data")
    requested = MotorConfig.model_validate(json.loads(FIXTURE.read_text()))
    requested.solve_params.mesh_density = args.mesh
    requested.solve_params.magneto2d_workers = 1
    config = _clockwise_excitation_config(requested) if args.excitation_frame == "public-clockwise" else requested.model_copy(deep=True)
    angles = list(PREFLIGHT_POSES) if args.preflight else [-360*k/args.positions for k in range(args.positions+1)]
    protocol = {"schema": "coilem.native_rotor_pilot/v1", "kind": "preflight" if args.preflight else "full_turn_history",
                "fixture": FIXTURE.relative_to(ROOT).as_posix(), "fixture_sha256": sha(FIXTURE), "positions": args.positions,
                "mechanical_angles_deg": angles, "mesh": args.mesh, "excitation_frame": args.excitation_frame,
                "requested_gamma_deg": requested.solve_params.current_angle_deg, "native_gamma_deg": config.solve_params.current_angle_deg,
                "current_peak_A": 20.0, "speed_rpm": 3000.0, "expected_native_nonlinear_tolerance": args.expected_nonlinear_tolerance,
                "native_field_frame": "global", "export_frame": "rotor_material", "fresh_field_solves": True,
                "mesh_policy": "Gmsh per relative angle; production slot-congruent mesh rotation; no solved-field reuse",
                "closure_tolerances": {"max_component_T": 1e-6, "rms_component_T": 1e-7},
                "identity": source_identity(args.binary), "full_matrix_started": False}
    protocol_path = directory / "protocol.json"
    if protocol_path.exists():
        if not args.resume or json.loads(protocol_path.read_text()) != protocol:
            raise ValueError("native pilot request, source or binary differs; use a new directory")
    else:
        write(protocol_path, protocol)
        write(directory / "requested-config.json", requested.model_dump(mode="json"))
        write(directory / "native-config.json", config.model_dump(mode="json"))
        np.savetxt(directory / "material-query-points.csv", material_query_points(), delimiter=",", fmt="%.17g")
    bases = {}
    new_positions = 0
    started = time.perf_counter()
    for index, angle in enumerate(angles):
        if index % shards != shard:
            continue
        output = directory / f"position-{index:04d}"
        checkpoint = output / "position.json"
        if checkpoint.exists():
            record = json.loads(checkpoint.read_text())
            if record["mechanical_angle_deg"] != angle or any(sha(output/name) != digest for name, digest in record["sha256"].items()):
                raise ValueError("native checkpoint angle or artifact failed validation")
            continue
        if args.limit is not None and new_positions >= args.limit:
            break
        output.mkdir(exist_ok=True)
        begin = time.perf_counter()
        pitch = 360/config.stator.slot_count
        base_angle = round(angle % pitch, 10)
        if base_angle not in bases or (args.preflight and index == len(angles)-1):
            mesh = run_gmsh_mesh_preview(config, rotor_angle_deg=base_angle)["solve_mesh_artifact"]
            bases[base_angle] = mesh
        artifact = _rotate_gmsh_artifact_for_config(bases[base_angle], config, angle)
        excitation = audit_excitation(artifact, config, angle)
        report = run_magneto2d_report(config, sweep=False, rotor_angle_deg=angle, solve_mesh_artifact=artifact,
                                     persist_artifacts_dir=output, artifact_prefix="native")
        convergence = report["solve_info"]["nonlinear_convergence"]
        validate_convergence(convergence, args.expected_nonlinear_tolerance)
        sample = field_sample(report, angle)
        np.savetxt(output / "rotor-material.csv", np.column_stack((sample.corners_mm.reshape(-1, 6), sample.bx_t, sample.by_t)),
                   delimiter=",", fmt="%.17g")
        np.savetxt(output / "material-queries.csv", query_sample(sample, material_query_points()), delimiter=",", fmt="%.17g")
        write(output / "excitation.json", excitation)
        record = {"index": index, "mechanical_angle_deg": angle, "native_gamma_deg": config.solve_params.current_angle_deg,
                  "rotor_elements": len(sample.bx_t), "total_elements": report["mesh_info"]["num_triangles"],
                  "wall_s": time.perf_counter()-begin, "convergence": convergence,
                  "sha256": {p.name: sha(p) for p in output.iterdir() if p.is_file()}}
        write(checkpoint, record)
        print(json.dumps({k: record[k] for k in ("index", "mechanical_angle_deg", "rotor_elements", "total_elements", "wall_s")}), flush=True)
        new_positions += 1
    write(directory / f"collection-{shard}-of-{shards}.json", {"new_positions": new_positions,
          "positions_present": len(list(directory.glob("position-*/position.json"))), "invocation_wall_s": time.perf_counter()-started})


if __name__ == "__main__":
    main()
