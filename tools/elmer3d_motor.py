"""Prepare or solve an experimental finite-length, no-load motor case."""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.elmer3d.motor import AxialGeometry, create_motor_case
from backend.models import MotorConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="motor JSON with explicit zero phase-current amplitude")
    parser.add_argument("--axial-geometry", type=Path, required=True, help="explicit axial geometry JSON")
    parser.add_argument("--rotor-angle-mech-deg", type=float, default=0)
    parser.add_argument("--output-dir", type=Path, required=True, help="new output directory")
    parser.add_argument("--solve", action="store_true", help="run separately installed Elmer after preparing the mesh")
    parser.add_argument("--elmer-home", type=Path)
    args = parser.parse_args()
    try:
        if args.output_dir.exists():
            raise ValueError("output directory already exists")
        config = MotorConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
        axial = AxialGeometry.model_validate_json(args.axial_geometry.read_text(encoding="utf-8"))
        inputs = args.output_dir.with_name(args.output_dir.name + "-inputs")
        case = create_motor_case(config, axial, inputs, rotor_angle_mech_deg=args.rotor_angle_mech_deg)
        from backend.elmer3d.mesh import read_mesh

        volume = read_mesh(case, case.mesh_file)
        print(f"Prepared {len(volume.tetra)} tetrahedra; case: {inputs / 'case.json'}")
        if args.solve:
            from backend.elmer3d.solver import solve_case

            result = solve_case(case, output_dir=args.output_dir, elmer_home=args.elmer_home)
            print(f"{result['status']}: {args.output_dir / 'result.json'}")
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Elmer 3D motor: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
