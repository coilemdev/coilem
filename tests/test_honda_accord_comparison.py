"""The 2005 Honda Accord comparison (#92): the first comparison rebuilds from its data, and new runs wind the motor as built (#91)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FOLDER = REPO_ROOT / "docs/hardware-validation/honda-accord-2005"
EVIDENCE = FOLDER / "first-comparison"
AS_WOUND = FOLDER / "real-winding-comparison"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_locked_rotor_request_puts_ornl_dc_pattern_on_the_real_coils():
    from backend.geometry_drawer import current_angle_elec_deg_for_rotor_elec
    from backend.models import MotorConfig
    from backend.solver import _clockwise_excitation_config
    from tools.honda_accord_comparison import AS_WOUND_WINDING, REQUEST, locked_rotor_request

    frozen = read(REQUEST)
    for current, delta in ((25, 0), (100, 95), (225, 150)):
        body = locked_rotor_request(current, delta)
        assert {k: v for k, v in body["rotor"].items() if k != "magnet_angle_deg"} == {
            k: v for k, v in frozen["rotor"].items() if k != "magnet_angle_deg"
        }
        assert (body["stator"], body["materials"]) == (frozen["stator"], frozen["materials"])
        assert body["winding"] == AS_WOUND_WINDING
        config = _clockwise_excitation_config(MotorConfig.model_validate(body))
        angle = math.radians(current_angle_elec_deg_for_rotor_elec(config, 0.0))
        amplitude = body["solve_params"]["current_amplitude_A"]
        # ORNL's (Ia, -Ia/2, -Ia/2) straight onto the tooth coils (#91), no emulation.
        coilem = [amplitude * math.sin(angle - k * 2 * math.pi / 3) for k in range(3)]
        assert coilem == pytest.approx([current, -current / 2, -current / 2], abs=1e-9)


def test_as_wound_winding_is_the_frozen_equivalent_in_series_turns():
    from backend.geometry import validate_geometry
    from backend.models import MotorConfig
    from tools.honda_accord_comparison import REQUEST, as_wound_request

    frozen, wound = read(REQUEST)["winding"], as_wound_request()["winding"]
    # A coil on every tooth: 24 coils of 52 turns, 8 per phase, one per path.
    assert wound["turns_per_coil"] * 24 / (6 * wound["parallel_paths"]) == frozen["turns_per_coil"] * 24 / 6 == 52
    assert validate_geometry(MotorConfig.model_validate(as_wound_request())) == []


def test_app_example_is_the_as_wound_request_and_previews():
    from fastapi.testclient import TestClient

    from backend.public_main import app
    from tools.honda_accord_comparison import as_wound_request

    example = read(REPO_ROOT / "frontend/src/public/examples/honda_accord_2005.coilem")
    design = {k: v for k, v in example.items() if k not in {"openem_schema_version", "openem_version", "name", "description", "debug"}}
    assert design == as_wound_request()
    response = TestClient(app, base_url="http://127.0.0.1").post("/preview", json=design)
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["qualification"]["status"] == "experimental"


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


def test_as_wound_comparison_rebuilds_from_its_runs():
    from tools.honda_accord_comparison import AS_WOUND_WINDING, CURRENTS_A, assemble

    comparison = read(AS_WOUND / "comparison.json")
    locked = read(AS_WOUND / "locked-rotor.json")
    no_load = read(AS_WOUND / "no-load.json")
    assert no_load["winding"] == comparison["winding"] == AS_WOUND_WINDING
    assert {r["current_A"] for r in locked} == set(CURRENTS_A)
    # ORNL's pattern straight onto the real tooth coils, on clean commits.
    assert all(r["coilem_currents_per_Ia"] == [1.0, -0.5, -0.5] for r in locked)
    assert not no_load["run"]["dirty"] and not any(r["run_dirty"] for r in locked)
    assert assemble(no_load, locked, Path("/nonexistent-is-not-written"), write=False) == comparison
    assert read(AS_WOUND / "zero-scan-100A.json")["zero_offset_elec_deg"] == 300.0


def test_as_wound_charts_regenerate_byte_for_byte(tmp_path):
    from tools import plot_honda_accord_comparison

    (tmp_path / "comparison.json").write_bytes((AS_WOUND / "comparison.json").read_bytes())
    plot_honda_accord_comparison.main.__globals__["sys"].argv = ["plot", str(tmp_path)]
    plot_honda_accord_comparison.main()
    for name in ("back-emf.svg", "locked-rotor-torque.svg"):
        assert (tmp_path / name).read_bytes() == (AS_WOUND / name).read_bytes()
