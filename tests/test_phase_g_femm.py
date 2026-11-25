"""Phase G FEMM rotor references: the committed requests, the excitation, the saved-model audit, the report and the grading.

None of these start FEMM. The collector itself is checked by running it (tools/phase_g_femm/README.md).
"""

import json
import math

import numpy as np
import pytest

from backend.benchmark_suite import loss_phase_g as g
from tests._private_evidence import requires_private_evidence
from tools.femm_reference.rotor_airgap import BOUNDARY
from tools.phase_g_femm import __main__ as orchestrator
from tools.phase_g_femm import collect, contract, report

# The FEMM records and the stored record are kept in the private repository (tools/release/private_evidence.py).
needs_rotor_references = requires_private_evidence("benchmarks/g-v2.0/references/femm-rotor")
needs_stored_record = requires_private_evidence("benchmarks/g-v2.0/results/coilem.json", "benchmarks/g-v2.0/references")


def test_every_registered_history_has_a_committed_request_for_its_own_fixture():
    registered = contract.spec()
    for row in registered["rotor_histories"]:
        request = contract.load_request(row["id"])
        config = request["requested_config"]
        assert request["schema"] == "coilem.phase_g_femm_request/v1" and request["history"] == row
        assert config == contract.read(contract.PROTOCOL / row["fixture"])
        assert request["positions"] == contract.POSITIONS == registered["rotor"]["positions"]
        assert request["collection_speed_rpm"] == registered["rotor"]["collection_speed_rpm"]
        assert request["evaluation_speeds_rpm"] == list(contract.SPEEDS)
        density, airgap, step = contract.FEMM_MESH[row["motor"]]
        assert request["femm_mesh"] == {"density": density, "airgap_target_mm": airgap, "airgap_arc_step_deg": step}
        # One native coil side per slot and layer, each a phase, a direction and a share of the coil's turns.
        sides = request["native_windings"]
        assert len(sides) == config["stator"]["slot_count"] * config["winding"]["layers"]
        assert {side["phase"] for side in sides} == set("ABC") and {side["direction"] for side in sides} == {"in", "out"}
        assert request["coefficients"]["kh"] > 0 and request["matched_magnet"] == contract.MATCHED_MAGNET


@needs_rotor_references
def test_every_committed_femm_record_answers_its_committed_request_with_the_current_calculator():
    records = g.rotor_references()
    assert set(records) == {row["id"] for row in contract.spec()["rotor_histories"]}
    for history_id, record in records.items():
        assert record["request_sha256"] == contract.sha(contract.request_path(history_id))
        assert record["loss_calculator"]["sha256"] == contract.sha(g.ROOT / record["loss_calculator"]["module"])
        assert record["positions"] == contract.POSITIONS and record["closure"]["max_T"] < 1e-6
        assert set(record["speeds"]) == {str(speed) for speed in contract.SPEEDS}


def test_a_request_written_for_another_specification_is_refused(tmp_path, monkeypatch):
    request = contract.load_request("inner_spm_loaded")
    monkeypatch.setattr(contract, "REQUESTS", tmp_path)
    contract.write(tmp_path / "inner_spm_loaded.json", request | {"spec_sha256": "0" * 64})
    with pytest.raises(ValueError, match="another Phase G specification"):
        contract.load_request("inner_spm_loaded")


