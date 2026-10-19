"""Keep the ring renderer's imported-coordinate fixture tied to the real preview."""

import json
import re
from pathlib import Path

import pytest

from backend.models import MotorConfig
from backend.preview import generate_preview
from backend.reference_models.prius import case_config, geometry_asset_sha256

pytestmark = pytest.mark.pr


def test_ring_fixture_keeps_all_actual_prius_slots_and_coil_connections() -> None:
    data = json.loads((Path(__file__).parent / "fixtures/prius_winding_ring.json").read_text(encoding="utf-8"))
    preview = generate_preview(MotorConfig.model_validate(case_config("prius-2004-loaded-torque-v1")))
    assert data["source_geometry_sha256"] == geometry_asset_sha256()
    slots = [r for r in preview.regions if re.match(r"^slot_\d+_", r.region_type)]
    assert len(data["regions"]) == len(slots) == 48
    for expected, actual in zip(data["regions"], slots, strict=True):
        assert expected["region_type"] == actual.region_type
        assert len(expected["points"]) == len(actual.points)
        # Platform libm implementations may differ in the final decimal places.
        # Keep identities/order exact and use a sub-nanometre coordinate tolerance.
        for expected_point, actual_point in zip(expected["points"], actual.points, strict=True):
            assert expected_point == pytest.approx(actual_point, rel=0, abs=1e-10)
    assert data["coils"] == [c.model_dump() for c in preview.winding_coils]
