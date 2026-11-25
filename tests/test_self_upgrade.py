"""Upgrade and restart: which installs it covers, what it runs and what it reports."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import self_upgrade, update_check, upgrade_steps
from backend.public_main import create_app
from backend.public_routes import solve as solve_routes
from backend.self_upgrade import UpgradePlan

PLAN = UpgradePlan("uv tool", ("/bin/uv", "tool", "upgrade", "coilem"), ("/tools/coilem/bin/coilem",), "uv tool upgrade coilem")
ARGS = ["--port", "2645", "--no-browser"]


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(update_check.SWITCH, raising=False)
    for module in (self_upgrade, update_check):
        monkeypatch.setattr(module, "__version__", "0.5.11")


def _environment(tmp_path: Path, *names: str) -> Path:
    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    for name in names:
        (prefix / name).parent.mkdir(parents=True, exist_ok=True)
        (prefix / name).write_text("", encoding="utf-8")
    return prefix


def _plan(prefix: Path, **kwargs: object) -> UpgradePlan | None:
    defaults: dict[str, object] = {"environ": {}, "platform": "darwin", "which": lambda name: None, "has_pip": False, "from_source": False}
    return self_upgrade.plan(prefix=prefix, **{**defaults, **kwargs})  # type: ignore[arg-type]


# --- Which installs it covers -------------------------------------------------


def test_a_uv_tool_install_is_upgraded_with_uv_tool_upgrade(tmp_path: Path) -> None:
    prefix = _environment(tmp_path, "uv-receipt.toml", "bin/coilem", "CACHEDIR.TAG")

    plan = _plan(prefix, which=lambda name: "/opt/bin/uv")

    assert plan == UpgradePlan("uv tool", ("/opt/bin/uv", "tool", "upgrade", "coilem"), (str(prefix / "bin/coilem"),), "uv tool upgrade coilem")


def test_a_uv_tool_started_through_uvx_uses_the_uv_that_started_it(tmp_path: Path) -> None:
    prefix = _environment(tmp_path, "uv-receipt.toml", "bin/coilem", "CACHEDIR.TAG")

    plan = _plan(prefix, environ={"UV": "/custom/uv"}, which=lambda name: "/opt/bin/uv")

    assert plan is not None and plan.method == "uv tool" and plan.upgrade[0] == "/custom/uv"


def test_uvx_fetches_then_starts_the_latest(tmp_path: Path) -> None:
    prefix = _environment(tmp_path, "CACHEDIR.TAG", "bin/coilem")

    plan = _plan(prefix, environ={"UV": "/opt/bin/uv"}, has_pip=True)

    assert plan == UpgradePlan(
        "uvx",
        ("/opt/bin/uv", "tool", "run", "coilem@latest", "--version"),
        ("/opt/bin/uv", "tool", "run", "coilem@latest"),
        "uvx coilem@latest",
    )


def test_pip_in_a_virtual_environment_upgrades_with_that_pip(tmp_path: Path) -> None:
    prefix = _environment(tmp_path, "bin/coilem")

    plan = _plan(prefix, has_pip=True)

    assert plan is not None
    assert plan.upgrade == (str(prefix / "bin/python"), "-m", "pip", "install", "--upgrade", "coilem")
    assert plan.start == (str(prefix / "bin/coilem"),)


@pytest.mark.parametrize(
    ("files", "kwargs"),
    [
        (("uv-receipt.toml", "Scripts/coilem.exe"), {"platform": "win32", "which": lambda name: "uv"}),  # Windows is off by default
        (("uv-receipt.toml", "bin/coilem"), {"from_source": True, "which": lambda name: "uv"}),  # a checkout is never replaced
        (("uv-receipt.toml", "bin/coilem"), {}),  # uv is not on the path
        (("uv-receipt.toml",), {"which": lambda name: "uv"}),  # no coilem script to start
        (("bin/coilem",), {}),  # no pip, not uv
        (("bin/coilem", "CACHEDIR.TAG"), {"has_pip": True}),  # a uv cache entry started without uv
        ((), {"has_pip": True}),
    ],
)
def test_other_installs_are_left_to_the_user(tmp_path: Path, files: tuple[str, ...], kwargs: dict[str, object]) -> None:
    assert _plan(_environment(tmp_path, *files), **kwargs) is None


def test_this_checkout_is_never_upgraded() -> None:
    assert self_upgrade.plan() is None


# --- What it runs ---------------------------------------------------------------


class _Runs:
    """Stands in for the two commands: the upgrade, then ``coilem --version``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, upgrade: object = 0, version: str | None = "coilEM 0.5.12\n") -> None:
        self.commands: list[list[str]] = []
        self.executed: list[str] | None = None
        self._upgrade, self._version = upgrade, version
        monkeypatch.setattr(self_upgrade.subprocess, "run", self._run)
        monkeypatch.setattr(self_upgrade.os, "execv", self._execv)
        monkeypatch.setattr(self_upgrade.signal, "signal", lambda *args: None)

    def _run(self, command: list[str], **kwargs: object) -> SimpleNamespace:
        command = list(command)
        self.commands.append(command)
        if command[-1] == "--version" and command[:-1] == list(PLAN.start):
            if self._version is None:
                return SimpleNamespace(returncode=1, stdout="")
            return SimpleNamespace(returncode=0, stdout=self._version)
        if isinstance(self._upgrade, BaseException):
            raise self._upgrade
        return SimpleNamespace(returncode=self._upgrade, stdout="")

    def _execv(self, path: str, argv: list[str]) -> None:
        assert path == argv[0]
        self.executed = argv
        raise SystemExit(0)  # the real call never returns

    def go(self) -> None:
        with pytest.raises(SystemExit):
            self_upgrade.upgrade_and_restart(PLAN, ARGS)


