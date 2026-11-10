"""Standard-library execution primitives for independently supplied producers.

Keep these separate from backend.benchmark_suite: an external producer may
provide its own backend package, so importing the application would claim its
namespace before the producer can initialize it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    def reject(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)


def json_bytes(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(json_bytes(value))
        replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def replace_with_retry(source, destination, *, timeout_s=3.0):
    """Retry only transient Windows access/sharing violations, with a deadline."""
    deadline = time.monotonic() + timeout_s
    delay = 0.02
    while True:
        try:
            Path(source).replace(destination)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in (5, 32, 33) or time.monotonic() >= deadline:
                raise
            time.sleep(min(delay, max(0, deadline - time.monotonic())))
            delay = min(delay * 2, 0.2)


@contextmanager
def run_lock(output):
    """Use the same kernel lock format as native benchmark output directories."""
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
