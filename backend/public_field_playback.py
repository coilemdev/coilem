"""Layered, publication-safe solved-field playback artifacts.

The native solver writes exact numerical JSON frames for diagnostics,
post-processing, and resolution-independent inspection. Browser playback uses
independently toggleable high-resolution raster layers so animation does not
need to download or rasterize those full arrays. Flat geometry and heatmap
layers use lossless PNG; detailed field lines use WebP.

One numerical frame is retained for every raster frame behind the lazy
field-frame endpoint. This keeps animation network usage lightweight while
allowing every stopped frame—not only the first angle—to switch back to exact
solver geometry when the user zooms. The retained 1536px layers and exact
frames make these artifacts deliberately larger than the former compact
pyramid; solve-cache cleanup and the durable workspace's configurable 10 GiB
limit bound storage.
"""

from __future__ import annotations

import gzip
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from backend.field_artifacts import (
    encode_solve_cache_artifact_id,
    resolve_solve_cache_artifact_id,
)
from backend.public_field_playback_contract import (
    PLAYBACK_ENCODING_LAYERED_RASTER,
    PLAYBACK_SCHEMA_V2,
    validate_field_playback_v2,
)

PLAYBACK_SCHEMA = PLAYBACK_SCHEMA_V2
PLAYBACK_ENCODING = PLAYBACK_ENCODING_LAYERED_RASTER
PLAYBACK_SIZE_PX = 1536
PLAYBACK_STYLE_REFERENCE_SIZE_PX = 768
PLAYBACK_DIRECTION_CUE_TARGET = 32
PLAYBACK_DIRECTION_CUE_LIMIT = 48
# Match the public viewer's Medium setting: render every second contour level
# into the compact animation artifact. Exact stopped frames still load the full
# numerical contour set for interactive density changes and zoom inspection.
PLAYBACK_CONTOUR_LEVEL_STRIDE = 2
PLAYBACK_RENDERER_REVISION = "medium-contours-mesh-v2"
_HEAT_COLORS = (
    (20, 42, 97, 255),
    (24, 85, 167, 255),
    (27, 142, 183, 255),
    (42, 182, 115, 255),
    (167, 200, 58, 255),
    (241, 194, 50, 255),
    (245, 139, 36, 255),
    (220, 61, 61, 255),
)

PlaybackMode = Literal["resultant_pm", "armature"]


def _payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return dict(value) if isinstance(value, dict) else {}


def _artifact_id(frame: Any) -> str | None:
    payload = _payload(frame)
    for key in ("full_field_frame_artifact", "field_frame_artifact"):
        artifact = _payload(payload.get(key))
        value = artifact.get("artifact_id")
        if isinstance(value, str) and value:
            return value
    return None


def _load_frame(artifact_id: str) -> tuple[Path, dict[str, Any]]:
    path = resolve_solve_cache_artifact_id(artifact_id)
    if (
        not path.is_file()
        or path.parent.name != "field_line_frames"
        or not path.name.endswith(".json.gz")
    ):
        raise ValueError("field playback source is not a numerical field frame")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        artifact = json.load(handle)
    frame = artifact.get("field_line_frame")
    if not isinstance(frame, dict):
        raise ValueError("field playback source has no field frame")
    return path, frame


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _view_geometry(plot: dict[str, Any]) -> tuple[
    list[list[float]],
    tuple[float, float, float, float],
]:
    nodes: list[list[float]] = []
    for raw_node in plot.get("nodes_mm") or []:
        if not isinstance(raw_node, list) or len(raw_node) < 2:
            nodes.append([])
            continue
        x = _finite_number(raw_node[0])
        y = _finite_number(raw_node[1])
        nodes.append([x, y] if x is not None and y is not None else [])
    valid_nodes = [node for node in nodes if len(node) == 2]
    if not valid_nodes:
        raise ValueError("field playback source has no drawable nodes")
    min_x = min(node[0] for node in valid_nodes)
    max_x = max(node[0] for node in valid_nodes)
    min_y = min(node[1] for node in valid_nodes)
    max_y = max(node[1] for node in valid_nodes)
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    padding = max(width, height) * 0.025
    return nodes, (
        min_x - padding,
        -max_y - padding,
        width + padding * 2.0,
        height + padding * 2.0,
    )


