"""Loaded Prius FEMM reference using Pyleecan's own current/rotor conventions."""

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
from pyleecan.Classes.InputCurrent import InputCurrent
from pyleecan.Classes.OPdq import OPdq
from pyleecan.Classes.Simu1 import Simu1
from pyleecan.Functions.FEMM.comp_FEMM_torque import comp_FEMM_torque
from pyleecan.Functions.FEMM.draw_FEMM import draw_FEMM
from pyleecan.Functions.FEMM.update_FEMM_simulation import update_FEMM_simulation
from pyleecan.Functions.load import load

MODEL_SHA = "a8922c4f712c38696e6dcf7e800ad5615a0b22dd45a802574f749a59945c8036"


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--machine", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--points", type=int, default=16)
    ap.add_argument("--angles", type=float, nargs="+", default=list(range(60, 181, 10)))
    ap.add_argument("--mesh", type=float, default=1)
    args = ap.parse_args()
    if args.points < 1 or args.mesh <= 0:
        raise ValueError("Positive points and mesh factor required")
    if hashlib.sha256(args.machine.read_bytes()).hexdigest() != MODEL_SHA:
        raise ValueError("Pinned unmodified published Prius model required")
    args.out.mkdir(parents=True, exist_ok=False)
    machine = load(str(args.machine))
    # The public test uses 128 samples/mechanical revolution: 16 distinct poses
    # over its 180-electrical-degree anti-period. Keep that domain at refinement.
    times = np.arange(args.points) * 30 / (2000 * 4 * args.points)
    currents_by_angle = {}
    for phi in args.angles:
        simu = Simu1(
            name=f"loaded-prius-{phi:g}", machine=machine.copy(),
            input=InputCurrent(OP=OPdq(N0=2000), time=times, Na_tot=2048),
        )
        simu.input.set_Id_Iq(I0=250 / np.sqrt(2), Phi0=np.radians(phi))
        simu.mag = simu.elec = simu.force = simu.struct = None
        simu.path_result = str(args.out / "current-generation" / f"phi-{phi:g}")
        output = simu.run()
        currents_by_angle[phi] = output.elec.get_Is().values.T
        rotor = output.get_angle_rotor()
        assert np.allclose(currents_by_angle[phi].sum(axis=0), 0, atol=1e-10)
    write(args.out / "registration.json", {
        "model_sha256": MODEL_SHA,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "speed_rpm": 2000, "phase_current_peak_A": 250,
        "phase_current_rms_A": 250 / np.sqrt(2), "magnet_temperature_C": 60,
        "magnet_remanence_T": 1.24 * .96, "stack_m": machine.stator.L1,
        "points": args.points, "current_angles_deg": args.angles,
        "rotor_angles_mech_deg": np.degrees(rotor).tolist(),
        "time_s": times.tolist(), "mesh_fineness": args.mesh,
        "current_policy": "Unmodified Pyleecan InputCurrent/OPdq -> OutElec.get_Is; no manual angle fit",
        "full_motor": True, "sliding_band": False, "FEMM_precision": 1e-10,
        "torque_policy": "Pyleecan comp_FEMM_torque / FEMM weighted stress integral 22 on all rotor groups",
        "dependencies": {n: importlib.metadata.version(n) for n in ("pyleecan", "SciDataTool", "numpy", "scipy", "pyfemm")},
    })
    output = SimpleNamespace(
        simu=SimpleNamespace(machine=machine),
        elec=SimpleNamespace(Is=currents_by_angle[args.angles[0]], Ir=None),
        get_logger=lambda: logging.getLogger("loaded-prius-compare"),
    )
    femm = _FEMMHandler()
    base = args.out / "base.fem"
    rows = []
    start = time.monotonic()
    try:
        fd = draw_FEMM(
            femm, output, is_mmfr=True, is_mmfs=True, sym=1, is_antiper=False,
            type_calc_leakage=0, type_BH_stator=0, type_BH_rotor=0,
            kgeo_fineness=1, kmesh_fineness=args.mesh,
            user_FEMM_dict={"simu": {"Lfemm": machine.stator.L1, "precision": 1e-10}},
            path_save=str(base).replace("\\", "/"), is_sliding_band=False, T_mag=60,
        )
        femm.main_minimize()
        write(args.out / "FEMM-dictionary.json", fd)
        femm.mi_close()
        for i, angle in enumerate(rotor):
            for phi in args.angles:
                case = args.out / f"phi-{phi:03g}" / f"pose-{i:03d}"
                case.mkdir(parents=True)
                path = case / "motor.fem"
                femm.opendocument(str(base).replace("\\", "/"))
                current = currents_by_angle[phi][:, i:i + 1]
                update_FEMM_simulation(femm, fd, True, False, np.array([angle]), current, None, 0)
                femm.mi_clearselected()
                femm.mi_saveas(str(path).replace("\\", "/"))
                t = time.monotonic()
                femm.mi_analyze(1)
                femm.mi_loadsolution()
                circuits = [list(femm.mo_getcircuitproperties("Circs" + str(p))) for p in range(3)]
                assert np.allclose([c[0] for c in circuits], current[:, 0], atol=1e-9)
                torque = comp_FEMM_torque(femm, fd["groups"]["lam_group_list"]["Rotor-0"], sym=1)
                row = {
                    "index": i, "current_angle_deg": phi,
                    "rotor_angle_mech_deg": float(np.degrees(angle)),
                    "time_electrical_angle_deg": -i * 180 / args.points,
                    "phase_current_A": current[:, 0].tolist(),
                    "phase_linkage_Wb": [c[2] for c in circuits],
                    "torque_Nm": torque, "nodes": femm.mo_numnodes(),
                    "elements": femm.mo_numelements(), "solve_s": time.monotonic() - t,
                    "fem_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "ans_sha256": hashlib.sha256(path.with_suffix(".ans").read_bytes()).hexdigest(),
                }
                write(case / "result.json", row)
                rows.append(row)
                write(args.out / "waveform.json", rows)
                print(f"FEMM {len(rows)}/{args.points * len(args.angles)} phi={phi:g}, pose={i}, torque={torque:.4f} Nm", flush=True)
                femm.mo_close()
                femm.mi_close()
        write(args.out / "completion.json", {"points": len(rows), "elapsed_s": time.monotonic() - start})
    finally:
        if femm.HandleToFEMM is not None:
            femm.closefemm()


if __name__ == "__main__":
    main()
