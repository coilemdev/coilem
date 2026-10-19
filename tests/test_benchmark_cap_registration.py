"""Cap-only reference reuse must fail closed for physical or numerical changes."""
import copy
import shutil

import pytest

from backend import resources
from backend.benchmark_suite import references
from backend.benchmark_suite.cli import inputs
from backend.benchmark_suite.contract import DEFAULT_BUNDLE, ROOT, SPEC, canonical, read, sha
from backend.benchmark_suite.references import load_bundle, load_suite


def test_cap_registration_changes_only_nine_caps_and_keeps_frozen_references():
    old = load_suite(ROOT / "benchmarks/abcd-v1.3/benchmark_spec.json")
    new = load_suite(SPEC)
    old_configs, old_protocols, old_golden = inputs(old, old["cases"])
    configs, protocols, golden = inputs(new, new["cases"])
    assert new["protocol_version"] == "1.4.0"
    assert protocols == old_protocols and golden == old_golden
    changed = []
    for key, before in old_configs.items():
        after = configs[key]
        if before == after:
            continue
        assert before["solve_params"]["max_nonlinear_iterations"] == 100
        expected = copy.deepcopy(before)
        expected["solve_params"]["max_nonlinear_iterations"] = 200
        assert after == expected
        changed.append(key)
    assert set(changed) == {
        (case, stage)
        for case in ("spm_4p12s_small", "spm_8p12s_reference", "spm_14p12s_high_pole")
        for stage in ("native-standard", "native-fine", "analytical")
    }
    before_hashes = {p: sha(p) for p in DEFAULT_BUNDLE.glob("*.json")}
    assert load_bundle(DEFAULT_BUNDLE, new) == load_bundle(DEFAULT_BUNDLE, old)
    assert before_hashes == {p: sha(p) for p in DEFAULT_BUNDLE.glob("*.json")}
    # The wheel must carry the historical requests needed to validate the bridge.
    packaged = set(resources.benchmark_data_files(ROOT))
    assert new["reference_compatibility"]["iteration_cap_change"]["measured_suite"] in packaged
    for case in old["cases"]:
        assert all(job["fixture"] in packaged for job in case["jobs"])


def test_packaged_cap_bridge_loads_without_source_checkout(tmp_path, monkeypatch):
    for name in resources.benchmark_data_files(ROOT):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    monkeypatch.setattr(references, "DATA_ROOT", tmp_path)
    spec = load_suite(tmp_path / resources.BENCHMARK_SUITE_FILE)
    _, records, _ = load_bundle(tmp_path / resources.BENCHMARK_REFERENCE_BUNDLE_DIR, spec)
    assert len(records) == 29


@pytest.mark.parametrize("mutation", ["missing", "suite_hash", "gate", "cap", "physical", "tolerance", "input_hash", "fixture_hash"])
def test_cap_bridge_rejects_unregistered_changes(monkeypatch, mutation):
    spec = load_suite(SPEC)
    bridge = spec["reference_compatibility"]
    case = next(c for c in spec["cases"] if c["id"] == "spm_4p12s_small")
    # Exercise the fine job as well as the first, reference-bound job.
    job = case["jobs"][1]
    config = read(ROOT / job["fixture"])
    original_checked = references.checked_json
    if mutation == "missing":
        bridge.pop("iteration_cap_change")
    elif mutation == "suite_hash":
        bridge["iteration_cap_change"]["measured_suite_sha256"] = "0" * 64
    elif mutation == "gate":
        case["protocol_sha256"] = "0" * 64
    elif mutation == "input_hash":
        job["input_sha256"] = "0" * 64
    elif mutation == "fixture_hash":
        job["fixture_sha256"] = "0" * 64
    else:
        if mutation == "cap":
            config["solve_params"]["max_nonlinear_iterations"] = 201
        elif mutation == "physical":
            config["stator"]["stack_length_mm"] += 1
        else:
            config["solve_params"]["nonlinear_tolerance"] = 0.01
        # Even correctly rehashed physical/tolerance edits cannot reuse old fields.
        job["input_sha256"] = canonical(config)
        monkeypatch.setattr(references, "checked_json", lambda root, name, digest:
                            config if name == job["fixture"] else original_checked(root, name, digest))
    with pytest.raises(ValueError, match="SHA-256 mismatch|iteration-cap bridge|identity mismatch"):
        load_bundle(DEFAULT_BUNDLE, spec)
