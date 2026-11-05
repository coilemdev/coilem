"""Small actual-solver check of clockwise running modes; no fitting or reuse."""
import argparse
import json
import threading
from pathlib import Path

from backend.experimental.outrunner_excitation import currents_at
from backend.experimental.outrunner_project import QUALITY_PRESETS, OutrunnerAnalysis, OutrunnerProject
from backend.experimental.outrunner_runtime import _solve_case
from backend.experimental.outrunner_sweep import SweepCase
from backend.magneto2d_adapter import ensure_magneto2d_binary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    binary = ensure_magneto2d_binary().resolve()
    rows = []
    for mode in ("ideal_six_step_120", "sinusoidal"):
        settings = OutrunnerAnalysis(**{key: value for key, value in QUALITY_PRESETS["preview"].items() if key != "label"},
                                     accuracy_plan="preview", excitation_mode=mode,
                                     current_amplitude_convention="plateau" if mode == "ideal_six_step_120" else "peak")
        project = OutrunnerProject(analysis=settings)
        for angle in (0, 60, 120):
            case = SweepCase(f"{mode}_{angle:03d}", -angle/7, currents_at(settings, -angle/7), "loaded")
            row = _solve_case(case, project, binary, args.output/case.id, threading.Event())
            torque_cw = -row["outer_rotor_torque_Nm"]
            if not torque_cw > 0:
                raise RuntimeError(f"Clockwise command produced nonpositive motoring torque: {case.id}: {torque_cw}")
            receipt = {"mode": mode, "electrical_angle_cw_deg": angle, "phase_currents_A": case.currents_A,
                       "clockwise_torque_Nm": torque_cw, "elapsed_s": row["elapsed_s"], "raw_sha256": row["raw_sha256"]}
            rows.append(receipt)
            (args.output/"receipt.json").write_text(json.dumps({"status": "RUNNING", "points": rows}, indent=2))
            print(json.dumps({key: value for key, value in receipt.items() if key != "raw_sha256"}), flush=True)
    (args.output/"receipt.json").write_text(json.dumps({"status": "PASS", "points": rows}, indent=2))
