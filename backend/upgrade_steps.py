"""The steps of an upgrade, usable with nothing but the standard library.

``backend/self_upgrade.py`` decides *what* to run; this file runs it. It is
kept free of every other coilEM import because on Windows it is also run as a
script, by a different Python, after coilEM has exited:

    python -I upgrade_steps.py <spec.json>

A running program on Windows locks its own files, so the copy being upgraded
cannot do the upgrade. The launcher copies this file out of the installation,
writes the commands to ``spec.json`` and starts it with the base interpreter
(which is outside the environment being replaced), then exits. This script
waits for coilEM to be gone, upgrades, records the outcome for the app, starts
coilEM again as its own child in the same console and stays until it ends, so
Ctrl+C in that console still reaches it.

On macOS and Linux the launcher calls :func:`upgrade` directly and then
replaces its own process; the script mode is not used there.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UPGRADE_TIMEOUT_S = 15 * 60
VERSION_TIMEOUT_S = 120
EXIT_WAIT_S = 60.0
# The program that started Python (the ``coilem.exe`` shim, or uv) ends a moment later.
PARENT_EXIT_WAIT_S = 5.0
RETRY_PAUSE_S = 2.0
HELPER_FOLDER_PREFIX = "coilem-upgrade-"
_REPORTED_VERSION = re.compile(r"^coilEM (\d{1,4}\.\d{1,4}\.\d{1,4})\s*$")
_RELEASED_VERSION = re.compile(r"\d{1,4}(\.\d{1,4}){2}")


def newer(candidate: str | None, than: str | None) -> bool:
    """Whether ``candidate`` is a released version above ``than``."""

    def key(version: str | None) -> tuple[int, ...] | None:
        return tuple(int(part) for part in version.split(".")) if version and _RELEASED_VERSION.fullmatch(version) else None

    new, old = key(candidate), key(than)
    return new is not None and old is not None and new > old


def reported_version(command: Sequence[str]) -> str | None:
    """Ask a ``coilem`` which version it is; ``None`` if it does not say."""

    try:
        done = subprocess.run(
            [*command, "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT_S, stdin=subprocess.DEVNULL, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in reversed(done.stdout.splitlines()) if done.returncode == 0 else ():
        match = _REPORTED_VERSION.match(line)
        if match:
            return match[1]
    return None


def upgrade(
    command: Sequence[str], start: Sequence[str], *, current: str, manual: str, attempts: int = 1
) -> tuple[bool, str]:
    """Run the upgrade and say whether a newer coilEM is now installed.

    Returns ``(True, new_version)`` or ``(False, reason)``. ``attempts`` above
    one retries a command that failed, for Windows, where a file of the old
    copy can stay locked for a moment after it exits.
    """

    print(f"coilem: upgrading ({manual}) ...", flush=True)
    for attempt in range(1, max(1, attempts) + 1):
        try:
            done = subprocess.run(list(command), timeout=UPGRADE_TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
        except subprocess.TimeoutExpired:
            return False, f"The upgrade did not finish within {UPGRADE_TIMEOUT_S // 60} minutes."
        except OSError as exc:
            return False, f"The upgrade command could not be started ({exc.strerror or type(exc).__name__})."
        if done.returncode == 0:
            break
        if attempt == max(1, attempts):
            return False, f"The upgrade command failed (exit code {done.returncode}); its output is in the terminal coilEM runs in."
        print(f"coilem: the upgrade command failed (exit code {done.returncode}); trying again ...", flush=True)
        time.sleep(RETRY_PAUSE_S)
    now = reported_version(start)
    if now is None:
        return False, "The upgrade ran, but the upgraded coilEM did not start."
    if not newer(now, current):
        return False, f"The upgrade ran, but coilEM is still {now}. The installation may be pinned to that version."
    return True, now


def record(path: Path, outcome: Mapping[str, Any]) -> None:
    """Save what the upgrade did where the app reads it; never raises."""

    payload = {"schema_version": 1, "at": datetime.now(timezone.utc).isoformat(), **outcome}
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass  # the terminal already says what happened


def failure(current: str, message: str, manual: str) -> dict[str, Any]:
    return {"ok": False, "from": current, "message": message, "manual": manual}


def wait_for_exit(pid: int, timeout_s: float) -> bool:
    """Wait until process ``pid`` is gone; ``False`` if it is still there."""

    if os.name == "nt":
        import ctypes

        synchronize = 0x00100000
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return True  # already gone, or not ours to wait for
        try:
            return kernel32.WaitForSingleObject(handle, int(timeout_s * 1000)) == 0
        finally:
            kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass  # exists, but belongs to someone else
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def _run_until_it_ends(command: Sequence[str]) -> int:
    """Run coilEM as a child and return its exit code.

    Ctrl+C in the console reaches the child as well; it stops itself, and a
    second Ctrl+C forces it. This process only waits.
    """

    try:
        child = subprocess.Popen(list(command), stdin=subprocess.DEVNULL)
    except OSError as exc:
        print(f"coilem: coilEM could not be started ({exc.strerror or type(exc).__name__}): {command[0]}", file=sys.stderr, flush=True)
        return 1
    while True:
        try:
            return child.wait()
        except KeyboardInterrupt:
            continue


def main(argv: Sequence[str] | None = None) -> int:
    """Carry out the upgrade described by a spec file written by the launcher."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: upgrade_steps.py <spec.json>", file=sys.stderr)
        return 2
    spec_path = Path(arguments[0])
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        current, manual = str(spec["current"]), str(spec["manual"])
        command, start, fallback = list(spec["upgrade"]), list(spec["start"]), list(spec["fallback"])
        launcher_args, outcome_path = list(spec["args"]), Path(spec["outcome"])
        pid, parent = int(spec["pid"]), int(spec.get("parent_pid") or 0)
        attempts = int(spec.get("attempts", 3))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"coilem: the upgrade could not be read ({type(exc).__name__}); nothing was changed.", file=sys.stderr, flush=True)
        return 2
    try:
        return _carry_out(pid, parent, command, start, fallback, launcher_args, outcome_path, current, manual, attempts)
    finally:
        # The launcher made this folder for the one run; nothing else is in it.
        if spec_path.parent.name.startswith(HELPER_FOLDER_PREFIX):
            shutil.rmtree(spec_path.parent, ignore_errors=True)


