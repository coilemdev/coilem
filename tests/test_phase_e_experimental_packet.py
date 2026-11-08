"""Retained cogging evidence stays experimental when included in normal reports."""

import json

import pytest

from backend.benchmark_suite.contract import ROOT, read, sha
from backend.benchmark_suite.references import load_bundle, load_suite, require_reviewed_bundle
from tools.build_phase_e_experimental_packet import BUNDLE, MEASURED, PACKET, build, generated_files, public_errors


def test_retained_cogging_projection_is_reproducible_without_field_solves():
    result = build(check=True)
    assert result["status"] == "PASS", result["changed"]
    assert result["files"] == 31
    assert result["retained_counts"] == {"PASS": 10, "YELLOW": 2}
    assert result["field_solves_executed"] == 0
    assert result["qualification_performed"] is False


def test_experimental_bundle_has_no_accepted_reference_review_or_qualification():
    spec = load_suite(ROOT / "benchmarks/abcd-v1.7/benchmark_spec.json")
    manifest, records, _ = load_bundle(ROOT / BUNDLE, spec)
    assert manifest["validation_status"] == "EXPERIMENTAL_REFERENCE"
    assert len(records) == 12
    assert "review" not in manifest
    with pytest.raises(ValueError):
        require_reviewed_bundle(ROOT / BUNDLE, manifest, spec)
    assert all(result["summary"]["cogging"]["status"] == "experimental" for result in records.values())


def test_yellow_cogging_grades_and_historical_reference_failures_remain_visible():
    report = read(ROOT / PACKET / "comparison.json")
    assert report["native_measured_commit"] == MEASURED
    assert report["new_v055_native_collection"] is False
    assert report["counts"] == {"PASS": 10, "YELLOW": 2}
    yellow = {row["case_id"]: row for row in report["rows"] if row["status"] == "YELLOW"}
    assert set(yellow) == {"spm_8p24s_distributed_femm_validation__cogging", "spm_12p36s_distributed_femm_validation__cogging"}
    assert all(10 < row["evaluation"]["cogging"]["peak_to_peak_error_pct"] < 20 for row in yellow.values())
    assert sum(row["historical_baseline_status"] == "FAIL" for row in report["rows"]) == 3
    assert all(row["experimental"] for row in report["rows"])


def test_e_projection_does_not_relabel_or_modify_the_reviewed_f_record():
    assert sha(ROOT / "benchmarks/records/phase-f/windows-x86_64.json") == (
        "9ef239d60943b991fa9fc392dee20a673afba76b232353d5ac2569bb819d45b0"
    )
    assert not (ROOT / "benchmarks/records/phase-e/windows-x86_64.json").exists()


def test_generated_cogging_packet_has_no_private_source_identities_or_paths():
    for name, data in generated_files().items():
        assert not public_errors(data.decode()), name


@pytest.mark.parametrize("value", [
    '"source": "C:/private/run"',
    json.dumps({"reference_commit": "f" * 40}),
    json.dumps({"producer_sha256": "f" * 64}),
    json.dumps({"native_measured_commit": "f" * 40}),
])
def test_experimental_packet_privacy_guard_rejects_private_provenance(value):
    assert public_errors(value)
