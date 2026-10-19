"""Run the published Prius plotting tutorial's open-circuit case with Pyleecan/FEMM.

Optional reference runtime only; Pyleecan and FEMM are not app dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_reference(machine_path: Path, notebook_path: Path, destination: Path) -> dict:
    import numpy as np
    from pyleecan.Classes.ForceMT import ForceMT
    from pyleecan.Classes.InputCurrent import InputCurrent
    from pyleecan.Classes.MagFEMM import MagFEMM
    from pyleecan.Classes.OPdq import OPdq
    from pyleecan.Classes.Simu1 import Simu1
    from pyleecan.Functions.load import load

    if digest(machine_path) != "a8922c4f712c38696e6dcf7e800ad5615a0b22dd45a802574f749a59945c8036":
        raise ValueError("Use the unchanged Prius machine from the pinned tutorial release")
    if digest(notebook_path) != "d4943674908c728ac881f64f25af8d3f516ff95300b4d85335c6af8af5f6352b":
        raise ValueError("Use the unchanged plotting notebook from the pinned tutorial release")
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    cells = ["".join(c.get("source", [])) for c in notebook["cells"]]
    setup = next(c for c in cells if "simu2 = simu.copy()" in c)
    required = ("Na_tot=252 * 8", "Nt_tot=50 * 8", "OPdq(N0=1000)", "simu2.input.OP.set_Id_Iq(Id=0,Iq=0)")
    if not all(token in setup for token in required):
        raise ValueError("The supplied notebook is not the pinned open-circuit tutorial setup")
    destination.mkdir(parents=True, exist_ok=False)
    machine = load(str(machine_path.resolve()))
    simu = Simu1(name="FEMM_periodicity", machine=machine)
    simu.input = InputCurrent(Na_tot=252 * 8, Nt_tot=50 * 8)
    simu.input.OP = OPdq(N0=1000)
    simu.input.OP.set_I0_Phi0(I0=250 / np.sqrt(2), Phi0=140 * np.pi / 180)
    simu.mag = MagFEMM(is_periodicity_a=True, is_periodicity_t=True, nb_worker=4)
    simu.force = ForceMT(is_periodicity_a=True, is_periodicity_t=True)
    simu2 = simu.copy()
    simu2.input.OP.set_Id_Iq(Id=0, Iq=0)
    # Only output location and run name differ; the unrelated loaded run and
    # plotting cells are omitted. Magnetic and force settings retain defaults.
    simu2.name = "Prius_tutorial_open_circuit"
    simu2.path_result = str(destination.resolve())
    registration = {
        "tutorial": "Pyleecan 1.5.0 Tutorials/03_tuto_Plots.ipynb, open-circuit branch",
        "source_commit": "e04992f98f76047da9ae1ba9b8db065aa487cc9e",
        "notebook_sha256": digest(notebook_path),
        "setup_cell_sha256": hashlib.sha256(setup.encode()).hexdigest(),
        "machine_sha256": digest(machine_path),
        "runner_sha256": digest(Path(__file__)),
        "speed_rpm": 1000,
        "magnet_temperature_C": simu2.mag.T_mag,
        "current_dq_A_rms": [simu2.input.OP.Id_ref, simu2.input.OP.Iq_ref],
        "simulation": simu2.as_dict(),
        "dependencies": {n: importlib.metadata.version(n) for n in ("pyleecan", "SciDataTool", "numpy", "scipy", "pyfemm")},
        "deviations": ["Skip the unrelated loaded branch and plot cells; change run name and output path only."],
    }
    (destination / "registration.json").write_text(json.dumps(registration, indent=2) + "\n", encoding="utf-8")
    start = time.monotonic()
    print("Running the published open-circuit tutorial at 1000 rpm, 20 C, zero current", flush=True)
    output = simu2.run()
    output.mag.comp_emf()
    output.save(str(destination / "output.json"))
    flux = output.mag.Phi_wind_stator.get_data_along("time", "phase")
    emf = output.mag.emf.get_data_along("time", "phase")
    current = output.elec.get_Is().get_data_along("time", "phase")
    if not np.all(current.values == 0):
        raise ValueError("The tutorial's open-circuit branch contains nonzero current")
    result = {
        "complete": True,
        "elapsed_s": time.monotonic() - start,
        "time_s": flux.axes[0].get_values().tolist(),
        "phase_flux_Wb": flux.values.tolist(),
        "phase_emf_V": emf.values.tolist(),
        "phase_current_A": current.values.tolist(),
        "flux_axes": [a.as_dict() for a in flux.axes],
        "raw_flux_shape": list(output.mag.Phi_wind_stator.values.shape),
        "raw_time_periodicity": output.mag.Phi_wind_stator.axes[0].get_periodicity(),
        "rotor_angle_rad": output.get_angle_rotor().tolist(),
        "initial_rotor_angle_rad": output.get_angle_rotor_initial(),
        "output_sha256": digest(destination / "output.json"),
    }
    (destination / "waveform.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Completed tutorial in {result['elapsed_s']:.1f}s; raw flux {result['raw_flux_shape']}, reconstructed {flux.values.shape}", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine", type=Path, required=True)
    parser.add_argument("--notebook", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run_reference(args.machine, args.notebook, args.out)


if __name__ == "__main__":
    main()
