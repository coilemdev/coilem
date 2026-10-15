"""Build hooks that make an installed coilEM independent of the source checkout.

A wheel build (``pip install .`` or ``python -m build --wheel``) copies into the
``backend`` package everything the runtime reads: the repository data files
(including the benchmark suite, reference and records ``coilem benchmark``
reads), the production UI bundle, the Magneto2D release binary and a stamped
build identity. Packaged data files must match ``snapshot-manifest.json``. Editable
installs skip all of this and read from the checkout.

Building the UI needs Node.js and npm, and building the solver needs Cargo.
Release builds package prebuilt artifacts from ``tools/release/artifacts.py``
instead: ``COILEM_BUILD_UI_DIST`` and ``COILEM_BUILD_MAGNETO2D_BINARY`` point at
them, and their ``.build.json`` sidecars supply toolchain records.
``COILEM_WHEEL_PLATFORM_TAG`` sets the wheel's platform tag from the release
policy, and ``COILEM_VERSION_SUFFIX=.devN`` makes a TestPyPI rehearsal version.
Other project metadata lives in pyproject.toml.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load(name: str, relative: str):
    # Standard-library modules loaded by path, without importing the backend
    # package or the tools package and their dependencies.
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up while it executes
    spec.loader.exec_module(module)
    return module


resources = _load("_coilem_build_resources", "backend/resources.py")
physics = _load("_coilem_build_physics", "backend/benchmark_suite/physics.py")
rust_licenses = _load("_coilem_build_rust_licenses", "tools/release/rust_licenses.py")
release_version = _load("_coilem_build_release_version", "tools/release/version.py")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _version(*command: str) -> str:
    return subprocess.run(list(command), capture_output=True, text=True, check=True).stdout.strip().splitlines()[0]


def _sidecar(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"coilEM build: {path.name} is missing next to the prebuilt artifact.")
    return json.loads(path.read_text(encoding="utf-8"))


def _check_packaged_sources() -> None:
    _require_checkout(ROOT / "snapshot-manifest.json", "nothing: data files are always checked")
    manifest = json.loads((ROOT / "snapshot-manifest.json").read_text(encoding="utf-8"))
    recorded = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    for relative in (*resources.PACKAGED_DATA_FILES, *resources.PACKAGE_DATA_FILES, *resources.benchmark_data_files(ROOT)):
        if _sha256(ROOT / relative) != recorded.get(relative):
            raise SystemExit(f"coilEM build: {relative} differs from its snapshot-manifest.json entry.")


def _ui_bundle() -> tuple[Path, dict[str, str]]:
    """The UI bundle to package and the toolchain that built it."""

    prebuilt = os.environ.get("COILEM_BUILD_UI_DIST")
    if prebuilt:
        bundle = Path(prebuilt).expanduser().resolve()
        if not (bundle / "index.html").is_file():
            raise SystemExit("coilEM build: COILEM_BUILD_UI_DIST has no index.html.")
        return bundle, _sidecar(bundle.parent / f"{bundle.name}.build.json")["toolchain"]
    frontend = ROOT / "frontend"
    _require_checkout(frontend / "package.json", "COILEM_BUILD_UI_DIST")
    npm = _tool("npm")
    if not (frontend / "node_modules").is_dir():
        _run([npm, "ci"], frontend)
    _run([npm, "run", "build"], frontend)
    return ROOT / resources.SOURCE_UI_DIR, {"node": _version(_tool("node"), "--version"), "npm": _version(npm, "--version")}


def _magneto2d_binary() -> tuple[Path, dict, str]:
    """The binary to package, its build record and the license file of its crates."""

    prebuilt = os.environ.get("COILEM_BUILD_MAGNETO2D_BINARY")
    if prebuilt:
        binary = Path(prebuilt).expanduser().resolve()
        if not binary.is_file():
            raise SystemExit("coilEM build: COILEM_BUILD_MAGNETO2D_BINARY is not a file.")
        licenses = binary.parent / f"{binary.stem}.licenses.txt"
        if not licenses.is_file():
            raise SystemExit(f"coilEM build: {licenses.name} is missing next to the prebuilt binary.")
        return binary, _sidecar(binary.parent / f"{binary.stem}.build.json"), licenses.read_text(encoding="utf-8")
    crate = ROOT / "solvers" / "magneto2d"
    _require_checkout(crate / "Cargo.toml", "COILEM_BUILD_MAGNETO2D_BINARY")
    cargo = os.environ.get("CARGO") or _tool("cargo", Path.home() / ".cargo" / "bin" / "cargo")
    _run([cargo, "build", "--release", "--locked", "--manifest-path", str(crate / "Cargo.toml")], ROOT)
    rustc = _tool("rustc", Path(cargo).with_name("rustc"))
    target = rust_licenses.host_target(rustc)
    record = {
        "magneto2d_version": re.search(r'^version\s*=\s*"([^"]+)"', (crate / "Cargo.toml").read_text(encoding="utf-8"), re.MULTILINE)[1],
        "target": target,
        "toolchain": {"rustc": _version(rustc, "-V"), "cargo": _version(cargo, "-V")},
    }
    try:
        crates = rust_licenses.collect(target, manifest=crate / "Cargo.toml", cargo=cargo)
    except rust_licenses.RustLicenseError as exc:
        raise SystemExit(f"coilEM build: {exc}") from exc
    licenses = rust_licenses.render(crates, target)
    name = "magneto2d.exe" if os.name == "nt" else "magneto2d"
    return crate / "target" / "release" / name, record, licenses


def _stamp_package_version(package: Path, version: str) -> None:
    """Give launcher and health checks the distribution version, including .devN."""

    initializer = package / "__init__.py"
    source, count = re.subn(
        r'^__version__ = "[^"]+"$',
        f"__version__ = {json.dumps(version)}",
        initializer.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit("coilEM build: backend/__init__.py must define exactly one __version__.")
    initializer.write_text(source, encoding="utf-8", newline="\n")


def stage_runtime_files(package: Path, version: str) -> None:
    """Copy data, UI, solver and build identity into a built ``backend`` package."""

    _check_packaged_sources()
    _stamp_package_version(package, version)
    data = package / resources.PACKAGED_DATA_DIR
    shutil.rmtree(data, ignore_errors=True)
    for relative in (*resources.PACKAGED_DATA_FILES, *resources.benchmark_data_files(ROOT)):
        target = data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)

    bundle, ui_toolchain = _ui_bundle()
    ui = package / resources.PACKAGED_UI_DIR
    shutil.rmtree(ui, ignore_errors=True)
    shutil.copytree(bundle, ui)

    binary, binary_record, crate_licenses = _magneto2d_binary()
    bin_dir = package / resources.PACKAGED_BIN_DIR
    shutil.rmtree(bin_dir, ignore_errors=True)
    bin_dir.mkdir(parents=True)
    packaged_binary = bin_dir / ("magneto2d.exe" if os.name == "nt" else "magneto2d")
    shutil.copyfile(binary, packaged_binary)
    packaged_binary.chmod(0o755)
    licenses = package / resources.PACKAGED_LICENSES_DIR
    shutil.rmtree(licenses, ignore_errors=True)
    licenses.mkdir(parents=True)
    (licenses / resources.MAGNETO2D_LICENSES_FILE).write_text(crate_licenses, encoding="utf-8")

    build_info = {
        "application_version": version,
        "application_commit": os.environ.get("COILEM_BUILD_COMMIT", "").strip()
        or resources.source_checkout_commit(ROOT),
        "magneto2d_version": binary_record["magneto2d_version"],
        "magneto2d_target": binary_record["target"],
        "magneto2d_sha256": _sha256(packaged_binary),
        "ui_bundle_sha256": resources.directory_sha256(ui),
        "toolchain": {**binary_record["toolchain"], **ui_toolchain},
        # The wheel carries the binary, not its Rust sources: `coilem benchmark`
        # matches records by these hashes (#71).
        physics.BUILD_INFO_KEY: physics.solver_source_hashes(ROOT),
    }
    (package / resources.BUILD_INFO_FILE).write_text(json.dumps(build_info, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    # setuptools is imported here so tests can load the staging helpers above
    # without it; builds get a current setuptools from pyproject.toml.
    from setuptools import Distribution, setup
    from setuptools.command.bdist_wheel import bdist_wheel
    from setuptools.command.build_py import build_py

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
            return "py3", "none", os.environ.get("COILEM_WHEEL_PLATFORM_TAG") or super().get_tag()[2]

    try:
        version = release_version.package_version()
    except release_version.VersionError as exc:
        raise SystemExit(f"coilEM build: {exc}") from exc
    setup(
        version=version,
        distclass=BinaryDistribution,
        cmdclass={"build_py": BuildPyWithRuntimeFiles, "bdist_wheel": PlatformWheel},
    )


# setuptools' PEP 517 backend runs this file as __main__.
if __name__ == "__main__":
    main()
