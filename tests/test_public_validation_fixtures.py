"""Public validation fixtures remain distinct, supported, and previewable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.geometry import validate_geometry
from backend.models import MotorConfig
from backend.public_main import app
from backend.public_policy import public_config_support_error

FIXTURE_ROOT = Path("references/benchmark_configs")
EXPECTED_FIXTURES = {
    "validation_ipm_10p_v_shape_medium.openem": ("IPM", "v_shape", 10, 12, 180.0),
    "validation_ipm_14p_flat_buried_large.openem": ("IPM", "flat_buried", 14, 18, 320.0),
    "validation_spm_24p_small.openem": ("SPM", "flat_buried", 24, 27, 90.0),
}


@pytest.mark.parametrize("filename,expected", EXPECTED_FIXTURES.items())
def test_public_validation_fixture_is_supported_and_previewable(
    filename: str,
    expected: tuple[str, str, int, int, float],
) -> None:
    raw = json.loads((FIXTURE_ROOT / filename).read_text(encoding="utf-8"))
    config = MotorConfig.model_validate(raw)
    topology, ipm_topology, poles, slots, stator_od_mm = expected

    assert (
        config.topology,
        config.rotor.ipm_topology,
        config.rotor.pole_count,
        config.stator.slot_count,
        config.stator.OD_mm,
    ) == (topology, ipm_topology, poles, slots, stator_od_mm)
    assert public_config_support_error(config, require_solve_params=True) is None
    assert validate_geometry(config) == []
    assert config.solve_options is not None
    assert config.solve_options.thd_analysis is False

    response = TestClient(app, base_url="http://127.0.0.1").post("/preview", json=raw)
    assert response.status_code == 200, response.text


def test_public_validation_fixture_sizes_are_deliberately_distinct() -> None:
    configs = {
        filename: MotorConfig.model_validate_json(
            (FIXTURE_ROOT / filename).read_text(encoding="utf-8")
        )
        for filename in EXPECTED_FIXTURES
    }

    assert configs["validation_spm_24p_small.openem"].stator.OD_mm < configs[
        "validation_ipm_10p_v_shape_medium.openem"
    ].stator.OD_mm < configs[
        "validation_ipm_14p_flat_buried_large.openem"
    ].stator.OD_mm
