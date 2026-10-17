"""Explicit experimental Elmer 3D cases. Does not alter the public solver selection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.elmer3d.model import Case3D


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", type=Path, help="3D case JSON; relative mesh paths resolve beside this file")
    source.add_argument("--demo", choices=["sphere", "coil", "torque", "steel"], help="generate and solve a physical control")
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory; existing results are never overwritten")
    parser.add_argument("--elmer-home", type=Path, help="separately installed runtime; no automatic download")
    parser.add_argument("--mesh-scale", type=float, default=1.0, help="control mesh size multiplier")
    args = parser.parse_args()
    try:
        if args.output_dir.exists():
            raise ValueError("output directory already exists")
        if args.demo:
            from backend.elmer3d.demo import create_demo

            # Keep generated inputs outside the immutable solve directory.
            inputs = args.output_dir.with_name(args.output_dir.name + "-inputs")
            case = create_demo(inputs, kind=args.demo, mesh_scale=args.mesh_scale)
        else:
            case = Case3D.model_validate_json(args.case.read_text(encoding="utf-8"))
            if not case.mesh_file.is_absolute():
                case = case.model_copy(update={"mesh_file": (args.case.resolve().parent / case.mesh_file).resolve()})
        from backend.elmer3d.solver import solve_case

        result = solve_case(case, output_dir=args.output_dir, elmer_home=args.elmer_home)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Elmer 3D: {exc}\n")
    print(json.dumps({key: result[key] for key in ("status", "notice", "nodes", "tetrahedra", "elapsed_s")}, indent=2))
    print(args.output_dir.resolve() / "result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
