"""Independent hand balances and heat accounting for the unqualified M1 core."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from backend.loss_breakdown import operating_point_losses
from backend.models import IronLoss, MotorConfig
from backend.models.thermal import ThermalInputs, ThermalLink, ThermalNetwork
from backend.thermal_network import build_network, solve_network, thermal_estimate
from tests.test_flux_linkage_map import _config


def inputs(**changes):
    return ThermalInputs.model_validate(dict(
        cooling="still_air", ambient_C=20, housing_h_W_m2K=10,
        end_space_h_W_m2K=10, airgap_h_W_m2K=20,
        coefficient_source="Test assumption, not measured cooling",
        housing_thickness_mm=3, slot_liner_mm=0.1, contact_m2K_W=0.001,
        bearing_to_housing_K_W=2, rotor_to_bearing_K_W=3,
        insulation_class="F", hotspot_allowance_K=15,
    ) | changes)


def iron_loss(split=True):
    return IronLoss(
        status="experimental", steel="M350-50A", electrical_frequency_Hz=100,
        iron_loss_W=10, iron_hysteresis_loss_W=6, iron_eddy_loss_W=4,
        iron_teeth_loss_W=3 if split else None, iron_yoke_loss_W=7 if split else None,
        stator_iron_mass_kg=1, validated_max_frequency_Hz=1000,
        validated_max_flux_density_T=1.5,
    )


def network(links, heat, fixed=None):
    fixed = fixed or {"ambient": 20}
    nodes = list(dict.fromkeys([*fixed, *heat, *(node for a, b, _ in links for node in (a, b))]))
    return ThermalNetwork(
        nodes=nodes, links=[ThermalLink(a=a, b=b, resistance_K_W=r, assumption="Hand example") for a, b, r in links],
        fixed_C=fixed, heat_W=heat,
    )


@pytest.mark.parametrize("links,heat,expected", [
    # 10 W through 2 K/W: 20 + 20 = 40 C (single-node conduction).
    ([("winding", "ambient", 2)], {"winding": 10}, {"winding": 40}),
    # Convection with h=10, A=0.02: R=1/(hA)=5 K/W.
    ([("winding", "ambient", 5)], {"winding": 10}, {"winding": 70}),
    # Series resistances 2+3, same 10 W through both.
    ([("winding", "housing", 2), ("housing", "ambient", 3)], {"winding": 10}, {"winding": 70, "housing": 50}),
    # Parallel resistances 2||2 = 1 K/W.
    ([("winding", "ambient", 2), ("winding", "ambient", 2)], {"winding": 10}, {"winding": 30}),
    # Two sources: housing rejects 15 W via 2 K/W; winding adds 10*3 K.
    ([("winding", "housing", 3), ("housing", "ambient", 2)], {"winding": 10, "housing": 5}, {"winding": 80, "housing": 50}),
])
def test_hand_checked_networks(links, heat, expected):
    temperatures, rejection, error = solve_network(network(links, heat))
    for name, value in expected.items():
        assert temperatures[name] == pytest.approx(value)
    assert rejection == pytest.approx(sum(heat.values()))
    assert abs(error) < 1e-10


def test_multiple_boundaries_and_unheated_floating_node():
    temperatures, rejection, _ = solve_network(network(
        [("w", "cold", 1), ("w", "hot", 1)], {"w": 10}, {"cold": 20, "hot": 40},
    ))
    assert temperatures["w"] == pytest.approx(35)
    assert rejection == pytest.approx(10)
    floating = network([("w", "ambient", 1)], {"w": 1, "floating": 0})
    with pytest.raises(ValueError, match="disconnected"):
        solve_network(floating)


def test_inputs_require_explicit_coefficients_hotspot_and_calibration_source():
    with pytest.raises(ValidationError):
        ThermalInputs(cooling="still_air", ambient_C=20)
    with pytest.raises(ValidationError, match="calibration"):
        inputs(calibration_multiplier=2)
    with pytest.raises(ValidationError):
        inputs(steel_k_W_mK=float("nan"))
    with pytest.raises(ValidationError, match="sum to one"):
        inputs(mechanical_split=dict(bearings=0.3, housing=0.3, rotor=0.3))


def records(mechanical=0, split=True):
    config = _config(mechanical_loss_W=mechanical)
    iron = iron_loss(split)
    winding, losses = operating_point_losses(config, 1, iron)
    return config, winding, losses, iron


def test_geometry_network_conserves_every_heat_source_and_sensitivity():
    config, winding, losses, iron = records(12)
    settings = inputs(mechanical_split=dict(bearings=0.25, housing=0.5, rotor=0.25),
                      extra_rotor_heat_W=5, magnet_frequency_limit_Hz=200)
    result = thermal_estimate(config, settings, winding, losses, iron)
    assert result.status == "experimental"
    assert result.total_heat_W == pytest.approx(losses.copper_loss_W + 10 + 12 + 5)
    assert result.rejected_heat_W == pytest.approx(result.total_heat_W)
    assert abs(result.energy_balance_error_W) < 1e-8
    assert result.nodes["rotor"].heat_W == 8
    assert result.rotor_heating.basis == "heat_transfer_plus_supplied_heat"
    assert result.rotor_heating.additional_heat_W == 5
    assert result.rotor_heating.mechanical_heat_to_rotor_W == 3
    assert result.rotor_heating.internal_loss_status == "not_modelled"
    assert result.nodes["bearings"].heat_W == 3
    assert result.nodes["housing"].heat_W == 6
    assert result.nodes["teeth"].heat_W == 3
    assert result.nodes["magnets"].status == "experimental"
    assert "eddy" in result.nodes["magnets"].status_reason
    assert result.nodes["winding"].limit_C == 140
    assert result.nodes["magnets"].limit_C == 80
    assert result.nodes["rotor"].temperature_C > result.baseline_without_extra_rotor_C["rotor"]
    assert result.hottest_node in result.nodes
    restored = type(result).model_validate_json(result.model_dump_json())
    assert restored == result


def test_missing_inputs_are_unavailable_instead_of_zero_heat():
    config, winding, losses, iron = records(10)
    result = thermal_estimate(config, inputs(), winding, losses, iron)
    assert result.status == "unavailable" and "destination" in result.status_reason
    unavailable = IronLoss(status="unavailable", status_reason="No data", steel="unknown",
                           validated_max_frequency_Hz=1000, validated_max_flux_density_T=1.5)
    result = thermal_estimate(config, inputs(), winding, losses, unavailable)
    assert result.status == "unavailable" and not result.nodes


def test_transferred_heat_is_visible_with_missing_internal_losses_explicit():
    config, winding, losses, iron = records(split=False)
    result = thermal_estimate(config, inputs(), winding, losses, iron)
    assert result.nodes["teeth"].heat_W + result.nodes["yoke"].heat_W == pytest.approx(10)
    temperatures, _, _ = solve_network(result.network)
    for name in ("rotor", "magnets", "bearings", "end_air", "airgap"):
        assert result.nodes[name].status == "experimental"
        assert result.nodes[name].heat_W == 0
        assert result.nodes[name].temperature_C == pytest.approx(temperatures[name])
        assert result.nodes[name].temperature_C > result.inputs.ambient_C
    assert result.rotor_heating.basis == "heat_transfer_only"
    assert result.rotor_heating.additional_heat_W == 0
    assert result.rotor_heating.mechanical_heat_to_rotor_W == 0
    assert result.rotor_heating.internal_loss_status == "not_modelled"
    assert "unknown contribution" in result.nodes["magnets"].status_reason
    assert "bearing friction is not independently calculated" in result.nodes["bearings"].status_reason
    assert result.nodes["winding"].status == "experimental"
    # A historical declaration neither changes the solve nor establishes scope.
    for limit in (1, 1000):
        legacy = thermal_estimate(config, inputs(magnet_frequency_limit_Hz=limit), winding, losses, iron)
        assert legacy.network == result.network
        assert legacy.nodes == result.nodes
        assert legacy.rotor_heating == result.rotor_heating


def test_hottest_headline_excludes_air_and_bearing_path_nodes():
    config, winding, losses, iron = records(mechanical=1000)
    settings = inputs(mechanical_split=dict(bearings=1, housing=0, rotor=0), magnet_frequency_limit_Hz=200)
    result = thermal_estimate(config, settings, winding, losses, iron)
    assert result.nodes["bearings"].temperature_C > result.nodes[result.hottest_node].temperature_C
    materials = {"winding", "end_winding", "teeth", "yoke", "housing", "rotor", "magnets"}
    assert result.hottest_node in materials
    assert result.nodes[result.hottest_node].temperature_C == max(result.nodes[n].temperature_C for n in materials)
    outside = thermal_estimate(config, settings.model_copy(update={"magnet_frequency_limit_Hz": 1}), winding, losses, iron)
    assert outside.nodes == result.nodes
    assert outside.hottest_node == result.hottest_node
    # Heat deposited in bearings can warm the rotor via transfer without being
    # mislabelled as internally generated rotor heat.
    assert outside.rotor_heating.basis == "heat_transfer_only"


def test_calibration_remains_experimental_and_records_its_source():
    config, winding, losses, iron = records()
    normal = thermal_estimate(config, inputs(), winding, losses, iron)
    settings = inputs(calibration_multiplier=2, calibration_source=dict(
        measurement="DC resistance rise", operating_point="10 A, standstill", cooling="still air at 20 C"))
    calibrated = thermal_estimate(config, settings, winding, losses, iron)
    assert calibrated.calibrated
    assert calibrated.nodes["winding"].status == "experimental"
    assert calibrated.nodes["winding"].temperature_C - 20 == pytest.approx(2 * (normal.nodes["winding"].temperature_C - 20))
    assert calibrated.inputs.calibration_source.measurement == "DC resistance rise"


def test_template_rejects_impossible_liner_and_inconsistent_losses():
    config, winding, losses, iron = records()
    with pytest.raises(ValueError, match="liner"):
        build_network(config, inputs(slot_liner_mm=50), winding, losses, iron)
    iron = iron.model_copy(update={"iron_teeth_loss_W": 11})
    with pytest.raises(ValueError, match="sum"):
        build_network(config, inputs(), winding, losses, iron)


def test_aluminium_does_not_silently_use_copper_conductivity():
    config, winding, losses, iron = records()
    config = config.model_copy(update={"materials": config.materials.model_copy(update={"conductor": "aluminum"})})
    result = thermal_estimate(config, inputs(), winding, losses, iron)
    assert result.status == "unavailable" and "conductivity" in result.status_reason
    assert thermal_estimate(config, inputs(conductor_k_W_mK=205), winding, losses, iron).status == "experimental"


def test_uniform_generation_slab_means_match_poisson_solution():
    from backend.thermal_network import slab_mean_resistance

    # g=12 W/m3, w=0.2 m, k=2, A=3: Q=g*w*A.
    g, width, k, area = 12, 0.2, 2, 3
    heat = g * width * area
    resistance = slab_mean_resistance(width, k, area, two_sided=True)
    temperatures, _, _ = solve_network(network([("mean", "ambient", resistance)], {"mean": heat}))
    assert temperatures["mean"] - 20 == pytest.approx(g * width**2 / (12 * k))
    one_face = slab_mean_resistance(width, k, area, two_sided=False)
    assert heat * one_face == pytest.approx(g * width**2 / (3 * k))


def test_unheated_housing_preserves_cylindrical_log_resistance():
    import math

    from backend.thermal_network import cylindrical_resistance

    assert cylindrical_resistance(0.1, 0.12, 0.2, 200) == pytest.approx(math.log(1.2) / (2 * math.pi * 200 * 0.2))


def test_end_surface_follows_actual_coil_arc_geometry_and_per_surface_gap():
    import json
    import math
    from pathlib import Path

    from backend.geometry_ir import build_geometry_ir
    from backend.models import MotorConfig
    from backend.thermal_network import end_winding_surface
    from backend.winding_resistance import _winding_coils

    raw = json.loads(Path("benchmarks/abcd-v1.5/fixtures/spm_8p12s_example_shoed.json").read_text())
    config = MotorConfig.model_validate(raw.get("config", raw))
    iron = iron_loss()
    winding, losses = operating_point_losses(config, 10, iron)
    area = sum(r.area_mm2 for r in build_geometry_ir(config).regions if r.kind == "SlotWinding") * 1e-6
    exposed, side = end_winding_surface(config, winding, area)
    assert exposed == pytest.approx(len(_winding_coils(config)) * 2 * winding.end_turn_length_mm * 1e-3 * 4 * side)
    # Gross bundle volume is total slot gross area times one end-turn length;
    # this matches the assumed active-slot fill and transverse conductivity.
    assert exposed * side / 4 == pytest.approx(area * winding.end_turn_length_mm * 1e-3)
    links = {(link.a, link.b): link.resistance_K_W for link in build_network(config, inputs(), winding, losses, iron).links}
    stack = config.stator.stack_length_mm * 1e-3
    assert links[("stator_bore", "airgap")] == pytest.approx(1 / (20 * math.pi * config.stator.ID_mm * 1e-3 * stack))
    assert links[("airgap", "rotor")] == pytest.approx(1 / (20 * math.pi * config.rotor.OD_mm * 1e-3 * stack))


def test_user_slot_conductivity_and_magnet_heat_sensitivity_are_explicit():
    config, winding, losses, iron = records()
    with pytest.raises(ValidationError, match="value and source"):
        inputs(slot_k_model="user", slot_k_W_mK=1)
    settings = inputs(slot_k_model="user", slot_k_W_mK=1, slot_k_source="User measured transverse value",
                      extra_rotor_heat_W=5, extra_rotor_heat_to_magnets_fraction=1, magnet_frequency_limit_Hz=200)
    result = thermal_estimate(config, settings, winding, losses, iron)
    assert result.nodes["magnets"].heat_W == 5
    assert result.nodes["magnets"].temperature_C > result.nodes["rotor"].temperature_C
    assert result.nodes["magnets"].temperature_C > result.baseline_without_extra_rotor_C["magnets"]


def _outer_records(current_A=8.0):
    """A 12-slot / 14-pole outrunner near the LRK reference, with its winding and loss records."""
    from tests.test_rotor_layout import outer_config

    raw = outer_config()
    raw["solve_params"]["current_amplitude_A"] = current_A
    config = MotorConfig.model_validate(raw)
    iron = iron_loss()
    winding, losses = operating_point_losses(config, 0.1, iron)
    return config, winding, losses, iron


def _outer_inputs(**changes):
    return inputs(**({"mount_to_ambient_K_W": 8.0} | changes))


def test_outer_rotor_network_sheds_heat_through_the_mount_and_the_rotor_shell():
    config, winding, losses, iron = _outer_records()
    network = build_network(config, _outer_inputs(), winding, losses, iron)
    assert "mount" in network.nodes and "housing" not in network.nodes
    to_ambient = sorted(sorted((link.a, link.b)) for link in network.links if "ambient" in (link.a, link.b))
    assert to_ambient == [["ambient", "mount"], ["ambient", "rotor"]], "Exactly two ways out: the mount and the rotor shell"
    result = thermal_estimate(config, _outer_inputs(), winding, losses, iron, with_copper_feedback=True)
    assert result.status == "experimental", result.status_reason
    assert set(result.nodes) >= {"winding", "end_winding", "teeth", "yoke", "mount", "rotor", "magnets", "ambient"}
    assert "housing" not in result.nodes
    assert result.energy_balance_error_W == pytest.approx(0, abs=1e-6)
    assert result.rejected_heat_W == pytest.approx(result.total_heat_W, rel=1e-9)
    assert all(node.temperature_C > 20 for name, node in result.nodes.items() if name != "ambient")
    assert result.nodes["winding"].temperature_C > result.nodes["yoke"].temperature_C > result.nodes["mount"].temperature_C
    assert any("Outer rotor" in note for note in result.notes)


def test_outer_rotor_estimate_needs_the_mount_resistance():
    config, winding, losses, iron = _outer_records()
    result = thermal_estimate(config, inputs(), winding, losses, iron, with_copper_feedback=True)
    assert result.status == "unavailable"
    assert "mount-to-surroundings resistance" in result.status_reason
    assert not result.nodes


def test_outer_rotor_cooling_inputs_each_lower_the_winding_temperature():
    config, winding, losses, iron = _outer_records()

    def hot(**changes):
        result = thermal_estimate(config, _outer_inputs(**changes), winding, losses, iron)
        assert result.status == "experimental", result.status_reason
        return result.nodes["winding"].temperature_C

    base = hot()
    assert hot(mount_to_ambient_K_W=2.0) < base, "A better mount cools the stator"
    assert hot(housing_h_W_m2K=100) < base, "More air over the rotor shell cools the stator"
    assert hot(airgap_h_W_m2K=200) < base, "A better gap path lets the shell take more heat"
    # With no way out through the shell, every watt must cross the mount resistance.
    blocked = thermal_estimate(config, _outer_inputs(housing_h_W_m2K=1e-9), winding, losses, iron)
    assert blocked.nodes["mount"].temperature_C - 20 == pytest.approx(blocked.total_heat_W * 8.0, rel=1e-4)


def test_outer_rotor_shell_path_matches_a_hand_calculation():
    """Block the mount: all heat leaves by the shell's entered coefficient over its stated outside area."""
    config, winding, losses, iron = _outer_records()
    h = 40.0
    result = thermal_estimate(config, _outer_inputs(mount_to_ambient_K_W=1e9, housing_h_W_m2K=h), winding, losses, iron)
    assert result.status == "experimental", result.status_reason
    length = config.stator.stack_length_mm * 1e-3
    inner_r, outer_r = config.rotor.ID_mm * 0.0005, config.rotor.OD_mm * 0.0005
    outside = 2 * math.pi * outer_r * length + math.pi * outer_r**2
    shell = 1 / (h * outside) + math.log(outer_r / inner_r) / (2 * math.pi * 20.0 * length)
    assert result.nodes["rotor"].temperature_C - 20 == pytest.approx(result.total_heat_W * shell, rel=1e-4)


def test_outer_rotor_mechanical_heat_for_the_stator_support_lands_on_the_mount():
    from tests.test_rotor_layout import outer_config

    raw = outer_config()
    raw["solve_params"]["mechanical_loss_W"] = 4.0
    config = MotorConfig.model_validate(raw)
    iron = iron_loss()
    winding, losses = operating_point_losses(config, 0.1, iron)
    network = build_network(config, _outer_inputs(mechanical_split=dict(bearings=0.25, housing=0.5, rotor=0.25)), winding, losses, iron)
    assert network.heat_W["mount"] == pytest.approx(2.0)
    assert "housing" not in network.heat_W


def test_inner_rotor_network_is_unchanged_by_the_mount_input():
    config, winding, losses, iron = records()
    plain = thermal_estimate(config, inputs(), winding, losses, iron)
    with_mount = thermal_estimate(config, inputs(mount_to_ambient_K_W=3.0), winding, losses, iron)
    assert plain.status == "experimental", plain.status_reason
    assert "housing" in plain.nodes and "mount" not in plain.nodes
    assert {name: node.temperature_C for name, node in plain.nodes.items()} == {name: node.temperature_C for name, node in with_mount.nodes.items()}
