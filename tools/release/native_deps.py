"""Check the dynamic dependencies of the Magneto2D binary inside a wheel.

The wheel must run on a clean machine at its declared platform floor:

- macOS: only system libraries (/usr/lib, /System), and a minimum OS no newer
  than the wheel tag (otool);
- Linux: only glibc and libgcc, with symbol versions no newer than the
  manylinux tag (readelf, objdump);
- Windows: only system DLLs, and no Visual C++ or UCRT runtime, because the
  C runtime is linked statically (dumpbin /dependents).

    python -m tools.release.native_deps WHEEL
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from packaging.utils import parse_wheel_filename

LINUX_ALLOWED = frozenset(
    {"libc.so.6", "libm.so.6", "libgcc_s.so.1", "libpthread.so.0", "libdl.so.2", "librt.so.1", "ld-linux-x86-64.so.2"}
)
_WINDOWS_RUNTIME = re.compile(r"^(vcruntime|msvcp|ucrtbase|api-ms-win-crt-)", re.IGNORECASE)
# API-set names resolve inside Windows rather than to files in System32.
_WINDOWS_API_SET = re.compile(r"^(api-ms-win-core-|ext-ms-)", re.IGNORECASE)


def otool_libraries(text: str) -> list[str]:
    return [line.strip().split(" (compatibility", 1)[0] for line in text.splitlines()[1:] if line.strip()]


def otool_minimum_os(text: str) -> tuple[int, int] | None:
    match = re.search(r"^\s*minos (\d+)\.(\d+)", text, re.MULTILINE) or re.search(
        r"LC_VERSION_MIN_MACOSX.*?^\s*version (\d+)\.(\d+)", text, re.MULTILINE | re.DOTALL
    )
    return (int(match[1]), int(match[2])) if match else None


def readelf_needed(text: str) -> list[str]:
    return re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", text)


def glibc_floor(text: str) -> tuple[int, int] | None:
    versions = [tuple(int(part) for part in found.split(".")[:2]) for found in re.findall(r"GLIBC_(\d+\.\d+(?:\.\d+)?)", text)]
    return max(versions) if versions else None


def dumpbin_dependents(text: str) -> list[str]:
    _, _, rest = text.partition("Image has the following dependencies:")
    names = []
    for line in rest.splitlines():
        line = line.strip()
        if not line:
            if names:
                break
            continue
        if line.startswith("Summary") or " " in line:
            break
        names.append(line)
    return names


def check_macos(libraries: list[str], minimum: tuple[int, int] | None, floor: tuple[int, int]) -> list[str]:
    problems = [f"non-system library: {library}" for library in libraries if not library.startswith(("/usr/lib/", "/System/"))]
    if minimum is None:
        problems.append("binary records no minimum macOS version")
    elif minimum > floor:
        problems.append(f"binary needs macOS {minimum[0]}.{minimum[1]}, newer than the wheel tag's {floor[0]}.{floor[1]}")
    return problems


def check_linux(needed: list[str], glibc: tuple[int, int] | None, floor: tuple[int, int]) -> list[str]:
    problems = [f"library outside glibc and libgcc: {library}" for library in needed if library not in LINUX_ALLOWED]
    if glibc is not None and glibc > floor:
        problems.append(f"binary needs glibc {glibc[0]}.{glibc[1]}, newer than the wheel tag's {floor[0]}.{floor[1]}")
    return problems


def check_windows(dlls: list[str], system_directory: Path | None) -> list[str]:
    problems = [f"C runtime DLL; link it statically: {dll}" for dll in dlls if _WINDOWS_RUNTIME.match(dll)]
    if not dlls:
        problems.append("dumpbin listed no dependencies")
    if system_directory is not None:
        problems += [
            f"not a system DLL: {dll}"
            for dll in dlls
            if not _WINDOWS_RUNTIME.match(dll) and not _WINDOWS_API_SET.match(dll) and not (system_directory / dll).is_file()
        ]
    return problems


def _run(*command: str) -> str:
    return subprocess.run(list(command), capture_output=True, text=True, check=True).stdout


def check_wheel(wheel: Path) -> tuple[list[str], list[str]]:
    """Return the binary's dependencies and any problems."""

    platform = next(iter(parse_wheel_filename(wheel.name)[3])).platform
    executable = "magneto2d.exe" if platform.startswith("win") else "magneto2d"
    with tempfile.TemporaryDirectory() as directory, zipfile.ZipFile(wheel) as archive:
        binary = Path(archive.extract(f"backend/_bin/{executable}", directory))
        if platform.startswith("macosx_"):
            major, minor = (int(part) for part in platform.split("_")[1:3])
            libraries = otool_libraries(_run("otool", "-L", str(binary)))
            return libraries, check_macos(libraries, otool_minimum_os(_run("otool", "-l", str(binary))), (major, minor))
        if platform.startswith("manylinux_"):
            major, minor = (int(part) for part in platform.split("_")[1:3])
            needed = readelf_needed(_run("readelf", "-d", str(binary)))
            return needed, check_linux(needed, glibc_floor(_run("objdump", "-T", str(binary))), (major, minor))
        if platform.startswith("win"):
            dlls = dumpbin_dependents(_run("dumpbin", "/dependents", str(binary)))
            system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
            return dlls, check_windows(dlls, system if system.is_dir() else None)
    return [], [f"no native check for platform {platform}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args(argv)
    dependencies, problems = check_wheel(args.wheel)
    print(f"{args.wheel.name}: Magneto2D depends on {', '.join(dependencies) or 'nothing'}")
    for problem in problems:
        print(f"{args.wheel.name}: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
