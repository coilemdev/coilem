"""The normal Windows record uses the actual source-matched A-D collection."""

from backend.benchmark_suite.contract import ROOT, read
from tools.verify_windows_abcd_packet import MEASURED, PACKET, verify


def test_current_windows_abcd_record_reproduces_all_original_gates():
    result = verify()
    assert result["status"] == "PASS", result["errors"]
    assert result["case_counts"] == {"PASS": 46, "UNSUPPORTED": 1}
    assert result["gate_counts"] == {"PASS": 336}
    assert result["native_jobs"] == 52
    assert result["physics_guard_count"] == 69
    assert result["field_solves_executed"] == 0


def test_current_windows_publication_keeps_old_measurement_and_other_platform_pins():
    summary = read(ROOT / PACKET / "report/benchmark_summary.json")
    assert summary["run"]["identity"]["commit"] == MEASURED
    assert summary["run"]["identity"]["harness_version"] == "1.10.0"
    assert summary["reporter_harness_version"] == "1.11.0"
    assert summary["run"]["publication_projection"]["native_measurements_modified"] is False
    historical = read(ROOT / "benchmarks/windows-v051-20261105-a4f9f4d/results.json")
    assert historical["measured_commit"] == "a4f9f4dccf2ba3aad530e7bd1604ece8eeaca86f"
    macos = read(ROOT / "benchmarks/records/macos-arm64.json")
    assert macos["measured_commit"] != MEASURED
    assert "numerical_resolution" in next(row for row in summary["rows"] if row["phase"] == "A")["evaluation"]
