"""Load and hash the frozen Elmer numerical profile."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.resources import package_resource

PROFILE_PATH = package_resource("elmer", "profiles", "v1.json")


def load_profile() -> tuple[dict[str, Any], str]:
    raw = PROFILE_PATH.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema_version") != "openem_elmer_numerical_profile/v1":
        raise ValueError(f"Unsupported Elmer numerical profile: {PROFILE_PATH}")
    return payload, hashlib.sha256(raw).hexdigest()
