"""Ask coilem.com, once a day at most, whether a newer coilEM is released.

coilEM runs on the user's computer and needs no network. This is the one
request it makes on its own, so the rules are kept in one place:

- **What is sent.** A plain ``GET`` of :data:`UPDATE_URL`. The ``User-Agent``
  names the coilEM version and the operating system (``coilEM/0.5.10
  (Windows)``). :data:`FIRST_CHECK_HEADER` says whether this is the first
  answered check from this computer in the current week or month, and
  whether coilEM had never run on this computer before (``install``), so that
  coilem.com can count installs per week and per month, and new installs,
  without ever being given an identifier. There is no install id, no design
  data and nothing in the URL.
- **What is read.** One version number. The release page and the upgrade
  command are built here, so a wrong answer from the server can show a wrong
  number and nothing else.
- **When.** Once per UTC calendar day, so each day's requests at coilem.com
  are that day's running installs. Only when the ``coilem`` launcher has started the app (see
  :func:`arm`), only for a released version, and never under CI. The
  development API and the test suite therefore never call out.
- **How to turn it off.** ``COILEM_UPDATE_CHECK=0`` where coilEM is started.

The check runs on a daemon thread and every failure is silent: being offline
or behind a firewall is normal and is not an error the user should see.
"""

from __future__ import annotations

import json
import os
import platform
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend import __version__
from backend.solve_workspace import _atomic_write_json, user_data_root

UPDATE_URL = "https://coilem.com/api/latest-version"
SWITCH = "COILEM_UPDATE_CHECK"
RELEASE_URL = "https://github.com/coilemdev/coilem/releases/tag/v{version}"
UPGRADE_COMMAND = "uv tool upgrade coilem"
FIRST_CHECK_HEADER = "Coilem-First-Check"
REQUEST_TIMEOUT_S = 5.0
MAX_RESPONSE_BYTES = 2048

_FILE_NAME = "update_check.json"
_RELEASED_VERSION = re.compile(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})")
_OFF_VALUES = frozenset({"0", "false", "no", "off"})
_STATE_KEYS = frozenset({"checked_at", "answered_at", "latest", "new_install"})
_LOCK = threading.Lock()
_armed = False
_running = False

Fetch = Callable[[tuple[str, ...]], str]


def _path() -> Path:
    return user_data_root() / _FILE_NAME


def version_key(version: object) -> tuple[int, int, int] | None:
    """Return a released ``X.Y.Z`` version as numbers, else ``None``.

    Development and pre-release builds are not plain ``X.Y.Z``; they neither
    ask for updates nor count as one.
    """

    match = _RELEASED_VERSION.fullmatch(version) if isinstance(version, str) else None
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def disabled_by(environ: Mapping[str, str] = os.environ) -> str | None:
    """Say what turns the check off: ``environment`` or nothing."""

    if environ.get(SWITCH, "").strip().lower() in _OFF_VALUES or environ.get("CI"):
        return "environment"
    return None


def _read() -> dict[str, Any]:
    """Return the saved state; a missing or damaged file reads as empty."""

    try:
        saved = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _write(changes: Mapping[str, Any]) -> None:
    with _LOCK:
        state = {key: value for key, value in _read().items() if key in _STATE_KEYS}
        state.update(changes)
        _atomic_write_json(_path(), {"schema_version": 1, **state})


def _stamp(state: Mapping[str, Any], key: str) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(state.get(key)))
    except ValueError:
        return None
    return stamp.astimezone(timezone.utc) if stamp.tzinfo is not None else None


def _checked_at(state: Mapping[str, Any]) -> datetime | None:
    return _stamp(state, "checked_at")


def first_check_periods(state: Mapping[str, Any], now: datetime) -> tuple[str, ...]:
    """Name the periods (``install``, ``week``, ``month``) in which no check was answered yet.

    ``install`` is sent until the first answered check of a copy that found
    no earlier coilEM on this computer (see :func:`arm`). Weeks are ISO weeks
    and both are in UTC, as coilem.com counts them. The date used is the last
    *answered* check: an attempt that never reached the server was not
    counted there and must not use up the period.
    """

    last = _stamp(state, "answered_at")
    today = now.astimezone(timezone.utc)
    periods = []
    if last is None and state.get("new_install") is True:
        periods.append("install")
    if last is None or last.isocalendar()[:2] != today.isocalendar()[:2]:
        periods.append("week")
    if last is None or (last.year, last.month) != (today.year, today.month):
        periods.append("month")
    return tuple(periods)


