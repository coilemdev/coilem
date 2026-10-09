"""The CLI transport must preserve exact six-step commutation boundaries."""
import json
import math
from pathlib import Path

import pytest

from backend.excitation import resolve_phase_current_sample
from backend.magneto2d_adapter import build_magneto2d_command, build_magneto2d_mesh_command
from backend.models import MotorConfig


@pytest.mark.parametrize("builder", [build_magneto2d_command, build_magneto2d_mesh_command])
def test_cli_angle_preserves_high_pole_commutation_sequence(builder):
    payload = json.loads(Path("tests/fixtures/spm_8p12s_concentrated.json").read_text())
    payload["materials"].update(stator_steel="M350-50A", rotor_steel="M350-50A")
    payload["rotor"]["pole_count"] = 14
    payload["solve_params"].update(
        excitation_mode="ideal_six_step_120", current_amplitude_convention="plateau", current_amplitude_A=20.0,
    )
    config = MotorConfig.model_validate(payload)
    for boundary in range(0, 361, 60):
        for offset in (-1e-9, 0.0, 1e-9):
            electrical_angle = boundary + offset
            mechanical_angle = -electrical_angle / 7
            command = builder(Path("input.json"), Path("output.json"), rotor_angle_deg=mechanical_angle)
            parsed = float(command[command.index("--rotor-angle-deg") + 1])
            assert parsed == mechanical_angle
            # Include the native degree/radian conversion before selecting the sector.
            restored = -math.degrees(math.radians(parsed)) * 7
            expected = resolve_phase_current_sample(config, electrical_angle, clockwise_positive=True)
            actual = resolve_phase_current_sample(config, restored, clockwise_positive=True)
            assert actual.phase_current_a == expected.phase_current_a, (boundary, offset)
