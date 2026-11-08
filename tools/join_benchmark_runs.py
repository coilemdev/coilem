"""Join immutable, complete shards; never relabel or edit a measured request."""
from __future__ import annotations

import argparse
import copy
import shutil
from pathlib import Path

from backend.benchmark_suite.cli import hardware_targets, inputs, verify_artifact
from backend.benchmark_suite.contract import canonical, checked_path, read, sha, write
from backend.benchmark_suite.references import load_bundle, load_suite
from backend.benchmark_suite.report import build
from tools.benchmark_prius import jobs as prius_jobs
from tools.download_benchmark_shards import link_or_copy
from tools.prius_benchmark_contract import grading_inputs, verify_completed_job, verify_registered_identity


def join_suite(shards, *, suite, bundle, output):
    spec = load_suite(suite)
    expected = [(case["id"], job["stage"]) for case in spec["cases"] for job in case["jobs"]]
    configs, protocols, golden = inputs(spec, spec["cases"])
    original, gathered, receipts, intervals = None, {}, [], []
    for folder in shards:
        manifest = read(folder / "run_manifest.json")
        intervals.append((manifest["started_at"], manifest["completed_at"]))
        if manifest["status"] != "COMPLETE" or manifest["smoke"] or manifest["identity"].get("dirty") is not False:
            raise ValueError("Need complete, clean, full-grid shards")
        if manifest["selection"]["spec_sha256"] != sha(suite):
            raise ValueError("Shard suite changed")
        common = {k: v for k, v in manifest["selection"].items() if k != "case_ids"}
        if original is None:
            original = manifest
            selection = common
        if manifest["identity"] != original["identity"] or common != selection:
            raise ValueError("Mixed candidate, binary, environment or reference identities")
        if (manifest["reference_mode"] != original["reference_mode"]
                or any(manifest.get(key) != original.get(key) for key in (
                    "reference_commit", "reference_id", "reference_identity_kind", "reference_review_scope"))):
            raise ValueError("Mixed reference modes")
        selected = set(manifest["selection"]["case_ids"])
        if len(selected) != len(manifest["selection"]["case_ids"]):
            raise ValueError("Duplicate case selection")
        pairs = [(j["case_id"], j["stage"]) for j in manifest["jobs"]]
        if set(pairs) != {p for p in expected if p[0] in selected} or len(pairs) != len(set(pairs)):
            raise ValueError("Shard jobs differ from its registered selection")
        for job in manifest["jobs"]:
            key = job["case_id"], job["stage"]
            if key not in expected or key in gathered:
                raise ValueError("Unexpected or duplicate job")
            checked_path(folder, job["result"])
            request = read(checked_path(folder, job["request"]))
            if (sha(checked_path(folder, job["request"])) != job["request_sha256"]
                    or request["identity"] != original["identity"] or canonical(request["config"]) != canonical(configs[key])):
                raise ValueError("Shard request changed")
            if job["status"] == "UNSUPPORTED":
                if key[0] != "ornl_prius_2004_ipm":
                    raise ValueError("Unexpected unsupported case")
            elif job["status"] == "COMPLETE":
                measured = verify_artifact(folder, job, original["identity"])
                request = read(checked_path(folder, job["request"]))
                if measured["status"] != "COMPLETE" or job.get("exit_code") != 0:
                    raise ValueError("Incomplete result or changed registered request")
            else:
                raise ValueError("Failed or missing shard measurement")
            gathered[key] = folder, job
        receipts.append({"manifest_sha256": sha(folder / "run_manifest.json"), "case_ids": sorted(selected)})
    if set(gathered) != set(expected):
        raise ValueError("Shards do not cover exactly the complete registered suite")
    # Everything is validated before creating a derived output. Originals stay immutable.
    output.mkdir(parents=True, exist_ok=False)
    merged = copy.deepcopy(original)
    merged.update(started_at=min(i[0] for i in intervals), completed_at=max(i[1] for i in intervals))
    merged["selection"]["case_ids"] = [case["id"] for case in spec["cases"]]
    merged["jobs"] = []
    for key in expected:
        folder, job = gathered[key]
        target = checked_path(output, str(Path(job["request"]).parent))
        shutil.copytree(checked_path(folder, str(Path(job["request"]).parent)), target,
                        ignore=shutil.ignore_patterns("native-runtime", "*.tar.gz", "*.tmp"))
        merged["jobs"].append(copy.deepcopy(job))
    merged["shard_join"] = {"schema": "coilem.shard_join/v1", "inputs": receipts, "measurements_mutated": False}
    write(output / "run_manifest.json", merged)
    references = {}
    if merged["reference_mode"] == "FROZEN_REFERENCE":
        _, references, digest = load_bundle(bundle, spec)
        if digest != merged["selection"]["bundle_sha256"]:
            raise ValueError("Joined reference bundle differs from measured shards")
    from backend.benchmark_suite.cli import evaluate
    return build(output, merged, evaluate(output, merged, spec["cases"], configs, protocols, golden,
                                         references, hardware_targets(spec["cases"])), pdf=False)


