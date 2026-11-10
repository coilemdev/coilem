"""Helpers for storing heavy solved-field artifacts outside UI payloads."""

from __future__ import annotations

import base64
import gzip
import json
import math
from pathlib import Path
from typing import Any

SOLVE_CACHE_ROOT = Path.home() / ".openem" / "solve_cache"
AIRGAP_RECORD_ARTIFACT_SCHEMA = "openem.airgap_field_records.v1"
FIELD_LINE_FRAME_ARTIFACT_SCHEMA = "openem.field_line_frame.v1"
DISPLAY_AIRGAP_RECORD_LIMIT = 720


def _b64url_encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> str:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def encode_solve_cache_artifact_id(path: Path) -> str:
    """Return an opaque id for a file under the solve-cache root."""

    root = SOLVE_CACHE_ROOT.expanduser().resolve()
    resolved = path.expanduser().resolve()
    rel = resolved.relative_to(root)
    return _b64url_encode(rel.as_posix())


def resolve_solve_cache_artifact_id(artifact_id: str) -> Path:
    """Resolve an opaque artifact id to a safe solve-cache path."""

    try:
        rel_text = _b64url_decode(artifact_id)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid artifact id") from exc
    rel = Path(rel_text)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("artifact id escapes solve cache")
    root = SOLVE_CACHE_ROOT.expanduser().resolve()
    resolved = (root / rel).resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("artifact id escapes solve cache")
    return resolved


def airgap_record_stats(records: dict[str, Any] | None) -> dict[str, float | int] | None:
    """Compute display stats from full airgap magnitude records."""

    mags = records.get("b_magnitude_t") if isinstance(records, dict) else None
    if not isinstance(mags, list):
        return None
    values = sorted(
        float(value)
        for value in mags
        if isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0.0
    )
    if not values:
        return None
    p95_index = min(len(values) - 1, max(0, math.floor((len(values) - 1) * 0.95)))
    return {
        "count": len(values),
        "mean_t": sum(values) / len(values),
        "p95_t": values[p95_index],
        "max_t": values[-1],
    }


def airgap_trace_profile_from_records(
    records: dict[str, Any] | None,
    *,
    bin_count: int = 180,
    span_deg: float = 360.0,
) -> dict[str, Any] | None:
    """Build a compact uniformly binned airgap profile from full records."""

    if not isinstance(records, dict):
        return None
    xs = records.get("centroid_x_mm")
    ys = records.get("centroid_y_mm")
    mags = records.get("b_magnitude_t")
    brs = records.get("b_radial_t")
    bts = records.get("b_tangential_t")
    if not (isinstance(xs, list) and isinstance(ys, list) and isinstance(mags, list)):
        return None
    if not (len(xs) == len(ys) == len(mags)) or not mags:
        return None

    normalized_span = max(1.0, min(360.0, float(span_deg)))
    count = max(1, int(bin_count))
    bins = [
        {
            "bmag": 0.0,
            "br": 0.0,
            "bt": 0.0,
            "brbt": 0.0,
            "samples": 0,
            "component_samples": 0,
        }
        for _ in range(count)
    ]
    sample_count = 0
    br_values = brs if isinstance(brs, list) else []
    bt_values = bts if isinstance(bts, list) else []
    have_components = len(br_values) == len(xs) and len(bt_values) == len(xs)

    for index in range(len(mags)):
        try:
            cx = float(xs[index])
            cy = float(ys[index])
            bmag = float(mags[index])
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(cx) and math.isfinite(cy) and math.isfinite(bmag)) or bmag <= 0.0:
            continue

        raw_angle_deg = (math.degrees(math.atan2(cy, cx)) + 360.0) % 360.0
        airgap_angle_deg = raw_angle_deg % normalized_span if normalized_span < 359.5 else raw_angle_deg
        bin_index = min(count - 1, max(0, int((airgap_angle_deg / normalized_span) * count)))
        bin_acc = bins[bin_index]
        bin_acc["bmag"] += bmag
        bin_acc["samples"] += 1
        sample_count += 1

        if have_components:
            try:
                br = float(br_values[index])
                bt = float(bt_values[index])
            except (TypeError, ValueError):
                continue
            if math.isfinite(br) and math.isfinite(bt):
                bin_acc["br"] += br
                bin_acc["bt"] += bt
                bin_acc["brbt"] += br * bt
                bin_acc["component_samples"] += 1

    if sample_count == 0:
        return None

    packed_bins: list[dict[str, Any]] = []
    for index, bin_acc in enumerate(bins):
        samples = int(bin_acc["samples"])
        if samples == 0:
            continue
        component_samples = int(bin_acc["component_samples"])
        packed: dict[str, Any] = {
            "mech_angle_deg": ((index + 0.5) / count) * normalized_span,
            "b_magnitude_t": bin_acc["bmag"] / samples,
            "samples": samples,
        }
        if component_samples > 0:
            packed["br_t"] = bin_acc["br"] / component_samples
            packed["bt_t"] = bin_acc["bt"] / component_samples
            packed["br_bt_t2"] = bin_acc["brbt"] / component_samples
        packed_bins.append(packed)

    return {
        "span_deg": normalized_span,
        "bin_count": count,
        "sample_count": sample_count,
        "bins": packed_bins,
    }


