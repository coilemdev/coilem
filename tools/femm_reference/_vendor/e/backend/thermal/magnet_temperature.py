"""Magnet Br(T)/Hc(T) derating for demagnetization checks (S48-03).

Room-temperature catalog values live in ``MAGNET_PROPERTIES``. Temperature
coefficients below are grade-family defaults (NdFeB / ferrite) with sources
cited in the module docstring. They are intentionally conservative until
the S50 calibration rig fits per-lot curves.

Sources (coefficients):
- NdFeB α_Br ≈ −0.12 %/K, α_Hcj ≈ −0.55 %/K (typical sintered NdFeB datasheets;
  Arnold Magnetic Technologies / Hitachi Metals application notes).
- Ferrite α_Br ≈ −0.20 %/K, α_Hcj ≈ +0.40 %/K (sign flip on coercivity).
- Reference temperature T0 = 20 °C (catalog Br/Hci).

Validity: linear coefficients are only trusted inside a grade-specific
temperature window. Outside that window we **reject** rather than invent
high-temperature physics (Hci must never reverse sign via extrapolation).
"""

from __future__ import annotations

from typing import Any

# Grade → (alpha_Br_per_K, alpha_Hci_per_K). Hci coefficients apply to the
# intrinsic coercivity magnitude used for the knee estimate.
_TEMP_COEFFS: dict[str, tuple[float, float]] = {
    "N35": (-0.0012, -0.0055),
    "N42": (-0.0012, -0.0055),
    "N48": (-0.0012, -0.0055),
    "N52": (-0.0012, -0.0055),
    "N48SH": (-0.0011, -0.0050),  # high-temp grade: slightly better Hci retention
    "Prius_2004_NdFeB": (-0.0012, -0.0055),
    "Ferrite_Y30": (-0.0020, 0.0040),
}

# Inclusive [T_min_C, T_max_C] for the linear coefficient model.
# NdFeB α_Hci = −0.0055 crosses zero magnitude at ~201.8 °C; keep the
# supported window strictly below that so Hci cannot reverse sign.
_GRADE_VALIDITY_C: dict[str, tuple[float, float]] = {
    "N35": (-40.0, 180.0),
    "N42": (-40.0, 180.0),
    "N48": (-40.0, 180.0),
    "N52": (-40.0, 180.0),
    "N48SH": (-40.0, 200.0),
    "Prius_2004_NdFeB": (-40.0, 180.0),
    "Ferrite_Y30": (-40.0, 250.0),
}

REFERENCE_TEMP_C = 20.0


class MagnetTemperatureError(ValueError):
    """Invalid magnet temperature derating request."""


def known_temperature_coefficient_grades() -> frozenset[str]:
    """Grades that have Br(T)/Hc(T) rows (required when derating)."""
    return frozenset(_TEMP_COEFFS)


def temperature_coefficients(magnet_grade: str) -> tuple[float, float]:
    """Return (α_Br, α_Hci) per kelvin for the grade.

    Unknown grades raise ``KeyError`` so a future ferrite (or other) entry
    added to ``MAGNET_PROPERTIES`` without a coefficient row cannot silently
    pick up the NdFeB Hc sign. Only call this when derating is actually
    requested (``magnet_temperature_C`` set); room-temp demag must not
    require coefficients.
    """
    if magnet_grade not in _TEMP_COEFFS:
        raise KeyError(
            f"no Br(T)/Hc(T) coefficients for magnet_grade={magnet_grade!r}; "
            f"add an entry to backend.thermal.magnet_temperature._TEMP_COEFFS"
        )
    return _TEMP_COEFFS[magnet_grade]


def grade_temperature_validity_C(magnet_grade: str) -> tuple[float, float]:
    """Return inclusive (T_min_C, T_max_C) for the linear coefficient model."""
    if magnet_grade not in _GRADE_VALIDITY_C:
        raise KeyError(
            f"no temperature validity window for magnet_grade={magnet_grade!r}"
        )
    return _GRADE_VALIDITY_C[magnet_grade]


def resolve_manual_magnet_temperature_C(config: Any) -> float | None:
    """Read ``solve_params.magnet_temperature_C`` when set (S49-06)."""
    sp = getattr(config, "solve_params", None)
    if sp is None:
        return None
    raw = getattr(sp, "magnet_temperature_C", None)
    if raw is None:
        return None
    return float(raw)


def derate_magnet_properties(
    mag_props: dict[str, Any],
    magnet_grade: str,
    temperature_c: float,
) -> dict[str, float]:
    """Return Br [T] and Hci [kA/m] derated to ``temperature_c``.

    Hci in ``MAGNET_PROPERTIES`` is stored as a negative kA/m value. Derating
    scales the magnitude; the sign is preserved. Temperatures outside the
    grade validity window raise :class:`MagnetTemperatureError` — we do not
    invent high-temperature physics via unbounded linear extrapolation.
    """
    br0 = float(mag_props["remanence_T"])
    hci0 = float(mag_props["coercivity_bH_kA_m"])
    alpha_br, alpha_hci = temperature_coefficients(magnet_grade)
    t_min, t_max = grade_temperature_validity_C(magnet_grade)
    temperature_c = float(temperature_c)
    if temperature_c < t_min or temperature_c > t_max:
        raise MagnetTemperatureError(
            f"magnet_grade={magnet_grade!r} temperature {temperature_c} °C is "
            f"outside the supported linear-coefficient range "
            f"[{t_min}, {t_max}] °C; refuse extrapolation rather than "
            f"fabricate high-temperature Br/Hci"
        )

    dT = temperature_c - REFERENCE_TEMP_C
    br_scale = 1.0 + alpha_br * dT
    hci_scale = 1.0 + alpha_hci * dT
    # Defense in depth: never allow a sign-reversing scale even if a validity
    # window is mis-configured relative to the coefficient zero-crossing.
    if br_scale <= 0.0:
        raise MagnetTemperatureError(
            f"Br scale factor {br_scale} <= 0 at {temperature_c} °C for "
            f"{magnet_grade!r}; linear model invalid"
        )
    if hci_scale <= 0.0:
        raise MagnetTemperatureError(
            f"Hci scale factor {hci_scale} <= 0 at {temperature_c} °C for "
            f"{magnet_grade!r}; linear model would reverse coercivity sign"
        )

    br_t = br0 * br_scale
    hci_mag = abs(hci0) * hci_scale
    hci_t = -hci_mag if hci0 < 0 else hci_mag

    # Physical floors — never allow negative Br or zero coercivity magnitude.
    br_t = max(br_t, 1.0e-6)
    if abs(hci_t) < 1.0e-6:
        hci_t = -1.0e-6 if hci0 < 0 else 1.0e-6

    # Sign must match catalog (NdFeB catalog Hci is negative).
    if (hci0 < 0.0) != (hci_t < 0.0):
        raise MagnetTemperatureError(
            f"Hci sign reversed for {magnet_grade!r} at {temperature_c} °C "
            f"(catalog={hci0}, derated={hci_t})"
        )

    return {
        "remanence_T": br_t,
        "coercivity_kA_m": hci_t,
        "temperature_C": temperature_c,
        "reference_temperature_C": REFERENCE_TEMP_C,
        "alpha_Br_per_K": alpha_br,
        "alpha_Hci_per_K": alpha_hci,
        "validity_min_C": t_min,
        "validity_max_C": t_max,
    }
