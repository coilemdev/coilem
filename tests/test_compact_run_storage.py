"""Saved runs keep field frames compact and drop older runs' field playback (#212)."""

from __future__ import annotations

import gzip
import json
import os
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from backend import field_frame_codec
from backend.field_artifacts import (
    AIRGAP_RECORD_ARTIFACT_SCHEMA,
    FIELD_LINE_FRAME_ARTIFACT_SCHEMA,
    compact_field_frame_path,
    encode_solve_cache_artifact_id,
    read_field_line_frame_artifact,
    resolve_solve_cache_artifact_id,
    solve_cache_root,
    write_field_line_frame_artifact,
)
from backend.solve_workspace import (
    FIELD_PLAYBACK_REMOVED_REASON,
    SolveWorkspace,
    resolve_run_artifact_id,
)

VALID_CONFIG = json.loads(Path("tests/fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"))


def _plot(scale: float, count: int = 40) -> dict[str, object]:
    return {
        "nodes_mm": [[0.1 * index, 0.2 * index + 1.0 / 3.0] for index in range(count + 2)],
        "triangles": [[index, index + 1, index + 2] for index in range(count)],
        "regions": ["stator_steel" if index % 3 else "airgap" for index in range(count)],
        "element_b_mag_t": [scale * (0.5 + index / 7.0) for index in range(count)],
        "element_bx_t": [scale * (0.3 - index / 11.0) for index in range(count)],
        "element_by_t": [scale * (0.4 + index / 13.0) for index in range(count)],
        "contour_levels": [{"level": 0.0012345678901234567, "segments_mm": [[0.1 * index, 0.0, 1.0, 1.0] for index in range(count)]}],
        "az_min": -0.0123456789012345,
        "az_max": 0.0123456789012345,
    }


def _frame() -> dict[str, object]:
    return {**_plot(1.0), "noload_plot": _plot(0.75)}


def _close(stored: object, original: object) -> None:
    """Assert a decoded value equals the original, floats to float32 precision."""

    if isinstance(original, dict):
        assert isinstance(stored, dict) and set(stored) == set(original)
        for key, value in original.items():
            _close(stored[key], value)
    elif isinstance(original, list):
        assert isinstance(stored, list) and len(stored) == len(original)
        for stored_value, value in zip(stored, original):
            _close(stored_value, value)
    elif isinstance(original, float):
        assert stored == pytest.approx(original, rel=1e-7, abs=1e-30)
    else:
        assert stored == original and type(stored) is type(original)


def test_compact_frames_round_trip_arrays_as_float32_and_everything_else_exactly() -> None:
    payload = {
        "schema_version": FIELD_LINE_FRAME_ARTIFACT_SCHEMA,
        "electrical_angle_deg": 1.0 / 3.0,
        "short": [1.0 / 3.0, 2.0 / 3.0],
        "flags": [True, False] * 10,
        "empty": [],
        "huge_ints": [2**70 + index for index in range(20)],
        "$dollar": {"$array": "a literal key, not a marker"},
        "field_line_frame": _frame(),
    }

    raw = field_frame_codec.encode_compact_field_frame(payload)
    decoded = field_frame_codec.decode_compact_field_frame(raw)

    _close(decoded, payload)
    # Scalars, short lists, booleans, integers and strings are exact.
    assert decoded["electrical_angle_deg"] == payload["electrical_angle_deg"]
    assert decoded["short"] == payload["short"]
    assert decoded["flags"] == payload["flags"]
    assert decoded["huge_ints"] == payload["huge_ints"]
    assert decoded["$dollar"] == payload["$dollar"]
    frame = decoded["field_line_frame"]
    assert frame["triangles"] == payload["field_line_frame"]["triangles"]
    assert frame["regions"] == payload["field_line_frame"]["regions"]
    assert frame["contour_levels"][0]["level"] == payload["field_line_frame"]["contour_levels"][0]["level"]
    # Long real-valued arrays are float32.
    stored = np.asarray(frame["element_bx_t"])
    assert np.array_equal(stored, np.asarray(payload["field_line_frame"]["element_bx_t"], dtype=np.float32))
    with pytest.raises(ValueError, match="not a compact field frame"):
        field_frame_codec.decode_compact_field_frame(b"{}")


def test_frame_writer_adds_a_compact_copy_that_reads_back_like_the_json(data_root: Path) -> None:
    ref = write_field_line_frame_artifact(_frame(), solve_cache_root() / "magneto2d-test", pos_idx=3, elec_angle_deg=45.0)

    assert ref is not None
    json_path = resolve_solve_cache_artifact_id(ref["artifact_id"])
    assert json_path.name == "pos003_45p000deg_field_frame.json.gz"
    compact_path = compact_field_frame_path(json_path)
    assert compact_path.name == "pos003_45p000deg_field_frame.f32.xz"
    assert field_frame_codec.is_compact_field_frame(compact_path)
    assert not list(compact_path.parent.glob(".*"))
    from_json = read_field_line_frame_artifact(json_path)
    from_compact = read_field_line_frame_artifact(compact_path)
    _close(from_compact, from_json)
    # The PM-only plot's shared mesh is restored from either form.
    assert from_compact["field_line_frame"]["noload_plot"]["triangles"] == _frame()["triangles"]
    assert compact_path.stat().st_size < json_path.stat().st_size


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(root))
    return root


