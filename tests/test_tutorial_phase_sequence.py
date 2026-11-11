"""Lessons 7 and 8: the phase sequence changes the currents, the target and the rotor side.

No solver or mesher runs here: the fixture functions get a stand-in runner that
writes an empty report, so only the angles and currents they attach are checked.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

import pytest

from backend import tutorial_fields
from backend.tutorial_fields import (
    _label_sequence_frame,
    _sequence_solver_angles,
    run_rotating_field_motor_fixture,
    run_three_phase_motor_fixture,
)

PEAK_A = 8.0
LAG_DEG = tutorial_fields._ROTATING_FIELD_MOTOR_LAG_DEG


def _empty_report_runner(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
    output_path = Path(command[command.index("-o") + 1])
    output_path.write_text(json.dumps({}))
    return subprocess.CompletedProcess(command, 0, "", "")


def _signed(angle_deg: float) -> float:
    return (angle_deg + 180.0) % 360.0 - 180.0


@pytest.mark.parametrize("angle_deg", [0.0, 33.75, 90.0, 191.25, 270.0])
def test_two_phase_reverse_sequence_flips_phase_b_and_the_rotor_side(angle_deg: float) -> None:
    solver_angle, rotor_angle = _sequence_solver_angles(angle_deg, "reverse")
    frame = _label_sequence_frame(
        run_rotating_field_motor_fixture(
            electrical_angle_deg=solver_angle,
            rotor_angle_deg=rotor_angle,
            peak_current_a=PEAK_A,
            runner=_empty_report_runner,
        ),
        angle_deg,
        "reverse",
    )
    theta = math.radians(angle_deg)

    assert frame["electrical_angle_deg"] == pytest.approx(angle_deg)
    assert frame["phase_a_current_a"] == pytest.approx(PEAK_A * math.cos(theta), abs=1e-9)
    assert frame["phase_b_current_a"] == pytest.approx(-PEAK_A * math.sin(theta), abs=1e-9)
    # The target turns clockwise (it sits at -θ) and the rotor trails it by the
    # lag, which for clockwise rotation is 15° further counterclockwise.
    assert _signed(frame["field_target_angle_deg"] + angle_deg) == pytest.approx(0.0, abs=1e-9)
    assert _signed(frame["rotor_angle_deg"] - frame["field_target_angle_deg"]) == pytest.approx(LAG_DEG)
    assert frame["torque_angle_deg"] == pytest.approx(LAG_DEG)
    assert frame["phase_sequence"] == "reverse"


@pytest.mark.parametrize("angle_deg", [0.0, 33.75, 90.0, 191.25, 270.0])
def test_two_phase_forward_sequence_is_unchanged(angle_deg: float) -> None:
    solver_angle, rotor_angle = _sequence_solver_angles(angle_deg, "forward")
    frame = _label_sequence_frame(
        run_rotating_field_motor_fixture(
            electrical_angle_deg=solver_angle,
            rotor_angle_deg=rotor_angle,
            peak_current_a=PEAK_A,
            runner=_empty_report_runner,
        ),
        angle_deg,
        "forward",
    )
    theta = math.radians(angle_deg)

    assert solver_angle == angle_deg
    assert frame["phase_b_current_a"] == pytest.approx(PEAK_A * math.sin(theta), abs=1e-9)
    assert _signed(frame["field_target_angle_deg"] - angle_deg) == pytest.approx(0.0, abs=1e-9)
    assert _signed(frame["field_target_angle_deg"] - frame["rotor_angle_deg"]) == pytest.approx(LAG_DEG)
    assert frame["torque_angle_deg"] == pytest.approx(LAG_DEG)


@pytest.mark.parametrize("angle_deg", [0.0, 33.75, 90.0, 191.25, 270.0])
def test_three_phase_reverse_sequence_swaps_b_and_c(angle_deg: float) -> None:
    forward = run_three_phase_motor_fixture(
        electrical_angle_deg=angle_deg,
        rotor_angle_deg=angle_deg - LAG_DEG,
        peak_current_a=PEAK_A,
        runner=_empty_report_runner,
    )
    solver_angle, rotor_angle = _sequence_solver_angles(angle_deg, "reverse")
    reverse = _label_sequence_frame(
        run_three_phase_motor_fixture(
            electrical_angle_deg=solver_angle,
            rotor_angle_deg=rotor_angle,
            peak_current_a=PEAK_A,
            runner=_empty_report_runner,
        ),
        angle_deg,
        "reverse",
    )

    assert reverse["electrical_angle_deg"] == pytest.approx(angle_deg)
    assert reverse["phase_a_current_a"] == pytest.approx(forward["phase_a_current_a"], abs=1e-9)
    assert reverse["phase_b_current_a"] == pytest.approx(forward["phase_c_current_a"], abs=1e-9)
    assert reverse["phase_c_current_a"] == pytest.approx(forward["phase_b_current_a"], abs=1e-9)
    # Forward: target at +θ. Reverse: target at -θ, rotor trailing clockwise.
    assert _signed(forward["field_target_angle_deg"] - angle_deg) == pytest.approx(0.0, abs=1e-6)
    assert _signed(reverse["field_target_angle_deg"] + angle_deg) == pytest.approx(0.0, abs=1e-6)
    assert _signed(reverse["rotor_angle_deg"] - reverse["field_target_angle_deg"]) == pytest.approx(LAG_DEG, abs=1e-6)
    assert reverse["torque_angle_deg"] == pytest.approx(LAG_DEG, abs=1e-6)