def status() -> dict[str, Any]:
    """Describe the check for the app: on or off, and the newer version if any."""

    state = _read()
    off = disabled_by()
    current = version_key(__version__)
    latest = state.get("latest") if off is None else None
    latest_key = version_key(latest)
    newer = current is not None and latest_key is not None and latest_key > current
    checked = _checked_at(state) if off is None else None
    return {
        "current": __version__,
        "enabled": off is None,
        "disabled_by": off,
        "switch": SWITCH,
        "checked_at": checked.isoformat() if checked else None,
        # False when the last answer is unknown: an unreachable server is not "up to date".
        "up_to_date": current is not None and latest_key is not None and not newer,
        "latest": latest if newer else None,
        "release_url": RELEASE_URL.format(version=latest) if newer else None,
        "upgrade_command": UPGRADE_COMMAND if newer else None,
    }


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """The answer comes from coilem.com or not at all."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def user_agent() -> str:
    return f"coilEM/{__version__} ({platform.system() or 'unknown'})"


def _fetch(first: tuple[str, ...] = ()) -> str:
    headers = {"User-Agent": user_agent(), "Accept": "application/json"}
    if first:
        headers[FIRST_CHECK_HEADER] = ", ".join(first)
    request = urllib.request.Request(UPDATE_URL, headers=headers)
    opener = urllib.request.build_opener(_NoRedirects)
    with opener.open(request, timeout=REQUEST_TIMEOUT_S) as response:
        return response.read(MAX_RESPONSE_BYTES + 1).decode("utf-8")


def parse_latest(body: str) -> str | None:
    """Return the version in the server's answer, or ``None`` if it is not one."""

    if len(body) > MAX_RESPONSE_BYTES:
        return None
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    latest = payload.get("latest") if isinstance(payload, dict) else None
    return latest if version_key(latest) is not None else None


def check_now(fetch: Fetch = _fetch, *, now: datetime | None = None) -> bool:
    """Ask once and save the answer. Returns whether an answer was saved.

    A failed request is still recorded as an attempt, so a computer that
    cannot reach coilem.com tries once a day, not on every page load.
    Redirects are refused and count as a failure.
    """

    moment = now or datetime.now(timezone.utc)
    stamp = moment.isoformat()
    try:
        latest = parse_latest(fetch(first_check_periods(_read(), moment)))
    except (OSError, ValueError, urllib.error.URLError):
        latest = None
    try:
        _write({"checked_at": stamp} if latest is None else {"checked_at": stamp, "answered_at": stamp, "latest": latest})
    except OSError:
        return False
    return latest is not None


def is_due(*, now: datetime | None = None) -> bool:
    """Whether a check may run now: armed, released, switched on, not yet today.

    "Today" is the UTC calendar day, not 24 hours since the last check: a
    person who starts coilEM at nine each morning is a few seconds short of
    24 hours every other day and would be missed on those days.
    """

    if not _armed or version_key(__version__) is None or disabled_by() is not None:
        return False
    last = _checked_at(_read())
    current = now or datetime.now(timezone.utc)
    # Any other day counts, so a clock set back cannot silence the check for good.
    return last is None or last.date() != current.astimezone(timezone.utc).date()


def check_if_due(fetch: Fetch = _fetch) -> threading.Thread | None:
    """Start one background check if one is due; return its thread."""

    global _running
    with _LOCK:
        if _running or not is_due():
            return None
        _running = True

    def run() -> None:
        global _running
        try:
            check_now(fetch)
        finally:
            _running = False

    thread = threading.Thread(target=run, name="coilem-update-check", daemon=True)
    thread.start()
    return thread


def arm(*, first_run: bool = False) -> None:
    """Allow checks in this process. Only the ``coilem`` launcher calls this.

    ``first_run`` says the launcher found no earlier coilEM on this computer:
    its data folder did not exist or was empty. That is remembered until the
    first answered check, which then says ``install``. Upgrading, or a
    version from before the update check, leaves files there, so neither is
    counted as a new install.
    """

    global _armed
    _armed = True
    if first_run and _stamp(_read(), "answered_at") is None:
        try:
            _write({"new_install": True})
        except OSError:
            pass  # not counted as new; the check itself still works


def notice() -> str | None:
    """What the launcher prints before the first check on this computer."""

    if version_key(__version__) is None or disabled_by() is not None or _checked_at(_read()) is not None:
        return None
    return (
        "coilEM asks coilem.com once a day whether a newer version is released. "
        "It sends the coilEM version, the operating system and whether this is the first check "
        "this week or month, or the first time coilEM runs on this computer, and no identifier. "
        f"Turn it off with {SWITCH}=0."
    )
