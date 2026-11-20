"""Replay a time-invariant analytical material potential on the collected meshes.

No field solves, filtering, material calibration, or physical rotor-loss claim.
The exact field at every material point is constant, so exact rotor loss is zero.
Nonzero loss measures remesh/linear-gradient/point-sampling contamination.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from backend.field_lines import generate_element_b_components
from backend.rotor_iron_loss import RotorFieldSample
from tools.rotor_native_pilot import sha
from tools.rotor_native_report import loss_rows


def static_potential(corners_mm, *, boundary_peak_t=0.7, radius_m=0.028):
    x, y = (np.asarray(corners_mm)*1e-3).reshape(-1, 2).T
    return boundary_peak_t/(4*radius_m**3)*(x**4-6*x*x*y*y+y**4)


def linear_gradient_sample(corners_mm, angle, *, boundary_peak_t=0.7, radius_m=0.028):
    corners = np.asarray(corners_mm)
    nodes = corners.reshape(-1, 2)
    triangles = np.arange(len(nodes)).reshape(-1, 3)
    az = static_potential(corners, boundary_peak_t=boundary_peak_t, radius_m=radius_m)
    bx, by = generate_element_b_components(nodes.tolist(), triangles.tolist(), az.tolist())
    return RotorFieldSample(angle, corners, np.asarray(bx), np.asarray(by), np.arange(len(corners)))


def analyse(directory):
    directory = Path(directory)
    protocol = json.loads((directory / "protocol.json").read_text())
    if protocol["kind"] != "full_turn_history" or protocol["positions"] != 384:
        raise ValueError("remesh probe requires the bounded 384-sample native history")
    # Production slot-congruent rotations give identical material meshes every
    # 32 steps. Read all registered raw meshes and verify rather than assume it.
    representatives, samples = [], []
    for index, angle in enumerate(protocol["mechanical_angles_deg"][:-1]):
        position = directory / f"position-{index:04d}"
        record = json.loads((position / "position.json").read_text())
        if sha(position / "rotor-material.csv") != record["sha256"]["rotor-material.csv"]:
            raise ValueError("native rotor mesh evidence changed")
        corners = np.loadtxt(position / "rotor-material.csv", delimiter=",")[:, :6].reshape(-1, 3, 2)
        if index < 32:
            representatives.append(linear_gradient_sample(corners, angle))
        base = representatives[index % 32]
        if corners.shape != base.corners_mm.shape or not np.allclose(corners, base.corners_mm, rtol=0, atol=1e-10):
            raise ValueError("slot-congruent material meshes differ")
        samples.append(RotorFieldSample(angle, base.corners_mm, base.bx_t, base.by_t, base.source_element_index))
    config = json.loads((directory / "native-config.json").read_text())
    rows, convergence = loss_rows(samples, 384, protocol["speed_rpm"], config["stator"]["stack_length_mm"]*1e-3)
    return {"schema": "coilem.rotor_static_potential_remesh_probe/v1", "protocol_sha256": sha(directory / "protocol.json"),
            "analysis_source_sha256": sha(__file__), "exact_rotor_loss_W": 0,
            "potential": "Az = B0/(4 R^3) * (x^4 - 6 x^2 y^2 + y^4), x,y in material metres; time invariant",
            "boundary_peak_T": 0.7, "radius_m": 0.028, "fresh_field_solves": 0,
            "interpretation": "nonzero values are numerical contamination, not motor loss; diagnostic cannot calibrate or correct native loss",
            "results": rows, "angular_convergence": convergence, "angular_gate_pass": all(s["pass"] for s in convergence),
            "full_matrix_started": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = analyse(args.directory)
    (args.directory / "remesh-probe.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"exact_W": 0, "angular_gate_pass": result["angular_gate_pass"],
                      "spurious_loss_W": [{"positions": r["positions"], "loss": r.get("production_sampling")}
                                          for r in result["results"]]}, indent=2))


if __name__ == "__main__":
    main()