def test_a_good_upgrade_starts_the_new_coilem_on_the_same_port(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _Runs(monkeypatch)

    runs.go()

    assert runs.commands == [list(PLAN.upgrade), [*PLAN.start, "--version"]]
    assert runs.executed == [*PLAN.start, *ARGS]
    monkeypatch.setattr(self_upgrade, "__version__", "0.5.12")
    assert self_upgrade.last_outcome() == {"ok": True, "from": "0.5.11", "to": "0.5.12", "message": None, "manual": None}


@pytest.mark.parametrize(
    ("runs_kwargs", "says"),
    [
        ({"upgrade": 2}, "failed (exit code 2)"),
        ({"upgrade": FileNotFoundError(2, "No such file or directory")}, "could not be started (No such file or directory)"),
        ({"upgrade": subprocess.TimeoutExpired("uv", 900)}, "did not finish within 15 minutes"),
        ({"version": None}, "the upgraded coilEM did not start"),
        ({"version": "coilEM 0.5.11\n"}, "coilEM is still 0.5.11. The installation may be pinned"),
        ({"version": "coilEM 0.5.10\n"}, "coilEM is still 0.5.10"),
        ({"version": "something else\n"}, "the upgraded coilEM did not start"),
    ],
)
def test_an_upgrade_that_does_not_work_starts_this_copy_again_and_says_why(
    monkeypatch: pytest.MonkeyPatch, runs_kwargs: dict[str, object], says: str
) -> None:
    runs = _Runs(monkeypatch, **runs_kwargs)  # type: ignore[arg-type]

    runs.go()

    assert runs.executed == [self_upgrade.sys.executable, "-m", "backend.launcher", *ARGS]
    outcome = self_upgrade.last_outcome()
    assert outcome is not None and outcome["ok"] is False
    assert says in outcome["message"]
    assert outcome["manual"] == "uv tool upgrade coilem"


def test_ctrl_c_during_the_upgrade_stops_without_restarting(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _Runs(monkeypatch, upgrade=KeyboardInterrupt())

    with pytest.raises(SystemExit) as stopped:
        self_upgrade.upgrade_and_restart(PLAN, ARGS)

    assert stopped.value.code == 130
    assert runs.executed is None


def test_the_version_is_read_from_the_last_matching_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        self_upgrade.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="Installed 40 packages\ncoilEM 0.6.0\n")
    )

    assert self_upgrade.reported_version(["coilem"]) == "0.6.0"


