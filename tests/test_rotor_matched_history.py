"""A reference comparison must match spatial excitation and physical materials."""

import copy
import math

import pytest

from tools.femm_reference.rotor_airgap import BOUNDARY
from tools.femm_reference.rotor_matched_history import match_geometry, mesh_controls, model_audit, selected_indices, validate_excitation


@pytest.mark.parametrize("mesh,target,arc", [("normal", 0.125, 0.25), ("fine", 0.1, 0.2), ("very_fine", 0.08, 0.16)])
def test_spatial_controls_are_explicit(mesh, target, arc):
    assert mesh_controls(mesh, target, arc) == {"mesh": mesh, "airgap_target_mm": target, "airgap_arc_step_deg": arc}


@pytest.mark.parametrize("target,arc", [(0, 0.2), (0.1, 0), (float("nan"), 0.2), (0.1, float("inf")), (0.1, 180)])
def test_nonphysical_spatial_controls_fail_before_collection(target, arc):
    with pytest.raises(ValueError, match="mesh controls"):
        mesh_controls("fine", target, arc)


@pytest.mark.parametrize("stride", [1, 2, 4])
def test_progressive_shards_cover_each_pose_once_and_keep_insertions_balanced(stride):
    shards = [set(selected_indices(384, stride, i, 4)) for i in range(4)]
    assert set.union(*shards) == set(range(0, 385, stride))
    assert sum(len(s) for s in shards) == len(set.union(*shards))
    if stride < 4:
        new_counts = [sum(i % (2*stride) != 0 for i in s) for s in shards]
        assert max(new_counts)-min(new_counts) <= 1


@pytest.mark.parametrize("angle,values", [(0, [207.84609690826525, -207.84609690826525, 0]),
                                         (-0.9375, [199.55270695261086, -215.24945796784516, 15.696751015234181]),
                                         (-22.5, [-120, -120, 240]), (-360, [207.84609690826525, -207.84609690826525, 0])])
def test_explicit_currents_match_independent_golden_native_schedule(angle, values):
    excitation = {"gate": "PASS", "native_gamma_deg": 180, "native_rotor_mechanical_deg": angle,
                  "phase_ampere_turns": dict(zip("ABC", values))}
    validate_excitation(excitation, angle)
    excitation["phase_ampere_turns"]["A"] *= -1
    with pytest.raises(ValueError, match="constant-gamma"):
        validate_excitation(excitation, angle)


def model():
    magnet = {"remanence_T": 1.315, "relative_permeability": 1.05}
    hc = 1.315/(1.05*4*math.pi*1e-7)
    text = f'[PrevSoln] = ""\n<BeginBdry>\n<BdryName> = "{BOUNDARY}"\n<innerangle> = -22.5\n<outerangle> = 0\n<EndBdry>\n'
    for name in ["Magnet", *(f"Magnet_N_{i}" for i in range(8))]:
        text += f'<BeginBlock>\n<BlockName> = "{name}"\n<Mu_x> = 1.05\n<Mu_y> = 1.05\n<H_c> = {hc}\n<J_re> = 0\n<EndBlock>\n'
    text += '<BeginBlock>\n<BlockName> = "Coil_v3_s0_l1"\n<J_re> = 2\n<EndBlock>\n'
    return text, {"Coil_v3_s0_l1": {"area_mm2": 80, "ampere_turns": 160}}, magnet


def test_saved_femm_coercivity_reconstructs_native_br_and_ni_uses_actual_area():
    text, applied, magnet = model()
    assert model_audit(text, -22.5, applied, magnet) == 0
    with pytest.raises(ValueError, match="magnet properties"):
        model_audit(text, -22.5, applied, magnet | {"remanence_T": 1.3})
    with pytest.raises(ValueError, match="boundary pose"):
        model_audit(text, 22.5, applied, magnet)
    with pytest.raises(ValueError, match="source materials"):
        model_audit(text, -22.5, {"Coil_v3_s0_l1": {"area_mm2": 81, "ampere_turns": 160}}, magnet)
    with pytest.raises(ValueError, match="previous-solution"):
        model_audit(text.replace('[PrevSoln] = ""', '[PrevSoln] = "old.ans"'), -22.5, applied, magnet)


def test_source_matching_uses_spatial_centres_and_rejects_phase_sign_swaps():
    native = [{"kind": "SlotWinding", "id": "slot0", "centroid_mm": [1, 0], "winding": {"phase": "A", "direction": "in"}},
              {"kind": "SlotWinding", "id": "slot1", "centroid_mm": [0, 1], "winding": {"phase": "B", "direction": "out"}}]
    observed = {"other_name1": {"centroid_mm": [0, 1], "phase": "B", "direction": "out"},
                "other_name0": {"centroid_mm": [1, 0], "phase": "A", "direction": "in"}}
    assert match_geometry(observed, native)[0]["native_region"] == "slot1"
    wrong = copy.deepcopy(observed)
    wrong["other_name0"]["direction"] = "out"
    with pytest.raises(ValueError, match="winding assignments"):
        match_geometry(wrong, native)
    wrong = copy.deepcopy(observed)
    wrong["other_name0"]["centroid_mm"] = [1.5, 0]
    with pytest.raises(ValueError, match="centroids"):
        match_geometry(wrong, native)


def test_magnet_polarity_is_matched_in_the_same_material_axes():
    native = [{"kind": "Magnet", "id": "m0", "centroid_mm": [1, 0], "magnetization_angle_deg": 0}]
    assert match_geometry({"north": {"centroid_mm": [1, 0], "magnetization_angle_deg": 360}}, native, magnet=True)
    with pytest.raises(ValueError, match="magnetization"):
        match_geometry({"north": {"centroid_mm": [1, 0], "magnetization_angle_deg": 180}}, native, magnet=True)
