"""Loaded reference source conservation and independent torque conventions."""

import copy
import json

import numpy as np
import pytest

from backend.custom_materials import SteelImportRequest, import_steel
from tools.compare_pyleecan_loaded import ANGLES, REFERENCE_NM, dq_torque, sampling_control, summarize
from tools.pyleecan_prius_loaded_compare import assign_currents, override_steel


def steel_control_inputs():
    request = {"materials": {"stator_steel": "original", "rotor_steel": "original", "magnet_grade": "keep-magnet"},
               "stator": {"stack_length_mm": 83.82}, "solve_params": {"current_amplitude_A": 250}}
    artifact = {"mesh": {"nodes": [[0, 0], [1, 0], [0, 1]], "triangles": [[0, 1, 2]], "boundary_nodes": [0, 1, 2]},
                "physics_contract": {"regions": [
                    {"id": role, "material": f"steel:{role}:original"} for role in ("stator", "rotor")
                ] + [{"id": "pm", "material": "magnet:keep-magnet"}]},
                "element_magnetization": [15], "element_current_density_a_per_m2": [123]}
    steel = import_steel(SteelImportRequest(name="Steel control", source="Test curve", csv_text="B_T,H_A_per_m\n0,0\n1,100\n2,10000"))
    return request, artifact, steel


def test_steel_control_updates_both_roles_and_preserves_every_other_input():
    request, artifact, steel = steel_control_inputs()
    old_request, old_artifact = copy.deepcopy(request), copy.deepcopy(artifact)
    audit = override_steel(request, artifact, steel)
    assert audit["region_counts"] == {"stator": 1, "rotor": 1}
    assert audit["replacement"]["bh_curve"] == [[0, 0], [1, 100], [2, 10000]]
    for role in ("stator", "rotor"):
        assert request["materials"][f"{role}_steel"] == steel.id
        old_request["materials"][f"{role}_steel"] = steel.id
    old_request["materials"]["custom_steels"] = {steel.id: steel.model_dump(mode="json")}
    for region, original in zip(artifact["physics_contract"]["regions"], old_artifact["physics_contract"]["regions"], strict=True):
        if original["material"].startswith("steel:"):
            original["material"] = f"steel:{original['id']}:{steel.id}"
        assert region == original
    assert request == old_request
    assert artifact == old_artifact


@pytest.mark.parametrize("fault", ["missing_rotor", "mismatched_steel"])
def test_steel_control_rejects_partial_or_inconsistent_assignments_before_mutating(fault):
    request, artifact, steel = steel_control_inputs()
    if fault == "missing_rotor":
        artifact["physics_contract"]["regions"].pop(1)
    else:
        artifact["physics_contract"]["regions"][1]["material"] = "steel:rotor:unexpected"
    before = copy.deepcopy((request, artifact))
    with pytest.raises(ValueError):
        override_steel(request, artifact, steel)
    assert (request, artifact) == before


def test_explicit_source_preserves_ampere_turns_on_unequal_slot_areas():
    artifact = {
        "mesh": {"nodes": [[0, 0], [2, 0], [0, 1], [3, 0], [4, 0], [3, 1]], "triangles": [[0, 1, 2], [3, 4, 5]]},
        "element_region_ids": ["positive", "negative"],
        "physics_contract": {"regions": [
            {"id": name, "kind": "SlotWinding", "winding": {
                "phase": "A", "direction": direction, "layers": 1, "parallel_paths": 1,
                "turns_per_coil": 9, "turn_fraction": 1,
            }} for name, direction in [("positive", "in"), ("negative", "out")]]
        },
    }
    audit = assign_currents(artifact, [2, -1, -1])
    assert artifact["element_current_density_a_per_m2"] == pytest.approx([18e6, -36e6])
    assert [r["density_A_per_m2"] * r["area_m2"] for r in audit] == pytest.approx([18, -18])
    provenance = artifact["physics_contract"]["provenance"]
    assert provenance["phase_current_A"] == [2, -1, -1]
    assert provenance["element_current_density_sources"] == ["explicit_signed_phase_current"] * 2


@pytest.mark.parametrize("currents", [[1, 1, 1], [1, -1], [np.nan, 0, 0]])
def test_invalid_phase_currents_rejected(currents):
    with pytest.raises(ValueError, match="balanced"):
        assign_currents({}, currents)


