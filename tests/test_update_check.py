"""The daily update check: what it sends, what it trusts and when it stays quiet."""

from __future__ import annotations

import http.server
import json
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import update_check
from backend.public_main import create_app

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(update_check.SWITCH, raising=False)
    monkeypatch.setattr(update_check, "__version__", "0.5.11")
    monkeypatch.setattr(update_check, "_armed", True)
    monkeypatch.setattr(update_check, "_running", False)


def _answer(version: object):
    return lambda first=(): json.dumps({"latest": version})


def _refuse(first: tuple[str, ...] = ()) -> str:
    raise AssertionError("no request may be made")


def test_a_newer_release_is_reported_with_its_page_and_command() -> None:
    assert update_check.check_now(_answer("0.5.12"), now=NOW)

    status = update_check.status()

    assert status["latest"] == "0.5.12"
    assert status["release_url"] == "https://github.com/coilemdev/coilem/releases/tag/v0.5.12"
    assert status["upgrade_command"] == "uv tool upgrade coilem"
    assert status["checked_at"] == NOW.isoformat()


@pytest.mark.parametrize("latest", ["0.5.11", "0.5.10", "0.4.99"])
def test_the_same_or_an_older_release_is_not_an_update(latest: str) -> None:
    update_check.check_now(_answer(latest), now=NOW)

    assert update_check.status()["latest"] is None


def test_versions_compare_as_numbers() -> None:
    update_check.check_now(_answer("0.10.0"), now=NOW)

    assert update_check.status()["latest"] == "0.10.0"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "not json",
        "[]",
        json.dumps({"latest": "1.0.0rc1"}),
        json.dumps({"latest": "9.9.9; rm -rf"}),
        json.dumps({"latest": "https://example.com"}),
        json.dumps({"latest": 6}),
        json.dumps({"latest": "9.9.9", "pad": "x" * update_check.MAX_RESPONSE_BYTES}),
    ],
)
def test_an_answer_that_is_not_one_version_is_ignored(body: str) -> None:
    assert not update_check.check_now(lambda first: body, now=NOW)

    assert update_check.status()["latest"] is None


def test_a_failed_request_is_silent_and_waits_a_day() -> None:
    def offline(first: tuple[str, ...]) -> str:
        raise OSError("no route to host")

    assert not update_check.check_now(offline, now=NOW)

    assert not update_check.is_due(now=NOW + timedelta(hours=11))
    assert update_check.is_due(now=NOW + timedelta(hours=12))


def test_no_answer_is_not_reported_as_up_to_date() -> None:
    update_check.check_now(lambda first: "<html>not found</html>", now=NOW)
    assert update_check.status()["up_to_date"] is False

    update_check.check_now(_answer("0.5.11"), now=NOW)
    assert update_check.status()["up_to_date"] is True

    update_check.check_now(_answer("0.5.12"), now=NOW)
    assert update_check.status()["up_to_date"] is False


def test_a_failed_request_keeps_the_last_known_release() -> None:
    update_check.check_now(_answer("0.5.12"), now=NOW)

    update_check.check_now(lambda first: "not json", now=NOW + timedelta(days=1))

    assert update_check.status()["latest"] == "0.5.12"


def test_the_check_runs_once_a_day() -> None:
    assert update_check.is_due(now=NOW)

    update_check.check_now(_answer("0.5.11"), now=NOW)

    assert not update_check.is_due(now=NOW + timedelta(hours=1))
    assert update_check.is_due(now=NOW + timedelta(days=1))


def test_a_start_at_the_same_time_each_morning_is_checked_every_day() -> None:
    update_check.check_now(_answer("0.5.11"), now=NOW + timedelta(seconds=40))

    assert update_check.is_due(now=NOW + timedelta(days=1))


def test_the_day_is_the_utc_day_whatever_the_saved_offset() -> None:
    tokyo = timezone(timedelta(hours=9))
    update_check.check_now(_answer("0.5.11"), now=datetime(2026, 12, 2, 8, 0, tzinfo=tokyo))  # 1 Dec 23:00 UTC

    assert not update_check.is_due(now=datetime(2026, 12, 1, 23, 30, tzinfo=timezone.utc))
    assert update_check.is_due(now=datetime(2026, 12, 2, 0, 5, tzinfo=timezone.utc))


