"""An invalid motor configuration reports what is wrong and where."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError, field_validator

from backend.public_main import app
from backend.public_policy import _MAX_VALIDATION_MESSAGE_CHARS, _validation_error

VALID_CONFIG = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "spm_4p12s_simple.json").read_text(encoding="utf-8")
)


def _rejection(route: str, mutate) -> dict:
    config = deepcopy(VALID_CONFIG)
    mutate(config)
    response = TestClient(app, base_url="http://127.0.0.1").post(route, json=config)
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "UNSUPPORTED_LAUNCH_CONFIG"
    return detail


@pytest.mark.parametrize("route", ["/preview", "/solve/validate"])
def test_section_validator_reason_is_reported_with_its_section(route: str) -> None:
    # The SPM 24p example's fault in #18: tooth shoes wider than the slot opening.
    detail = _rejection(
        route,
        lambda config: config["stator"].update(
            slot_opening_mm=2.1, tooth_shoe_enabled=True, tooth_shoe_overhang_mm=1.5
        ),
    )
    assert detail["field"] == "stator"
    assert detail["message"].startswith(
        "stator: tooth shoe overhang is too large for the slot opening: 2*overhang (3 mm)"
    )


@pytest.mark.parametrize(
    ("mutate", "field", "message"),
    [
        (
            lambda config: config["stator"].update(tooth_shoe_height_mm=20),
            "stator.tooth_shoe_height_mm",
            "stator.tooth_shoe_height_mm: Input should be less than or equal to 10",
        ),
        (
            lambda config: config["winding"].pop("turns_per_coil"),
            "winding.turns_per_coil",
            "winding.turns_per_coil: Field required",
        ),
        (
            lambda config: config["materials"].update(magnet_grade="N99"),
            "materials.magnet_grade",
            "materials.magnet_grade: Input should be 'N35', 'N42', 'N48', 'N52', 'N48SH', "
            "'Ferrite_Y30', 'Prius_2004_NdFeB' or 'ORNL_Prius_2004_NdFeB'",
        ),
    ],
)
def test_field_errors_lead_with_the_field(mutate, field: str, message: str) -> None:
    detail = _rejection("/preview", mutate)
    assert (detail["field"], detail["message"]) == (field, message)


def test_validator_prefix_is_removed() -> None:
    detail = _rejection("/preview", lambda config: config["materials"].update(stator_steel="unobtainium"))
    assert detail["field"] == "materials"
    assert detail["message"].startswith("materials: Steel selection requires")
    assert "Value error" not in detail["message"]


def test_message_does_not_repeat_the_input() -> None:
    submitted = "<img src=x>" + "X" * 5000
    detail = _rejection("/preview", lambda config: config.update(topology=submitted))
    assert detail["field"] == "topology"
    assert detail["message"] == "topology: Input should be 'IPM' or 'SPM'"
    assert "<img" not in json.dumps(detail)


def test_long_validator_message_is_truncated() -> None:
    class Probe(BaseModel):
        value: int

        @field_validator("value")
        @classmethod
        def reject(cls, value: int) -> int:
            raise ValueError("y" * 1000)

    with pytest.raises(ValidationError) as caught:
        Probe(value=1)
    error = _validation_error(caught.value)
    assert len(str(error)) == _MAX_VALIDATION_MESSAGE_CHARS
    assert str(error).startswith("value: yyy")
    assert str(error).endswith("\u2026")
    assert error.field == "value"