def _pixel_mapper(
    view_box: tuple[float, float, float, float],
    *,
    size_px: int = PLAYBACK_SIZE_PX,
) -> Any:
    view_x, view_y, view_width, view_height = view_box
    scale = min(size_px / view_width, size_px / view_height)
    offset_x = (size_px - view_width * scale) / 2.0
    offset_y = (size_px - view_height * scale) / 2.0

    def point(x: float, y: float) -> tuple[float, float]:
        return (
            offset_x + (x - view_x) * scale,
            offset_y + (-y - view_y) * scale,
        )

    return point


def _triangles(
    plot: dict[str, Any],
    nodes: list[list[float]],
) -> list[tuple[int, list[tuple[float, float]]]]:
    valid: list[tuple[int, list[tuple[float, float]]]] = []
    for index, triangle in enumerate(plot.get("triangles") or []):
        if not isinstance(triangle, list) or len(triangle) != 3:
            continue
        try:
            points = [nodes[int(node_index)] for node_index in triangle]
        except (IndexError, TypeError, ValueError):
            continue
        if any(len(point) != 2 for point in points):
            continue
        valid.append((index, [(point[0], point[1]) for point in points]))
    return valid


def _contour_levels(
    plot: dict[str, Any],
    *,
    level_stride: int = 1,
) -> list[dict[str, Any]]:
    stride = max(1, int(level_stride))
    return [
        level
        for index, level in enumerate(plot.get("contour_levels") or [])
        if index % stride == 0 and isinstance(level, dict)
    ]


def _contour_segments(
    plot: dict[str, Any],
    *,
    level_stride: int = 1,
) -> list[tuple[float, float, float, float]]:
    segments: list[tuple[float, float, float, float]] = []
    for level in _contour_levels(plot, level_stride=level_stride):
        for segment in level.get("segments_mm") or []:
            if not isinstance(segment, list) or len(segment) < 4:
                continue
            values = [_finite_number(value) for value in segment[:4]]
            if any(value is None for value in values):
                continue
            segments.append((values[0], values[1], values[2], values[3]))  # type: ignore[arg-type]
    return segments