@pytest.mark.parametrize("history_id", ["inner_spm_loaded", "distributed_spm_loaded", "outer_spm_loaded"])
def test_the_excitation_is_a_balanced_sine_of_the_registered_amplitude(history_id):
    config = contract.load_request(history_id)["requested_config"]
    amplitude = config["solve_params"]["current_amplitude_A"] * config["winding"]["turns_per_coil"] / config["winding"]["parallel_paths"]
    peaks = np.zeros(3)
    for index in range(contract.POSITIONS):
        phases = contract.phase_ampere_turns(config, contract.pose_angle(index))
        assert sum(phases.values()) == pytest.approx(0, abs=1e-9 * amplitude)
        peaks = np.maximum(peaks, np.abs([phases[p] for p in "ABC"]))
    assert peaks == pytest.approx(amplitude, rel=2e-3)
    with pytest.raises(ValueError, match="gamma zero"):
        contract.phase_ampere_turns(config | {"solve_params": config["solve_params"] | {"current_angle_deg": 30}}, 0)
    with pytest.raises(ValueError, match="phase-axis contract"):
        contract.phase_ampere_turns(config | {"rotor": config["rotor"] | {"pole_count": 4}}, 0)


def test_poses_turn_the_rotor_clockwise_and_the_last_closes_the_turn():
    assert contract.pose_angle(0) == 0 and contract.pose_angle(96) == -90 and contract.pose_angle(contract.POSITIONS) == -360


def outer_model_text(inner_angle, amps, magnet_hc=1.315 / (1.05 * 4e-7 * math.pi), prev=""):
    circuits = "".join(f'<BeginCircuit>\n<CircuitName> = "{p}"\n<TotalAmps_re> = {a!r}\n<TotalAmps_im> = 0\n<CircuitType> = 1\n<EndCircuit>\n'
                       for p, a in zip("ABC", amps, strict=True))
    return (f'[PrevSoln] = "{prev}"\n<BeginBdry>\n<BdryName> = "{BOUNDARY}"\n'
            f"<BdryType> = 6\n<innerangle> = {inner_angle!r}\n<outerangle> = 0\n<EndBdry>\n"
            f'<BeginBlock>\n<BlockName> = "PermanentMagnet"\n<Mu_x> = 1.05\n<Mu_y> = 1.05\n<H_c> = {magnet_hc!r}\n<EndBlock>\n' + circuits)


def test_the_outer_rotor_pose_audit_needs_the_stator_turned_the_other_way_and_the_registered_currents():
    config = contract.load_request("outer_spm_loaded")["requested_config"]
    turns = config["winding"]["turns_per_coil"]
    angle = contract.pose_angle(7)
    phases = contract.phase_ampere_turns(config, angle)
    amps = [phases[p] / turns for p in "ABC"]
    assert collect.outer_model_audit(outer_model_text(-angle, amps), angle, phases, turns, contract.MATCHED_MAGNET) < 1e-12
    for wrong, message in ((outer_model_text(angle, amps), "boundary pose"),
                           (outer_model_text(-angle, [amps[0] * 1.01, *amps[1:]]), "phase currents"),
                           (outer_model_text(-angle, amps, magnet_hc=9e5), "magnet"),
                           (outer_model_text(-angle, amps, prev="seed.ans"), "previous-solution")):
        with pytest.raises(ValueError, match=message):
            collect.outer_model_audit(wrong, angle, phases, turns, contract.MATCHED_MAGNET)


def test_femm_coil_blocks_must_match_the_native_coil_sides():
    native = contract.load_request("inner_spm_loaded")["native_windings"]
    coils = [{key: side[key] for key in ("phase", "direction", "turn_fraction")}
             | {"centroid_mm": [side["centroid_mm"][0] + 1e-4, side["centroid_mm"][1]]} for side in native]
    assert max(row["centroid_difference_mm"] for row in collect.audit_windings(coils, native)) < 2e-4
    with pytest.raises(ValueError, match="different places"):
        collect.audit_windings([coils[0] | {"centroid_mm": [0, 0]}, *coils[1:]], native)
    with pytest.raises(ValueError, match="phase, direction or turn share"):
        collect.audit_windings([coils[0] | {"direction": "out" if coils[0]["direction"] == "in" else "in"}, *coils[1:]], native)
    with pytest.raises(ValueError, match="counts differ"):
        collect.audit_windings(coils[1:], native)


