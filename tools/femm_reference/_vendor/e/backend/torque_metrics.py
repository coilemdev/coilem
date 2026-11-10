"""Shared torque waveform scalar metrics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def torque_at_q_axis_nm(
    angles_elec_deg: Any,
    torque_nm: Any,
    *,
    q_axis_elec_deg: float = 0.0,
) -> float | None:
    """Return the torque sample nearest the q-axis electrical angle.

    coilEM's SPM loaded-torque convention treats 0 electrical degrees as the
    q-axis aligned sample. This scalar is intentionally separate from average
    torque, which can be near zero for a full sinusoidal sweep.
    """
    if not isinstance(angles_elec_deg, Sequence) or isinstance(angles_elec_deg, (str, bytes)):
        return None
    if not isinstance(torque_nm, Sequence) or isinstance(torque_nm, (str, bytes)):
        return None

    count = min(len(angles_elec_deg), len(torque_nm))
    if count <= 0:
        return None

    target = _finite_number(q_axis_elec_deg)
    if target is None:
        target = 0.0

    best_distance: float | None = None
    best_torque: float | None = None
    for index in range(count):
        angle = _finite_number(angles_elec_deg[index])
        torque = _finite_number(torque_nm[index])
        if angle is None or torque is None:
            continue
        distance = abs(((angle - target + 180.0) % 360.0) - 180.0)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_torque = torque
    return best_torque
