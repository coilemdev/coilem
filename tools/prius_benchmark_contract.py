"""Frozen inputs and durable job checks for the Prius collection tools."""

from __future__ import annotations

import gzip
import hashlib
import json

from backend.benchmark_suite.contract import canonical, checked_path, identity, read, sha

SCHEMA = "coilem.pyleecan_prius_app_benchmark/v2"
LEGACY_SCHEMA = "coilem.pyleecan_prius_app_benchmark/v1"
EVIDENCE_PATH = "docs/benchmarks/pyleecan-prius-v1"
GRADING_INPUTS = {
    "protocol": f"{EVIDENCE_PATH}/protocol.json",
    "tutorial": f"{EVIDENCE_PATH}/pyleecan-tutorial-results.json",
    "loaded": f"{EVIDENCE_PATH}/pyleecan-loaded-results.json",
    "ui": f"{EVIDENCE_PATH}/pyleecan-ui-results.json",
    "hardware": "docs/hardware-validation/ornl-prius-2004/target-back-emf.json",
}
COLLECTOR_FILES = ("tools/benchmark_prius.py", "tools/prius_benchmark_contract.py")


def capture_identity(root, binary):
    """Use the common harness identity, adding the actual collection code."""
    current = identity(binary)
    current["collector_source_sha256"] = {name: sha(root / name) for name in COLLECTOR_FILES}
    return current


def verify_identity(expected, current):
    if current != expected:
        changed = sorted(key for key in set(expected) | set(current) if expected.get(key) != current.get(key))
        raise ValueError(f"Benchmark identity changed: {', '.join(changed)}")


def verify_registered_identity(registration):
    frozen = registration["identity"]
    expected = {"source_commit": frozen["commit"], "source_dirty": frozen["dirty"],
                "source_sha256": {**frozen["source_files"], **frozen["collector_source_sha256"]},
                "binary_sha256": frozen["binary_sha256"], "platform": frozen["platform"],
                "python": frozen["python"], "dependencies": frozen["dependencies"]}
    if any(registration.get(key) != value for key, value in expected.items()):
        raise ValueError("Registration disagrees with its frozen execution identity")


def freeze_inputs(root, output):
    """Copy exact grading bytes before the first field, checking the snapshot."""
    raw = {key: (root / name).read_bytes() for key, name in GRADING_INPUTS.items()}
    entries = {}
    for key, source in GRADING_INPUTS.items():
        relative = f"frozen-inputs/{key}.json"
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw[key])
        entries[key] = {"source": source, "file": relative, "sha256": sha(target)}
    if any(sha(root / GRADING_INPUTS[key]) != entry["sha256"] for key, entry in entries.items()):
        raise ValueError("Grading inputs changed while being frozen")
    return entries


def grading_inputs(run, registration, *, legacy_root=None):
    """Read the run's pinned bytes, or an explicitly labelled legacy reanalysis."""
    if registration["schema"] == LEGACY_SCHEMA:
        if legacy_root is None:
            raise ValueError("Legacy v1 run has no frozen grading inputs; use --legacy-unpinned for explicit post-hoc reanalysis")
        paths = {key: legacy_root / name for key, name in GRADING_INPUTS.items()}
        mode = "legacy-unpinned-reanalysis"
    elif registration["schema"] == SCHEMA:
        entries = registration["frozen_inputs"]
        if set(entries) != set(GRADING_INPUTS):
            raise ValueError("Incomplete frozen grading inputs")
        paths = {}
        for key, source in GRADING_INPUTS.items():
            entry = entries[key]
            path = checked_path(run, entry["file"])
            if entry["source"] != source:
                raise ValueError(f"Frozen grading input changed: {key}")
            paths[key] = path
        mode = "frozen-at-collection"
    else:
        raise ValueError("Unsupported Prius registration schema")
    payloads, hashes = {}, {}
    for key, path in paths.items():
        raw = path.read_bytes()
        hashes[key] = hashlib.sha256(raw).hexdigest()
        if registration["schema"] == SCHEMA and hashes[key] != registration["frozen_inputs"][key]["sha256"]:
            raise ValueError(f"Frozen grading input changed: {key}")
        payloads[key] = json.loads(raw, parse_constant=_reject_constant)
    return (payloads, {
        "mode": mode,
        "frozen_before_fields": mode == "frozen-at-collection",
        "input_sha256": hashes,
    })


def _reject_constant(value):
    raise ValueError(f"Non-finite grading input: {value}")


def job_folder(run, job):
    return checked_path(run, job.get("directory", job["job"]))


def verify_completed_job(run, job, expected_identity):
    """Trust a completed job only after its portable and raw artifacts verify."""
    verify_identity(expected_identity, job["identity_before"])
    verify_identity(expected_identity, job["identity_after"])
    folder = job_folder(run, job)
    for filename, key in (
        ("request.json", "request_sha256"), ("result.json", "result_sha256"),
        ("result-original.json", "result_original_sha256"),
        ("environment.json", "environment_sha256"), ("artifact-index.json", "artifact_index_sha256"),
    ):
        if sha(folder / filename) != job[key]:
            raise ValueError(f"Completed artifact changed: {job['job']}/{filename}")
    if read(folder / "request.json") != job["request"] or read(folder / "environment.json") != job["environment"]:
        raise ValueError(f"Completed request/environment changed: {job['job']}")
    result = read(folder / "result.json")
    if any(result[key] != job[key] for key in ("torque_waveform", "back_emf_waveform", "solve_metadata")):
        raise ValueError(f"Completed result differs from registration: {job['job']}")
    if result["summary"]["avg_torque_Nm"] != job["metrics"]["mean_torque_Nm"]:
        raise ValueError(f"Completed mean differs from registration: {job['job']}")
    for entry in read(folder / "artifact-index.json"):
        compressed = checked_path(folder / "retained", entry["file"] + ".gz")
        digest, size = hashlib.sha256(), 0
        with gzip.open(compressed, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if digest.hexdigest() != entry["sha256"] or size != entry["bytes"]:
            raise ValueError(f"Retained artifact changed: {job['job']}/{entry['file']}")


def selection_identity(selected):
    return canonical(selected)