# --- What the app is told afterwards --------------------------------------------


def test_an_outcome_is_shown_for_an_hour_and_only_to_the_right_version(monkeypatch: pytest.MonkeyPatch) -> None:
    self_upgrade._record({"ok": False, "from": "0.5.11", "message": "It failed.", "manual": "uv tool upgrade coilem"})
    now = datetime.now(timezone.utc)

    assert self_upgrade.last_outcome(now=now + timedelta(minutes=59)) is not None
    assert self_upgrade.last_outcome(now=now + timedelta(minutes=61)) is None
    monkeypatch.setattr(self_upgrade, "__version__", "0.5.12")  # upgraded by hand since
    assert self_upgrade.last_outcome(now=now) is None


def test_no_outcome_file_or_a_damaged_one_reads_as_none(tmp_path: Path) -> None:
    assert self_upgrade.last_outcome() is None

    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "upgrade_outcome.json").write_text("{broken", encoding="utf-8")

    assert self_upgrade.last_outcome() is None


# --- The route -------------------------------------------------------------------


def _client(monkeypatch: pytest.MonkeyPatch, *, launcher: bool = True, plan: UpgradePlan | None = PLAN) -> tuple[TestClient, list[UpgradePlan]]:
    monkeypatch.setattr(update_check, "_armed", False)
    monkeypatch.setattr(self_upgrade, "plan", lambda: plan)
    update_check.check_now(lambda first: '{"latest": "0.5.12"}')
    app = create_app()
    asked: list[UpgradePlan] = []
    if launcher:
        app.state.request_upgrade = asked.append
    return TestClient(app, base_url="http://127.0.0.1"), asked


def test_the_route_hands_the_plan_to_the_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    client, asked = _client(monkeypatch)

    assert client.get("/updates").json()["self_upgrade"] is True
    answer = client.post("/updates/upgrade")

    assert answer.status_code == 202
    assert answer.json() == {"restarting": True, "from": "0.5.11", "to": "0.5.12"}
    assert asked == [PLAN]


@pytest.mark.parametrize("kwargs", [{"launcher": False}, {"plan": None}])
def test_without_a_launcher_or_a_plan_the_app_gives_the_command_instead(monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, object]) -> None:
    client, asked = _client(monkeypatch, **kwargs)  # type: ignore[arg-type]

    assert client.get("/updates").json()["self_upgrade"] is False
    refused = client.post("/updates/upgrade")

    assert refused.status_code == 409
    assert refused.json()["detail"]["error_code"] == "UPGRADE_UNAVAILABLE"
    assert asked == []


def test_nothing_newer_means_nothing_to_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    client, asked = _client(monkeypatch)
    update_check.check_now(lambda first: '{"latest": "0.5.11"}')

    assert client.get("/updates").json()["self_upgrade"] is False
    assert client.post("/updates/upgrade").status_code == 409
    assert asked == []


def test_a_running_solve_is_not_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    client, asked = _client(monkeypatch)
    monkeypatch.setitem(solve_routes._ACTIVE_SOLVE, "running", True)

    refused = client.post("/updates/upgrade")

    assert refused.status_code == 409
    assert refused.json()["detail"]["error_code"] == "SOLVE_RUNNING"
    assert asked == []


def test_a_request_from_another_site_cannot_start_an_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    client, asked = _client(monkeypatch)

    refused = client.post("/updates/upgrade", headers={"Origin": "https://example.com"})

    assert refused.status_code == 403
    assert asked == []


# --- Windows: detection, off unless switched on ----------------------------------

WINDOWS_ON = {self_upgrade.WINDOWS_SWITCH: "1"}


def _windows(tmp_path: Path, *names: str) -> tuple[Path, str]:
    prefix = _environment(tmp_path, *names)
    base = tmp_path / "python" / "python.exe"
    base.parent.mkdir()
    base.write_text("", encoding="utf-8")
    return prefix, str(base)


