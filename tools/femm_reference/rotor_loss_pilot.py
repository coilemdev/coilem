"""Bounded #306 SPM pilot, separate from the frozen E/F collectors.

Run in the pinned FEMM environment on Windows. This process deliberately loads
the preserved E backend, not production rotor-loss code. Analysis is a separate
process. Each committed position retains model, answer, raw mesh/B and fixed
material-point queries, with hashes for safe resume. No release claim is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np

from tools.femm_reference import phase_e, runtime

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lua_path(path):
    return json.dumps(Path(path).resolve().as_posix())


def export_fields(femm, directory, angle, reference_points):
    mesh_path, points_path = directory / "rotor.csv", directory / "points.csv"
    commands = [
        'mo_smooth("off")', f'f=openfile({lua_path(mesh_path)},"w")',
        "for i=1,mo_numelements() do",
        "n1,n2,n3,x,y,a,g=mo_getelement(i)", "if g==10 then",
        "x1,y1=mo_getnode(n1); x2,y2=mo_getnode(n2); x3,y3=mo_getnode(n3)",
        "az,bx,by=mo_getpointvalues(x,y)",
        'write(f,format("%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g\\n",x1,y1,x2,y2,x3,y3,bx,by))',
        "end end", "closefile(f)",
    ]
    script = directory / "mesh-export.lua"
    script.write_text("\n".join(commands), encoding="ascii")
    femm.callfemm(f"dofile({lua_path(script)})")
    mesh = np.loadtxt(mesh_path, delimiter=",", ndmin=2)
    if mesh.shape[1] != 8 or not len(mesh) or not np.isfinite(mesh).all():
        raise ValueError("FEMM rotor export is empty or malformed")
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    if reference_points is None:
        centres = mesh[:, :6].reshape(-1, 3, 2).mean(axis=1)
        reference_points = np.column_stack((cosine*centres[:, 0] + sine*centres[:, 1],
                                            -sine*centres[:, 0] + cosine*centres[:, 1]))
    queries = [f'f=openfile({lua_path(points_path)},"w")']
    for x, y in reference_points:
        gx, gy = cosine*x - sine*y, sine*x + cosine*y
        queries.extend([f"az,bx,by=mo_getpointvalues({gx:.17g},{gy:.17g})",
                        'write(f,format("%.17g,%.17g\\n",bx,by))'])
    queries.append("closefile(f)")
    query_script = directory / "point-export.lua"
    query_script.write_text("\n".join(queries), encoding="ascii")
    femm.callfemm(f"dofile({lua_path(query_script)})")
    points = np.loadtxt(points_path, delimiter=",", ndmin=2)
    if points.shape != (len(reference_points), 2) or not np.isfinite(points).all():
        raise ValueError("FEMM material-point queries failed")
    return reference_points, len(mesh)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--positions", type=int, default=96)
    parser.add_argument("--mesh", choices=["normal", "fine", "very_fine"], default="normal")
    parser.add_argument("--limit", type=int, help="Maximum new positions this invocation, including the independent endpoint")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--shard", default="0/1", help="Disjoint position shard INDEX/COUNT; prepare position zero first")
    args = parser.parse_args()
    if args.positions < 8 or (args.limit is not None and args.limit < 1):
        parser.error("positions must be >=8 and limit must be positive")
    shard, shards = map(int, args.shard.split("/"))
    if shards < 1 or not 0 <= shard < shards:
        parser.error("invalid shard")
    directory = args.out.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    identity = runtime.identity("e")
    protocol = {
        "schema": "coilem.rotor_loss_pilot/v1", "scientific_status": "PILOT_NOT_QUALIFIED",
        "collector_sha256": sha(__file__), "fixture_sha256": sha(FIXTURE),
        "fixture": str(FIXTURE.relative_to(ROOT)), "positions": args.positions, "mesh": args.mesh,
        "speed_rpm": 3000.0, "current_peak_A": 20.0, "gamma_deg": 0.0,
        "span_mechanical_deg": 360.0, "direction": -1,
        "smoothing": "off", "rotor_group": 10,
        "reference_identity": identity, "comparison_tolerances": {
            "analytical_relative": 0.01, "reference_relative": 0.10,
            "convergence_relative": 0.05, "absolute_loss_W": 0.001,
        },
    }
    protocol_path = directory / "protocol.json"
    if protocol_path.exists():
        if not args.resume or json.loads(protocol_path.read_text()) != protocol:
            raise ValueError("Existing pilot request/source differs or --resume was omitted")
    else:
        runtime.write(protocol_path, protocol)
    # Frozen geometry/excitation backend lives only in this collector process.
    Solver, Model, geometry, curve, magnets, femm, automation_module, adapter = phase_e.load_adapter()
    for key in tuple(os.environ):
        if key != "COILEM_FEMM_BIN" and key.startswith(("COILEM_", "OPENEM_", "FEMM_")):
            os.environ.pop(key)
    config = Model.model_validate(json.loads(FIXTURE.read_text()))
    config.solve_params.mesh_density = args.mesh
    geom = geometry(config)
    from backend.femm_geometry import _femm_airgap_width_mm

    gap = min(0.25, _femm_airgap_width_mm(geom)/4) * {"normal": 1, "fine": 0.5, "very_fine": 0.25}[args.mesh]
    os.environ["FEMM_AIRGAP_MESHSIZE_MM"] = str(gap)

    class PilotSolver(Solver):
        def _set_femm_blockprop(self, *a, **kw):
            if a[4] == "rotor_core":
                kw["group"] = 10
            return super()._set_femm_blockprop(*a, **kw)

    worker_directory = directory / f"worker-{shard}-of-{shards}"
    worker_directory.mkdir(exist_ok=True)
    automation = automation_module.Automation(worker_directory)
    reference_points = None
    reference_path = directory / "reference-points.csv"
    if reference_path.exists():
        reference_points = np.loadtxt(reference_path, delimiter=",", ndmin=2)
    if shards > 1 and reference_points is None:
        raise ValueError("Collect position zero with --limit 1 before starting shards")
    new_positions = 0
    start = time.perf_counter()
    try:
        automation.open(1)
        for index in range(args.positions + 1):
            if index % shards != shard:
                continue
            output = directory / f"position-{index:04d}"
            checkpoint = output / "position.json"
            angle = -360.0 * index/args.positions
            if checkpoint.exists():
                recorded = json.loads(checkpoint.read_text())
                if recorded["mechanical_angle_deg"] != angle or any(sha(output/name) != digest for name, digest in recorded["sha256"].items()):
                    raise ValueError("Pilot checkpoint failed its angle or artifact hash check")
                continue
            if args.limit is not None and new_positions >= args.limit:
                break
            output.mkdir(exist_ok=True)
            started = time.perf_counter()
            solver = PilotSolver()
            solver._last_geom = geom
            solver._last_rotor_offset_rad = math.radians(angle)
            solver._setup_problem(femm, config, geom)
            femm.mi_probdef(0, "millimeters", "planar", 1e-8, config.stator.stack_length_mm, 30, 0)
            solver._draw_full_geometry(femm, config, geom, rotor_offset_deg=angle)
            solver._apply_winding_current(femm, config, geom, -angle*config.rotor.pole_count/2)
            solver._apply_boundary(femm, geom)
            model = output / "model.fem"
            femm.mi_saveas(str(model))
            femm.mi_createmesh()
            femm.mi_analyze(1)
            femm.mi_loadsolution()
            reference_points, rotor_elements = export_fields(femm, output, angle, reference_points)
            if not reference_path.exists():
                np.savetxt(reference_path, reference_points, delimiter=",", fmt="%.17g")
            record = {
                "index": index, "mechanical_angle_deg": angle,
                "endpoint": index == args.positions, "rotor_elements": rotor_elements,
                "total_elements": int(femm.mo_numelements()), "airgap_target_mm": gap,
                "wall_s": time.perf_counter()-started,
                "sha256": {p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()},
            }
            femm.mo_close()
            femm.mi_close()
            runtime.write(checkpoint, record)
            new_positions += 1
            print(json.dumps({k: record[k] for k in ("index", "mechanical_angle_deg", "rotor_elements", "total_elements", "wall_s")}), flush=True)
    finally:
        automation.close()
    completed = len(list(directory.glob("position-*/position.json")))
    runtime.write(directory / f"collection-{shard}-of-{shards}.json", {
        "status": "COMPLETE" if completed == args.positions+1 else "PARTIAL",
        "committed_positions": completed, "expected_positions_with_closure": args.positions+1,
        "new_positions": new_positions, "invocation_wall_s": time.perf_counter()-start,
        "reference_points_sha256": sha(reference_path) if reference_path.exists() else None,
    })


if __name__ == "__main__":
    main()
