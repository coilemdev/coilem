"""The distribution version: ``backend.__version__``, plus ``.devN`` for rehearsals.

TestPyPI never accepts the same version twice, so a rehearsal upload sets
``COILEM_VERSION_SUFFIX=.devN`` to publish a unique development release. A
release tag must name the version exactly, with no suffix. Standard library
only: setup.py loads it by path.

    python -m tools.release.version [--tag vX.Y.Z]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class VersionError(Exception):
    pass


def application_version(root: Path = ROOT) -> str:
    match = re.search(r'^__version__ = "([^"]+)"$', (root / "backend" / "__init__.py").read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise VersionError("backend/__init__.py does not define __version__")
    return match[1]


def package_version(environ: Mapping[str, str] = os.environ, root: Path = ROOT) -> str:
    suffix = environ.get("COILEM_VERSION_SUFFIX", "")
    if suffix and not re.fullmatch(r"\.dev\d+", suffix):
        raise VersionError("COILEM_VERSION_SUFFIX must be a development suffix such as .dev12")
    return application_version(root) + suffix


def check_tag(tag: str, version: str) -> None:
    if tag != f"v{version}":
        raise VersionError(f"tag {tag} does not match the package version {version}; tag releases as v{version}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="a release tag that must match the version exactly")
    args = parser.parse_args(argv)
    try:
        version = package_version()
        if args.tag is not None:
            check_tag(args.tag, version)
    except VersionError as exc:
        print(f"release version: {exc}", file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
