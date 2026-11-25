"""Compare the thermal network with published motor temperature measurements.

One source so far: ORNL/TM-2005/33, the 2004 Prius traction motor loaded at
four coolant temperatures. The network gets the report's losses, conductivities
and casing temperatures; nothing comes from a coilEM solve. See
``backend/benchmark_suite/thermal_published.py`` for what is assumed. Run from
a checkout:

    python -m tools.check_thermal_published --out benchmarks/thermal-v0.6/published-prius-results.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backend.benchmark_suite.thermal_published import DATA, FIXTURE, compare

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("backend/benchmark_suite/thermal_published.py", "backend/thermal_network.py", DATA, FIXTURE)


def _rounded(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, 6 if abs(value) < 1 else 3)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="write the comparison as JSON")
    args = parser.parse_args()
    result = _rounded(compare())
    result["source_sha256"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(f"contact resistance set from the report's model: {result['fitted_contact_m2K_W']} m2K/W")
    print(f"{'coolant':>7s} {'tc':3s} {'casing':>7s} {'measured':>8s} {'report model':>15s} {'network':>8s} {'range':>15s} {'diff K':>7s}")
    for row in result["rows"]:
        low, high = row["source_model_C"]
        net_low, net_high = row["network_range_C"]
        print(f"{row['coolant_C']:7d} {row['thermocouple']:3s} {row['casing_C']:7.1f} {row['measured_C']:8.1f} {low:7.1f}-{high:<7.1f} "
              f"{row['network_C']:8.1f} {net_low:7.1f}-{net_high:<7.1f} {row['difference_K']:+7.1f}")
    summary = result["summary"]
    print(f"network minus measured over {summary['points']} points: mean {summary['difference_K']['mean']:+.1f} K, "
          f"{summary['difference_K']['min']:+.1f} to {summary['difference_K']['max']:+.1f} K")
    print(f"three-thermocouple means: {summary['mean_difference_K']['min']:+.1f} to {summary['mean_difference_K']['max']:+.1f} K, "
          f"rise ratio {summary['mean_rise_ratio']['min']:.2f} to {summary['mean_rise_ratio']['max']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
