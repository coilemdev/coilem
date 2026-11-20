"""Prescribed static material potential through the full fixed-motion/Az adapter.

No motor field solves. The exact rotor loss is zero; retain the ordinary FE
gradient and loss paths and use the predeclared 1 mW absolute loss floor.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np

from backend.iron_loss import M350_50A_LOSS
from backend.models import MotorConfig
from backend.rotor_iron_loss import RotorLossMaterial, RotorSamplingPlan, harmonic_rotor_iron_loss, rotor_flux_history
from backend.rotor_motion_mesh import FixedMaterialRotorMesh
from tools.rotor_native_pilot import field_sample, sha, write
from tools.rotor_native_remesh_probe import static_potential


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--positions", type=int, default=32)
    parser.add_argument("--airgap-divisions", type=int, default=1536)
    parser.add_argument("--airgap-layers", type=int, default=4)
    args = parser.parse_args()
    config = MotorConfig.model_validate(json.loads(args.config.read_text()))
    motion = FixedMaterialRotorMesh(json.loads(args.template.read_text()), angular_divisions=args.airgap_divisions,
                                    radial_layers=args.airgap_layers)
    plan = RotorSamplingPlan(3000, args.positions)
    samples = []
    for angle in plan.mechanical_angles_deg:
        mesh = motion.at_angle(config, angle)["mesh"]
        a = math.radians(angle)
        xy = np.asarray(mesh["nodes"]) @ np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        report = {"mesh_info": {"total_span_deg": 360}, "field_plot": {"total_span_deg": 360,
                  "nodes_mm": mesh["nodes"], "triangles": mesh["triangles"], "regions": mesh["regions"],
                  "az_nodal": static_potential(xy).tolist()}}
        samples.append(field_sample(report, angle))
    history = rotor_flux_history(plan, samples)
    loss = harmonic_rotor_iron_loss(history, material=RotorLossMaterial("M350-50A", "analytical static control", M350_50A_LOSS),
                                   stack_length_m=config.stator.stack_length_mm*1e-3)
    result = {"schema": "coilem.fixed_material_static_control/v1", "positions": args.positions, "exact_W": 0,
              "potential": "Az = B0/(4 R^3) * (x^4-6*x^2*y^2+y^4), in rotor material metres; B0=0.7 T, R=0.028 m",
              "loss": asdict(loss) | {"total_W": loss.total_W}, "absolute_tolerance_W": 0.001,
              "gate": "PASS" if loss.total_W < 0.001 else "FAIL", "distinct_material_meshes": history.distinct_meshes,
              "angular_divisions": args.airgap_divisions, "radial_layers": args.airgap_layers,
              "template_sha256": sha(args.template), "config_sha256": sha(args.config), "fresh_field_solves": 0,
              "source_sha256": {name: sha(Path(__file__).resolve().parents[1] / name) for name in
                                ("backend/rotor_motion_mesh.py", "tools/rotor_fixed_mesh_control.py", "tools/rotor_native_pilot.py")},
              "full_matrix_started": False}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write(args.out, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
