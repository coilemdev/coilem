"""A mesh also serves rotor angles that are whole slot pitches less whole pole pitches away (opt-in)."""

from __future__ import annotations

import copy
import math

import pytest

from backend import solver_environment
from backend.gmsh_mesh_rotation import (
    congruence_shift,
    gmsh_pole_pitch_mesh_reuse_enabled,
    pole_pitch_congruence_groups,
    rotate_solve_mesh_artifact,
    slot_congruence_groups,
)


def test_congruence_shift_prefers_slot_pitches_and_finds_the_fewest_pole_pitches() -> None:
    # 12 slots: slot pitch 30 deg. 8 poles: pole pitch 45 deg.
    assert congruence_shift(30.0, 12) == (1, 0)
    assert congruence_shift(-60.0, 12, 8) == (-2, 0)
    assert congruence_shift(15.0, 12) is None
    assert congruence_shift(15.0, 12, 8) == (2, 1)  # 2 * 30 - 1 * 45
    assert congruence_shift(75.0, 12, 8) == (4, 1)
    assert congruence_shift(7.5, 12, 8) is None
    # 14 poles on 12 slots: every 360 / 84 deg is congruent.
    step = 360.0 / 84.0
    for multiple in range(1, 12):
        n_slots, n_poles = congruence_shift(multiple * step, 12, 14)
        assert math.isclose(n_slots * 30.0 - n_poles * (360.0 / 14.0), multiple * step, abs_tol=1e-9)
    assert congruence_shift(0.5 * step, 12, 14) is None


def test_bases_a_pole_pitch_apart_are_grouped() -> None:
    # An 8-pole 12-slot sweep at 7.5 deg electrical: 48 positions, 1.875 deg mechanical apart.
    jobs = [{"angle_key": index, "rotor_angle_mech_deg": index * 1.875} for index in range(48)]
    slot_groups = slot_congruence_groups(jobs, 12)
    assert len(slot_groups) == 16
    pole_groups = pole_pitch_congruence_groups([group["base"] for group in slot_groups], 12, 8)
    # Slot-pitch bases 15 deg apart share a mesh: eight meshes, each turned once more.
    assert len(pole_groups) == 8
    assert all(len(group["derived"]) == 1 for group in pole_groups)
    for group in pole_groups:
        (job, (n_slots, n_poles)), = group["derived"]
        delta = job["rotor_angle_mech_deg"] - group["base"]["rotor_angle_mech_deg"]
        assert math.isclose(delta, 15.0) and (n_slots, n_poles) == (2, 1)
    # The user's 14-pole 12-slot outrunner at 5 deg electrical: 42 slot-pitch bases, 6 meshes.
    jobs = [{"angle_key": index, "rotor_angle_mech_deg": index * 5.0 / 7.0} for index in range(72)]
    slot_groups = slot_congruence_groups(jobs, 12)
    assert len(slot_groups) == 42
    assert len(pole_pitch_congruence_groups([group["base"] for group in slot_groups], 12, 14)) == 6


def _artifact() -> dict:
    return {
        "mesh": {
            "nodes": [[10.0, 0.0], [0.0, 10.0], [-10.0, 0.0]],
            "triangles": [[0, 1, 2]],
            "regions": ["Magnet"],
            "info": {"rotor_angle_mech_deg": 0.0},
        },
        "element_region_ids": ["magnet_0"],
        "element_magnetization": [30.0],
        "element_current_density_a_per_m2": [None],
        "rotor_angle_mech_deg": 0.0,
        "physics_contract": {
            "motion": {"rotor_angle_mech_deg": 0.0},
            "regions": [
                {"id": "magnet_0", "kind": "Magnet", "source_group": "pm:n:magnet0", "magnetization_angle_deg": 30.0},
                {"id": "magnet_1", "kind": "Magnet", "source_group": "pm:S:magnet1", "magnetization_angle_deg": 255.0},
                {"id": "rotor_core", "kind": "RotorCore"},
            ],
            "provenance": {},
        },
    }


def _rotate(artifact: dict, target: float, pole_count: int | None) -> dict:
    return rotate_solve_mesh_artifact(
        artifact,
        slot_count=12,
        target_rotor_angle_mech_deg=target,
        phase_ampere_turns=lambda _elec: {"A": 0.0, "B": 0.0, "C": 0.0},
        current_angle_elec_deg_for_mech=lambda mech: 4.0 * mech,
        pole_count=pole_count,
    )


