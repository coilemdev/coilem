"""Write protocol 1.9.0, the default A–D suite: protocol 1.6.0 with Newton for every Picard request.

Newton is coilEM's default nonlinear method from v0.5.6. Protocol 1.9.0 changes exactly one
field from protocol 1.6.0: each request that set ``solve_params.nonlinear_solver`` to ``picard``
(every Phase A and Phase D request) now sets ``newton``. Motors, materials, currents, grids,
iteration caps, cases and gates are unchanged, and requests that already used Newton
(Phases B and C) keep their 1.6.0 fixture files.

FEMM never reads coilEM's nonlinear method, so the suite reuses the reviewed protocol 1.6.0 FEMM
bundle through a hash-bound solve-option bridge. ``backend/benchmark_suite/references.py`` checks
that every changed request differs from its 1.6.0 request in that field alone.

    python -m tools.make_newton_protocol          # rewrite benchmarks/abcd-v1.9
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from backend.benchmark_suite.contract import canonical, read, sha, write

ROOT = Path(__file__).resolve().parents[1]
SUITE = "benchmarks/abcd-v1.9"
BASE_SUITE = "benchmarks/abcd-v1.6/benchmark_spec.json"
CHANGE = {"nonlinear_solver": {"from": "picard", "to": "newton"}}
REASON = (
    "Only coilEM's nonlinear method changes, from Picard to Newton, in the Phase A and D requests. FEMM "
    "solves its own nonlinear problem and never reads this field, so the frozen protocol 1.6.0 FEMM records "
    "remain valid for the changed requests. Motors, materials, currents, grids, iteration caps and gates "
    "are unchanged. A same-commit comparison (PR #221, e12918d) found Newton within 6e-5 of Picard on every "
    "changed request, with identical FEMM gate verdicts."
)


def _fixture_path(case_id: str, stage: str) -> str:
    return f"{SUITE}/fixtures/{case_id}__{stage}.json"


def requests() -> dict[str, dict]:
    """The changed requests, keyed by their fixture path."""

    base = read(ROOT / BASE_SUITE)
    out = {}
    for case in base["cases"]:
        for job in case["jobs"]:
            request = read(ROOT / job["fixture"])
            if request["solve_params"].get("nonlinear_solver") != CHANGE["nonlinear_solver"]["from"]:
                continue
            changed = deepcopy(request)
            changed["solve_params"]["nonlinear_solver"] = CHANGE["nonlinear_solver"]["to"]
            out[_fixture_path(case["id"], job["stage"])] = changed
    return out


def suite(changed: dict[str, dict]) -> dict:
    """The protocol 1.9.0 suite for these changed requests."""

    base = read(ROOT / BASE_SUITE)
    bundle_manifest = ROOT / "benchmarks/reference-baselines/protocol16-reviewed-20261103/manifest.json"
    bundle = read(bundle_manifest)
    cases, changed_jobs = [], []
    for case in base["cases"]:
        new_case = deepcopy(case)
        for job in new_case["jobs"]:
            path = _fixture_path(case["id"], job["stage"])
            if path not in changed:
                continue
            job["fixture"] = path
            job["fixture_sha256"] = sha(ROOT / path) if (ROOT / path).is_file() else None
            job["input_sha256"] = canonical(changed[path])
            changed_jobs.append({"case_id": case["id"], "stage": job["stage"]})
        cases.append(new_case)
    return {
        "schema": base["schema"],
        "protocol_version": "1.9.0",
        "convention": base["convention"],
        "material_contract": base["material_contract"],
        "golden": base["golden"],
        "golden_sha256": base["golden_sha256"],
        "cases": cases,
        "request_change": {
            "prior_protocol": base["protocol_version"],
            "solve_params": CHANGE,
            "requests": changed_jobs,
        },
        "reference_compatibility": {
            "schema": "coilem.reference_validation_bridge/v1",
            "measured_protocol_version": bundle["protocol_version"],
            "reference_commit": bundle["reference_commit"],
            "manifest_sha256": sha(bundle_manifest),
            "six_step_protocol_sha256": {case["id"]: case["protocol_sha256"] for case in base["cases"] if case["phase"] == "D"},
            "reason": REASON,
            "solve_option_change": {
                "schema": "coilem.solve_option_bridge/v1",
                "measured_suite": BASE_SUITE,
                "measured_suite_sha256": sha(ROOT / BASE_SUITE),
                "solve_params": CHANGE,
                "reason": REASON,
            },
        },
    }


def main() -> None:
    changed = requests()
    for path, request in changed.items():
        write(ROOT / path, request)
    write(ROOT / SUITE / "benchmark_spec.json", suite(changed))
    print(f"wrote {len(changed)} Newton requests and {SUITE}/benchmark_spec.json")


if __name__ == "__main__":
    main()
