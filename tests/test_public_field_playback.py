"""Publication-safe layered raster playback packaging tests."""

from __future__ import annotations

import gzip
import json
import math
import re
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

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
        "element_bx_t": [0.5 * scale, 0.0],
        "element_by_t": [0.0, 1.2 * scale],
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
    assert manifest["renderer_revision"] == "medium-b-arrows-mesh-fixed-flux-scale-v4"
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
    assert len(list((cache_dir / "field_playback").rglob("*.png"))) == 0
    assert len(list((cache_dir / "field_playback").rglob("*.webp"))) == 12
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
        # Geometry, flux density and mesh are lossless WebP (PNG's pixels at
        # under half the bytes); the field-arrow layer stays lossy WebP.
        expected_formats = {
            "geometry": ("WEBP", "image/webp"),
            "flux_density": ("WEBP", "image/webp"),
            "mesh": ("WEBP", "image/webp"),
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


def _field_arrows_source() -> str:
    return Path("frontend/src/public/fieldArrows.ts").read_text(encoding="utf-8")


def _ts_number(expression: str) -> float:
    """A TypeScript number literal or ``a / b``, as the arrow constants are written."""

    if expression.strip() == "Number.POSITIVE_INFINITY":
        return math.inf
    parts = [float(part) for part in expression.split("/")]
    return parts[0] / parts[1] if len(parts) == 2 else parts[0]


def test_playback_arrows_use_the_viewers_spacing_rings_and_fading() -> None:
    """The images' arrows are the ones a paused frame draws (frontend/src/public/fieldArrows.ts)."""

    source = _field_arrows_source()
    spacing = re.search(r"FIELD_ARROW_SPACING_FRACTION[^=]*= \{(.*?)\};", source, re.S)
    assert spacing is not None
    assert {
        name: _ts_number(value)
        for name, value in re.findall(r"(\w+): ([\d. /]+),", spacing.group(1))
    } == pytest.approx(public_field_playback.FIELD_ARROW_SPACING_FRACTION)
    length = re.search(r"FIELD_ARROW_LENGTH_FRACTION = ([\d.]+);", source)
    assert length is not None and float(length.group(1)) == public_field_playback.FIELD_ARROW_LENGTH_FRACTION
    offsets = re.search(r"FIELD_ARROW_RING_OFFSET = \{ primary: ([\d.]+), pm: ([\d.]+) \}", source)
    assert offsets is not None
    assert {"primary": float(offsets.group(1)), "pm": float(offsets.group(2))} == public_field_playback.FIELD_ARROW_RING_OFFSET
    for name in ("FIELD_ARROW_REFERENCE_PERCENTILE", "FIELD_ARROW_HIDE_BELOW_SHARE", "FIELD_ARROW_MIN_T"):
        value = re.search(rf"{name} = ([\d.e-]+);", source)
        assert value is not None and float(value.group(1)) == getattr(public_field_playback, name), name
    steps = re.search(r"FIELD_ARROW_OPACITY_STEPS[^=]*= \[(.*?)\];", source, re.S)
    assert steps is not None
    assert tuple(
        (_ts_number(upper), float(opacity))
        for upper, opacity in re.findall(r"\[([\w.]+), ([\d.]+)\]", steps.group(1))
    ) == public_field_playback.FIELD_ARROW_OPACITY_STEPS


def _disc_plot(b_at) -> dict:
    """A 64-gon disc of radius 10.2 mm as a fan about its centre (as in test-field-arrows.mjs)."""

    nodes = [[0.0, 0.0]] + [
        [10.2 * math.cos(2 * math.pi * index / 64), 10.2 * math.sin(2 * math.pi * index / 64)]
        for index in range(64)
    ]
    triangles = [[0, 1 + index, 1 + (index + 1) % 64] for index in range(64)]
    fields = [
        b_at(sum(nodes[node][0] for node in triangle) / 3, sum(nodes[node][1] for node in triangle) / 3)
        for triangle in triangles
    ]
    return {
        "nodes_mm": nodes,
        "triangles": triangles,
        "element_bx_t": [bx for bx, _ in fields],
        "element_by_t": [by for _, by in fields],
    }


def test_playback_arrows_sample_the_same_rings_as_the_viewer() -> None:
    mesh = public_field_playback._arrow_mesh(_disc_plot(lambda x, y: (0.8, 0.0)))
    assert mesh is not None
    primary = public_field_playback._sample_field_arrows(mesh, 1.0, 0.5)
    # Rings at 0.5 … 9.5 mm with round(2πr) arrows each; the PM field's at 1 … 10 mm.
    assert len(primary) == 314
    assert len(public_field_playback._sample_field_arrows(mesh, 1.0, 1.0)) == 346
    assert [(round(x, 6), round(y, 6)) for x, y, *_ in primary[:3]] == [(0.5, 0.0), (-0.25, 0.433013), (-0.25, -0.433013)]
    assert math.atan2(primary[3][1], primary[3][0]) == pytest.approx(math.pi / 9)
    assert all(
        ux == pytest.approx(1.0) and uy == pytest.approx(0.0) and b == pytest.approx(0.8) and opacity == 1.0
        for _, _, ux, uy, b, opacity in primary
    )
    assert mesh.reference_t == pytest.approx(0.8)

    circulating = public_field_playback._arrow_mesh(_disc_plot(lambda x, y: (-0.2 * y, 0.2 * x)))
    assert circulating is not None
    for x, y, ux, uy, *_ in public_field_playback._sample_field_arrows(circulating, 1.0, 0.5):
        assert abs(ux * x + uy * y) / math.hypot(x, y) < 0.06
        assert ux * -y + uy * x > 0

    quiet = public_field_playback._arrow_mesh(_disc_plot(lambda x, y: (0.01 if x > 0 else 1.0, 0.0)))
    assert quiet is not None
    assert all(x < 0.6 for x, *_ in public_field_playback._sample_field_arrows(quiet, 1.0, 0.5))
    assert public_field_playback._arrow_mesh({"nodes_mm": [[0, 0]], "triangles": [[0, 0, 0]]}) is None
    # Fading is a share of each field's strong |B|; a field with nothing in it shows nothing.
    opacity = public_field_playback._field_arrow_opacity
    assert [opacity(value, 1.0) for value in (0.01, 0.05, 0.15, 1.4)] == [0.0, 0.35, 0.65, 1.0]
    assert [opacity(0.03, 0.2), opacity(0.2, 0.2), opacity(5e-5, 1e-3)] == [0.65, 1.0, 0.0]


def test_playback_arrow_layer_draws_light_arrows_with_a_dark_rim() -> None:
    plot = _disc_plot(lambda x, y: (0.0, 1.0))
    view_box = (-10.71, -10.71, 21.42, 21.42)
    layer = public_field_playback._render_arrows(Image, ImageDraw, plot, view_box, ring_offset=0.5)
    assert layer.size == (1536, 1536)
    alpha = layer.getchannel("A")
    assert alpha.getbbox() is not None
    # The first arrow sits 0.5 spacings right of the axis, pointing up the image.
    point = public_field_playback._pixel_mapper(view_box)
    spacing = 21.42 * public_field_playback.FIELD_ARROW_SPACING_FRACTION["medium"]
    centre_x, centre_y = point(0.5 * spacing, 0.0)
    red, green, blue, opacity = layer.getpixel((round(centre_x), round(centre_y)))
    assert opacity > 200 and min(red, green, blue) > 200
    length_px = spacing * public_field_playback.FIELD_ARROW_LENGTH_FRACTION * 1536 / 21.42
    rim_red, _, _, rim_opacity = layer.getpixel((round(centre_x), round(centre_y + length_px / 2 + 1)))
    assert rim_opacity > 120 and rim_red < 80
    empty = public_field_playback._render_arrows(Image, ImageDraw, {"nodes_mm": [], "triangles": []}, view_box, ring_offset=0.5)
    assert empty.getchannel("A").getbbox() is None


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


def test_composition_reuses_the_frame_geometry_exactly(monkeypatch, tmp_path) -> None:
    """Passing the frame's own geometry renders the same layers, and the frame builds it once per plot."""

    cache_dir = tmp_path / "magneto2d-test"
    source = cache_dir / "field_line_frames" / "frame_000.json.gz"
    _write_frame(source, 0.0)
    _configure_artifact_ids(monkeypatch, cache_dir, {"source-0": source})

    plot = _plot(0.0)
    refs = {"base_ref": {"artifact_id": "base"}, "mesh_ref": {"artifact_id": "mesh"}}
    rendered = {}
    for label, geometry in (("own", None), ("shared", public_field_playback._drawable_geometry(plot))):
        output_dir = cache_dir / label
        output_dir.mkdir()
        rendered[label] = public_field_playback._render_composition(
            Image,
            ImageDraw,
            plot,
            output_dir=output_dir,
            frame_index=0,
            composition="resultant",
            geometry=geometry,
            **refs,
        )
    # Layer artifact ids name their output folder; everything else must match.
    assert json.dumps(rendered["own"]).replace("own/", "") == json.dumps(rendered["shared"]).replace("shared/", "")
    for path in (cache_dir / "own").iterdir():
        assert path.read_bytes() == (cache_dir / "shared" / path.name).read_bytes()

    built = []
    triangles = public_field_playback._triangles
    monkeypatch.setattr(
        public_field_playback,
        "_triangles",
        lambda plot, nodes: built.append(plot["element_b_mag_t"][0]) or triangles(plot, nodes),
    )
    output_dir = cache_dir / "frame"
    output_dir.mkdir()
    public_field_playback._package_playback_frame(
        0, "source-0", str(cache_dir), str(output_dir), "resultant_pm", 0.0
    )
    # The loaded plot (|B| 0.5) once; the no-load plot is on the same mesh and shares it.
    assert built == [0.5]


def test_pm_only_plot_shares_geometry_only_on_the_same_mesh() -> None:
    plot, other = _plot(0.0), _plot(0.0)
    assert public_field_playback._same_mesh(plot, other)
    # The no-load solve can place a node a few 1e-15 mm away.
    other["nodes_mm"][0][0] += 2e-15
    assert public_field_playback._same_mesh(plot, other)
    other["nodes_mm"][0][0] += 1e-6
    assert not public_field_playback._same_mesh(plot, other)
    moved = _plot(0.0)
    moved["triangles"] = [list(reversed(triangle)) for triangle in moved["triangles"]]
    assert not public_field_playback._same_mesh(plot, moved)
    assert not public_field_playback._same_mesh(plot, {"triangles": plot["triangles"]})


def test_a_frame_described_without_drawing_counts_the_same_triangles() -> None:
    plot = _plot(0.0)
    plot["triangles"] = [*plot["triangles"], [0, 1], [0, 1, 10**6], "bad"]
    nodes, _ = public_field_playback._view_geometry(plot)
    drawn = public_field_playback._triangles(plot, nodes)
    assert public_field_playback._drawable_triangle_count(plot, nodes) == len(drawn) > 0
    assert len(public_field_playback._drawable_geometry(plot, draw=False)[2]) == len(drawn)


def test_flux_colours_use_one_fixed_scale_with_magenta_above_two_tesla() -> None:
    """A single hot element no longer sets the top of the colour scale."""

    colors = public_field_playback._HEAT_COLORS
    assert public_field_playback._flux_color(0.0) == colors[0]
    assert public_field_playback._flux_color(0.24) == colors[0]
    assert public_field_playback._flux_color(1.39) == colors[5]
    assert public_field_playback._flux_color(1.99) == colors[7]
    assert public_field_playback._flux_color(2.0) == colors[7]
    assert public_field_playback._flux_color(2.64) == (244, 60, 245, 255)
    assert public_field_playback.FLUX_COLOR_SCALE == {
        "kind": "fixed",
        "min": 0.0,
        "max": 2.0,
        "over_range_color": "#f43cf5",
    }


def test_heat_layer_keeps_the_data_range_but_colours_by_the_fixed_scale() -> None:
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    plot = _plot(0.0)
    plot["element_b_mag_t"] = [0.5, 2.6]
    _, point, triangles = public_field_playback._drawable_geometry(plot)
    image, min_b, max_b = public_field_playback._render_heat(Image, ImageDraw, plot, triangles, point)

    assert (min_b, max_b) == (0.5, 2.6)
    colors = {color for _, color in image.getcolors(maxcolors=4096)}
    assert (244, 60, 245, 255) in colors
    assert public_field_playback._HEAT_COLORS[2] in colors
    # A per-frame scale would have made 0.5 T the bottom colour.
    assert public_field_playback._HEAT_COLORS[0] not in colors
