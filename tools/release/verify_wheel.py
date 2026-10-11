"""Check a built coilEM wheel before it is tested or published.

Verifies the platform tag, the metadata (dependencies pinned exactly to
requirements.lock, the supported Python range, license files), the packaged
runtime files and the stamped build identity, including that the recorded
binary and UI hashes match the files in the wheel.

    python -m tools.release.verify_wheel WHEEL [--platform-tag TAG] [--require-commit]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name, parse_wheel_filename

from backend import resources
from tools.release.policy import SUPPORTED_PYTHONS, read_lock

ROOT = Path(__file__).resolve().parents[2]
LICENSE_FILES = ("LICENSE", "THIRD_PARTY_NOTICES.md")


def _requirement_key(requirement: Requirement) -> tuple[str, str, str]:
    return canonicalize_name(requirement.name), str(requirement.specifier), str(requirement.marker or "")


def check_wheel(path: Path, *, platform_tag: str | None = None, require_commit: bool = False, lock: Path = ROOT / "requirements.lock") -> list[str]:
    problems: list[str] = []
    name, parsed_version, _, tags = parse_wheel_filename(path.name)
    version = str(parsed_version)
    tag_text = {f"{tag.interpreter}-{tag.abi}-{tag.platform}" for tag in tags}
    if len(tags) != 1 or next(iter(tags)).interpreter != "py3" or next(iter(tags)).abi != "none":
        problems.append(f"wheel tag must be a single py3-none-<platform> tag, got {sorted(tag_text)}")
    wheel_platform = next(iter(tags)).platform
    if platform_tag is not None and wheel_platform != platform_tag:
        problems.append(f"platform tag {wheel_platform} differs from the release policy's {platform_tag}")
    if wheel_platform in {"any", ""} or wheel_platform.startswith("linux_"):
        problems.append(f"{wheel_platform} is not a publishable platform tag")

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
        top_level = {entry.split("/", 1)[0] for entry in names}
        if top_level != {"backend", dist_info}:
            problems.append(f"unexpected top-level entries: {sorted(top_level - {'backend', dist_info})}")

        metadata = Parser().parsestr(archive.read(f"{dist_info}/METADATA").decode("utf-8"))
        runtime = [Requirement(value) for value in metadata.get_all("Requires-Dist", []) if "extra ==" not in value]
        locked = read_lock(lock)
        if sorted(map(_requirement_key, runtime)) != sorted(map(_requirement_key, locked)):
            extra = sorted({str(item) for item in runtime} - {str(item) for item in locked})
            missing = sorted({str(item) for item in locked} - {str(item) for item in runtime})
            problems.append(f"Requires-Dist differs from requirements.lock: extra={extra} missing={missing}")
        requires_python = SpecifierSet(metadata.get("Requires-Python", ""))
        unsupported = [python for python in SUPPORTED_PYTHONS if python not in requires_python]
        last_major, last_minor = SUPPORTED_PYTHONS[-1].split(".")
        if unsupported or f"{last_major}.{int(last_minor) + 1}" in requires_python:
            problems.append(f"Requires-Python {requires_python} must cover exactly Python {', '.join(SUPPORTED_PYTHONS)}")
        if metadata.get("License-Expression") != "AGPL-3.0-or-later":
            problems.append("License-Expression is not AGPL-3.0-or-later")
        for license_file in LICENSE_FILES:
            if license_file not in metadata.get_all("License-File", []) or f"{dist_info}/licenses/{license_file}" not in names:
                problems.append(f"{license_file} is not shipped as a license file")
        entry_points = archive.read(f"{dist_info}/entry_points.txt").decode("utf-8")
        for script in ("coilem = backend.launcher:main", "coilem-serve = backend.public_main:start"):
            if script not in entry_points:
                problems.append(f"missing console script: {script}")

        executable = "magneto2d.exe" if wheel_platform.startswith("win") else "magneto2d"
        binary_name = f"backend/{resources.PACKAGED_BIN_DIR}/{executable}"
        required = [
            binary_name,
            f"backend/{resources.PACKAGED_UI_DIR}/index.html",
            f"backend/{resources.PACKAGED_LICENSES_DIR}/{resources.MAGNETO2D_LICENSES_FILE}",
            f"backend/{resources.BUILD_INFO_FILE}",
            *(f"backend/{resources.PACKAGED_DATA_DIR}/{relative}" for relative in resources.PACKAGED_DATA_FILES),
            *resources.PACKAGE_DATA_FILES,
        ]
        for entry in required:
            if entry not in names:
                problems.append(f"missing {entry}")
        if problems:
            return problems

        if not executable.endswith(".exe") and not (archive.getinfo(binary_name).external_attr >> 16) & 0o111:
            problems.append(f"{binary_name} is not executable")
        if not any(entry.startswith(f"backend/{resources.PACKAGED_UI_DIR}/assets/") for entry in names):
            problems.append("the UI bundle has no assets")
        for relative in resources.PACKAGED_DATA_FILES:
            source = ROOT / relative
            if source.is_file() and archive.read(f"backend/{resources.PACKAGED_DATA_DIR}/{relative}") != source.read_bytes():
                problems.append(f"packaged {relative} differs from the source file")
        crate_licenses = archive.read(f"backend/{resources.PACKAGED_LICENSES_DIR}/{resources.MAGNETO2D_LICENSES_FILE}").decode("utf-8")
        if "faer " not in crate_licenses or "COPYING.SUITE_SPARSE.AMD.BSD" not in crate_licenses:
            problems.append("the crate license file does not cover faer and its incorporated notices")

        build = json.loads(archive.read(f"backend/{resources.BUILD_INFO_FILE}"))
        for field in resources.BUILD_IDENTITY_FIELDS:
            if not build.get(field):
                problems.append(f"build info has no {field}")
        if build.get("application_version") != version:
            problems.append(f"build info version {build.get('application_version')} differs from the wheel's {version}")
        if require_commit and not re.fullmatch(r"[0-9a-f]{40}", str(build.get("application_commit"))):
            problems.append("build info application_commit is not a full commit hash")
        if build.get("magneto2d_sha256") != hashlib.sha256(archive.read(binary_name)).hexdigest():
            problems.append("build info magneto2d_sha256 does not match the packaged binary")
        prefix = f"backend/{resources.PACKAGED_UI_DIR}/"
        ui_lines = "".join(
            f"{entry.removeprefix(prefix)} {hashlib.sha256(archive.read(entry)).hexdigest()}\n"
            for entry in sorted(names)
            if entry.startswith(prefix) and not entry.endswith("/")
        )
        if build.get("ui_bundle_sha256") != hashlib.sha256(ui_lines.encode("utf-8")).hexdigest():
            problems.append("build info ui_bundle_sha256 does not match the packaged UI")
        toolchain = build.get("toolchain") or {}
        for tool in ("rustc", "cargo", "node", "npm"):
            if not toolchain.get(tool):
                problems.append(f"build info toolchain has no {tool} version")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--platform-tag", help="expected platform tag from the release policy")
    parser.add_argument("--require-commit", action="store_true", help="require a full application commit hash")
    args = parser.parse_args(argv)
    problems = check_wheel(args.wheel, platform_tag=args.platform_tag, require_commit=args.require_commit)
    for problem in problems:
        print(f"{args.wheel.name}: {problem}", file=sys.stderr)
    if not problems:
        print(f"{args.wheel.name}: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
