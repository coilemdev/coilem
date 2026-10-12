"""Post-solve pipeline speedups keep their outputs unchanged."""

from __future__ import annotations

import gzip
import json
import math
import random
import zipfile
from pathlib import Path

from backend.field_artifacts import _write_json_gz
from backend.field_lines import _dedupe_points, _farthest_point_pair, generate_contour_segments
from backend.public_report import write_replayable_run_package
from backend.solver import _validated_steel_flux_density_rms
from backend.steel_flux_metrics import (
    finalize_steel_flux_density_rms,
    merge_steel_flux_density_rms_accumulator,
    new_steel_flux_density_rms_accumulator,
    update_steel_flux_density_rms_accumulator,
)


def _unfiltered_contour_segments(nodes, triangles, az, levels):
    """generate_contour_segments' per-triangle rule, applied to every triangle."""

    max_abs = max(abs(value) for value in az)
    value_tol = max(max_abs * 1e-9, 1e-12)
    result = []
    for level in levels:
        segments = []
        for tri in triangles:
            values = [az[index] for index in tri]
            points = [nodes[index] for index in tri]
            if all(abs(value - level) <= value_tol for value in values):
                continue
            hits = []
            for start, end in ((0, 1), (1, 2), (2, 0)):
                v1, v2 = values[start] - level, values[end] - level
                p1, p2 = points[start], points[end]
                if abs(v1) <= value_tol and abs(v2) <= value_tol:
                    hits += [(float(p1[0]), float(p1[1])), (float(p2[0]), float(p2[1]))]
                elif abs(v1) <= value_tol:
                    hits.append((float(p1[0]), float(p1[1])))
                elif abs(v2) <= value_tol:
                    hits.append((float(p2[0]), float(p2[1])))
                elif (v1 > 0) != (v2 > 0):
                    t = v1 / (v1 - v2)
                    hits.append((float(p1[0] + t * (p2[0] - p1[0])), float(p1[1] + t * (p2[1] - p1[1]))))
            unique = _dedupe_points(hits, 1e-7)
            if len(unique) > 2:
                pair = _farthest_point_pair(unique)
                if pair is None:
                    continue
                unique = [pair[0], pair[1]]
            if len(unique) == 2:
                (x1, y1), (x2, y2) = unique
                segments.append([x1, y1, x2, y2])
        result.append(segments)
    return result


def test_contour_skip_matches_testing_every_triangle() -> None:
    rng = random.Random(7)
    size = 12
    nodes = [[float(x), float(y)] for y in range(size) for x in range(size)]
    triangles = []
    for y in range(size - 1):
        for x in range(size - 1):
            a, b, c, d = y * size + x, y * size + x + 1, (y + 1) * size + x, (y + 1) * size + x + 1
            triangles += [[a, b, c], [b, d, c]]
    # Quantized values put many vertices exactly on a level; one NaN keeps
    # its triangles on the full checks.
    az = [round(rng.uniform(-1.0, 1.0), 1) for _ in nodes]
    az[size + 3] = math.nan
    levels = [-0.5, -0.2, 0.0, 0.1, 0.3, 0.7, 1.0, -1.0]

    contours = generate_contour_segments(nodes, triangles, az, levels)

    # repr() compares the NaN coordinates a NaN vertex produces, which == cannot.
    assert repr([level.segments_mm for level in contours]) == repr(
        _unfiltered_contour_segments(nodes, triangles, az, levels)
    )
    assert sum(len(level.segments_mm) for level in contours) > 0


def test_json_gz_writer_round_trips_compact_json(tmp_path: Path) -> None:
    payload = {"field_line_frame": {"nodes_mm": [[0.1, 2.0]], "az": [1e-300, -3.5]}, "n": 1}
    path = tmp_path / "frame.json.gz"

    _write_json_gz(path, payload)

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        text = handle.read()
    assert text == json.dumps(payload, separators=(",", ":"))


def test_merged_frame_accumulators_match_one_running_sum() -> None:
    frames = []
    for offset in range(4):
        frames.append(
            {
                "nodes_mm": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
                "triangles": [[0, 1, 2], [1, 3, 2]],
                "regions": ["stator_tooth", "stator_yoke"],
                "element_b_mag_t": [0.4 + 0.1 * offset, 1.3 - 0.05 * offset],
            }
        )
    running = new_steel_flux_density_rms_accumulator()
    merged = new_steel_flux_density_rms_accumulator()
    for frame in frames:
        update_steel_flux_density_rms_accumulator(running, frame)
        per_frame = new_steel_flux_density_rms_accumulator()
        update_steel_flux_density_rms_accumulator(per_frame, frame)
        merge_steel_flux_density_rms_accumulator(merged, per_frame)

    expected = finalize_steel_flux_density_rms(running)
    actual = finalize_steel_flux_density_rms(merged)
    for bucket in ("teeth", "yoke"):
        assert math.isclose(actual[bucket], expected[bucket], rel_tol=1e-12)


def test_precomputed_steel_rms_is_validated_before_use() -> None:
    assert _validated_steel_flux_density_rms({"teeth": 0.7, "yoke": None}) == {
        "teeth": 0.7,
        "yoke": None,
    }
    assert _validated_steel_flux_density_rms({"teeth": None, "yoke": None}) is None
    assert _validated_steel_flux_density_rms({"teeth": -1.0, "yoke": 0.4}) is None
    assert _validated_steel_flux_density_rms({"teeth": math.nan, "yoke": 0.4}) is None
    assert _validated_steel_flux_density_rms({"teeth": True, "yoke": 0.4}) is None
    assert _validated_steel_flux_density_rms(None) is None


def test_replay_package_stores_already_compressed_files(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "artifacts").mkdir(parents=True)
    (run / "result.json").write_text(json.dumps({"torque": [1.0] * 200}), encoding="utf-8")
    (run / "artifacts" / "layer.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8)
    (run / "artifacts" / "lines.webp").write_bytes(b"RIFF" + bytes(range(256)) * 8)
    with gzip.open(run / "artifacts" / "frame.json.gz", "wb") as handle:
        handle.write(b"{}" * 100)
    target = tmp_path / "run-package.zip"

    write_replayable_run_package(run, target, completed_at="2026-10-12T12:00:00Z")

    with zipfile.ZipFile(target) as archive:
        kinds = {info.filename: info.compress_type for info in archive.infolist()}
        assert archive.testzip() is None
        assert archive.read("artifacts/layer.png") == (run / "artifacts" / "layer.png").read_bytes()
    assert kinds == {
        "artifacts/frame.json.gz": zipfile.ZIP_STORED,
        "artifacts/layer.png": zipfile.ZIP_STORED,
        "artifacts/lines.webp": zipfile.ZIP_STORED,
        "result.json": zipfile.ZIP_DEFLATED,
    }
