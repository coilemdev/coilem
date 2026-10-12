"""Persistent per-angle Gmsh mesh cache under the coilEM user-data root.

The in-memory per-angle cache in ``backend.solver`` is lost when the backend
restarts. This module keeps the same base artifacts on disk, one gzip JSON file
per rotor angle, so re-running a design whose geometry and mesh settings are
unchanged skips Gmsh entirely, even in a new backend process.

A cached artifact is the artifact Gmsh would build again: serial Gmsh is
deterministic for the same input, and a JSON round trip keeps every float,
int, string and key order. The entry key therefore covers everything a mesh
depends on besides the caller's scope key (mesh signature, materials and
rotation convention): the rotor angle, the Gmsh version, the application and
producer versions, the mesh profile file and the Python runtime.

Every operation is best effort. A failed write leaves the cache unchanged, and
an unreadable or corrupt entry is deleted and treated as a miss, so the caller
meshes that angle again. Writes go to a temporary file and are moved into place
with ``os.replace``, so readers in other threads or other backend processes
sharing the user-data root never see a partial file. Files are not fsynced: a
file damaged by a power cut is just a corrupt entry.

The cache has its own byte budget, separate from the solve cache's, and evicts
least recently used entries. Recency is the file's modification time, which a
hit refreshes, so it is shared between processes. Pruning is serialized only
within one process: two backends sharing a user-data root can prune at the
same time, and the worst outcome is a file deleted twice or a few more entries
evicted than needed, which later runs mesh again.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend import __version__

MESH_CACHE_DIR_NAME = "mesh_cache"
MESH_CACHE_ENTRY_SCHEMA = "coilem.gmsh_mesh_cache_entry/v1"
# Bump whenever a change to the Gmsh producer or the geometry it meshes can
# change a solve-mesh artifact for the same config and rotor angle: for
# example backend/gmsh_solver.py, backend/geometry.py, backend/geometry_ir*.py,
# the winding tables in backend/geometry_drawer.py or backend/winding_utils.py,
# or how the solver maps sweep angles to rotor angles. Old entries then miss
# and age out of the budget.
GMSH_MESH_PRODUCER_VERSION = 1
DEFAULT_MESH_CACHE_MAX_BYTES = 1024 * 1024 * 1024
_ENTRY_SUFFIX = ".json.gz"
_TEMPORARY_SUFFIX = ".tmp"
# A temporary file older than this belongs to a writer that died before its
# os.replace; a live write takes milliseconds.
_STALE_TEMPORARY_AGE_S = 600.0
_PRUNE_LOCK = threading.Lock()


def mesh_cache_root() -> Path:
    """Return the mesh-cache folder, resolved on each call like the solve cache."""

    # Imported here because solve_workspace pulls in the report stack.
    from backend.solve_workspace import user_data_root

    return user_data_root() / MESH_CACHE_DIR_NAME


def _mesh_cache_max_bytes() -> int:
    return DEFAULT_MESH_CACHE_MAX_BYTES


def _gmsh_version() -> str | None:
    from backend import gmsh_solver

    if not gmsh_solver.GMSH_AVAILABLE or gmsh_solver.gmsh is None:
        return None
    return str(gmsh_solver.gmsh.__version__)


def _mesh_profile_sha256() -> str | None:
    from backend import gmsh_solver

    try:
        return gmsh_solver._load_gmsh_mesh_profile_config()[1]
    except Exception:
        return None


def mesh_cache_entry_key(
    scope: str,
    angle_key: int,
    rotor_angle_mech_deg: float,
) -> dict[str, Any] | None:
    """Return the full identity of one cached artifact, or None if Gmsh is missing."""

    gmsh_version = _gmsh_version()
    profile_sha256 = _mesh_profile_sha256()
    if gmsh_version is None or profile_sha256 is None:
        return None
    return {
        "schema": MESH_CACHE_ENTRY_SCHEMA,
        "producer_version": GMSH_MESH_PRODUCER_VERSION,
        "application_version": __version__,
        "gmsh_version": gmsh_version,
        "mesh_profile_sha256": profile_sha256,
        "runtime": {
            "python": f"{sys.implementation.name}-{sys.version_info[0]}.{sys.version_info[1]}",
            "platform": sys.platform,
            "machine": platform.machine(),
        },
        "scope": scope,
        "angle_key": int(angle_key),
        "rotor_angle_mech_deg": float(rotor_angle_mech_deg),
    }


def _entry_path(root: Path, key: dict[str, Any]) -> Path:
    digest = hashlib.sha256(
        json.dumps(key, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return root / f"{digest}{_ENTRY_SUFFIX}"


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def has_mesh_cache_entry(key: dict[str, Any]) -> bool:
    """Cheap existence probe; load_mesh_cache_entry can still miss."""

    try:
        return _entry_path(mesh_cache_root(), key).is_file()
    except OSError:
        return False


def load_mesh_cache_entry(key: dict[str, Any]) -> dict[str, Any] | None:
    """Return the cached artifact for ``key``, or None on a miss.

    The artifact is freshly parsed, so the caller owns it.
    """

    try:
        path = _entry_path(mesh_cache_root(), key)
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        _discard(path)
        return None
    try:
        payload = json.loads(gzip.decompress(raw).decode("utf-8"))
        artifact = payload.get("artifact") if isinstance(payload, dict) else None
        if payload.get("key") != key or not isinstance(artifact, dict):
            raise ValueError("mesh cache entry does not match its key")
    except Exception:
        _discard(path)
        return None
    try:
        # Mark the entry recently used for least-recently-used eviction.
        os.utime(path)
    except OSError:
        pass
    return artifact


def store_mesh_cache_entry(key: dict[str, Any], artifact: dict[str, Any]) -> bool:
    """Write one artifact atomically; return whether it was stored."""

    temporary: Path | None = None
    try:
        root = mesh_cache_root()
        root.mkdir(parents=True, exist_ok=True)
        path = _entry_path(root, key)
        text = json.dumps({"key": key, "artifact": artifact}, separators=(",", ":"))
        # mtime=0 keeps the bytes of an entry the same whoever writes it.
        data = gzip.compress(text.encode("utf-8"), compresslevel=1, mtime=0)
        temporary = root / f".{path.name}.{uuid.uuid4().hex}{_TEMPORARY_SUFFIX}"
        with temporary.open("xb") as handle:
            handle.write(data)
        os.replace(temporary, path)
        temporary = None
        return True
    except Exception:
        return False
    finally:
        if temporary is not None:
            _discard(temporary)


def prune_mesh_cache(max_bytes: int | None = None) -> None:
    """Delete least recently used entries until the cache fits its budget."""

    budget = _mesh_cache_max_bytes() if max_bytes is None else int(max_bytes)
    with _PRUNE_LOCK:
        try:
            root = mesh_cache_root()
            candidates = list(root.iterdir()) if root.is_dir() else []
        except OSError:
            return
        now = time.time()
        entries: list[tuple[float, str, int, Path]] = []
        for path in candidates:
            try:
                stat = path.stat()
            except OSError:
                continue
            if path.name.endswith(_ENTRY_SUFFIX):
                entries.append((stat.st_mtime, path.name, stat.st_size, path))
            elif (
                path.name.endswith(_TEMPORARY_SUFFIX)
                and now - stat.st_mtime > _STALE_TEMPORARY_AGE_S
            ):
                _discard(path)
        total = sum(size for _mtime, _name, size, _path in entries)
        for _mtime, _name, size, path in sorted(entries):
            if total <= budget:
                break
            _discard(path)
            total -= size


def clear_mesh_cache() -> None:
    """Delete every persisted entry (test and maintenance hook)."""

    prune_mesh_cache(max_bytes=0)
