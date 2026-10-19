"""Published Pyleecan Prius geometry/materials, explicit no-load FEMM sweep."""

import argparse
import hashlib
import importlib.metadata
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from pyleecan.Classes._FEMMHandler import _FEMMHandler
from pyleecan.Functions.FEMM.draw_FEMM import draw_FEMM
from pyleecan.Functions.FEMM.update_FEMM_simulation import update_FEMM_simulation
from pyleecan.Functions.load import load


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--machine", type=Path, required=True)
    ap.add_argument("--points", type=int, default=48)
    ap.add_argument("--speed-rpm", type=int, default=3000)
    ap.add_argument("--electrical-range-deg", type=int, choices=(180, 360), default=360)
    ap.add_argument("--initial-rotor-deg", type=float, default=0)
    ap.add_argument("--clockwise", action="store_true")
    ap.add_argument("--mesh", type=float, default=1)
    args = ap.parse_args()
    if args.points < 12 or not np.isfinite(args.speed_rpm) or args.speed_rpm <= 0:
        raise ValueError("Use at least 12 positions over a complete electrical cycle and a finite positive speed")
    args.out.mkdir(parents=True, exist_ok=False)
    source = args.machine
    if hashlib.sha256(source.read_bytes()).hexdigest() != "a8922c4f712c38696e6dcf7e800ad5615a0b22dd45a802574f749a59945c8036":
        raise ValueError("This study requires the pinned published Toyota_Prius.json; preserve other models as separate studies")
    machine = load(str(source))
    assert np.array_equal(machine.stator.winding.wind_mat, json.loads(source.read_text())["stator"]["winding"]["wind_mat"])
    write(
        args.out / "registration.json",
        {
            "model_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "model_name": machine.name,
            "points": args.points,
            "electrical_range_deg": args.electrical_range_deg,
            "initial_rotor_mechanical_deg": args.initial_rotor_deg,
            "rotation_direction": -1 if args.clockwise else 1,
            "speed_rpm": args.speed_rpm,
            "phase_current_A": [0, 0, 0],
            "magnet_temperature_C": 20,
            "stack_m": machine.stator.L1,
            "mesh_fineness": args.mesh,
            "full_model": True,
            "sliding_band": False,
            "FEMM_precision": 1e-10,
            "depth_policy": "Use physical 0.08382 m FEMM depth directly; no subsequent stack multiplier.",
            "dependencies": {n: importlib.metadata.version(n) for n in ("pyleecan", "SciDataTool", "numpy", "scipy", "pyfemm")},
        },
    )
    output = SimpleNamespace(
        simu=SimpleNamespace(machine=machine),
        elec=SimpleNamespace(Is=np.zeros((3, 1)), Ir=None),
        get_logger=lambda: logging.getLogger("prius-compare"),
    )
    femm = _FEMMHandler()
    base = args.out / "base.fem"
    start = time.monotonic()
    try:
        print("Generating full published Pyleecan model", flush=True)
        fd = draw_FEMM(
            femm,
            output,
            is_mmfr=True,
            is_mmfs=False,
            sym=1,
            is_antiper=False,
            type_calc_leakage=0,
            type_BH_stator=0,
            type_BH_rotor=0,
            kgeo_fineness=1,
            kmesh_fineness=args.mesh,
            user_FEMM_dict={"simu": {"Lfemm": machine.stator.L1, "precision": 1e-10}},
            path_save=str(base).replace("\\", "/"),
            is_sliding_band=False,
            T_mag=20,
        )
        femm.main_minimize()
        write(args.out / "FEMM-dictionary.json", fd)
        femm.mi_close()
        print(f"Geometry generated in {time.monotonic() - start:.1f}s", flush=True)
        rows = []
        for i in range(args.points):
            angle_e = i * args.electrical_range_deg / args.points
            angle_m = args.initial_rotor_deg + (-1 if args.clockwise else 1) * angle_e / 4
            case = args.out / f"pose-{i:03d}"
            case.mkdir()
            f = case / "motor.fem"
            femm.opendocument(str(base).replace("\\", "/"))
            update_FEMM_simulation(femm, fd, True, False, np.array([angle_m * np.pi / 180]), np.zeros((3, 1)), None, 0)
            femm.mi_clearselected()
            femm.mi_saveas(str(f).replace("\\", "/"))
            t = time.monotonic()
            femm.mi_analyze(1)
            femm.mi_loadsolution()
            circuit = [list(femm.mo_getcircuitproperties("Circs" + str(p))) for p in range(3)]
            assert all(abs(c[0]) < 1e-15 for c in circuit)
            row = {
                "index": i,
                "electrical_angle_deg": angle_e,
                "mechanical_angle_deg": angle_m,
                "phase_linkage_Wb": [c[2] for c in circuit],
                "circuit_properties": circuit,
                "nodes": femm.mo_numnodes(),
                "elements": femm.mo_numelements(),
                "solve_s": time.monotonic() - t,
                "fem_sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                "ans_sha256": hashlib.sha256(f.with_suffix(".ans").read_bytes()).hexdigest(),
            }
            write(case / "result.json", row)
            rows.append(row)
            write(args.out / "waveform.json", rows)
            print(f"FEMM {i + 1}/{args.points}: {angle_e:g} deg, {row['elements']} elements, linkage={row['phase_linkage_Wb']}", flush=True)
            femm.mo_close()
            femm.mi_close()
        write(args.out / "completion.json", {"elapsed_s": time.monotonic() - start, "points": len(rows)})
    finally:
        if femm.HandleToFEMM is not None:
            femm.closefemm()


if __name__ == "__main__":
    main()