def join_prius(shards, output):
    from backend.public_policy import parse_public_motor_config

    expected = {name: parse_public_motor_config(body).model_dump(mode="json") for name, body in prius_jobs(True, True)}
    first, gathered, receipts, intervals = None, {}, [], []
    for folder in shards:
        registration = read(folder / "registration.json")
        intervals.append((registration["started_utc"], registration["finished_utc"]))
        verify_registered_identity(registration)
        grading_inputs(folder, registration)
        if not registration.get("complete") or registration["status"] != "COMPLETE" or registration["source_dirty"]:
            raise ValueError("Incomplete Prius shard")
        if first is None:
            first = registration
        for key in ("identity", "frozen_inputs", "source_machine_sha256", "geometry_asset_sha256"):
            if registration[key] != first[key]:
                raise ValueError("Mixed Prius identities or grading inputs")
        names = [j["job"] for j in registration["selection"]["jobs"]]
        if len(names) != len(set(names)) or set(names) != {j["job"] for j in registration["jobs"]}:
            raise ValueError("Prius shard does not match its selection")
        for job in registration["jobs"]:
            name = job["job"]
            if name in gathered or name not in expected or job["request"] != expected[name]:
                raise ValueError("Unexpected, duplicate or modified Prius job")
            if registration["job_states"][name]["status"] != "COMPLETE":
                raise ValueError("Incomplete Prius job state")
            verify_completed_job(folder, job, first["identity"])
            gathered[name] = folder, job, registration["job_states"][name]
        receipts.append(sha(folder / "registration.json"))
    if set(gathered) != set(expected):
        raise ValueError("Incomplete Prius coverage")
    output.mkdir(parents=True, exist_ok=False)
    merged = copy.deepcopy(first)
    merged.update(started_utc=min(i[0] for i in intervals), finished_utc=max(i[1] for i in intervals))
    merged.update(jobs=[], job_states={}, selection={"curve": True, "refinement": True, "only": None,
                  "jobs": [{"job": name, "request": body} for name, body in expected.items()]})
    for entry in first["frozen_inputs"].values():
        target = checked_path(output, entry["file"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checked_path(shards[0], entry["file"]), target)
    for name in expected:
        folder, job, state = gathered[name]
        target = checked_path(output, job["directory"])
        shutil.copytree(checked_path(folder, job["directory"]), target, copy_function=link_or_copy)
        merged["jobs"].append(job)
        merged["job_states"][name] = state
    merged["shard_join"] = {"registrations_sha256": receipts, "measurements_mutated": False}
    write(output / "registration.json", merged)
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--reference-bundle", type=Path)
    parser.add_argument("--prius", action="store_true")
    args = parser.parse_args()
    if args.prius:
        join_prius(args.shards, args.out)
    else:
        if not args.suite or not args.reference_bundle:
            parser.error("--suite and --reference-bundle are required")
        join_suite(args.shards, suite=args.suite, bundle=args.reference_bundle, output=args.out)


if __name__ == "__main__":
    main()
