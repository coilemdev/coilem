"""Recognize and remove local machine paths from text meant for publication.

``tools/verify_snapshot.py --publication`` rejects committed files that match
these patterns, and the shareable benchmark report is checked by the same
rules (#71). The script loads this file by path, so it uses only the standard
library.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

ABSOLUTE_USER_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+\\", re.IGNORECASE),
    re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/", re.IGNORECASE),
)
LOCAL_PATH_PLACEHOLDER = "<local path>"
# A home directory, then any path characters up to the next separator in prose.
_USER_PATH_SPANS = (
    re.compile(r"[A-Za-z]:\\Users\\[^\s\"'`<>|]+", re.IGNORECASE),
    re.compile(r"/(?:Users|home)/[^\s\"'`<>|]+", re.IGNORECASE),
)


def contains_local_path(text: str) -> bool:
    return any(pattern.search(text) for pattern in ABSOLUTE_USER_PATH_PATTERNS)


def redact_local_paths(text: str, known: Iterable[str] = ()) -> str:
    """Replace known local paths (longest first) and any user-home path with a placeholder."""

    for path in sorted({path for path in known if path and len(path) > 1}, key=len, reverse=True):
        text = text.replace(path, LOCAL_PATH_PLACEHOLDER)
    for pattern in _USER_PATH_SPANS:
        text = pattern.sub(LOCAL_PATH_PLACEHOLDER, text)
    return text
