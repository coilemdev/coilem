"""Frozen design portability and opt-in API boundaries."""
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.experimental.outrunner_project import OutrunnerProject
from backend.public_main import create_app


def test_bundled_coilem_roundtrip_preserves_exact_fixture_and_settings():
    path = Path(__file__).resolve().parents[1]/"frontend/src/public/outrunner/lrk_12s14p.coilem"
    project = OutrunnerProject.model_validate_json(path.read_text())
    restored = OutrunnerProject.model_validate_json(project.model_dump_json())
    assert restored == project
    assert len(project.fixture_data["labels"]) == 29
    assert project.analysis.loaded_currents_A == [0, 4, -4]
    assert project.analysis.unique_samples == 48


@pytest.mark.parametrize("change", ["geometry", "steel", "hash", "unknown"])
def test_changed_frozen_definition_is_rejected(change):
    raw = deepcopy(OutrunnerProject().model_dump())
    if change == "geometry":
        raw["fixture_data"]["labels"][0]["x_mm"] = 123
    elif change == "steel":
        raw["fixture_data"]["materials"][3]["bh_points_T_A_per_m"][1][1] += 1
    elif change == "hash":
        raw["source_sha256"] = "0"*64
    else:
        raw["stator"] = {"OD_mm": 100}
    with pytest.raises(ValidationError):
        OutrunnerProject.model_validate(raw)


def test_routes_are_absent_by_default_and_preview_requires_exact_inputs(monkeypatch):
    monkeypatch.delenv("COILEM_EXPERIMENTAL_OUTRUNNER", raising=False)
    app = create_app()
    assert not any(path.startswith("/experimental/outrunner") for path in app.openapi()["paths"])
    monkeypatch.setenv("COILEM_EXPERIMENTAL_OUTRUNNER", "1")
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    project = OutrunnerProject().model_dump()
    response = client.post("/experimental/outrunner/preview", json=project)
    assert response.status_code == 200, response.text
    regions = response.json()["regions"]
    assert sum(region["kind"] == "Magnet" for region in regions) == 14
    assert sum(region["kind"] == "SlotWinding" for region in regions) == 12
    project["fixture_data"]["labels"] = []
    assert client.post("/experimental/outrunner/preview", json=project).status_code == 422
    assert client.get("/experimental/outrunner/runs/not-a-run-id").status_code == 404
