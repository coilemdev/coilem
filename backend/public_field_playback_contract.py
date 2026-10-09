"""Generic, publication-safe contract for cached 2D field playback."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

PLAYBACK_SCHEMA_V2 = "coilem.field_playback.v2"
PLAYBACK_ENCODING_LAYERED_WEBP = "layered-webp-v1"
PLAYBACK_ENCODING_LAYERED_RASTER = "layered-raster-v1"
PLAYBACK_ENCODINGS = frozenset(
    {
        PLAYBACK_ENCODING_LAYERED_WEBP,
        PLAYBACK_ENCODING_LAYERED_RASTER,
    }
)
PLAYBACK_MEDIA_TYPES = frozenset({"image/png", "image/webp"})

TIMELINE_KINDS = frozenset({"angle", "time", "phase", "step"})
LAYER_ROLES = frozenset(
    {"geometry", "scalar", "contours", "vectors", "annotations"}
)
MAX_VECTOR_CUES_PER_VISUAL = 128


class FieldPlaybackContractError(ValueError):
    """Raised when a generic playback manifest violates the public contract."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FieldPlaybackContractError(f"{field} must be an object")
    return value


def _sequence(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise FieldPlaybackContractError(f"{field} must be an array")
    return value


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not value.replace("_", "").replace("-", "").isalnum()
    ):
        raise FieldPlaybackContractError(
            f"{field} must be a non-empty alphanumeric identifier"
        )
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FieldPlaybackContractError(f"{field} must be non-empty text")
    return value


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FieldPlaybackContractError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise FieldPlaybackContractError(f"{field} must be finite")
    return number


def _catalog_ids(
    values: Any,
    field: str,
    *,
    allowed_roles: frozenset[str] | None = None,
) -> set[str]:
    ids: set[str] = set()
    for index, item_value in enumerate(_sequence(values, field)):
        item = _mapping(item_value, f"{field}[{index}]")
        item_id = _identifier(item.get("id"), f"{field}[{index}].id")
        if item_id in ids:
            raise FieldPlaybackContractError(f"{field} contains duplicate id {item_id!r}")
        _text(item.get("label"), f"{field}[{index}].label")
        if allowed_roles is not None:
            role = item.get("role")
            if role not in allowed_roles:
                raise FieldPlaybackContractError(
                    f"{field}[{index}].role must be one of {sorted(allowed_roles)}"
                )
            if item.get("media_type") not in PLAYBACK_MEDIA_TYPES:
                raise FieldPlaybackContractError(
                    f"{field}[{index}].media_type must be one of "
                    f"{sorted(PLAYBACK_MEDIA_TYPES)}"
                )
            if not isinstance(item.get("default_visible"), bool):
                raise FieldPlaybackContractError(
                    f"{field}[{index}].default_visible must be boolean"
                )
            for optional_text in ("quantity", "unit"):
                if item.get(optional_text) is not None:
                    _text(item[optional_text], f"{field}[{index}].{optional_text}")
        elif item.get("description") is not None:
            _text(item["description"], f"{field}[{index}].description")
        ids.add(item_id)
    if not ids:
        raise FieldPlaybackContractError(f"{field} must not be empty")
    return ids


