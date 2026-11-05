"""Deterministic, runtime-balanced qualification shards; no field solves."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.benchmark_suite.contract import canonical, read, sha
from backend.resources import BENCHMARK_SUITE_FILE
from tools.benchmark_prius import jobs

ROOT = Path(__file__).resolve().parents[1]


def balance(names, runtimes, count):
    if count < 1 or len(names) != len(set(names)):
        raise ValueError("Need a positive shard count and unique cases")
    groups = [[] for _ in range(min(count, len(names)))]
    totals = [0.0] * len(groups)
    for name in sorted(names, key=lambda n: (-float(runtimes.get(n) or 120), n)):
        index = min(range(len(groups)), key=lambda i: (totals[i], i))
        groups[index].append(name)
        totals[index] += float(runtimes.get(name) or 120)
    return [sorted(group) for group in groups]


def plan(root=ROOT, *, count=8, suite=BENCHMARK_SUITE_FILE):
    spec = read(root / suite)
    record = read(root / "benchmarks/records/windows-x86_64.json")
    suite_groups = balance([c["id"] for c in spec["cases"]], record.get("case_runtime_s", {}), count)
    prius_names = [name for name, _ in jobs(True, True)]
    prius_path = record.get("prius_report", "benchmarks/candidate-qualification-20261103/prius/app-results.json")
    prius_report = read(root / prius_path)
    prius_times = {job["job"]: job["metrics"].get("elapsed_s") for job in prius_report["jobs"]}
    prius_groups = balance(prius_names, prius_times, min(count, 4))
    shards = [
        {"id": f"{kind}-{i:02d}", "kind": kind, "cases": cases}
        for kind, groups in (("suite", suite_groups), ("prius", prius_groups))
        for i, cases in enumerate(groups)
    ]
    body = {"schema": "coilem.benchmark_shards/v1", "suite": suite, "suite_sha256": sha(root / suite),
            "shards": shards, "prius_jobs": prius_names}
    return {**body, "plan_sha256": canonical(body)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", type=int, default=8)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = plan(count=args.groups)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"include": result["shards"]}))


if __name__ == "__main__":
    main()