def _direction_cues(
    plot: dict[str, Any],
    *,
    level_stride: int = 1,
) -> list[dict[str, float]]:
    """Sample physics-derived B-vector cues without retaining full contour arrays."""

    candidates_by_level: list[list[dict[str, float]]] = []
    for level in _contour_levels(plot, level_stride=level_stride):
        if not isinstance(level, dict):
            continue
        segments = level.get("segments_mm") or []
        bx_values = level.get("segment_bx_t") or []
        by_values = level.get("segment_by_t") or []
        magnitude_values = level.get("segment_b_mag_t") or []
        candidates: list[dict[str, float]] = []
        for index, segment in enumerate(segments):
            if (
                not isinstance(segment, list)
                or len(segment) < 4
                or index >= len(bx_values)
                or index >= len(by_values)
            ):
                continue
            coordinates = [_finite_number(value) for value in segment[:4]]
            bx = _finite_number(bx_values[index])
            by = _finite_number(by_values[index])
            if any(value is None for value in coordinates) or bx is None or by is None:
                continue
            vector_length = math.hypot(bx, by)
            if vector_length <= 1e-12:
                continue
            magnitude = (
                _finite_number(magnitude_values[index])
                if index < len(magnitude_values)
                else vector_length
            )
            x1, y1, x2, y2 = coordinates
            candidates.append(
                {
                    "x": round((x1 + x2) * 0.5, 4),  # type: ignore[operator]
                    "y": round((y1 + y2) * 0.5, 4),  # type: ignore[operator]
                    "dx": round(bx / vector_length, 6),
                    "dy": round(by / vector_length, 6),
                    "magnitude": round(
                        magnitude if magnitude is not None else vector_length,
                        6,
                    ),
                }
            )
        if candidates:
            candidates_by_level.append(candidates)

    if not candidates_by_level:
        return []

    target = min(
        PLAYBACK_DIRECTION_CUE_LIMIT,
        max(1, PLAYBACK_DIRECTION_CUE_TARGET),
    )
    per_level = max(1, target // len(candidates_by_level))
    selected: list[dict[str, float]] = []
    selected_ids: set[int] = set()
    for candidates in candidates_by_level:
        count = min(per_level, len(candidates))
        if count == 1:
            indices = [len(candidates) // 2]
        else:
            indices = [
                round(index * (len(candidates) - 1) / (count - 1))
                for index in range(count)
            ]
        for index in indices:
            candidate = candidates[index]
            selected.append(candidate)
            selected_ids.add(id(candidate))

    remaining = [
        candidate
        for candidates in candidates_by_level
        for candidate in candidates
        if id(candidate) not in selected_ids
    ]
    if remaining and len(selected) < target:
        needed = min(target - len(selected), len(remaining))
        if needed == 1:
            fill_indices = [len(remaining) // 2]
        else:
            fill_indices = [
                round(index * (len(remaining) - 1) / (needed - 1))
                for index in range(needed)
            ]
        selected.extend(remaining[index] for index in fill_indices)
    return selected[:target]


def _save_webp(image: Any, path: Path, *, quality: int) -> dict[str, Any]:
    temporary = path.with_name(f".{path.name}.tmp")
    image.save(
        temporary,
        format="WEBP",
        quality=quality,
        method=2,
        exact=True,
    )
    temporary.replace(path)
    return {
        "artifact_id": encode_solve_cache_artifact_id(path),
        "media_type": "image/webp",
        "byte_count": path.stat().st_size,
    }


def _save_png(image: Any, path: Path) -> dict[str, Any]:
    temporary = path.with_name(f".{path.name}.tmp")
    image.save(
        temporary,
        format="PNG",
        compress_level=6,
    )
    temporary.replace(path)
    return {
        "artifact_id": encode_solve_cache_artifact_id(path),
        "media_type": "image/png",
        "byte_count": path.stat().st_size,
    }


def _render_base(
    image_module: Any,
    image_draw_module: Any,
    triangles: list[tuple[int, list[tuple[float, float]]]],
    point: Any,
    *,
    size_px: int = PLAYBACK_SIZE_PX,
) -> Any:
    image = image_module.new(
        "RGBA",
        (size_px, size_px),
        (0, 0, 0, 0),
    )
    draw = image_draw_module.Draw(image, "RGBA")
    for _, triangle in triangles:
        pixels = [point(x, y) for x, y in triangle]
        draw.polygon(pixels, fill=(32, 39, 51, 255), outline=(47, 57, 72, 105))
    return image


def _render_mesh(
    image_module: Any,
    image_draw_module: Any,
    triangles: list[tuple[int, list[tuple[float, float]]]],
    point: Any,
    *,
    size_px: int = PLAYBACK_SIZE_PX,
) -> Any:
    """Render solver-element edges on a transparent layer.

    Keeping this separate from the geometry and scalar layers lets the public
    viewer place the triangulation above the flux-density heatmap.
    """

    image = image_module.new(
        "RGBA",
        (size_px, size_px),
        (0, 0, 0, 0),
    )
    draw = image_draw_module.Draw(image, "RGBA")
    line_scale = size_px / PLAYBACK_STYLE_REFERENCE_SIZE_PX
    for _, triangle in triangles:
        pixels = [point(x, y) for x, y in triangle]
        draw.line(
            [*pixels, pixels[0]],
            fill=(203, 213, 225, 105),
            width=max(1, round(0.65 * line_scale)),
            joint="curve",
        )
    return image


def _render_heat(
    image_module: Any,
    image_draw_module: Any,
    plot: dict[str, Any],
    triangles: list[tuple[int, list[tuple[float, float]]]],
    point: Any,
    *,
    size_px: int = PLAYBACK_SIZE_PX,
) -> tuple[Any, float, float]:
    values = plot.get("element_b_mag_t") or []
    finite_values = [
        number
        for value in values
        if (number := _finite_number(value)) is not None
    ]
    min_b = min(finite_values, default=0.0)
    max_b = max(finite_values, default=0.0)
    span = max(max_b - min_b, float.fromhex("0x1.0p-52"))
    image = image_module.new(
        "RGBA",
        (size_px, size_px),
        (0, 0, 0, 0),
    )
    draw = image_draw_module.Draw(image, "RGBA")
    for index, triangle in triangles:
        if index >= len(values):
            continue
        value = _finite_number(values[index])
        if value is None:
            continue
        bucket = min(
            len(_HEAT_COLORS) - 1,
            max(0, int(((value - min_b) / span) * len(_HEAT_COLORS))),
        )
        draw.polygon(
            [point(x, y) for x, y in triangle],
            fill=_HEAT_COLORS[bucket],
        )
    return image, min_b, max_b


def _render_lines(
    image_module: Any,
    image_draw_module: Any,
    image_filter_module: Any,
    segments: list[tuple[float, float, float, float]],
    point: Any,
    *,
    size_px: int = PLAYBACK_SIZE_PX,
) -> Any:
    glow = image_module.new(
        "RGBA",
        (size_px, size_px),
        (0, 0, 0, 0),
    )
    core = image_module.new(
        "RGBA",
        (size_px, size_px),
        (0, 0, 0, 0),
    )
    glow_draw = image_draw_module.Draw(glow, "RGBA")
    core_draw = image_draw_module.Draw(core, "RGBA")
    line_scale = size_px / PLAYBACK_STYLE_REFERENCE_SIZE_PX
    for x1, y1, x2, y2 in segments:
        pixels = [point(x1, y1), point(x2, y2)]
        glow_draw.line(
            pixels,
            fill=(255, 145, 0, 135),
            width=max(1, round(4 * line_scale)),
        )
        core_draw.line(
            pixels,
            fill=(255, 209, 102, 245),
            width=max(1, round(line_scale)),
        )
    glow = glow.filter(
        image_filter_module.GaussianBlur(
            radius=0.9 * size_px / PLAYBACK_STYLE_REFERENCE_SIZE_PX
        )
    )
    glow.alpha_composite(core)
    return glow


def _render_composition(
    image_module: Any,
    image_draw_module: Any,
    image_filter_module: Any,
    plot: dict[str, Any],
    *,
    output_dir: Path,
    frame_index: int,
    composition: str,
    base_ref: dict[str, Any],
    mesh_ref: dict[str, Any],
) -> dict[str, Any]:
    nodes, view_box = _view_geometry(plot)
    point = _pixel_mapper(view_box)
    triangles = _triangles(plot, nodes)
    if not triangles:
        raise ValueError("field playback source has no drawable triangles")
    heat, min_b, max_b = _render_heat(
        image_module,
        image_draw_module,
        plot,
        triangles,
        point,
    )
    contour_levels = _contour_levels(
        plot,
        level_stride=PLAYBACK_CONTOUR_LEVEL_STRIDE,
    )
    segments = _contour_segments(
        plot,
        level_stride=PLAYBACK_CONTOUR_LEVEL_STRIDE,
    )
    lines = _render_lines(
        image_module,
        image_draw_module,
        image_filter_module,
        segments,
        point,
    )
    heat_ref = _save_png(
        heat,
        output_dir / f"frame_{frame_index:04d}_{composition}_flux.png",
    )
    lines_ref = _save_webp(
        lines,
        output_dir / f"frame_{frame_index:04d}_{composition}_lines.webp",
        quality=90,
    )
    return {
        "layers": {
            "geometry": base_ref,
            "flux_density": heat_ref,
            "mesh": mesh_ref,
            "field_lines": lines_ref,
        },
        "vector_cues": _direction_cues(
            plot,
            level_stride=PLAYBACK_CONTOUR_LEVEL_STRIDE,
        ),
        "view_box": " ".join(f"{value:.9g}" for value in view_box),
        "legend": {
            "label": "Flux density",
            "quantity": "magnetic_flux_density",
            "unit": "T",
            "min": min_b,
            "max": max_b,
        },
        "statistics": {
            "triangle_count": len(triangles),
            "contour_level_count": len(contour_levels),
            "contour_segment_count": len(segments),
        },
    }


def _layer_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": "geometry",
            "label": "Geometry",
            "role": "geometry",
            "media_type": "image/png",
            "default_visible": True,
        },
        {
            "id": "flux_density",
            "label": "Flux density",
            "role": "scalar",
            "media_type": "image/png",
            "default_visible": True,
            "quantity": "magnetic_flux_density",
            "unit": "T",
        },
        {
            "id": "field_lines",
            "label": "Field lines",
            "role": "contours",
            "media_type": "image/webp",
            "default_visible": True,
            "quantity": "magnetic_vector_potential",
            "unit": "Wb/m",
        },
        {
            "id": "mesh",
            "label": "Mesh",
            "role": "annotations",
            "media_type": "image/png",
            "default_visible": False,
        },
    ]


def _composition_catalog(composition_ids: set[str]) -> list[dict[str, Any]]:
    definitions = {
        "armature": {
            "id": "armature",
            "label": "Stator only",
            "description": "Exact zero-remanence current-produced field",
        },
        "resultant": {
            "id": "resultant",
            "label": "Resultant",
            "description": "Permanent-magnet and applied-current field",
        },
        "pm": {
            "id": "pm",
            "label": "PM only",
            "description": "Exact zero-current permanent-magnet field",
        },
    }
    return [
        definitions.get(
            composition_id,
            {"id": composition_id, "label": composition_id.replace("_", " ").title()},
        )
        for composition_id in sorted(composition_ids)
    ]


def _existing_manifest(manifest_path: Path) -> tuple[dict[str, Any] | None, set[str]]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, set()
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != PLAYBACK_SCHEMA
        or payload.get("encoding") != PLAYBACK_ENCODING
        or payload.get("renderer_revision") != PLAYBACK_RENDERER_REVISION
    ):
        return None, set()
    try:
        validate_field_playback_v2(payload)
    except ValueError:
        return None, set()
    snapshots = payload.get("numerical_snapshots")
    retained = {
        artifact_id
        for snapshot in (snapshots if isinstance(snapshots, list) else [])
        if isinstance(snapshot, dict)
        if isinstance((artifact_id := snapshot.get("artifact_id")), str)
    }
    return payload, retained


