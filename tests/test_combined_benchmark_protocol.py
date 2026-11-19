"""The default A-F registry must preserve physics, source identity and complete coverage."""
import shutil
from collections import Counter

import pytest

from backend import resources
from backend.benchmark_suite import COMMAND_PHASES, PROTOCOL_VERSION, command, composition, references
from backend.benchmark_suite.cli import inputs
from backend.benchmark_suite.contract import DEFAULT_BUNDLE, ROOT, SPEC, canonical, read, sha
from backend.benchmark_suite.ef_review import audit
from tools import make_combined_protocol
from tools.release.qualification import _review_errors


def test_default_suite_covers_all_six_phases_without_changing_existing_requests():
    spec = references.load_suite(SPEC)
    assert PROTOCOL_VERSION == spec["protocol_version"] == "1.10.0"
    assert COMMAND_PHASES == tuple("ABCDEF")
    assert Counter(c["phase"] for c in spec["cases"]) == {"A": 19, "B": 20, "C": 5, "D": 3, "E": 12, "F": 10}
    assert spec["cases"][:47] == read(ROOT / "benchmarks/abcd-v1.9/benchmark_spec.json")["cases"]
    configs, _, _ = inputs(spec, spec["cases"])
    refined = read(ROOT / "benchmarks/cogging-refined-v1/benchmark_spec.json")
    assert [c for c in spec["cases"] if c["id"] in {c["id"] for c in refined["cases"]}] == refined["cases"]
    for case in spec["cases"]:
        if case["phase"] in "EF":
            assert configs[case["id"], "native"]["solve_params"]["nonlinear_solver"] == "newton"


def test_generator_reproduces_every_registered_byte():
    for name, data in make_combined_protocol.build_files().items():
        assert (ROOT / name).read_bytes() == data, name


def test_combined_reference_preserves_four_source_commits_and_all_reviews():
    spec = references.load_suite(SPEC)
    manifest, fields, digest = references.load_bundle(DEFAULT_BUNDLE, spec)
    assert len(fields) == 68 and "ornl_prius_2004_ipm" not in fields and len(digest) == 64
    assert manifest["reference_commit"] is None and len(manifest["reference_commits"]) == 4
    assert len(manifest["components"]) == 5
    assert references.require_reviewed_bundle(DEFAULT_BUNDLE, manifest, spec)["decision"] == "ACCEPTED_FOR_REGISTERED_PARITY"
    assert _review_errors(ROOT, resources.BENCHMARK_REFERENCE_BUNDLE_DIR, manifest, spec, sha(SPEC)) == []
    hub = manifest["records"]["spm_outer_30p27s_hub__baseline"]
    assert hub["component"] == "f-hub" and hub["reference_commit"] == "5291451ca8fd307a2216cee219b9c7d2a7b30332"


@pytest.mark.parametrize("mutation", ["missing_case", "duplicate_case", "missing_component", "duplicate_component",
                                    "reversed_solver", "mesh_rule", "floor", "material", "stage"])
def test_composition_refuses_incomplete_coverage_or_unregistered_contract_changes(mutation):
    spec = read(SPEC)
    if mutation == "missing_case":
        spec["cases"].pop()
    elif mutation == "duplicate_case":
        spec["cases"].append(spec["cases"][-1])
    elif mutation == "missing_component":
        spec["components"].pop()
    elif mutation == "duplicate_component":
        spec["components"].append(spec["components"][-1])
    elif mutation in {"reversed_solver", "mesh_rule"}:
        rule = spec["components"][1]["native_solve_option_change"]
        if mutation == "reversed_solver":
            rule["nonlinear_solver"] = {"from": "newton", "to": "picard"}
        else:
            rule["mesh_density"] = {"from": "normal", "to": "very_fine"}
    elif mutation == "floor":
        next(c for c in spec["cases"] if c["phase"] == "E")["cogging_floor_Nm"] *= 2
    elif mutation == "material":
        spec["material_contract"]["magnets"]["N42"]["Br_T"] += .01
    else:
        spec["cases"][-1]["jobs"][0]["stage"] = "other"
    with pytest.raises(ValueError):
        composition.components(spec, ROOT)