def test_windows_uv_tool_upgrade_is_planned_only_when_switched_on(tmp_path: Path) -> None:
    prefix, base = _windows(tmp_path, "uv-receipt.toml", "Scripts/coilem.exe")
    common = {"platform": "win32", "which": lambda name: "C:/bin/uv.exe", "base_executable": base}

    assert _plan(prefix, **common) is None
    assert _plan(prefix, environ={self_upgrade.WINDOWS_SWITCH: "0"}, **common) is None
    plan = _plan(prefix, environ=WINDOWS_ON, **common)

    assert plan == UpgradePlan(
        "uv tool", ("C:/bin/uv.exe", "tool", "upgrade", "coilem"), (str(prefix / "Scripts" / "coilem.exe"),), "uv tool upgrade coilem", base
    )


def test_windows_pip_uses_the_environments_python_exe(tmp_path: Path) -> None:
    prefix, base = _windows(tmp_path, "Scripts/coilem.exe")

    plan = _plan(prefix, platform="win32", environ=WINDOWS_ON, has_pip=True, base_executable=base)

    assert plan is not None and plan.helper_python == base
    assert plan.upgrade[0] == str(prefix / "Scripts" / "python.exe")


def test_windows_uvx_is_planned_with_a_helper(tmp_path: Path) -> None:
    prefix, base = _windows(tmp_path, "CACHEDIR.TAG", "Scripts/coilem.exe")

    plan = _plan(prefix, platform="win32", environ={**WINDOWS_ON, "UV": "C:/bin/uv.exe"}, base_executable=base)

    assert plan is not None and (plan.method, plan.helper_python) == ("uvx", base)


def test_windows_needs_an_interpreter_outside_the_environment(tmp_path: Path) -> None:
    prefix, _ = _windows(tmp_path, "uv-receipt.toml", "Scripts/coilem.exe", "Scripts/python.exe")
    common = {"platform": "win32", "environ": WINDOWS_ON, "which": lambda name: "uv"}

    assert _plan(prefix, base_executable=str(prefix / "Scripts" / "python.exe"), **common) is None
    assert _plan(prefix, base_executable=str(tmp_path / "missing" / "python.exe"), **common) is None
    assert _plan(prefix, base_executable="", **common) is None


def test_other_systems_never_use_a_helper(tmp_path: Path) -> None:
    prefix = _environment(tmp_path, "uv-receipt.toml", "bin/coilem")

    plan = _plan(prefix, which=lambda name: "/opt/bin/uv", environ=WINDOWS_ON)

    assert plan is not None and plan.helper_python is None


# --- Windows: handing over to the helper ------------------------------------------

HELPED = UpgradePlan("uv tool", ("uv", "tool", "upgrade", "coilem"), ("C:/tools/coilem.exe",), "uv tool upgrade coilem", "C:/python/python.exe")


def test_hand_over_copies_the_helper_out_and_starts_it_with_the_base_python(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    started: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(self_upgrade.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "helper"))
    (tmp_path / "helper").mkdir()
    monkeypatch.setattr(self_upgrade.subprocess, "Popen", lambda command, **kwargs: started.append((command, kwargs)))

    assert self_upgrade.hand_over(HELPED, ARGS)

    [(command, kwargs)] = started
    script, spec_path = tmp_path / "helper" / "upgrade_steps.py", tmp_path / "helper" / "spec.json"
    assert command == ["C:/python/python.exe", "-I", str(script), str(spec_path)]
    assert script.read_bytes() == Path(upgrade_steps.__file__).read_bytes()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert spec["upgrade"] == ["uv", "tool", "upgrade", "coilem"]
    assert spec["start"] == ["C:/tools/coilem.exe"]
    assert spec["fallback"] == [sys.executable, "-m", "backend.launcher"]
    assert spec["args"] == ARGS
    assert (spec["current"], spec["manual"], spec["pid"]) == ("0.5.11", "uv tool upgrade coilem", self_upgrade.os.getpid())
    assert Path(spec["outcome"]).name == "upgrade_outcome.json"


