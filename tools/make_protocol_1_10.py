"""Write protocol 1.10.0, the default A–D suite: protocol 1.9.0 without the unsupported ORNL Prius placeholder.

Protocol 1.9.0 carried ``ornl_prius_2004_ipm``, a deferred hardware fixture that the public policy
rejects. It was recorded as UNSUPPORTED, ran no field solve and never had a FEMM record. Protocol
1.10.0 retires it from the scored suite (#233). Every other case, request, grid and gate is
protocol 1.9.0's, byte for byte, and no fixture file is added or changed.

The suite keeps protocol 1.9.0's bridge to the reviewed protocol 1.6.0 FEMM bundle and adds
``retired_cases`` to it. ``backend/benchmark_suite/references.py`` accepts a retired case only if
the measured suite has it and the bundle holds no record for it.

    python -m tools.make_protocol_1_10          # rewrite benchmarks/abcd-v1.10/benchmark_spec.json
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from backend.benchmark_suite.contract import read, write

ROOT = Path(__file__).resolve().parents[1]
SUITE = "benchmarks/abcd-v1.10/benchmark_spec.json"
BASE_SUITE = "benchmarks/abcd-v1.9/benchmark_spec.json"
RETIRED = {
    "ornl_prius_2004_ipm": (
        "Deferred ORNL 2004 Prius hardware placeholder. The public policy rejects its HoleM50 rotor, so "
        "it was recorded as UNSUPPORTED, ran no field solve and has no FEMM record. The dedicated "
        "17-job Pyleecan Prius software benchmark is separate and unchanged; hardware correlation is "
        "tracked in public issue 82."
    ),
}


def suite() -> dict:
    """The protocol 1.10.0 suite."""

    base = read(ROOT / BASE_SUITE)
    phases = {case["id"]: case["phase"] for case in base["cases"]}
    if not set(RETIRED) <= set(phases):
        raise ValueError("A retired case is not in protocol 1.9.0")
    out = deepcopy(base)
    out["protocol_version"] = "1.10.0"
    out["cases"] = [case for case in out["cases"] if case["id"] not in RETIRED]
    out["case_change"] = {
        "prior_protocol": base["protocol_version"],
        "retired": [{"case_id": case_id, "phase": phases[case_id], "reason": reason} for case_id, reason in RETIRED.items()],
    }
    out["reference_compatibility"]["retired_cases"] = sorted(RETIRED)
    return out


def main() -> None:
    write(ROOT / SUITE, suite())
    print(f"wrote {SUITE}")


if __name__ == "__main__":
    main()
