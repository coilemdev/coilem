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
    stored = learning_progress.write_completed_lessons(["rotor-chase", "airgap-tax", "airgap-tax"])

    assert stored == ["airgap-tax", "rotor-chase"]
    assert learning_progress.read_completed_lessons() == ["airgap-tax", "rotor-chase"]
    assert (tmp_path / "learning_progress.json").is_file()


def test_malformed_ids_are_dropped() -> None:
    stored = learning_progress.write_completed_lessons(["airgap-tax", "../etc", "", 7, "A" * 80])

    assert stored == ["airgap-tax"]


def test_a_damaged_file_reads_as_no_lessons(tmp_path: Path) -> None:
    (tmp_path / "learning_progress.json").write_text("{not json", encoding="utf-8")

    assert learning_progress.read_completed_lessons() == []
