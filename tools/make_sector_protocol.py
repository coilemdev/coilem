"""Write protocol 1.11.0: the combined A-F suite (protocol 1.10.0) solved as one repeating sector.

Protocol 1.11.0 changes exactly one field from protocol 1.10.0: every request sets
``solve_params.symmetry`` to ``"auto"``. coilEM then meshes and solves one repeating sector
when the geometry and winding repeat around the circle, and the full motor otherwise; each
measured row records which (``sector_repeats``). Motors, materials, currents, grids,
iteration caps, floors, cases and gates are unchanged.

FEMM always solves the whole motor and never reads this field, so the suite reuses the
reviewed protocol 1.10.0 combined reference bundle through a hash-bound solve-option bridge.
``backend/benchmark_suite/references.py`` checks that every request differs from its
protocol 1.10.0 request in that field alone.

    python -m tools.make_sector_protocol          # rewrite benchmarks/af-v1.11-sector
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from backend.benchmark_suite import SECTOR_PROTOCOL_VERSION
from backend.benchmark_suite.contract import canonical, read, sha, write
from backend.resources import BENCHMARK_SECTOR_SUITE_FILE, BENCHMARK_SUITE_FILE

ROOT = Path(__file__).resolve().parents[1]
SUITE = str(Path(BENCHMARK_SECTOR_SUITE_FILE).parent.as_posix())
CHANGE = {"symmetry": {"from": "full", "to": "auto"}}
REASON = (
    "Only coilEM's solved region changes: every request sets solve_params.symmetry to auto, so coilEM "
    "meshes and solves one repeating sector when the geometry and winding repeat around the circle, and the "
    "full motor otherwise. FEMM always solves the whole motor and never reads this field, so the frozen "
    "protocol 1.10.0 references remain valid for the changed requests. Motors, materials, currents, grids, "
    "iteration caps, floors and gates are unchanged. A sector solve reproduces the full-circle solve of the "
    "same mesh to round-off (tests/test_sector_symmetry.py); against a separately meshed full motor it "
    "differs at mesh level."
)


def _fixture_path(case_id: str, stage: str) -> str:
    return f"{SUITE}/fixtures/{case_id}__{stage}.json"


def requests() -> dict[str, dict]:
    """Every protocol 1.10.0 request with the sector option, keyed by its new fixture path."""

    base = read(ROOT / BENCHMARK_SUITE_FILE)
    out = {}
    for case in base["cases"]:
        for job in case["jobs"]:
            request = read(ROOT / job["fixture"])
            if request["solve_params"].get("symmetry", CHANGE["symmetry"]["from"]) != CHANGE["symmetry"]["from"]:
                raise ValueError(f"{case['id']} {job['stage']} already sets a solved region")
            changed = deepcopy(request)
            changed["solve_params"]["symmetry"] = CHANGE["symmetry"]["to"]
            out[_fixture_path(case["id"], job["stage"])] = changed
    return out


def suite(changed: dict[str, dict]) -> dict:
    """The protocol 1.11.0 suite for these changed requests."""

    base = read(ROOT / BENCHMARK_SUITE_FILE)
    cases, changed_jobs = [], []
    for case in base["cases"]:
        new_case = deepcopy(case)
        for job in new_case["jobs"]:
            path = _fixture_path(case["id"], job["stage"])
            job["fixture"] = path
            job["fixture_sha256"] = sha(ROOT / path) if (ROOT / path).is_file() else None
            job["input_sha256"] = canonical(changed[path])
            changed_jobs.append({"case_id": case["id"], "stage": job["stage"]})
        cases.append(new_case)
    return {
        "schema": base["schema"],
        "protocol_version": SECTOR_PROTOCOL_VERSION,
        "convention": base["convention"],
        "material_contract": base["material_contract"],
        "golden": base["golden"],
        "golden_sha256": base["golden_sha256"],
        "scope": f"{base['scope']}; every request solved as one repeating sector where the motor repeats",
        "cases": cases,
        "request_change": {
            "prior_protocol": base["protocol_version"],
            "solve_params": CHANGE,
            "requests": changed_jobs,
        },
        "reference_compatibility": {
            "schema": "coilem.reference_validation_bridge/v1",
            "measured_protocol_version": base["protocol_version"],
            "reason": REASON,
            "solve_option_change": {
                "schema": "coilem.solve_option_bridge/v1",
                "measured_suite": BENCHMARK_SUITE_FILE,
                "measured_suite_sha256": sha(ROOT / BENCHMARK_SUITE_FILE),
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
    print(f"wrote {len(changed)} sector requests and {SUITE}/benchmark_spec.json")


if __name__ == "__main__":
    main()
