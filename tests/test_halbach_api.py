"""HAL-07 public API, streaming, and durable-export contracts."""

from __future__ import annotations

import copy
import csv
import io
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.public_routes.halbach as halbach_routes
from backend.gmsh_solver import GMSH_AVAILABLE
from backend.halbach.geometry import AXIAL_END_EFFECTS_NOTICE
from backend.halbach.models import HalbachArrayConfig
from backend.halbach.solver import solve_halbach
from backend.public_main import PUBLIC_API_PATHS

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "schemas" / "v1" / "examples" / "halbach_array_16_segment.json"
requires_gmsh = pytest.mark.skipif(not GMSH_AVAILABLE, reason="Gmsh is required")


def _payload() -> dict:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["solve"]["quality"] = "quick"
    payload["sample_region"]["radial_samples"] = 5
    payload["sample_region"]["angular_samples"] = 16
    return payload


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(halbach_routes.router)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        yield test_client


@pytest.fixture(scope="module")
def solved_report() -> dict:
    if not GMSH_AVAILABLE:
        pytest.skip("Gmsh is required")
    return solve_halbach(HalbachArrayConfig.model_validate(_payload())).halbach_report


def _minimal_export_report() -> dict:
    """A schema-valid export input that needs no native solver or user data."""
    from backend.halbach.solver import HALBACH_REPORT_SCHEMA

    report = {key: {} for key in HALBACH_REPORT_SCHEMA["required"]}
    report.update(
        openem_schema_kind="halbach_solution_report",
        openem_schema_version="1.0",
        configuration=json.loads(EXAMPLE.read_text(encoding="utf-8")),
        peak_memory_bytes=None,
        warnings=[],
    )
    report["model"] = {
        "formulation": "planar_az",
        "assumption": "infinite_length_extruded_2d",
        "axial_end_effects_modeled": False,
        "axial_length_usage": ["extruded_2d_estimates"],
        "notice": AXIAL_END_EFFECTS_NOTICE,
    }
    report["artifacts"] = {
        "magnetostatic_problem_sha256": "0" * 64,
        "generic_field_report_input_sha256": None,
        "geometry_hash": "0" * 64,
        "mesh_hash": "0" * 64,
    }
    for section in ("bore_field", "external_leakage", "magnet", "energy", "field_data"):
        report[section] = {
            key: 0 for key in HALBACH_REPORT_SCHEMA["properties"][section]["required"]
        }
    report["bore_field"]["b_parallel_t"] = {"mean": 1.0}
    report["samples"] = {"bore": [], "leakage": []}
    report["magnetostatic_problem"] = {
        "kind": "magnetostatic_problem",
        "version": "1.0",
        "units": {"length": "mm"},
        "mesh": {"nodes": [[0, 0], [1, 0], [0, 1]], "triangles": [[0, 1, 2]]},
        "materials": [{"kind": "linear", "mu_r": 1}],
        "elements": [{"material_id": 0}],
        "boundaries": {"dirichlet_az_zero_nodes": [0]},
    }
    return report


@pytest.mark.parametrize("untrusted_text", ["=1+1", "+1+1", "-1+1", "@SUM(1,1)", "\t=1+1", "\r=1+1"])
def test_csv_export_neutralizes_submitted_formula_cells(
    client: TestClient,
    untrusted_text: str,
) -> None:
    report = _minimal_export_report()
    report["samples"]["bore"] = [{"x_mm": untrusted_text, "y_mm": -1.25}]
    original = copy.deepcopy(report)

    response = client.post("/halbach/export/csv", json={"report": report})

    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"), newline="")))
    sample = next(row for row in rows if row and row[0] == "bore")
    assert sample[2] == "'" + untrusted_text
    assert sample[3] == "-1.25"
    assert report == original


