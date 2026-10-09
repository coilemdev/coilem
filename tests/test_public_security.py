"""Public request provenance regressions; all effects use an in-memory solver."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.public_main import app
from backend.public_routes import solve
from backend.public_security import DEFAULT_UI_ORIGINS, public_ui_origins


@pytest.fixture
def active_solver(monkeypatch):
    class FakeSolver:
        cancelled = False

        def cancel_active_solve(self):
            self.cancelled = True

    solver = FakeSolver()
    monkeypatch.setattr(solve, "_ACTIVE_SOLVE", {
        "running": True, "cancelled": False, "solver": solver, "run_writer": None,
    })
    return solver


@pytest.mark.parametrize("origin", [
    "https://untrusted.example", "null", "", "http://127.0.0.1:5173.evil.example",
    "http://localhost:9999", "http://127.0.0.1:5173/", "http://localhost.attacker.example:5173",
])
def test_untrusted_simple_post_cannot_cancel(active_solver, origin):
    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/solve/cancel", headers={"Origin": origin, "Content-Type": "text/plain"}, content="",
    )
    assert response.status_code == 403
    assert not active_solver.cancelled
    assert not solve._ACTIVE_SOLVE["cancelled"]
    assert response.headers["vary"] == "Origin"


@pytest.mark.parametrize("host", [
    "attacker.example", "127.0.0.1.attacker.example", "localhost.attacker.example",
    "localhost@attacker.example", "127.1", "2130706433", "127.0.0.1:0",
    "localhost:65536", "localhost.", "", "::1", "127.0.0.1, attacker.example",
])
def test_untrusted_host_cannot_reach_routes(active_solver, host):
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/health", headers={"Host": host}).status_code == 400
    assert client.post("/solve/cancel", headers={"Host": host}).status_code == 400
    assert not active_solver.cancelled


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost:8000", "[::1]:8000"])
def test_loopback_cli_can_cancel(active_solver, host):
    response = TestClient(app, base_url="http://127.0.0.1").post("/solve/cancel", headers={"Host": host})
    assert response.status_code == 200
    assert active_solver.cancelled


@pytest.mark.parametrize("origin", DEFAULT_UI_ORIGINS)
def test_trusted_ui_preflight_and_action(active_solver, origin):
    client = TestClient(app, base_url="http://127.0.0.1")
    preflight = client.options("/solve/cancel", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type",
    })
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    result = client.post("/solve/cancel", headers={"Origin": origin, "Sec-Fetch-Site": "cross-site"})
    assert result.status_code == 200
    assert result.headers["access-control-allow-origin"] == origin
    assert active_solver.cancelled


@pytest.mark.parametrize("header,value", [("Host", "localhost"), ("Origin", DEFAULT_UI_ORIGINS[0])])
def test_duplicate_provenance_headers_are_rejected(active_solver, header, value):
    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/solve/cancel", headers=[(header, value), (header, value)],
    )
    assert response.status_code in {400, 403}
    assert not active_solver.cancelled


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_originless_browser_request_cannot_read_or_cancel(active_solver, site):
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"Sec-Fetch-Site": site, "Sec-Fetch-Mode": "no-cors"}
    assert client.get("/runs", headers=headers).status_code == 403
    assert client.post("/solve/cancel", headers=headers).status_code == 403
    assert not active_solver.cancelled


@pytest.mark.parametrize("origin", ["https://remote.example", "http://localhost:5173/", "null", "*", "http://localhost"])
def test_ui_origin_override_fails_closed(monkeypatch, origin):
    monkeypatch.setenv("COILEM_LOCAL_UI_ORIGIN", origin)
    with pytest.raises(ValueError, match="loopback origin"):
        public_ui_origins()


def test_ui_origin_override_is_explicit_loopback_only(monkeypatch):
    monkeypatch.setenv("COILEM_LOCAL_UI_ORIGIN", "http://127.0.0.1:54173")
    assert public_ui_origins() == (*DEFAULT_UI_ORIGINS, "http://127.0.0.1:54173")
