"""Release tooling: compatibility policy, wheel checks, native dependencies and inputs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import tomllib
from packaging.specifiers import SpecifierSet
from packaging.tags import Tag

from backend import __version__, resources
from tools.release import artifacts, native_deps, policy, rust_licenses, verify_wheel, version

REPO_ROOT = Path(__file__).resolve().parents[1]
GMSH = [
    "gmsh-4.15.2-py2.py3-none-macosx_10_15_x86_64.whl",
    "gmsh-4.15.2-py2.py3-none-macosx_12_0_arm64.whl",
    "gmsh-4.15.2-py2.py3-none-manylinux_2_24_x86_64.whl",
    "gmsh-4.15.2-py2.py3-none-win_amd64.whl",
]
NUMPY = [
    f"numpy-2.4.6-cp{minor}-cp{minor}-{platform}.whl"
    for minor in ("311", "312", "313", "314")
    for platform in (
        "macosx_11_0_arm64",
        "macosx_14_0_arm64",
        "macosx_10_13_x86_64",
        "manylinux_2_27_x86_64.manylinux_2_28_x86_64",
        "musllinux_1_2_x86_64",
        "win_amd64",
    )
]
# NumPy 2.5 has no Python 3.11 wheels, so the lock pins it for Python 3.15 only.
NUMPY_25 = [
    f"numpy-2.5.4-cp{minor}-cp{minor}-{platform}.whl"
    for minor in ("312", "313", "314", "315")
    for platform in (
        "macosx_11_0_arm64",
        "macosx_14_0_arm64",
        "macosx_10_15_x86_64",
        "manylinux_2_27_x86_64.manylinux_2_28_x86_64",
        "musllinux_1_2_x86_64",
        "win_amd64",
    )
]
SPLIT_NUMPY = [
    policy.Requirement('numpy==2.4.6; python_version < "3.15"'),
    policy.Requirement('numpy==2.5.4; python_version >= "3.15"'),
]


def fake_index(files: dict[str, list[str]]):
    """Wheel files by ``name``, or by ``name==version`` for a package pinned twice."""
    return lambda name, version: files.get(f"{name}=={version}", files.get(name))


def test_python_and_platform_tag_rules() -> None:
    assert policy.python_compatible(Tag("py3", "none", "any"), "3.12")
    assert policy.python_compatible(Tag("cp312", "cp312", "win_amd64"), "3.12")
    assert not policy.python_compatible(Tag("cp312", "cp312", "win_amd64"), "3.13")
    assert not policy.python_compatible(Tag("cp313", "cp313t", "win_amd64"), "3.13")
    assert policy.python_compatible(Tag("cp39", "abi3", "win_amd64"), "3.13")
    assert not policy.python_compatible(Tag("pp310", "pypy310_pp73", "win_amd64"), "3.10")
    macos_arm, _, linux, windows = policy.TARGETS
    assert policy.platform_floor(Tag("py3", "none", "macosx_11_0_universal2"), macos_arm) == (11, 0)
    assert policy.platform_floor(Tag("py3", "none", "macosx_10_15_x86_64"), macos_arm) is False
    assert policy.platform_floor(Tag("py3", "none", "manylinux2014_x86_64"), linux) == (2, 17)
    assert policy.platform_floor(Tag("py3", "none", "musllinux_1_2_x86_64"), linux) is False
    assert policy.platform_floor(Tag("py3", "none", "win_amd64"), windows) is None


def test_floor_is_the_highest_minimum_across_pins() -> None:
    requirements = [
        policy.Requirement("gmsh==4.15.2"),
        *SPLIT_NUMPY,
        policy.Requirement("idna==3.18"),
        policy.Requirement('colorama==0.4.6; platform_system == "Windows"'),
    ]
    index = {
        "gmsh": GMSH,
        "numpy==2.4.6": NUMPY,
        "numpy==2.5.4": NUMPY_25,
        "idna": ["idna-3.18-py3-none-any.whl"],
        "colorama": ["colorama-0.4.6-py2.py3-none-any.whl"],
    }
    result = policy.compute_policy(requirements, fake_index(index))
    assert result["macos-arm64"]["platform_tag"] == "macosx_12_0_arm64"
    assert result["macos-arm64"]["limited_by"] == ["gmsh"]
    assert result["macos-x86_64"]["macosx_deployment_target"] == "10.15"
    assert result["linux-x86_64"]["platform_tag"] == "manylinux_2_27_x86_64"
    assert result["linux-x86_64"]["limited_by"] == ["numpy"]
    # The binary is built in the newest image that does not exceed the floor.
    assert result["linux-x86_64"]["build_image"] == "quay.io/pypa/manylinux2014_x86_64"
    assert result["windows-amd64"]["platform_tag"] == "win_amd64"


def test_rust_minimum_applies_without_binary_pins() -> None:
    result = policy.compute_policy([policy.Requirement("idna==3.18")], fake_index({"idna": ["idna-3.18-py3-none-any.whl"]}))
    assert result["macos-arm64"]["platform_tag"] == "macosx_11_0_arm64"
    assert result["linux-x86_64"]["platform_tag"] == "manylinux_2_17_x86_64"


def test_missing_wheel_for_a_supported_python_fails() -> None:
    only_old = [name for name in NUMPY if "cp314" not in name]
    with pytest.raises(policy.PolicyError, match="numpy==2.4.6: no wheel for macos-arm64 on Python 3.14"):
        policy.compute_policy([policy.Requirement("numpy==2.4.6")], fake_index({"numpy": only_old}))


def test_split_pins_must_cover_every_python_once() -> None:
    policy.check_markers(SPLIT_NUMPY)
    policy.check_markers(policy.read_lock(REPO_ROOT / "requirements.lock"))
    gap = [policy.Requirement('numpy==2.4.6; python_version < "3.14"'), SPLIT_NUMPY[1]]
    with pytest.raises(policy.PolicyError, match="numpy has 0 pins for macos-arm64 on Python 3.14"):
        policy.check_markers(gap)
    overlap = [policy.Requirement('numpy==2.4.6; python_version <= "3.15"'), SPLIT_NUMPY[1]]
    with pytest.raises(policy.PolicyError, match="numpy has 2 pins for macos-arm64 on Python 3.15"):
        policy.compute_policy(overlap, fake_index({"numpy==2.4.6": NUMPY, "numpy==2.5.4": NUMPY_25}))
    # A platform marker may still limit a package to some targets.
    policy.check_markers([policy.Requirement('colorama==0.4.6; platform_system == "Windows"')])


def test_audit_pins_list_each_pythons_exact_pins(tmp_path: Path) -> None:
    lock = policy.read_lock(REPO_ROOT / "requirements.lock")
    oldest, newest = policy.audit_pins(lock, "3.11"), policy.audit_pins(lock, "3.15")
    assert "numpy==2.4.6" in oldest and "numpy==2.5.4" not in oldest
    assert "numpy==2.5.4" in newest and "numpy==2.4.6" not in newest
    # pip-audit skips pins whose markers do not match its interpreter, so the
    # audit lists carry none, and include the Windows-only pin everywhere.
    assert "colorama==0.4.6" in oldest and not any(";" in pin for pin in oldest + newest)
    assert len({pin.split("==")[0] for pin in newest}) == len(newest)
    assert policy.main(["--audit-pins", str(tmp_path)]) == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == [f"pins-{python}.txt" for python in policy.SUPPORTED_PYTHONS]
    assert (tmp_path / "pins-3.15.txt").read_text(encoding="utf-8").splitlines() == newest


def test_lock_must_hold_exact_pins(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text("# comment\nnumpy==2.4.6\nfastapi>=0.1\n")
    with pytest.raises(policy.PolicyError, match="exact pins"):
        policy.read_lock(lock)
    assert [str(item) for item in policy.read_lock(REPO_ROOT / "requirements.lock")][0].startswith("annotated-doc==")


def test_requires_python_covers_exactly_the_supported_versions() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    specifier = SpecifierSet(project["requires-python"])
    assert all(version in specifier for version in policy.SUPPORTED_PYTHONS)
    major, minor = policy.SUPPORTED_PYTHONS[-1].split(".")
    assert f"{major}.{int(minor) + 1}" not in specifier
    assert f"{major}.{int(policy.SUPPORTED_PYTHONS[0].split('.')[1]) - 1}" not in specifier
    assert project["dynamic"] == ["version", "dependencies"]
    assert tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["dynamic"]["dependencies"] == {
        "file": ["requirements.lock"]
    }


def test_release_build_refuses_cpu_specific_or_ad_hoc_flags() -> None:
    with pytest.raises(artifacts.ArtifactError, match="COILEM_MAGNETO2D_BUILD_RUSTFLAGS"):
        artifacts.release_environment("x86_64-unknown-linux-gnu", {"COILEM_MAGNETO2D_BUILD_RUSTFLAGS": "-C target-cpu=native"}, None)
    with pytest.raises(artifacts.ArtifactError, match="RUSTFLAGS"):
        artifacts.release_environment("x86_64-unknown-linux-gnu", {"RUSTFLAGS": "-C target-cpu=native"}, None)
    with pytest.raises(artifacts.ArtifactError, match="deployment-target"):
        artifacts.release_environment("aarch64-apple-darwin", {}, None)
    assert artifacts.release_environment("aarch64-apple-darwin", {}, "12.0")["MACOSX_DEPLOYMENT_TARGET"] == "12.0"
    windows = artifacts.release_environment("x86_64-pc-windows-msvc", {}, None)
    assert windows["RUSTFLAGS"] == "-C target-feature=+crt-static"
    assert "RUSTFLAGS" not in artifacts.release_environment("x86_64-unknown-linux-gnu", {}, None)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_crate_license_report_dedupes_texts(newline: str) -> None:
    mit = "MIT License\n\nCopyright (c) Example"
    crates = [
        rust_licenses.Crate("alpha", "1.0.0", "MIT OR Apache-2.0", "https://example.com/alpha", {"LICENSE-MIT": mit, "LICENSE-APACHE": "Apache"}),
        rust_licenses.Crate("beta", "2.0.0", "MIT OR Apache-2.0", "", {"LICENSE-APACHE": "Apache"}),
    ]
    text = rust_licenses.render(crates, "x86_64-unknown-linux-gnu")
    assert "built for x86_64-unknown-linux-gnu" in text
    assert text.count("\nApache\n") == 1
    assert "Used by: alpha 1.0.0 (LICENSE-APACHE), beta 2.0.0 (LICENSE-APACHE)" in text
    assert verify_wheel.crates_without_license_text(text.replace("\n", newline)) == []
    uncovered = text.replace("Used by: alpha 1.0.0 (LICENSE-APACHE), beta 2.0.0 (LICENSE-APACHE)", "Used by: alpha 1.0.0 (LICENSE-APACHE)")
    assert verify_wheel.crates_without_license_text(uncovered.replace("\n", newline)) == ["beta 2.0.0"]


@pytest.mark.parametrize("report", [
    "Used by: faer 0.24.0 (LICENSE)\n",
    "Header\n\nCrates\n",
    "Header\n\nCrates\n-----\nfaer 0.24.0: MIT\n",
    "Header\n\nCrates\n------\n\nLicense texts\n-------------\n",
    "Header\n\nCrates\n------\nnot a crate entry\n",
])
def test_malformed_crate_license_reports_are_rejected(report: str) -> None:
    with pytest.raises(ValueError, match="crate license report"):
        verify_wheel.crates_without_license_text(report)


def test_crates_without_their_own_license_get_the_recorded_upstream_notice() -> None:
    faer = rust_licenses.Crate("faer", "0.24.0", "MIT", "", {"COPYING.SUITE_SPARSE.AMD.BSD": "AMD notice"})
    assert not rust_licenses.has_own_license(faer)
    assert rust_licenses.add_upstream_notice(faer)
    upstream = [name for name in faer.license_files if name.startswith("LICENSE from https://codeberg.org/sarah-quinones/faer/")]
    assert upstream and faer.license_files[upstream[0]].startswith("MIT License")
    assert "COPYING.SUITE_SPARSE.AMD.BSD" in faer.license_files
    shipped = rust_licenses.Crate("memchr", "2.8.0", "Unlicense OR MIT", "", {"COPYING": "x", "UNLICENSE": "y"})
    assert rust_licenses.add_upstream_notice(shipped) and set(shipped.license_files) == {"COPYING", "UNLICENSE"}
    assert not rust_licenses.add_upstream_notice(rust_licenses.Crate("unknown", "1.0.0", "MIT", ""))
    for filename, source in set(rust_licenses.UPSTREAM_NOTICES.values()):
        text = (rust_licenses.CRATE_NOTICES / filename).read_text(encoding="utf-8")
        assert text.startswith("MIT License") and "Copyright (c)" in text, filename
        assert source.startswith("https://") and source.endswith("/LICENSE")


@pytest.mark.parametrize("target", ["x86_64-unknown-linux-gnu", "aarch64-apple-darwin", "x86_64-apple-darwin", "x86_64-pc-windows-msvc"])
def test_every_linked_crate_carries_a_license_text(target: str) -> None:
    # Gmsh can alter the native Windows PATH without updating os.environ.
    cargo = shutil.which("cargo")
    if cargo is None:
        pytest.skip("needs Cargo and the locked crate sources")
    try:
        crates = rust_licenses.collect(target, cargo=cargo)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"cargo metadata is unavailable here: {exc.stderr.strip()[:200]}")
    upstream = [crate for crate in crates if any(name.startswith("LICENSE from ") for name in crate.license_files)]
    noticed = [crate for crate in crates if rust_licenses.has_own_license(crate) or crate in upstream]
    assert crates and noticed == crates
    assert verify_wheel.crates_without_license_text(rust_licenses.render(crates, target)) == []


OTOOL_L = """/tmp/magneto2d:
\t/usr/lib/libiconv.2.dylib (compatibility version 7.0.0, current version 7.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1351.0.0)
"""
OTOOL_LOAD = "Load command 9\n      cmd LC_BUILD_VERSION\n  cmdsize 32\n platform 1\n    minos 12.0\n      sdk 15.5\n"
READELF_D = """
 0x0000000000000001 (NEEDED)             Shared library: [libgcc_s.so.1]
 0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]
