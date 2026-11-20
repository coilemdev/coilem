"""Protocol 1.11.0: the combined A-F suite (1.10.0) solved as one repeating sector, on the same references."""

import copy

import pytest

from backend import resources
from backend.benchmark_suite import PROTOCOL_VERSION, SECTOR_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS, references
from backend.benchmark_suite.cli import inputs
from backend.benchmark_suite.contract import DEFAULT_BUNDLE, ROOT, SECTOR_SPEC, SPEC, canonical, read
from backend.benchmark_suite.references import load_bundle, load_suite
from backend.benchmark_suite.report import solved_region_summary, solved_region_text
from tools import make_sector_protocol
from tools.benchmark_prius import jobs as prius_jobs
from tools.benchmark_shards import plan


def test_the_sector_suite_is_supported_but_not_the_default():
    spec = load_suite(SECTOR_SPEC)
    assert spec["protocol_version"] == SECTOR_PROTOCOL_VERSION == "1.11.0" and "1.11.0" in SUPPORTED_PROTOCOL_VERSIONS
    assert PROTOCOL_VERSION == "1.10.0" and resources.BENCHMARK_SUITE_FILE == "benchmarks/af-v1.10/benchmark_spec.json"
    assert resources.BENCHMARK_SECTOR_SUITE_FILE == "benchmarks/af-v1.11-sector/benchmark_spec.json"


def test_the_generator_reproduces_the_registered_requests_and_suite():
    changed = make_sector_protocol.requests()
    assert len(changed) == 75
    for path, request in changed.items():
        assert read(ROOT / path) == request
    assert make_sector_protocol.suite(changed) == read(SECTOR_SPEC)


def test_every_request_changes_only_its_solved_region():
    old, new = load_suite(SPEC), load_suite(SECTOR_SPEC)
    old_configs, old_protocols, old_golden = inputs(old, old["cases"])
    configs, protocols, golden = inputs(new, new["cases"])
    assert protocols == old_protocols and golden == old_golden and configs.keys() == old_configs.keys()
    for key, before in old_configs.items():
        assert "symmetry" not in before["solve_params"]
        expected = copy.deepcopy(before)
        expected["solve_params"]["symmetry"] = "auto"
        assert configs[key] == expected
    # Cases, floors, grids and gates are the registered ones.
    for old_case, case in zip(old["cases"], new["cases"], strict=True):
        assert {k: v for k, v in case.items() if k != "jobs"} == {k: v for k, v in old_case.items() if k != "jobs"}
    assert len(new["request_change"]["requests"]) == 75
    assert new["request_change"]["solve_params"] == {"symmetry": {"from": "full", "to": "auto"}}


def test_an_absent_solved_region_is_the_full_motor():
    assert references.REFERENCE_INDEPENDENT_SOLVE_OPTIONS["symmetry"] == ("full", "auto")
    assert references.SOLVE_OPTION_DEFAULTS == {"symmetry": "full"}


def _without_cogging_geometry_review(monkeypatch):
    # The refined cogging references bind a review of the current geometry sources, tested on its
    # own (tests/test_refined_cogging_registration.py). This file tests only the sector bridge.
    monkeypatch.setattr(references, "_require_cogging_review", lambda directory, manifest, reviewed, review: review)


def test_the_bridge_grades_against_the_combined_references_unchanged(monkeypatch):
    _without_cogging_geometry_review(monkeypatch)
    _, records, digest = load_bundle(DEFAULT_BUNDLE, load_suite(SECTOR_SPEC))
    _, registered, registered_digest = load_bundle(DEFAULT_BUNDLE, load_suite(SPEC))
    assert records == registered and digest == registered_digest and len(records) == 68


def test_the_wheel_carries_the_sector_suite_and_its_requests():
    packaged = set(resources.benchmark_data_files(ROOT))
    spec = read(SECTOR_SPEC)
    assert resources.BENCHMARK_SECTOR_SUITE_FILE in packaged
    assert spec["reference_compatibility"]["solve_option_change"]["measured_suite"] in packaged
    assert all(job["fixture"] in packaged for case in spec["cases"] for job in case["jobs"])


