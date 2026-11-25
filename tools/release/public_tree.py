"""Export private release work as one history-free commit on top of public main.

The private experiments repository keeps its ``main`` equal to the public
``main``. Release work such as 0.5.10 is developed there on a private branch
whose history holds benchmark evidence that stays private
(``tools/release/private_evidence.py``; docs/RELEASING.md). That work reaches
the public repository as one new commit whose only parent is public main and
whose tree is the release tree without the private evidence. The private
history is never pushed.

    python -m tools.release.public_tree --source release/v0.5.10 --base origin/main --branch public/v0.5.10

The export reads only committed objects and works in a temporary worktree, so
the caller's checkout, index and current branch are untouched. It:

1. refuses unless the base is an ancestor of the source, the base holds no
   path classified private (public evidence is never filtered), every file
   under an evidence root is classified, and the branch does not exist yet;
2. checks the source out into the temporary worktree, removes the private
   paths and regenerates ``snapshot-manifest.json`` for that tree: its file
   list, a ``public_patches`` entry against the base for each changed file,
   ``source_commit`` set to the private source commit and
   ``history_transferred`` false; patch entries that name private paths are
   dropped;
3. refuses a tree in which any file quotes a measured claim declared in
   ``tools/release/disclosure_fingerprints.json`` (``tools/release/disclosures.py``):
   such claims stay in the private repository even when the file around them
   is public;
4. runs that tree's own ``tools/verify_snapshot.py --publication --public-tree``
   and checks the written tree again for private paths;
5. commits the tree with the base as its only parent, records the private
   source commit in the message, and creates the local branch. It never pushes.

The commit uses the repository's git identity (``git config user.name`` and
``user.email``, or the ``GIT_AUTHOR_*``/``GIT_COMMITTER_*`` variables).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tools.refresh_snapshot_manifest import MANIFEST, refreshed
from tools.release import disclosures, private_evidence

ROOT = Path(__file__).resolve().parents[2]
_GIT = shutil.which("git") or "git"


class ExportError(RuntimeError):
    """The export was refused; nothing was created."""


@dataclass(frozen=True)
class Export:
    branch: str
    commit: str
    base: str
    source: str
    dropped: tuple[str, ...]
    files: int


def _git(repo: Path, *args: str, input: str | None = None) -> str:
    completed = subprocess.run([_GIT, "-C", str(repo), *args], input=input, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ExportError(f"git {' '.join(args[:2])} failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed.stdout


def _commit(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()


def _tree_files(repo: Path, ref: str) -> list[str]:
    return [name for name in _git(repo, "ls-tree", "-r", "-z", "--name-only", ref).split("\0") if name]


def _version(tree: Path) -> str:
    match = re.search(r'^__version__ = "([^"]+)"$', (tree / "backend" / "__init__.py").read_text(encoding="utf-8"), re.MULTILINE)
    return match[1] if match else "unknown"


def verify_publication(tree: Path, python: str = sys.executable) -> None:
    """The exported tree's own snapshot and publication gate, refusing private evidence."""

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run([python, "tools/verify_snapshot.py", "--publication", "--public-tree"], cwd=tree, env=env,
                               capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ExportError("verify_snapshot.py --publication --public-tree failed on the export:\n"
                          + (completed.stderr or completed.stdout).strip())


def _refresh_manifest(tree: Path, base: str, source: str, reason: str) -> None:
    path = tree / MANIFEST
    manifest, missing = refreshed(tree, json.loads(path.read_text(encoding="utf-8")), base, reason)
    if missing:  # refreshed() only leaves paths without a reason when none is given
        raise ExportError(f"changed files need a reason: {missing}")
    manifest["public_patches"] = [entry for entry in manifest["public_patches"] if not private_evidence.is_private(entry["path"])]
    manifest["source_commit"] = source
    manifest["history_transferred"] = False
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def quoted_claims(tree: Path, fingerprints: disclosures.Fingerprints | None = None) -> list[str]:
    """Files of the exported tree that quote a measured claim kept in the private repository."""

    files = [name for name in _git(tree, "ls-files", "-z").split("\0") if name]
    return disclosures.scan_files(tree, files, fingerprints)


def export(repo: Path, source_ref: str, base_ref: str, branch: str, *, reason: str | None = None,
           verify: Callable[[Path], None] = verify_publication,
           fingerprints: disclosures.Fingerprints | None = None) -> Export:
    """Create ``branch`` at a history-free public commit of ``source_ref`` on ``base_ref``.

    ``fingerprints`` replaces the declared measured claims (tests only).
    """

    repo = Path(repo).resolve()
    try:
        source, base = _commit(repo, source_ref), _commit(repo, base_ref)
    except ExportError as exc:
        raise ExportError(f"cannot resolve the source or base commit: {exc}") from exc
    _git(repo, "check-ref-format", "--branch", branch)
    if subprocess.run([_GIT, "-C", str(repo), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                      capture_output=True, check=False).returncode == 0:
        raise ExportError(f"branch {branch} already exists; delete it or choose another name")
    if subprocess.run([_GIT, "-C", str(repo), "merge-base", "--is-ancestor", base, source],
                      capture_output=True, check=False).returncode != 0:
        raise ExportError(f"the source {source[:12]} does not contain the public base {base[:12]}; merge public main first")
    in_base = private_evidence.private_paths(_tree_files(repo, base))
    if in_base:
        raise ExportError("the public base already holds paths classified private; public evidence is never filtered. "
                          f"Fix tools/release/private_evidence.py: {in_base}")
    source_files = _tree_files(repo, source)
    unclassified = private_evidence.unclassified(source_files)
    if unclassified:
        raise ExportError(f"classify these files in tools/release/private_evidence.py first: {unclassified}")
    dropped = tuple(private_evidence.private_paths(source_files))

    scratch = Path(tempfile.mkdtemp(prefix="coilem-public-tree-"))
    tree = scratch / "tree"
    try:
        _git(repo, "worktree", "add", "--detach", "--quiet", str(tree), source)
        if dropped:
            _git(tree, "--literal-pathspecs", "rm", "-q", "--pathspec-from-file=-", "--pathspec-file-nul", input="\0".join(dropped))
        version = _version(tree)
        _refresh_manifest(tree, base, source, reason or (
            f"coilEM {version} public export of private commit {source}; "
            "generated benchmark evidence is kept in the private repository."))
        _git(tree, "add", "--", MANIFEST)
        claims = quoted_claims(tree, fingerprints)
        if claims:
            raise ExportError("measured claims kept in the private repository are quoted in public files; reword them "
                              "and keep the original privately (tools/release/disclosures.py):\n" + "\n".join(claims))
        verify(tree)
        tree_id = _git(tree, "write-tree").strip()
        exported = _tree_files(repo, tree_id)
        left = private_evidence.private_paths(exported)
        if left:
            raise ExportError(f"private evidence is still in the export: {left}")
        message = (
            f"coilEM {version} public source from private {source[:12]}\n\n"
            f"History-free export of private commit {source} onto public main {base}.\n"
            f"{len(dropped)} generated benchmark evidence files (tools/release/private_evidence.py) are kept in the\n"
            "private repository, and no private history is transferred.\n\n"
            f"Private-Source-Commit: {source}\n"
        )
        commit = _git(repo, "commit-tree", tree_id, "-p", base, "-F", "-", input=message).strip()
        _git(repo, "branch", branch, commit)
        return Export(branch=branch, commit=commit, base=base, source=source, dropped=dropped, files=len(exported))
    finally:
        subprocess.run([_GIT, "-C", str(repo), "worktree", "remove", "--force", str(tree)], capture_output=True, check=False)
        shutil.rmtree(scratch, ignore_errors=True)
        subprocess.run([_GIT, "-C", str(repo), "worktree", "prune"], capture_output=True, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="private release commit or ref to export")
    parser.add_argument("--base", required=True, help="public main (for example origin/main)")
    parser.add_argument("--branch", required=True, help="local branch to create at the export commit")
    parser.add_argument("--repo", type=Path, default=ROOT, help="repository holding both commits (default: this checkout)")
    parser.add_argument("--reason", help="public_patches reason for every changed file (default names the source commit)")
    parser.add_argument("--python", default=sys.executable, help="interpreter for the export's verify_snapshot.py")
    args = parser.parse_args(argv)
    try:
        result = export(args.repo, args.source, args.base, args.branch, reason=args.reason,
                        verify=lambda tree: verify_publication(tree, args.python))
    except ExportError as exc:
        print(f"public export refused: {exc}", file=sys.stderr)
        return 1
    print(f"{result.branch} -> {result.commit}: {result.files} files on public {result.base[:12]}, "
          f"exported from private {result.source[:12]}; {len(result.dropped)} private evidence files left out. Not pushed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
