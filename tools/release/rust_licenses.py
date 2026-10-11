"""Collect the license files of the Rust crates compiled into Magneto2D.

A wheel ships the compiled Magneto2D executable, which statically links its
crate dependencies, so the wheel must carry those crates' license notices.
This resolves the normal (linked) dependency graph for one target from
Cargo.lock and writes every license file the crates distribute, with identical
texts printed once. Some crates publish packages without their own license
file; their upstream LICENSE files are kept in ``crate_notices/``. A linked
crate with neither fails the build. Standard library only: setup.py loads it
by path.

    python -m tools.release.rust_licenses --target x86_64-unknown-linux-gnu --output FILE
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "solvers" / "magneto2d" / "Cargo.toml"
CRATE_NOTICES = Path(__file__).resolve().parent / "crate_notices"
_LICENSE_PREFIXES = ("license", "licence", "copying", "copyright", "notice", "unlicense")
# A crate's own license; COPYING.<component> files are incorporated notices.
_OWN_LICENSE_PREFIXES = ("license", "licence", "unlicense", "copyright")
_OWN_LICENSE_NAMES = frozenset({"copying", "copying.txt", "copying.md"})
_EQUATOR = ("equator.LICENSE", "https://github.com/sarah-ek/equator/blob/572df6071c33cd4ce3298b8ba851774b0645b8a5/LICENSE")
_FAER = ("faer.LICENSE", "https://codeberg.org/sarah-quinones/faer/src/tag/faer-v0.24.1/LICENSE")
_NANO_GEMM = ("nano-gemm.LICENSE", "https://github.com/sarah-ek/nano-gemm/blob/nano-gemm-v0.2.2/LICENSE")
# Crates whose published packages omit their own license file: the upstream
# LICENSE kept in crate_notices/ and where it was taken from.
UPSTREAM_NOTICES: dict[str, tuple[str, str]] = {
    "equator": _EQUATOR,
    "equator-macro": _EQUATOR,
    "faer": _FAER,
    "faer-traits": _FAER,
    "nano-gemm": _NANO_GEMM,
    "nano-gemm-c32": _NANO_GEMM,
    "nano-gemm-c64": _NANO_GEMM,
    "nano-gemm-core": _NANO_GEMM,
    "nano-gemm-f32": _NANO_GEMM,
    "nano-gemm-f64": _NANO_GEMM,
    "pulp-wasm-simd-flag": ("pulp.LICENSE", "https://github.com/sarah-quinones/pulp/blob/pulp-wasm-simd-flag-v0.1.0/LICENSE"),
}


class RustLicenseError(Exception):
    pass


@dataclass
class Crate:
    name: str
    version: str
    license: str
    repository: str
    license_files: dict[str, str] = field(default_factory=dict)


def has_own_license(crate: Crate) -> bool:
    return any(name.lower().startswith(_OWN_LICENSE_PREFIXES) or name.lower() in _OWN_LICENSE_NAMES for name in crate.license_files)


def add_upstream_notice(crate: Crate) -> bool:
    """Give a crate without its own license file the recorded upstream notice."""

    if has_own_license(crate):
        return True
    notice = UPSTREAM_NOTICES.get(crate.name)
    if notice is None:
        return False
    filename, source = notice
    crate.license_files[f"LICENSE from {source}"] = (CRATE_NOTICES / filename).read_text(encoding="utf-8")
    return True


def host_target(rustc: str = "rustc") -> str:
    output = subprocess.run([rustc, "-vV"], capture_output=True, text=True, check=True).stdout
    return next(line.split(":", 1)[1].strip() for line in output.splitlines() if line.startswith("host:"))


def collect(target: str, *, manifest: Path = MANIFEST, cargo: str = "cargo") -> list[Crate]:
    """Third-party crates linked into the binary for ``target``: normal
    dependencies only, excluding build scripts' and tests' dependencies.
    Raises RustLicenseError when a crate has no license notice."""

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
    unresolved = sorted(f"{crate.name} {crate.version}" for crate in crates if not add_upstream_notice(crate))
    if unresolved:
        raise RustLicenseError(
            "these linked crates ship no license file of their own: "
            + ", ".join(unresolved)
            + ". Add their upstream LICENSE to tools/release/crate_notices/ and UPSTREAM_NOTICES."
        )
    return sorted(crates, key=lambda crate: (crate.name, crate.version))


def render(crates: list[Crate], target: str) -> str:
    lines = [
        "Third-party licenses for the Magneto2D executable",
        "",
        f"The Magneto2D executable in this package was built for {target}. It",
        "statically links the Rust crates below, resolved from",
        "solvers/magneto2d/Cargo.lock. Each crate's license files follow, with",
        "identical texts printed once. For crates published without their own",
        "license file, the upstream LICENSE is included with its source.",
        "Magneto2D itself is licensed under AGPL-3.0-or-later; see LICENSE.",
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

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", help="Rust target triple (default: the host)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    target = args.target or host_target()
    try:
        crates = collect(target)
    except RustLicenseError as exc:
        print(f"rust licenses: {exc}", file=sys.stderr)
        return 1
    args.output.write_text(render(crates, target), encoding="utf-8")
    print(f"{len(crates)} crates -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