def sample_airgap_records_evenly(
    records: dict[str, Any] | None,
    *,
    limit: int = DISPLAY_AIRGAP_RECORD_LIMIT,
) -> dict[str, Any] | None:
    """Return an aligned display-sized sample of parallel airgap arrays."""

    if not isinstance(records, dict):
        return None
    mags = records.get("b_magnitude_t")
    if not isinstance(mags, list) or not mags:
        return None
    count = len(mags)
    if limit <= 0:
        return None
    if count <= limit:
        return dict(records)

    last_index = count - 1
    indexes = sorted({
        round((index * last_index) / (limit - 1))
        for index in range(limit)
    })
    sampled: dict[str, Any] = {}
    for key, value in records.items():
        if isinstance(value, list) and len(value) == count:
            sampled[key] = [value[index] for index in indexes]
        else:
            sampled[key] = value
    return sampled


def write_airgap_records_artifact(
    records: dict[str, Any] | None,
    cache_dir: Path | None,
    *,
    pos_idx: int,
    elec_angle_deg: float,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist full airgap records and return a lightweight artifact ref."""

    stats = airgap_record_stats(records)
    if records is None or stats is None or cache_dir is None:
        return None
    try:
        artifact_dir = cache_dir / "airgap_records"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        angle_token = f"{elec_angle_deg:.3f}".replace("-", "m").replace(".", "p")
        path = artifact_dir / f"pos{pos_idx:03d}_{angle_token}deg_airgap_records.json.gz"
        payload = {
            "schema_version": AIRGAP_RECORD_ARTIFACT_SCHEMA,
            "position_index": int(pos_idx),
            "electrical_angle_deg": float(elec_angle_deg),
            "record_count": int(stats["count"]),
            "stats": stats,
            "airgap_brbt": profile,
            "airgap_b_records": records,
        }
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        return {
            "artifact_id": encode_solve_cache_artifact_id(path),
            "format": "json.gz",
            "media_type": "application/json+gzip",
            "schema_version": AIRGAP_RECORD_ARTIFACT_SCHEMA,
            "record_count": int(stats["count"]),
            "byte_count": path.stat().st_size,
            "relative_path": path.resolve().relative_to(SOLVE_CACHE_ROOT.expanduser().resolve()).as_posix(),
        }
    except Exception:
        return None


def _field_line_frame_segment_count(frame: dict[str, Any] | None) -> int:
    contours = frame.get("contour_levels") if isinstance(frame, dict) else None
    if not isinstance(contours, list):
        return 0
    count = 0
    for level in contours:
        if not isinstance(level, dict):
            continue
        segments = level.get("segments_mm")
        if isinstance(segments, list):
            count += len(segments)
    return count


def _field_line_frame_record_count(frame: dict[str, Any] | None) -> int:
    if not isinstance(frame, dict):
        return 0
    element_b = frame.get("element_b_mag_t")
    if isinstance(element_b, list) and element_b:
        return len(element_b)
    return _field_line_frame_segment_count(frame)


def write_field_line_frame_artifact(
    frame: dict[str, Any] | None,
    cache_dir: Path | None,
    *,
    pos_idx: int,
    elec_angle_deg: float,
    artifact_label: str = "field_frame",
) -> dict[str, Any] | None:
    """Persist one solved field-line frame and return a lightweight artifact ref."""

    if frame is None or cache_dir is None:
        return None
    try:
        frame_payload = dict(frame)
        frame_payload.pop("field_frame_artifact", None)
        artifact_dir = cache_dir / "field_line_frames"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        angle_token = f"{elec_angle_deg:.3f}".replace("-", "m").replace(".", "p")
        safe_label = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in artifact_label) or "field_frame"
        path = artifact_dir / f"pos{pos_idx:03d}_{angle_token}deg_{safe_label}.json.gz"
        record_count = _field_line_frame_record_count(frame_payload)
        payload = {
            "schema_version": FIELD_LINE_FRAME_ARTIFACT_SCHEMA,
            "position_index": int(pos_idx),
            "electrical_angle_deg": float(elec_angle_deg),
            "record_count": record_count,
            "field_line_frame": frame_payload,
        }
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        return {
            "artifact_id": encode_solve_cache_artifact_id(path),
            "format": "json.gz",
            "media_type": "application/json+gzip",
            "schema_version": FIELD_LINE_FRAME_ARTIFACT_SCHEMA,
            "record_count": record_count,
            "byte_count": path.stat().st_size,
            "relative_path": path.resolve().relative_to(SOLVE_CACHE_ROOT.expanduser().resolve()).as_posix(),
        }
    except Exception:
        return None