"""
OBJDUMP_T = """
0000000000000000      DF *UND*  0000000000000000  GLIBC_2.2.5 memcpy
0000000000000000      DF *UND*  0000000000000000 (GLIBC_2.17) clock_gettime
"""
DUMPBIN = """Dump of file magneto2d.exe

File Type: EXECUTABLE IMAGE

  Image has the following dependencies:

    KERNEL32.dll
    ntdll.dll
    api-ms-win-core-synch-l1-2-0.dll

  Summary

        1000 .data
"""


def test_native_dependency_parsers_and_rules(tmp_path: Path) -> None:
    libraries = native_deps.otool_libraries(OTOOL_L)
    assert libraries == ["/usr/lib/libiconv.2.dylib", "/usr/lib/libSystem.B.dylib"]
    assert native_deps.otool_minimum_os(OTOOL_LOAD) == (12, 0)
    assert native_deps.check_macos(libraries, (12, 0), (12, 0)) == []
    assert native_deps.check_macos([*libraries, "/opt/homebrew/lib/libfoo.dylib"], (13, 0), (12, 0)) == [
        "non-system library: /opt/homebrew/lib/libfoo.dylib",
        "binary needs macOS 13.0, newer than the wheel tag's 12.0",
    ]
    needed = native_deps.readelf_needed(READELF_D)
    assert needed == ["libgcc_s.so.1", "libc.so.6"]
    assert native_deps.glibc_floor(OBJDUMP_T) == (2, 17)
    assert native_deps.check_linux(needed, (2, 17), (2, 27)) == []
    assert native_deps.check_linux([*needed, "libstdc++.so.6"], (2, 28), (2, 27)) == [
        "library outside glibc and libgcc: libstdc++.so.6",
        "binary needs glibc 2.28, newer than the wheel tag's 2.27",
    ]
    dlls = native_deps.dumpbin_dependents(DUMPBIN)
    assert dlls == ["KERNEL32.dll", "ntdll.dll", "api-ms-win-core-synch-l1-2-0.dll"]
    system = tmp_path / "System32"
    system.mkdir()
    for name in ("KERNEL32.dll", "ntdll.dll"):
        (system / name).touch()
    assert native_deps.check_windows(dlls, system) == []
    assert native_deps.check_windows([*dlls, "VCRUNTIME140.dll", "libfoo.dll"], system) == [
        "C runtime DLL; link it statically: VCRUNTIME140.dll",
        "not a system DLL: libfoo.dll",
    ]


def _write_wheel(
    path: Path, *, requires: list[str], binary: bytes = b"binary", stamp_binary: bytes | None = None,
    runtime_version: str = "0.2.0", crate_licenses: str | None = None,
) -> Path:
    dist_info = "coilem-0.2.0.dist-info"
    ui = {"index.html": b"<!doctype html>", "assets/index-AbCd1234.js": b"export {};", "assets/Lesson-AbCd1234.js": b"export {};"}
    ui_hash = hashlib.sha256(
        "".join(f"{name} {hashlib.sha256(data).hexdigest()}\n" for name, data in sorted(ui.items())).encode()
    ).hexdigest()
    build = {
        "application_version": "0.2.0",
        "application_commit": "a" * 40,
        "magneto2d_version": "0.3.2",
        "magneto2d_target": "aarch64-apple-darwin",
        "magneto2d_sha256": hashlib.sha256(stamp_binary or binary).hexdigest(),
        "ui_bundle_sha256": ui_hash,
        "toolchain": {"rustc": "rustc 1.94.0", "cargo": "cargo 1.94.0", "node": "v24.0.0", "npm": "11.0.0"},
    }
    metadata = "Metadata-Version: 2.4\nName: coilem\nVersion: 0.2.0\nRequires-Python: <3.16,>=3.11\n"
    metadata += "License-Expression: AGPL-3.0-or-later\nLicense-File: LICENSE\nLicense-File: THIRD_PARTY_NOTICES.md\n"
    metadata += "".join(f"Requires-Dist: {line}\n" for line in requires) + 'Requires-Dist: pytest; extra == "dev"\n'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("backend/__init__.py", f"__version__ = {json.dumps(runtime_version)}\n")
        archive.writestr(f"{dist_info}/METADATA", metadata)
        archive.writestr(
            f"{dist_info}/entry_points.txt",
            "[console_scripts]\ncoilem = backend.launcher:main\ncoilem-serve = backend.public_main:start\n",
        )
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            archive.writestr(f"{dist_info}/licenses/{name}", name)
        executable = zipfile.ZipInfo("backend/_bin/magneto2d")
        executable.external_attr = 0o100755 << 16
        archive.writestr(executable, binary)
        for name, data in ui.items():
            archive.writestr(f"backend/_ui/{name}", data)
        archive.writestr(
            "backend/_licenses/magneto2d-rust-crates.txt",
            crate_licenses if crate_licenses is not None else
            "Header\n\nCrates\n------\nfaer 0.24.0: MIT\n\nLicense texts\n-------------\n\nUsed by: faer 0.24.0 (COPYING.SUITE_SPARSE.AMD.BSD)\n",
        )
        archive.writestr("backend/_build_info.json", json.dumps(build))
        for relative in (*resources.PACKAGED_DATA_FILES, *resources.benchmark_data_files(REPO_ROOT)):
            archive.writestr(f"backend/_data/{relative}", (REPO_ROOT / relative).read_bytes())
        for relative in resources.PACKAGE_DATA_FILES:
            archive.writestr(relative, (REPO_ROOT / relative).read_bytes())
    return path


def test_bundle_hash_orders_paths_the_same_on_every_os(tmp_path: Path) -> None:
    files = {"index.html": b"index", "assets/index-AbCd1234.js": b"lower", "assets/Lesson-AbCd1234.js": b"upper"}
    for name, data in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    # Code-point order puts upper case first; Windows orders Path objects without case.
    order = ["assets/Lesson-AbCd1234.js", "assets/index-AbCd1234.js", "index.html"]
    lines = "".join(f"{name} {hashlib.sha256(files[name]).hexdigest()}\n" for name in order)
    assert resources.directory_sha256(tmp_path) == hashlib.sha256(lines.encode()).hexdigest()
    assert resources.bundle_sha256(reversed(list(files.items()))) == resources.directory_sha256(tmp_path)


def test_wheel_checks(tmp_path: Path) -> None:
    lock = [str(item) for item in policy.read_lock(REPO_ROOT / "requirements.lock")]
    good = _write_wheel(tmp_path / "coilem-0.2.0-py3-none-macosx_12_0_arm64.whl", requires=lock)
    assert verify_wheel.check_wheel(good, platform_tag="macosx_12_0_arm64", require_commit=True) == []
    assert verify_wheel.check_wheel(good, platform_tag="macosx_11_0_arm64") == [
        "platform tag macosx_12_0_arm64 differs from the release policy's macosx_11_0_arm64"
    ]
    loose = _write_wheel(tmp_path / "coilem-0.2.0-py3-none-macosx_12_0_arm64.whl", requires=["numpy>=1.24", *lock[1:]])
    assert any("Requires-Dist differs from requirements.lock" in problem for problem in verify_wheel.check_wheel(loose))
    stale = _write_wheel(tmp_path / "coilem-0.2.0-py3-none-macosx_12_0_arm64.whl", requires=lock, stamp_binary=b"other")
    assert verify_wheel.check_wheel(stale) == ["build info magneto2d_sha256 does not match the packaged binary"]
    linux = _write_wheel(tmp_path / "coilem-0.2.0-py3-none-linux_x86_64.whl", requires=lock)
    assert "linux_x86_64 is not a publishable platform tag" in verify_wheel.check_wheel(linux)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_wheel_rejects_missing_crate_coverage_and_malformed_report(tmp_path: Path, newline: str) -> None:
    lock = [str(item) for item in policy.read_lock(REPO_ROOT / "requirements.lock")]
    path = tmp_path / "coilem-0.2.0-py3-none-macosx_12_0_arm64.whl"
    report = (
        "Header\n\nCrates\n------\nfaer 0.24.0: MIT\nnano-gemm 0.2.2: MIT\n\nLicense texts\n-------------\n\n"
        "Used by: faer 0.24.0 (COPYING.SUITE_SPARSE.AMD.BSD)\n"
    )
    wheel = _write_wheel(path, requires=lock, crate_licenses=report.replace("\n", newline))
    assert verify_wheel.check_wheel(wheel) == [
        "crates without a license text in the crate license file: nano-gemm 0.2.2"
    ]
    wheel = _write_wheel(path, requires=lock, crate_licenses="Used by: faer 0.24.0 (COPYING.SUITE_SPARSE.AMD.BSD)\n")
    assert verify_wheel.check_wheel(wheel) == ["crate license report is missing its Crates section"]


def test_wheel_rejects_a_different_backend_version(tmp_path: Path) -> None:
    lock = [str(item) for item in policy.read_lock(REPO_ROOT / "requirements.lock")]
    wheel = _write_wheel(
        tmp_path / "coilem-0.2.0-py3-none-macosx_12_0_arm64.whl", requires=lock, runtime_version="0.2.0.dev17",
    )
    assert verify_wheel.check_wheel(wheel) == ["backend version 0.2.0.dev17 differs from the wheel's 0.2.0"]


def test_acceptance_test_is_self_contained_with_current_inputs() -> None:
    spec = importlib.util.spec_from_file_location("acceptance", REPO_ROOT / "tools/release/acceptance.py")
    acceptance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acceptance)
    assert acceptance.MOTOR == json.loads((REPO_ROOT / "tests/fixtures/spm_4p12s_simple.json").read_text())
    examples = REPO_ROOT / "schemas/v1/examples"
    assert acceptance.CYLINDRICAL_HALBACH == json.loads((examples / "halbach_array_16_segment.json").read_text())
    assert acceptance.LINEAR_HALBACH == json.loads((examples / "linear_halbach_array_4_period.json").read_text())
    source = (REPO_ROOT / "tools/release/acceptance.py").read_text().splitlines()
    imports = {line.split()[1].split(".")[0] for line in source if line.startswith(("import ", "from "))}
    assert not imports & {"backend", "tools", "packaging", "pytest"}


def test_rehearsal_versions_and_release_tags() -> None:
    assert version.package_version({}) == __version__
    assert version.package_version({"COILEM_VERSION_SUFFIX": ".dev3816"}) == f"{__version__}.dev3816"
    for suffix in ("rc1", ".dev", "+local", ".post1", "-dev1", ".dev1.dev2"):
        with pytest.raises(version.VersionError, match="development suffix"):
            version.package_version({"COILEM_VERSION_SUFFIX": suffix})
    version.check_tag(f"v{__version__}", __version__)
    with pytest.raises(version.VersionError, match="does not match"):
        version.check_tag("v9.9.9", __version__)
    with pytest.raises(version.VersionError, match="does not match"):
        version.check_tag(f"v{__version__}", f"{__version__}.dev1")


def _job(workflow: str, name: str) -> str:
    body = workflow.split(f"\n  {name}:\n", 1)[1]
    following = [line for line in body.splitlines() if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":")]
    return body.split(f"\n{following[0]}\n", 1)[0] if following else body


def test_release_workflow_publishes_only_after_acceptance() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release-wheels.yml").read_text()
    assert "upload.pypi.org" not in workflow
    assert workflow.count("pypa/gh-action-pypi-publish@") == 2
    assert workflow.count("id-token: write") == 2

    testpypi = _job(workflow, "publish-testpypi")
    assert "needs: [policy, acceptance, acceptance-bare-linux]" in testpypi
    assert "if: inputs.publish == 'testpypi'" in testpypi
    assert "repository-url: https://test.pypi.org/legacy/" in testpypi
    assert "id-token: write" in testpypi and "name: testpypi" in testpypi
    assert "--index-url https://test.pypi.org/simple/ --expect-sha256" in _job(workflow, "testpypi-acceptance")

    # PyPI: only a pushed tag (checked against the version by the policy job),
    # only after acceptance, and only through the reviewed `pypi` environment.
    pypi = _job(workflow, "publish-pypi")
    assert "needs: [policy, acceptance, acceptance-bare-linux]" in pypi
    assert "if: github.event_name == 'push' && github.ref_type == 'tag'" in pypi
    assert "name: pypi" in pypi and "id-token: write" in pypi
    assert "repository-url" not in pypi
    assert 'args=(--tag "$GITHUB_REF_NAME")' in _job(workflow, "policy")
    assert "--index-url https://pypi.org/simple/ --expect-sha256" in _job(workflow, "pypi-acceptance")
    release = _job(workflow, "github-release")
    assert "needs: [policy, pypi-acceptance]" in release
    assert "contents: write" in release and "--draft --verify-tag" in release
    assert workflow.count("contents: write") == 1


# Actions that ran on Node 20 and the first major of each that runs on Node 24 (#79).
NODE24_MAJORS = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/setup-node": 5,
    "actions/upload-artifact": 6,
    "actions/download-artifact": 7,
}


def test_workflow_actions_are_pinned_by_commit_to_node24_releases() -> None:
    import re

    pattern = re.compile(r"uses: (actions/[a-z-]+)@(\S+)(?: # v(\d+)\.\d+\.\d+)?")
    seen = set()
    for workflow in sorted((REPO_ROOT / ".github/workflows").glob("*.yml")):
        for action, ref, major in pattern.findall(workflow.read_text()):
            seen.add(action)
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{workflow.name}: {action}@{ref} is not pinned by commit"
            assert major and int(major) >= NODE24_MAJORS[action], f"{workflow.name}: {action} v{major} predates Node 24"
    assert seen == set(NODE24_MAJORS)


def _acceptance_module():
    spec = importlib.util.spec_from_file_location("acceptance", REPO_ROOT / "tools/release/acceptance.py")
    acceptance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acceptance)
    return acceptance


def test_acceptance_takes_the_built_wheel_from_the_json_api(tmp_path, monkeypatch) -> None:
    import io
    import urllib.error

    acceptance = _acceptance_module()
    wheel_bytes = b"the wheel CI built"
    digest = hashlib.sha256(wheel_bytes).hexdigest()
    listing = {"urls": [
        {"packagetype": "sdist", "filename": "coilem-0.4.0.tar.gz", "url": "https://files.example/sdist", "digests": {"sha256": "0" * 64}},
        {"packagetype": "bdist_wheel", "filename": "coilem-0.4.0-py3-none-other.whl", "url": "https://files.example/other",
         "digests": {"sha256": "1" * 64}},
        {"packagetype": "bdist_wheel", "filename": "coilem-0.4.0-py3-none-this.whl", "url": "https://files.example/this",
         "digests": {"sha256": digest}},
    ]}
    requested = []

    def urlopen(url, timeout=None):
        requested.append(url)
        if url.endswith("/json") and len(requested) == 1:
            raise urllib.error.HTTPError(url, 404, "not yet", None, None)  # still propagating
        if url.endswith("/json"):
            return io.BytesIO(json.dumps(listing).encode())
        assert url == "https://files.example/this"
        return io.BytesIO(wheel_bytes)

    monkeypatch.setattr(acceptance.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(acceptance.time, "sleep", lambda seconds: None)
    run = acceptance.Acceptance(tmp_path)
    wheel = run.download("coilem==0.4.0", "https://test.pypi.org/simple/", digest, "python")
    assert requested[0] == "https://test.pypi.org/pypi/coilem/0.4.0/json"
    assert Path(wheel).read_bytes() == wheel_bytes
    assert run.results[-1][1] is True

    # A version whose files don't include the wheel CI built fails the check instead of installing anything.
    requested.clear()
    requested.append("skip the propagation miss")
    assert acceptance.Acceptance(tmp_path / "other").download("coilem==0.4.0", "https://pypi.org/simple/", "f" * 64, "python") == ""



def test_acceptance_falls_back_to_pip_at_once_when_the_json_api_is_unusable(tmp_path, monkeypatch) -> None:
    import ssl
    import urllib.error

    acceptance = _acceptance_module()
    wheel_bytes = b"the wheel CI built"
    digest = hashlib.sha256(wheel_bytes).hexdigest()
    sleeps, pip_calls = [], []
    monkeypatch.setattr(acceptance.time, "sleep", sleeps.append)

    def pip_download(self, requirement, index_url, python, destination):
        pip_calls.append(requirement)
        wheel = destination / "coilem-0.4.0-py3-none-this.whl"
        wheel.write_bytes(wheel_bytes)
        return wheel

    monkeypatch.setattr(acceptance.Acceptance, "pip_download", pip_download)
    failures = [
        urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed")),  # TLS on a runner's Python
        urllib.error.HTTPError("https://test.pypi.org/pypi/coilem/0.4.0/json", 403, "forbidden", None, None),
    ]
    for failure in failures:
        def urlopen(url, timeout=None, failure=failure):
            raise failure

        monkeypatch.setattr(acceptance.urllib.request, "urlopen", urlopen)
        run = acceptance.Acceptance(tmp_path / str(len(pip_calls)))
        wheel = run.download("coilem==0.4.0", "https://test.pypi.org/simple/", digest, "python")
        assert Path(wheel).read_bytes() == wheel_bytes and run.results[-1][1] is True
    # Neither failure is "not on the index yet": pip takes over without the 25-minute wait.
    assert pip_calls == ["coilem==0.4.0", "coilem==0.4.0"] and sleeps == []

def test_release_notes_links_become_absolute_for_the_release_page() -> None:
    from tools.release.release_notes import absolute_links

    text = "See [install\n](README.md#install), [docs](./docs/VALIDATION.md), [web](https://x.org/a), [here](#top) and [abs](/root)."
    assert absolute_links(text, "coilemdev/coilem", "v0.4.0") == (
        "See [install\n](https://github.com/coilemdev/coilem/blob/v0.4.0/README.md#install), "
        "[docs](https://github.com/coilemdev/coilem/blob/v0.4.0/docs/VALIDATION.md), [web](https://x.org/a), [here](#top) and [abs](/root)."
    )
    notes = (REPO_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    rewritten = absolute_links(notes, "coilemdev/coilem", "v0.4.0")
    import re

    assert not [t for t in re.findall(r"\]\(([^)\s]+)\)", rewritten) if not t.startswith(("http://", "https://", "#", "mailto:"))]
    release = _job((REPO_ROOT / ".github/workflows/release-wheels.yml").read_text(), "github-release")
    assert "tools/release/release_notes.py RELEASE_NOTES.md" in release and '--notes-file "$RUNNER_TEMP/notes.md"' in release
