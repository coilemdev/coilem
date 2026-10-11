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


def fake_index(files: dict[str, list[str]]):
    return lambda name, version: files[name]


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
        policy.Requirement("numpy==2.4.6"),
        policy.Requirement("idna==3.18"),
        policy.Requirement('colorama==0.4.6; platform_system == "Windows"'),
    ]
    index = {"gmsh": GMSH, "numpy": NUMPY, "idna": ["idna-3.18-py3-none-any.whl"], "colorama": ["colorama-0.4.6-py2.py3-none-any.whl"]}
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


def test_crate_license_report_dedupes_texts() -> None:
    mit = "MIT License\n\nCopyright (c) Example"
    crates = [
        rust_licenses.Crate("alpha", "1.0.0", "MIT OR Apache-2.0", "https://example.com/alpha", {"LICENSE-MIT": mit, "LICENSE-APACHE": "Apache"}),
        rust_licenses.Crate("beta", "2.0.0", "MIT OR Apache-2.0", "", {"LICENSE-APACHE": "Apache"}),
    ]
    text = rust_licenses.render(crates, "x86_64-unknown-linux-gnu")
    assert "built for x86_64-unknown-linux-gnu" in text
    assert text.count("\nApache\n") == 1
    assert "Used by: alpha 1.0.0 (LICENSE-APACHE), beta 2.0.0 (LICENSE-APACHE)" in text
    assert verify_wheel.crates_without_license_text(text) == []
    uncovered = text.replace("Used by: alpha 1.0.0 (LICENSE-APACHE), beta 2.0.0 (LICENSE-APACHE)", "Used by: alpha 1.0.0 (LICENSE-APACHE)")
    assert verify_wheel.crates_without_license_text(uncovered) == ["beta 2.0.0"]


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


@pytest.mark.skipif(shutil.which("cargo") is None, reason="needs Cargo and the locked crate sources")
@pytest.mark.parametrize("target", ["x86_64-unknown-linux-gnu", "aarch64-apple-darwin", "x86_64-apple-darwin", "x86_64-pc-windows-msvc"])
def test_every_linked_crate_carries_a_license_text(target: str) -> None:
    try:
        crates = rust_licenses.collect(target)
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


def _write_wheel(path: Path, *, requires: list[str], binary: bytes = b"binary", stamp_binary: bytes | None = None) -> Path:
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
    metadata = "Metadata-Version: 2.4\nName: coilem\nVersion: 0.2.0\nRequires-Python: <3.15,>=3.11\n"
    metadata += "License-Expression: AGPL-3.0-or-later\nLicense-File: LICENSE\nLicense-File: THIRD_PARTY_NOTICES.md\n"
    metadata += "".join(f"Requires-Dist: {line}\n" for line in requires) + 'Requires-Dist: pytest; extra == "dev"\n'
    with zipfile.ZipFile(path, "w") as archive:
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
            "Header\n\nCrates\n------\nfaer 0.24.0: MIT\n\nLicense texts\n-------------\n\nUsed by: faer 0.24.0 (COPYING.SUITE_SPARSE.AMD.BSD)\n",
        )
        archive.writestr("backend/_build_info.json", json.dumps(build))
        for relative in resources.PACKAGED_DATA_FILES:
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


def test_release_workflow_uploads_only_to_testpypi_after_acceptance() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release-wheels.yml").read_text()
    assert "upload.pypi.org" not in workflow
    assert workflow.count("pypa/gh-action-pypi-publish@") == 1
    publish = workflow.split("\n  publish-testpypi:\n", 1)[1].split("\n  testpypi-acceptance:\n", 1)[0]
    assert "needs: [policy, acceptance]" in publish
    assert "if: inputs.publish == 'testpypi'" in publish
    assert "repository-url: https://test.pypi.org/legacy/" in publish
    assert "id-token: write" in publish and "name: testpypi" in publish
    assert "--index-url https://test.pypi.org/simple/ --expect-sha256" in workflow
