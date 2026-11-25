"""Skip a test when the private benchmark evidence it reads is absent.

The public source export leaves out the generated records listed in
``tools/release/private_evidence.py``; they are kept in the private repository.
A test that compares against such a record skips there and runs everywhere the
record is present. Name only private paths: a public definition that goes
missing must still fail.

    @requires_private_evidence("benchmarks/h-v1.0/results/coilem.json")
    def test_...(): ...

    skip_without_private_evidence("benchmarks/thermal-v0.6/femm")  # inside a fixture or test
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.release import private_evidence

ROOT = Path(__file__).resolve().parents[1]


def _checked(paths: tuple[str, ...]) -> tuple[str, ...]:
    if not paths:
        raise ValueError("name the private evidence the test reads")
    for path in paths:
        # A directory is private when the files under it are.
        if not (private_evidence.is_private(path) or private_evidence.is_private(path.rstrip("/") + "/_")):
            raise ValueError(f"{path} is not private evidence; a missing public file must fail, not skip")
    return paths


def missing_private_evidence(*paths: str) -> list[str]:
    """The named private files, or directories with no file in them, that are absent."""

    absent = []
    for path in _checked(paths):
        location = ROOT / path
        present = location.is_file() or (location.is_dir() and any(item.is_file() for item in location.rglob("*")))
        if not present:
            absent.append(path)
    return absent


def _reason(absent: list[str]) -> str:
    return f"private benchmark evidence absent ({', '.join(absent)}): it is {private_evidence.PRIVATE_NOTE}"


def requires_private_evidence(*paths: str) -> pytest.MarkDecorator:
    """Mark a test to skip unless every named private record is present."""

    absent = missing_private_evidence(*paths)
    return pytest.mark.skipif(bool(absent), reason=_reason(absent))


def skip_without_private_evidence(*paths: str) -> None:
    """Skip the running test (or every test using the running fixture) when a named record is absent."""

    absent = missing_private_evidence(*paths)
    if absent:
        pytest.skip(_reason(absent))
