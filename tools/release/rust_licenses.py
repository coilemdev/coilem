"""Collect the license files of the Rust crates compiled into Magneto2D.

A wheel ships the compiled Magneto2D executable, which statically links its
crate dependencies, so the wheel must carry those crates' license notices.
This resolves the normal (linked) dependency graph for one target from
Cargo.lock and writes every license file the crates distribute, with identical
texts printed once. Standard library only: setup.py loads it by path.

    python -m tools.release.rust_licenses --target x86_64-unknown-linux-gnu --output FILE
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "solvers" / "magneto2d" / "Cargo.toml"
_LICENSE_PREFIXES = ("license", "licence", "copying", "copyright", "notice", "unlicense")


@dataclass
class Crate:
    name: str
    version: str
    license: str
    repository: str
    license_files: dict[str, str] = field(default_factory=dict)


def host_target(rustc: str = "rustc") -> str:
    output = subprocess.run([rustc, "-vV"], capture_output=True, text=True, check=True).stdout
    return next(line.split(":", 1)[1].strip() for line in output.splitlines() if line.startswith("host:"))


def collect(target: str, *, manifest: Path = MANIFEST, cargo: str = "cargo") -> list[Crate]:
    """Third-party crates linked into the binary for ``target``: normal
    dependencies only, excluding build scripts' and tests' dependencies."""

    metadata = json.loads(
        subprocess.run(
            [cargo, "metadata", "--format-version", "1", "--locked", "--manifest-path", str(manifest), "--filter-platform", target],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    packages = {package["id"]: package for package in metadata["packages"]}
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    root = metadata["resolve"]["root"]
    linked: set[str] = set()
    pending = [root]
    while pending:
        package_id = pending.pop()
        if package_id in linked:
            continue
        linked.add(package_id)
        for dependency in nodes[package_id]["deps"]:
            if any(kind["kind"] is None for kind in dependency["dep_kinds"]):
                pending.append(dependency["pkg"])
    crates = []
    for package_id in linked - {root}:
        package = packages[package_id]
        directory = Path(package["manifest_path"]).parent
        files = {
            path.name: path.read_text(encoding="utf-8", errors="replace")
            for path in sorted(directory.iterdir())
            if path.is_file() and path.name.lower().startswith(_LICENSE_PREFIXES)
        }
        crates.append(
            Crate(
                name=package["name"],
                version=package["version"],
                license=package.get("license") or "unspecified",
                repository=package.get("repository") or "",
                license_files=files,
            )
        )
    return sorted(crates, key=lambda crate: (crate.name, crate.version))


def render(crates: list[Crate], target: str) -> str:
    lines = [
        "Third-party licenses for the Magneto2D executable",
        "",
        f"The Magneto2D executable in this package was built for {target}. It",
        "statically links the Rust crates below, resolved from",
        "solvers/magneto2d/Cargo.lock. Each crate's license files follow, with",
        "identical texts printed once. Magneto2D itself is licensed under",
        "AGPL-3.0-or-later; see LICENSE.",
        "",
        "Crates",
        "------",
    ]
    lines += [f"{crate.name} {crate.version}: {crate.license}" + (f" ({crate.repository})" if crate.repository else "") for crate in crates]

    texts: dict[str, tuple[str, list[str]]] = {}
    for crate in crates:
        for name, text in crate.license_files.items():
            digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
            texts.setdefault(digest, (text.strip(), []))[1].append(f"{crate.name} {crate.version} ({name})")
    lines += ["", "License texts", "-------------"]
    for text, users in texts.values():
        lines += ["", "=" * 78, "Used by: " + ", ".join(users), "=" * 78, "", text]

    missing = [crate for crate in crates if not crate.license_files]
    if missing:
        lines += [
            "",
            "Crates without license files",
            "----------------------------",
            "These crates declare the license shown in their package metadata but",
            "distribute no license file; see each repository for its notice.",
            "",
        ]
        lines += [f"{crate.name} {crate.version}: {crate.license}" + (f" ({crate.repository})" if crate.repository else "") for crate in missing]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", help="Rust target triple (default: the host)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    target = args.target or host_target()
    crates = collect(target)
    args.output.write_text(render(crates, target), encoding="utf-8")
    without = sum(not crate.license_files for crate in crates)
    print(f"{len(crates)} crates, {without} without license files -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
