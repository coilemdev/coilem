"""``coilem``: serve the built UI and the local API, then open the browser.

Port policy. ``--port`` and ``COILEM_LOCAL_API_PORT`` are used exactly and fail
when occupied. Otherwise the stable default 2645 is used, falling back within
2645-2654 when another program holds it. The fallback is never remembered:
browser-saved state (Halbach autosaves, tutorial progress) is scoped to the
origin, port included, which is also why the launcher always opens
``http://127.0.0.1:<port>`` and never ``localhost``.

One server runs per user-data root, enforced by a lock file there. A second
launch opens the browser at the running server and exits instead of starting
another; a running server of a different coilEM version is reported.

The launcher binds the listening socket itself and hands it to uvicorn, so the
port cannot be taken between selection and serving. Ctrl+C stops accepting
work and cancels active solver processes; a second Ctrl+C forces exit.
"""

from __future__ import annotations

import argparse
import errno
import http.client
import json
import os
import signal
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from backend import __version__

DEFAULT_PORT = 2645  # "COIL" on a phone keypad. Never change it: saved state is per origin.
FALLBACK_PORTS = range(DEFAULT_PORT, DEFAULT_PORT + 10)
LOCK_FILE = "launcher.lock"
RECORD_FILE = "launcher.json"
PROBE_TIMEOUT_S = 2.0
# Windows can take just over two seconds to report WSAECONNREFUSED.
PROBE_CONNECT_TIMEOUT_S = 5.0 if os.name == "nt" else PROBE_TIMEOUT_S
READY_TIMEOUT_S = 60.0
RUNNING_INSTANCE_WAIT_S = 10.0
GRACEFUL_SHUTDOWN_S = 10
SHUTDOWN_DEADLINE_S = 20.0
_WSAEACCES = 10013


class LaunchError(Exception):
    """A launch failure reported to the user as one message."""


@dataclass(frozen=True)
class RunningCoilem:
    port: int
    version: str
    user_data_root_id: str | None


def bound_url(port: int) -> str:
    from backend.public_security import bound_ui_origin

    return bound_ui_origin(port)


def requested_port(cli_port: int | None, environ: Mapping[str, str] = os.environ) -> int | None:
    """Return an exact port from ``--port`` or ``COILEM_LOCAL_API_PORT``, else ``None``."""

    if cli_port is not None:
        port, source = cli_port, "--port"
    elif environ.get("COILEM_LOCAL_API_PORT"):
        source = "COILEM_LOCAL_API_PORT"
        try:
            port = int(environ["COILEM_LOCAL_API_PORT"])
        except ValueError as exc:
            raise LaunchError("COILEM_LOCAL_API_PORT must be an integer.") from exc
    else:
        return None
    if not 1 <= port <= 65535:
        raise LaunchError(f"{source} must be between 1 and 65535.")
    return port


def probe(port: int) -> RunningCoilem | bool:
    """Return the coilEM serving ``port``, ``True`` for another program, ``False`` if nothing listens."""

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=PROBE_CONNECT_TIMEOUT_S)
    try:
        try:
            connection.connect()
        except ConnectionRefusedError:
            return False
        except OSError:
            # A timeout or access denial does not establish that the port is free.
            return True
        try:
            assert connection.sock is not None
            connection.sock.settimeout(PROBE_TIMEOUT_S)
            connection.request("GET", "/health", headers={"Accept": "application/json"})
            response = connection.getresponse()
            body = response.read(1_000_000)
        except (OSError, http.client.HTTPException):
            return True
    finally:
        connection.close()
    try:
        payload = json.loads(body)
    except ValueError:
        return True
    if (
        response.status != 200
        or not isinstance(payload, dict)
        or payload.get("solver") != "magneto2d"
        or payload.get("mode") != "local"
        or not isinstance(payload.get("version"), str)
    ):
        return True
    root_id = payload.get("user_data_root_id")
    return RunningCoilem(port, payload["version"], root_id if isinstance(root_id, str) else None)


def port_unavailable(exc: OSError, *, windows: bool = os.name == "nt") -> bool:
    """Whether a bind error means another program holds the port."""

    if exc.errno == errno.EADDRINUSE:
        return True
    # Windows reports ports in a Hyper-V/WSL excluded range as access denied
    # (`netsh interface ipv4 show excludedportrange protocol=tcp`).
    return windows and (exc.errno in {errno.EACCES, _WSAEACCES} or getattr(exc, "winerror", None) == _WSAEACCES)


