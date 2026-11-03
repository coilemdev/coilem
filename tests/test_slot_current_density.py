"""Each slot carries exactly N·I·scale/paths, whatever its shape.

Slot current density used to be the slot's ampere-turns over a nominal
trapezoid area. A tooth shoe takes part of the slot, so the meshed winding is
smaller than that trapezoid and shoed designs ran at about 95% of their
current (the example 8p12s at 28.7 A of 30 A). The density is now spread over
each slot's meshed winding area, on a fresh mesh and on the cache's rotated
and re-baked meshes alike.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.excitation import phase_current_sample_dict, resolve_phase_current_sample
from backend.geometry_drawer import compute_3phase_slot_ampere_turns_for_rotor_elec
from backend.gmsh_mesh_rotation import _SLOT_REGION_RE
from backend.gmsh_solver import GMSH_AVAILABLE, run_gmsh_mesh_preview
from backend.models import MotorConfig
from backend.solver import _rebake_gmsh_artifact_for_config, _rotate_gmsh_artifact_for_config

pytestmark = [pytest.mark.pr, pytest.mark.skipif(not GMSH_AVAILABLE, reason="gmsh is not installed")]

CONCENTRATED = Path("tests/fixtures/spm_8p12s_concentrated.json")
SHOE = {"tooth_shoe_enabled": True, "tooth_shoe_overhang_mm": 0.6}
ROTOR_ANGLE_MECH_DEG = 7.0  # every phase carries current here

CASES = {
    "shoed single layer": ({"stator": SHOE}),
    "shoed tooth coils": ({"stator": SHOE, "winding": {"layers": 2}}),
    "shoed, two parallel paths": ({"stator": SHOE, "winding": {"parallel_paths": 2}}),
    "plain slots": ({}),
}


def _config(overrides: dict, **solve_params) -> MotorConfig:
    data = json.loads(CONCENTRATED.read_text(encoding="utf-8"))
    data["materials"].update(stator_steel="M350-50A", rotor_steel="M350-50A")
    for section, values in overrides.items():
        data[section].update(values)
    data["solve_params"].update(mesh_density="coarse", **solve_params)
    return MotorConfig.model_validate(data)


def _phase_ampere_turns(config: MotorConfig, rotor_angle_mech_deg: float) -> dict[str, float]:
    """N·I/paths from the terminal currents: a wye sine drive has no source scale."""

    elec = rotor_angle_mech_deg * config.rotor.pole_count // 2
    currents = phase_current_sample_dict(resolve_phase_current_sample(config, elec))
    turns, paths = config.winding.turns_per_coil, config.winding.parallel_paths
    return {phase: turns * current / paths for phase, current in currents.items()}


def _slot_integrals(artifact: dict) -> dict[int, dict[str, float]]:
    """∫J dA over each slot (A) and per winding region, from the elements themselves."""

    nodes = artifact["mesh"]["nodes"]
    out: dict[int, dict[str, float]] = {}
    for tri, region_id, density in zip(
        artifact["mesh"]["triangles"], artifact["element_region_ids"], artifact["element_current_density_a_per_m2"]
    ):
        match = _SLOT_REGION_RE.match(str(region_id))
        if match is None:
            continue
        (x1, y1), (x2, y2), (x3, y3) = (nodes[n][:2] for n in tri)
        area_m2 = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2.0 * 1e-6
        slot = out.setdefault(int(match.group("index")), {})
        slot[region_id] = slot.get(region_id, 0.0) + float(density) * area_m2
    return out


def _expected(artifact: dict, ampere_turns: dict[str, float]) -> dict[int, float]:
    """What each slot must carry: the signed sum of its coil sides, each its share of N·I/paths."""

    expected: dict[int, float] = {}
    for entry in artifact["physics_contract"]["regions"]:
        if entry["kind"] != "SlotWinding":
            continue
        winding = entry["winding"]
        sign = 1.0 if winding["direction"] == "in" else -1.0
        slot = int(_SLOT_REGION_RE.match(entry["id"]).group("index"))
        expected[slot] = expected.get(slot, 0.0) + sign * winding["turn_fraction"] * ampere_turns[winding["phase"]]
    return expected


def _assert_slots_carry(artifact: dict, ampere_turns: dict[str, float], *, rel: float = 1e-9) -> None:
    peak = max(abs(value) for value in ampere_turns.values())
    integrals = _slot_integrals(artifact)
    expected = _expected(artifact, ampere_turns)
    assert sorted(integrals) == sorted(expected)
    for slot, regions in integrals.items():
        assert sum(regions.values()) == pytest.approx(expected[slot], abs=rel * peak), slot
    # Each coil side of a split slot carries exactly its own share too.
    for entry in artifact["physics_contract"]["regions"]:
        if entry["kind"] == "SlotWinding":
            winding = entry["winding"]
            sign = 1.0 if winding["direction"] == "in" else -1.0
            slot = int(_SLOT_REGION_RE.match(entry["id"]).group("index"))
            share = sign * winding["turn_fraction"] * ampere_turns[winding["phase"]]
            assert integrals[slot][entry["id"]] == pytest.approx(share, abs=rel * peak), entry["id"]


@pytest.mark.parametrize("case", CASES, ids=str)
def test_each_slot_carries_its_ampere_turns(case: str) -> None:
    config = _config(CASES[case])
    artifact = run_gmsh_mesh_preview(config, rotor_angle_deg=ROTOR_ANGLE_MECH_DEG)["solve_mesh_artifact"]
    ampere_turns = _phase_ampere_turns(config, ROTOR_ANGLE_MECH_DEG)
    assert compute_3phase_slot_ampere_turns_for_rotor_elec(config, ROTOR_ANGLE_MECH_DEG * 4) == pytest.approx(ampere_turns)
    _assert_slots_carry(artifact, ampere_turns)


def test_a_shoed_slot_is_smaller_than_the_nominal_trapezoid() -> None:
    """The case this fixes: the meshed winding misses the shoe's share of the trapezoid."""

    from backend.geometry_drawer import _slot_body_width_mm, _slot_mouth_width_mm, _slot_radial_depth_mm

    config = _config({"stator": SHOE})
    artifact = run_gmsh_mesh_preview(config, rotor_angle_deg=ROTOR_ANGLE_MECH_DEG)["solve_mesh_artifact"]
    trapezoid = 0.5 * (_slot_mouth_width_mm(config) + _slot_body_width_mm(config)) * _slot_radial_depth_mm(config)
    meshed = {entry["winding"]["area_mm2"] for entry in artifact["physics_contract"]["regions"] if entry["kind"] == "SlotWinding"}
    assert max(meshed) < 0.99 * trapezoid


@pytest.mark.parametrize("case", ["shoed single layer", "shoed tooth coils"])
def test_cache_rotation_and_rebake_keep_each_slots_ampere_turns(case: str) -> None:
    config = _config(CASES[case])
    artifact = run_gmsh_mesh_preview(config, rotor_angle_deg=ROTOR_ANGLE_MECH_DEG)["solve_mesh_artifact"]

    # One slot pitch on: the rotated mesh carries the target angle's currents.
    target = ROTOR_ANGLE_MECH_DEG + 360.0 / config.stator.slot_count
    _assert_slots_carry(_rotate_gmsh_artifact_for_config(artifact, config, target), _phase_ampere_turns(config, target))

    # Another operating point on the cached mesh, as an MTPA sweep reuses it.
    other = _config(CASES[case], current_amplitude_A=35.0, current_angle_deg=30.0)
    _assert_slots_carry(_rebake_gmsh_artifact_for_config(artifact, other), _phase_ampere_turns(other, ROTOR_ANGLE_MECH_DEG))
