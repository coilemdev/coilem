"""Add actual half-step solves while retaining exact requests at prior nodes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backend.experimental.outrunner_sweep import SweepCase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--family", choices=("loaded", "noload"), default="noload")
    args = parser.parse_args()
    raw = args.input.read_bytes()
    prior = json.loads(raw)
    selected = sorted([x for x in prior["cases"] if x["family"] == args.family], key=lambda x: x["angle_ccw_deg"])
    if len(selected) < 25:
        raise ValueError("An initial complete declared grid is required")
    samples = 2*(len(selected)-1)
    cases = list(prior["cases"])
    for i, (left, right) in enumerate(zip(selected, selected[1:])):
        case = SweepCase(f"{args.family}_refine{samples}_{i:04d}", (left["angle_ccw_deg"]+right["angle_ccw_deg"])/2,
                         tuple(left["currents_A"]), args.family, left["reference_model"])
        cases.append(case.to_dict())
    if args.out.exists():
        raise ValueError("Retain prior declarations; use a fresh manifest filename")
    args.out.write_text(json.dumps({"cases": cases, "refines_manifest_sha256": hashlib.sha256(raw).hexdigest(),
                                   "refined_family": args.family, "unique_samples": samples}, indent=2)+"\n", encoding="utf-8")
    print(f"Declared {samples} unique {args.family} angles with unchanged old requests and new half-step solves")


if __name__ == "__main__":
    main()
