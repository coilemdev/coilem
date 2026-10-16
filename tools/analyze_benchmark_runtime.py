"""Analyze saved native or external reference measurements without running solvers."""
from __future__ import annotations

import argparse
import heapq
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def elapsed(start, end):
    if not start or not end:
        return None
    value = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    if value < 0:
        raise ValueError("Completion precedes start")
    return value


def schedule(jobs, workers, *, longest_first=False):
    """Counterfactual makespan with fixed job durations and no resource contention."""
    if workers < 1:
        raise ValueError("At least one worker is required")
    durations = [job["runtime_s"] for job in jobs]
    if longest_first:
        durations.sort(reverse=True)
    available = [0.0] * workers
    heapq.heapify(available)
    for duration in durations:
        start = heapq.heappop(available)
        heapq.heappush(available, start + duration)
    return max(available, default=0.0)


def analyze(root, suite):
    phases = {case["id"]: case["phase"] for case in suite["cases"]}
    manifest_path = root / "run_manifest.json"
    jobs = []
    started = completed = None
    status = None
    if manifest_path.exists():
        manifest = read(manifest_path)
        started, completed = manifest.get("started_at"), manifest.get("completed_at")
        status = manifest.get("status")
        candidates = [(job["case_id"], job["stage"], root / job["result"], job) for job in manifest["jobs"]]
    else:
        state_path = root / "run-state.json"
        if state_path.exists():
            state = read(state_path)
            started, completed = state.get("started_at"), state.get("completed_at")
            status = state.get("status")
        candidates = [(path.parent.name, "reference", path, {}) for path in sorted((root / "measurements").glob("*/measurement.json"))]
    for case_id, stage, path, registered in candidates:
        data = read(path) if path.exists() else {}
        runtime = data.get("runtime_s")
        if runtime is not None:
            runtime = float(runtime)
            if not math.isfinite(runtime) or runtime < 0:
                raise ValueError(f"Invalid runtime for {case_id}/{stage}")
        jobs.append({
            "case_id": case_id, "phase": phases.get(case_id, "UNKNOWN"), "stage": stage,
            "status": data.get("status", registered.get("status", "INCOMPLETE")), "runtime_s": runtime,
            "started_at": data.get("started_at", registered.get("started_at")),
            "completed_at": data.get("completed_at", registered.get("completed_at")),
        })
    if not jobs:
        raise ValueError("No recorded benchmark jobs found")
    measured = [job for job in jobs if job["status"] == "COMPLETE" and job["runtime_s"] is not None]
    totals = defaultdict(lambda: {"completed_jobs": 0, "job_runtime_sum_s": 0.0})
    for job in measured:
        totals[job["phase"]]["completed_jobs"] += 1
        totals[job["phase"]]["job_runtime_sum_s"] += job["runtime_s"]
    intervals = [(job["started_at"], job["completed_at"]) for job in measured if job["started_at"] and job["completed_at"]]
    if intervals:
        first = min((start for start, _ in intervals), key=datetime.fromisoformat)
        last = max((end for _, end in intervals), key=datetime.fromisoformat)
        collection_span = elapsed(first, last)
    else:
        collection_span = None
    # The suite order is available even for external producers that stored files alphabetically.
    case_order = {case["id"]: index for index, case in enumerate(suite["cases"])}
    ordered = sorted(measured, key=lambda job: case_order.get(job["case_id"], len(case_order)))
    estimates = []
    total = sum(job["runtime_s"] for job in measured)
    longest = max((job["runtime_s"] for job in measured), default=0.0)
    for workers in (1, 2, 4, 8):
        estimates.append({
            "workers": workers, "lower_bound_s": max(longest, total / workers),
            "registered_order_s": schedule(ordered, workers),
            "longest_first_s": schedule(ordered, workers, longest_first=True),
        })
    return {
        "schema": "coilem.benchmark_runtime_analysis/v1", "run_status": status,
        "job_status_counts": dict(Counter(job["status"] for job in jobs)),
        "registered_wall_elapsed_s": elapsed(started, completed),
        "completed_measurement_span_s": collection_span, "successful_job_runtime_sum_s": total,
        "phases": dict(sorted(totals.items())),
        "jobs": sorted(jobs, key=lambda job: -(job["runtime_s"] or 0)),
        "scheduling_estimates": estimates,
        "estimate_assumptions": (
            "Fixed recorded successful-job durations; no contention, startup, verification, reporting or retry overhead. "
            "Estimates are not measured speedups."
        ),
        "wall_time_scope": (
            "Registered wall time may include restarts, downtime and reporting. Measurement span runs from the first completed job's "
            "start to the last completed job's end. Neither is a sum of CPU time."
        ),
    }


def markdown(report):
    lines = ["# Recorded benchmark runtime", "", "All values below are seconds.", "",
             f"Recorded status: {report['run_status'] or 'unavailable'}; job outcomes: {report['job_status_counts']}.", "",
             f"Registered wall time: {report['registered_wall_elapsed_s']}; "
             f"completed-measurement span: {report['completed_measurement_span_s']}; "
             f"successful-job runtime sum: {report['successful_job_runtime_sum_s']:.3f}.",
             "", report["wall_time_scope"], "", "| Phase | Completed jobs | Summed job runtime |", "| --- | ---: | ---: |"]
    for phase, values in report["phases"].items():
        lines.append(f"| {phase} | {values['completed_jobs']} | {values['job_runtime_sum_s']:.3f} |")
    lines += ["", "## Scheduling estimates", "", report["estimate_assumptions"], "",
              "| Workers | Theoretical lower bound | Registered order | Longest first |", "| ---: | ---: | ---: | ---: |"]
    for row in report["scheduling_estimates"]:
        lines.append(f"| {row['workers']} | {row['lower_bound_s']:.3f} | {row['registered_order_s']:.3f} | {row['longest_first_s']:.3f} |")
    lines += ["", "## Recorded jobs", "", "| Phase | Case / stage | Status | Runtime |", "| --- | --- | --- | ---: |"]
    for job in report["jobs"]:
        runtime = "unavailable" if job["runtime_s"] is None else f"{job['runtime_s']:.3f}"
        lines.append(f"| {job['phase']} | {job['case_id']} / {job['stage']} | {job['status']} | {runtime} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=Path(__file__).resolve().parents[1] / "benchmarks/abcd-v1.3/benchmark_spec.json")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.run.resolve(), read(args.suite))
    # Always write a new artifact; keep measurement/source trees immutable.
    if args.out_dir.resolve().is_relative_to(args.run.resolve()):
        parser.error("Keep analysis output outside the measured run")
    artifacts = (("runtime-analysis.json", json.dumps(report, indent=2, allow_nan=False) + "\n"),
                 ("runtime-analysis.md", markdown(report)))
    for name, _ in artifacts:
        if (args.out_dir / name).exists():
            parser.error(f"Analysis artifact already exists: {args.out_dir / name}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in artifacts:
        path = args.out_dir / name
        path.write_text(content, encoding="utf-8", newline="\n")
    print(args.out_dir / "runtime-analysis.md")


if __name__ == "__main__":
    main()
