"""A lesson sweep sends the mesh its frames share once."""

from __future__ import annotations

import json

from backend.tutorial_fields import encode_sweep_response


def _frame(angle: float, regions: list[str]) -> dict:
    return {
        "nodes_mm": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        "triangles": [[0, 1, 2]],
        "regions": regions,
        "electrical_angle_deg": angle,
        "az_nodal": [0.0, angle, 0.0],
    }


def test_shared_mesh_is_sent_once_and_frames_keep_their_own_data() -> None:
    sweep = {
        "fixture": "three_phase_motor",
        "frames": [_frame(0.0, ["air"]), _frame(11.25, ["air"])],
    }

    encoded = json.loads(encode_sweep_response(sweep))

    assert encoded["shared_frame_data"] == {
        "nodes_mm": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        "triangles": [[0, 1, 2]],
        "regions": ["air"],
    }
    assert [sorted(frame) for frame in encoded["frames"]] == [["az_nodal", "electrical_angle_deg"]] * 2
    assert encoded["frames"][1]["az_nodal"] == [0.0, 11.25, 0.0]
    # The caller's sweep is left as it was.
    assert "nodes_mm" in sweep["frames"][0]


def test_a_key_that_differs_between_frames_stays_on_each_frame() -> None:
    sweep = {
        "frames": [_frame(0.0, ["air"])],
        "phase_a_frames": [_frame(0.0, ["magnet"])],
    }

    encoded = json.loads(encode_sweep_response(sweep))

    assert "regions" not in encoded["shared_frame_data"]
    assert encoded["frames"][0]["regions"] == ["air"]
    assert encoded["phase_a_frames"][0]["regions"] == ["magnet"]
    assert "nodes_mm" not in encoded["phase_a_frames"][0]
