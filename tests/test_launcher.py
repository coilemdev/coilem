"""`coilem` launcher: port precedence and fallback, second launch and the root lock."""

from __future__ import annotations

import errno
import json
import socket
import socketserver
import threading
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend import __version__, launcher
from backend.launcher import LaunchError, RunningCoilem


def test_port_precedence_and_validation() -> None:
    assert launcher.requested_port(None, {}) is None
    assert launcher.requested_port(None, {"COILEM_LOCAL_API_PORT": ""}) is None
    assert launcher.requested_port(None, {"COILEM_LOCAL_API_PORT": "9001"}) == 9001
    assert launcher.requested_port(9002, {"COILEM_LOCAL_API_PORT": "9001"}) == 9002
    with pytest.raises(LaunchError, match="integer"):
        launcher.requested_port(None, {"COILEM_LOCAL_API_PORT": "eighty"})
    with pytest.raises(LaunchError, match="--port"):
        launcher.requested_port(0, {})
    with pytest.raises(LaunchError, match="COILEM_LOCAL_API_PORT"):
        launcher.requested_port(None, {"COILEM_LOCAL_API_PORT": "65536"})


def test_default_port_range_is_fixed() -> None:
    assert launcher.DEFAULT_PORT == 2645
    assert list(launcher.FALLBACK_PORTS) == list(range(2645, 2655))


def test_bind_errors_that_mean_occupied() -> None:
    assert launcher.port_unavailable(OSError(errno.EADDRINUSE, "in use"), windows=False)
    assert not launcher.port_unavailable(OSError(errno.EACCES, "denied"), windows=False)
    # Hyper-V/WSL excluded ranges report access denied on Windows.
    assert launcher.port_unavailable(OSError(errno.EACCES, "denied"), windows=True)
    assert launcher.port_unavailable(OSError(10013, "WSAEACCES"), windows=True)
    assert not launcher.port_unavailable(OSError(errno.EINVAL, "invalid"), windows=True)


def test_bind_loopback_refuses_a_port_another_program_holds() -> None:
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        assert launcher.bind_loopback(holder.getsockname()[1]) is None


def test_bind_loopback_listens_on_loopback_only() -> None:
    with socket.socket() as finder:
        finder.bind(("127.0.0.1", 0))
        port = finder.getsockname()[1]
    sock = launcher.bind_loopback(port)
    assert sock is not None
    try:
        assert sock.getsockname() == ("127.0.0.1", port)
    finally:
        sock.close()


class _FakeSocket:
    def __init__(self, port: int) -> None:
        self.port = port


def _simulate(monkeypatch, *, free: set[int], found: dict[int, RunningCoilem | bool]) -> None:
    monkeypatch.setattr(launcher, "bind_loopback", lambda port: _FakeSocket(port) if port in free else None)
    monkeypatch.setattr(launcher, "probe", lambda port: found.get(port, True))


def test_default_port_falls_back_within_the_range(monkeypatch) -> None:
    other_root = RunningCoilem(2646, __version__, "another-root")
    _simulate(monkeypatch, free={2648, 2649}, found={2645: True, 2646: other_root, 2647: True})
    sock, running = launcher.claim_port(None, "this-root")
    assert running is None and sock.port == 2648


def test_default_port_range_exhausted(monkeypatch) -> None:
    _simulate(monkeypatch, free=set(), found={})
    with pytest.raises(LaunchError, match="2645-2654 are all in use"):
        launcher.claim_port(None, "this-root")


def test_explicit_port_never_falls_back(monkeypatch) -> None:
    _simulate(monkeypatch, free={2646}, found={9000: True})
    with pytest.raises(LaunchError, match="Port 9000 is already in use"):
        launcher.claim_port(9000, "this-root")
    _simulate(monkeypatch, free={2646}, found={9000: RunningCoilem(9000, __version__, "another-root")})
    with pytest.raises(LaunchError, match="Port 9000 is already in use"):
        launcher.claim_port(9000, "this-root")


