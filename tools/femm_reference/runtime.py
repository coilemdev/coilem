"""Repository-local source identity and isolated historical model namespaces."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path

from tools.benchmark_suite.external_contract import read, sha
from tools.benchmark_suite.external_contract import write as write

PACKAGE = Path(__file__).resolve().parent
DATA = PACKAGE / "data"
MANIFEST = PACKAGE / "source-manifest.json"
DEPENDENCIES = ("numpy", "pydantic", "pyfemm", "pywin32")


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def ast_fingerprint(node):
    """Hash parsed definitions consistently across supported Python versions.

    Python 3.13 changed ast.dump's treatment of empty fields. Structural JSON
    omits those optional fields explicitly, including empty new type parameters.
    Python 3.15 adds is_lazy=0 to ordinary imports; retain nonzero lazy modes.
    """
    def encode(value):
        if isinstance(value, ast.AST):
            return {"node": type(value).__name__, "fields": {
                name: encode(child) for name, child in ast.iter_fields(value)
                if child is not None and not (isinstance(child, list) and not child)
                and not (isinstance(value, (ast.Import, ast.ImportFrom)) and name == "is_lazy" and child == 0)
            }}
        if isinstance(value, list):
            return [encode(child) for child in value]
        if isinstance(value, complex):
            return {"complex": [value.real, value.imag]}
        if isinstance(value, bytes):
            return {"bytes_hex": value.hex()}
        if value is Ellipsis:
            return {"ellipsis": True}
        return value
    return canonical(encode(node))


def verify_sources(package=PACKAGE):
    """Check imported sources and requests without Git, FEMM, or old checkouts."""
    manifest = read(package / "source-manifest.json")
    for name, entry in manifest["files"].items():
        path = (package / name).resolve()
        if not path.is_relative_to(package.resolve()) or not path.is_file() or sha(path) != entry["sha256"]:
            raise ValueError(f"FEMM reference source changed or missing: {name}")
    return manifest


def activate(phase):
    """Each worker owns one pinned backend; never replace an imported backend."""
    if phase not in {"e", "f"}:
        raise ValueError("Unknown FEMM reference phase")
    source = PACKAGE / "_vendor" / phase
    loaded = sys.modules.get("backend")
    if loaded is not None and not Path(loaded.__file__).resolve().is_relative_to(source):
        raise RuntimeError("FEMM reference phases need separate worker processes; another backend is already imported")
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))


def binary_directory():
    """FEMM is installed separately; its directory can be changed per run."""
    configured = os.environ.get("COILEM_FEMM_BIN")
    return Path(configured).expanduser().resolve() if configured else Path(os.environ.get("SystemDrive", "C:") + "/femm42/bin")


def binary_hashes(*, required=False):
    expected = read(DATA / "femm-binaries.json")
    directory = binary_directory()
    if not all((directory / name).is_file() for name in expected):
        if required:
            raise ValueError("FEMM 4.2 binaries are missing; set COILEM_FEMM_BIN or use --femm-bin")
        return None
    actual = {name: sha(directory / name) for name in expected}
    if actual != expected:
        raise ValueError("FEMM binaries differ from the preserved reference build")
    return actual


def check_environment():
    if sys.platform != "win32":
        raise ValueError("FEMM reference field collection currently requires Windows COM")
    binary_hashes(required=True)
    missing = []
    for name in DEPENDENCIES:
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        raise ValueError("Missing FEMM reference dependencies: " + ", ".join(missing))


def identity(phase):
    manifest = verify_sources()
    dependencies = {}
    for name in DEPENDENCIES:
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    implementation = {path.relative_to(PACKAGE).as_posix(): sha(path) for path in sorted(PACKAGE.glob("*.py"))}
    return {
        "schema": "coilem.femm_reference_adapter/v1",
        "phase": phase.upper(),
        "source_manifest_sha256": sha(MANIFEST),
        "verified_files": len(manifest["files"]),
        "implementation_sha256": implementation,
        "dependencies": dependencies,
        "femm_binaries": binary_hashes(),
        "scientific_status": "REVIEW_REQUIRED",
        "physics_policy": "Preserved E/F meshes, materials, extraction methods and complete angle grids",
        "cache_reuse_enabled": False,
        "native_results_read": False,
    }
