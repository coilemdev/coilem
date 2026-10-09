"""Public API gates for the linear Halbach topology."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.public_routes.halbach as halbach_routes
from backend.gmsh_solver import GMSH_AVAILABLE
from backend.halbach.linear_geometry import LINEAR_MODEL_NOTICE
from backend.public_main import PUBLIC_API_PATHS

ROOT = Path(__file__).parents[1]
EXAMPLE = (
    ROOT
    / "schemas"
    / "v1"
    / "examples"
    / "linear_halbach_array_4_period.json"
)
requires_gmsh = pytest.mark.skipif(not GMSH_AVAILABLE, reason="Gmsh is required")


def _payload() -> dict:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["solve"]["quality"] = "quick"
    return payload


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(halbach_routes.router)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        yield test_client


def test_capability_and_preview_expose_linear_topology(
    client: TestClient,
) -> None:
    capability = halbach_routes.halbach_capability_payload()
    assert capability["array_types"] == ["cylindrical", "linear"]
    assert capability["linear"]["blocks_per_period"] == 4

    response = client.post("/halbach/linear/preview", json=_payload())
    assert response.status_code == 200
    result = response.json()
    assert result["kind"] == "linear_halbach_preview"
    assert result["geometry"]["application_kind"] == "linear_halbach_array"
    assert result["design_health"]["ready_to_solve"] is True
    assert result["design_health"]["analytics"]["block_count"] == 16
    assert LINEAR_MODEL_NOTICE in {
        warning["message"] for warning in result["design_health"]["warnings"]
    }


def test_linear_validation_returns_field_addressable_errors(
    client: TestClient,
) -> None:
    payload = _payload()
    payload["geometry"]["block_width"] = 0
    response = client.post("/halbach/linear/solve/validate", json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["valid"] is False
    assert any(
        error["field"] == "geometry.block_width" for error in result["errors"]
    )


def test_linear_validation_accepts_ui_custom_material_payload(
    client: TestClient,
) -> None:
    payload = _payload()
    payload["magnet"] = {
        "source": "custom",
        "name": "Custom NdFeB",
        "remanence_t": 1.3,
        "relative_permeability": 1.05,
        "temperature_c": 20.0,
        "reference_temperature_c": 20.0,
        "source_note": "User-entered material parameters.",
    }

    response = client.post("/halbach/linear/solve/validate", json=payload)

    assert response.status_code == 200
    assert response.json()["valid"] is True


@requires_gmsh
def test_linear_mesh_preview_retains_groups_and_hashes(
    client: TestClient,
) -> None:
    response = client.post("/halbach/linear/mesh-preview", json=_payload())
    assert response.status_code == 200
    result = response.json()
    assert result["kind"] == "linear_halbach_mesh_preview"
    assert len(result["triangles"]) == len(result["regions"])
    assert {"exterior_air", "magnet_000", "magnet_015"} <= set(
        result["physical_groups"]
    )
    assert result["geometry_hash"]
    assert result["magnetostatic_problem_sha256"]


def test_linear_direct_and_stream_routes_share_report_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = {
        "openem_schema_kind": "linear_halbach_solution_report",
        "openem_schema_version": "1.0",
    }

    def fake_solve(_config, *, progress_callback=None):
        if progress_callback is not None:
            progress_callback("Generating rectangular Gmsh mesh", 0.25)
        return SimpleNamespace(linear_halbach_report=report)

    monkeypatch.setattr(halbach_routes, "solve_linear_halbach", fake_solve)
    direct = client.post("/halbach/linear/solve", json=_payload())
    assert direct.status_code == 200
    assert direct.json() == report

    stream = client.post("/halbach/linear/solve/stream", json=_payload())
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in stream.text
    assert "event: complete" in stream.text
    assert '"openem_schema_kind":"linear_halbach_solution_report"' in stream.text


def test_public_allowlist_contains_linear_halbach_surface() -> None:
    assert {
        "/halbach/linear/preview",
        "/halbach/linear/mesh-preview",
        "/halbach/linear/solve/validate",
        "/halbach/linear/solve",
        "/halbach/linear/solve/stream",
    } <= PUBLIC_API_PATHS