def bind_loopback(port: int) -> socket.socket | None:
    """Listen on ``127.0.0.1:port``; ``None`` when another program holds the port."""

    if os.name != "nt" and not sys.platform.startswith("linux") and probe(port) is not False:
        # BSD/macOS let a specific-address bind coexist with another program's
        # wildcard listener; Linux and Windows refuse that bind themselves.
        return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            # Rebind over TIME_WAIT after a restart instead of falling back.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(2048)
    except OSError as exc:
        sock.close()
        if port_unavailable(exc):
            return None
        raise LaunchError(f"Cannot listen on 127.0.0.1:{port}: {exc.strerror or exc}") from exc
    return sock


def acquire_root_lock(root: Path) -> IO[bytes] | None:
    """Hold the user-data root's launcher lock for this process; ``None`` if taken."""

    root.mkdir(parents=True, exist_ok=True)
    handle = open(root / LOCK_FILE, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def write_record(root: Path, port: int) -> None:
    temporary = root / f"{RECORD_FILE}.{os.getpid()}.tmp"
    temporary.write_text(json.dumps({"port": port, "pid": os.getpid(), "version": __version__}), encoding="utf-8")
    os.replace(temporary, root / RECORD_FILE)


def recorded_port(root: Path) -> int | None:
    try:
        port = json.loads((root / RECORD_FILE).read_text(encoding="utf-8")).get("port")
    except (OSError, ValueError, AttributeError):
        return None
    return port if isinstance(port, int) and 1 <= port <= 65535 else None


def reuse_running(found: RunningCoilem, *, open_browser: bool, exact_port: int | None = None) -> int:
    """Open a same-root, same-version server; report a different version."""

    url = bound_url(found.port)
    if found.version != __version__:
        print(
            f"coilem: coilEM {found.version} is already running at {url}; this is coilEM {__version__}.\n"
            "Stop the running copy first; use a different COILEM_USER_DATA_ROOT and --port for a separate instance.",
            file=sys.stderr,
        )
        return 1
    if exact_port is not None and found.port != exact_port:
        raise LaunchError(
            f"coilEM is already running at {url} using this data folder; requested port {exact_port} cannot be used. "
            "Stop the running copy first, or set COILEM_USER_DATA_ROOT to use a different folder."
        )
    print(f"coilEM {found.version} is already running at {url}")
    if open_browser:
        webbrowser.open(url)
    return 0


def _wait_for_locked_instance(root: Path, root_id: str) -> RunningCoilem | None:
    """Find the server holding this root's lock; it may still be starting."""

    deadline = time.monotonic() + RUNNING_INSTANCE_WAIT_S
    while True:
        port = recorded_port(root)
        if port is not None:
            found = probe(port)
            if isinstance(found, RunningCoilem) and found.user_data_root_id == root_id:
                return found
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)


def claim_port(explicit: int | None, root_id: str) -> tuple[socket.socket | None, RunningCoilem | None]:
    """Bind the requested or default port, or return the coilEM found holding it."""

    for port in (explicit,) if explicit is not None else FALLBACK_PORTS:
        sock = bind_loopback(port)
        if sock is not None:
            return sock, None
        found = probe(port)
        if isinstance(found, RunningCoilem) and (found.version != __version__ or found.user_data_root_id == root_id):
            return None, found
        if explicit is not None:
            raise LaunchError(f"Port {port} is already in use. Choose another with --port.")
    raise LaunchError(
        f"Ports {FALLBACK_PORTS.start}-{FALLBACK_PORTS.stop - 1} are all in use. Choose a free port with --port."
    )


def _shutdown_native_work() -> None:
    from backend.magneto2d_adapter import shutdown_native_processes
    from backend.public_routes.solve import request_active_solve_cancellation

    try:
        request_active_solve_cancellation()
    finally:
        shutdown_native_processes()


def _force_exit(code: int) -> None:
    # Never take solver locks on the signal-handling thread: it may hold them.
    worker = threading.Thread(target=_shutdown_native_work, daemon=True)
    worker.start()
    worker.join(2.0)
    os._exit(code)


def _exit_after_deadline() -> None:
    time.sleep(SHUTDOWN_DEADLINE_S)
    print(f"coilem: shutdown took longer than {SHUTDOWN_DEADLINE_S:g} s; exiting.", file=sys.stderr, flush=True)
    _force_exit(1)


