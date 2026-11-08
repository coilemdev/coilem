"""Retained Phase E waveforms are usable evidence, never qualification."""

import copy
import shutil
from collections import Counter

import pytest

from backend.benchmark_suite.cogging_metrics import COGGING_RELATIVE_PCT, evaluate_cogging
from backend.benchmark_suite.contract import DATA_ROOT, read, sha, write
from backend.benchmark_suite.references import (
    PHASE_E_REFERENCE_STATUS,
    load_bundle,
    load_suite,
    reference_provenance,
    require_reviewed_bundle,
)
from backend.models.performance import CoggingTorque

pytestmark = pytest.mark.pr
SUITE = DATA_ROOT / "benchmarks/abcd-v1.7/benchmark_spec.json"
BUNDLE = DATA_ROOT / "benchmarks/reference-baselines/phase-e-experimental-20261108"
RETAINED = DATA_ROOT / "benchmarks/windows-v051-20261105-a4f9f4d"


@pytest.fixture
def packet(tmp_path):
    folder = tmp_path / "bundle"
    shutil.copytree(BUNDLE, folder)
    return folder, load_suite(SUITE), read(folder / "manifest.json")


def refresh(folder, manifest, *, update_dataset=False):
    dataset = read(folder / manifest["dataset"]["file"])
    checks = read(folder / manifest["self_checks"]["file"])
    records = {cid: read(folder / entry["file"]) for cid, entry in manifest["records"].items()}
    if update_dataset:
        for cid, record in records.items():
            result = record["result"]
            dataset["cases"][cid] = {"input_sha256": record["input_sha256"],
                                      "reference_selection": result["solve_metadata"]["reference_selection"],
                                      "cogging_torque_waveform": result["cogging_torque_waveform"]}
    write(folder / manifest["dataset"]["file"], dataset)
    manifest["dataset"]["sha256"] = sha(folder / manifest["dataset"]["file"])
    manifest["reference_id"] = "sha256:" + manifest["dataset"]["sha256"]
    for cid, record in records.items():
        record["reference_id"] = manifest["reference_id"]
        entry = manifest["records"][cid]
        write(folder / entry["file"], record)
        entry["sha256"] = sha(folder / entry["file"])
        checks["cases"][cid]["record_sha256"] = entry["sha256"]
    write(folder / manifest["self_checks"]["file"], checks)
    manifest["self_checks"]["sha256"] = sha(folder / manifest["self_checks"]["file"])
    write(folder / "manifest.json", manifest)


def test_complete_retained_dataset_is_explicitly_experimental_and_immutable(packet):
    folder, spec, manifest = packet
    before = {path.relative_to(folder).as_posix(): sha(path) for path in folder.rglob("*") if path.is_file()}
    loaded, records, digest = load_bundle(folder, spec)
    assert len(records) == 12 and len(digest) == 64 and loaded == manifest
    assert loaded["validation_status"] == PHASE_E_REFERENCE_STATUS
    assert reference_provenance(loaded) == {
        "reference_id": manifest["reference_id"], "reference_identity_kind": "DATASET_SHA256",
        "reference_review_scope": "EXPERIMENTAL_REFERENCE",
    }
    assert {path.relative_to(folder).as_posix(): sha(path) for path in folder.rglob("*") if path.is_file()} == before
    assert CoggingTorque.model_fields["status"].default == "experimental"
    with pytest.raises(ValueError, match="experimental"):
        require_reviewed_bundle(folder, loaded, spec)


def test_original_gates_and_raw_ten_pass_two_yellow_are_preserved(packet):
    folder, spec, _ = packet
    _, references, _ = load_bundle(folder, spec)
    retained_waves = {row["case_id"]: row for row in read(RETAINED / "waveforms.json")["cogging"]}
    old_rows = {row["case_id"]: row for row in read(RETAINED / "results.json")["cogging"]["cases"]}
    counts = Counter()
    for case in spec["cases"]:
        cid = case["id"]
        original = old_rows[cid]["selected_reference_evaluation"]
        native = {"cogging_torque_waveform": retained_waves[cid]["native"],
                  "summary": {"cogging": original["cogging"]["candidate"]},
                  "solve_metadata": {"solver_name": "magneto2d-retained", "mesh_source": "native"}}
        config = read(DATA_ROOT / case["jobs"][0]["fixture"])
        actual = evaluate_cogging(native, references[cid], config, case["cogging_floor_Nm"])
        assert actual["status"] == original["status"]
        assert actual["gates"] == original["gates"]
        counts[actual["status"]] += 1
    assert COGGING_RELATIVE_PCT == (10.0, 20.0)
    assert counts == {"PASS": 10, "YELLOW": 2}


