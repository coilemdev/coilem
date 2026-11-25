"""The FEMM heat-flow reference: how the stator and the whole cross-section are drawn.

FEMM itself is not run here. The tests that judge the network against the
stored FEMM results are kept privately with those results, in
tests/private_records/test_thermal_records.py.
"""

from __future__ import annotations

import math

import pytest

from tools.check_thermal_conduction_fe import designs
from tools.check_thermal_conduction_femm import NO_MESH, WHOLE_GROUPS, lower, stator_regions, whole_section
from tools.femm_reference.ir_helpers import inside, polyline


@pytest.fixture(scope="module")
def configs():
    return {fixture: config for _, fixture, config, _ in designs()}




def _config(configs, text):
    return next(config for fixture, config in configs.items() if text in fixture)


def test_shared_edges_are_drawn_once_and_the_back_face_is_marked(configs):
    config = _config(configs, "spm_8p12s_concentrated")
    regions = stator_regions(config)
    model = lower(regions, {"back": config.stator.OD_mm / 2})
    drawn = len(model.lines) + len(model.arcs)
    listed = sum(len(loop.segments) for region in regions for loop in region.loops)
    # Every tooth side is also a slot side, and every tooth root and slot bottom is also part of the yoke.
    assert len(model.lines) == 2 * config.stator.slot_count
    assert drawn < listed
    assert len(model.faces["back"]) == 4
    assert all(math.hypot(*point) == pytest.approx(config.stator.OD_mm / 2) for point in model.faces["back"])
    assert len(model.labels) == len(regions)


def test_every_label_sits_inside_its_own_region_only(configs):
    for text in ("spm_8p12s_concentrated", "spm_outrunner_14p12s"):
        regions = stator_regions(_config(configs, text))
        model = lower(regions, {"back": (_config(configs, text).stator.ID_mm if "outrunner" in text else _config(configs, text).stator.OD_mm) / 2})
        outlines = {region.region_id: [polyline(loop) for loop in region.loops] for region in regions}
        for region_id, _, point in model.labels:
            for other, loops in outlines.items():
                within = inside(point, loops[0]) and not any(inside(point, hole) for hole in loops[1:])
                assert within == (other == region_id)


def test_an_outer_rotor_stator_is_held_at_its_hub_face(configs):
    config = _config(configs, "spm_outrunner_14p12s")
    model = lower(stator_regions(config), {"back": config.stator.ID_mm / 2})
    assert all(math.hypot(*point) == pytest.approx(config.stator.ID_mm / 2) for point in model.faces["back"])


def test_a_face_that_is_not_in_the_outlines_is_refused(configs):
    config = _config(configs, "spm_outrunner_14p12s")
    with pytest.raises(ValueError, match="Cooled face not found"):
        lower(stator_regions(config), {"back": config.stator.ID_mm / 2 + 0.5})


def test_the_shaft_is_left_out_of_the_whole_section(configs):
    assert WHOLE_GROUPS["Shaft"] == NO_MESH
    problem = whole_section(_config(configs, "spm_8p12s_concentrated"), 10.0)
    assert sum(problem["heat_W"].values()) == pytest.approx(10.0)
    assert sum(problem["network_exit_W"].values()) == pytest.approx(10.0)
    assert "Shaft" in {region.kind for region in problem["regions"]}