def test_an_odd_number_of_pole_pitches_turns_the_mesh_and_reverses_the_magnets() -> None:
    base = _artifact()
    before = copy.deepcopy(base)

    # 15 deg on 8 poles and 12 slots: two slot pitches forward, one pole pitch back.
    turned = _rotate(base, 15.0, 8)

    assert base == before
    assert turned["rotor_angle_mech_deg"] == 15.0
    assert turned["physics_contract"]["motion"]["rotor_angle_mech_deg"] == 15.0
    # The mesh turns by the two slot pitches, 60 deg, not by the 15 deg the rotor angle changed.
    x, y = turned["mesh"]["nodes"][0]
    assert math.isclose(x, 10.0 * math.cos(math.radians(60.0))) and math.isclose(y, 10.0 * math.sin(math.radians(60.0)))
    # Each magnet turns with the mesh and takes the opposite polarity.
    assert turned["element_magnetization"] == [pytest.approx((30.0 + 60.0 + 180.0) % 360.0)]
    regions = {region["id"]: region for region in turned["physics_contract"]["regions"]}
    assert regions["magnet_0"]["magnetization_angle_deg"] == pytest.approx(270.0)
    assert regions["magnet_0"]["source_group"] == "pm:s:magnet0"
    assert regions["magnet_1"]["magnetization_angle_deg"] == pytest.approx((255.0 + 240.0) % 360.0)
    assert regions["magnet_1"]["source_group"] == "pm:N:magnet1"
    assert turned["physics_contract"]["provenance"]["mesh_reuse"] == {
        "kind": "slot_and_pole_pitch_congruence_rotation",
        "rotated_from_rotor_angle_mech_deg": 0.0,
        "n_slot_pitches": 2,
        "n_pole_pitches": 1,
    }


def test_slot_pitches_alone_behave_as_before_with_or_without_a_pole_count() -> None:
    base = _artifact()
    plain = _rotate(base, 30.0, None)
    assert _rotate(base, 30.0, 8) == plain
    assert plain["element_magnetization"] == [60.0]
    assert plain["physics_contract"]["regions"][0]["source_group"] == "pm:n:magnet0"
    assert plain["physics_contract"]["provenance"]["mesh_reuse"] == {
        "kind": "slot_pitch_congruence_rotation",
        "rotated_from_rotor_angle_mech_deg": 0.0,
        "n_slot_pitches": 1,
    }
    # Without a pole count, an angle that needs pole pitches is still refused.
    with pytest.raises(ValueError, match="whole number of slot pitches"):
        _rotate(base, 15.0, None)
    # Two pole pitches leave the polarity alone: 14 poles, 12 slots, 60 deg electrical.
    even = _rotate(base, 2 * 360.0 / 84.0, 14)
    assert even["physics_contract"]["provenance"]["mesh_reuse"]["n_pole_pitches"] == 2
    assert even["physics_contract"]["regions"][0]["source_group"] == "pm:n:magnet0"
    assert even["element_magnetization"] == [pytest.approx(30.0 + 60.0)]


def test_pole_pitch_reuse_is_off_unless_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COILEM_MAGNETO2D_GMSH_POLE_PITCH_MESH_REUSE", raising=False)
    monkeypatch.setattr(solver_environment, "ISOLATED_RUNTIME", False)
    assert gmsh_pole_pitch_mesh_reuse_enabled() is False
    monkeypatch.setenv("COILEM_MAGNETO2D_GMSH_POLE_PITCH_MESH_REUSE", "1")
    assert gmsh_pole_pitch_mesh_reuse_enabled() is True
    # It rides on slot-pitch reuse: with that off there is no rotated mesh to start from.
    monkeypatch.setenv("COILEM_MAGNETO2D_GMSH_MESH_REUSE", "0")
    assert gmsh_pole_pitch_mesh_reuse_enabled() is False
    # The public runtime ignores the shell, so it stays off there whatever is set.
    monkeypatch.setenv("COILEM_MAGNETO2D_GMSH_MESH_REUSE", "1")
    monkeypatch.setattr(solver_environment, "ISOLATED_RUNTIME", True)
    assert gmsh_pole_pitch_mesh_reuse_enabled() is False


def test_pole_pitch_reuse_changes_the_mesh_signature_and_is_experimental(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from backend.magneto2d_adapter import build_magneto2d_mesh_signature
    from backend.models import MotorConfig
    from backend.qualification import classify_qualification
    from backend.topology_provenance import build_topology_provenance

    fixture = Path("benchmarks/main-20261009-bad71d9/fixtures/spm_8p12s_concentrated__baseline.json")
    config = MotorConfig.model_validate_json(fixture.read_text(encoding="utf-8"))
    monkeypatch.setattr("backend.qualification.evidence_matches_runtime", lambda: True)
    monkeypatch.setattr(solver_environment, "ISOLATED_RUNTIME", False)
    monkeypatch.delenv("COILEM_MAGNETO2D_GMSH_POLE_PITCH_MESH_REUSE", raising=False)
    # Off records nothing, so existing signatures and evidence hashes are unchanged.
    assert "pole_pitch_mesh_reuse" not in build_topology_provenance(config)["mesh_policy"]
    plain = build_magneto2d_mesh_signature(config)
    assert classify_qualification(config)["status"] == "qualified"

    monkeypatch.setenv("COILEM_MAGNETO2D_GMSH_POLE_PITCH_MESH_REUSE", "1")
    assert build_topology_provenance(config)["mesh_policy"]["pole_pitch_mesh_reuse"] is True
    assert build_magneto2d_mesh_signature(config) != plain
    result = classify_qualification(config)
    assert result["status"] == "experimental"
    assert result["reason"].startswith("Pole-pitch mesh reuse")
