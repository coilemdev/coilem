"""Preset provenance, real field units and guarded local visualization artifacts."""
import gzip
import hashlib
import json

import numpy as np
import pytest
from pydantic import ValidationError

from backend.experimental import outrunner_runtime as runtime
from backend.experimental import outrunner_visuals as visuals
from backend.experimental.femm_outrunner import FixtureMesh
from backend.experimental.outrunner_project import QUALITY_PRESETS, OutrunnerAnalysis, OutrunnerProject, OutrunnerRunRequest


def preset(name):
    return OutrunnerAnalysis(accuracy_plan=name, **{k: v for k, v in QUALITY_PRESETS[name].items() if k != "label"})


def test_named_plans_and_legacy_settings_preserve_numerical_identity():
    assert OutrunnerAnalysis.model_validate({}).accuracy_plan == "standard"
    legacy = OutrunnerAnalysis.model_validate({"gap_size_mm": .025, "unique_samples": 192})
    assert legacy.accuracy_plan == "custom"
    assert legacy.unique_samples == 192 and legacy.gap_size_mm == .025
    identities = {visuals.mesh_identity(OutrunnerProject(analysis=preset(name))) for name in QUALITY_PRESETS}
    assert len(identities) == 3
    with pytest.raises(ValidationError, match="Named accuracy plan"):
        OutrunnerAnalysis(accuracy_plan="preview")


def test_estimates_count_endpoints_and_use_observed_local_time(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "_root", lambda: tmp_path)
    standard = OutrunnerRunRequest(project=OutrunnerProject())
    assert runtime.estimate(standard)["positions"] == 98
    assert runtime.estimate(OutrunnerRunRequest(project=OutrunnerProject(), analysis="source_point"))["positions"] == 1
    preview = runtime.estimate(OutrunnerRunRequest(project=OutrunnerProject(analysis=preset("preview"))))
    assert preview["positions"] == 50
    assert preview["total_range_s"][1] < runtime.estimate(standard)["total_range_s"][0]
    run = tmp_path/("a"*32)
    run.mkdir()
    (run/"request.json").write_text(standard.model_dump_json())
    (run/"state.json").write_text(json.dumps({"rows": [{"elapsed_s": 20, "duration_includes_archive": True}]}))
    estimate = runtime.estimate(standard)
    assert estimate["basis"] == "completed_local_points"
    assert estimate["point_range_s"] == [15, 32]
    assert estimate["total_range_s"] == [1470, 3136]


def test_preview_and_solve_share_the_identical_native_mesh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(visuals, "_root", lambda: tmp_path)
    calls = []
    def generate(angle, gap, bulk):
        calls.append((angle, gap, bulk))
        nodes = np.array([[i*2., 0.] for i in range(29) for _ in range(3)])
        nodes[1::3, 0] += 1
        nodes[2::3, 1] += 1
        nodes = np.vstack([nodes, [[6.5, 0], [15.39, 0]]])
        return FixtureMesh(nodes, np.arange(87).reshape(-1, 3), np.arange(29), np.array([87, 88]), provenance={"mesh_policy": "test"})
    monkeypatch.setattr(visuals, "generate_native_mesh", generate)
    project = OutrunnerProject(analysis=preset("preview"))
    preview_path = visuals.mesh_preview_path(project)
    with gzip.open(preview_path) as stream:
        preview = json.load(stream)
    cached = visuals.native_mesh(project)
    assert calls == [(0, .1, .5)]
    assert preview["triangles"] == cached.triangles.tolist()
    assert preview["nodes_mm"] == cached.nodes_mm.tolist()
    assert preview["mesh_info"]["mesh_identity"] == visuals.mesh_identity(project)
    assert preview["mesh_qa"]["min_triangle_quality"] == pytest.approx(3**.5/2)


def retain_case(folder, index, az):
    case_id = f"loaded_{index:04d}"
    case = folder/case_id
    case.mkdir()
    payloads = {"mesh.json": {"nodes_mm": [[0, 0], [1, 0], [0, 1]], "triangles": [[0, 1, 2]], "label_ids": [0]},
                "field.json": {"solution": {"az_nodal": az, "convergence": {"converged": True}}}}
    hashes = {}
    for name, payload in payloads.items():
        raw = json.dumps(payload).encode()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        with gzip.open(case/(name+".gz"), "wb") as stream:
            stream.write(raw)
    return {"case": {"id": case_id, "family": "loaded", "angle_ccw_deg": index*10, "currents_A": [0, 4, -4]},
            "raw_sha256": hashes, "outer_rotor_torque_Nm": .1}


def test_frames_use_actual_az_in_si_units_fixed_scale_and_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(visuals, "_root", lambda: tmp_path)
    run_id = "a"*32
    folder = tmp_path/run_id
    folder.mkdir()
    # One mm with dAz/dy=.001 Wb/m gives Bx=1 T, not .001 T.
    rows = [retain_case(folder, 0, [0, 0, .001]), retain_case(folder, 1, [0, 0, .002])]
    (folder/"state.json").write_text(json.dumps({"status": "COMPLETE", "rows": rows}))
    first, second = [visuals.prepare_frame(run_id, index) for index in [0, 1]]
    assert first["maxB"] == pytest.approx(1.)
    assert second["maxB"] == pytest.approx(2.)
    assert first["colorScale"] == second["colorScale"]
    assert first["colorScale"] == {"minB": 0, "maxB": 2, "overAboveT": 2, "fixed": True}
    assert first["identity"]["raw_sha256"] == rows[0]["raw_sha256"]
    assert first["identity"]["renderer_revision"] == visuals.PLAYBACK_RENDERER_REVISION
    assert visuals.frame_layer_path(run_id, 0, "heat").read_bytes() != visuals.frame_layer_path(run_id, 1, "heat").read_bytes()
    with gzip.open(visuals.frame_folder(run_id, 0)/"numerical.json.gz") as stream:
        plot = json.load(stream)
    assert plot["element_bx_t"] == pytest.approx([1.])
    assert plot["element_by_t"] == pytest.approx([0.])
    assert plot["angle_deg"] == 0
    assert all(frame["raster_ready"] for frame in visuals.completed_frames(run_id))
    # Raw evidence must verify before deriving a new image.
    with gzip.open(folder/"loaded_0000"/"field.json.gz", "wb") as stream:
        stream.write(b'{}')
    with pytest.raises(ValueError, match="hash mismatch"):
        visuals._verified_json(folder/"loaded_0000", rows[0], "field.json")
    with pytest.raises(ValueError):
        visuals.frame_layer_path(run_id, 0, "../../secret")
    with pytest.raises(ValueError):
        visuals.run_folder("../outside")
    with pytest.raises(ValueError):
        visuals.prepare_frame(run_id, -1)
