"""Rotor layout facts shared across the solve pipeline.

An outer-rotor (outrunner) motor puts the stator inside and the rotor outside.
Code that still assumes the rotor sits inside the stator calls
``require_inner_rotor`` so an outer rotor fails loudly instead of producing a
silently wrong field or torque.
"""
from __future__ import annotations

from typing import Any


class OuterRotorUnsupportedError(ValueError):
    """An outer-rotor design reached a path that only supports inner rotors."""


def is_outer_rotor(config: Any) -> bool:
    return getattr(config, "rotor_layout", "inner") == "outer"


def outer_rotor_airgap_mm(config: Any) -> float:
    """Gap between the stator's tooth tips and an outer rotor's magnet faces."""
    return config.rotor.ID_mm / 2 - config.rotor.magnet_thickness_mm - config.stator.OD_mm / 2


def require_inner_rotor(config: Any, where: str) -> None:
    if is_outer_rotor(config):
        raise OuterRotorUnsupportedError(f"Outer-rotor (outrunner) designs are not supported by {where}.")
