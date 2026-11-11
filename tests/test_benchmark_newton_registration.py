"""Protocol 1.9.0: protocol 1.6.0 with Newton for every Picard request, reusing the 1.6.0 FEMM bundle."""

import copy
import shutil

import pytest

from backend import resources
from backend.benchmark_suite import PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS, references
from backend.benchmark_suite.cli import inputs
from backend.benchmark_suite.contract import ROOT, canonical, read, sha
from backend.benchmark_suite.references import load_bundle, load_suite, require_reviewed_bundle
from tools import make_newton_protocol

DEFAULT_BUNDLE = ROOT / "benchmarks/reference-baselines/protocol16-reviewed-20261103"
SUITE = ROOT / "benchmarks/abcd-v1.9/benchmark_spec.json"
MEASURED = ROOT / "benchmarks/abcd-v1.6/benchmark_spec.json"


def test_protocol_1_9_remains_a_supported_historical_suite():
    spec = load_suite(SUITE)
    assert spec["protocol_version"] == "1.9.0" and "1.9.0" in SUPPORTED_PROTOCOL_VERSIONS
    assert PROTOCOL_VERSION == "1.10.0" and resources.BENCHMARK_SUITE_FILE == "benchmarks/af-v1.10/benchmark_spec.json"


def test_the_generator_reproduces_the_registered_requests_and_suite():
    changed = make_newton_protocol.requests()
    for path, request in changed.items():
        assert read(ROOT / path) == request
    assert make_newton_protocol.suite(changed) == read(SUITE)


def test_only_picard_requests_change_and_only_to_newton():
    old, new = load_suite(MEASURED), load_suite(SUITE)
    old_configs, old_protocols, old_golden = inputs(old, old["cases"])
    configs, protocols, golden = inputs(new, new["cases"])
    assert protocols == old_protocols and golden == old_golden
    assert [case["id"] for case in new["cases"]] == [case["id"] for case in old["cases"]]
    changed = set()
    for key, before in old_configs.items():
        after = configs[key]
        assert after["solve_params"]["nonlinear_solver"] == "newton"
        if before["solve_params"]["nonlinear_solver"] == "newton":
            assert after == before
            continue
        expected = copy.deepcopy(before)
        expected["solve_params"]["nonlinear_solver"] = "newton"
        assert after == expected
        changed.add(key)
    phases = {case["id"]: case["phase"] for case in new["cases"]}
    assert {phases[case_id] for case_id, _ in changed} == {"A", "D"}
    assert len(changed) == 28 and {(r["case_id"], r["stage"]) for r in new["request_change"]["requests"]} == changed
    # Requests that already used Newton keep their protocol 1.6.0 files.
    for old_case, case in zip(old["cases"], new["cases"]):
        for old_job, job in zip(old_case["jobs"], case["jobs"]):
            if (case["id"], job["stage"]) not in changed:
                assert job == old_job


def test_the_bridge_reuses_the_reviewed_1_6_bundle_unchanged():
    old, new = load_suite(MEASURED), load_suite(SUITE)
    before = {path: sha(path) for path in DEFAULT_BUNDLE.glob("*.json")}
    manifest, records, digest = load_bundle(DEFAULT_BUNDLE, new)
    _, old_records, old_digest = load_bundle(DEFAULT_BUNDLE, old)
    assert records == old_records and digest == old_digest and len(records) == 46
    assert require_reviewed_bundle(DEFAULT_BUNDLE, manifest, new)["decision"] == "ACCEPTED_FOR_REGISTERED_PARITY"
    assert before == {path: sha(path) for path in DEFAULT_BUNDLE.glob("*.json")}


def test_the_wheel_carries_the_measured_suite_and_its_requests():
    packaged = set(resources.benchmark_data_files(ROOT))
    change = read(SUITE)["reference_compatibility"]["solve_option_change"]
    assert change["measured_suite"] in packaged
    for case in read(MEASURED)["cases"]:
        assert all(job["fixture"] in packaged for job in case["jobs"])


def test_packaged_bridge_loads_without_source_checkout(tmp_path, monkeypatch):
    for name in resources.benchmark_data_files(ROOT):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    monkeypatch.setattr(references, "DATA_ROOT", tmp_path)
    spec = load_suite(tmp_path / "benchmarks/abcd-v1.9/benchmark_spec.json")
    manifest, records, _ = load_bundle(tmp_path / "benchmarks/reference-baselines/protocol16-reviewed-20261103", spec)
    assert len(records) == 46
    require_reviewed_bundle(tmp_path / "benchmarks/reference-baselines/protocol16-reviewed-20261103", manifest, spec)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "suite_hash", "unlisted_option", "reversed", "extra_option_change", "physical", "tolerance",
     "back_to_picard", "input_hash", "fixture_hash", "both_bridges"],
)
def test_solve_option_bridge_rejects_unregistered_changes(monkeypatch, mutation):
    spec = load_suite(SUITE)
    bridge = spec["reference_compatibility"]
    change = bridge["solve_option_change"]
    case = next(c for c in spec["cases"] if c["id"] == "spm_8p12s_reference")
    # Exercise a later job as well as the first, reference-bound job.
    job = case["jobs"][1]
    config = read(ROOT / job["fixture"])
    original_checked = references.checked_json
    if mutation == "missing":
        bridge.pop("solve_option_change")
    elif mutation == "suite_hash":
        change["measured_suite_sha256"] = "0" * 64
    elif mutation == "unlisted_option":
        change["solve_params"]["mesh_density"] = {"from": "normal", "to": "coarse"}
    elif mutation == "reversed":
        change["solve_params"]["nonlinear_solver"] = {"from": "newton", "to": "picard"}
    elif mutation == "input_hash":
        job["input_sha256"] = "0" * 64
    elif mutation == "fixture_hash":
        job["fixture_sha256"] = "0" * 64
    elif mutation == "both_bridges":
        bridge["iteration_cap_change"] = {"schema": "coilem.iteration_cap_bridge/v1"}
    else:
        if mutation == "extra_option_change":
            config["solve_params"]["max_nonlinear_iterations"] = 150
        elif mutation == "physical":
            config["stator"]["stack_length_mm"] += 1
        elif mutation == "tolerance":
            config["solve_params"]["nonlinear_tolerance"] = 0.01
        else:
            config["solve_params"]["nonlinear_solver"] = "picard"
        # Even a correctly rehashed edit cannot reuse the frozen fields.
        job["input_sha256"] = canonical(config)
        monkeypatch.setattr(references, "checked_json", lambda root, name, digest:
                            config if name == job["fixture"] else original_checked(root, name, digest))
    with pytest.raises(ValueError, match="SHA-256 mismatch|solve-option bridge|one kind of request change|identity mismatch"):
        load_bundle(DEFAULT_BUNDLE, spec)


def test_the_review_check_cannot_be_reached_with_an_unchecked_bridge(monkeypatch):
    spec = load_suite(SUITE)
    manifest = read(DEFAULT_BUNDLE / "manifest.json")
    spec["reference_compatibility"]["solve_option_change"]["solve_params"]["mesh_density"] = {"from": "normal", "to": "coarse"}
    with pytest.raises(ValueError, match="solve-option bridge"):
        require_reviewed_bundle(DEFAULT_BUNDLE, manifest, spec)