def build_public_field_playback(
    frames: Any,
    *,
    mode: PlaybackMode,
) -> tuple[dict[str, Any] | None, set[str]]:
    """Build hybrid raster playback and return its manifest and numerical JSON ids.

    If any source or render step fails, ``None`` is returned so callers can
    continue through the numerical-frame fallback.
    """

    frame_values = list(frames) if isinstance(frames, (list, tuple)) else []
    source_ids = [
        artifact_id
        for frame in frame_values
        if (artifact_id := _artifact_id(frame)) is not None
    ]
    if not source_ids:
        return None, set()

    try:
        first_source_path = resolve_solve_cache_artifact_id(source_ids[0])
        cache_dir = first_source_path.parent.parent
        output_dir = cache_dir / "field_playback" / mode
        manifest_path = output_dir / "manifest.json"
        existing, retained = _existing_manifest(manifest_path)
        if existing is not None:
            return existing, retained

        from PIL import Image, ImageDraw, ImageFilter  # type: ignore

        output_dir.mkdir(parents=True, exist_ok=True)
        def package_frame(
            indexed_source: tuple[int, str],
        ) -> tuple[Path, dict[str, Any]]:
            frame_index, artifact_id = indexed_source
            source_path, outer = _load_frame(artifact_id)
            if source_path.parent.parent != cache_dir:
                raise ValueError("field playback frames span multiple solve caches")
            nodes, view_box = _view_geometry(outer)
            point = _pixel_mapper(view_box)
            triangles = _triangles(outer, nodes)
            if not triangles:
                raise ValueError("field playback source has no drawable triangles")
            base = _render_base(Image, ImageDraw, triangles, point)
            base_ref = _save_png(
                base,
                output_dir / f"frame_{frame_index:04d}_base.png",
            )
            mesh = _render_mesh(Image, ImageDraw, triangles, point)
            mesh_ref = _save_png(
                mesh,
                output_dir / f"frame_{frame_index:04d}_mesh.png",
            )
            compositions: dict[str, Any] = {
                "armature" if mode == "armature" else "resultant": _render_composition(
                    Image,
                    ImageDraw,
                    ImageFilter,
                    outer,
                    output_dir=output_dir,
                    frame_index=frame_index,
                    composition="armature" if mode == "armature" else "resultant",
                    base_ref=base_ref,
                    mesh_ref=mesh_ref,
                )
            }
            if mode == "resultant_pm":
                pm_plot = outer.get("noload_plot")
                if isinstance(pm_plot, dict):
                    compositions["pm"] = _render_composition(
                        Image,
                        ImageDraw,
                        ImageFilter,
                        pm_plot,
                        output_dir=output_dir,
                        frame_index=frame_index,
                        composition="pm",
                        base_ref=base_ref,
                        mesh_ref=mesh_ref,
                    )
            frame_payload = _payload(frame_values[frame_index])
            return source_path, {
                "index": frame_index,
                "coordinate": float(frame_payload.get("angle_deg", 0.0)),
                "compositions": compositions,
            }

        workers = min(4, len(source_ids))
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="coilem-field-playback",
        ) as executor:
            packaged = list(executor.map(package_frame, enumerate(source_ids)))
        manifest_frames = [frame for _, frame in packaged]
        expected_compositions = set(manifest_frames[0]["compositions"])
        if any(
            set(frame["compositions"]) != expected_compositions
            for frame in manifest_frames[1:]
        ):
            raise ValueError("field playback compositions are not aligned")

        manifest = {
            "schema_version": PLAYBACK_SCHEMA,
            "encoding": PLAYBACK_ENCODING,
            "renderer_revision": PLAYBACK_RENDERER_REVISION,
            "width_px": PLAYBACK_SIZE_PX,
            "height_px": PLAYBACK_SIZE_PX,
            "frame_count": len(manifest_frames),
            "timeline": {
                "kind": "angle",
                "unit": "deg_electrical",
                "loop": True,
                "direction": "increasing",
            },
            "layers": _layer_catalog(),
            "compositions": _composition_catalog(expected_compositions),
            "frames": manifest_frames,
            "annotations": [],
            "numerical_snapshots": [
                {
                    "artifact_id": artifact_id,
                    "media_type": "application/json+gzip",
                }
                for artifact_id in source_ids
            ],
            "manifest_artifact_id": encode_solve_cache_artifact_id(manifest_path),
        }
        validate_field_playback_v2(manifest)
        manifest_path_tmp = manifest_path.with_name(".manifest.json.tmp")
        manifest_path_tmp.write_text(
            json.dumps(manifest, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
        manifest_path_tmp.replace(manifest_path)

        retained = set(source_ids)
        return manifest, retained
    except Exception:
        return None, set()
