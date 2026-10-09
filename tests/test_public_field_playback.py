"""Publication-safe layered raster playback packaging tests."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from backend import public_field_playback
from backend.public_field_playback_contract import (
    FieldPlaybackContractError,
    validate_field_playback_v2,
)


def _plot(angle_deg: float, scale: float = 1.0) -> dict:
    return {
        "angle_deg": angle_deg,
        "nodes_mm": [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]],
        "triangles": [[0, 1, 2], [0, 2, 3]],
        "regions": ["steel", "steel"],
        "element_b_mag_t": [0.5 * scale, 1.2 * scale],
        "contour_levels": [
            {
                "level": 0.1,
                "segments_mm": [[-0.8, 0.0, 0.8, 0.0], [0.0, -0.8, 0.0, 0.8]],
                "segment_b_mag_t": [0.5 * scale, 0.7 * scale],
                "segment_bx_t": [0.5 * scale, 0.0],
                "segment_by_t": [0.0, 0.7 * scale],
            }
        ],
        "az_min": -0.1,
        "az_max": 0.1,
        "n_pole_pitches": 2,
        "total_span_deg": 360.0,
    }


def _write_frame(path: Path, angle_deg: float) -> None:
    outer = _plot(angle_deg)
    outer["noload_plot"] = _plot(angle_deg, 0.75)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump({"field_line_frame": outer}, handle)


def _configure_artifact_ids(monkeypatch, cache_dir: Path, sources: dict[str, Path]) -> None:
    monkeypatch.setattr(
        public_field_playback,
        "resolve_solve_cache_artifact_id",
        lambda artifact_id: sources[artifact_id],
    )
    monkeypatch.setattr(
        public_field_playback,
        "encode_solve_cache_artifact_id",
        lambda path: path.resolve().relative_to(cache_dir.resolve()).as_posix(),
    )


def test_hybrid_raster_manifest_keeps_numerical_frames_for_exact_zoom_detail(
    monkeypatch,
    tmp_path,
) -> None:
    cache_dir = tmp_path / "magneto2d-test"
    first = cache_dir / "field_line_frames" / "frame_000.json.gz"
    second = cache_dir / "field_line_frames" / "frame_001.json.gz"
    _write_frame(first, 0.0)
    _write_frame(second, 15.0)
    sources = {"source-0": first, "source-1": second}
    _configure_artifact_ids(monkeypatch, cache_dir, sources)

    frames = [
        {"angle_deg": 0.0, "field_frame_artifact": {"artifact_id": "source-0"}},
        {"angle_deg": 15.0, "field_frame_artifact": {"artifact_id": "source-1"}},
    ]
    manifest, retained = public_field_playback.build_public_field_playback(
        frames,
        mode="resultant_pm",
    )

    assert manifest is not None
    assert manifest["schema_version"] == "coilem.field_playback.v2"
    assert manifest["encoding"] == "layered-raster-v1"
    assert manifest["renderer_revision"] == "medium-contours-mesh-v2"
    assert manifest["width_px"] == 1536
    assert manifest["height_px"] == 1536
    assert "detail_width_px" not in manifest
    assert "detail_height_px" not in manifest
    assert manifest["frame_count"] == 2
    assert manifest["timeline"] == {
        "kind": "angle",
        "unit": "deg_electrical",
        "loop": True,
        "direction": "increasing",
    }
    assert {layer["role"] for layer in manifest["layers"]} == {
        "geometry",
        "scalar",
        "contours",
        "annotations",
    }
    assert {composition["id"] for composition in manifest["compositions"]} == {
        "resultant",
        "pm",
    }
    assert retained == {"source-0", "source-1"}
    assert first.is_file()
    assert second.is_file()
    assert (
        cache_dir / "field_playback" / "resultant_pm" / "manifest.json"
    ).is_file()
    assert len(list((cache_dir / "field_playback").rglob("*.png"))) == 8
    assert len(list((cache_dir / "field_playback").rglob("*.webp"))) == 4
    assert manifest["numerical_snapshots"] == [
        {
            "artifact_id": "source-0",
            "media_type": "application/json+gzip",
        },
        {
            "artifact_id": "source-1",
            "media_type": "application/json+gzip",
        },
    ]

    first_frame = manifest["frames"][0]
    assert first_frame["coordinate"] == 0.0
    assert set(first_frame["compositions"]) == {"resultant", "pm"}
    for composition in first_frame["compositions"].values():
        assert composition["legend"]["unit"] == "T"
        assert composition["vector_cues"] == [
            {
                "x": 0.0,
                "y": 0.0,
                "dx": 1.0,
                "dy": 0.0,
                "magnitude": pytest.approx(composition["legend"]["max"] * 5 / 12),
            },
            {
                "x": 0.0,
                "y": 0.0,
                "dx": 0.0,
                "dy": 1.0,
                "magnitude": pytest.approx(composition["legend"]["max"] * 7 / 12),
            },
        ]
        expected_formats = {
            "geometry": ("PNG", "image/png"),
            "flux_density": ("PNG", "image/png"),
            "mesh": ("PNG", "image/png"),
            "field_lines": ("WEBP", "image/webp"),
        }
        for layer, (image_format, media_type) in expected_formats.items():
            assert composition["layers"][layer]["media_type"] == media_type
            image_path = cache_dir / composition["layers"][layer]["artifact_id"]
            with Image.open(image_path) as image:
                assert image.format == image_format
                assert image.size == (1536, 1536)
        assert "detail_layers" not in composition


def test_playback_medium_density_uses_every_second_contour_level() -> None:
    plot = _plot(0.0)
    plot["contour_levels"] = [
        {
            "level": float(index),
            "segments_mm": [[float(index), 0.0, float(index), 1.0]],
        }
        for index in range(5)
    ]

    levels = public_field_playback._contour_levels(
        plot,
        level_stride=public_field_playback.PLAYBACK_CONTOUR_LEVEL_STRIDE,
    )
    segments = public_field_playback._contour_segments(
        plot,
        level_stride=public_field_playback.PLAYBACK_CONTOUR_LEVEL_STRIDE,
    )

    assert [level["level"] for level in levels] == [0.0, 2.0, 4.0]
    assert [segment[0] for segment in segments] == [0.0, 2.0, 4.0]


def test_playback_medium_density_matches_frontend_worker_stride() -> None:
    worker_source = Path("frontend/src/public/fieldPlaybackWorker.ts").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"const MEDIUM_CONTOUR_LEVEL_STRIDE = (\d+);",
        worker_source,
    )

    assert match is not None
    assert int(match.group(1)) == public_field_playback.PLAYBACK_CONTOUR_LEVEL_STRIDE


def test_failed_packaging_keeps_every_numerical_frame(monkeypatch, tmp_path) -> None:
    cache_dir = tmp_path / "magneto2d-test"
    first = cache_dir / "field_line_frames" / "frame_000.json.gz"
    second = cache_dir / "field_line_frames" / "frame_001.json.gz"
    _write_frame(first, 0.0)
    second.parent.mkdir(parents=True, exist_ok=True)
    second.write_bytes(b"not gzip")
    sources = {"source-0": first, "source-1": second}
    _configure_artifact_ids(monkeypatch, cache_dir, sources)

    manifest, retained = public_field_playback.build_public_field_playback(
        [
            {"angle_deg": 0.0, "field_frame_artifact": {"artifact_id": "source-0"}},
            {"angle_deg": 15.0, "field_frame_artifact": {"artifact_id": "source-1"}},
        ],
        mode="resultant_pm",
    )

    assert manifest is None
    assert retained == set()
    assert first.is_file()
    assert second.is_file()
    assert not (
        cache_dir / "field_playback" / "resultant_pm" / "manifest.json"
    ).exists()


def test_v2_contract_supports_tutorial_timelines_and_arbitrary_compositions() -> None:
    artifact = {
        "artifact_id": "tutorial-lesson-01/frame-000/resultant.webp",
        "media_type": "image/webp",
        "byte_count": 128,
    }
    manifest = {
        "schema_version": "coilem.field_playback.v2",
        "encoding": "layered-webp-v1",
        "width_px": 768,
        "height_px": 768,
        "detail_width_px": 1536,
        "detail_height_px": 1536,
        "frame_count": 2,
        "timeline": {
            "kind": "time",
            "unit": "ms",
            "loop": True,
            "direction": "increasing",
        },
        "layers": [
            {
                "id": "geometry",
                "label": "Geometry",
                "role": "geometry",
                "media_type": "image/webp",
                "default_visible": True,
            },
            {
                "id": "flux_density",
                "label": "Flux density",
                "role": "scalar",
                "media_type": "image/webp",
                "default_visible": True,
                "quantity": "magnetic_flux_density",
                "unit": "T",
            },
            {
                "id": "lesson_labels",
                "label": "Lesson labels",
                "role": "annotations",
                "media_type": "image/webp",
                "default_visible": True,
            },
        ],
        "compositions": [
            {
                "id": "magnet_a",
                "label": "Magnet A",
                "description": "Field from the first permanent magnet",
            },
            {
                "id": "conductor",
                "label": "Conductor",
                "description": "Field from the energized conductor",
            },
            {
                "id": "resultant",
                "label": "Resultant",
                "description": "Combined field",
            },
        ],
        "frames": [
            {
                "index": index,
                "coordinate": coordinate,
                "compositions": {
                    "resultant": {
                        "layers": {
                            "geometry": artifact,
                            "flux_density": artifact,
                            "lesson_labels": artifact,
                        },
                        "detail_layers": {
                            "geometry": artifact,
                            "flux_density": artifact,
                            "lesson_labels": artifact,
                        },
                        "view_box": "-10 -10 20 20",
                        "vector_cues": [
                            {
                                "x": 0.0,
                                "y": 1.0,
                                "dx": 1.0,
                                "dy": 0.0,
                                "magnitude": 0.8,
                            }
                        ],
                        "legend": {
                            "label": "Flux density",
                            "quantity": "magnetic_flux_density",
                            "unit": "T",
                            "min": 0.0,
                            "max": 1.5,
                        },
                        "statistics": {"triangle_count": 24},
                    }
                },
            }
            for index, coordinate in enumerate((0.0, 50.0))
        ],
        "annotations": [
            {
                "id": "current_direction",
                "label": "Current direction",
                "frame_start": 0,
                "frame_end": 1,
            }
        ],
        "numerical_snapshots": [],
    }

    assert validate_field_playback_v2(manifest)["timeline"]["kind"] == "time"

    partial_snapshots = json.loads(json.dumps(manifest))
    partial_snapshots["numerical_snapshots"] = [
        {
            "artifact_id": "tutorial-lesson-01/frame-000/resultant.json.gz",
            "media_type": "application/json+gzip",
        }
    ]
    with pytest.raises(FieldPlaybackContractError, match="one entry per frame"):
        validate_field_playback_v2(partial_snapshots)

    broken = json.loads(json.dumps(manifest))
    broken["frames"][0]["compositions"]["resultant"]["layers"]["unknown"] = artifact
    with pytest.raises(FieldPlaybackContractError, match="unknown layers"):
        validate_field_playback_v2(broken)

    incomplete_detail = json.loads(json.dumps(manifest))
    del incomplete_detail["frames"][0]["compositions"]["resultant"][
        "detail_layers"
    ]["lesson_labels"]
    with pytest.raises(FieldPlaybackContractError, match="same layers"):
        validate_field_playback_v2(incomplete_detail)

    zero_direction = json.loads(json.dumps(manifest))
    cue = zero_direction["frames"][0]["compositions"]["resultant"]["vector_cues"][0]
    cue["dx"] = 0.0
    cue["dy"] = 0.0
    with pytest.raises(FieldPlaybackContractError, match="direction must be non-zero"):
        validate_field_playback_v2(zero_direction)