def validate_field_playback_v2(manifest_value: Any) -> dict[str, Any]:
    """Validate a generic v2 manifest and return its plain dictionary."""

    manifest = _mapping(manifest_value, "manifest")
    if manifest.get("schema_version") != PLAYBACK_SCHEMA_V2:
        raise FieldPlaybackContractError(
            f"schema_version must be {PLAYBACK_SCHEMA_V2!r}"
        )
    if manifest.get("encoding") not in PLAYBACK_ENCODINGS:
        raise FieldPlaybackContractError(
            f"encoding must be one of {sorted(PLAYBACK_ENCODINGS)}"
        )
    width = int(_finite(manifest.get("width_px"), "width_px"))
    height = int(_finite(manifest.get("height_px"), "height_px"))
    if width <= 0 or height <= 0:
        raise FieldPlaybackContractError("playback dimensions must be positive")
    detail_width_value = manifest.get("detail_width_px")
    detail_height_value = manifest.get("detail_height_px")
    if (detail_width_value is None) != (detail_height_value is None):
        raise FieldPlaybackContractError(
            "detail playback dimensions must be provided together"
        )
    if detail_width_value is not None and detail_height_value is not None:
        detail_width = int(_finite(detail_width_value, "detail_width_px"))
        detail_height = int(_finite(detail_height_value, "detail_height_px"))
        if detail_width < width or detail_height < height:
            raise FieldPlaybackContractError(
                "detail playback dimensions must not be smaller than playback dimensions"
            )

    timeline = _mapping(manifest.get("timeline"), "timeline")
    if timeline.get("kind") not in TIMELINE_KINDS:
        raise FieldPlaybackContractError(
            f"timeline.kind must be one of {sorted(TIMELINE_KINDS)}"
        )
    _text(timeline.get("unit"), "timeline.unit")
    if not isinstance(timeline.get("loop"), bool):
        raise FieldPlaybackContractError("timeline.loop must be boolean")
    direction = timeline.get("direction")
    if direction is not None and direction not in {"increasing", "decreasing"}:
        raise FieldPlaybackContractError(
            "timeline.direction must be 'increasing' or 'decreasing'"
        )

    layers = _sequence(manifest.get("layers"), "layers")
    layer_ids = _catalog_ids(
        layers,
        "layers",
        allowed_roles=LAYER_ROLES,
    )
    layer_media_types = {
        str(_mapping(layer, f"layers[{index}]").get("id")): str(
            _mapping(layer, f"layers[{index}]").get("media_type")
        )
        for index, layer in enumerate(layers)
    }
    composition_ids = _catalog_ids(manifest.get("compositions"), "compositions")

    frames = _sequence(manifest.get("frames"), "frames")
    if int(_finite(manifest.get("frame_count"), "frame_count")) != len(frames):
        raise FieldPlaybackContractError("frame_count does not match frames")
    if not frames:
        raise FieldPlaybackContractError("frames must not be empty")

    seen_indices: set[int] = set()
    previous_coordinate: float | None = None
    direction = timeline.get("direction", "increasing")
    for frame_position, frame_value in enumerate(frames):
        frame = _mapping(frame_value, f"frames[{frame_position}]")
        index = int(_finite(frame.get("index"), f"frames[{frame_position}].index"))
        if index in seen_indices:
            raise FieldPlaybackContractError(f"duplicate frame index {index}")
        seen_indices.add(index)
        coordinate = _finite(
            frame.get("coordinate"),
            f"frames[{frame_position}].coordinate",
        )
        if frame.get("duration_ms") is not None and _finite(
            frame["duration_ms"],
            f"frames[{frame_position}].duration_ms",
        ) <= 0:
            raise FieldPlaybackContractError("frame duration_ms must be positive")
        if previous_coordinate is not None:
            if direction == "increasing" and coordinate < previous_coordinate:
                raise FieldPlaybackContractError("frame coordinates must be increasing")
            if direction == "decreasing" and coordinate > previous_coordinate:
                raise FieldPlaybackContractError("frame coordinates must be decreasing")
        previous_coordinate = coordinate

        frame_compositions = _mapping(
            frame.get("compositions"),
            f"frames[{frame_position}].compositions",
        )
        if not frame_compositions:
            raise FieldPlaybackContractError(
                f"frames[{frame_position}].compositions must not be empty"
            )
        unknown_compositions = set(frame_compositions) - composition_ids
        if unknown_compositions:
            raise FieldPlaybackContractError(
                f"frame references unknown compositions {sorted(unknown_compositions)}"
            )
        for composition_id, visual_value in frame_compositions.items():
            visual = _mapping(
                visual_value,
                f"frames[{frame_position}].compositions.{composition_id}",
            )
            artifacts = _mapping(
                visual.get("layers"),
                f"frames[{frame_position}].compositions.{composition_id}.layers",
            )
            if not artifacts:
                raise FieldPlaybackContractError(
                    f"composition {composition_id!r} has no layers"
                )
            unknown_layers = set(artifacts) - layer_ids
            if unknown_layers:
                raise FieldPlaybackContractError(
                    f"composition references unknown layers {sorted(unknown_layers)}"
                )
            for layer_id, artifact_value in artifacts.items():
                artifact = _mapping(
                    artifact_value,
                    f"frames[{frame_position}].layers.{layer_id}",
                )
                _text(
                    artifact.get("artifact_id"),
                    f"frames[{frame_position}].layers.{layer_id}.artifact_id",
                )
                if artifact.get("media_type") != layer_media_types[layer_id]:
                    raise FieldPlaybackContractError(
                        f"frames[{frame_position}].layers.{layer_id}.media_type "
                        "must match its layer definition"
                    )
                if _finite(
                    artifact.get("byte_count"),
                    f"frames[{frame_position}].layers.{layer_id}.byte_count",
                ) < 0:
                    raise FieldPlaybackContractError("artifact byte_count must be non-negative")

            detail_artifacts_value = visual.get("detail_layers")
            if detail_artifacts_value is not None:
                detail_artifacts = _mapping(
                    detail_artifacts_value,
                    (
                        f"frames[{frame_position}].compositions."
                        f"{composition_id}.detail_layers"
                    ),
                )
                if set(detail_artifacts) != set(artifacts):
                    raise FieldPlaybackContractError(
                        "detail_layers must provide the same layers as layers"
                    )
                for layer_id, artifact_value in detail_artifacts.items():
                    artifact = _mapping(
                        artifact_value,
                        (
                            f"frames[{frame_position}].compositions."
                            f"{composition_id}.detail_layers.{layer_id}"
                        ),
                    )
                    _text(
                        artifact.get("artifact_id"),
                        (
                            f"frames[{frame_position}].detail_layers."
                            f"{layer_id}.artifact_id"
                        ),
                    )
                    if artifact.get("media_type") != layer_media_types[layer_id]:
                        raise FieldPlaybackContractError(
                            "detail playback layer media_type must match its "
                            "layer definition"
                        )
                    if _finite(
                        artifact.get("byte_count"),
                        (
                            f"frames[{frame_position}].detail_layers."
                            f"{layer_id}.byte_count"
                        ),
                    ) < 0:
                        raise FieldPlaybackContractError(
                            "detail artifact byte_count must be non-negative"
                        )

            view_box = _text(
                visual.get("view_box"),
                f"frames[{frame_position}].compositions.{composition_id}.view_box",
            )
            if len(view_box.split()) != 4:
                raise FieldPlaybackContractError("view_box must contain four numbers")
            for view_index, value in enumerate(view_box.split()):
                _finite(value, f"view_box[{view_index}]")

            legend_value = visual.get("legend")
            if legend_value is not None:
                legend = _mapping(legend_value, "legend")
                _text(legend.get("label"), "legend.label")
                _text(legend.get("unit"), "legend.unit")
                minimum = _finite(legend.get("min"), "legend.min")
                maximum = _finite(legend.get("max"), "legend.max")
                if maximum < minimum:
                    raise FieldPlaybackContractError("legend.max must be >= legend.min")

            vector_cues = _sequence(
                visual.get("vector_cues", []),
                f"frames[{frame_position}].compositions.{composition_id}.vector_cues",
            )
            if len(vector_cues) > MAX_VECTOR_CUES_PER_VISUAL:
                raise FieldPlaybackContractError(
                    f"vector_cues must contain at most {MAX_VECTOR_CUES_PER_VISUAL} items"
                )
            for cue_index, cue_value in enumerate(vector_cues):
                cue = _mapping(
                    cue_value,
                    (
                        f"frames[{frame_position}].compositions."
                        f"{composition_id}.vector_cues[{cue_index}]"
                    ),
                )
                prefix = (
                    f"frames[{frame_position}].compositions."
                    f"{composition_id}.vector_cues[{cue_index}]"
                )
                _finite(cue.get("x"), f"{prefix}.x")
                _finite(cue.get("y"), f"{prefix}.y")
                dx = _finite(cue.get("dx"), f"{prefix}.dx")
                dy = _finite(cue.get("dy"), f"{prefix}.dy")
                if math.hypot(dx, dy) <= 1e-12:
                    raise FieldPlaybackContractError(
                        f"{prefix} direction must be non-zero"
                    )
                if cue.get("magnitude") is not None and _finite(
                    cue["magnitude"],
                    f"{prefix}.magnitude",
                ) < 0:
                    raise FieldPlaybackContractError(
                        f"{prefix}.magnitude must be non-negative"
                    )

    for annotation_index, annotation_value in enumerate(
        _sequence(manifest.get("annotations", []), "annotations")
    ):
        annotation = _mapping(
            annotation_value,
            f"annotations[{annotation_index}]",
        )
        _identifier(annotation.get("id"), f"annotations[{annotation_index}].id")
        _text(annotation.get("label"), f"annotations[{annotation_index}].label")
        for boundary in ("frame_start", "frame_end"):
            if annotation.get(boundary) is not None:
                frame_boundary = int(
                    _finite(
                        annotation[boundary],
                        f"annotations[{annotation_index}].{boundary}",
                    )
                )
                if frame_boundary < 0 or frame_boundary >= len(frames):
                    raise FieldPlaybackContractError(
                        f"annotations[{annotation_index}].{boundary} is outside frames"
                    )

    numerical_snapshots = _sequence(
        manifest.get("numerical_snapshots", []),
        "numerical_snapshots",
    )
    if numerical_snapshots and len(numerical_snapshots) != len(frames):
        raise FieldPlaybackContractError(
            "numerical_snapshots must be empty or contain one entry per frame"
        )
    for snapshot_index, snapshot_value in enumerate(numerical_snapshots):
        snapshot = _mapping(
            snapshot_value,
            f"numerical_snapshots[{snapshot_index}]",
        )
        _text(
            snapshot.get("artifact_id"),
            f"numerical_snapshots[{snapshot_index}].artifact_id",
        )
        if snapshot.get("media_type") != "application/json+gzip":
            raise FieldPlaybackContractError(
                "numerical snapshots must use application/json+gzip"
            )

    if manifest.get("manifest_artifact_id") is not None:
        _text(manifest["manifest_artifact_id"], "manifest_artifact_id")

    return dict(manifest)
