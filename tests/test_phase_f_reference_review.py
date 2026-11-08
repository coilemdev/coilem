"""Windows Phase F accepts reviewed datasets without inventing producer commits."""

import copy
import shutil

import pytest

from backend.benchmark_suite.contract import DATA_ROOT, DEFAULT_BUNDLE, SPEC, canonical, read, sha, write
from backend.benchmark_suite.references import (
    PHASE_F_HUB_CASE,
    PHASE_F_REVIEW_SCOPE,
    load_bundle,
    load_suite,
    reference_manifest_payload_sha256,
    reference_provenance,
    require_reviewed_bundle,
)
from backend.benchmark_suite.report import build

SUITE = DATA_ROOT / "benchmarks/abcd-v1.8/benchmark_spec.json"
PUBLIC_COMMIT = "34de0f4ca1604311f15edf6fb49b5a2a1bf27909"


def _refresh(folder, manifest, review):
    for entry in manifest["records"].values():
        entry["sha256"] = sha(folder / entry["file"])
    for entry in manifest.get("mesh_controls", {}).values():
        entry["sha256"] = sha(folder / entry["file"])
    if "self_checks" in review:
        review["self_checks"]["sha256"] = sha(folder / review["self_checks"]["file"])
    for exception in review["exceptions"].values():
        evidence = exception["evidence"]
        evidence["sha256"] = sha(folder / evidence["file"])
    review.update(
        manifest_payload_sha256=reference_manifest_payload_sha256(manifest),
        source_cohorts_sha256=canonical(manifest["source_cohorts"]),
        cases={cid: {"record_sha256": entry["sha256"], "input_sha256": entry["input_sha256"],
                     "source_cohort": entry["source_cohort"]} for cid, entry in manifest["records"].items()},
    )
    write(folder / "review.json", review)
    manifest["review"] = {"file": "review.json", "sha256": sha(folder / "review.json")}
    write(folder / "manifest.json", manifest)


@pytest.fixture
def packet(tmp_path):
    source = DATA_ROOT / "benchmarks/reference-baselines/phase-f-reviewed-20261108"
    folder = tmp_path / "bundle"
    shutil.copytree(source, folder)
    manifest = read(folder / "manifest.json")
    review = read(folder / manifest["review"]["file"])
    return folder, load_suite(SUITE), manifest, review


