"""Which tutorial lessons are finished, kept in the user data root.

The browser also keeps this list, but its storage belongs to one origin, port
included, so a launch on a fallback port or in another browser started from
zero. The data root is the same wherever the app is opened from.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from backend.solve_workspace import _atomic_write_json, user_data_root

_FILE_NAME = "learning_progress.json"
_LESSON_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
MAX_LESSON_IDS = 64
_LOCK = threading.Lock()


def _path() -> Path:
    return user_data_root() / _FILE_NAME


def clean_lesson_ids(values: object) -> list[str]:
    """Keep well-formed lesson ids, once each, in sorted order."""

    if not isinstance(values, list):
        return []
    ids = {value for value in values if isinstance(value, str) and _LESSON_ID.fullmatch(value)}
    return sorted(ids)[:MAX_LESSON_IDS]


def read_completed_lessons() -> list[str]:
    """Return the saved lesson ids; a missing or damaged file reads as none."""

    try:
        saved = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return clean_lesson_ids(saved.get("completed") if isinstance(saved, dict) else None)


def update_completed_lessons(add: object = None, remove: object = None) -> list[str]:
    """Mark lessons finished or not finished and return the saved list.

    Changes are applied to what is on disk, so two browsers open at once each
    keep the lessons the other one finished.
    """

    with _LOCK:
        completed = set(read_completed_lessons())
        completed.update(clean_lesson_ids(add))
        completed.difference_update(clean_lesson_ids(remove))
        saved = sorted(completed)[:MAX_LESSON_IDS]
        _atomic_write_json(_path(), {"schema_version": 1, "completed": saved})
    return saved
