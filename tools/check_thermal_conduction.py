"""Export a frozen FEMM heat-flow request or judge an owner-collected bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.benchmark_suite.thermal_conduction import MODELS, check_conduction, registration, request_for_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=[case["id"] for case in registration()["cases"]])
    parser.add_argument("--request-out", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--candidate-model", choices=MODELS, default="surface_mean_v2")
    args = parser.parse_args()
    if args.request_out and args.request_out.exists():
        parser.error("Request output already exists; choose a new path to preserve the frozen request")
    case = next(case for case in registration()["cases"] if case["id"] == args.case)
    request = request_for_case(case, candidate_model=args.candidate_model)
    if args.request_out:
        args.request_out.parent.mkdir(parents=True, exist_ok=True)
        args.request_out.write_text(json.dumps(request, indent=2, allow_nan=False) + "\n")
    result = check_conduction(request, json.loads(args.bundle.read_text()) if args.bundle else None)
    print(json.dumps(result, indent=2, allow_nan=False))
    return int(result["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
