"""Lesson progress is kept in the user data root, not only in the browser."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import learning_progress


@pytest.fixture(autouse=True)
def _data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))


def test_nothing_saved_reads_as_no_lessons() -> None:
    assert learning_progress.read_completed_lessons() == []


def test_saved_lessons_are_read_back(tmp_path: Path) -> None:
    stored = learning_progress.update_completed_lessons(add=["rotor-chase", "airgap-tax", "airgap-tax"])

    assert stored == ["airgap-tax", "rotor-chase"]
    assert learning_progress.read_completed_lessons() == ["airgap-tax", "rotor-chase"]
    assert (tmp_path / "learning_progress.json").is_file()


def test_a_save_keeps_lessons_saved_by_another_browser() -> None:
    learning_progress.update_completed_lessons(add=["follow-the-flux", "airgap-tax"])
    learning_progress.update_completed_lessons(add=["current-field"])

    stored = learning_progress.update_completed_lessons(add=["iron-saturation"])

    assert stored == ["airgap-tax", "current-field", "follow-the-flux", "iron-saturation"]


def test_a_restarted_lesson_is_removed() -> None:
    learning_progress.update_completed_lessons(add=["follow-the-flux", "airgap-tax"])

    assert learning_progress.update_completed_lessons(remove=["airgap-tax"]) == ["follow-the-flux"]


def test_malformed_ids_are_dropped() -> None:
    stored = learning_progress.update_completed_lessons(add=["airgap-tax", "../etc", "", 7, "A" * 80])

    assert stored == ["airgap-tax"]


def test_a_damaged_file_reads_as_no_lessons(tmp_path: Path) -> None:
    (tmp_path / "learning_progress.json").write_text("{not json", encoding="utf-8")

    assert learning_progress.read_completed_lessons() == []


def test_progress_routes_round_trip() -> None:
    from fastapi.testclient import TestClient

    from backend.public_main import create_app

    client = TestClient(create_app(bound_port=2645), base_url="http://127.0.0.1:2645")
    origin = {"Origin": "http://127.0.0.1:2645"}

    saved = client.post("/tutorials/progress", json={"add": ["airgap-tax"]}, headers=origin)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"completed": ["airgap-tax"]}
    assert client.get("/tutorials/progress").json() == {"completed": ["airgap-tax"]}
    removed = client.post("/tutorials/progress", json={"remove": ["airgap-tax"]}, headers=origin)
    assert removed.json() == {"completed": []}
