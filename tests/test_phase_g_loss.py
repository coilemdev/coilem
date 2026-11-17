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


@pytest.mark.parametrize("continue_independent", [False, True])
def test_campaign_keeps_closure_failure_and_only_compares_independent_valid_cases(tmp_path, monkeypatch, continue_independent):
    import argparse
    import sys
    from pathlib import Path

    import tools.phase_g_loss.__main__ as campaign
    import tools.phase_g_loss.report as reporter
    from tools.phase_g_loss.contract import read

    cases = [case_by_id("inner-spm-loaded"), case_by_id("outer-spm-no-load")]
    output = tmp_path / "campaign"
    for case in cases:
        for index in range(POSITIONS + 1):
            directory = output / "native" / case["id"] / f"position-{index:04d}"
            directory.mkdir(parents=True)
            write(directory / "position.json", {})
    binary = tmp_path / "solver"
    binary.write_bytes(b"test identity")
    monkeypatch.setattr(campaign, "suite", lambda: {"cases": cases})
    monkeypatch.setattr(campaign.subprocess, "check_output", lambda command, **kw: "field-commit\n" if "rev-parse" in command else "")
    monkeypatch.setattr(campaign, "live_femm_count", lambda: 0)
    monkeypatch.setattr(reporter, "summary", lambda *a: None)
    monkeypatch.setattr(reporter, "compare", lambda *a: {"component_comparison_pass": True, "component_agreement_pass": True})
    events = []

    def commands(arguments, logs, cancel=None):
        for command, log in zip(arguments, logs, strict=True):
            if "tools.phase_g_loss.report" in command:
                directory = Path(command[command.index("--history") + 1])
                valid = directory.name == "inner-spm-loaded"
                result = {
                    "case_id": directory.name,
                    "numerical_history_pass": valid,
                    "regions": {
                        "stator": {
                            "closure": {"pass": valid},
                            "speeds": {"3000": {"angular_steps": [{"total_W": True}, {"total_W": True}]}},
                        }
                    },
                }
                write(directory / "analysis.json", result)
                events.append(("analyse", directory.parent.name, directory.name))
                if not valid:
                    log.write_text("Phase G history gate failed; inspect analysis.json\n")
                    raise RuntimeError("history gate failed")
            elif "tools.phase_g_loss.femm" in command:
                events.append(("femm", command[command.index("--case") + 1]))
            else:
                raise AssertionError("Unexpected collector command")

    monkeypatch.setattr(campaign, "commands", commands)
    args = argparse.Namespace(
        mode="run", out=output, binary=binary, case=None, native_workers=4, femm_workers=2,
        femm_python=Path(sys.executable), wait_for_femm=False, allow_angular_failure=True,
        continue_independent_cases=continue_independent,
        parallel_femm_cases=False,
        femm_workers_per_case=1,
    )
    if not continue_independent:
        with pytest.raises(RuntimeError, match="history gate"):
            campaign.run(args)
        assert read(output / "run-state.json")["status"] == "STOPPED_WITH_CHECKPOINTS"
        assert not any(event[0] == "femm" for event in events)
        return
    campaign.run(args)
    state = read(output / "run-state.json")
    assert state["status"] == "PILOT_COLLECTION_COMPLETE_WITH_FAILED_CHECKS"
    assert state["native_completed"] == [case["id"] for case in cases]
    assert state["native_history_failures"] == ["outer-spm-no-load"]
    assert state["native_angular_failures"] == []  # A closure failure is not an angular failure.
    assert state["femm_completed"] == ["inner-spm-loaded"]
    assert set(state["femm_skipped"]) == {"outer-spm-no-load"}
    assert not state["qualification_complete"]
    assert read(output / "native/outer-spm-no-load/analysis.json")["numerical_history_pass"] is False
    assert all(event[1] == "inner-spm-loaded" for event in events if event[0] == "femm")
    assert events.index(("analyse", "native", "outer-spm-no-load")) < next(i for i, event in enumerate(events) if event[0] == "femm")


