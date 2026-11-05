"""Atomic local sidecars shared by the solver, status polling and playback.

Windows readers can briefly deny replacement even when the file is writable.
Coordinate our readers/writers and retry transient sharing failures from other
readers (including scanners), without truncating the last committed JSON file.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

_LOCK = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}
_REPLACE_ATTEMPTS = 10


def _path_lock(path: Path):
    key = os.path.normcase(os.path.abspath(path))
    with _LOCK:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def read_json(path: Path) -> dict:
    # Close the file before JSON parsing; never hold a Windows file handle
    # across postprocessing, field rendering or a network response.
    with _path_lock(path):
        raw = path.read_bytes()
    return json.loads(raw)


def replace_file(temporary: Path, destination: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS-1:
                raise
            time.sleep(min(.01*2**attempt, .2))


def write_json(path: Path, payload: dict) -> None:
    raw = (json.dumps(payload, allow_nan=False, indent=2)+"\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with _path_lock(path):
        try:
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            replace_file(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
