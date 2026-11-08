"""Locate runtime files in an installed package or a source checkout.

A wheel carries everything the runtime reads inside the ``backend`` package:
repository data files under ``_data/``, the built UI under ``_ui/``, the
Magneto2D executable under ``_bin/`` and the stamped ``_build_info.json``.
``setup.py`` copies them in at build time. A source checkout, including an
editable install, reads the same files from the repository instead.

This module uses only the standard library: ``setup.py`` loads it by path to
share the packaged-file list and the build-identity derivation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Iterable
from functools import reduce
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

PACKAGED_DATA_DIR = "_data"
PACKAGED_UI_DIR = "_ui"
PACKAGED_BIN_DIR = "_bin"
PACKAGED_LICENSES_DIR = "_licenses"
MAGNETO2D_LICENSES_FILE = "magneto2d-rust-crates.txt"
BUILD_INFO_FILE = "_build_info.json"
SOURCE_UI_DIR = "frontend/dist-public-boundary"

# Repository files outside ``backend/`` that the runtime reads. The build copies
# each one into ``backend/_data/<same relative path>`` after checking its bytes
# against ``snapshot-manifest.json``.
PACKAGED_DATA_FILES = (
    "materials/electrical-steel/M350-50A.csv",
    "schemas/v1/field_solution_report.schema.json",
    "schemas/v1/halbach_array_config.schema.json",
    "schemas/v1/halbach_solution_report.schema.json",
    "schemas/v1/linear_halbach_array_config.schema.json",
    "schemas/v1/linear_halbach_solution_report.schema.json",
    "schemas/v1/magnetostatic_problem.schema.json",
)
# Data files that already live inside the package; declared as package data.
PACKAGE_DATA_FILES = (
    "backend/elmer/profiles/v1.json",
    "backend/mesh_profiles/gmsh_profiles.json",
    "backend/reference_models/pyleecan_prius_2004.json",
    "backend/reference_models/pyleecan_prius_2004_config.json",
    "backend/reference_models/lrk_12s14p_source.json",
    "backend/reference_models/lrk_12s14p_config.json",
)
# ``coilem benchmark`` (#71) reads the registered suite, everything it
# registers, the frozen reference bundle and the published per-platform
# records. ``benchmark_data_files`` lists them; the build copies them into
# ``backend/_data`` like the files above.
BENCHMARK_SUITE_FILE = "benchmarks/abcd-v1.6/benchmark_spec.json"
BENCHMARK_REFERENCE_BUNDLE_DIR = "benchmarks/reference-baselines/protocol16-reviewed-20261103"
BENCHMARK_RECORDS_DIR = "benchmarks/records"
PHASE_F_SUITE_FILE = "benchmarks/abcd-v1.8/benchmark_spec.json"
PHASE_F_REFERENCE_BUNDLE_DIR = "benchmarks/reference-baselines/phase-f-reviewed-20261108"
PHASE_F_RECORD_FILE = "benchmarks/records/phase-f/windows-x86_64.json"
BENCHMARK_COLLECTION_FILE = "benchmarks/public-benchmark-collection.json"


def package_resource(*parts: str) -> Traversable:
    """Return a file or directory inside the installed ``backend`` package."""

    return reduce(lambda node, part: node / part, parts, resources.files("backend"))


def source_checkout_root() -> Path | None:
    """Return the repository root when ``backend`` is imported from a checkout."""

    root = Path(__file__).resolve().parents[1]
    markers = (
        root / "pyproject.toml",
        root / "snapshot-manifest.json",
        root / "solvers" / "magneto2d" / "Cargo.toml",
    )
    return root if all(marker.is_file() for marker in markers) else None


def data_file(relative_path: str) -> Traversable:
    """Return a repository data file such as ``schemas/v1/<name>.json``."""

    packaged = package_resource(PACKAGED_DATA_DIR, *relative_path.split("/"))
    if packaged.is_file():
        return packaged
    root = source_checkout_root()
    if root is not None and (root / relative_path).is_file():
        return root / relative_path
    raise FileNotFoundError(f"coilEM data file {relative_path} is missing from this installation")


def benchmark_data_files(root: Path) -> tuple[str, ...]:
    """The repository files ``coilem benchmark`` reads, relative to ``root``."""

    spec = json.loads((root / BENCHMARK_SUITE_FILE).read_text(encoding="utf-8"))
    files = {BENCHMARK_SUITE_FILE, spec["golden"]}
    cap_change = spec.get("reference_compatibility", {}).get("iteration_cap_change")
    if cap_change:
        measured_suite = cap_change["measured_suite"]
        files.add(measured_suite)
        measured = json.loads((root / measured_suite).read_text(encoding="utf-8"))
        for case in measured["cases"]:
            files.update(job["fixture"] for job in case["jobs"])
    for case in spec["cases"]:
        files.update(job["fixture"] for job in case["jobs"])
        if case.get("protocol"):
            files.add(case["protocol"])
        if case.get("hardware_reference"):
            files.add(case["hardware_reference"]["file"])
    bundle = json.loads((root / BENCHMARK_REFERENCE_BUNDLE_DIR / "manifest.json").read_text(encoding="utf-8"))
    files.add(f"{BENCHMARK_REFERENCE_BUNDLE_DIR}/manifest.json")
    files.update(f"{BENCHMARK_REFERENCE_BUNDLE_DIR}/{entry['file']}" for entry in bundle["records"].values())
    files.update(f"{BENCHMARK_REFERENCE_BUNDLE_DIR}/{entry['file']}" for entry in bundle.get("review_artifacts", []))
    files.update(path.relative_to(root).as_posix() for path in (root / BENCHMARK_RECORDS_DIR).glob("*.json"))
    files.update(phase_f_data_files(root))
    files.update(collection_data_files(root))
    return tuple(sorted(files))


def collection_data_files(root: Path) -> tuple[str, ...]:
    """All data needed by the composed public command, including experimental E."""
    root = root.resolve()
    if not (root / BENCHMARK_COLLECTION_FILE).is_file():
        return ()
    files, scanned = {BENCHMARK_COLLECTION_FILE}, set()

    def contained(relative):
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError("Collection data paths must be repository-relative")
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Collection data path escapes its root")
        return path

    def load(relative):
        path = contained(relative)
        files.add(path.relative_to(root).as_posix())
        return json.loads(path.read_text(encoding="utf-8"))

    def collect_evidence(value, base):
        if isinstance(value, dict):
            if isinstance(value.get("file"), str) and isinstance(value.get("sha256"), str):
                name = value["file"]
                relative = name if name.startswith("benchmarks/") else base + "/" + name
                path = contained(relative)
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != value["sha256"]:
                    raise ValueError("Collection packaged evidence changed: " + relative)
                files.add(path.relative_to(root).as_posix())
                if path.suffix == ".json" and path not in scanned:
                    scanned.add(path)
                    collect_evidence(json.loads(raw), path.parent.relative_to(root).as_posix())
            for child in value.values():
                collect_evidence(child, base)
        elif isinstance(value, list):
            for child in value:
                collect_evidence(child, base)

    descriptor = load(BENCHMARK_COLLECTION_FILE)
    for component in descriptor["components"]:
        suite_path = component["suite"]["file"]
        spec = load(suite_path)
        files.add(spec["golden"])
        for case in spec["cases"]:
            files.update(job["fixture"] for job in case["jobs"])
            if case.get("protocol"):
                files.add(case["protocol"])
        directory = component["reference_bundle"]["directory"]
        collect_evidence(load(directory + "/manifest.json"), directory)
        for entry in component["records"].values():
            record = load(entry["file"])
            source = contained(record["source"])
            if not source.is_dir():
                raise FileNotFoundError("Collection platform-record report is missing")
            files.update(path.relative_to(root).as_posix() for path in source.rglob("*.json") if path.is_file())
    for relative in files:
        if not contained(relative).is_file():
            raise FileNotFoundError("Collection runtime data is missing: " + relative)
    return tuple(sorted(files))


def phase_f_data_files(root: Path) -> tuple[str, ...]:
    """Ship the separate Windows F basis without replacing the A-D defaults."""
    root = root.resolve()
    if not (root / PHASE_F_RECORD_FILE).is_file():
        return ()

    def contained(relative):
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError("Phase F data paths must be repository-relative")
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Phase F data path escapes the data root")
        return path

    def load(relative):
        return json.loads(contained(relative).read_text(encoding="utf-8"))

    record = load(PHASE_F_RECORD_FILE)
    spec = load(PHASE_F_SUITE_FILE)
    bundle = load(PHASE_F_REFERENCE_BUNDLE_DIR + "/manifest.json")
    files = {PHASE_F_RECORD_FILE, PHASE_F_SUITE_FILE, PHASE_F_REFERENCE_BUNDLE_DIR + "/manifest.json", spec["golden"]}
    files.update(job["fixture"] for case in spec["cases"] for job in case["jobs"])
    files.update(PHASE_F_REFERENCE_BUNDLE_DIR + "/" + entry["file"] for entry in bundle["records"].values())
    files.add(PHASE_F_REFERENCE_BUNDLE_DIR + "/" + bundle["review"]["file"])
    files.update(PHASE_F_REFERENCE_BUNDLE_DIR + "/" + entry["file"] for entry in bundle.get("review_artifacts", []))

    def evidence_files(value):
        if isinstance(value, dict):
            if isinstance(value.get("file"), str) and isinstance(value.get("sha256"), str):
                prefix = PHASE_F_REFERENCE_BUNDLE_DIR + "/"
                path = contained(prefix + value["file"])
                if not path.is_relative_to(contained(PHASE_F_REFERENCE_BUNDLE_DIR)):
                    raise ValueError("Phase F evidence path escapes its bundle")
                files.add(path.relative_to(root).as_posix())
            for child in value.values():
                evidence_files(child)
        elif isinstance(value, list):
            for child in value:
                evidence_files(child)

    evidence_files(bundle)
    evidence_files(load(PHASE_F_REFERENCE_BUNDLE_DIR + "/" + bundle["review"]["file"]))
    source = contained(record["source"])
    packet = [path for path in source.rglob("*.json") if path.is_file()]
    if not source.is_dir() or not packet:
        raise FileNotFoundError("The Phase F measured-results packet is missing")
    files.update(path.relative_to(root).as_posix() for path in packet)
    for relative in files:
        if not contained(relative).is_file():
            raise FileNotFoundError("Required Phase F runtime data is missing: " + relative)
    return tuple(sorted(files))


def read_data_json(relative_path: str) -> Any:
    return json.loads(data_file(relative_path).read_text(encoding="utf-8"))


def packaged_file_path(*parts: str) -> Path | None:
    """Return a real filesystem path for a packaged file, when it exists.

    Executables and served files need an OS path. Packages installed from a
    wheel always provide one; a zip import does not, and is treated as absent.
    """

    resource = package_resource(*parts)
    return resource if isinstance(resource, Path) and resource.is_file() else None


def ui_bundle_root() -> Path | None:
    """Return the built UI: the packaged copy, else a source-checkout build."""

    index = packaged_file_path(PACKAGED_UI_DIR, "index.html")
    if index is not None:
        return index.parent
    root = source_checkout_root()
    if root is not None and (root / SOURCE_UI_DIR / "index.html").is_file():
        return root / SOURCE_UI_DIR
    return None


def stamped_build_info() -> dict[str, Any] | None:
    """Return the build identity stamped into an installed package, if any."""

    resource = package_resource(BUILD_INFO_FILE)
    try:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


BUILD_IDENTITY_FIELDS = (
    "application_version",
    "application_commit",
    "magneto2d_version",
    "magneto2d_target",
    "magneto2d_sha256",
    "ui_bundle_sha256",
    "toolchain",
)


def bundle_sha256(files: Iterable[tuple[str, bytes]]) -> str:
    """Hash a file tree from ``(relative POSIX path, content)`` pairs.

    The build info's ``ui_bundle_sha256``. Files are ordered by their path
    string, so every OS agrees: Windows orders ``Path`` objects without case.
    """

    lines = "".join(f"{path} {hashlib.sha256(data).hexdigest()}\n" for path, data in sorted(files))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def directory_sha256(root: Path) -> str:
    return bundle_sha256((path.relative_to(root).as_posix(), path.read_bytes()) for path in root.rglob("*") if path.is_file())


def build_identity() -> dict[str, Any]:
    """What this installation runs: an installed package's stamped build, or a source checkout."""

    stamped = stamped_build_info()
    if stamped is None:
        return {"installation": "source"}
    return {"installation": "package", **{field: stamped.get(field) for field in BUILD_IDENTITY_FIELDS}}


def source_checkout_commit(root: Path) -> str:
    """Derive the application commit for a checkout, as published snapshots record it."""

    try:
        snapshot_commit = json.loads((root / "snapshot-manifest.json").read_text(encoding="utf-8")).get("source_commit")
    except (OSError, json.JSONDecodeError):
        snapshot_commit = None
    if isinstance(snapshot_commit, str) and re.fullmatch(r"[0-9a-f]{40}", snapshot_commit):
        return snapshot_commit
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def application_commit() -> str:
    """``COILEM_BUILD_COMMIT``, else the stamped build identity, else the checkout's."""

    configured = os.environ.get("COILEM_BUILD_COMMIT")
    if configured:
        return configured.strip()
    stamped = stamped_build_info()
    if stamped is not None and isinstance(stamped.get("application_commit"), str):
        return stamped["application_commit"]
    root = source_checkout_root()
    return source_checkout_commit(root) if root is not None else "unknown"
