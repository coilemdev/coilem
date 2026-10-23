"""Magnet temperature: Br and HcJ derated from 20 °C (#137).

coilEM's magnets are linear in the solve: remanence Br with a recoil
permeability, so the coercive field follows Br. Derating therefore scales Br
(the solver's COILEM_MAGNET_BR_SCALE), which lowers the magnet flux, back EMF
and torque. Intrinsic coercivity HcJ is derated and recorded for the
demagnetisation margin a later release checks; the field solve does not use it.

Coefficients are the reversible temperature coefficients in the same Arnold
Magnetic Technologies NdFeB grade table the room-temperature Br values come
from (MATERIALS.md, "Magnet temperature"). Grades without cited coefficients
(ferrite and the Prius presets) are refused rather than given a guessed value;
the pinned Prius reference keeps its own published 20/60 °C cases.

The linear model is used from −40 °C up to the temperature where HcJ would
fall to a quarter of its 20 °C value; above the grade's maximum operating
temperature the magnet risks irreversible demagnetisation, which coilEM does
not model, so results there carry a warning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.models.performance import MAGNET_TEMPERATURE_STATUS_REASON

REFERENCE_TEMP_C = 20.0
MIN_TEMP_C = -40.0
# Below this share of its 20 °C value the linear HcJ model has no physical meaning.
_MIN_HCJ_SHARE = 0.25
_MAX_TEMP_C = 200.0

ARNOLD_NDFEB_TABLE = {
    "label": "Arnold Magnetic Technologies, Neodymium Iron Boron Magnets grade table (Rev. Temp. Coef. Br and HcJ, %/°C)",
    "url": "https://www.arnoldmagnetics.com/products/neodymium-iron-boron-magnets/",
}


@dataclass(frozen=True)
class GradeTemperature:
    """Reversible temperature coefficients of one grade, in percent per kelvin."""

    alpha_br_pct_per_K: float
    alpha_hcj_pct_per_K: float
    hcj_20C_kA_m: float  # Arnold's minimum HcJ at room temperature
    max_operating_C: float


# Arnold grade table, read 2026-10-21: Br %/°C, HcJ %/°C, HcJ min kA/m, max °C.
GRADE_TEMPERATURE: dict[str, GradeTemperature] = {
    "N35": GradeTemperature(-0.12, -0.618, 955.0, 80.0),
    "N42": GradeTemperature(-0.12, -0.75, 955.0, 80.0),
    "N48": GradeTemperature(-0.12, -0.75, 955.0, 80.0),
    "N52": GradeTemperature(-0.12, -0.75, 876.0, 60.0),
    "N48SH": GradeTemperature(-0.12, -0.535, 1512.0, 150.0),
}


def grade_temperature_range_C(grade: str) -> tuple[float, float] | None:
    """Where the linear coefficients are used for a grade, or None without coefficients."""

    coefficients = GRADE_TEMPERATURE.get(grade)
    if coefficients is None:
        return None
    # HcJ(T) / HcJ(20 °C) = 1 + α·ΔT falls to the floor at ΔT = (floor − 1) / α.
    to_floor = (_MIN_HCJ_SHARE - 1.0) / (coefficients.alpha_hcj_pct_per_K / 100.0)
    return MIN_TEMP_C, min(_MAX_TEMP_C, REFERENCE_TEMP_C + to_floor)


def magnet_temperature_unavailable_reason(grade: str, temperature_C: float | None) -> str | None:
    """Why a magnet temperature cannot be used for this grade; None when it can (or none is set)."""

    if temperature_C is None:
        return None
    window = grade_temperature_range_C(grade)
    if window is None:
        return (
            f"No cited temperature coefficients for {grade}: magnet temperature is available for "
            f"{', '.join(GRADE_TEMPERATURE)}. Leave it empty for the 20 °C catalogue values."
        )
    low, high = window
    if not low <= temperature_C <= high:
        return (
            f"{grade} magnet temperature must lie between {low:g} and {high:.0f} °C; beyond that the linear "
            "coefficients no longer describe the magnet."
        )
    return None


def br_scale(grade: str, temperature_C: float) -> float:
    """Br(T) / Br(20 °C) for a grade with coefficients."""

    return 1.0 + GRADE_TEMPERATURE[grade].alpha_br_pct_per_K / 100.0 * (temperature_C - REFERENCE_TEMP_C)


def magnet_temperature_record(config: Any) -> dict[str, Any] | None:
    """Derated magnet values a solve uses, for SolveMetadata; None at the catalogue's 20 °C or for the Prius reference."""

    solve_params = getattr(config, "solve_params", None)
    temperature = getattr(solve_params, "magnet_temperature_C", None)
    if temperature is None or getattr(config, "geometry_reference", None):
        return None
    grade = config.materials.magnet_grade
    if magnet_temperature_unavailable_reason(grade, temperature) is not None:
        return None
    from backend.public_material_catalog import MAGNET_SOLVER_INPUTS

    coefficients = GRADE_TEMPERATURE[grade]
    br_20 = MAGNET_SOLVER_INPUTS[grade][1]
    delta = float(temperature) - REFERENCE_TEMP_C
    return {
        "magnet_temperature_C": float(temperature),
        "magnet_remanence_T": br_20 * br_scale(grade, temperature),
        "magnet_intrinsic_coercivity_kA_m": coefficients.hcj_20C_kA_m * (1.0 + coefficients.alpha_hcj_pct_per_K / 100.0 * delta),
        "magnet_temperature_status": "experimental",
        "magnet_temperature_status_reason": MAGNET_TEMPERATURE_STATUS_REASON,
    }


def magnet_temperature_warning(config: Any) -> str | None:
    """A note when the magnet runs above its grade's maximum operating temperature."""

    solve_params = getattr(config, "solve_params", None)
    temperature = getattr(solve_params, "magnet_temperature_C", None)
    grade = getattr(getattr(config, "materials", None), "magnet_grade", None)
    coefficients = GRADE_TEMPERATURE.get(grade or "")
    if temperature is None or coefficients is None or temperature <= coefficients.max_operating_C:
        return None
    return (
        f"{grade} is rated to {coefficients.max_operating_C:.0f} °C; at {temperature:g} °C the magnet risks irreversible "
        "demagnetisation, which coilEM does not model. A high-temperature grade such as N48SH is rated to 150 °C."
    )