def _cached_run_result(tag: str, sources: dict[str, Path]) -> dict:
    """A result whose frame, playback image and air-gap record live in the solve cache."""

    cache = solve_cache_root() / f"magneto2d-{tag}"
    ref = write_field_line_frame_artifact(_frame(), cache, pos_idx=0, elec_angle_deg=0.0)
    assert ref is not None
    image = cache / "field_playback" / "resultant" / "frame_0000_resultant_flux.webp"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"RIFF" + tag.encode() * 64)
    airgap = cache / "airgap_records" / "pos000_0p000deg_airgap_records.json.gz"
    airgap.parent.mkdir(parents=True)
    with gzip.open(airgap, "wt", encoding="utf-8") as handle:
        json.dump({"schema_version": AIRGAP_RECORD_ARTIFACT_SCHEMA, "airgap_b_records": {}}, handle)
    sources.update({f"frame-{tag}": resolve_solve_cache_artifact_id(ref["artifact_id"]), f"image-{tag}": image, f"airgap-{tag}": airgap})
    return {
        "summary": {"avg_torque_Nm": 1.0},
        "solve_metadata": {"solver_name": "magneto2d-rust-test"},
        "field_line_frames": [{"angle_deg": 0.0, "field_frame_artifact": dict(ref), "full_field_frame_artifact": dict(ref)}],
        "field_playback": {
            "frames": [{"compositions": {"resultant": {"flux": {"artifact_id": encode_solve_cache_artifact_id(image), "media_type": "image/webp"}}}}]
        },
        "airgap_records": [{"artifact_id": encode_solve_cache_artifact_id(airgap), "schema_version": AIRGAP_RECORD_ARTIFACT_SCHEMA}],
    }


def _save(workspace: SolveWorkspace, result: dict):
    writer = workspace.begin_run(project_name="Retention Motor", config=VALID_CONFIG, submitted_request={"config": deepcopy(VALID_CONFIG)})
    return writer.complete(result)


def _records(run: Path) -> dict[str, dict]:
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    return {record["kind"]: record for record in manifest["artifacts"]}


def test_saved_run_keeps_the_compact_frame_and_links_cache_files(data_root: Path) -> None:
    sources: dict[str, Path] = {}
    location = _save(SolveWorkspace(data_root), _cached_run_result("a", sources))

    loaded = SolveWorkspace(data_root).load_run(location.project_slug, location.run_id)
    assert loaded["integrity"]["valid"] is True
    assert loaded["field_playback"] == {"available": True, "removed_at": None, "message": None}
    ref = loaded["result"]["field_line_frames"][0]["field_frame_artifact"]
    assert ref == loaded["result"]["field_line_frames"][0]["full_field_frame_artifact"]
    assert ref["relative_path"].endswith(".f32.xz")
    # The ref still describes the frame as served; the file says how it is stored.
    assert ref["media_type"] == "application/json+gzip"
    stored = resolve_run_artifact_id(ref["artifact_id"])
    assert field_frame_codec.is_compact_field_frame(stored)
    assert ref["byte_count"] == stored.stat().st_size
    # The run shares the cache's bytes instead of copying them.
    compact = compact_field_frame_path(sources["frame-a"])
    assert os.stat(stored).st_ino == os.stat(compact).st_ino
    _close(read_field_line_frame_artifact(stored), read_field_line_frame_artifact(sources["frame-a"]))
    assert set(_records(location.path)) == {"field_frame", "field_playback_image", "other"}


