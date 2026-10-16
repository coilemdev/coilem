"""Verify the producer opt-in projection and cache invalidation contract."""
from tools.benchmark_suite.payload_reuse import reuse_full_payload


def test_paired_payloads_preserve_values_and_reuse_expensive_builder():
    calls = []

    def original(data, *, include_raw_mesh, angle):
        calls.append((data, angle))
        payload = {"angle": angle, "contours": [data["value"] * angle]}
        if include_raw_mesh:
            payload["nodes"] = [data["value"]]
        return payload

    data = {"value": 3}
    expected_compact = original(data, include_raw_mesh=False, angle=2)
    expected_full = original(data, include_raw_mesh=True, angle=2)
    calls.clear()
    cached = reuse_full_payload(original, raw_fields={"nodes"})
    compact = cached(data, angle=2)
    full = cached(data, include_raw_mesh=True, angle=2)
    assert compact == expected_compact and full == expected_full
    assert len(calls) == 1
    full["caller_annotation"] = True
    assert cached(data, include_raw_mesh=True, angle=2) == expected_full
    assert cached.counts == {"builds": 1, "reuses": 2}


def test_changed_position_or_input_cannot_reuse_previous_field():
    calls = []

    def original(data, *, include_raw_mesh, angle):
        calls.append(angle)
        return {"angle": angle, "value": data["value"], "nodes": data}

    cached = reuse_full_payload(original, raw_fields={"nodes"})
    first = {"value": 3}
    assert cached(first, angle=1)["angle"] == 1
    assert cached(first, angle=2)["angle"] == 2
    assert cached({"value": 4}, angle=2)["value"] == 4
    # Equal values in a different mesh object still require a new build.
    assert cached({"value": 4}, angle=2)["value"] == 4
    assert len(calls) == 4


def test_incomplete_fields_remain_none_and_are_built_once():
    calls = []

    def original(data, **options):
        calls.append(data)
        return None

    cached = reuse_full_payload(original, raw_fields=())
    assert cached(None) is None
    assert cached(None, include_raw_mesh=True) is None
    assert len(calls) == 1
