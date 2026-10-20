"""Performance routes (#139–#141): map status, the streamed map run and the drive envelope."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from backend.public_main import app
from backend.public_routes import solve as solve_routes
from tests.test_flux_linkage_map import RAW, FakeSolver


class FakePublicSolver:
    def __init__(self):
        self.solve = FakeSolver()
        self.cancelled = False

    def cancel_active_solve(self):
        self.cancelled = True


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    fake = FakePublicSolver()
    monkeypatch.setattr(solve_routes, "_create_public_solver", lambda *args, **kwargs: fake)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        test_client.fake = fake
        yield test_client


def _body(**map_settings):
    return {"request": {"config": deepcopy(RAW)}, "map": {"preset": "preview", "peak_current_A": 20.0, **map_settings}}


def _events(text: str) -> list[tuple[str, dict]]:
    events, kind = [], None
    for line in text.splitlines():
        if line.startswith("event: "):
            kind = line[7:].strip()
        elif line.startswith("data: ") and kind:
            events.append((kind, json.loads(line[6:])))
            kind = None
    return events


def test_status_streamed_map_and_resume(client):
    status = client.post("/performance/map/status", json=_body()).json()
    assert (status["solves_total"], status["solves_finished"], status["map"]) == (29, 0, None)

    events = _events(client.post("/performance/map/stream", json=_body()).text)
    progress = [payload for kind, payload in events if kind == "progress" and payload.get("done")]
    assert [payload["done"] for payload in progress] == list(range(1, 30))
    assert progress[-1]["total"] == 29 and "eta_s" in progress[-1]
    kind, complete = events[-1]
    assert kind == "complete"
    assert len(complete["map"]["points"]) == 35
    assert all(value is None or value == pytest.approx(100.0) for value in complete["torque_agreement_pct"])
    assert len(client.fake.solve.calls) == 29

    status = client.post("/performance/map/status", json=_body()).json()
    assert status["solves_finished"] == 29 and status["map"]["scope_key"] == status["scope_key"]
    assert status["positions_per_point"] == 12
    # A lower peak reuses the 20 A map; a higher one, or one much lower, needs its own.
    assert client.post("/performance/map/status", json=_body(peak_current_A=15.0)).json()["map"]["current_peak_A"][-1] == 20.0
    assert client.post("/performance/map/status", json=_body(peak_current_A=30.0)).json()["map"] is None
    assert client.post("/performance/map/status", json=_body(peak_current_A=8.0)).json()["map"] is None


def test_the_map_waits_for_a_running_solve(client):
    solve_routes._claim_solve(object())
    try:
        response = client.post("/performance/map/stream", json=_body())
        assert response.status_code == 409
        assert response.json()["detail"]["error_code"] == "SOLVE_ALREADY_RUNNING"
    finally:
        solve_routes._ACTIVE_SOLVE.update(running=False, cancelled=False, solver=None, run_writer=None)


def test_bad_map_requests_are_refused(client):
    assert client.post("/performance/map/status", json={"map": {"peak_current_A": 20}}).status_code == 422
    assert client.post("/performance/map/status", json=_body(peak_current_A=-1)).status_code == 422


def test_drive_returns_the_envelope_and_efficiency_map(client):
    complete = _events(client.post("/performance/map/stream", json=_body()).text)[-1][1]
    body = {
        "map": complete["map"],
        "limits": {"dc_bus_V": 24.0, "peak_current_A": 20.0, "max_speed_rpm": 15000.0},
        "phase_resistance_ohm": 0.2,
        "winding_temperature_C": 80.0,
        "mechanical_loss_W": 1.0,
    }
    response = client.post("/performance/drive", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["envelope"]["curves"][0]["limit"] == "peak"
    assert payload["efficiency_map"]["mechanical_loss_W"] == 1.0
    body["limits"]["dc_bus_V"] = -5
    assert client.post("/performance/drive", json=body).status_code == 422
