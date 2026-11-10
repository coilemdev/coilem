"""The refined cohort keeps measured inputs and rejects forged reference passes."""
import copy
import json
import shutil
from pathlib import Path

import pytest

from backend.benchmark_suite import references
from backend.benchmark_suite.contract import canonical, read, sha

ROOT = Path(__file__).resolve().parents[1]
SUITE = "benchmarks/cogging-refined-v1"
BUNDLE = "benchmarks/reference-baselines/cogging-refined-20261110"


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    for name in (SUITE, BUNDLE):
        shutil.copytree(ROOT / name, tmp_path / name)
    for name in read(tmp_path / BUNDLE / "geometry-review.json")["current_sources"]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    measured = read(tmp_path / SUITE / "measured-suite.json")
    for case in measured["cases"]:
        name = case["jobs"][0]["fixture"]
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    monkeypatch.setattr(references, "DATA_ROOT", tmp_path)
    return tmp_path, references.load_suite(tmp_path / SUITE / "benchmark_spec.json")


def test_refined_references_are_reviewed_and_preserve_measured_request_ids(cohort):
    root, spec = cohort
    manifest, data, _ = references.load_bundle(root / BUNDLE, spec)
    review = references.require_reviewed_bundle(root / BUNDLE, manifest, spec)
    assert spec["protocol_version"] == "1.7.1" and len(data) == 3
    assert sum(case["positions_verified"] for case in review["cases"].values()) == 75
    for case in spec["cases"]:
        assert manifest["records"][case["id"]]["input_sha256"] != case["jobs"][0]["input_sha256"]


@pytest.mark.parametrize("field,value", [("current_angle_deg", 1.0), ("rotor_step_deg", 2.5), ("corner_refinement", False)])
def test_native_mesh_bridge_rejects_other_solve_changes(cohort, field, value):
    root, spec = cohort
    job = spec["cases"][0]["jobs"][0]
    path = root / job["fixture"]
    config = read(path)
    config["solve_params"][field] = value
    write(path, config)
    job.update(input_sha256=canonical(config), fixture_sha256=sha(path))
    with pytest.raises(ValueError, match="only normal to very_fine"):
        references.load_bundle(root / BUNDLE, spec)


def test_forged_pass_receipt_cannot_hide_reference_mean_failure(cohort):
    root, spec = cohort
    folder = root / BUNDLE
    manifest = read(folder / "manifest.json")
    case = spec["cases"][0]
    entry = manifest["records"][case["id"]]
    path = folder / entry["file"]
    record = read(path)
    wave = record["result"]["cogging_torque_waveform"]
    wave["torque_Nm"] = [value + 1 for value in wave["torque_Nm"]]
    write(path, record)
    entry["sha256"] = sha(path)
    review = read(folder / "review.json")
    review["cases"][case["id"]]["record_sha256"] = entry["sha256"]
    write(folder / "review.json", review)
    manifest["review"]["sha256"] = sha(folder / "review.json")
    write(folder / "manifest.json", manifest)
    spec["reference_compatibility"]["manifest_sha256"] = sha(folder / "manifest.json")
    with pytest.raises(ValueError, match="Invalid or incomplete refined cogging reference"):
        references.load_bundle(folder, spec)


def test_mesh_bridge_cannot_change_registered_floor(cohort):
    root, spec = cohort
    changed = copy.deepcopy(spec)
    changed["cases"][0]["cogging_floor_Nm"] *= 10
    with pytest.raises(ValueError, match="changed cases, floors or stages"):
        references.load_bundle(root / BUNDLE, changed)
