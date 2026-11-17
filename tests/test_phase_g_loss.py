"""Phase G independent input, loss-law and evidence boundary controls."""

import math

import numpy as np
import pytest

from tools.phase_g_loss.contract import (
    POSITIONS,
    ROOT,
    case_by_id,
    checkpoint,
    config_for,
    phase_ampere_turns,
    protocol,
    reference_resistance,
    sha,
    suite,
    write,
)
from tools.phase_g_loss.report import components_pass, independent_loss, production_loss


def test_four_fixtures_eight_conditions_do_not_change_af():
    spec = suite()
    assert len(spec["fixtures"]) == 4 and len(spec["cases"]) == 8
    assert {c["current_peak_A"] for c in spec["cases"] if c["id"].endswith("no-load")} == {0}
    assert all(c["rotor_supported"] is False for c in spec["cases"] if c["id"].startswith("outer"))
    assert sha(ROOT / "benchmarks/af-v1.10/benchmark_spec.json") == "14f80962ecb09ef4c5df569d0e5c89158dc7b2516cc9a8e47df34a57f501bcc4"
    for case in spec["cases"]:
        raw = config_for(case)
        assert raw["solve_params"]["symmetry"] == "full"
        assert raw["solve_params"]["winding_temperature_C"] == 20
        assert raw["winding"]["wire"]["strands_in_hand"] == 2


@pytest.mark.parametrize("case", [c["id"] for c in suite()["cases"]])
@pytest.mark.parametrize("angle", [0, -0.9375, -22.5, -180, -360])
def test_independent_sines_match_all_registered_phase_axes_paths_and_loads(case, angle):
    from backend.geometry_drawer import compute_3phase_slot_ampere_turns_for_rotor_elec
    from backend.models import MotorConfig
    from backend.solver import _clockwise_excitation_config

    raw = config_for(case_by_id(case))
    cfg = _clockwise_excitation_config(MotorConfig.model_validate(raw))
    expected = phase_ampere_turns(raw, angle)
    assert compute_3phase_slot_ampere_turns_for_rotor_elec(cfg, angle * cfg.rotor.pole_count / 2) == pytest.approx(expected, abs=1e-10)
    assert sum(expected.values()) == pytest.approx(0, abs=1e-10)


def test_unregistered_excitation_cannot_silently_borrow_another_phase_axis():
    raw = config_for(case_by_id("inner-spm-loaded"))
    raw["rotor"]["pole_count"] = 10
    with pytest.raises(ValueError, match="phase-axis"):
        phase_ampere_turns(raw, 0)


@pytest.mark.parametrize("count", [96, 192, 384])
def test_independent_and_production_kernels_match_analytic_vector_multiharmonics(count):
    from dataclasses import asdict

    from backend.iron_loss import M350_50A_LOSS

    coefficients = asdict(M350_50A_LOSS)
    theta = 2 * np.pi * np.arange(count) / count
    values = np.zeros((count, 2, 2))
    values[:, 0, 0] = 0.4 + 0.6 * np.sin(4 * theta)
    values[:, 0, 1] = 0.8 * np.cos(4 * theta)
    values[:, 1, 0] = 0.2 * np.sin(3 * theta) + 0.1 * np.cos(7 * theta)
    areas = np.array([1e-5, 2e-5])
    mass = areas * 0.05 * coefficients["density_kg_m3"]
    expected_h = mass[0] * coefficients["kh"] * 200
    expected_e = mass[0] * coefficients["kc"] * 200**2
    for order, amplitude in ((3, 0.2), (7, 0.1)):
        expected_h += mass[1] * coefficients["kh"] * (50 * order) * amplitude ** coefficients["alpha"]
        expected_e += mass[1] * coefficients["kc"] * (50 * order) ** 2 * amplitude**2
    native = production_loss(values, areas, 3000, 0.05, coefficients)
    reference = independent_loss(values, -360 * np.arange(count) / count, areas, 3000, 0.05, coefficients)
    for result in (native, reference):
        assert result["hysteresis_W"] == pytest.approx(expected_h, rel=1e-11)
        assert result["lamination_eddy_W"] == pytest.approx(expected_e, rel=1e-11)
    low = independent_loss(values, -360 * np.arange(count) / count, areas, 1500, 0.05, coefficients)
    assert reference["hysteresis_W"] == pytest.approx(2 * low["hysteresis_W"])
    assert reference["lamination_eddy_W"] == pytest.approx(4 * low["lamination_eddy_W"])


def test_independent_copper_geometry_formula_paths_temperature_and_layers():
    raw = config_for(case_by_id("inner-spm-loaded"))
    radius = 0.03
    blocks = [
        {"slot": slot, "area_mm2": 10, "centroid_mm": [radius * 1000 * math.cos(slot * math.pi / 6), radius * 1000 * math.sin(slot * math.pi / 6)]}
        for slot in range(12)
    ]
    result = reference_resistance(raw, blocks)
    mlt = 2 * raw["stator"]["stack_length_mm"] * 1e-3 + math.pi * (math.pi / 6) * radius
    area = 2 * math.pi / 4 * (0.8e-3) ** 2
    expected = (1e-6 / 58) * 24 * mlt / area
    assert result["phase_resistance_ohm"] == pytest.approx(expected)
    split = [dict(block, area_mm2=5) for block in blocks for _ in range(2)]
    assert reference_resistance(raw, split)["phase_resistance_ohm"] == pytest.approx(expected)
    raw["winding"]["parallel_paths"] = 2
    raw["solve_params"]["winding_temperature_C"] = 100
    assert reference_resistance(raw, blocks)["phase_resistance_ohm"] == pytest.approx(expected / 4 * 1.3144)
    with pytest.raises(ValueError, match="missing slot"):
        reference_resistance(raw, blocks[:-1])


def test_resume_rejects_modified_raw_fields_protocol_and_pose(tmp_path):
    directory = tmp_path / "position-0000"
    directory.mkdir()
    raw = directory / "fields.npz"
    np.savez(raw, stator=np.ones((1, 2)))
    write(directory / "position.json", {"index": 0, "angle_deg": 0, "sha256": {"fields.npz": sha(raw)}})
    assert checkpoint(tmp_path, 0)["index"] == 0
    np.savez(raw, stator=np.zeros((1, 2)))
    with pytest.raises(ValueError, match="checkpoint changed"):
        checkpoint(tmp_path, 0)
    expected = {"schema": "example", "positions": POSITIONS}
    protocol(tmp_path, expected)
    with pytest.raises(ValueError, match="sources, inputs"):
        protocol(tmp_path, expected | {"positions": 192})


def test_component_gate_cannot_hide_cancelling_errors_in_total():
    a = {"hysteresis_W": 2.0, "lamination_eddy_W": 8.0, "total_W": 10.0}
    b = {"hysteresis_W": 4.0, "lamination_eddy_W": 6.0, "total_W": 10.0}
    result = components_pass(a, b, 0.10)
    assert result == {"hysteresis_W": False, "lamination_eddy_W": False, "total_W": True}


def test_femm_worker_module_does_not_claim_the_production_backend_namespace():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            'import sys; import tools.phase_g_loss.femm; assert not any(x == "backend" or x.startswith("backend.") for x in sys.modules)',
        ],
        cwd=ROOT,
        check=True,
    )
