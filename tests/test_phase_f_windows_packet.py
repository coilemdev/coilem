"""Public Phase F evidence reproduces its verdicts without private identities."""

import json

import pytest

from backend.benchmark_suite.contract import ROOT, read
from tools.verify_phase_f_windows_packet import BUNDLE, MEASURED, RECORD, public_text_errors, verify


def test_public_packet_reproduces_every_comparison_and_preserves_review_flags():
    result = verify()
    assert result["status"] == "PASS", result["errors"]
    assert result["cases"] == 10
    assert result["gate_counts"] == {"PASS": 60}
    assert result["reference_self_checks"] == 30
    assert result["mesh_controls"] == 2
    assert result["field_solves_executed"] == 0
    lrk = read(ROOT / BUNDLE / "lrk-sensitivity-review.json")
    assert lrk["original_check_counts"] == {"PASS": 9, "FAIL": 2}
    assert [row["original_status"] for row in lrk["rows"]] == ["FAIL", "FAIL"]
    assert all(row["absolute_error_mNm"] > row["allowed_error_mNm"] for row in lrk["rows"])


def test_public_record_uses_actual_native_pin_and_limits_qualification_scope():
    record = read(ROOT / RECORD)
    assert record["measured_commit"] == MEASURED
    assert len(record["physics_files"]) == 69
    assert record["platform"] == "windows-x86_64"
    assert record["reference_id"].startswith("sha256:")
    assert "reference_commit" not in record
    scope = record["qualification_scope"]
    assert scope["outputs"] == ["mean_torque", "back_emf"]
    assert scope["macos_qualified"] is False
    assert "cogging_torque" in scope["excluded_outputs"]
    assert "dq_flux_linkage" in scope["excluded_outputs"]
    assert "magnet_temperature_derating" in scope["excluded_outputs"]


@pytest.mark.parametrize("value", [
    r'"source": "C:\\private\\run"',
    '"source": "C:/private/run"',
    json.dumps({"source": "/" + "/".join(("Users", "example", "run"))}),
    json.dumps({"reference_commit": "f" * 40}),
    json.dumps({"adapter_commit": "f" * 40}),
    json.dumps({"producer_sha256": "f" * 64}),
    json.dumps({"unexpected_identity": "f" * 40}),
])
def test_public_packet_privacy_check_rejects_private_provenance(value):
    assert public_text_errors(value)


@pytest.mark.parametrize("value", [
    json.dumps({"measured_commit": MEASURED}),
    json.dumps({"reference_id": "sha256:" + "f" * 64}),
    '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
    "Public documentation: https://example.org/data",
])
def test_privacy_check_accepts_public_pin_dataset_digest_and_web_links(value):
    assert not public_text_errors(value)
