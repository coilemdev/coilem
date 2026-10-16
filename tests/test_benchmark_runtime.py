"""Timing estimates must never be presented as measured wall-clock speedups."""
import json

import pytest

from tools.analyze_benchmark_runtime import analyze, elapsed, markdown, schedule


def store(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_case_scheduling_exposes_long_tail():
    jobs = [{"runtime_s": duration} for duration in (1, 1, 1, 9)]
    assert schedule(jobs, 2) == 10
    assert schedule(jobs, 2, longest_first=True) == 9


def test_external_measurements_keep_wall_sum_and_estimate_separate(tmp_path):
    start, end = "2026-10-15T12:00:00+00:00", "2026-10-15T12:00:10+00:00"
    store(tmp_path / "run-state.json", {"started_at": start, "completed_at": "2026-10-15T12:00:30+00:00", "status": "REVIEW_REQUIRED"})
    for case in ("a", "b"):
        store(tmp_path / "measurements" / case / "measurement.json", {
            "status": "COMPLETE", "runtime_s": 10, "started_at": start, "completed_at": end,
        })
    store(tmp_path / "measurements/broken/measurement.json", {"status": "ERROR", "runtime_s": 5})
    report = analyze(tmp_path, {"cases": [{"id": case, "phase": "A"} for case in ("a", "b", "broken")]})
    assert report["registered_wall_elapsed_s"] == 30
    assert report["completed_measurement_span_s"] == 10
    assert report["successful_job_runtime_sum_s"] == 20
    assert report["phases"]["A"]["completed_jobs"] == 2
    assert report["job_status_counts"] == {"COMPLETE": 2, "ERROR": 1}
    assert report["scheduling_estimates"][1]["longest_first_s"] == 10
    assert "Estimates are not measured speedups" in markdown(report)


def test_native_missing_and_unsupported_jobs_are_retained(tmp_path):
    store(tmp_path / "run_manifest.json", {"status": "RUNNING", "jobs": [
        {"case_id": "a", "stage": "native", "result": "jobs/a/result.json", "status": "RUNNING"},
        {"case_id": "b", "stage": "native", "result": "jobs/b/result.json", "status": "UNSUPPORTED"},
    ]})
    report = analyze(tmp_path, {"cases": [{"id": "a", "phase": "C"}, {"id": "b", "phase": "C"}]})
    assert report["registered_wall_elapsed_s"] is None
    assert report["job_status_counts"] == {"RUNNING": 1, "UNSUPPORTED": 1}
    assert report["successful_job_runtime_sum_s"] == 0


def test_missing_complete_artifact_and_escaped_paths_are_not_reported_as_completed(tmp_path):
    manifest = {"jobs": [{"case_id": "a", "stage": "native", "result": "jobs/a/result.json", "status": "COMPLETE"}]}
    store(tmp_path / "run_manifest.json", manifest)
    suite = {"cases": [{"id": "a", "phase": "A"}]}
    assert analyze(tmp_path, suite)["job_status_counts"] == {"MISSING_ARTIFACT": 1}
    manifest["jobs"][0]["result"] = "../outside.json"
    store(tmp_path / "run_manifest.json", manifest)
    with pytest.raises(ValueError, match="escapes"):
        analyze(tmp_path, suite)


@pytest.mark.parametrize("duration", [-1, float("inf"), float("nan")])
def test_invalid_runtime_is_rejected(tmp_path, duration):
    store(tmp_path / "measurements/a/measurement.json", {"status": "COMPLETE", "runtime_s": duration})
    with pytest.raises(ValueError, match="Invalid runtime"):
        analyze(tmp_path, {"cases": [{"id": "a", "phase": "A"}]})


def test_timestamps_respect_offsets_and_reject_negative_span():
    assert elapsed("2026-10-15T08:00:00-04:00", "2026-10-15T12:00:10+00:00") == 10
    with pytest.raises(ValueError, match="Completion precedes start"):
        elapsed("2026-10-15T12:00:10+00:00", "2026-10-15T12:00:00+00:00")