def collected_history(directory, history_id):
    """A complete collection whose rotor field, in rotor axes, has a 5th and an 11th harmonic of the turn."""
    request = contract.load_request(history_id)
    directory.mkdir(parents=True)
    contract.write(directory / "protocol.json", {"history": request["history"], "request_sha256": contract.sha(contract.request_path(history_id)),
                                                 "spec_sha256": contract.sha(contract.SPEC), "femm_mesh": request["femm_mesh"],
                                                 "reference_identity": {"solver": "FEMM 5"}})
    corners = np.array([[[20.0, 0.0], [21.0, 0.0], [20.5, 1.0]], [[20.0, 2.0], [21.0, 2.0], [20.5, 3.0]]])
    contract.write_npz(directory / "rotor-geometry.npz", rotor_corners=corners)
    fields = []
    for index in range(contract.POSITIONS + 1):
        a = math.radians(contract.pose_angle(index))
        b = np.array([[0.8 + 0.3 * math.cos(5 * a), 0.2 * math.sin(11 * a)], [0.1 * math.sin(5 * a), 1.1 + 0.05 * math.cos(11 * a)]])
        fields.append(b)
        output = directory / f"position-{index:04d}"
        output.mkdir()
        contract.write_npz(output / "fields.npz", rotor=b)
        contract.write(output / "position.json", {
            "index": index, "angle_deg": contract.pose_angle(index), "wall_s": 1.0,
            "geometry_sha256": contract.sha(directory / "rotor-geometry.npz"), "protocol_sha256": contract.sha(directory / "protocol.json"),
            "sha256": {"fields.npz": contract.sha(output / "fields.npz")}})
    return request, corners, np.asarray(fields)


def test_the_report_works_out_the_loss_from_the_collected_turn_with_the_independent_calculator(tmp_path):
    from tools.rotor_loss_reference import reference_loss

    directory = tmp_path / "outer_spm_loaded"
    request, corners, fields = collected_history(directory, "outer_spm_loaded")
    record = report.analyse(directory, "outer_spm_loaded")
    assert record["schema"] == "coilem.phase_g_rotor_reference/v1" and record["solver"] == "FEMM 5"
    assert record["rotor_elements"] == 2 and record["closure"]["max_T"] < 1e-12 and record["collection_wall_s"] == 385
    stack = request["requested_config"]["stator"]["stack_length_mm"] * 1e-3
    for speed in contract.SPEEDS:
        for stride in contract.STRIDES:
            angles = [contract.pose_angle(index) for index in range(0, contract.POSITIONS, stride)]
            expected = reference_loss(fields[:-1:stride], angles, contract.areas(corners), speed_rpm=speed, stack_m=stack,
                                      coefficients=request["coefficients"], field_frame="rotor_material")
            got = record["speeds"][str(speed)][str(len(angles))]
            assert got["total_W"] == pytest.approx(expected["total_W"], rel=1e-12) and got["total_W"] > 0
            assert got["total_W"] == pytest.approx(got["hysteresis_W"] + got["lamination_eddy_W"], rel=1e-12)
    # Loss grows with speed (hysteresis like f, eddy like f squared).
    assert 2 < record["speeds"]["3000"]["384"]["total_W"] / record["speeds"]["1500"]["384"]["total_W"] < 4


def test_the_report_refuses_an_incomplete_or_altered_collection(tmp_path):
    directory = tmp_path / "inner_spm_loaded"
    collected_history(directory, "inner_spm_loaded")
    (directory / "position-0200" / "position.json").unlink()
    with pytest.raises(ValueError, match="pose 200 is missing"):
        report.analyse(directory, "inner_spm_loaded")
    other = tmp_path / "other" / "inner_spm_loaded"
    collected_history(other, "inner_spm_loaded")
    contract.write_npz(other / "position-0100" / "fields.npz", rotor=np.zeros((2, 2)))
    with pytest.raises(ValueError, match="A finished pose changed"):
        report.analyse(other, "inner_spm_loaded")
    with pytest.raises(ValueError, match="another request"):
        report.analyse(other, "inner_spm_no_load")


