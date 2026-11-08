"""Fast JSON for the solver's large per-solve files, with the standard library as the fallback.

Each per-angle solve writes its ~14 MB mesh as JSON for Magneto2D and parses
its ~13 MB report back, and the field-frame stage parses each report again.
The standard library holds Python's GIL for all of that, and the eight solve
threads share one GIL. orjson does the same conversions several times faster.

orjson reads and writes the same values as ``json``: floats round-trip
exactly, -0.0 included, and parsed floats are correctly rounded. Some numbers
are written in a different text form (``0.00001`` for ``1e-05``), so it is not
used where text must match byte for byte, such as evidence hashes. Values it
cannot serialize (non-string keys, integers beyond 64 bits, unknown types)
and text it rejects but ``json`` accepts (``NaN``) fall back to ``json``.
One difference has no fallback: orjson reads an integer beyond the 64-bit
range as a float, where ``json`` keeps it exact. Magneto2D writes no such
integer, so only use ``loads`` on solver output. Without orjson installed,
everything uses ``json``.
"""

from __future__ import annotations

import json
from typing import Any

try:  # pragma: no cover - exercised by whichever interpreter runs the tests
    import orjson
except ImportError:  # pragma: no cover
    orjson = None  # type: ignore[assignment]


def dumps_bytes(value: Any) -> bytes:
    """Compact UTF-8 JSON for ``value``, as the solver reads it."""

    if orjson is not None:
        try:
            return orjson.dumps(value)
        except TypeError:
            pass
    return json.dumps(value).encode("utf-8")


def loads(data: bytes | str) -> Any:
    """Parse JSON text or UTF-8 bytes; ``json.JSONDecodeError`` on invalid input."""

    if orjson is not None:
        try:
            return orjson.loads(data)
        except orjson.JSONDecodeError:
            pass
    return json.loads(data)
