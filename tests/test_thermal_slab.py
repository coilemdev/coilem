"""Independent boundary/mean balances for exact planar slab elements."""

import copy
import math

import pytest
from pydantic import ValidationError

from backend.benchmark_suite import thermal_analytical as suite
from backend.benchmark_suite.thermal_analytical_reference import reference_for
from backend.geometry_ir import build_geometry_ir
from backend.models.thermal import ThermalNetwork, ThermalSlab
from backend.thermal_network import boundary_heat_flows, build_network, solve_copper_feedback, solve_network, thermal_estimate
from tests.test_thermal_network import inputs, records


def slab_network(heat=12, resistance=1, left=20, right=40):
    return ThermalNetwork(nodes=["mean", "left", "right"], links=[],
        fixed_C={"right": right, **({"left": left} if left is not None else {})}, heat_W={"mean": heat},
        slabs=[ThermalSlab(mean="mean", a="left", b="right", resistance_K_W=resistance,
                          assumption="Uniform planar source; independently integrated test problem")])


@pytest.mark.parametrize("heat,left,right", [(12,20,20),(12,20,40),(0,20,40),(5,40,20),(0,20,20)])
def test_distinct_boundaries_match_mean_and_signed_fluxes(heat, left, right):
    net = slab_network(heat=heat, left=left, right=right)
    temperatures, rejected, balance = solve_network(net)
    assert temperatures["mean"] == pytest.approx((left + right) / 2 + heat / 12)
    assert boundary_heat_flows(net, temperatures) == pytest.approx({"left": heat / 2 + right - left,
                                                                  "right": heat / 2 + left - right})
    assert rejected == pytest.approx(heat, abs=1e-10) and abs(balance) < 1e-10


def test_insulated_surface_and_mean_are_not_the_same_temperature():
    net = slab_network(heat=10, resistance=3, left=None, right=20)
    t, rejected, balance = solve_network(net)
    # T(x)=20+g*(L^2-x^2)/(2*k): left rise Q*R/2, mean rise Q*R/3.
    assert t == pytest.approx({"left": 35, "mean": 30, "right": 20})
    assert rejected == pytest.approx(10) and abs(balance) < 1e-10


@pytest.mark.parametrize("heat", [10,125,150])
def test_copper_feedback_uses_spatial_mean_with_slab_surface_ports(heat):
    net = slab_network(heat=heat, resistance=6, left=None, right=20)
    # Exact one-face mean resistance is R/3=2; scalar feedback gain=.008*Q20.
    if heat >= 125:
        with pytest.raises(ValueError, match="No stable thermal equilibrium"):
            solve_copper_feedback(net, .004, ("mean",))
        return
    resolved, t, rejected, balance, gain, residual = solve_copper_feedback(net, .004, ("mean",))
    expected = 20 + 2 * heat / (1 - .008 * heat)
    assert t["mean"] == pytest.approx(expected)
    assert resolved.heat_W["mean"] == pytest.approx(heat * (1 + .004 * (expected - 20)))
    assert t["left"] == pytest.approx(20 + 3 * resolved.heat_W["mean"])
    assert gain == pytest.approx(.008 * heat)
    assert rejected == pytest.approx(resolved.heat_W["mean"])
    assert abs(balance) < 1e-9 and residual < 1e-9


def test_layered_element_matches_independent_integration_away_from_registered_inputs():
    template = next(c for c in suite.registration()["cases"] if c["id"] == "layered_combined")
    # Exercise transported and generated heat separately, including perfect
    # contact, changed geometry and a non-default ambient. No fitted coefficients.
    for q in ((0,0,1),(7,0,0),(0,11,0),(4,9,2)):
        for contact in (0, .3):
            case = copy.deepcopy(template)
            p = case["parameters"]
            p.update(ambient_C=41, contacts_K_W=[contact, .08], outer_resistance_K_W=.7, area_m2=.007)
            for i, layer in enumerate(p["layers"]):
                layer.update(heat_W=q[i], length_m=.004 * (i + 1), k_W_mK=.8 + 3*i)
            assert suite.prediction_for(case) == pytest.approx(reference_for(case).values, abs=1e-10, rel=1e-10)


@pytest.mark.parametrize("change", [{"a":"mean"},{"b":"missing"},{"resistance_K_W":-1},{"resistance_K_W":float("nan")}])
def test_invalid_slab_ports_and_resistance_are_rejected(change):
    raw = slab_network().model_dump()
    raw["slabs"][0].update(change)
    with pytest.raises(ValidationError):
        ThermalNetwork.model_validate(raw)


def test_motor_radial_adapter_matches_its_independently_integrated_limit():
    config, winding, losses, iron = records()
    settings = inputs()
    full = build_network(config, settings, winding, losses, iron)
    # Isolate the actual production radial path; no end/gap bypass. Winding-side
    # heat is distributed at the tooth mean by this explicitly reduced model.
    radial = ThermalNetwork(nodes=["winding","teeth","yoke","stator_bore","tooth_yoke_interface","stator_outer","housing"],
        links=[link for link in full.links if (link.a, link.b) in {("winding","teeth"),("stator_outer","housing")}],
        slabs=full.slabs, heat_W={"winding":10,"teeth":3,"yoke":7}, fixed_C={"housing":20})
    t, rejected, balance = solve_network(radial)
    length = config.stator.stack_length_mm * 1e-3
    outer, inner = config.stator.OD_mm * .0005, config.stator.ID_mm * .0005
    yoke = config.stator.yoke_thickness_mm * 1e-3
    depth = outer - inner - yoke
    area = sum(r.area_mm2 for r in build_geometry_ir(config).regions if r.kind == "StatorTooth") * 1e-6
    rt = depth**2 / (settings.steel_k_W_mK * area * length)
    ry = yoke / (settings.steel_k_W_mK * 2 * math.pi * outer * length)
    rc = settings.contact_m2K_W / (2 * math.pi * outer * length)
    rc += math.log((outer + settings.housing_thickness_mm * 1e-3) / outer) / (2 * math.pi * settings.housing_k_W_mK * length)
    surface = 20 + 20 * rc
    interface = surface + (13 + 7/2) * ry
    assert t["stator_outer"] == pytest.approx(surface)
    assert t["yoke"] == pytest.approx(surface + (13/2 + 7/3) * ry)
    assert t["tooth_yoke_interface"] == pytest.approx(interface)
    assert t["teeth"] == pytest.approx(interface + 13 * rt/3)
    assert t["stator_bore"] == pytest.approx(interface + 13 * rt/2)
    assert rejected == pytest.approx(20) and abs(balance) < 1e-9


def test_surface_ports_stay_internal_and_legacy_networks_still_parse():
    config, winding, losses, iron = records()
    result = thermal_estimate(config, inputs(), winding, losses, iron)
    assert len(result.network.slabs) == 2
    assert len(result.nodes) == 11
    assert not {"stator_bore","tooth_yoke_interface","stator_outer"}.intersection(result.nodes)
    assert type(result).model_validate_json(result.model_dump_json()) == result
    legacy = {"nodes":["ambient"],"links":[],"fixed_C":{"ambient":20},"heat_W":{}}
    assert ThermalNetwork.model_validate(legacy).slabs == []
