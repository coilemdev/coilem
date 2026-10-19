"""Keep the ring renderer's imported-coordinate fixture tied to the real preview."""

import json
import re
from pathlib import Path

import pytest

from backend.models import MotorConfig
from backend.preview import generate_preview
from backend.reference_models.prius import case_config, geometry_asset_sha256

pytestmark = pytest.mark.pr


def test_ring_fixture_keeps_all_actual_prius_slots_and_coil_connections():
    data = json.loads((Path(__file__).parent / "fixtures/prius_winding_ring.json").read_text(encoding="utf-8"))
    preview = generate_preview(MotorConfig.model_validate(case_config("prius-2004-loaded-torque-v1")))
    assert data["source_geometry_sha256"] == geometry_asset_sha256()
    assert data["regions"] == [
        {"region_type": r.region_type, "points": r.points}
        for r in preview.regions if re.match(r"^slot_\d+_", r.region_type)
    ]
    assert len(data["regions"]) == 48
    assert data["coils"] == [c.model_dump() for c in preview.winding_coils]