def test_rehashed_physical_edit_cannot_use_native_solver_compatibility(monkeypatch):
    spec = read(SPEC)
    job = next(c for c in spec["cases"] if c["phase"] == "F")["jobs"][0]
    config = read(ROOT / job["fixture"])
    config["stator"]["stack_length_mm"] += 1
    job["input_sha256"] = canonical(config)
    original = composition.checked_json
    monkeypatch.setattr(composition, "checked_json", lambda root, name, digest:
                        config if name == job["fixture"] else original(root, name, digest))
    with pytest.raises(ValueError, match="request differs"):
        composition.components(spec, ROOT)


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    for name in resources.benchmark_data_files(ROOT):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
    monkeypatch.setattr(references, "DATA_ROOT", tmp_path)
    return tmp_path


def test_wheel_contains_all_review_dependencies_without_git_or_reference_tools(packaged):
    spec = references.load_suite(packaged / resources.BENCHMARK_SUITE_FILE)
    manifest, fields, _ = references.load_bundle(packaged / resources.BENCHMARK_REFERENCE_BUNDLE_DIR, spec)
    assert len(fields) == 68
    references.require_reviewed_bundle(packaged / resources.BENCHMARK_REFERENCE_BUNDLE_DIR, manifest, spec)


@pytest.mark.parametrize("name", ["benchmarks/af-v1.10/phase-f-source-policy.json",
                                 "benchmarks/femm-ef-20261110/field-hashes.json",
                                 "benchmarks/reference-baselines/f-original-20261110/review.json",
                                 "benchmarks/reference-baselines/f-hub-20261110/spm_outer_30p27s_hub__baseline.json"])
def test_changed_packaged_review_or_fields_fail_closed(packaged, name):
    path = packaged / name
    path.write_bytes(path.read_bytes() + b" ")
    spec = references.load_suite(packaged / resources.BENCHMARK_SUITE_FILE)
    with pytest.raises(ValueError, match="mismatch|changed"):
        references.load_bundle(packaged / resources.BENCHMARK_REFERENCE_BUNDLE_DIR, spec)


def test_quick_selection_includes_one_complete_request_per_phase_and_cli_lists_them(capsys):
    cases = command.select_cases(references.load_suite(SPEC), list(COMMAND_PHASES), True)
    assert [c["phase"] for c in cases] == list("ABCDEF")
    assert {c["id"] for c in cases} == set(command.QUICK_CASES)
    assert command.main(["--quick", "--list"]) == 0
    listed = capsys.readouterr().out
    assert "6 cases" in listed and "__cogging" in listed and "spm_outer_" in listed


def test_an_older_record_does_not_claim_coverage_of_new_phases(monkeypatch, capsys):
    monkeypatch.setattr(command, "load_records", lambda: {"windows-x86_64": {
        "platform": "windows-x86_64", "cases": {}, "case_runtime_s": {}}})
    monkeypatch.setattr(command, "select_record", lambda records: (records["windows-x86_64"], False))
    assert command.main(["--phase", "F", "--list"]) == 0
    assert "10 cases" in capsys.readouterr().out


@pytest.mark.parametrize("mutation", ["cogging_closure", "voltage_derivative", "loaded_sign"])
def test_reference_review_recomputes_scientific_checks(mutation):
    source = read(ROOT / "benchmarks/femm-ef-20261110/femm-results.json")["cases_and_controls"]
    row = next(row for row in source if row["alias"] == ("e11" if mutation == "cogging_closure" else "f00"))
    measured = read(ROOT / f"benchmarks/af-v1.10/components/{'e-normal' if row['phase'] == 'E' else 'f-original'}.json")
    case = next(c for c in measured["cases"] if c["id"] == row["case_id"])
    cfg = read(ROOT / case["jobs"][0]["fixture"])
    result = row["result"]
    if mutation == "cogging_closure":
        result["cogging_torque_waveform"]["torque_Nm"][-1] += 1
    elif mutation == "voltage_derivative":
        result["back_emf_waveform"]["phase_a_V"][10] += 1
    else:
        result["summary"]["avg_torque_Nm"] *= -1
    with pytest.raises(ValueError):
        audit(case, result, cfg)
