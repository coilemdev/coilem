"""Judge pre-registered DC bench data, without changing a design or its status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.benchmark_suite.thermal_bench import check_bench, registration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--registration", type=Path, help="Owner-frozen exact motor/cooling registration")
    args = parser.parse_args()
    spec = json.loads(args.registration.read_text()) if args.registration else registration()
    result = check_bench(json.loads(args.bundle.read_text()) if args.bundle else None, spec=spec)
    print(json.dumps(result, indent=2, allow_nan=False))
    return int(result["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