@pytest.mark.parametrize(
    "mutation",
    ["missing", "measured_suite", "suite_hash", "unlisted_option", "reversed", "extra_option_change", "physical",
     "back_to_full", "input_hash", "fixture_hash", "both_bridges", "components"],
)
def test_the_sector_bridge_rejects_unregistered_changes(monkeypatch, mutation):
    spec = load_suite(SECTOR_SPEC)
    bridge = spec["reference_compatibility"]
    change = bridge["solve_option_change"]
    case = next(c for c in spec["cases"] if c["id"] == "spm_14p12s_high_pole")
    # A later job as well as the first, reference-bound one.
    job = case["jobs"][1]
    config = read(ROOT / job["fixture"])
    original_checked = references.checked_json
    if mutation == "missing":
        bridge.pop("solve_option_change")
    elif mutation == "measured_suite":
        change["measured_suite"] = "benchmarks/abcd-v1.9/benchmark_spec.json"
    elif mutation == "suite_hash":
        change["measured_suite_sha256"] = "0" * 64
    elif mutation == "unlisted_option":
        change["solve_params"]["mesh_density"] = {"from": "normal", "to": "coarse"}
    elif mutation == "reversed":
        change["solve_params"]["symmetry"] = {"from": "auto", "to": "full"}
    elif mutation == "input_hash":
        job["input_sha256"] = "0" * 64
    elif mutation == "fixture_hash":
        job["fixture_sha256"] = "0" * 64
    elif mutation == "both_bridges":
        bridge["iteration_cap_change"] = {"schema": "coilem.iteration_cap_bridge/v1"}
    elif mutation == "components":
        spec["components"] = read(SPEC)["components"]
    else:
        if mutation == "extra_option_change":
            config["solve_params"]["mesh_density"] = "fine"
        elif mutation == "physical":
            config["stator"]["stack_length_mm"] += 1
        else:
            config["solve_params"]["symmetry"] = "full"
        # Even a correctly rehashed edit cannot reuse the frozen fields.
        job["input_sha256"] = canonical(config)
        monkeypatch.setattr(references, "checked_json", lambda root, name, digest:
                            config if name == job["fixture"] else original_checked(root, name, digest))
    with pytest.raises(ValueError, match="SHA-256 mismatch|solve-option bridge|Protocol 1.11.0"):
        load_bundle(DEFAULT_BUNDLE, spec)


def test_the_sector_collection_plans_the_same_shards_on_the_sector_suite():
    registered, sector = plan(), plan(suite=resources.BENCHMARK_SECTOR_SUITE_FILE)
    assert sector["suite"] == resources.BENCHMARK_SECTOR_SUITE_FILE and sector["plan_sha256"] != registered["plan_sha256"]
    assert sector["shards"] == registered["shards"] and sector["prius_jobs"] == registered["prius_jobs"]


def test_sector_prius_jobs_change_only_their_solved_region():
    full, sector = dict(prius_jobs(True, True)), dict(prius_jobs(True, True, "auto"))
    assert full.keys() == sector.keys() and len(full) == 17
    for name, config in full.items():
        assert "symmetry" not in config["solve_params"]
        expected = copy.deepcopy(config)
        expected["solve_params"]["symmetry"] = "auto"
        assert sector[name] == expected


def test_the_report_names_the_region_each_case_solved():
    assert solved_region_text({"id": "a"}) == ""
    assert solved_region_text({"sector_repeats": {"native": 4}}) == ". Solved as one 1/4 sector"
    assert solved_region_text({"sector_repeats": {"native": None}}) == ". Solved as the full motor (it does not repeat)"
    mixed = solved_region_text({"sector_repeats": {"native-standard": 2, "native-fine": None}})
    assert mixed == ". Solved as native-standard: one 1/2 sector; native-fine: the full motor (it does not repeat)"
    rows = [{"id": "a", "sector_repeats": {"native": 4}}, {"id": "b", "sector_repeats": {"native": None}}, {"id": "c"}]
    assert solved_region_summary(rows) == ("Sector solves: 1 of 2 measured cases solved one repeating sector. "
                                           "Solved as the full motor: b.")
    assert solved_region_summary([{"id": "c"}]) == ""
