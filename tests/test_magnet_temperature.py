"""Magnet temperature (#137): cited coefficients, ranges, the solver's Br scale and the run record."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.magnet_temperature import (
    ARNOLD_NDFEB_TABLE,
    GRADE_TEMPERATURE,
    br_scale,
    grade_temperature_range_C,
    magnet_temperature_record,
    magnet_temperature_unavailable_reason,
    magnet_temperature_warning,
)
from backend.magneto2d_adapter import _magneto2d_env_overrides
from backend.models import MotorConfig
from backend.public_policy import PublicConfigError, parse_public_motor_config

RAW = json.loads(Path("tests/fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"))


def _config(temperature, grade="N42", **solve_params) -> MotorConfig:
    raw = deepcopy(RAW)
    raw["materials"]["magnet_grade"] = grade
    raw["solve_params"].update(magnet_temperature_C=temperature, **solve_params)
    return MotorConfig.model_validate(raw)


def test_coefficients_are_arnolds_grade_table():
    assert "arnoldmagnetics.com" in ARNOLD_NDFEB_TABLE["url"]
    assert {grade: (row.alpha_br_pct_per_K, row.alpha_hcj_pct_per_K, row.max_operating_C) for grade, row in GRADE_TEMPERATURE.items()} == {
        "N35": (-0.12, -0.618, 80.0),
        "N42": (-0.12, -0.75, 80.0),
        "N48": (-0.12, -0.75, 80.0),
        "N52": (-0.12, -0.75, 60.0),
        "N48SH": (-0.12, -0.535, 150.0),
    }


def test_br_scales_linearly_from_20_C():
    assert br_scale("N42", 20.0) == 1.0
    assert br_scale("N42", 100.0) == pytest.approx(1 - 0.0012 * 80)
    assert br_scale("N48SH", -20.0) == pytest.approx(1 + 0.0012 * 40)


def test_each_grade_is_used_until_its_coercivity_falls_to_a_quarter():
    assert grade_temperature_range_C("N42") == pytest.approx((-40.0, 120.0))
    assert grade_temperature_range_C("N35")[1] == pytest.approx(20 + 75 / 0.618)
    assert grade_temperature_range_C("N48SH")[1] == pytest.approx(20 + 75 / 0.535)
    assert grade_temperature_range_C("Ferrite_Y30") is None


@pytest.mark.parametrize(
    ("grade", "temperature", "reason"),
    [
        ("N42", None, None),
        ("N42", 100.0, None),
        ("N42", 121.0, "between -40 and 120"),
        ("N42", -41.0, "between -40 and 120"),
        ("Ferrite_Y30", 60.0, "No cited temperature coefficients for Ferrite_Y30"),
        ("Prius_2004_NdFeB", 60.0, "No cited temperature coefficients"),
    ],
)
def test_unavailable_reasons(grade, temperature, reason):
    got = magnet_temperature_unavailable_reason(grade, temperature)
    assert (got is None) if reason is None else (reason in got)


def test_the_run_records_the_derated_values():
    record = magnet_temperature_record(_config(100.0))
    assert record["magnet_temperature_C"] == 100.0
    assert record["magnet_remanence_T"] == pytest.approx(1.315 * (1 - 0.0012 * 80))
    assert record["magnet_intrinsic_coercivity_kA_m"] == pytest.approx(955 * (1 - 0.0075 * 80))
    assert magnet_temperature_record(_config(None)) is None


def test_a_warning_above_the_grades_rating():
    assert "rated to 80 °C" in magnet_temperature_warning(_config(100.0))
    assert magnet_temperature_warning(_config(70.0)) is None
    assert magnet_temperature_warning(_config(120.0, grade="N48SH")) is None


def test_the_solver_gets_the_br_scale_and_nothing_at_20_C():
    assert "COILEM_MAGNET_BR_SCALE" not in _magneto2d_env_overrides(_config(None))
    assert "COILEM_MAGNET_BR_SCALE" not in _magneto2d_env_overrides(_config(20.0))
    assert float(_magneto2d_env_overrides(_config(100.0))["COILEM_MAGNET_BR_SCALE"]) == pytest.approx(0.904)
    # The stator-only field keeps the magnets switched off whatever their temperature.
    assert _magneto2d_env_overrides(_config(100.0, field_composition_source="armature"))["COILEM_MAGNET_BR_SCALE"] == "0"


def test_validation_and_the_public_policy_follow_the_grade():
    assert _config(100.0).solve_params.magnet_temperature_C == 100.0
    with pytest.raises(ValidationError, match="No cited temperature coefficients"):
        _config(60.0, grade="Ferrite_Y30")
    raw = deepcopy(RAW)
    raw["solve_params"]["magnet_temperature_C"] = 100.0
    assert parse_public_motor_config(raw).solve_params.magnet_temperature_C == 100.0
    raw["solve_params"]["magnet_temperature_C"] = 130.0
    with pytest.raises(PublicConfigError, match="between -40 and 120"):
        parse_public_motor_config(raw)


def test_the_report_records_the_magnet_temperature_and_derated_values():
    import io

    pypdf = pytest.importorskip("pypdf")
    from backend.public_report import build_public_run_pdf
    from tests.test_loss_breakdown import _stored_result

    raw = deepcopy(RAW)
    raw["solve_params"]["magnet_temperature_C"] = 100.0
    result = _stored_result()
    result["solve_metadata"].update(magnet_temperature_C=100.0, magnet_remanence_T=1.18876, magnet_intrinsic_coercivity_kA_m=382.0)
    pdf = build_public_run_pdf(project=raw, request={"resolved_config": raw}, result=result, material={}, manifest={})
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "Magnet Br at temperature" in text and "1.189 T" in text and "382 kA/m" in text


def test_the_app_mirrors_the_cited_coefficients():
    import re

    source = Path("frontend/src/public/magnetTemperature.ts").read_text(encoding="utf-8")
    for grade, row in GRADE_TEMPERATURE.items():
        match = re.search(rf"{grade}: \{{ alphaBr: ([-0-9.]+), alphaHcj: ([-0-9.]+), hcj20: ([0-9.]+), maxOperating: ([0-9.]+) \}}", source)
        assert match, grade
        assert tuple(float(value) for value in match.groups()) == (
            row.alpha_br_pct_per_K, row.alpha_hcj_pct_per_K, row.hcj_20C_kA_m, row.max_operating_C
        )