def test_a_clock_set_back_does_not_silence_the_check() -> None:
    update_check.check_now(_answer("0.5.11"), now=NOW + timedelta(days=400))

    assert update_check.is_due(now=NOW)


def test_only_the_launcher_may_start_a_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_check, "_armed", False)

    assert not update_check.is_due(now=NOW)
    assert update_check.check_if_due(_refuse) is None


@pytest.mark.parametrize("version", ["0.5.11.dev3", "0.6.0rc1", "0.5.11+local"])
def test_an_unreleased_build_never_asks(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    monkeypatch.setattr(update_check, "__version__", version)

    assert not update_check.is_due(now=NOW)
    assert update_check.notice() is None


@pytest.mark.parametrize("value", ["0", "false", "OFF", " no "])
def test_the_environment_switch_turns_it_off(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(update_check.SWITCH, value)

    assert update_check.disabled_by() == "environment"
    assert not update_check.is_due(now=NOW)
    assert update_check.check_if_due(_refuse) is None


def test_ci_never_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")

    assert not update_check.is_due(now=NOW)


def _asked(now: datetime, *, answered: bool = True) -> tuple[str, ...]:
    """Run one check at ``now`` and return the periods it reported as first."""

    seen: list[tuple[str, ...]] = []

    def fetch(first: tuple[str, ...]) -> str:
        seen.append(first)
        if not answered:
            raise OSError("offline")
        return json.dumps({"latest": "0.5.11"})

    update_check.check_now(fetch, now=now)
    return seen[0]


def test_the_first_check_of_a_week_and_month_says_so() -> None:
    tuesday = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)  # ISO week 49

    assert _asked(tuesday) == ("week", "month")
    assert _asked(tuesday + timedelta(days=1)) == ()
    assert _asked(tuesday + timedelta(days=5)) == ()  # Sunday, same week
    assert _asked(tuesday + timedelta(days=6)) == ("week",)  # Monday, week 50
    assert _asked(datetime(2027, 1, 1, 9, 0, tzinfo=timezone.utc)) == ("week", "month")


def test_a_month_can_start_inside_a_week() -> None:
    assert _asked(datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc)) == ("week", "month")  # Monday

    assert _asked(datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)) == ("month",)  # Tuesday, same week


def test_a_week_that_spans_the_new_year_is_one_week() -> None:
    assert _asked(datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc)) == ("week", "month")  # Thursday, 2026-W53

    assert _asked(datetime(2027, 1, 2, 12, 0, tzinfo=timezone.utc)) == ("month",)  # Saturday, still 2026-W53


def test_an_unanswered_check_does_not_use_up_the_week() -> None:
    monday = datetime(2026, 12, 7, 12, 0, tzinfo=timezone.utc)

    assert _asked(monday, answered=False) == ("week", "month")
    assert _asked(monday + timedelta(days=1)) == ("week", "month")
    assert _asked(monday + timedelta(days=2)) == ()


def test_the_background_check_saves_its_answer() -> None:
    thread = update_check.check_if_due(_answer("0.6.0"))

    assert thread is not None
    thread.join(timeout=5)
    assert update_check.status()["latest"] == "0.6.0"
    assert update_check.check_if_due(_refuse) is None


def test_the_request_names_the_version_and_system_only() -> None:
    agent = update_check.user_agent()

    assert agent.startswith("coilEM/0.5.11 (") and agent.endswith(")")
    assert update_check.UPDATE_URL == "https://coilem.com/api/latest-version"
    assert "?" not in update_check.UPDATE_URL


def test_the_notice_is_printed_until_the_first_check() -> None:
    assert update_check.SWITCH in (update_check.notice() or "")

    update_check.check_now(_answer("0.5.11"), now=NOW)

    assert update_check.notice() is None


def test_a_damaged_file_reads_as_never_checked(tmp_path: Path) -> None:
    (tmp_path / "update_check.json").write_text("{broken", encoding="utf-8")

    assert update_check.status()["latest"] is None
    assert update_check.is_due(now=NOW)


def test_the_api_reports_the_check_and_has_no_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_check, "_armed", False)
    update_check.check_now(_answer("0.5.12"), now=NOW)
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    assert client.get("/updates").json()["latest"] == "0.5.12"

    assert client.post("/updates", json={"enabled": False}).status_code == 405


