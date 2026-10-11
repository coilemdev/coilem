"""Build the release Magneto2D binary and UI bundle that wheels package.

Each artifact goes into an output directory with a ``.build.json`` sidecar
recording the toolchain and hashes; the binary also gets the license file of
the crates it links. ``setup.py`` packages them when ``COILEM_BUILD_UI_DIST``
and ``COILEM_BUILD_MAGNETO2D_BINARY`` point here.

The binary build enforces the compatibility policy: a locked release build for
an explicit target, the declared macOS deployment target, a statically linked
C runtime on Windows, and no CPU-specific code generation.

    python -m tools.release.artifacts magneto2d --target TRIPLE --out DIR [--macos-deployment-target 12.0]
    python -m tools.release.artifacts ui --out DIR
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from tools.release import rust_licenses

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "solvers" / "magneto2d"
FRONTEND = ROOT / "frontend"
_RUSTFLAG_VARIABLES = ("RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS")
WINDOWS_CRT_STATIC = "-C target-feature=+crt-static"


class ArtifactError(Exception):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(root: Path) -> str:
    """Hash of every file's relative path and content; matches setup.py."""

    lines = (f"{path.relative_to(root).as_posix()} {sha256(path)}\n" for path in sorted(root.rglob("*")) if path.is_file())
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def tool_version(*command: str) -> str:
    return subprocess.run(list(command), capture_output=True, text=True, check=True).stdout.strip().splitlines()[0]


def crate_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', (CRATE / "Cargo.toml").read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise ArtifactError("solvers/magneto2d/Cargo.toml has no package version")
    return match[1]


def release_environment(target: str, environ: dict[str, str], macos_deployment_target: str | None) -> dict[str, str]:
    """The build environment for ``target``, refusing CPU-specific settings."""

    if environ.get("COILEM_MAGNETO2D_BUILD_RUSTFLAGS"):
        raise ArtifactError("unset COILEM_MAGNETO2D_BUILD_RUSTFLAGS for release builds")
    for name in _RUSTFLAG_VARIABLES:
        if environ.get(name):
            raise ArtifactError(f"unset {name}: release builds use generic code generation")
    environment = dict(environ)
    if "apple-darwin" in target:
        if not macos_deployment_target:
            raise ArtifactError("macOS builds need --macos-deployment-target from the release policy")
        environment["MACOSX_DEPLOYMENT_TARGET"] = macos_deployment_target
    elif macos_deployment_target:
        raise ArtifactError("--macos-deployment-target applies only to macOS targets")
    if target.endswith("windows-msvc"):
        environment["RUSTFLAGS"] = WINDOWS_CRT_STATIC
    return environment


def build_magneto2d(target: str, out: Path, macos_deployment_target: str | None) -> Path:
    environment = release_environment(target, dict(os.environ), macos_deployment_target)
    cargo = environment.get("CARGO", "cargo")
    command = [cargo, "build", "--release", "--locked", "--manifest-path", str(CRATE / "Cargo.toml"), "--target", target]
    print("release build:", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    name = "magneto2d.exe" if "windows" in target else "magneto2d"
    out.mkdir(parents=True, exist_ok=True)
    binary = out / name
    shutil.copyfile(CRATE / "target" / target / "release" / name, binary)
    binary.chmod(0o755)
    (out / "magneto2d.licenses.txt").write_text(
        rust_licenses.render(rust_licenses.collect(target, cargo=cargo), target), encoding="utf-8"
    )
    sidecar = {
        "magneto2d_version": crate_version(),
        "target": target,
        "sha256": sha256(binary),
        "rustflags": environment.get("RUSTFLAGS", ""),
        "macosx_deployment_target": environment.get("MACOSX_DEPLOYMENT_TARGET"),
        "toolchain": {"rustc": tool_version("rustc", "-V"), "cargo": tool_version(cargo, "-V")},
    }
    (out / "magneto2d.build.json").write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return binary


def build_ui(out: Path) -> Path:
    npm = shutil.which("npm")
    if npm is None:
        raise ArtifactError("npm was not found on PATH")
    for arguments in (["ci"], ["run", "build"]):
        subprocess.run([npm, *arguments], cwd=FRONTEND, check=True)
    bundle = out / "ui"
    shutil.rmtree(bundle, ignore_errors=True)
    shutil.copytree(ROOT / "frontend" / "dist-public-boundary", bundle)
    sidecar = {
        "sha256": tree_sha256(bundle),
        "toolchain": {"node": tool_version("node", "--version"), "npm": tool_version(npm, "--version")},
    }
    (out / "ui.build.json").write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="artifact", required=True)
    magneto2d = commands.add_parser("magneto2d")
    magneto2d.add_argument("--target", required=True)
    magneto2d.add_argument("--out", type=Path, required=True)
    magneto2d.add_argument("--macos-deployment-target")
    ui = commands.add_parser("ui")
    ui.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.artifact == "magneto2d":
            print(build_magneto2d(args.target, args.out, args.macos_deployment_target))
        else:
            print(build_ui(args.out))
    except ArtifactError as exc:
        print(f"release artifact: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
