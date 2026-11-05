"""Actual native meshes and per-angle solved-field layers for the local fixture."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import threading
import time
from pathlib import Path

import numpy as np

from backend.experimental.femm_outrunner import ASSET_SHA256, FixtureMesh, source
from backend.experimental.outrunner_geometry import generate_native_mesh
from backend.experimental.outrunner_project import OutrunnerProject
from backend.experimental.outrunner_storage import read_json, replace_file, write_json
from backend.field_lines import build_field_line_plot_from_mesh
from backend.public_field_playback import (
    FLUX_COLOR_SCALE,
    PLAYBACK_RENDERER_REVISION,
    _contour_segments,
    _direction_cues,
    _pixel_mapper,
    _render_base,
    _render_heat,
    _render_lines,
    _render_mesh,
    _triangles,
    _view_geometry,
)
from backend.solve_workspace import user_data_root

VISUAL_VERSION = "outrunner-solved-layers/v3"
LAYER_NAMES = frozenset({"base", "heat", "mesh", "lines"})
_LOCK = threading.Lock()
_KEY_LOCKS: dict[str, threading.Lock] = {}
_PREPARING: set[str] = set()


def _lock(path: Path):
    with _LOCK:
        return _KEY_LOCKS.setdefault(str(path), threading.Lock())


def _root() -> Path:
    return user_data_root()/"experimental"/"femm-outrunner"


def _read(path: Path) -> dict:
    with gzip.open(path, "rb") as stream:
        return json.loads(stream.read())


def _write_gzip(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix+".tmp")
    with gzip.open(temporary, "wb", compresslevel=3) as stream:
        stream.write(json.dumps(value, allow_nan=False, separators=(",", ":")).encode())
    replace_file(temporary, path)


def region_names() -> list[str]:
    names = []
    for label in source()["labels"]:
        material = label["material"]
        inward_north = math.cos(math.radians(label["magnetization_angle_deg_raw"]-label["theta_deg"])) < 0
        kind = "air" if material == "Air" else ("magnet_n" if inward_north else "magnet_s") if label["material_index_1based"] == 2 else (
            f"slot_{label['index']} ({label['circuit']}{'+' if label['signed_turns'] > 0 else '-'})" if label["circuit"] else (
                "rotor_core" if label["group"] == 2 else "stator_yoke"))
        names.append(f"{material} / {kind}")
    return names


def mesh_identity(project: OutrunnerProject) -> str:
    settings = project.analysis
    raw = json.dumps([ASSET_SHA256, settings.mesh_policy, settings.gap_size_mm, settings.bulk_size_mm], separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _mesh_data(mesh: FixtureMesh) -> dict:
    return {"nodes_mm": mesh.nodes_mm.tolist(), "triangles": mesh.triangles.tolist(), "label_ids": mesh.label_ids.tolist(),
            "dirichlet_nodes": mesh.dirichlet_nodes.tolist(), "provenance": mesh.provenance}


def _mesh_from(data: dict) -> FixtureMesh:
    mesh = FixtureMesh(np.asarray(data["nodes_mm"]), np.asarray(data["triangles"], dtype=np.int64),
                       np.asarray(data["label_ids"], dtype=np.int64), np.asarray(data["dirichlet_nodes"], dtype=np.int64),
                       provenance=data["provenance"])
    mesh.validate()
    return mesh


def native_mesh(project: OutrunnerProject, angle: float = 0) -> FixtureMesh:
    settings = project.analysis
    if angle != 0:
        return generate_native_mesh(angle, settings.gap_size_mm, settings.bulk_size_mm)
    folder = _root()/"mesh-previews"/mesh_identity(project)
    with _lock(folder):
        raw_path = folder/"native.json.gz"
        if raw_path.exists():
            return _mesh_from(_read(raw_path))
        mesh = generate_native_mesh(0, settings.gap_size_mm, settings.bulk_size_mm)
        folder.mkdir(parents=True, exist_ok=True)
        _write_gzip(raw_path, _mesh_data(mesh))
        return mesh


def mesh_preview_path(project: OutrunnerProject) -> Path:
    mesh = native_mesh(project)
    path = _root()/"mesh-previews"/mesh_identity(project)/"preview-v2.json.gz"
    with _lock(path):
        if path.exists():
            return path
        xyz = mesh.nodes_mm[mesh.triangles]
        edges = np.roll(xyz, -1, axis=1)-xyz
        twice_area = abs(edges[:, 0, 0]*(-edges[:, 2, 1])-edges[:, 0, 1]*(-edges[:, 2, 0]))
        quality = 2*math.sqrt(3)*twice_area/np.sum(edges**2, axis=(1, 2))
        names = region_names()
        _write_gzip(path, {"nodes_mm": mesh.nodes_mm.tolist(), "triangles": mesh.triangles.tolist(),
                           "regions": [names[int(i)] for i in mesh.label_ids],
                           "mesh_info": {"num_nodes": len(mesh.nodes_mm), "num_triangles": len(mesh.triangles),
                                         "mesh_identity": mesh_identity(project), "gap_size_mm": project.analysis.gap_size_mm,
                                         "bulk_size_mm": project.analysis.bulk_size_mm},
                           "mesh_qa": {"min_triangle_quality": float(quality.min()), "mean_triangle_quality": float(quality.mean())},
                           "generation_time_ms": 0})
    return path


def run_folder(run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid run identifier")
    return _root()/run_id


def completed_frames(run_id: str) -> list[dict]:
    state = read_json(run_folder(run_id)/"state.json")
    return [{"index": index, "case_id": row["case"]["id"], "family": row["case"]["family"],
             "angle_ccw_deg": row["case"]["angle_ccw_deg"], "currents_A": row["case"]["currents_A"],
             "torque_Nm": row["outer_rotor_torque_Nm"],
             "raster_ready": _frame_ready(run_folder(run_id)/row["case"]["id"]/"visuals-v1"/"frame.json", row)}
            for index, row in enumerate(state.get("rows", []))]


def _frame_identity(row: dict) -> dict:
    return {"visual_version": VISUAL_VERSION, "renderer_revision": PLAYBACK_RENDERER_REVISION, "raw_sha256": row["raw_sha256"]}


def _frame_ready(path: Path, row: dict) -> bool:
    try:
        return read_json(path)["identity"] == _frame_identity(row)
    except (OSError, ValueError, KeyError):
        return False


def prepare_playback(run_id: str) -> dict:
    completed_frames(run_id)
    with _LOCK:
        if run_id in _PREPARING:
            return {"status": "PREPARING"}
        _PREPARING.add(run_id)

    def work():
        try:
            while True:
                for frame in completed_frames(run_id):
                    if not frame["raster_ready"]:
                        prepare_frame(run_id, frame["index"])
                state = read_json(run_folder(run_id)/"state.json")
                if state["status"] not in ("RUNNING", "QUEUED"):
                    if all(frame["raster_ready"] for frame in completed_frames(run_id)):
                        break
                time.sleep(0.5)
        except Exception as exc:
            write_json(run_folder(run_id)/"playback-error.json", {"error": str(exc)})
        finally:
            with _LOCK:
                _PREPARING.discard(run_id)
    threading.Thread(target=work, daemon=True).start()
    return {"status": "PREPARING"}


def _case(run_id: str, index: int) -> tuple[Path, dict]:
    folder = run_folder(run_id)
    state = read_json(folder/"state.json")
    rows = state.get("rows", [])
    if index < 0 or index >= len(rows):
        raise ValueError("This solved frame is not available yet")
    row = rows[index]
    case_id = row["case"]["id"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", case_id):
        raise ValueError("Invalid retained case identity")
    return folder/case_id, row


def _verified_json(folder: Path, row: dict, name: str) -> dict:
    with gzip.open(folder/(name+".gz"), "rb") as stream:
        raw = stream.read()
    if hashlib.sha256(raw).hexdigest() != row["raw_sha256"][name]:
        raise ValueError("Retained numerical evidence hash mismatch")
    return json.loads(raw)


def frame_folder(run_id: str, index: int) -> Path:
    folder, _ = _case(run_id, index)
    return folder/"visuals-v1"


def prepare_frame(run_id: str, index: int) -> dict:
    """Render a real per-angle field. No rigid rotation or angular interpolation."""
    from PIL import Image, ImageDraw, ImageFilter

    folder, row = _case(run_id, index)
    output = folder/"visuals-v1"
    expected = _frame_identity(row)
    with _lock(output):
        receipt = output/"frame.json"
        if receipt.exists():
            result = read_json(receipt)
            if result["identity"] == expected:
                return result
        data = _verified_json(folder, row, "mesh.json")
        field = _verified_json(folder, row, "field.json")["solution"]
        if not field["convergence"]["converged"]:
            raise ValueError("Cannot display a nonconverged field as a solution")
        names = region_names()
        plot = build_field_line_plot_from_mesh(
            config_summary={"topology": "SPM", "slots": 12, "poles": 14, "stator_od_mm": 25.6,
                            "rotor_od_mm": 30.78, "magnet_thickness_mm": 1, "stack_length_mm": 10},
            mesh_info={"num_nodes": len(data["nodes_mm"]), "num_triangles": len(data["triangles"]),
                       "pole_pitch_deg": 360/14, "n_pole_pitches": 14, "total_span_deg": 360},
            nodes_mm=data["nodes_mm"], triangles=data["triangles"], regions=[names[i] for i in data["label_ids"]],
            az_nodal=field["az_nodal"], n_pole_pitches=14, total_span_deg=360)
        if plot is None:
            raise ValueError("No drawable numerical field")
        payload = plot.model_dump(mode="json")
        payload["angle_deg"] = row["case"]["angle_ccw_deg"]
        output.mkdir(exist_ok=True)
        _write_gzip(output/"numerical.json.gz", payload)
        nodes, view_box = _view_geometry(payload)
        triangles = _triangles(payload, nodes)
        size = 1024
        mapper = _pixel_mapper(view_box, size_px=size)
        base = _render_base(Image, ImageDraw, triangles, mapper, size_px=size)
        mesh = _render_mesh(Image, ImageDraw, triangles, mapper, size_px=size)
        heat, minimum, maximum = _render_heat(Image, ImageDraw, payload, triangles, mapper, size_px=size)
        lines = _render_lines(Image, ImageDraw, ImageFilter, _contour_segments(payload, level_stride=2), mapper, size_px=size)
        for name, layer in (("base", base), ("heat", heat), ("mesh", mesh), ("lines", lines)):
            temp = output/(name+".tmp")
            layer.save(temp, format="WEBP", lossless=True, method=1)
            replace_file(temp, output/(name+".webp"))
        result = {"identity": expected, "frame_index": index, "case": row["case"], "width": size, "height": size,
                  "viewBox": " ".join(str(value) for value in view_box), "minB": minimum, "maxB": maximum,
                  "colorScale": {"minB": FLUX_COLOR_SCALE["min"], "maxB": FLUX_COLOR_SCALE["max"],
                                 "overAboveT": FLUX_COLOR_SCALE["max"], "fixed": True}, "triangleCount": len(triangles),
                  "contourLevelCount": len(payload["contour_levels"]),
                  "contourSegmentCount": sum(len(level["segments_mm"]) for level in payload["contour_levels"]),
                  "vectorCues": _direction_cues(payload, level_stride=2)}
        write_json(receipt, result)
        return result


def frame_layer_path(run_id: str, index: int, layer: str) -> Path:
    if layer not in LAYER_NAMES:
        raise ValueError("Unknown field layer")
    prepare_frame(run_id, index)
    return frame_folder(run_id, index)/(layer+".webp")