def _launcher_server_class() -> type:
    import uvicorn

    class LauncherServer(uvicorn.Server):
        def handle_exit(self, sig: int, frame: Any) -> None:
            if self.should_exit and sig == signal.SIGINT:
                print("\ncoilem: forced exit.", file=sys.stderr, flush=True)
                _force_exit(130)
            if not self.should_exit:
                print("\ncoilem: stopping; cancelling active solves (Ctrl+C again to force).", file=sys.stderr, flush=True)
                threading.Thread(target=_shutdown_native_work, daemon=True).start()
                threading.Thread(target=_exit_after_deadline, daemon=True).start()
            super().handle_exit(sig, frame)

    return LauncherServer


def _announce_when_ready(server: Any, port: int, root_id: str, *, open_browser: bool) -> None:
    url = bound_url(port)
    deadline = time.monotonic() + READY_TIMEOUT_S
    while not server.should_exit:
        found = probe(port)
        if isinstance(found, RunningCoilem) and found.user_data_root_id == root_id:
            print(f"coilEM {__version__} is running at {url} (Ctrl+C to stop)", flush=True)
            if open_browser:
                webbrowser.open(url)
            return
        if time.monotonic() >= deadline:
            print(f"coilem: the server did not answer at {url} within {READY_TIMEOUT_S:g} s.", file=sys.stderr, flush=True)
            return
        time.sleep(0.1)


def _raise_exit(signum: int, frame: Any) -> None:
    raise SystemExit(128 + signum)


def serve(sock: socket.socket, port: int, ui_bundle: Path, root_id: str, *, open_browser: bool) -> int:
    import uvicorn

    from backend.public_main import create_app

    app = create_app(bound_port=port, ui_bundle=ui_bundle)
    config = uvicorn.Config(
        app,
        log_level="info",
        access_log=False,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
    )
    server = _launcher_server_class()(config)
    threading.Thread(
        target=_announce_when_ready,
        args=(server, port, root_id),
        kwargs={"open_browser": open_browser},
        daemon=True,
    ).start()
    # uvicorn re-raises the signal that stopped it once shutdown completes.
    # Turn termination requests into an exit that still runs cleanup.
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _raise_exit)
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    return 0


def launch(args: argparse.Namespace) -> int:
    from backend.resources import ui_bundle_root
    from backend.solve_workspace import user_data_root, user_data_root_id

    explicit = requested_port(args.port)
    ui_bundle = ui_bundle_root()
    if ui_bundle is None:
        raise LaunchError(
            "this installation has no built UI. In a source checkout, run `npm ci` and "
            "`npm run build` in frontend/, or use the development servers in the README."
        )
    root = user_data_root()
    root_id = user_data_root_id()
    open_browser = not args.no_browser

    lock = acquire_root_lock(root)
    if lock is None:
        found = _wait_for_locked_instance(root, root_id)
        if found is None:
            raise LaunchError(
                f"another coilEM is using the data folder {root} but does not answer. "
                "Stop it, or set COILEM_USER_DATA_ROOT to use a different folder."
            )
        return reuse_running(found, open_browser=open_browser, exact_port=explicit)
    try:
        sock, found = claim_port(explicit, root_id)
        if found is not None:
            return reuse_running(found, open_browser=open_browser, exact_port=explicit)
        assert sock is not None
        port = sock.getsockname()[1]
        if explicit is None and port != DEFAULT_PORT:
            print(
                f"coilem: port {DEFAULT_PORT} is in use, so coilEM is using port {port}. "
                "Halbach autosaves and tutorial progress saved in your browser belong to "
                f"http://127.0.0.1:{DEFAULT_PORT} and are not available on this port.",
                file=sys.stderr,
            )
        write_record(root, port)
        try:
            return serve(sock, port, ui_bundle, root_id, open_browser=open_browser)
        finally:
            (root / RECORD_FILE).unlink(missing_ok=True)
    finally:
        lock.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coilem", description="Start coilEM and open it in your browser.")
    parser.add_argument(
        "--port",
        type=int,
        help=f"serve on exactly this loopback port (default {DEFAULT_PORT}, falling back within "
        f"{FALLBACK_PORTS.start}-{FALLBACK_PORTS.stop - 1})",
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--version", action="version", version=f"coilEM {__version__}")
    args = parser.parse_args(argv)
    try:
        return launch(args)
    except LaunchError as exc:
        print(f"coilem: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # before the server took over signal handling
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
