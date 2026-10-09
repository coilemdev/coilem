"""Steel-region flux-density metrics derived from solved field frames."""

from __future__ import annotations

import gzip
import json
import math
import re
from typing import Any, Literal

from backend import field_artifacts

SteelRegionBucket = Literal["teeth", "yoke"]
SteelFluxDensityAccumulator = dict[SteelRegionBucket, dict[str, float]]


def new_steel_flux_density_rms_accumulator() -> SteelFluxDensityAccumulator:
    """Create an accumulator for area-weighted steel |B| RMS metrics."""

    return {
        "teeth": {"area_mm2": 0.0, "weighted_b2_t2_mm2": 0.0},
        "yoke": {"area_mm2": 0.0, "weighted_b2_t2_mm2": 0.0},
    }


def update_steel_flux_density_rms_accumulator(
    accumulator: SteelFluxDensityAccumulator,
    frame: Any,
) -> None:
    """Accumulate area-weighted |B|^2 for stator teeth and yoke triangles."""

    nodes = _list_value(_field_value(frame, "nodes_mm"))
    triangles = _list_value(_field_value(frame, "triangles"))
    regions = _list_value(_field_value(frame, "regions"))
    if not nodes or not triangles or not regions:
        artifact_frame = _field_frame_from_artifact_ref(frame)
        if artifact_frame is not None:
            update_steel_flux_density_rms_accumulator(accumulator, artifact_frame)
        return
    if not nodes or not triangles or len(regions) != len(triangles):
        return

    b_mag = _list_value(_field_value(frame, "element_b_mag_t"))
    b_x = _list_value(_field_value(frame, "element_bx_t"))
    b_y = _list_value(_field_value(frame, "element_by_t"))
    has_mag = len(b_mag) == len(triangles)
    has_xy = len(b_x) == len(triangles) and len(b_y) == len(triangles)
    if not has_mag and not has_xy:
        return

    for index, triangle in enumerate(triangles):
        bucket = _steel_region_bucket(regions[index])
        if bucket is None:
            continue
        area_mm2 = _triangle_area_mm2(nodes, triangle)
        if area_mm2 is None:
            continue
        field_t = _finite_float(b_mag[index]) if has_mag else None
        if field_t is None and has_xy:
            bx_t = _finite_float(b_x[index])
            by_t = _finite_float(b_y[index])
            if bx_t is not None and by_t is not None:
                field_t = math.hypot(bx_t, by_t)
        if field_t is None or field_t < 0:
            continue
        accumulator[bucket]["area_mm2"] += area_mm2
        accumulator[bucket]["weighted_b2_t2_mm2"] += area_mm2 * field_t * field_t


def merge_steel_flux_density_rms_accumulator(
    accumulator: SteelFluxDensityAccumulator,
    update: Any,
) -> None:
    """Merge a serializable steel RMS accumulator into another accumulator."""

    if not isinstance(update, dict):
        return
    for bucket in ("teeth", "yoke"):
        incoming = update.get(bucket)
        if not isinstance(incoming, dict):
            continue
        area_mm2 = _finite_float(incoming.get("area_mm2"))
        weighted_b2 = _finite_float(incoming.get("weighted_b2_t2_mm2"))
        if area_mm2 is None or weighted_b2 is None or area_mm2 <= 0 or weighted_b2 < 0:
            continue
        accumulator[bucket]["area_mm2"] += area_mm2
        accumulator[bucket]["weighted_b2_t2_mm2"] += weighted_b2


def finalize_steel_flux_density_rms(
    accumulator: SteelFluxDensityAccumulator,
) -> dict[SteelRegionBucket, float | None]:
    """Return final area-weighted RMS |B| values in Tesla."""

    result: dict[SteelRegionBucket, float | None] = {"teeth": None, "yoke": None}
    for bucket in ("teeth", "yoke"):
        area_mm2 = accumulator[bucket]["area_mm2"]
        weighted_b2 = accumulator[bucket]["weighted_b2_t2_mm2"]
        if area_mm2 > 0 and weighted_b2 >= 0:
            result[bucket] = math.sqrt(weighted_b2 / area_mm2)
    return result


def steel_flux_density_rms_from_frames(
    frames: list[Any] | tuple[Any, ...] | None,
) -> dict[SteelRegionBucket, float | None] | None:
    """Compute steel RMS |B| values from a sequence of solved field frames."""

    if not frames:
        return None
    accumulator = new_steel_flux_density_rms_accumulator()
    for frame in frames:
        update_steel_flux_density_rms_accumulator(accumulator, frame)
    result = finalize_steel_flux_density_rms(accumulator)
    return result if result["teeth"] is not None or result["yoke"] is not None else None


def _field_value(frame: Any, key: str) -> Any:
    if isinstance(frame, dict):
        return frame.get(key)
    return getattr(frame, key, None)


def _artifact_id_from_ref(ref: Any) -> str | None:
    if isinstance(ref, dict):
        artifact_id = ref.get("artifact_id")
    else:
        artifact_id = getattr(ref, "artifact_id", None)
    return artifact_id if isinstance(artifact_id, str) and artifact_id else None


def _field_frame_from_artifact_ref(frame: Any) -> dict[str, Any] | None:
    ref = _field_value(frame, "full_field_frame_artifact") or _field_value(
        frame,
        "field_frame_artifact",
    )
    artifact_id = _artifact_id_from_ref(ref)
    if artifact_id is None:
        return None
    try:
        path = field_artifacts.resolve_solve_cache_artifact_id(artifact_id)
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        return None
    loaded_frame = payload.get("field_line_frame") if isinstance(payload, dict) else None
    return loaded_frame if isinstance(loaded_frame, dict) else None


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _normalize_region_tag(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"[\s-]+", "_", text)
    text = re.sub(r"__+", "_", text)
    return text.lower()


def _steel_region_bucket(value: Any) -> SteelRegionBucket | None:
    region = _normalize_region_tag(value)
    if region in {"stator_tooth", "stator_teeth", "tooth", "teeth"}:
        return "teeth"
    if region in {"stator_yoke", "yoke", "back_iron", "stator_back_iron"}:
        return "yoke"
    return None


def _triangle_area_mm2(nodes: list[Any], triangle: Any) -> float | None:
    if not isinstance(triangle, list) or len(triangle) != 3:
        return None
    try:
        ia = int(triangle[0])
        ib = int(triangle[1])
        ic = int(triangle[2])
    except (TypeError, ValueError):
        return None
    if ia != triangle[0] or ib != triangle[1] or ic != triangle[2]:
        return None
    if ia < 0 or ib < 0 or ic < 0 or max(ia, ib, ic) >= len(nodes):
        return None
    a = nodes[ia]
    b = nodes[ib]
    c = nodes[ic]
    if not isinstance(a, list) or not isinstance(b, list) or not isinstance(c, list):
        return None
    ax = _finite_float(a[0] if len(a) > 0 else None)
    ay = _finite_float(a[1] if len(a) > 1 else None)
    bx = _finite_float(b[0] if len(b) > 0 else None)
    by = _finite_float(b[1] if len(b) > 1 else None)
    cx = _finite_float(c[0] if len(c) > 0 else None)
    cy = _finite_float(c[1] if len(c) > 1 else None)
    if ax is None or ay is None or bx is None or by is None or cx is None or cy is None:
        return None
    area_mm2 = abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) * 0.5
    return area_mm2 if area_mm2 > 0 and math.isfinite(area_mm2) else None