@pytest.mark.parametrize("phi", [60, 90, 140, 180])
def test_park_torque_matches_analytical_salient_motor(phi):
    current_peak = 250
    id_, iq = current_peak * np.cos(np.radians(phi)), current_peak * np.sin(np.radians(phi))
    ld, lq, pm = .0005, .0015, .2
    expected = 6 * ((pm + ld * id_) * iq - lq * iq * id_)
    for angle in [0, -22.5, -67.5, -157.5]:
        theta = np.radians(angle + np.array([0, -120, 120]))
        row = {
            "time_electrical_angle_deg": angle,
            "phase_current_A": id_ * np.cos(theta) - iq * np.sin(theta),
            "phase_linkage_Wb": (pm + ld * id_) * np.cos(theta) - lq * iq * np.sin(theta) + 4,
        }
        assert dq_torque(row) == pytest.approx(expected, abs=1e-10)


def test_partial_loaded_sweep_cannot_be_reported_as_complete(tmp_path):
    (tmp_path / "registration.json").write_text(json.dumps({"expected_poses": 104}))
    (tmp_path / "completion.json").write_text(json.dumps({"complete": False}))
    (tmp_path / "waveform.json").write_text("[]")
    with pytest.raises(ValueError, match="complete"):
        summarize(tmp_path)


def complete_sweep(tmp_path):
    rows = []
    for phi, torque in zip(ANGLES, REFERENCE_NM, strict=True):
        for i in range(8):
            angle = -i * 22.5
            theta = np.radians(angle + np.array([0, -120, 120]))
            rows.append({
                "index": i, "current_angle_deg": phi, "time_electrical_angle_deg": angle,
                "phase_current_A": (250 * np.cos(theta + np.radians(phi))).tolist(),
                "phase_linkage_Wb": (.2 * np.cos(theta)).tolist(),
                "torque_Nm": torque, "nonlinear_residual": 1e-10,
            })
    (tmp_path / "registration.json").write_text(json.dumps({"expected_poses": 104}))
    (tmp_path / "completion.json").write_text(json.dumps({"complete": True}))
    return rows


def test_complete_curve_keeps_published_peak_and_distinct_single_point_target(tmp_path):
    rows = complete_sweep(tmp_path)
    (tmp_path / "waveform.json").write_text(json.dumps(rows))
    result = summarize(tmp_path)
    assert result["metrics"]["peak_mean_stress_Nm"] == 353
    assert result["metrics"]["peak_current_angle_deg"] == 140
    assert result["metrics"]["curve_RMSE_Nm"] == 0
    assert result["metrics"]["single_test_60deg_reference_Nm"] == 82
    assert all(r["change_Nm"] == 0 for r in result["sampling_coarsening"])


@pytest.mark.parametrize("change", ["current_phase", "duplicate_pose", "nonuniform_time"])
def test_reference_convention_and_pose_errors_cannot_silently_pass(tmp_path, change):
    rows = complete_sweep(tmp_path)
    if change == "current_phase":
        rows[0]["phase_current_A"] = rows[0]["phase_current_A"][::-1]
    elif change == "duplicate_pose":
        rows[0]["index"] = 1
    else:
        rows[1]["time_electrical_angle_deg"] += 1
    (tmp_path / "waveform.json").write_text(json.dumps(rows))
    with pytest.raises(ValueError):
        summarize(tmp_path)


def test_sampling_refinement_averages_ripple_instead_of_comparing_one_pose(tmp_path):
    coarse, fine = tmp_path / "coarse", tmp_path / "fine"
    coarse.mkdir()
    fine.mkdir()
    old = []
    new = []
    for n, rows in [(8, old), (16, new)]:
        for phi, avg in [(60, 83), (140, 353)]:
            for i in range(n):
                theta = -i * 180 / n
                rows.append({"index": i, "current_angle_deg": phi, "time_electrical_angle_deg": theta,
                             "torque_Nm": avg + 30 * np.sin(np.radians(6 * theta + 20))})
    (coarse / "waveform.json").write_text(json.dumps(old))
    (fine / "waveform.json").write_text(json.dumps(new))
    (fine / "registration.json").write_text(json.dumps({"expected_poses": 32}))
    (fine / "completion.json").write_text(json.dumps({"complete": True}))
    control = sampling_control(coarse, fine)
    assert control["pass"]
    assert [r["refined_mean_Nm"] for r in control["rows"]] == pytest.approx([83, 353])
    assert [r["change_Nm"] for r in control["rows"]] == pytest.approx([0, 0], abs=1e-10)
    new[0]["index"] = 1
    (fine / "waveform.json").write_text(json.dumps(new))
    with pytest.raises(ValueError, match="complete pose"):
        sampling_control(coarse, fine)
