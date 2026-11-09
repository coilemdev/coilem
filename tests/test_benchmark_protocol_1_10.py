"""Protocol 1.10.0: protocol 1.9.0 without the unsupported ORNL Prius placeholder (#233)."""

import copy

import pytest

from backend import resources
from backend.benchmark_suite import PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS, references
from backend.benchmark_suite.cli import inputs
from backend.benchmark_suite.contract import DEFAULT_BUNDLE, ROOT, SPEC, read, sha
from backend.benchmark_suite.references import load_bundle, load_suite
from backend.public_policy import PublicConfigError, parse_public_solve_request
from tools import make_protocol_1_10
from tools.release import qualification

SUITE = ROOT / "benchmarks/abcd-v1.10/benchmark_spec.json"
PRIOR = ROOT / "benchmarks/abcd-v1.9/benchmark_spec.json"
RETIRED = "ornl_prius_2004_ipm"


def test_protocol_1_10_is_the_default_suite():
    spec = load_suite(SUITE)
    assert spec["protocol_version"] == PROTOCOL_VERSION == "1.10.0" and "1.10.0" in SUPPORTED_PROTOCOL_VERSIONS
    assert SPEC == SUITE and resources.BENCHMARK_SUITE_FILE == "benchmarks/abcd-v1.10/benchmark_spec.json"
    assert make_protocol_1_10.suite() == read(SUITE)


def test_only_the_placeholder_leaves_and_nothing_else_changes():
    old, new = load_suite(PRIOR), load_suite(SUITE)
    assert [case for case in old["cases"] if case["id"] != RETIRED] == new["cases"]
    assert len(old["cases"]) == 47 and len(new["cases"]) == 46
    assert new["case_change"]["prior_protocol"] == "1.9.0"
    assert [(entry["case_id"], entry["phase"]) for entry in new["case_change"]["retired"]] == [(RETIRED, "C")]
    for key in ("schema", "convention", "material_contract", "golden", "golden_sha256", "request_change"):
        assert new[key] == old[key]
    bridge = {key: value for key, value in new["reference_compatibility"].items() if key != "retired_cases"}
    assert bridge == old["reference_compatibility"] and new["reference_compatibility"]["retired_cases"] == [RETIRED]
    old_configs, old_protocols, old_golden = inputs(old, [case for case in old["cases"] if case["id"] != RETIRED])
    configs, protocols, golden = inputs(new, new["cases"])
    assert (configs, protocols, golden) == (old_configs, old_protocols, old_golden) and len(configs) == 52


def test_no_frozen_protocol_file_changes():
    # The suite adds no request: every fixture is one protocol 1.9.0 already registered.
    old = {job["fixture"]: job["fixture_sha256"] for case in load_suite(PRIOR)["cases"] for job in case["jobs"]}
    for case in load_suite(SUITE)["cases"]:
        for job in case["jobs"]:
            assert old[job["fixture"]] == job["fixture_sha256"] == sha(ROOT / job["fixture"])
    assert RETIRED in {case["id"] for case in load_suite(PRIOR)["cases"]}


def test_the_reviewed_bundle_covers_every_case_of_the_suite():
    spec = load_suite(SUITE)
    manifest, records, _ = load_bundle(DEFAULT_BUNDLE, spec)
    assert manifest["validation_status"] == "REVIEWED_FOR_REGISTERED_PARITY"
    assert set(records) == {case["id"] for case in spec["cases"]} and len(records) == 46
    assert RETIRED not in manifest["records"]


def test_a_bridge_cannot_retire_a_case_that_has_a_reference(tmp_path, monkeypatch):
    spec = load_suite(SUITE)
    measured = spec["cases"][0]["id"]
    changed = copy.deepcopy(spec)
    changed["cases"] = changed["cases"][1:]
    changed["reference_compatibility"]["retired_cases"].append(measured)
    with pytest.raises(ValueError, match="cannot be retired through a bridge"):
        load_bundle(DEFAULT_BUNDLE, changed)
    unknown = copy.deepcopy(spec)
    unknown["reference_compatibility"]["retired_cases"].append("no_such_case")
    with pytest.raises(ValueError, match="retires a case the measured suite does not have"):
        load_bundle(DEFAULT_BUNDLE, unknown)
    # Dropping a case without registering it as retired is still refused.
    silent = copy.deepcopy(spec)
    silent["cases"] = silent["cases"][1:]
    with pytest.raises(ValueError, match="requires the complete measured suite"):
        load_bundle(DEFAULT_BUNDLE, silent)
    assert references.REFERENCE_INDEPENDENT_SOLVE_OPTIONS == {"nonlinear_solver": ("picard", "newton")}


def test_the_release_gate_plans_no_unsupported_case_for_the_default_suite():
    spec = load_suite(SUITE)
    bundle = resources.BENCHMARK_REFERENCE_BUNDLE_DIR
    reference = read(ROOT / bundle / "manifest.json")
    assert qualification._review_errors(ROOT, bundle, reference, spec, sha(SUITE)) == []
    with_record = {**reference, "records": {**reference["records"], RETIRED: {}}}
    assert qualification._review_errors(ROOT, bundle, with_record, spec, sha(SUITE)) == [
        "solve-option bridge retires a case that has a reference record"]


def test_the_public_policy_still_rejects_the_retired_request():
    # The rejection is covered here, outside the scored suite.
    case = next(case for case in load_suite(PRIOR)["cases"] if case["id"] == RETIRED)
    request = read(ROOT / case["jobs"][0]["fixture"])
    with pytest.raises(PublicConfigError, match="flat-buried and V-shape IPM only"):
        parse_public_solve_request(request)
