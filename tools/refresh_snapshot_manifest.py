"""Bring snapshot-manifest.json in line with the working tree.

Every tracked file has a ``files`` entry with its size and SHA-256. A file that
existed at the base commit and has changed since also gets a ``public_patches``
entry recording the hash of its prior content and the reason for the change.
New files need no patch entry. The manifest does not list itself.

    python tools/refresh_snapshot_manifest.py --reason "Why these files changed"
    python tools/refresh_snapshot_manifest.py --check

Run it after staging the change and before committing, so the base commit
(``HEAD`` unless ``--base`` says otherwise) still holds the prior content.
Running it again before the commit updates its own entries instead of adding
duplicates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

_GIT_EXECUTABLE = shutil.which("git") or "git"
MANIFEST = "snapshot-manifest.json"


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output([_GIT_EXECUTABLE, "-C", str(root), *args])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def refreshed(root: Path, manifest: dict, base: str, reason: str | None) -> tuple[dict, list[str]]:
    """Return the manifest for the working tree and the changed paths that still need a reason."""

    base_commit = _git(root, "rev-parse", base).decode().strip()
    tracked = {name for name in _git(root, "ls-files", "-z").decode().split("\0") if name and name != MANIFEST}
    order = [entry["path"] for entry in manifest["files"] if entry["path"] in tracked]
    order.extend(sorted(tracked - set(order)))
    contents = {name: (root / name).read_bytes() for name in order}
    files = [{"path": name, "bytes": len(contents[name]), "sha256": _sha256(contents[name])} for name in order]

    at_base = {}
    for line in _git(root, "ls-tree", "-r", "-z", base_commit).decode().split("\0"):
        if line:
            meta, name = line.split("\t", 1)
            at_base[name] = meta.split()[2]
    patches = list(manifest["public_patches"])
    recorded = {(entry["base_commit"], entry["path"]): index for index, entry in enumerate(patches)}
    missing_reason = []
    for name in order:
        if name not in at_base:
            continue
        prior = _git(root, "cat-file", "blob", at_base[name])
        if prior == contents[name]:
            continue
        index = recorded.get((base_commit, name))
        if index is None and reason is None:
            missing_reason.append(name)
            continue
        entry = {"base_commit": base_commit, "path": name, "source_sha256": _sha256(prior),
                 "reason": reason if reason is not None else patches[index]["reason"]}
        if index is None:
            patches.append(entry)
        else:
            patches[index] = entry
    return {**manifest, "files": files, "public_patches": patches}, missing_reason


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base", default="HEAD", help="commit holding the prior content (default: HEAD)")
    parser.add_argument("--reason", help="one sentence recorded for every changed file")
    parser.add_argument("--check", action="store_true", help="report whether the manifest is current; write nothing")
    args = parser.parse_args()
    root = args.root.resolve()
    path = root / MANIFEST
    text = path.read_text(encoding="utf-8")
    manifest, missing_reason = refreshed(root, json.loads(text), args.base, args.reason)
    if missing_reason and not args.check:
        print("Changed files need --reason:\n  " + "\n  ".join(missing_reason), file=sys.stderr)
        return 2
    updated = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        current = updated == text and not missing_reason
        print("snapshot manifest is current" if current else "snapshot manifest is out of date")
        return 0 if current else 1
    path.write_text(updated, encoding="utf-8")
    print(f"{MANIFEST}: {len(manifest['files'])} files, {len(manifest['public_patches'])} patch entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
