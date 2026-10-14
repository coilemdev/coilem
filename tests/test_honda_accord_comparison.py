"""The 2005 Honda Accord comparison (#92) is reproducible from its data, with #91 emulated correctly."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FOLDER = REPO_ROOT / "docs/hardware-validation/honda-accord-2005"
EVIDENCE = FOLDER / "first-comparison"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_locked_rotor_request_puts_ornl_dc_pattern_on_the_tooth_coils():
    from backend.geometry_drawer import current_angle_elec_deg_for_rotor_elec
    from backend.models import MotorConfig
    from backend.solver import _clockwise_excitation_config
    from tools.honda_accord_comparison import REQUEST, locked_rotor_request

    frozen = read(REQUEST)
    for current, delta in ((25, 0), (100, 95), (225, 150)):
        body = locked_rotor_request(current, delta)
        assert {k: v for k, v in body["rotor"].items() if k != "magnet_angle_deg"} == {
            k: v for k, v in frozen["rotor"].items() if k != "magnet_angle_deg"
        }
        assert (body["stator"], body["winding"], body["materials"]) == (frozen["stator"], frozen["winding"], frozen["materials"])
        config = _clockwise_excitation_config(MotorConfig.model_validate(body))
        angle = math.radians(current_angle_elec_deg_for_rotor_elec(config, 0.0))
        amplitude = body["solve_params"]["current_amplitude_A"]
        coilem = [amplitude * math.sin(angle - k * 2 * math.pi / 3) for k in range(3)]
        # coilEM's slot-map currents (0.75, -0.75, 0) Ia ...
        assert coilem == pytest.approx([0.75 * current, -0.75 * current, 0.0], abs=1e-9)
        # ... are ORNL's (Ia, -Ia/2, -Ia/2) on the real tooth coils: i'A = (iA - iC)/2, i'B = (iB - iA)/2.
        ia, ib, ic = current, -current / 2, -current / 2
        assert coilem[:2] == pytest.approx([(ia - ic) / 2, (ib - ia) / 2])


def test_tooth_coil_repairing_scales_by_root3_over_2_and_inverts_5th_and_7th():
    from tools.honda_accord_comparison import tooth_coil

    theta = [math.radians(2 * i) for i in range(180)]

    def phase(k):
        return [math.cos(t - k * 2 * math.pi / 3) + 0.1 * math.cos(5 * (t - k * 2 * math.pi / 3)) for t in theta]

    real = tooth_coil(phase(0), phase(1))

    def harmonic(v, n):
        return complex(sum(x * math.cos(n * t) for x, t in zip(v, theta)), -sum(x * math.sin(n * t) for x, t in zip(v, theta))) * 2 / len(v)

    h1, h5 = harmonic(real, 1), harmonic(real, 5)
    assert abs(h1) == pytest.approx(math.sqrt(3) / 2)
    assert abs(h5) == pytest.approx(0.1 * math.sqrt(3) / 2)
    # Relative to the fundamental, the 5th turns over: in step on coilEM's slot map, inverted on the tooth coil.
    relative = math.degrees(math.atan2((h5 / h1**5).imag, (h5 / h1**5).real))
    assert abs(abs(relative) - 180) < 1e-6


def test_committed_comparison_matches_its_data():
    from tools.honda_accord_comparison import CURRENTS_A, assemble

    comparison = read(EVIDENCE / "comparison.json")
    locked = read(EVIDENCE / "locked-rotor.json")
    assert {r["current_A"] for r in locked} == set(CURRENTS_A)
    assert all(r["coilem_currents_per_Ia"] in (None, [0.75, -0.75, 0.0], [0.75, -0.75, -0.0]) for r in locked)
    rebuilt = assemble(read(EVIDENCE / "no-load.json"), locked, Path("/nonexistent-is-not-written"), write=False)
    assert rebuilt == comparison
    targets = {r["current_A"]: r["peak_torque_Nm"] for r in read(FOLDER / "target-locked-rotor.json")["rows"]}
    assert {p["current_A"]: p["ornl_peak_Nm"] for p in comparison["locked_rotor"]["peak_by_current"]} == targets


def test_charts_regenerate_byte_for_byte(tmp_path):
    from tools import plot_honda_accord_comparison

    (tmp_path / "comparison.json").write_bytes((EVIDENCE / "comparison.json").read_bytes())
    plot_honda_accord_comparison.main.__globals__["sys"].argv = ["plot", str(tmp_path)]
    plot_honda_accord_comparison.main()
    for name in ("back-emf.svg", "locked-rotor-torque.svg"):
        assert (tmp_path / name).read_bytes() == (EVIDENCE / name).read_bytes()
