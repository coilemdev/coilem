"""Upgrade coilEM from the app and start it again.

**Upgrade and restart** in the app asks the launcher to stop serving.
The launcher then, in the same terminal and the same process:

1. runs the upgrade command for the way this copy was installed, with its
   output on the terminal;
2. asks the result which version it is;
3. records the outcome in the user data root for the app to show;
4. replaces itself with the upgraded ``coilem`` on the port it had, so the open
   browser tab finds it again and Ctrl+C still stops it.

If the upgrade fails, or leaves the version unchanged, this same copy starts
again and the app says what happened and gives the command to run by hand.

Only fixed commands run; nothing from a request reaches a command line. The
three install layouts are told apart by what uv and pip leave on disk:

- ``uv tool install coilem``: ``uv-receipt.toml`` in the environment.
- ``uvx coilem``: uv names itself in ``UV`` and the environment is a cache
  entry (``CACHEDIR.TAG``) without a receipt. There is nothing to upgrade in
  place: the newest version is fetched, then started with ``coilem@latest``.
- pip in a virtual environment: ``pip`` importable and a ``coilem`` script.

On Windows a running program locks its own files and cannot replace itself, so
step 1 onwards is handed to a helper (``backend/upgrade_steps.py``, run as a
script by the base interpreter, which is outside the environment being
upgraded). The launcher exits; the helper waits for it to be gone, upgrades,
and runs the upgraded coilEM as its child in the same console. The terminal
returns to its prompt meanwhile, and Ctrl+C in it still stops coilEM.

The Windows path has not been run on Windows yet. It is off unless
:data:`WINDOWS_SWITCH` is set, and the menu gives the command instead.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NoReturn

from backend import __version__, upgrade_steps
from backend.resources import source_checkout_root
from backend.solve_workspace import user_data_root
from backend.upgrade_steps import reported_version

__all__ = ["UpgradePlan", "hand_over", "last_outcome", "plan", "reported_version", "upgrade_and_restart"]

# Set to 1 to offer Upgrade and restart on Windows, for testing it there.
WINDOWS_SWITCH = "COILEM_EXPERIMENTAL_UPGRADE"
# How long after a restart the app keeps showing what the upgrade did.
OUTCOME_SHOWN_FOR = timedelta(hours=1)
_FILE_NAME = "upgrade_outcome.json"


@dataclass(frozen=True)
class UpgradePlan:
    """How this copy of coilEM is upgraded and started again."""

    method: str
    #: Fetches the newest version; its output goes to the terminal.
    upgrade: tuple[str, ...]
    #: Starts the upgraded coilEM; the launcher's arguments are appended.
    start: tuple[str, ...]
    #: What to tell the user to run if this fails.
    manual: str
    #: Windows only: the interpreter outside this environment that runs the helper.
    helper_python: str | None = None


def _base_python(prefix: Path, base_executable: str | None) -> str | None:
    """The interpreter this environment was made from, if it lies outside it."""

    if not base_executable:
        return None
    base = Path(base_executable)
    try:
        inside = base.resolve().is_relative_to(prefix.resolve())
    except OSError:
        return None
    return None if inside or not base.is_file() else str(base)


def plan(
    *,
    prefix: Path | None = None,
    environ: Mapping[str, str] = os.environ,
    platform: str = sys.platform,
    which: Any = shutil.which,
    has_pip: bool | None = None,
    from_source: bool | None = None,
    base_executable: str | None = None,
) -> UpgradePlan | None:
    """Return how to upgrade this installation, or ``None`` if the app cannot.

    A source checkout is never upgraded: its environment holds the checkout
    itself, and installing the released package over it would replace it.
    """

    if from_source is None:
        from_source = source_checkout_root() is not None
    windows = platform == "win32"
    if from_source or (windows and environ.get(WINDOWS_SWITCH) != "1"):
        return None
    root = Path(sys.prefix if prefix is None else prefix)
    scripts = root / ("Scripts" if windows else "bin")
    script = scripts / ("coilem.exe" if windows else "coilem")
    helper = None
    if windows:
        helper = _base_python(root, base_executable if base_executable is not None else getattr(sys, "_base_executable", None))
        if helper is None:
            return None
    uv = environ.get("UV") or which("uv")
    if (root / "uv-receipt.toml").is_file():
        if not uv or not script.is_file():
            return None
        return UpgradePlan("uv tool", (uv, "tool", "upgrade", "coilem"), (str(script),), "uv tool upgrade coilem", helper)
    if environ.get("UV") and (root / "CACHEDIR.TAG").is_file():
        latest = (environ["UV"], "tool", "run", "coilem@latest")
        return UpgradePlan("uvx", (*latest, "--version"), latest, "uvx coilem@latest", helper)
    if has_pip is None:
        has_pip = importlib.util.find_spec("pip") is not None
    in_environment = sys.prefix != sys.base_prefix if prefix is None else True
    if has_pip and in_environment and script.is_file() and not (root / "CACHEDIR.TAG").is_file():
        python = str(scripts / ("python.exe" if windows else "python"))
        return UpgradePlan(
            "pip", (python, "-m", "pip", "install", "--upgrade", "coilem"), (str(script),), "pip install --upgrade coilem", helper
        )
    return None


def _path() -> Path:
    return user_data_root() / _FILE_NAME


def _record(outcome: Mapping[str, Any]) -> None:
    upgrade_steps.record(_path(), outcome)


def last_outcome(*, now: datetime | None = None) -> dict[str, Any] | None:
    """What the last upgrade from the app did, while it is recent enough to matter.

    A success is reported only to the version it produced; a failure only to
    the version that tried, so neither outlives the next ordinary upgrade.
    """

    try:
        saved = json.loads(_path().read_text(encoding="utf-8"))
        at = datetime.fromisoformat(str(saved.get("at")))
    except (OSError, ValueError, AttributeError):
        return None
    if at.tzinfo is None or (now or datetime.now(timezone.utc)) - at > OUTCOME_SHOWN_FOR:
        return None
    ok = saved.get("ok") is True
    if saved.get("to" if ok else "from") != __version__:
        return None
    return {
        "ok": ok,
        "from": str(saved.get("from", "")),
        "to": saved.get("to") if ok else None,
        "message": None if ok else str(saved.get("message", "")),
        "manual": None if ok else str(saved.get("manual", "")),
    }


def _this_copy() -> tuple[str, ...]:
    """The command that starts the copy that is running now."""

    return (sys.executable, "-m", "backend.launcher")


def hand_over(steps: UpgradePlan, launcher_args: Sequence[str]) -> bool:
    """Start the helper that upgrades after this process has exited (Windows).

    Returns whether the helper was started; the launcher then simply exits.
    The helper runs from a copy outside the installation, under the base
    interpreter, so nothing it uses is replaced by the upgrade.
    """

    assert steps.helper_python is not None
    try:
        folder = Path(tempfile.mkdtemp(prefix=upgrade_steps.HELPER_FOLDER_PREFIX))
        script = folder / "upgrade_steps.py"
        script.write_bytes(Path(upgrade_steps.__file__).read_bytes())
        spec = folder / "spec.json"
        spec.write_text(
            json.dumps(
                {
                    "current": __version__,
                    "manual": steps.manual,
                    "upgrade": list(steps.upgrade),
                    "start": list(steps.start),
                    "fallback": list(_this_copy()),
                    "args": list(launcher_args),
                    "outcome": str(_path()),
                    "pid": os.getpid(),
                    "parent_pid": os.getppid(),
                    "attempts": 3,
                }
            ),
            encoding="utf-8",
        )
        command = [steps.helper_python, "-I", str(script), str(spec)]
        # The coilem.exe shim may hold this process in a job that ends its
        # children with it; ask to leave the job, and go without if refused.
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        for flags in dict.fromkeys((breakaway, 0)):
            try:
                subprocess.Popen(command, stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
                break
            except OSError:
                if flags == 0:
                    raise
    except OSError as exc:
        message = f"The upgrade could not be started ({exc.strerror or type(exc).__name__})."
        _record(upgrade_steps.failure(__version__, message, steps.manual))
        print(
            f"coilem: {message} coilEM is stopped; start it again with `coilem`. To upgrade by hand: {steps.manual}",
            file=sys.stderr,
            flush=True,
        )
        return False
    print(
        "coilem: stopping to upgrade. This window returns to its prompt while coilEM upgrades and starts again; "
        "Ctrl+C here still stops it.",
        flush=True,
    )
    return True


def _exec(command: Sequence[str]) -> NoReturn:
    sys.stdout.flush()
    sys.stderr.flush()
    # Fixed commands only; see the module docstring.
    os.execv(command[0], list(command))


def upgrade_and_restart(steps: UpgradePlan, launcher_args: Sequence[str]) -> NoReturn:
    """Upgrade, record the outcome and become the next coilEM. Never returns.

    Called by the launcher once it has stopped serving and released its port
    and data-folder lock.
    """

    # The server's handlers are gone with the server; Ctrl+C now simply stops.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    this_copy = _this_copy()
    try:
        ok, detail = upgrade_steps.upgrade(steps.upgrade, steps.start, current=__version__, manual=steps.manual)
    except KeyboardInterrupt:
        print("\ncoilem: upgrade interrupted; coilEM is stopped.", file=sys.stderr, flush=True)
        _record(upgrade_steps.failure(__version__, "The upgrade was interrupted.", steps.manual))
        raise SystemExit(130) from None
    if ok:
        _record({"ok": True, "from": __version__, "to": detail})
        print(f"coilem: upgraded to {detail}; starting it.", flush=True)
        _exec((*steps.start, *launcher_args))
    _record(upgrade_steps.failure(__version__, detail, steps.manual))
    print(f"coilem: {detail}\ncoilem: starting coilEM {__version__} again. To upgrade by hand: {steps.manual}", file=sys.stderr, flush=True)
    _exec((*this_copy, *launcher_args))
