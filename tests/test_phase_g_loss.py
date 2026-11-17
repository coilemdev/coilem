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


def test_femm_answer_reader_has_correct_units_curl_and_material_selection(tmp_path):
    from tools.phase_g_loss.femm_answers import answer_fields

    path = tmp_path / "linear.ans"
    # A_z = 0.003*x_mm + 0.002*y_mm: B_x=2 T, B_y=-3 T.
    path.write_text(
        "\n".join(
            [
                "[Frequency] = 0",
                "[LengthUnits] = millimeters",
                '<BlockName> = "coilEM_M350_50A_test"',
                "[NumBlockLabels] = 2",
                "0.2 0.2 1 1 0 0 0 1 0",
                "2.2 0.2 1 1 0 0 10 1 0",
                "[Solution]",
                "6",
                "0 0 0 -1",
                "1 0 0.003 -1",
                "0 1 0.002 -1",
                "2 0 0.006 -1",
                "3 0 0.009 -1",
                "2 1 0.008 -1",
                "2",
                "0 1 2 0 -1 -1 -1 0",
                "3 4 5 1 -1 -1 -1 0",
            ]
        ),
        encoding="ascii",
    )
    result = answer_fields(path)
    assert result["stator"][0] == pytest.approx([2, -3])
    assert result["rotor"][0] == pytest.approx([2, -3])
    assert result["stator_corners"][0, 0] == pytest.approx([0, 0])
    assert result["rotor_corners"][0, 0] == pytest.approx([2, 0])
    path.write_text(path.read_text().replace("[Frequency] = 0", "[Frequency] = 50"))
    with pytest.raises(ValueError, match="magnetostatic"):
        answer_fields(path)


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


def test_analysis_replay_preserves_original_receipt_and_rejects_changed_physics():
    from tools.phase_g_loss.report import consistent_analysis

    original = {"numerical_history_pass": True, "result": {"total_W": 12.0}, "case_id": "example"}
    replay = original | {"analysis_implementation_sha256": "reader-version"}
    assert consistent_analysis(original, replay)
    assert not consistent_analysis(original, replay | {"result": {"total_W": 12.01}})
    assert not consistent_analysis(original, replay | {"numerical_history_pass": False})
    assert not consistent_analysis(original, replay | {"numerical_history_pass": 1})


def test_resume_only_accepts_identical_hashed_native_producers(tmp_path):
    from tools.phase_g_loss.__main__ import verify_native_snapshots

    directory = tmp_path / "native" / "example"
    directory.mkdir(parents=True)
    name = "tools/phase_g_loss/native.py"
    write(directory / "protocol.json", {"identity": {"source_sha256": {name: sha(ROOT / name)}}})
    verify_native_snapshots(tmp_path)
    write(directory / "protocol.json", {"identity": {"source_sha256": {name: "0" * 64}}})
    with pytest.raises(ValueError, match="source changed"):
        verify_native_snapshots(tmp_path)


def test_pilot_exception_is_only_distributed_coarse_grid_with_stable_final_step():
    from tools.phase_g_loss.report import admissible_history

    analysis = {
        "case_id": "distributed-spm-no-load",
        "numerical_history_pass": False,
        "regions": {"rotor": {"closure": {"pass": True}, "speeds": {"3000": {"angular_steps": [{"total_W": False}, {"total_W": True}]}}}},
    }
    assert not admissible_history(analysis)
    assert admissible_history(analysis, allow_angular_failure=True)
    assert not admissible_history(analysis | {"case_id": "outer-spm-loaded"}, allow_angular_failure=True)
    analysis["regions"]["rotor"]["speeds"]["3000"]["angular_steps"][-1]["total_W"] = False
    assert not admissible_history(analysis, allow_angular_failure=True)
    analysis["regions"]["rotor"]["speeds"]["3000"]["angular_steps"][-1]["total_W"] = True
    analysis["regions"]["rotor"]["closure"]["pass"] = False
    assert not admissible_history(analysis, allow_angular_failure=True)


def test_agreement_does_not_turn_failed_convergence_into_a_passing_comparison():
    from tools.phase_g_loss.report import compare

    value = {"hysteresis_W": 1.0, "lamination_eddy_W": 2.0, "total_W": 3.0}
    native = {
        "case_id": "distributed-spm-no-load",
        "protocol_sha256": "native-history",
        "numerical_history_pass": False,
        "rotor_status": "experimental",
        "copper": {"W": 0.0, "phase_resistance_ohm": 1.0},
        "regions": {"rotor": {"speeds": {str(s): {"samples": {"384": value}} for s in (1500, 3000)}}},
        "modelled_totals": {str(s): {"known_loss_subtotal_W": 3.0} for s in (1500, 3000)},
    }
    reference = native | {"numerical_history_pass": True, "bound_native_protocol_sha256": "native-history", "protocol_sha256": "femm-history"}
    result = compare(native, reference)
    assert result["component_agreement_pass"]
    assert not result["component_comparison_pass"]
    assert result["status"] == "COMPONENT_AGREEMENT_PASS_ANGULAR_CHECK_FAILED"
    assert not result["qualification_complete"]
