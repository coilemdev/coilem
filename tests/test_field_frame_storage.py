"""Stored field frames keep the PM-only plot's mesh once, and read back whole."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from PIL import Image

from backend import field_artifacts, public_field_playback
from backend.field_artifacts import (
    NOLOAD_MESH_FROM_FRAME,
    read_field_line_frame_artifact,
    restore_noload_mesh,
    write_field_line_frame_artifact,
)


def _plot(scale: float) -> dict[str, object]:
    return {
        "nodes_mm": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
        "triangles": [[0, 1, 2], [1, 3, 2]],
        "regions": ["stator_steel", "airgap"],
        "element_b_mag_t": [0.4 * scale, 0.9 * scale],
        "element_bx_t": [0.1 * scale, 0.2 * scale],
        "element_by_t": [0.3 * scale, 0.8 * scale],
        "contour_levels": [{"level": 0.0, "segments_mm": [[0.0, 0.0, 1.0, 1.0]]}],
    }


def _frame() -> dict[str, object]:
    return {**_plot(1.0), "noload_plot": _plot(0.75)}


def _stored(path: Path) -> dict[str, object]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    cache = field_artifacts.solve_cache_root() / "magneto2d-test"
    cache.mkdir(parents=True)
    return cache


def test_pm_only_plot_stores_the_frame_mesh_once_and_reads_back_whole(cache_dir: Path) -> None:
    frame = _frame()
    ref = write_field_line_frame_artifact(frame, cache_dir, pos_idx=3, elec_angle_deg=45.0)
    assert ref is not None
    path = field_artifacts.resolve_solve_cache_artifact_id(ref["artifact_id"])

    stored_noload = _stored(path)["field_line_frame"]["noload_plot"]
    assert stored_noload[NOLOAD_MESH_FROM_FRAME] == ["nodes_mm", "triangles", "regions"]
    for key in ("nodes_mm", "triangles", "regions"):
        assert key not in stored_noload
    assert stored_noload["element_b_mag_t"] == frame["noload_plot"]["element_b_mag_t"]

    assert read_field_line_frame_artifact(path)["field_line_frame"] == frame
    # The caller's frame is not changed by writing it.
    assert frame == _frame()


def test_pm_only_nodes_that_differ_in_the_last_digit_stay_as_solved(cache_dir: Path) -> None:
    """The no-load solve can place nodes 1e-15 off the loaded frame's; keep them exact."""

    frame = _frame()
    frame["noload_plot"]["nodes_mm"] = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0000000000000002], [1.0, 1.0]]
    ref = write_field_line_frame_artifact(frame, cache_dir, pos_idx=0, elec_angle_deg=0.0)
    path = field_artifacts.resolve_solve_cache_artifact_id(ref["artifact_id"])

    stored_noload = _stored(path)["field_line_frame"]["noload_plot"]
    assert stored_noload[NOLOAD_MESH_FROM_FRAME] == ["triangles", "regions"]
    assert stored_noload["nodes_mm"] == frame["noload_plot"]["nodes_mm"]
    assert "triangles" not in stored_noload
    assert read_field_line_frame_artifact(path)["field_line_frame"] == frame


def test_pm_only_plot_on_its_own_mesh_is_stored_in_full(cache_dir: Path) -> None:
    frame = _frame()
    for key, value in (("nodes_mm", [[0.0, 0.0], [2.0, 0.0], [0.0, 2.0]]), ("triangles", [[0, 1, 2]]), ("regions", ["airgap"])):
        frame["noload_plot"][key] = value
    ref = write_field_line_frame_artifact(frame, cache_dir, pos_idx=0, elec_angle_deg=0.0)
    path = field_artifacts.resolve_solve_cache_artifact_id(ref["artifact_id"])

    stored_noload = _stored(path)["field_line_frame"]["noload_plot"]
    assert NOLOAD_MESH_FROM_FRAME not in stored_noload
    assert stored_noload["nodes_mm"] == frame["noload_plot"]["nodes_mm"]
    assert read_field_line_frame_artifact(path)["field_line_frame"] == frame


def test_frames_stored_before_sharing_read_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "pos000_0p000deg_field_frame.json.gz"
    payload = {"schema_version": "openem.field_line_frame.v1", "field_line_frame": _frame()}
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)

    assert read_field_line_frame_artifact(path) == payload
    assert restore_noload_mesh(_frame()) == _frame()


def test_pm_playback_layer_renders_from_a_shared_mesh_frame(cache_dir: Path) -> None:
    frame = _frame()
    ref = write_field_line_frame_artifact(frame, cache_dir, pos_idx=1, elec_angle_deg=15.0)
    path, loaded = public_field_playback._load_frame(ref["artifact_id"])

    assert path.is_file()
    assert loaded["noload_plot"]["nodes_mm"] == frame["nodes_mm"]
    assert loaded["noload_plot"]["triangles"] == frame["triangles"]


def test_lossless_webp_layer_keeps_every_pixel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    cache = field_artifacts.solve_cache_root()
    cache.mkdir(parents=True)
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for x in range(64):
        image.putpixel((x, x), (245, 158, 11, 128 + x))
    ref = public_field_playback._save_lossless_webp(image, cache / "layer.webp")

    assert ref["media_type"] == "image/webp"
    with Image.open(cache / "layer.webp") as stored:
        assert stored.format == "WEBP"
        assert stored.convert("RGBA").tobytes() == image.tobytes()