def test_reviewed_windows_dataset_keeps_distinct_cohorts_and_failed_lrk_checks(packet):
    folder, spec, manifest, _ = packet
    before = {path.relative_to(folder).as_posix(): sha(path) for path in folder.rglob("*") if path.is_file()}
    loaded, records, digest = load_bundle(folder, spec)
    review = require_reviewed_bundle(folder, loaded, spec)
    assert loaded == manifest and len(records) == 10 and len(digest) == 64
    assert review["exceptions"]["lrk_reference_sensitivity"]["preserved_fail_indices"] == [5, 10]
    assert "reference_commit" not in reference_provenance(loaded)
    assert reference_provenance(loaded)["reference_identity_kind"] == "DATASET_SHA256"
    assert {path.relative_to(folder).as_posix(): sha(path) for path in folder.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("field,value", [
    ("protocol_version", "1.7.0"), ("reference_id", PUBLIC_COMMIT), ("normalized", False),
    ("validation_status", "REVIEWED_FOR_REGISTERED_PARITY"), ("reference_commit", PUBLIC_COMMIT),
])
def test_v2_wrong_protocol_identity_or_scope_fails_closed(packet, field, value):
    folder, spec, manifest, review = packet
    manifest[field] = value
    _refresh(folder, manifest, review)
    with pytest.raises(ValueError):
        load_bundle(folder, spec)


@pytest.mark.parametrize("kind", ["missing_case", "unknown_cohort", "different_mesh", "missing_base", "different_material"])
def test_v2_requires_exact_case_cohort_and_material_contract(packet, kind):
    folder, spec, manifest, review = packet
    if kind == "missing_case":
        manifest["records"].pop(next(iter(manifest["records"])))
    elif kind == "unknown_cohort":
        manifest["records"][PHASE_F_HUB_CASE]["source_cohort"] = "original"
    elif kind == "different_mesh":
        manifest["source_cohorts"]["hub_bulk_mesh_variant"]["bulk_mesh_mm"] = 1.0
    elif kind == "missing_base":
        manifest["source_cohorts"]["hub_bulk_mesh_variant"].pop("base_cohort")
    else:
        manifest["material_contract"] = copy.deepcopy(manifest["material_contract"])
        manifest["material_contract"]["magnets"]["N42"]["Br_T"] = 1.2
    _refresh(folder, manifest, review)
    with pytest.raises(ValueError):
        load_bundle(folder, spec)


@pytest.mark.parametrize("kind", ["grid", "missing_phase", "wrong_input", "private_identity", "local_path", "flux_grid"])
def test_v2_record_tampering_rejected_even_after_hashes_are_updated(packet, kind):
    folder, spec, manifest, review = packet
    entry = manifest["records"][PHASE_F_HUB_CASE]
    record = read(folder / entry["file"])
    if kind == "grid":
        record["result"]["torque_waveform"]["electrical_angle_deg"][0] = 1.0
    elif kind == "missing_phase":
        record["result"]["back_emf_waveform"].pop("phase_c_V")
    elif kind == "wrong_input":
        record["input_sha256"] = "f" * 64
    elif kind == "private_identity":
        record["reference_commit"] = "f" * 40
    elif kind == "local_path":
        record["result"]["solve_metadata"] = {"notes": "\\".join(("C:", "bench", "private", "producer.py"))}
    else:
        record["result"]["no_load_flux_linkage_waveform"] = {"electrical_angle_deg": [0], "phase_a_Wb": [1]}
    write(folder / entry["file"], record)
    _refresh(folder, manifest, review)
    with pytest.raises(ValueError):
        load_bundle(folder, spec)


@pytest.mark.parametrize("kind", ["missing", "macos", "global", "cases", "binding", "owner", "waiver", "lrk_status", "source_claim"])
def test_review_cannot_expand_scope_or_waive_failed_checks(packet, kind):
    folder, spec, manifest, review = packet
    if kind == "missing":
        manifest.pop("review")
        write(folder / "manifest.json", manifest)
    else:
        if kind == "macos":
            review["platform"] = "macos-arm64"
        elif kind == "global":
            review["scope"] = "GLOBAL_RELEASE_QUALIFICATION"
        elif kind == "cases":
            review["cases"].pop(PHASE_F_HUB_CASE)
        elif kind == "binding":
            review["manifest_payload_sha256"] = "f" * 64
        elif kind == "owner":
            review.pop("owner_decision_sha256")
        elif kind == "waiver":
            review["exceptions"]["lrk_reference_sensitivity"]["limits_changed"] = True
        else:
            exception = "lrk_reference_sensitivity" if kind == "lrk_status" else "mixed_source_cohorts"
            evidence = review["exceptions"][exception]["evidence"]
            data = read(folder / evidence["file"])
            if kind == "lrk_status":
                data["rows"][0]["original_status"] = "PASS"
            else:
                data["single_producer_contract_satisfied"] = True
            write(folder / evidence["file"], data)
            evidence["sha256"] = sha(folder / evidence["file"])
        write(folder / "review.json", review)
        manifest["review"]["sha256"] = sha(folder / "review.json")
        write(folder / "manifest.json", manifest)
    with pytest.raises(ValueError):
        load_bundle(folder, spec)


def test_v1_default_reference_identity_is_unchanged():
    manifest, records, _ = load_bundle(DEFAULT_BUNDLE, load_suite(SPEC))
    assert manifest["schema"] == "coilem.frozen_reference_bundle/v1" and records
    assert reference_provenance(manifest) == {"reference_commit": manifest["reference_commit"]}


@pytest.mark.parametrize("kind", ["self_pointer", "self_file", "self_hash", "control_entry", "control_file", "control_hash"])
def test_missing_or_changed_control_evidence_fails_closed(packet, kind):
    folder, spec, manifest, review = packet
    control = manifest["mesh_controls"]["spm_outer_12p9s_micro__baseline"]
    if kind == "self_pointer":
        review.pop("self_checks")
        _refresh(folder, manifest, review)
    elif kind == "control_entry":
        manifest["mesh_controls"].pop("spm_outer_12p9s_micro__baseline")
        _refresh(folder, manifest, review)
    else:
        entry = review["self_checks"] if kind.startswith("self") else control
        path = folder / entry["file"]
        if kind.endswith("file"):
            path.unlink()
        else:
            path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises((ValueError, OSError)):
        load_bundle(folder, spec)


@pytest.mark.parametrize("kind", ["false_status", "name", "limit", "delta", "spacing", "flag"])
def test_rehashed_self_check_cannot_change_results_names_limits_or_review_flags(packet, kind):
    folder, spec, manifest, review = packet
    path = folder / review["self_checks"]["file"]
    receipt = read(path)
    check = next(check for check in receipt["checks"] if check["id"].endswith(":half_airgap_mesh"))
    if kind == "false_status":
        check["status"] = "FAIL"
    elif kind == "name":
        check["id"] = "unregistered_control"
    elif kind == "limit":
        check["maximum_exclusive_pct"] = 20
    elif kind == "delta":
        check["delta_pct"]["avg_torque_Nm"] = 0
    elif kind == "spacing":
        next(iter(receipt["phase_spacing"].values()))["B_C_relative_to_A_deg"][0] += 1
    else:
        receipt["historical_review_flags"][0]["status"] = "PASS"
    write(path, receipt)
    _refresh(folder, manifest, review)
    with pytest.raises(ValueError):
        load_bundle(folder, spec)


@pytest.mark.parametrize("kind", ["cohort", "input", "case", "grid", "gap_scale", "within_limit_delta", "over_limit_delta"])
def test_rehashed_control_must_match_identity_mesh_and_independently_computed_deltas(packet, kind):
    folder, spec, manifest, review = packet
    entry = manifest["mesh_controls"]["spm_outer_12p9s_micro__baseline"]
    record = read(folder / entry["file"])
    if kind == "cohort":
        record["source_cohort"] = "hub_bulk_mesh_variant"
    elif kind == "input":
        record["input_sha256"] = "f" * 64
    elif kind == "case":
        record["case_id"] = PHASE_F_HUB_CASE
    elif kind == "grid":
        record["result"]["back_emf_waveform"]["electrical_angle_deg"][0] = 1
    elif kind == "gap_scale":
        record["result"]["solve_metadata"]["airgap_mesh_size_mm"] *= 2
    else:
        factor = 1.001 if kind == "within_limit_delta" else 1.05
        torque = record["result"]["torque_waveform"]["torque_Nm"]
        record["result"]["torque_waveform"]["torque_Nm"] = [value * factor for value in torque]
        record["result"]["summary"]["avg_torque_Nm"] *= factor
    write(folder / entry["file"], record)
    _refresh(folder, manifest, review)
    with pytest.raises(ValueError):
        load_bundle(folder, spec)


def test_phase_f_report_labels_dataset_identity_without_a_fake_commit(packet, tmp_path):
    _, spec, manifest, _ = packet
    run = {"identity": {"harness_version": "test", "protocol_version": "1.8.0", "commit": PUBLIC_COMMIT},
           "reference_mode": "FROZEN_REFERENCE", "smoke": False, **reference_provenance(manifest)}
    case = spec["cases"][0]
    rows = [{"id": case["id"], "phase": "F", "fixture": case["jobs"][0]["fixture"], "status": "PASS",
             "evaluation": {"status": "PASS", "gates": {"mean_torque": "PASS"}}, "measurements": {},
             "configurations": {"native": {"name": "report test"}}}]
    output = tmp_path / "report-test"
    output.mkdir()
    assert build(output, run, rows) == "PASS"
    for filename in ("coilem_benchmark_report.html", "benchmark_report.md"):
        text = (output / "report" / filename).read_text(encoding="utf-8")
        assert "Coilem Phase F benchmark" in text and "Reference dataset" in text
        assert PHASE_F_REVIEW_SCOPE in text and manifest["reference_id"] in text
        assert "Reference commit:" not in text and "reference commit:" not in text