@pytest.mark.parametrize("section", ["timings_ms", "artifacts"])
def test_pdf_export_renders_submitted_markup_as_text_without_loading_images(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
) -> None:
    pypdf = pytest.importorskip("pypdf")
    report = _minimal_export_report()
    sentinel = tmp_path / "local-audit-sentinel.png"
    sentinel.write_bytes(b"local data must never be opened by the PDF renderer")
    markup = f"<img src='{sentinel}' width='4' height='4'/>"
    key = "untrusted" if section == "timings_ms" else "generic_field_report_input_sha256"
    report[section][key] = markup
    original = copy.deepcopy(report)
    image_reads = []

    def reject_image_read(source):
        image_reads.append(source)
        raise AssertionError("Report text must not invoke an image loader")

    monkeypatch.setattr("reportlab.platypus.paraparser.ImageReader", reject_image_read)

    response = client.post("/halbach/export/pdf", json={"report": report})

    assert response.status_code == 200
    reader = pypdf.PdfReader(io.BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "<img" in text
    assert sum(len(page.images) for page in reader.pages) == 0
    assert image_reads == []
    assert report == original
    assert sentinel.read_bytes() == b"local data must never be opened by the PDF renderer"


def test_preview_returns_neutral_geometry_material_and_design_health(
    client: TestClient,
) -> None:
    response = client.post("/halbach/preview", json=_payload())
    assert response.status_code == 200
    result = response.json()
    assert result["kind"] == "halbach_preview"
    assert result["geometry"]["application_kind"] == "halbach_array"
    assert result["design_health"]["ready_to_solve"] is True
    assert AXIAL_END_EFFECTS_NOTICE in {
        warning["message"] for warning in result["design_health"]["warnings"]
    }
    serialized = json.dumps(result).lower()
    assert '"pole_count"' not in serialized
    assert '"slot_count"' not in serialized


def test_preview_rejects_unknown_fields(client: TestClient) -> None:
    payload = _payload()
    payload["geometry"]["invented_motor_field"] = 12
    response = client.post("/halbach/preview", json=payload)
    assert response.status_code == 422


def test_validate_returns_field_addressable_errors(client: TestClient) -> None:
    payload = _payload()
    payload["geometry"]["outer_radius"] = payload["geometry"]["inner_radius"]
    response = client.post("/halbach/solve/validate", json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["valid"] is False
    assert any(
        error["field"] == "geometry"
        and "geometry.outer_radius" in error["message"]
        for error in result["errors"]
    )


@requires_gmsh
def test_mesh_preview_retains_groups_and_problem_hash(client: TestClient) -> None:
    response = client.post("/halbach/mesh-preview", json=_payload())
    assert response.status_code == 200
    result = response.json()
    assert result["kind"] == "halbach_mesh_preview"
    assert len(result["triangles"]) == len(result["regions"])
    assert {"bore_air", "exterior_air", "magnet_00"} <= set(
        result["physical_groups"]
    )
    assert result["magnetostatic_problem_sha256"]
    assert result["geometry_hash"]


def test_solve_and_stream_share_the_same_report_contract(
    client: TestClient,
    solved_report: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_solve(_config, *, progress_callback=None):
        if progress_callback is not None:
            progress_callback("Generating Gmsh mesh", 0.25)
            progress_callback("Preparing report", 0.98)
        return SimpleNamespace(halbach_report=solved_report)

    monkeypatch.setattr(halbach_routes, "solve_halbach", fake_solve)
    direct = client.post("/halbach/solve", json=_payload())
    assert direct.status_code == 200
    assert direct.json()["openem_schema_kind"] == "halbach_solution_report"

    stream = client.post("/halbach/solve/stream", json=_payload())
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in stream.text
    assert "Generating Gmsh mesh" in stream.text
    assert "event: complete" in stream.text
    assert '"openem_schema_kind":"halbach_solution_report"' in stream.text


@pytest.mark.parametrize(
    ("kind", "content_type", "filename"),
    [
        ("report", "application/json", "halbach-solution-report.json"),
        ("problem", "application/json", "magnetostatic-problem.json"),
        ("field", "application/json", "field-solution-report.json"),
        ("csv", "text/csv", "halbach-field-samples.csv"),
        ("svg", "image/svg+xml", "halbach-field-plot.svg"),
        ("png", "image/png", "halbach-field-plot.png"),
        ("pdf", "application/pdf", "halbach-report.pdf"),
    ],
)
def test_exports_are_downloadable_and_retain_model_notice(
    client: TestClient,
    solved_report: dict,
    kind: str,
    content_type: str,
    filename: str,
) -> None:
    response = client.post(f"/halbach/export/{kind}", json={"report": solved_report})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert filename in response.headers["content-disposition"]
    if kind == "csv":
        assert AXIAL_END_EFFECTS_NOTICE.encode("utf-8") in response.content
    elif kind == "svg":
        assert AXIAL_END_EFFECTS_NOTICE.encode("utf-8") in response.content
    elif kind == "png":
        assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    elif kind == "pdf":
        assert response.content.startswith(b"%PDF")
    else:
        assert json.loads(response.content)


def test_exports_fail_closed_when_notice_is_removed(
    client: TestClient,
    solved_report: dict,
) -> None:
    report = copy.deepcopy(solved_report)
    report["model"]["notice"] = "finite design"
    response = client.post("/halbach/export/report", json={"report": report})
    assert response.status_code == 400
    assert "permanent axial-end-effect notice" in response.json()["detail"]


def test_export_rejects_report_that_fails_the_versioned_schema(
    client: TestClient,
    solved_report: dict,
) -> None:
    report = copy.deepcopy(solved_report)
    report["openem_schema_kind"] = "hand_edited_result"
    response = client.post("/halbach/export/report", json={"report": report})
    assert response.status_code == 400
    assert "Invalid Halbach report" in response.json()["detail"]


def test_pdf_export_handles_nullable_uniformity_and_leakage_ratio(
    client: TestClient,
    solved_report: dict,
) -> None:
    report = copy.deepcopy(solved_report)
    report["bore_field"]["uniformity_ppm"] = None
    report["external_leakage"]["leakage_ratio_rms"] = None
    response = client.post("/halbach/export/pdf", json={"report": report})
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_public_api_allowlist_contains_complete_halbach_surface() -> None:
    assert {
        "/halbach/preview",
        "/halbach/mesh-preview",
        "/halbach/solve/validate",
        "/halbach/solve",
        "/halbach/solve/stream",
        "/halbach/export/{export_kind}",
    } <= PUBLIC_API_PATHS
