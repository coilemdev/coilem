"""The public source export: one history-free commit on public main, without the private evidence."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.release import disclosures, private_evidence, public_tree

GIT = shutil.which("git") or "git"
PRIVATE = (
    "benchmarks/h-v1.0/RESULTS.md",
    "benchmarks/h-v1.0/results/coilem.json",
    "benchmarks/h-v1.0/references/femm5/case.json",
    "benchmarks/thermal-v0.6/spm_8p12s_concentrated-native.json",
    "benchmarks/thermal-v0.6/analytical-results.json",
    "benchmarks/thermal-v0.6/screenshots/thermal-results.png",
)
PUBLIC = (
    "benchmarks/h-v1.0/README.md",
    "benchmarks/h-v1.0/benchmark_spec.json",
    "benchmarks/h-v1.0/fixtures/design.json",
    "benchmarks/thermal-v0.6/map-interpolation-gates.json",
    "benchmarks/thermal-v0.6/published/report.json",
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run([GIT, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> dict:
    """Public main with A-F evidence, then two private release commits that add evidence."""

    repo = tmp_path / "experiments"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Export test")
    git(repo, "config", "user.email", "export-test@example.invalid")
    write(repo, "backend/__init__.py", '__version__ = "0.5.10"\n')
    write(repo, "docs/guide.md", "public main\n")
    write(repo, "benchmarks/af-v1.10/benchmark_spec.json", '{"suite": "A-F"}\n')
    write(repo, "benchmarks/qualification-5e6fab283d16/macos-arm64/report/benchmark_results.csv", "case,status\n")
    write(repo, public_tree.MANIFEST, json.dumps({"schema_version": 1, "source_commit": "c" * 40, "history_transferred": False,
                                                  "files": [], "public_patches": []}, indent=2) + "\n")
    base = commit(repo, "public main")
    git(repo, "switch", "-q", "-c", "release/v0.5.10")
    write(repo, "docs/guide.md", "release\n")
    for relative in (*PRIVATE[:3], *PUBLIC[:3]):
        write(repo, relative, f"{relative}\n")
    first = commit(repo, "Phase H with its first FEMM record")
    for relative in (*PRIVATE[3:], *PUBLIC[3:]):
        write(repo, relative, f"{relative}\n")
    write(repo, "benchmarks/h-v1.0/results/coilem.json", "regenerated\n")
    source = commit(repo, "Thermal evidence")
    return {"repo": repo, "base": base, "history": (first, source), "source": source}


def no_verify(tree: Path) -> None:
    assert not any((tree / relative).exists() for relative in PRIVATE)


def test_the_export_is_one_commit_on_public_main_without_the_private_evidence(repo: dict) -> None:
    root = repo["repo"]
    checked = []
    result = public_tree.export(root, "release/v0.5.10", "main", "public/v0.5.10",
                                verify=lambda tree: (no_verify(tree), checked.append(tree)))
    assert checked and not checked[0].exists()  # verified in a temporary worktree that is gone again
    assert result.branch == "public/v0.5.10" and result.dropped == tuple(sorted(PRIVATE))
    assert git(root, "rev-parse", "public/v0.5.10") == result.commit
    # Its only parent is public main; no private commit is reachable from it.
    assert git(root, "rev-list", "--parents", "-n", "1", result.commit).split() == [result.commit, repo["base"]]
    assert git(root, "rev-list", "--count", f"{repo['base']}..{result.commit}") == "1"
    for private_commit in repo["history"]:
        reachable = subprocess.run([GIT, "-C", str(root), "merge-base", "--is-ancestor", private_commit, result.commit], check=False)
        assert reachable.returncode == 1
    message = git(root, "log", "-1", "--format=%B", result.commit)
    assert f"Private-Source-Commit: {repo['source']}" in message

    files = set(git(root, "ls-tree", "-r", "--name-only", result.commit).splitlines())
    assert not files & set(PRIVATE) and private_evidence.private_paths(files) == []
    assert set(PUBLIC) | {"docs/guide.md", "benchmarks/af-v1.10/benchmark_spec.json",
                          "benchmarks/qualification-5e6fab283d16/macos-arm64/report/benchmark_results.csv"} <= files
    assert git(root, "show", f"{result.commit}:docs/guide.md") == "release"

    manifest = json.loads(git(root, "show", f"{result.commit}:{public_tree.MANIFEST}"))
    assert manifest["source_commit"] == repo["source"] and manifest["history_transferred"] is False
    assert {entry["path"] for entry in manifest["files"]} == files - {public_tree.MANIFEST}
    assert [(entry["base_commit"], entry["path"]) for entry in manifest["public_patches"]] == [(repo["base"], "docs/guide.md")]
    assert repo["source"] in manifest["public_patches"][0]["reason"]

    # The caller's checkout, branch and worktrees are untouched.
    assert git(root, "branch", "--show-current") == "release/v0.5.10"
    assert git(root, "status", "--porcelain") == ""
    assert len(git(root, "worktree", "list", "--porcelain").split("worktree ")) == 2


def test_patch_entries_naming_private_evidence_are_dropped(repo: dict) -> None:
    root = repo["repo"]
    manifest = json.loads((root / public_tree.MANIFEST).read_text())
    manifest["public_patches"] = [
        {"base_commit": repo["history"][0], "path": "benchmarks/h-v1.0/results/coilem.json", "source_sha256": "0" * 64, "reason": "r"},
        {"base_commit": "d" * 40, "path": "docs/old.md", "source_sha256": "1" * 64, "reason": "kept"},
    ]
    write(root, public_tree.MANIFEST, json.dumps(manifest, indent=2) + "\n")
    commit(root, "Manifest with history")
    result = public_tree.export(root, "HEAD", "main", "public/test", verify=no_verify)
    exported = json.loads(git(root, "show", f"{result.commit}:{public_tree.MANIFEST}"))
    assert [entry["path"] for entry in exported["public_patches"]] == ["docs/old.md", "docs/guide.md"]


def test_a_refused_export_creates_nothing(repo: dict) -> None:
    root = repo["repo"]

    def failing(tree: Path) -> None:
        raise public_tree.ExportError("snapshot gate failed")

    with pytest.raises(public_tree.ExportError, match="snapshot gate failed"):
        public_tree.export(root, "release/v0.5.10", "main", "public/v0.5.10", verify=failing)
    assert git(root, "branch", "--list", "public/v0.5.10") == ""
    assert len(git(root, "worktree", "list", "--porcelain").split("worktree ")) == 2

    git(root, "branch", "public/v0.5.10", "main")
    with pytest.raises(public_tree.ExportError, match="already exists"):
        public_tree.export(root, "release/v0.5.10", "main", "public/v0.5.10", verify=no_verify)


def test_a_public_file_quoting_a_known_measured_claim_is_refused(repo: dict) -> None:
    root = repo["repo"]
    claim = "the test motor's winding reads 4.25 K above the imaginary reference (Phase Z)"
    known = disclosures.Fingerprints.from_phrases([claim])
    # Its private record may keep the claim: that file is left out of the export.
    write(root, "benchmarks/h-v1.0/RESULTS.md", f"| Winding | PASS |\n\n{claim}\n")
    commit(root, "Private record states the claim")
    result = public_tree.export(root, "HEAD", "main", "public/clean", verify=no_verify, fingerprints=known)
    assert "benchmarks/h-v1.0/RESULTS.md" in result.dropped

    write(root, "docs/guide.md", "release\n\nMeasured: The test motor's winding\nreads 4.25 K above the imaginary reference (*Phase Z*).\n")
    commit(root, "A guide that quotes it")
    with pytest.raises(public_tree.ExportError, match=r"claims kept in the private repository are quoted[\s\S]*docs/guide\.md"):
        public_tree.export(root, "HEAD", "main", "public/quoted", verify=no_verify, fingerprints=known)
    assert git(root, "branch", "--list", "public/quoted") == ""
    assert len(git(root, "worktree", "list", "--porcelain").split("worktree ")) == 2


def test_the_declared_claims_are_checked_by_default(repo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo["repo"]
    claim = "the test motor's winding reads 4.25 K above the imaginary reference (Phase Z)"
    monkeypatch.setattr(disclosures.Fingerprints, "load", classmethod(lambda cls, path=None: cls.from_phrases([claim])))
    write(root, "docs/guide.md", f"{claim}\n")
    commit(root, "A guide that quotes it")
    with pytest.raises(public_tree.ExportError, match="docs/guide.md"):
        public_tree.export(root, "HEAD", "main", "public/default", verify=no_verify)


def test_unclassified_evidence_and_unrelated_bases_are_refused(repo: dict) -> None:
    root = repo["repo"]
    write(root, "benchmarks/thermal-v0.6/new-table.txt", "?\n")
    commit(root, "An unclassified file")
    with pytest.raises(public_tree.ExportError, match="new-table.txt"):
        public_tree.export(root, "HEAD", "main", "public/a", verify=no_verify)

    git(root, "switch", "-q", "--orphan", "elsewhere")
    write(root, "docs/guide.md", "unrelated\n")
    commit(root, "Unrelated history")
    with pytest.raises(public_tree.ExportError, match="does not contain the public base"):
        public_tree.export(root, "release/v0.5.10", "elsewhere", "public/b", verify=no_verify)


def test_a_base_that_already_holds_private_evidence_is_refused(repo: dict) -> None:
    root = repo["repo"]
    git(root, "switch", "-q", "main")
    write(root, "benchmarks/h-v1.0/results/coilem.json", "published\n")
    base = commit(root, "Public main with a Phase H record")
    git(root, "switch", "-q", "-c", "release/next")
    write(root, "docs/guide.md", "next\n")
    commit(root, "Next release")
    with pytest.raises(public_tree.ExportError, match="public evidence is never filtered"):
        public_tree.export(root, "release/next", base, "public/next", verify=no_verify)
