"""Build hooks that make an installed coilEM independent of the source checkout.

A wheel build (``pip install .`` or ``python -m build --wheel``) copies into the
``backend`` package everything the runtime reads: the repository data files,
the production UI bundle, the Magneto2D release binary and a stamped build
identity. Packaged data files must match ``snapshot-manifest.json``. Editable
installs skip all of this and read from the checkout.

Building the UI needs Node.js and npm, and building the solver needs Cargo.
Set ``COILEM_BUILD_UI_DIST`` or ``COILEM_BUILD_MAGNETO2D_BINARY`` to package a
prebuilt bundle or binary instead. Project metadata lives in pyproject.toml.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

from setuptools import Distribution, setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent


def _load_resources():
    # Shares the packaged-file layout with the runtime without importing the
    # backend package and its dependencies.
    spec = importlib.util.spec_from_file_location("_coilem_build_resources", ROOT / "backend" / "resources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resources = _load_resources()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(root: Path) -> str:
    lines = (
        f"{path.relative_to(root).as_posix()} {_sha256(path)}\n"
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _require_checkout(path: Path, override: str) -> None:
    if not path.exists():
        raise SystemExit(
            f"coilEM build: {path.relative_to(ROOT).as_posix()} is missing. Build the wheel from a "
            f"source checkout (`pip install .`), or set {override}."
        )


def _tool(name: str, *fallbacks: Path) -> str:
    found = shutil.which(name)
    if found:
        return found
    for candidate in fallbacks:
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(f"coilEM build: `{name}` was not found on PATH.")


def _run(command: list[str], cwd: Path) -> None:
    print(f"coilEM build: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _check_packaged_sources() -> None:
    _require_checkout(ROOT / "snapshot-manifest.json", "nothing: data files are always checked")
    manifest = json.loads((ROOT / "snapshot-manifest.json").read_text(encoding="utf-8"))
    recorded = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    for relative in (*resources.PACKAGED_DATA_FILES, *resources.PACKAGE_DATA_FILES):
        if _sha256(ROOT / relative) != recorded.get(relative):
            raise SystemExit(f"coilEM build: {relative} differs from its snapshot-manifest.json entry.")


def _ui_bundle() -> Path:
    prebuilt = os.environ.get("COILEM_BUILD_UI_DIST")
    if prebuilt:
        bundle = Path(prebuilt).expanduser().resolve()
        if not (bundle / "index.html").is_file():
            raise SystemExit("coilEM build: COILEM_BUILD_UI_DIST has no index.html.")
        return bundle
    frontend = ROOT / "frontend"
    _require_checkout(frontend / "package.json", "COILEM_BUILD_UI_DIST")
    npm = _tool("npm")
    if not (frontend / "node_modules").is_dir():
        _run([npm, "ci"], frontend)
    _run([npm, "run", "build"], frontend)
    return ROOT / resources.SOURCE_UI_DIR


def _magneto2d_binary() -> Path:
    prebuilt = os.environ.get("COILEM_BUILD_MAGNETO2D_BINARY")
    if prebuilt:
        binary = Path(prebuilt).expanduser().resolve()
        if not binary.is_file():
            raise SystemExit("coilEM build: COILEM_BUILD_MAGNETO2D_BINARY is not a file.")
        return binary
    crate = ROOT / "solvers" / "magneto2d"
    _require_checkout(crate / "Cargo.toml", "COILEM_BUILD_MAGNETO2D_BINARY")
    cargo = os.environ.get("CARGO") or _tool("cargo", Path.home() / ".cargo" / "bin" / "cargo")
    _run([cargo, "build", "--release", "--locked", "--manifest-path", str(crate / "Cargo.toml")], ROOT)
    name = "magneto2d.exe" if os.name == "nt" else "magneto2d"
    return crate / "target" / "release" / name


def stage_runtime_files(package: Path, version: str) -> None:
    """Copy data, UI, solver and build identity into a built ``backend`` package."""

    _check_packaged_sources()
    data = package / resources.PACKAGED_DATA_DIR
    shutil.rmtree(data, ignore_errors=True)
    for relative in resources.PACKAGED_DATA_FILES:
        target = data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)

    bundle = _ui_bundle()
    ui = package / resources.PACKAGED_UI_DIR
    shutil.rmtree(ui, ignore_errors=True)
    shutil.copytree(bundle, ui)

    binary = _magneto2d_binary()
    bin_dir = package / resources.PACKAGED_BIN_DIR
    shutil.rmtree(bin_dir, ignore_errors=True)
    bin_dir.mkdir(parents=True)
    packaged_binary = bin_dir / ("magneto2d.exe" if os.name == "nt" else "magneto2d")
    shutil.copyfile(binary, packaged_binary)
    packaged_binary.chmod(0o755)

    build_info = {
        "application_version": version,
        "application_commit": os.environ.get("COILEM_BUILD_COMMIT", "").strip()
        or resources.source_checkout_commit(ROOT),
        "magneto2d_sha256": _sha256(packaged_binary),
        "ui_bundle_sha256": _tree_sha256(ui),
    }
    (package / resources.BUILD_INFO_FILE).write_text(json.dumps(build_info, indent=2) + "\n", encoding="utf-8")


class BuildPyWithRuntimeFiles(build_py):
    def run(self) -> None:
        super().run()
        if not self.editable_mode:
            stage_runtime_files(Path(self.build_lib) / "backend", self.distribution.get_version())


class BinaryDistribution(Distribution):
    """Wheels carry the Magneto2D executable, so they are platform specific."""

    def has_ext_modules(self) -> bool:
        return True


class PlatformWheel(bdist_wheel):
    def get_tag(self) -> tuple[str, str, str]:
        # The binary is a standalone executable, so one wheel per platform
        # serves every supported Python version.
        return "py3", "none", super().get_tag()[2]


# setuptools' PEP 517 backend runs this file as __main__; tests import it.
if __name__ == "__main__":
    setup(
        distclass=BinaryDistribution,
        cmdclass={"build_py": BuildPyWithRuntimeFiles, "bdist_wheel": PlatformWheel},
    )