@pytest.mark.parametrize("explicit", [None, 2645])
def test_running_coilem_on_the_port_is_reported(monkeypatch, explicit) -> None:
    same_root = RunningCoilem(2645, __version__, "this-root")
    _simulate(monkeypatch, free=set(), found={2645: same_root})
    assert launcher.claim_port(explicit, "this-root") == (None, same_root)
    other_version = RunningCoilem(2645, "9.9.9", "another-root")
    _simulate(monkeypatch, free=set(), found={2645: other_version})
    assert launcher.claim_port(explicit, "this-root") == (None, other_version)


def test_second_launch_opens_the_running_server(monkeypatch, capsys) -> None:
    opened: list[str] = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    running = RunningCoilem(2647, __version__, "this-root")
    assert launcher.reuse_running(running, open_browser=True) == 0
    assert opened == ["http://127.0.0.1:2647"]
    assert launcher.reuse_running(running, open_browser=False) == 0
    assert opened == ["http://127.0.0.1:2647"]
    assert "already running at http://127.0.0.1:2647" in capsys.readouterr().out


def test_a_different_running_version_is_reported_not_replaced(monkeypatch, capsys) -> None:
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: pytest.fail("must not open"))
    assert launcher.reuse_running(RunningCoilem(2645, "9.9.9", "this-root"), open_browser=True) == 1
    error = capsys.readouterr().err
    assert "coilEM 9.9.9 is already running" in error and f"this is coilEM {__version__}" in error


def _health_server(payload: object, status: int = 200) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    class Server(ThreadingHTTPServer):
        def server_bind(self) -> None:
            # Skip HTTPServer's reverse-DNS lookup of the bound name, which can take seconds.
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address[:2]

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_probe_distinguishes_coilem_other_programs_and_free_ports() -> None:
    coilem = _health_server({"status": "ok", "mode": "local", "solver": "magneto2d", "version": "0.2.0", "user_data_root_id": "abc"})
    other = _health_server({"status": "ok"})
    try:
        assert launcher.probe(coilem.server_port) == RunningCoilem(coilem.server_port, "0.2.0", "abc")
        assert launcher.probe(other.server_port) is True
    finally:
        coilem.shutdown()
        other.shutdown()
    with socket.socket() as finder:
        finder.bind(("127.0.0.1", 0))
        free_port = finder.getsockname()[1]
    assert launcher.probe(free_port) is False


def test_root_lock_admits_one_launcher(tmp_path: Path) -> None:
    first = launcher.acquire_root_lock(tmp_path / "root")
    assert first is not None
    try:
        assert launcher.acquire_root_lock(tmp_path / "root") is None
    finally:
        first.close()
    again = launcher.acquire_root_lock(tmp_path / "root")
    assert again is not None
    again.close()


def test_record_round_trip(tmp_path: Path) -> None:
    assert launcher.recorded_port(tmp_path) is None
    launcher.write_record(tmp_path, 2646)
    assert launcher.recorded_port(tmp_path) == 2646
    assert json.loads((tmp_path / launcher.RECORD_FILE).read_text())["version"] == __version__


def test_locked_root_reuses_the_recorded_server(monkeypatch, tmp_path: Path) -> None:
    from backend import solve_workspace

    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr("backend.resources.ui_bundle_root", lambda: tmp_path)
    root_id = solve_workspace.user_data_root_id()
    holder = launcher.acquire_root_lock(tmp_path)
    launcher.write_record(tmp_path, 9100)
    monkeypatch.setattr(launcher, "probe", lambda port: RunningCoilem(port, __version__, root_id) if port == 9100 else False)
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)
    try:
        assert launcher.launch(Namespace(port=None, no_browser=True)) == 0
    finally:
        holder.close()


def test_missing_ui_bundle_is_a_clear_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr("backend.resources.ui_bundle_root", lambda: None)
    assert launcher.main(["--no-browser"]) == 1
    assert "no built UI" in capsys.readouterr().err
