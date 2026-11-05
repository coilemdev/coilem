"""Lossless per-job runtime archives, verified before deleting temporary fields."""
from __future__ import annotations

import hashlib
import shutil
import tarfile
from pathlib import Path

from backend.benchmark_suite.contract import sha, write


def stream_hash(stream):
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def archive_runtime(runtime, destination):
    runtime, destination = Path(runtime), Path(destination)
    if not runtime.is_dir() or destination.exists():
        raise ValueError("Need an existing runtime and a new archive")
    inventory = {}
    for path in sorted(runtime.rglob("*")):
        if path.is_symlink():
            raise ValueError("Runtime archives cannot contain symbolic links")
        if path.is_file():
            inventory[path.relative_to(runtime).as_posix()] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if temporary.exists():
        raise ValueError("Interrupted archive exists; preserve it for inspection")
    with tarfile.open(temporary, "w:gz", compresslevel=1) as archive:
        archive.add(runtime, arcname="runtime")
    verified = {}
    with tarfile.open(temporary, "r|gz") as archive:
        for member in archive:
            if member.isfile():
                with archive.extractfile(member) as stream:
                    verified[Path(member.name).relative_to("runtime").as_posix()] = {
                        "bytes": member.size, "sha256": stream_hash(stream)}
    if verified != inventory:
        raise ValueError("Archive differs from original fields; originals retained")
    temporary.rename(destination)
    receipt = {"schema": "coilem.runtime_archive/v1", "archive": destination.name,
               "sha256": sha(destination), "bytes": destination.stat().st_size, "files": inventory}
    write(destination.with_name(destination.name + ".json"), receipt)
    shutil.rmtree(runtime)
    return receipt
