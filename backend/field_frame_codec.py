"""Compact storage for solved field frames: float32 arrays in an xz stream.

A field frame is JSON with about a million numbers (mesh nodes, triangles,
element flux density, contour segments) written with 17 significant digits,
about 8 MB gzipped for a 40-pole motor. Saved runs keep one per rotor
position for playback only; the solve reads its physics from the cache's
JSON copy. Here every numeric list of at least ``MIN_ARRAY_LENGTH`` values
is stored as a little-endian array (float32 for real values, int32 for
integers) and every list of strings as a table plus indexes, with the rest
of the frame kept as JSON. The whole stream is xz-compressed: a quarter to
a third of the gzipped JSON.

Float32 keeps about seven significant digits: 0.1 micrometre on a 100 mm
motor, 0.1 microtesla on a 1 T field. Shorter lists, scalars and every
non-numeric value round-trip exactly.
"""

from __future__ import annotations

import json
import lzma
import struct
from itertools import chain
from pathlib import Path
from typing import Any

import numpy as np

MAGIC = b"COILEMF1"
SCHEMA_VERSION = "coilem.compact_field_frame.v1"
SUFFIX = ".f32.xz"
MEDIA_TYPE = "application/x-coilem-field-frame+xz"
# Shorter lists (a level's few values, a summary) stay exact in the JSON part.
MIN_ARRAY_LENGTH = 16
# xz preset 1 is about twice as fast as the default 6 for a file 4% larger.
_XZ_PRESET = 1
_ARRAY_KEY = "$array"
_STRINGS_KEY = "$strings"
_INT32 = np.iinfo(np.int32)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


_PLAIN_NUMBERS = frozenset({int, float})


def _all_numbers(values: list[Any]) -> bool:
    """``all(_is_number(value) for value in values)``, without a Python call per value.

    Frame arrays hold plain ints and floats, which the set of their types
    settles at once; anything else (bools, number subclasses) takes the slow path.
    """
    return set(map(type, values)) <= _PLAIN_NUMBERS or all(_is_number(value) for value in values)


def _all_ints(values: list[Any]) -> bool:
    kinds = set(map(type, values))
    if kinds <= {int}:
        return True
    if kinds <= _PLAIN_NUMBERS:
        return False
    return all(isinstance(value, int) for value in values)


def _numeric_dtype(values: list[Any]) -> str:
    if _all_ints(values):
        if values and _INT32.min <= min(values) and max(values) <= _INT32.max:
            return "<i4"
        return "<i8"
    return "<f4"


def _escape_key(key: str) -> str:
    # Data keys never start with "$"; doubling keeps a stray one distinct from a marker.
    return f"${key}" if key.startswith("$") else key


def _unescape_key(key: str) -> str:
    return key[1:] if key.startswith("$$") else key


class _Encoder:
    def __init__(self) -> None:
        self.arrays: list[np.ndarray] = []

    def _add(self, array: np.ndarray) -> int:
        self.arrays.append(np.ascontiguousarray(array))
        return len(self.arrays) - 1

    def encode(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {_escape_key(str(key)): self.encode(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return self._encode_list(list(value))
        return value

    def _encode_list(self, values: list[Any]) -> Any:
        if len(values) >= MIN_ARRAY_LENGTH:
            try:
                encoded = self._encode_array(values)
            except OverflowError:
                encoded = None  # integers beyond int64 stay exact as JSON
            if encoded is not None:
                return encoded
        return [self.encode(value) for value in values]

    def _encode_array(self, values: list[Any]) -> dict[str, Any] | None:
        if _all_numbers(values):
            return {_ARRAY_KEY: self._add(np.asarray(values, dtype=_numeric_dtype(values)))}
        if set(map(type, values)) == {str} or all(isinstance(value, str) for value in values):
            table = sorted(set(values))
            index = {text: position for position, text in enumerate(table)}
            dtype = "<u1" if len(table) <= 0xFF else "<u2" if len(table) <= 0xFFFF else "<u4"
            indexes = np.asarray([index[text] for text in values], dtype=dtype)
            return {_ARRAY_KEY: self._add(indexes), _STRINGS_KEY: table}
        width = len(values[0]) if isinstance(values[0], (list, tuple)) else 0
        if width and all(isinstance(row, (list, tuple)) for row in values) and set(map(len, values)) == {width}:
            flat = list(chain.from_iterable(values))
            if not _all_numbers(flat):
                return None
            array = np.asarray(flat, dtype=_numeric_dtype(flat)).reshape(len(values), width)
            return {_ARRAY_KEY: self._add(array)}
        return None


def encode_compact_field_frame(payload: dict[str, Any]) -> bytes:
    """Return ``payload`` (a JSON-compatible dict) as compact frame bytes."""

    encoder = _Encoder()
    tree = encoder.encode(payload)
    header = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "arrays": [{"dtype": array.dtype.str, "shape": list(array.shape)} for array in encoder.arrays],
            "value": tree,
        },
        separators=(",", ":"),
        allow_nan=True,
    ).encode("utf-8")
    body = b"".join([struct.pack("<Q", len(header)), header, *(array.tobytes() for array in encoder.arrays)])
    return MAGIC + lzma.compress(body, format=lzma.FORMAT_XZ, preset=_XZ_PRESET)


def decode_compact_field_frame(raw: bytes) -> dict[str, Any]:
    """Inverse of ``encode_compact_field_frame``; arrays come back as plain lists."""

    if not raw.startswith(MAGIC):
        raise ValueError("not a compact field frame")
    try:
        body = lzma.decompress(raw[len(MAGIC):], format=lzma.FORMAT_XZ)
    except lzma.LZMAError as exc:
        raise ValueError("compact field frame is corrupt") from exc
    (header_length,) = struct.unpack_from("<Q", body, 0)
    offset = 8 + header_length
    header = json.loads(body[8:offset].decode("utf-8"))
    if header.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported compact field frame schema")
    arrays: list[np.ndarray] = []
    for spec in header["arrays"]:
        dtype = np.dtype(spec["dtype"])
        shape = tuple(int(size) for size in spec["shape"])
        count = int(np.prod(shape, dtype=np.int64))
        arrays.append(np.frombuffer(body, dtype=dtype, count=count, offset=offset).reshape(shape))
        offset += count * dtype.itemsize
    if offset != len(body):
        raise ValueError("compact field frame has trailing or missing array data")

    def decode(value: Any) -> Any:
        if isinstance(value, dict):
            if _ARRAY_KEY in value:
                array = arrays[int(value[_ARRAY_KEY])]
                table = value.get(_STRINGS_KEY)
                if isinstance(table, list):
                    return [table[index] for index in array.tolist()]
                return array.tolist()
            return {_unescape_key(key): decode(child) for key, child in value.items()}
        if isinstance(value, list):
            return [decode(child) for child in value]
        return value

    payload = decode(header["value"])
    if not isinstance(payload, dict):
        raise ValueError("compact field frame does not hold an object")
    return payload


def is_compact_field_frame(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False
