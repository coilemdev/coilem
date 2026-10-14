"""The committed ORNL Prius comparison is reproducible from its data (#82)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FOLDER = REPO_ROOT / "docs/hardware-validation/ornl-prius-2004"
EVIDENCE = FOLDER / "first-comparison"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_locked_rotor_request_reproduces_ornl_dc_currents():
    from backend.geometry_drawer import current_angle_elec_deg_for_rotor_elec
    from backend.models import MotorConfig
    from tools.ornl_prius_comparison import REQUEST, locked_rotor_request, rotor_offset_mech_deg

    frozen = read(REQUEST)
    for delta in (0, 88, 176):
        body = locked_rotor_request(150, delta)
        # Only the excitation and the rotor angle differ from the frozen request.
        def unrotated(rotor):
            return {k: v for k, v in rotor.items() if k != "magnet_angle_deg"}

        assert unrotated(body["rotor"]) == unrotated(frozen["rotor"])
        assert (body["stator"], body["winding"], body["materials"]) == (frozen["stator"], frozen["winding"], frozen["materials"])
        assert -45.0 <= body["rotor"]["magnet_angle_deg"] < 45.0
        angle = math.radians(current_angle_elec_deg_for_rotor_elec(MotorConfig.model_validate(body), 0.0))
        currents = [math.sin(angle - k * 2 * math.pi / 3) for k in range(3)]
        assert currents == pytest.approx([1.0, -0.5, -0.5])
    assert rotor_offset_mech_deg(0) == pytest.approx(26.25)


def test_committed_comparison_matches_its_data():
    from tools.ornl_prius_comparison import split_torque

    comparison = read(EVIDENCE / "comparison.json")["locked_rotor"]
    solves = {(r["current_A"], r["delta_deg"]): r["torque_Nm"] for r in read(EVIDENCE / "locked-rotor.json")}
    targets = read(FOLDER / "target-locked-rotor.json")["rows"]
    assert comparison["currents_A"] == [50, 75, 100, 125, 150, 200, 250]
    assert len(solves) == 7 * 23
    for row, target in zip(comparison["rows"], targets, strict=True):
        assert row["delta_deg"] == target["electrical_position_deg_S3"]
        for current in comparison["currents_A"]:
            assert row["ornl_Nm"][str(current)] == target[f"torque_Nm_{current}A"]
            assert row["coilem_Nm"][str(current)] == solves[current, row["delta_deg"]]
    assert comparison["magnet_reluctance_split"] == [split_torque(comparison["rows"], c) for c in comparison["currents_A"]]


def test_charts_regenerate_byte_for_byte(tmp_path):
    from tools import plot_ornl_prius_comparison

    (tmp_path / "comparison.json").write_bytes((EVIDENCE / "comparison.json").read_bytes())
    plot_ornl_prius_comparison.main.__globals__["sys"].argv = ["plot", str(tmp_path)]
    plot_ornl_prius_comparison.main()
    for name in ("back-emf.svg", "locked-rotor-torque.svg"):
        assert (tmp_path / name).read_bytes() == (EVIDENCE / name).read_bytes()