def test_older_runs_give_up_field_playback_but_keep_results_and_other_artifacts(
    data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COILEM_FIELD_PLAYBACK_KEEP_RUNS", "2")
    workspace = SolveWorkspace(data_root)
    sources: dict[str, Path] = {}
    locations = [_save(workspace, _cached_run_result(tag, sources)) for tag in ("a", "b", "c")]
    oldest, *newest = locations

    records = _records(oldest.path)
    assert records["field_frame"]["removed_at"] and records["field_playback_image"]["removed_at"]
    assert not (oldest.path / records["field_frame"]["relative_path"]).exists()
    assert not (oldest.path / records["field_playback_image"]["relative_path"]).exists()
    # The air-gap record is not playback and stays, as do the results and report.
    assert "removed_at" not in records["other"]
    assert (oldest.path / records["other"]["relative_path"]).is_file()
    assert (oldest.path / "result.json").is_file() and (oldest.path / "report" / "report.pdf").is_file()
    loaded = workspace.load_run(oldest.project_slug, oldest.run_id)
    assert loaded["integrity"]["valid"] is True
    assert loaded["field_playback"]["available"] is False
    assert loaded["field_playback"]["message"] == FIELD_PLAYBACK_REMOVED_REASON
    assert loaded["field_playback"]["removed_at"] == records["field_frame"]["removed_at"]
    assert workspace.load_run_comparison(oldest.project_slug, oldest.run_id)["result"]["summary"]["avg_torque_Nm"] == 1.0
    # The previous-runs dialog marks the run and states the rule.
    listed = {record["run_id"]: record for record in workspace.list_runs()}
    assert listed[oldest.run_id]["field_playback_removed_at"] == records["field_frame"]["removed_at"]
    assert all("field_playback_removed_at" not in listed[location.run_id] for location in newest)
    assert workspace.storage_policy()["field_playback_keep_latest_per_project"] == 2
    for location in newest:
        kept = _records(location.path)
        assert all("removed_at" not in record for record in kept.values())
        assert workspace.load_run(location.project_slug, location.run_id)["field_playback"]["available"] is True

    # A later pass leaves an already pruned run's manifest alone.
    manifest_path = oldest.path / "manifest.json"
    before = manifest_path.read_bytes()
    assert workspace.prune_field_playback(oldest.project_slug) == 0
    assert manifest_path.read_bytes() == before


def test_runs_saved_before_artifact_kinds_are_classified_from_their_files(data_root: Path) -> None:
    workspace = SolveWorkspace(data_root)
    sources: dict[str, Path] = {}
    result = _cached_run_result("a", sources)
    compact_field_frame_path(sources["frame-a"]).unlink()  # older apps kept the gzipped JSON
    old = _save(workspace, result)
    manifest_path = old.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["artifacts"]:
        record.pop("kind")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _save(workspace, _cached_run_result("b", sources))

    assert workspace.prune_field_playback(old.project_slug, keep_latest=1) > 0

    records = json.loads(manifest_path.read_text(encoding="utf-8"))["artifacts"]
    by_suffix = {Path(record["relative_path"]).suffixes[-1]: record for record in records}
    assert by_suffix[".webp"]["kind"] == "field_playback_image" and by_suffix[".webp"]["removed_at"]
    removed = sorted(record["kind"] for record in records if record.get("removed_at"))
    assert removed == ["field_frame", "field_playback_image"]
    # The gzipped air-gap record is told apart from the gzipped frame by its schema.
    kept = [record for record in records if not record.get("removed_at")]
    assert len(kept) == 1 and (old.path / kept[0]["relative_path"]).is_file()
    assert workspace.load_run(old.project_slug, old.run_id)["integrity"]["valid"] is True


def test_a_full_workspace_frees_older_playback_before_refusing_a_solve(data_root: Path) -> None:
    sources: dict[str, Path] = {}
    roomy = SolveWorkspace(data_root)
    first = _save(roomy, _cached_run_result("a", sources))
    second = _save(roomy, _cached_run_result("b", sources))
    playback = sum(
        (first.path / record["relative_path"]).stat().st_size
        for record in json.loads((first.path / "manifest.json").read_text(encoding="utf-8"))["artifacts"]
        if record["kind"] != "other"
    )

    full = SolveWorkspace(data_root, max_bytes=roomy.usage_bytes() - playback // 2)
    writer = full.begin_run(project_name="Retention Motor", config=VALID_CONFIG, submitted_request={"config": VALID_CONFIG})
    writer.fail(error_code="TEST", message="not needed")

    assert full.load_run(first.project_slug, first.run_id)["field_playback"]["available"] is False
    # The project's newest run keeps its playback.
    assert full.load_run(second.project_slug, second.run_id)["field_playback"]["available"] is True


def test_the_field_frame_route_serves_a_saved_runs_compact_frame(data_root: Path) -> None:
    from fastapi.testclient import TestClient

    from backend.public_main import app

    sources: dict[str, Path] = {}
    location = _save(SolveWorkspace(data_root), _cached_run_result("a", sources))
    ref = SolveWorkspace(data_root).load_run(location.project_slug, location.run_id)["result"]["field_line_frames"][0]["field_frame_artifact"]

    response = TestClient(app, base_url="http://127.0.0.1").get(f"/solve/field-frame/{ref['artifact_id']}")

    assert response.status_code == 200, response.text
    frame = response.json()["field_line_frame"]
    assert frame["triangles"] == _frame()["triangles"]
    assert frame["noload_plot"]["regions"] == _frame()["regions"]
    _close(frame["element_bx_t"], _frame()["element_bx_t"])
