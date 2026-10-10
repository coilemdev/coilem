"""Input integrity, runtime provenance and process-safe resumable output."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from tools.benchmark_suite import HARNESS_VERSION, PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "benchmarks/abcd-v1/benchmark_spec.json"
DEFAULT_BUNDLE = ROOT / "benchmarks/reference-baselines/main-bad71d9"
# Native solver isolation can change process PATH. Provenance calls must use the
# Git executable/environment resolved before that scope, without changing solve options.
_GIT_EXECUTABLE = shutil.which("git")
_GIT_ENV = dict(os.environ)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    def reject(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    temp.replace(path)


def checked_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Input path escapes its bundle")
    return path


def checked_json(root, relative, expected_sha):
    path = checked_path(root, relative)
    if sha(path) != expected_sha:
        raise ValueError(f"Input SHA-256 mismatch: {relative}")
    return read(path)


def git(*args):
    if not _GIT_EXECUTABLE:
        raise ValueError("Git is required to register candidate provenance")
    return subprocess.check_output([_GIT_EXECUTABLE, "-C", str(ROOT), *args], env=_GIT_ENV, text=True).strip()


def identity(binary):
    # Hash actual sources, including uncommitted code when explicitly allowed.
    sources = {}
    for directory, suffixes in (
        ("backend", {".py"}),
        ("tools/benchmark_suite", {".py"}),
        ("solvers/magneto2d/src", {".rs"}),
        ("materials", {".csv", ".json"}),
    ):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and path.suffix in suffixes:
                sources[path.relative_to(ROOT).as_posix()] = sha(path)
    for name in ("tools/run_benchmarks.py", "solvers/magneto2d/Cargo.toml", "solvers/magneto2d/Cargo.lock", "snapshot-manifest.json"):
        sources[name] = sha(ROOT / name)
    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "source_sha256": canonical(sources),
        "source_files": sources,
        "binary_sha256": sha(binary),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_executable_sha256": sha(Path(os.sys.executable)),
        "dependencies": {name: importlib.metadata.version(name) for name in ("gmsh", "meshio", "numpy", "pydantic")},
        "harness_version": HARNESS_VERSION,
        "protocol_version": PROTOCOL_VERSION,
    }


@contextmanager
def run_lock(output):
    """Kernel-owned lock; released even after a crash, unlike a stale PID file."""
    output.mkdir(parents=True, exist_ok=True)
    with (output / "run.lock").open("a+b") as stream:
        try:
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("A benchmark process already owns this output directory") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
