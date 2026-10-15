"""The COILEM_EXPERIMENTAL_ROTORS launch switch: off by default, HoleM50 through the app when on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "frontend/src/public/examples/ornl_prius_2004_holem50.coilem"
PUBLIC_IPM_MESSAGE = "The public launch supports flat-buried and V-shape IPM only."


def prius_design() -> dict:
    design = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return {k: v for k, v in design.items() if k not in {"openem_schema_version", "openem_version", "name", "description"}}


def client() -> TestClient:
    from backend.public_main import app

    return TestClient(app, base_url="http://127.0.0.1")


def test_example_is_the_frozen_benchmark_request_on_a_full_cycle():
    frozen = json.loads((REPO_ROOT / "benchmarks/abcd-v1.2/fixtures/ornl_prius_2004_ipm.json").read_text(encoding="utf-8"))
    design = prius_design()
    for section in ("stator", "rotor", "winding", "materials", "solve_options"):
        assert design[section] == frozen[section]
    # A public design carries no FEMM settings; the grid covers one full electrical cycle.
    expected = {k: v for k, v in frozen["solve_params"].items() if k != "femm_workers"}
    expected.update(rotor_sweep_range_deg=360.0, torque_method="weighted_stress", linear_solver_preconditioner="direct")
    assert design["solve_params"] == expected


def test_switch_is_off_by_default(monkeypatch):
    monkeypatch.delenv("COILEM_EXPERIMENTAL_ROTORS", raising=False)
    from backend.models import MotorConfig
    from backend.qualification import classify_qualification

    health = client().get("/health").json()["capabilities"]["experimental_rotors"]
    assert health == {"enabled": False, "families": [], "switch": "COILEM_EXPERIMENTAL_ROTORS"}
    response = client().post("/solve/validate", json=prius_design())
    assert response.status_code == 400 and response.json()["detail"]["message"] == PUBLIC_IPM_MESSAGE
    assert classify_qualification(MotorConfig.model_validate(prius_design()))["status"] == "unsupported"


@pytest.mark.parametrize("value", ["1", "true", "on"])
def test_switch_lets_the_app_preview_and_validate_holem50(monkeypatch, value):
    monkeypatch.setenv("COILEM_EXPERIMENTAL_ROTORS", value)
    from backend.models import MotorConfig
    from backend.qualification import classify_qualification

    health = client().get("/health").json()["capabilities"]["experimental_rotors"]
    assert health == {"enabled": True, "families": ["pyleecan_holem50"], "switch": "COILEM_EXPERIMENTAL_ROTORS"}
    validation = client().post("/solve/validate", json=prius_design())
    assert validation.status_code == 200, validation.json()
    preview = client().post("/preview", json=prius_design())
    assert preview.status_code == 200, preview.json()
    qualification = classify_qualification(MotorConfig.model_validate(prius_design()))
    assert qualification["status"] == "experimental" and "HoleM50" in qualification["reason"]


def test_switch_admits_only_experimental_families(monkeypatch):
    monkeypatch.setenv("COILEM_EXPERIMENTAL_ROTORS", "1")
    for family in ("spoke", "barrier"):
        design = prius_design()
        design["rotor"]["ipm_topology"] = family
        response = client().post("/solve/validate", json=design)
        assert response.status_code == 400 and response.json()["detail"]["message"] == PUBLIC_IPM_MESSAGE