# --- The real request, against a server on this computer ---------------------


class _Site(http.server.ThreadingHTTPServer):
    """Answers every GET with the reply set on it and records what it was sent."""

    reply: tuple[int, dict[str, str], bytes] = (200, {}, b"")
    delay_s = 0.0
    daemon_threads = True

    def __init__(self) -> None:
        self.seen: list[tuple[str, dict[str, str]]] = []
        super().__init__(("127.0.0.1", 0), _SiteHandler)


class _SiteHandler(http.server.BaseHTTPRequestHandler):
    server: _Site

    def do_GET(self) -> None:
        self.server.seen.append((self.path, {key.lower(): value for key, value in self.headers.items()}))
        time.sleep(self.server.delay_s)
        status, headers, body = self.server.reply
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Site]:
    server = _Site()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(update_check, "UPDATE_URL", f"http://127.0.0.1:{server.server_port}/api/latest-version")
    monkeypatch.setattr(update_check, "REQUEST_TIMEOUT_S", 0.5)
    for proxy in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(proxy, raising=False)
    yield server
    server.shutdown()
    server.server_close()


def test_the_real_request_reads_the_version_and_sends_nothing_else(site: _Site) -> None:
    site.reply = (200, {"Content-Type": "application/json"}, b'{"latest": "0.5.12"}')

    assert update_check.check_now(now=NOW)

    assert update_check.status()["latest"] == "0.5.12"
    [(path, headers)] = site.seen
    assert path == "/api/latest-version"
    assert headers["user-agent"] == update_check.user_agent()
    # Whatever a Python HTTP client adds by itself, and nothing that names the user or the computer.
    assert set(headers) == {"user-agent", "accept", "accept-encoding", "host", "connection", "coilem-first-check"}
    assert headers["accept"] == "application/json"
    assert headers["coilem-first-check"] == "week, month"

    site.seen.clear()
    update_check.check_now(now=NOW + timedelta(days=1))

    assert "coilem-first-check" not in site.seen[0][1]


def test_a_redirect_is_not_followed(site: _Site) -> None:
    other = _Site()
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        other.reply = (200, {}, b'{"latest": "9.9.9"}')
        site.reply = (302, {"Location": f"http://127.0.0.1:{other.server_port}/elsewhere"}, b"")

        assert not update_check.check_now(now=NOW)

        assert other.seen == []
        assert update_check.status()["latest"] is None
    finally:
        other.shutdown()
        other.server_close()


@pytest.mark.parametrize("status", [404, 500, 503])
def test_an_error_page_is_silent(site: _Site, status: int) -> None:
    site.reply = (status, {}, b'{"latest": "9.9.9"}')

    assert not update_check.check_now(now=NOW)
    assert update_check.status()["latest"] is None


def test_a_web_page_instead_of_an_answer_is_ignored(site: _Site) -> None:
    site.reply = (200, {"Content-Type": "text/html"}, b"<!doctype html><title>coilEM</title>" + b" " * 20_000)

    assert not update_check.check_now(now=NOW)


def test_bytes_that_are_not_text_are_ignored(site: _Site) -> None:
    site.reply = (200, {}, b"\xff\xfe\x00latest")

    assert not update_check.check_now(now=NOW)


def test_a_server_that_does_not_answer_in_time_is_given_up_on(site: _Site) -> None:
    site.reply = (200, {}, b'{"latest": "0.5.12"}')
    site.delay_s = 2.0
    started = time.monotonic()

    assert not update_check.check_now(now=NOW)

    assert time.monotonic() - started < 1.5
    assert not update_check.is_due(now=NOW)


def test_nothing_listening_is_silent(monkeypatch: pytest.MonkeyPatch, site: _Site) -> None:
    port = site.server_port
    site.shutdown()
    site.server_close()
    monkeypatch.setattr(update_check, "UPDATE_URL", f"http://127.0.0.1:{port}/api/latest-version")

    assert not update_check.check_now(now=NOW)


def test_a_data_folder_that_cannot_be_written_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr(update_check, "_atomic_write_json", refuse)

    assert not update_check.check_now(_answer("0.5.12"), now=NOW)
    thread = update_check.check_if_due(_answer("0.5.12"))
    assert thread is not None
    thread.join(timeout=5)
    assert update_check._running is False
