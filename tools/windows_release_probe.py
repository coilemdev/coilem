"""Temporary hosted Windows probes for issues #234 and #316."""

import ctypes
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from collections import deque
from pathlib import Path

from tools.release.acceptance import (
    MOTOR,
    Acceptance,
    headless_design,
    magneto2d_solving,
    sse_events,
)


def lookup() -> int:
    import gmsh

    paths = {name: shutil.which(name) for name in ("git", "node")}
    assert all(paths.values()), paths
    buffer = ctypes.create_unicode_buffer(32768)

    def native_path():
        ctypes.windll.kernel32.GetEnvironmentVariableW("PATH", buffer, len(buffer))
        return buffer.value

    before = native_path()
    expected = {}
    for name in paths:
        expected[name] = subprocess.check_output([name, "--version"], text=True).strip()
    gmsh.initialize()
    gmsh.finalize()
    print("Native PATH changed:", before != native_path())
    for name, path in paths.items():
        try:
            result = subprocess.check_output([name, "--version"], text=True).strip()
        except FileNotFoundError as error:
            print(f"{name} bare lookup failed after Gmsh: {error!r}")
        else:
            print(f"{name} bare lookup after Gmsh: {result}")
        absolute = shutil.which(name)
        assert absolute == path
        result = subprocess.check_output([absolute, "--version"], text=True).strip()
        assert result == expected[name]
        print(f"{name} absolute lookup after Gmsh: {result}")
    return 0


def interrupt(acceptance, process, ready, stage, log, expected_exit, detail):
    sent = ready.wait(120) and process.poll() is None
    if sent:
        process.send_signal(signal.CTRL_BREAK_EVENT)
    try:
        code = process.wait(timeout=60 if sent else 1)
    except subprocess.TimeoutExpired:
        code = None
        process.kill()
        process.wait(timeout=10)
    result, extra = detail()
    remaining = acceptance.solver_processes()
    passed = sent and code == expected_exit and result and not remaining
    acceptance.check(
        f"interrupt {stage}",
        passed,
        f"sent={sent}, exit={code}, remaining={remaining}, detail={extra}",
    )
    if not passed:
        for line in list(log)[-20:]:
            print("  ", line)


def cli(acceptance, stage, attempt):
    design = acceptance.work / "motor.coilem"
    design.write_text(json.dumps(headless_design()), encoding="utf-8")
    out = acceptance.work / f"cancel-{stage}-{attempt}.json"
    command = [
        str(acceptance.bin / "coilem.exe"), "solve", str(design), "--setup", "Quick torque",
        "--quality", "standard", "--mesh", "normal", "--analyses", "torque,back_emf,cogging",
        "--progress", "json", "--out", str(out),
    ]
    process = subprocess.Popen(
        command, cwd=acceptance.work, env=acceptance.env, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    ready = threading.Event()
    log = deque(maxlen=20)

    def follow():
        for line in process.stderr:
            log.append(line.rstrip())
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("stage") == stage and magneto2d_solving(
                "progress", {"stage": stage, "position": event.get("done"), "total": event.get("total")},
            ):
                ready.set()

    def detail():
        result = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        error = result.get("error") or {}
        return error.get("error_code") == "SOLVER_CANCELLED", error

    threading.Thread(target=follow, daemon=True).start()
    interrupt(acceptance, process, ready, f"CLI {stage} #{attempt}", log, 130, detail)


def launcher(acceptance, stage, attempt):
    import urllib.request

    server = acceptance.launch()
    port = []
    started = threading.Event()
    ready = threading.Event()
    log = deque(maxlen=20)

    def follow():
        for line in server.stdout:
            log.append(line.rstrip())
            match = re.search(r"is running at http://127\.0\.0\.1:(\d+)", line)
            if match:
                port.append(match[1])
                started.set()

    def stream():
        motor = json.loads(json.dumps(MOTOR))
        motor["solve_params"].update({"solve_quality": "standard", "mesh_density": "normal"})
        request = urllib.request.Request(
            f"http://127.0.0.1:{port[0]}/solve/stream",
            data=json.dumps(motor).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                for event, payload in sse_events(line.decode() for line in response):
                    if magneto2d_solving(event, payload) and payload.get("stage") == stage:
                        ready.set()
        except (OSError, ValueError):
            pass

    def detail():
        data = acceptance.data_root
        manifests = (data / "solves").rglob("manifest.json")
        marked = any("SOLVER_CANCELLED" in path.read_text(encoding="utf-8") for path in manifests)
        leftover = (data / "launcher.json").exists()
        return marked and not leftover, f"cancelled manifest={marked}, launcher record remains={leftover}"

    threading.Thread(target=follow, daemon=True).start()
    try:
        if not started.wait(60):
            acceptance.check("launcher started for interruption probe", False, str(list(log)))
            return
        threading.Thread(target=stream, daemon=True).start()
        interrupt(acceptance, server, ready, f"server {stage} #{attempt}", log, 0, detail)
    finally:
        if server.poll() is None:
            server.kill()
            server.wait(timeout=10)


def cancel(wheel):
    with tempfile.TemporaryDirectory(prefix="coilem-win-verify-", ignore_cleanup_errors=True) as directory:
        acceptance = Acceptance(Path(directory))
        acceptance.install(str(Path(wheel).resolve()), sys.executable)
        attempts = int(os.environ.get("COILEM_PROBE_ATTEMPTS", "4"))
        for method in (cli, launcher):
            for stage in ("noload_sweep", "magneto2d_sweep"):
                for attempt in range(1, attempts + 1):
                    acceptance.data_root = acceptance.work / f"{method.__name__}-{stage}-{attempt}"
                    acceptance.env["COILEM_USER_DATA_ROOT"] = str(acceptance.data_root)
                    method(acceptance, stage, attempt)
        return acceptance.finish()


if __name__ == "__main__":
    raise SystemExit(lookup() if sys.argv[1] == "lookup" else cancel(sys.argv[2]))
