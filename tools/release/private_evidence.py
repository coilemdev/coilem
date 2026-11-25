"""Benchmark evidence that stays in the private experiments repository.

The release rule (docs/RELEASING.md, step 2) runs release qualification in the
private experiments repository: "Keep the review and measurements in the
private repository. The existing A-F measurements in the public package retain
their original measured commit." PUBLICATION_STATUS.md adds that public
benchmark publication is paused. This module is the one declared list of that
evidence: the generated records of the benchmarks added after the public A-F
record, the measured statements taken out of public documents
(``MEASURED_CLAIMS.md`` in each benchmark folder), and the tests that check
those records (``tests/private_records``). Their definitions (README,
specification, fixtures, FEMM requests, gates, protocol documents and
transcribed published data) stay public. A measured claim quoted in a public
file is refused separately, by ``tools/release/disclosures.py``.

Every file under ``EVIDENCE_ROOTS`` must match exactly one of ``PRIVATE`` or
``PUBLIC``, so a new file there needs a decision before it can be exported.
Nothing outside those roots is private: the A-F evidence on public ``main``
is never filtered or changed.

The public source export (``tools/release/public_tree.py``) drops these paths,
the wheel verifier refuses them, ``tools/verify_snapshot.py --public-tree``
refuses them, and tests that read them skip when they are absent.

Standard library only: ``setup.py`` and ``tools/verify_snapshot.py`` load this
file by path.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

# Benchmarks registered after the public A-F record, and the private tests of their records.
# Only files here can be private.
EVIDENCE_ROOTS = ("benchmarks/g-v2.0", "benchmarks/h-v1.0", "benchmarks/thermal-v0.6", "tests/private_records")

# Generated measurements. ``*`` matches within one path segment, ``**`` any depth.
PRIVATE = (
    # Phase G (protocol G-2.0.0): coilEM's stored record and the FEMM 4.2
    # stator and FEMM 5 rotor outputs it is graded against.
    "benchmarks/g-v2.0/RESULTS.md",
    "benchmarks/g-v2.0/results/**",
    "benchmarks/g-v2.0/references/**",
    "benchmarks/g-v2.0/MEASURED_CLAIMS.md",
    # Phase H (protocol H-1.0.0): coilEM's stored record and the FEMM 5 outputs.
    "benchmarks/h-v1.0/RESULTS.md",
    "benchmarks/h-v1.0/results/**",
    "benchmarks/h-v1.0/references/**",
    "benchmarks/h-v1.0/MEASURED_CLAIMS.md",
    # Thermal 0.6: result records, metrics tables, the native comparison and
    # rating bundles, their recomputations, FEMM outputs, screenshots and the
    # write-ups that mainly report those numbers.
    "benchmarks/thermal-v0.6/*-results.json",
    "benchmarks/thermal-v0.6/*-metrics.csv",
    "benchmarks/thermal-v0.6/*-native.json",
    "benchmarks/thermal-v0.6/*-recomputed.json",
    "benchmarks/thermal-v0.6/path-audit-initial.json",
    "benchmarks/thermal-v0.6/rotor-heat-path-checks.json",
    "benchmarks/thermal-v0.6/ipm-interpolation-isolation.json",
    "benchmarks/thermal-v0.6/femm/**",
    "benchmarks/thermal-v0.6/screenshots/**",
    "benchmarks/thermal-v0.6/*RESULTS*.md",
    "benchmarks/thermal-v0.6/THERMAL_PATH_AUDIT.md",
    "benchmarks/thermal-v0.6/ROTOR_HEAT_SCOPE.md",
    "benchmarks/thermal-v0.6/MEASURED_CLAIMS.md",
    # Tests that check the records above and state measured bounds, and the
    # plaintext list of measured claims behind tools/release/disclosure_fingerprints.json.
    "tests/private_records/**",
)

# Definitions and inputs that any tool needs to run the benchmarks.
PUBLIC = (
    "benchmarks/g-v2.0/README.md",
    "benchmarks/g-v2.0/benchmark_spec.json",
    "benchmarks/g-v2.0/fixtures/**",
    "benchmarks/g-v2.0/femm-requests/**",
    "benchmarks/h-v1.0/README.md",
    "benchmarks/h-v1.0/benchmark_spec.json",
    "benchmarks/h-v1.0/fixtures/**",
    "benchmarks/h-v1.0/femm-requests/**",
    "benchmarks/thermal-v0.6/README.md",
    "benchmarks/thermal-v0.6/*-gates.json",
    "benchmarks/thermal-v0.6/*-gate.json",
    "benchmarks/thermal-v0.6/*-fixtures.json",
    "benchmarks/thermal-v0.6/ANALYTICAL_PROTOCOL.md",
    "benchmarks/thermal-v0.6/ANALYTICAL_REDUCTION_FIX.md",
    "benchmarks/thermal-v0.6/BENCH_PROTOCOL.md",
    "benchmarks/thermal-v0.6/FEMM_REQUEST.md",
    "benchmarks/thermal-v0.6/published/**",
)

PRIVATE_NOTE = "kept in the private repository"


def _regex(pattern: str) -> re.Pattern[str]:
    parts = []
    for token in re.split(r"(\*\*|\*)", pattern):
        parts.append(".+" if token == "**" else "[^/]*" if token == "*" else re.escape(token))
    return re.compile("".join(parts))


@lru_cache(maxsize=None)
def _compiled(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(_regex(pattern) for pattern in patterns)


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(regex.fullmatch(path) for regex in _compiled(patterns))


def _normal(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def in_evidence_root(path: str) -> bool:
    path = _normal(path)
    return any(path.startswith(root + "/") for root in EVIDENCE_ROOTS)


def is_private(path: str) -> bool:
    """True for a repository-relative POSIX path that is private evidence."""

    path = _normal(path)
    return in_evidence_root(path) and _matches(path, PRIVATE)


def is_public_definition(path: str) -> bool:
    path = _normal(path)
    return in_evidence_root(path) and _matches(path, PUBLIC)


def private_paths(paths: Iterable[str]) -> list[str]:
    return sorted(path for path in paths if is_private(path))


def unclassified(paths: Iterable[str]) -> list[str]:
    """Files under an evidence root that match neither list, or both."""

    return sorted(path for path in paths
                  if in_evidence_root(path) and is_private(path) == is_public_definition(path))