@pytest.mark.parametrize("workers_per_case,total_workers", [(1, 2), (2, 4)])
def test_two_case_schedule_overlaps_fixtures_with_disjoint_shards(tmp_path, monkeypatch, workers_per_case, total_workers):
    import argparse
    import sys
    from pathlib import Path
    from threading import Barrier, Lock

    import tools.phase_g_loss.__main__ as campaign
    import tools.phase_g_loss.report as reporter
    from tools.phase_g_loss.contract import read

    cases = [case_by_id("flat-ipm-no-load"), case_by_id("distributed-spm-no-load")]
    output = tmp_path / "campaign"
    for case in cases:
        write(output / "native" / case["id"] / "analysis.json", {
            "case_id": case["id"], "numerical_history_pass": True,
            "regions": {"stator": {"closure": {"pass": True}, "speeds": {"3000": {"angular_steps": [{"total_W": True}]}}}},
        })
    initial_registration = {
        "schema": "coilem.phase_g_campaign/v1", "candidate": "field-commit",
        "suite_sha256": sha(campaign.SUITE), "cases": cases, "binary_sha256": None,
        "native_workers": 4, "femm_workers": 2,
    }
    write(output / "registration.json", initial_registration)
    initial_hash = sha(output / "registration.json")
    monkeypatch.setattr(campaign, "suite", lambda: {"cases": cases})
    monkeypatch.setattr(campaign.subprocess, "check_output", lambda command, **kw: "field-commit\n" if "rev-parse" in command else "")
    monkeypatch.setattr(campaign, "live_femm_count", lambda: 0)
    monkeypatch.setattr(reporter, "summary", lambda *a: None)
    monkeypatch.setattr(reporter, "compare", lambda *a: {"component_comparison_pass": True, "component_agreement_pass": True})
    barrier, lock, active, seen, shards = Barrier(2), Lock(), set(), [], []

    def commands(arguments, logs, cancel=None):
        assert cancel is not None
        command = arguments[0]
        if "tools.phase_g_loss.femm" in command:
            case = command[command.index("--case") + 1]
            if "--limit" in command:
                assert len(arguments) == 1  # A single bootstrap establishes the shared geometry.
                with lock:
                    assert case not in active
                    active.add(case)
                barrier.wait(timeout=5)
                with lock:
                    seen.append(set(active))
            else:
                assert len(arguments) == workers_per_case
                shards.extend(command[command.index("--shard") + 1] for command in arguments)
        else:
            directory = Path(command[command.index("--history") + 1])
            write(directory / "analysis.json", read(output / "native" / directory.name / "analysis.json"))

    monkeypatch.setattr(campaign, "commands", commands)
    campaign.run(argparse.Namespace(
        mode="femm", out=output, binary=None, case=None, native_workers=4, femm_workers=total_workers,
        femm_python=Path(sys.executable), wait_for_femm=False, allow_angular_failure=True,
        continue_independent_cases=True, parallel_femm_cases=True,
        femm_workers_per_case=workers_per_case,
    ))
    assert seen == [{case["id"] for case in cases}] * 2
    assert sorted(shards) == sorted([f"{index}/{workers_per_case}" for index in range(workers_per_case)] * 2)
    state = read(output / "run-state.json")
    assert set(state["femm_completed"]) == {case["id"] for case in cases}
    assert state["active_femm_cases"] == []
    assert state["status"] == "NUMERICAL_COLLECTION_COMPLETE_EXPERIMENTAL"
    assert state["femm_worker_limit"] == total_workers
    assert state["femm_workers_per_case"] == workers_per_case
    assert state["femm_case_concurrency"] == 2
    assert sha(output / "registration.json") == initial_hash
    plan = read(output / state["worker_plan_receipt"])
    assert plan["femm_worker_limit"] == total_workers
    assert plan["initial_registered_femm_workers"] == 2
    assert plan["registration_sha256"] == initial_hash


def test_cancelled_case_does_not_launch_more_field_workers(tmp_path, monkeypatch):
    from threading import Event

    import tools.phase_g_loss.__main__ as campaign

    cancel = Event()
    cancel.set()
    monkeypatch.setattr(campaign.subprocess, "Popen", lambda *a, **kw: pytest.fail("Cancelled case launched a field worker"))
    with pytest.raises(RuntimeError, match="peer worker failed"):
        campaign.commands([["never-start"]], [tmp_path / "worker.log"], cancel)


@pytest.mark.parametrize("total,per_case,parallel", [(1, 2, True), (2, 2, False), (5, 1, True)])
def test_worker_allocation_cannot_exceed_the_global_budget(total, per_case, parallel):
    from argparse import Namespace

    from tools.phase_g_loss.__main__ import femm_worker_plan

    with pytest.raises(ValueError):
        femm_worker_plan(Namespace(femm_workers=total, femm_workers_per_case=per_case, parallel_femm_cases=parallel))


def test_sharding_requires_verified_zero_pose_and_shared_geometry(tmp_path):
    from tools.phase_g_loss.__main__ import reference_prepared

    assert not reference_prepared(tmp_path)
    write(tmp_path / "preparation.json", {"mesh": "fixed"})
    geometry = tmp_path / "material-geometry.npz"
    np.savez(geometry, stator_corners=np.ones((1, 3, 2)))
    protocol = tmp_path / "protocol.json"
    write(protocol, {"preparation_sha256": sha(tmp_path / "preparation.json")})
    assert not reference_prepared(tmp_path)
    zero = tmp_path / "position-0000"
    zero.mkdir()
    np.savez(zero / "fields.npz", stator=np.ones((1, 2)))
    write(zero / "position.json", {
        "index": 0, "angle_deg": 0, "protocol_sha256": sha(protocol),
        "geometry_sha256": sha(geometry), "sha256": {"fields.npz": sha(zero / "fields.npz")},
    })
    assert reference_prepared(tmp_path)
    np.savez(geometry, stator_corners=np.zeros((1, 3, 2)))
    with pytest.raises(ValueError, match="different inputs or integration geometry"):
        reference_prepared(tmp_path)