def test_hand_over_goes_without_leaving_the_job_when_that_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(self_upgrade.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    monkeypatch.setattr(self_upgrade.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000, raising=False)
    flags: list[int] = []

    def popen(command: list[str], **kwargs: object) -> None:
        flags.append(kwargs["creationflags"])  # type: ignore[arg-type]
        if kwargs["creationflags"]:
            raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(self_upgrade.subprocess, "Popen", popen)

    assert self_upgrade.hand_over(HELPED, ARGS)
    assert flags == [0x01000000, 0]


def test_a_helper_that_cannot_start_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(self_upgrade.tempfile, "mkdtemp", lambda prefix: str(tmp_path))

    def popen(command: list[str], **kwargs: object) -> None:
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(self_upgrade.subprocess, "Popen", popen)

    assert not self_upgrade.hand_over(HELPED, ARGS)
    outcome = self_upgrade.last_outcome()
    assert outcome is not None and "could not be started" in outcome["message"]


def test_the_helper_file_imports_nothing_from_coilem() -> None:
    source = Path(upgrade_steps.__file__).read_text(encoding="utf-8")

    assert "from backend" not in source and "import backend" not in source


# --- The helper itself, run for real as a separate process ------------------------


def _helper(tmp_path: Path, *, upgrade: str, waits_for: int, version: str = "0.5.12", **extra: object) -> subprocess.CompletedProcess[str]:
    """Run ``upgrade_steps.py`` as the launcher would, with small Python stand-ins."""

    marker = tmp_path / "started.txt"
    coilem = tmp_path / "coilem.py"
    coilem.write_text(
        "import sys, pathlib\n"
        f"if sys.argv[1:] == ['--version']: print('coilEM {version}'); raise SystemExit(0)\n"
        f"pathlib.Path({str(marker)!r}).write_text('new ' + ' '.join(sys.argv[1:]))\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    old = tmp_path / "old.py"
    old.write_text(
        f"import sys, pathlib\npathlib.Path({str(marker)!r}).write_text('old ' + ' '.join(sys.argv[1:]))\nraise SystemExit(9)\n",
        encoding="utf-8",
    )
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "current": "0.5.11",
                "manual": "uv tool upgrade coilem",
                "upgrade": [sys.executable, "-c", upgrade],
                "start": [sys.executable, str(coilem)],
                "fallback": [sys.executable, str(old)],
                "args": ARGS,
                "outcome": str(tmp_path / "data" / "upgrade_outcome.json"),
                "pid": waits_for,
                "attempts": 2,
                **extra,
            }
        ),
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, "-I", upgrade_steps.__file__, str(spec)], capture_output=True, text=True, timeout=60, check=False
    )


def _gone_soon(seconds: float = 0.6) -> subprocess.Popen[bytes]:
    """A stand-in for the old coilEM: it exits by itself shortly.

    It is waited for on a thread, as the shell that started coilEM would;
    otherwise it would linger as a zombie that still counts as running.
    """

    process = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])
    threading.Thread(target=process.wait, daemon=True).start()
    return process


def test_the_helper_waits_for_coilem_to_exit_then_upgrades_and_starts_the_new_one(tmp_path: Path) -> None:
    order = tmp_path / "order.txt"
    old_coilem = _gone_soon()
    started = time.monotonic()

    done = _helper(tmp_path, upgrade=f"open({str(order)!r}, 'w').write('upgraded')", waits_for=old_coilem.pid)

    assert old_coilem.wait() == 0 and time.monotonic() - started >= 0.5  # it waited
    assert order.read_text() == "upgraded"
    assert (tmp_path / "started.txt").read_text() == "new --port 2645 --no-browser"
    assert done.returncode == 7  # the exit code of the coilEM it ran
    assert "upgraded to 0.5.12" in done.stdout
    assert (tmp_path / "spec.json").exists()  # only a folder the launcher made for the run is removed
    saved = json.loads((tmp_path / "data" / "upgrade_outcome.json").read_text())
    assert (saved["ok"], saved["from"], saved["to"]) == (True, "0.5.11", "0.5.12")


