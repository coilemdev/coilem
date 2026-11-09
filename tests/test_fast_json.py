"""fast_json writes and reads the same values as json, and falls back to it."""

from __future__ import annotations

import json
import math
import random

import pytest

from backend import fast_json


def _exact(value) -> str:
    # json keeps -0.0 and every float's shortest round-trip digits, so equal
    # texts mean equal values, signs and bits included.
    return json.dumps(value, sort_keys=True)


def _random_payload(rng: random.Random, depth: int = 4):
    floats = [0.0, -0.0, 1e-05, -2.5e-310, 5e-324, 1.7976931348623157e308, 0.1, 1 / 3, -123456.789e10, 4.0e6]
    if depth == 0 or rng.random() < 0.3:
        choice = rng.random()
        if choice < 0.6:
            return rng.choice(floats) if rng.random() < 0.3 else rng.uniform(-1e3, 1e3) * 10 ** rng.randint(-12, 12)
        if choice < 0.8:
            return rng.randint(-(2**62), 2**62)
        return rng.choice(["slot_1", "é", "a\"b", "", None, True, False])
    if rng.random() < 0.5:
        return [_random_payload(rng, depth - 1) for _ in range(rng.randint(0, 6))]
    return {f"k{index}": _random_payload(rng, depth - 1) for index in range(rng.randint(0, 5))}


def test_dumps_writes_the_same_values_as_json():
    rng = random.Random(3)
    for _ in range(300):
        payload = _random_payload(rng)
        written = fast_json.dumps_bytes(payload)
        assert _exact(json.loads(written)) == _exact(payload)
        assert _exact(fast_json.loads(written)) == _exact(payload)


def test_loads_reads_the_same_values_as_json():
    rng = random.Random(9)
    for _ in range(300):
        text = json.dumps(_random_payload(rng))
        assert _exact(fast_json.loads(text)) == _exact(json.loads(text))
        assert _exact(fast_json.loads(text.encode("utf-8"))) == _exact(json.loads(text))


def test_values_orjson_does_not_handle_fall_back_to_json():
    for payload in ({1: "non-string key"}, [2**80], {"big": -(2**70)}):
        assert fast_json.dumps_bytes(payload) == json.dumps(payload).encode("utf-8")
    assert math.isnan(fast_json.loads("[NaN]")[0])
    # 64-bit integers are exact both ways; the documented exception is beyond that range.
    assert fast_json.loads("[18446744073709551615, -9223372036854775808]") == [18446744073709551615, -9223372036854775808]
    with pytest.raises(json.JSONDecodeError):
        fast_json.loads(b'{"unterminated": ')


def test_without_orjson_everything_uses_json(monkeypatch):
    monkeypatch.setattr(fast_json, "orjson", None)
    payload = {"a": [-0.0, 1e-05, 2]}
    assert fast_json.dumps_bytes(payload) == json.dumps(payload).encode("utf-8")
    assert _exact(fast_json.loads(b'{"a": [-0.0, 1e-05, 2]}')) == _exact(payload)