def _carry_out(
    pid: int,
    parent: int,
    command: Sequence[str],
    start: Sequence[str],
    fallback: Sequence[str],
    launcher_args: Sequence[str],
    outcome_path: Path,
    current: str,
    manual: str,
    attempts: int,
) -> int:
    try:
        if not wait_for_exit(pid, EXIT_WAIT_S):
            message = "coilEM did not stop, so it was not upgraded."
            record(outcome_path, failure(current, message, manual))
            print(f"coilem: {message} To upgrade by hand, stop it and run: {manual}", file=sys.stderr, flush=True)
            return 1
        if parent > 0:
            wait_for_exit(parent, PARENT_EXIT_WAIT_S)
        ok, detail = upgrade(command, start, current=current, manual=manual, attempts=attempts)
    except KeyboardInterrupt:
        record(outcome_path, failure(current, "The upgrade was interrupted.", manual))
        print("\ncoilem: upgrade interrupted; coilEM is stopped.", file=sys.stderr, flush=True)
        return 130
    if ok:
        record(outcome_path, {"ok": True, "from": current, "to": detail})
        print(f"coilem: upgraded to {detail}; starting it. Ctrl+C in this window stops it.", flush=True)
        return _run_until_it_ends([*start, *launcher_args])
    record(outcome_path, failure(current, detail, manual))
    print(f"coilem: {detail}\ncoilem: starting coilEM {current} again. To upgrade by hand: {manual}", file=sys.stderr, flush=True)
    return _run_until_it_ends([*fallback, *launcher_args])


if __name__ == "__main__":
    raise SystemExit(main())
