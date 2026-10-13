"""Compute the platform floor each release wheel can claim.

A coilEM wheel installs its pinned runtime dependencies (requirements.lock), so
the oldest OS it supports is the highest minimum among the binary wheels those
pins publish for that platform, and never below what the bundled Rust binary
needs. This tool reads the lock, lists each pin's wheels on PyPI, and reports
per target the wheel platform tag, the macOS deployment target or manylinux
glibc version for the Magneto2D build, and which pins set the floor. It fails
when a pin has no wheel for a supported platform and Python version, or when
the lock's environment markers leave a package with no pin, or more than one,
for a supported platform and Python version.

    python -m tools.release.policy [--json] [--github-output FILE]
    python -m tools.release.policy --audit-pins DIR

``--audit-pins`` writes each supported Python's pins without markers, for
pip-audit, which skips pins whose markers do not match its own interpreter.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement
from packaging.tags import Tag
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_PYTHONS = ("3.11", "3.12", "3.13", "3.14", "3.15")
# Minimums of Rust's standard library for the release toolchain.
RUST_MINIMUMS = {"macos-arm64": (11, 0), "macos-x86_64": (10, 12), "linux-x86_64": (2, 17)}
# Newest manylinux build image first; the binary is built in the newest one
# whose glibc does not exceed the floor.
MANYLINUX_IMAGES = (
    ((2, 34), "quay.io/pypa/manylinux_2_34_x86_64"),
    ((2, 28), "quay.io/pypa/manylinux_2_28_x86_64"),
    ((2, 17), "quay.io/pypa/manylinux2014_x86_64"),
)
_LEGACY_MANYLINUX = {"manylinux1": (2, 5), "manylinux2010": (2, 12), "manylinux2014": (2, 17)}
_MACOS_TAG = re.compile(r"macosx_(\d+)_(\d+)_(\w+)")
_MANYLINUX_TAG = re.compile(r"manylinux_(\d+)_(\d+)_(\w+)")


class PolicyError(Exception):
    pass


@dataclass(frozen=True)
class Target:
    key: str
    system: str  # macos | linux | windows
    arch: str

    def marker_environment(self, python: str) -> dict[str, str]:
        sys_platform, platform_system, os_name, machine = {
            "macos": ("darwin", "Darwin", "posix", self.arch),
            "linux": ("linux", "Linux", "posix", self.arch),
            "windows": ("win32", "Windows", "nt", "AMD64"),
        }[self.system]
        return {
            "sys_platform": sys_platform,
            "platform_system": platform_system,
            "os_name": os_name,
            "platform_machine": machine,
            "python_version": python,
            "python_full_version": f"{python}.0",
        }


TARGETS = (
    Target("macos-arm64", "macos", "arm64"),
    Target("macos-x86_64", "macos", "x86_64"),
    Target("linux-x86_64", "linux", "x86_64"),
    Target("windows-amd64", "windows", "amd64"),
)


def read_lock(path: Path) -> list[Requirement]:
    requirements = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        specifiers = list(requirement.specifier)
        if len(specifiers) != 1 or specifiers[0].operator != "==":
            raise PolicyError(f"requirements.lock entries must be exact pins: {line}")
        requirements.append(requirement)
    return requirements


def pinned_version(requirement: Requirement) -> str:
    return next(iter(requirement.specifier)).version


def applies(requirement: Requirement, target: Target, python: str) -> bool:
    return requirement.marker is None or requirement.marker.evaluate(target.marker_environment(python))


def check_markers(requirements: list[Requirement], pythons: Iterable[str] = SUPPORTED_PYTHONS) -> None:
    """Require one pin per package on every supported Python of each target
    where the package is installed, so a pin split by Python version cannot
    leave a version without it or install two."""

    pythons = tuple(pythons)
    for target in TARGETS:
        pins: dict[str, dict[str, list[str]]] = {}
        for requirement in requirements:
            for python in pythons:
                if applies(requirement, target, python):
                    pins.setdefault(canonicalize_name(requirement.name), {}).setdefault(python, []).append(str(requirement))
        for name, by_python in pins.items():
            for python in pythons:
                found = by_python.get(python, [])
                if len(found) != 1:
                    raise PolicyError(f"{name} has {len(found)} pins for {target.key} on Python {python}: {found}")


def audit_pins(requirements: list[Requirement], python: str) -> list[str]:
    """The exact pins a supported Python installs on any target, without markers."""

    return [
        f"{requirement.name}=={pinned_version(requirement)}"
        for requirement in requirements
        if any(applies(requirement, target, python) for target in TARGETS)
    ]


def pypi_wheel_files(name: str, version: str) -> list[str]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
    return [entry["filename"] for entry in payload["urls"] if entry["filename"].endswith(".whl")]


def python_compatible(tag: Tag, python: str) -> bool:
    major, minor = (int(part) for part in python.split("."))
    interpreter, abi = tag.interpreter, tag.abi
    if interpreter in {"py3", f"py{major}{minor}"}:
        return abi == "none"
    match = re.fullmatch(r"cp(\d)(\d+)", interpreter)
    if not match:
        return False
    version = (int(match[1]), int(match[2]))
    if abi == "abi3":
        return version <= (major, minor)
    return version == (major, minor) and abi in {interpreter, "none"}


def platform_floor(tag: Tag, target: Target) -> tuple[int, int] | None | bool:
    """Return the platform minimum ``tag`` needs on ``target``: ``None`` for any
    platform, a version tuple, or ``False`` when the tag does not run there."""

    platform = tag.platform
    if platform == "any":
        return None
    if target.system == "macos":
        match = _MACOS_TAG.fullmatch(platform)
        if not match:
            return False
        arches = {"arm64": {"arm64", "universal2"}, "x86_64": {"x86_64", "universal2", "intel"}}[target.arch]
        return (int(match[1]), int(match[2])) if match[3] in arches else False
    if target.system == "linux":
        legacy = re.fullmatch(r"(manylinux1|manylinux2010|manylinux2014)_(\w+)", platform)
        if legacy:
            return _LEGACY_MANYLINUX[legacy[1]] if legacy[2] == target.arch else False
        match = _MANYLINUX_TAG.fullmatch(platform)
        return (int(match[1]), int(match[2])) if match and match[3] == target.arch else False
    return None if platform == "win_amd64" else False


def package_floor(files: Iterable[str], target: Target, python: str) -> tuple[int, int] | None:
    """The lowest platform minimum among a package's wheels for ``target``."""

    floors: list[tuple[int, int] | None] = []
    for filename in files:
        _, _, _, tags = parse_wheel_filename(filename)
        for tag in tags:
            if not python_compatible(tag, python):
                continue
            floor = platform_floor(tag, target)
            if floor is not False:
                floors.append(floor)
    if not floors:
        raise PolicyError(f"no wheel for {target.key} on Python {python}")
    if None in floors:
        return None
    return min(floor for floor in floors if floor is not None)