def femm_record(history_id, total_W):
    """A FEMM record with the same loss at every position count and both speeds."""
    by_count = {str(count): {"hysteresis_W": total_W * 0.3, "lamination_eddy_W": total_W * 0.7, "total_W": total_W} for count in (96, 192, 384)}
    return {"history": history_id, "solver": "FEMM 5", "speeds": {"1500": by_count, "3000": by_count}}


def rotor_history(total_W):
    by_count = {str(count): {"hysteresis_W": total_W * 0.3, "lamination_eddy_W": total_W * 0.7, "total_W": total_W} for count in (96, 192, 384)}
    return {"closure": {"max_T": 1e-13, "rms_T": 1e-14}, "speeds": {"1500": by_count, "3000": by_count}}


def test_rotor_loss_against_femm_allows_ten_percent_or_one_milliwatt_per_component():
    gates = g.spec()["gates"]
    graded = g.grade_rotor(rotor_history(0.0640), 3000, gates, femm_record("x", 0.0600))
    assert graded["reference"]["status"] == "PASS" and graded["reference"]["values"]["total_W"]["difference_pct"] == pytest.approx(6.667, abs=1e-3)
    assert g.grade_rotor(rotor_history(0.0680), 3000, gates, femm_record("x", 0.0600))["reference"]["status"] == "FAIL"
    # 0.3 mW against 0.1 mW is three times FEMM and still inside the 1 mW floor.
    assert g.grade_rotor(rotor_history(0.0003), 3000, gates, femm_record("x", 0.0001))["reference"]["status"] == "PASS"
    # Its own checks and the FEMM comparison are separate results.
    assert g.grade_rotor(rotor_history(0.0680), 3000, gates, femm_record("x", 0.0600))["status"] == "PASS"


@needs_stored_record
def test_a_stored_femm_record_grades_both_speeds_of_its_history(monkeypatch):
    stored = json.loads((g.ROOT / g.PROTOCOL / "results" / "coilem.json").read_text(encoding="utf-8"))
    measured = next(row for row in stored["rotor_histories"] if row["id"] == "inner_spm_loaded")["speeds"]

    def scaled(factor):
        speeds = {speed: {count: {key: value * factor for key, value in row.items()} for count, row in rows.items()}
                  for speed, rows in measured.items()}
        return {"inner_spm_loaded": {"history": "inner_spm_loaded", "solver": "FEMM 5", "speeds": speeds}}

    monkeypatch.setattr(g, "rotor_references", lambda: scaled(1.05))
    graded = g.compare(stored)
    assert graded["rotor_vs_femm"] == {"PASS": 2, "FAIL": 0, "NOT_RUN": 14} and "FEMM 5 for 1 of 8" in graded["rotor_reference"]
    # The own checks do not move when a FEMM record is added.
    assert graded["rotor_own_checks"] == stored["comparisons"]["rotor_own_checks"]
    monkeypatch.setattr(g, "rotor_references", lambda: scaled(1.25))
    assert g.compare(stored)["rotor_vs_femm"] == {"PASS": 0, "FAIL": 2, "NOT_RUN": 14}


def test_the_run_command_starts_windows_femm_or_femm5_at_the_chosen_minimum_angle(tmp_path):
    windows = orchestrator.collector("inner_spm_loaded", tmp_path, "1/4", None, ["--keep-answers"])
    assert windows[1:3] == ["-m", "tools.phase_g_femm.collect"] and windows[-1] == "--keep-answers" and "1/4" in windows
    femm5 = orchestrator.collector("inner_spm_loaded", tmp_path, "0/4", 33.0, [])
    assert femm5[1:5] == ["-m", "tools.phase_g_femm.femm5_run", "--min-angle", "33.0"] and femm5[5:7] == ["-m", "tools.phase_g_femm.collect"]