def test_the_helper_starts_the_old_copy_again_when_the_upgrade_fails(tmp_path: Path) -> None:
    done = _helper(tmp_path, upgrade="raise SystemExit(3)", waits_for=_gone_soon(0.1).pid)

    assert (tmp_path / "started.txt").read_text() == "old --port 2645 --no-browser"
    assert done.returncode == 9
    assert "trying again" in done.stdout  # a locked file can clear on the second attempt
    saved = json.loads((tmp_path / "data" / "upgrade_outcome.json").read_text())
    assert saved["ok"] is False and "exit code 3" in saved["message"] and saved["manual"] == "uv tool upgrade coilem"


def test_the_helper_retries_an_upgrade_that_fails_once(tmp_path: Path) -> None:
    tries = tmp_path / "tries.txt"
    flaky = (
        f"import pathlib; p = pathlib.Path({str(tries)!r}); n = len(p.read_text()) if p.exists() else 0; "
        "p.write_text('x' * (n + 1)); raise SystemExit(0 if n else 5)"
    )

    done = _helper(tmp_path, upgrade=flaky, waits_for=_gone_soon(0.1).pid)

    assert tries.read_text() == "xx"
    assert (tmp_path / "started.txt").read_text().startswith("new ")
    assert done.returncode == 7


def test_the_helper_does_not_call_an_unchanged_version_an_upgrade(tmp_path: Path) -> None:
    done = _helper(tmp_path, upgrade="pass", waits_for=_gone_soon(0.1).pid, version="0.5.11")

    assert (tmp_path / "started.txt").read_text().startswith("old ")
    assert "still 0.5.11" in done.stderr


def test_the_helper_changes_nothing_while_coilem_is_still_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    order = tmp_path / "order.txt"
    stays = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert not upgrade_steps.wait_for_exit(stays.pid, 0.3)
        monkeypatch.setattr(upgrade_steps, "EXIT_WAIT_S", 0.3)
        spec = tmp_path / "spec.json"
        spec.write_text(
            json.dumps(
                {"current": "0.5.11", "manual": "uv tool upgrade coilem", "upgrade": [sys.executable, "-c", f"open({str(order)!r}, 'w')"],
                 "start": ["x"], "fallback": ["x"], "args": [], "outcome": str(tmp_path / "outcome.json"), "pid": stays.pid}
            ),
            encoding="utf-8",
        )

        assert upgrade_steps.main([str(spec)]) == 1

        assert not order.exists()
        assert "did not stop" in json.loads((tmp_path / "outcome.json").read_text())["message"]
    finally:
        stays.kill()
        stays.wait()


def test_the_helper_refuses_a_spec_it_cannot_read(tmp_path: Path) -> None:
    (tmp_path / "spec.json").write_text("{broken", encoding="utf-8")

    assert upgrade_steps.main([str(tmp_path / "spec.json")]) == 2
    assert upgrade_steps.main([]) == 2


def test_the_helper_removes_the_folder_the_launcher_made_for_it(tmp_path: Path) -> None:
    folder = tmp_path / f"{upgrade_steps.HELPER_FOLDER_PREFIX}abc"
    folder.mkdir()
    (folder / "spec.json").write_text("{broken", encoding="utf-8")
    spec = folder / "spec.json"
    spec.write_text(
        json.dumps(
            {"current": "0.5.11", "manual": "m", "upgrade": [sys.executable, "-c", "raise SystemExit(1)"], "start": ["x"],
             "fallback": [sys.executable, "-c", "pass"], "args": [], "outcome": str(tmp_path / "outcome.json"), "pid": _gone_soon(0.1).pid,
             "attempts": 1}
        ),
        encoding="utf-8",
    )

    assert upgrade_steps.main([str(spec)]) == 0

    assert not folder.exists()
    assert (tmp_path / "outcome.json").exists()