@pytest.mark.parametrize("field,value", [
    ("protocol_version", "1.8.0"), ("normalized", False), ("convention", "other"),
    ("validation_status", "REVIEWED_FOR_WINDOWS_ENGINEERING_PARITY"), ("reference_id", "sha256:" + "f" * 64),
    ("suite_sha256", "f" * 64), ("review", {"file": "review.json", "sha256": "f" * 64}),
    ("reference_commit", "a" * 40), ("source_directory", "C:/private"),
])
def test_manifest_cannot_promote_relabel_or_leak_private_provenance(packet, field, value):
    folder, spec, manifest = packet
    manifest[field] = value
    write(folder / "manifest.json", manifest)
    with pytest.raises((ValueError, OSError)):
        load_bundle(folder, spec)


@pytest.mark.parametrize("kind", ["missing", "extra", "input", "material", "floor"])
def test_only_the_complete_unchanged_registered_suite_is_allowed(packet, kind):
    folder, spec, manifest = packet
    if kind == "missing":
        manifest["records"].pop(next(iter(manifest["records"])))
    elif kind == "extra":
        manifest["records"]["unregistered"] = copy.deepcopy(next(iter(manifest["records"].values())))
    elif kind == "input":
        next(iter(manifest["records"].values()))["input_sha256"] = "f" * 64
    elif kind == "material":
        manifest["material_contract"]["magnets"]["N42"]["Br_T"] = 1.4
    else:
        spec["cases"][0]["cogging_floor_Nm"] *= 100
    write(folder / "manifest.json", manifest)
    with pytest.raises(ValueError):
        load_bundle(folder, spec)


@pytest.mark.parametrize("kind", ["case", "phase", "input", "status", "cohort", "commit", "private_path",
                                  "grid", "missing_endpoint", "bool", "summary", "mesh", "endpoints", "precision"])
def test_rehashed_records_still_require_identity_raw_grid_summary_and_mesh_metadata(packet, kind):
    folder, spec, manifest = packet
    entry = next(iter(manifest["records"].values()))
    path = folder / entry["file"]
    record = read(path)
    if kind == "case":
        record["case_id"] = "other"
    elif kind == "phase":
        record["phase"] = "F"
    elif kind == "input":
        record["input_sha256"] = "f" * 64
    elif kind == "status":
        record["validation_status"] = "QUALIFIED"
    elif kind == "cohort":
        record["source_cohort"] = "original"
    elif kind == "commit":
        record["public_candidate_commit"] = "f" * 40
    elif kind == "private_path":
        record["source_path"] = "C:/private"
    elif kind in {"grid", "missing_endpoint", "bool"}:
        wave = record["result"]["cogging_torque_waveform"]
        if kind == "grid":
            wave["electrical_angle_deg"][1] += .1
        elif kind == "missing_endpoint":
            wave["torque_Nm"].pop()
        else:
            wave["torque_Nm"][1] = True
    elif kind == "summary":
        record["result"]["summary"]["cogging"]["mean_Nm"] += 1
    elif kind == "mesh":
        record["result"]["solve_metadata"]["reference_selection"] = "half_airgap_mesh"
    elif kind == "endpoints":
        record["result"]["solve_metadata"]["independent_endpoints"] = False
    else:
        record["result"]["solve_metadata"]["precision"] = 1e-6
    write(path, record)
    refresh(folder, manifest)
    with pytest.raises(ValueError):
        load_bundle(folder, spec)


@pytest.mark.parametrize("capsule", ["dataset", "source_evidence", "self_checks"])
def test_changed_hash_bound_capsules_fail_closed(packet, capsule):
    folder, spec, manifest = packet
    path = folder / manifest[capsule]["file"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        load_bundle(folder, spec)


@pytest.mark.parametrize("kind", ["mean", "floor", "verdict", "selection", "case"])
def test_even_rehashed_self_checks_must_preserve_actual_values_and_verdicts(packet, kind):
    folder, spec, manifest = packet
    path = folder / manifest["self_checks"]["file"]
    checks = read(path)
    row = next(iter(checks["cases"].values()))
    if kind == "mean":
        row["mean_Nm"] += 1
    elif kind == "floor":
        row["registered_floor_Nm"] *= 100
    elif kind == "verdict":
        row["reference_cogging_mean"] = "YELLOW"
    elif kind == "selection":
        row["reference_selection"] = "unregistered"
    else:
        checks["cases"].pop(next(iter(checks["cases"])))
    write(path, checks)
    manifest["self_checks"]["sha256"] = sha(path)
    write(folder / "manifest.json", manifest)
    with pytest.raises(ValueError):
        load_bundle(folder, spec)


def test_changing_both_waveform_and_dataset_cannot_detach_retained_source(packet):
    folder, spec, manifest = packet
    entry = next(iter(manifest["records"].values()))
    path = folder / entry["file"]
    record = read(path)
    record["result"]["cogging_torque_waveform"]["torque_Nm"][0] += .001
    write(path, record)
    refresh(folder, manifest, update_dataset=True)
    with pytest.raises(ValueError):
        load_bundle(folder, spec)