def compute_policy(
    requirements: list[Requirement],
    fetch: Callable[[str, str], list[str]] = pypi_wheel_files,
    pythons: Iterable[str] = SUPPORTED_PYTHONS,
) -> dict[str, dict[str, object]]:
    pythons = tuple(pythons)
    check_markers(requirements, pythons)
    files = {str(requirement): fetch(requirement.name, pinned_version(requirement)) for requirement in requirements}
    policy: dict[str, dict[str, object]] = {}
    for target in TARGETS:
        floor = RUST_MINIMUMS.get(target.key)
        constraints: dict[str, str] = {}
        for requirement in requirements:
            for python in pythons:
                if not applies(requirement, target, python):
                    continue
                try:
                    package = package_floor(files[str(requirement)], target, python)
                except PolicyError as exc:
                    raise PolicyError(f"{requirement.name}=={pinned_version(requirement)}: {exc}") from exc
                if package is not None:
                    constraints[requirement.name] = max(constraints.get(requirement.name, "0.0"), f"{package[0]}.{package[1]}", key=_version_key)
                    floor = package if floor is None else max(floor, package)
        policy[target.key] = _describe(target, floor, constraints)
    return policy


def _version_key(text: str) -> tuple[int, int]:
    major, minor = text.split(".")
    return int(major), int(minor)


def _describe(target: Target, floor: tuple[int, int] | None, constraints: dict[str, str]) -> dict[str, object]:
    limiting = sorted(name for name, value in constraints.items() if floor is not None and _version_key(value) == floor)
    description: dict[str, object] = {"limited_by": limiting}
    if target.system == "macos":
        assert floor is not None
        description["platform_tag"] = f"macosx_{floor[0]}_{floor[1]}_{target.arch}"
        description["macosx_deployment_target"] = f"{floor[0]}.{floor[1]}"
    elif target.system == "linux":
        assert floor is not None
        description["platform_tag"] = f"manylinux_{floor[0]}_{floor[1]}_{target.arch}"
        description["glibc"] = f"{floor[0]}.{floor[1]}"
        description["build_image"] = next(image for glibc, image in MANYLINUX_IMAGES if glibc <= floor)
    else:
        description["platform_tag"] = "win_amd64"
    return description


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lock", type=Path, default=ROOT / "requirements.lock")
    parser.add_argument("--json", action="store_true", help="print the policy as JSON")
    parser.add_argument("--github-output", type=Path, help="append `policy=<json>` for a GitHub Actions step")
    parser.add_argument("--audit-pins", type=Path, metavar="DIR", help="write pins-<python>.txt for each supported Python and exit")
    args = parser.parse_args(argv)
    try:
        requirements = read_lock(args.lock)
        if args.audit_pins:
            check_markers(requirements)
            args.audit_pins.mkdir(parents=True, exist_ok=True)
            for python in SUPPORTED_PYTHONS:
                pins = "".join(f"{pin}\n" for pin in audit_pins(requirements, python))
                (args.audit_pins / f"pins-{python}.txt").write_text(pins, encoding="utf-8")
            return 0
        policy = compute_policy(requirements)
    except PolicyError as exc:
        print(f"release policy: {exc}", file=sys.stderr)
        return 1
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"policy={json.dumps(policy, separators=(',', ':'))}\n")
    if args.json:
        print(json.dumps(policy, indent=2))
    else:
        for key, entry in policy.items():
            extra = f" (limited by {', '.join(entry['limited_by'])})" if entry["limited_by"] else ""
            print(f"{key}: {entry['platform_tag']}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
