"""Independent fixed-current electrothermal balances; no FEM or fitted bands."""

import pytest

from backend.loss_breakdown import operating_point_losses
from backend.thermal_network import solve_copper_feedback, thermal_estimate
from tests.test_thermal_network import inputs, network, records


def test_single_node_matches_closed_form_equilibrium():
    # x = R*Q20*(1+alpha*(Ta-20+x)); x = 20*1.02/(1-.08).
    net = network([("winding", "ambient", 2)], {"winding": 10}, {"ambient": 25})
    resolved, temperatures, rejection, error, gain, residual = solve_copper_feedback(net, .004, ("winding",))
    expected = 25 + 20 * 1.02 / .92
    assert temperatures["winding"] == pytest.approx(expected)
    assert resolved.heat_W["winding"] == pytest.approx(10 * (1 + .004 * (expected - 20)))
    assert rejection == pytest.approx(resolved.heat_W["winding"])
    assert gain == pytest.approx(.08)
    assert abs(error) < 1e-10 and residual < 1e-10


def test_two_copper_nodes_use_their_own_temperatures_with_shared_cooling():
    # Write rises x=Tw-20, y=Te-20, z=Th-20 by hand:
    # z=2*(4+10*(1+.004*x)+5*(1+.004*y)); x=z+30*(1+.004*x);
    # y=z+25*(1+.004*y). Thus .8*x-.04*y=68, -.08*x+.86*y=63.
    net = network([("winding", "housing", 3), ("end_winding", "housing", 5), ("housing", "ambient", 2)],
                  {"winding": 10, "end_winding": 5, "housing": 4})
    resolved, t, rejection, error, _, residual = solve_copper_feedback(net, .004, ("winding", "end_winding"))
    x = (68 * .86 + .04 * 63) / (.8 * .86 - .04 * .08)
    y = (.8 * 63 + .08 * 68) / (.8 * .86 - .04 * .08)
    assert t["winding"] == pytest.approx(20 + x)
    assert t["end_winding"] == pytest.approx(20 + y)
    assert t["winding"] != pytest.approx(t["end_winding"])
    assert resolved.heat_W["winding"] == pytest.approx(10 * (1 + .004 * x))
    assert resolved.heat_W["end_winding"] == pytest.approx(5 * (1 + .004 * y))
    assert resolved.heat_W["housing"] == 4
    assert rejection == pytest.approx(sum(resolved.heat_W.values()))
    assert abs(error) < 1e-9 and residual < 1e-9


@pytest.mark.parametrize("heat", [125, 150])
def test_critical_and_supercritical_feedback_reject_algebraic_solutions(heat):
    # alpha*Q20*R >= 1: no stable physical equilibrium, even if invertible.
    net = network([("winding", "ambient", 2)], {"winding": heat})
    with pytest.raises(ValueError, match="No stable thermal equilibrium"):
        solve_copper_feedback(net, .004, ("winding",))


def test_shared_cooling_can_be_unstable_when_each_copper_path_alone_is_stable():
    net = network([("winding", "housing", .1), ("end_winding", "housing", .1), ("housing", "ambient", 1)],
                  {"winding": 150, "end_winding": 150})
    # Each self-gain is .66 < 1, but cross-heating makes the common-mode gain 1.26.
    with pytest.raises(ValueError, match="No stable thermal equilibrium"):
        solve_copper_feedback(net, .004, ("winding", "end_winding"))


@pytest.mark.parametrize("q,alpha,expected", [(0,.004,20), (10,0,40), (124,.004,31020)])
def test_zero_heat_constant_resistance_and_near_critical_stable_equilibrium(q, alpha, expected):
    _, t, _, _, gain, _ = solve_copper_feedback(network([("winding", "ambient", 2)], {"winding": q}), alpha, ("winding",))
    assert t["winding"] == pytest.approx(expected)
    assert gain < 1


def test_point_ignores_start_temperature_and_keeps_fixed_loss_path_unchanged():
    config, winding, losses, iron = records()
    settings = inputs(cooling="forced_air", housing_h_W_m2K=50)
    fixed = thermal_estimate(config, settings, winding, losses, iron)
    point = thermal_estimate(config, settings, winding, losses, iron, with_copper_feedback=True)
    assert fixed.copper_feedback is None
    assert point.copper_feedback is not None
    assert point.nodes["winding"].temperature_C > fixed.nodes["winding"].temperature_C
    assert point.nodes["magnets"].temperature_C > fixed.nodes["magnets"].temperature_C
    assert point.nodes["magnets"].heat_W == 0
    assert point.rotor_heating.basis == "heat_transfer_only"
    assert point.rotor_heating.internal_loss_status == "not_modelled"
    assert point.total_heat_W == pytest.approx(point.copper_feedback.copper_loss_W + iron.iron_loss_W)
    assert point.nodes["winding"].heat_W == point.copper_feedback.copper_active_loss_W
    assert point.nodes["end_winding"].heat_W == point.copper_feedback.copper_end_winding_loss_W
    assert 3 * losses.phase_current_rms_A**2 * point.copper_feedback.phase_resistance_ohm == pytest.approx(point.copper_feedback.copper_loss_W)
    hot_config = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"winding_temperature_C": 100})})
    hot_winding, hot_losses = operating_point_losses(hot_config, 1, iron)
    repeated = thermal_estimate(hot_config, settings, hot_winding, hot_losses, iron, with_copper_feedback=True)
    assert repeated == point  # No double temperature correction from a warm source run.
    assert type(point).model_validate_json(point.model_dump_json()) == point


def test_extra_rotor_sensitivity_resolves_its_own_copper_feedback_and_keeps_heat():
    config, winding, losses, iron = records(mechanical=12)
    settings = inputs(cooling="forced_air", housing_h_W_m2K=100, extra_rotor_heat_W=10, magnet_frequency_limit_Hz=200,
                      mechanical_split=dict(bearings=.25,housing=.5,rotor=.25))
    point = thermal_estimate(config, settings, winding, losses, iron, with_copper_feedback=True)
    baseline = thermal_estimate(config, settings.model_copy(update={"extra_rotor_heat_W": 0}), winding, losses, iron, with_copper_feedback=True)
    assert point.baseline_without_extra_rotor_C == {n:v.temperature_C for n,v in baseline.nodes.items()}
    assert point.copper_feedback.copper_loss_W > baseline.copper_feedback.copper_loss_W
    assert point.nodes["rotor"].heat_W == 13
    assert point.nodes["housing"].heat_W == 6
    assert point.nodes["bearings"].heat_W == 3
    assert point.nodes["teeth"].heat_W == 3
    assert point.nodes["yoke"].heat_W == 7


def test_unstable_point_has_no_temperature_or_partial_feedback_output():
    config, winding, losses, iron = records()
    result = thermal_estimate(config, inputs(housing_h_W_m2K=.0001), winding, losses, iron, with_copper_feedback=True)
    assert result.status == "unavailable"
    assert "No stable thermal equilibrium" in result.status_reason
    assert not result.nodes and result.network is None and result.copper_feedback is None
    assert result.hottest_node is None and result.total_heat_W is None


def test_feedback_still_rejects_missing_heat_and_nonphysical_resistance():
    config, winding, losses, iron = records()
    missing = iron.model_copy(update={"status":"unavailable", "iron_loss_W":None})
    assert thermal_estimate(config, inputs(), winding, losses, missing, with_copper_feedback=True).status == "unavailable"
    net = network([("winding", "ambient", 2)], {"winding": 10}, {"ambient": -260})
    with pytest.raises(ValueError, match="nonphysical conductor resistance"):
        solve_copper_feedback(net, .004, ("winding",))


def test_point_rejects_stable_root_outside_the_existing_resistance_domain():
    from backend.models import WindingResistance

    domain = WindingResistance.model_json_schema()["properties"]["winding_temperature_C"]
    assert (domain["minimum"], domain["maximum"]) == (-50, 250)
    config, winding, losses, iron = records()
    result = thermal_estimate(config, inputs(), winding, losses, iron, with_copper_feedback=True)
    assert result.status == "unavailable" and not result.nodes
    assert "outside -50 to 250 C" in result.status_reason
    assert "Raise the cooling values or lower the current" in result.status_reason


@pytest.mark.parametrize("convention,amplitude", [("rms",10),("peak",10*2**.5),("plateau",10*1.5**.5)])
def test_feedback_uses_rms_current_for_every_drive_convention(convention, amplitude):
    config, _, _, iron = records()
    config = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={
        "current_amplitude_convention": convention, "current_amplitude_A": amplitude,
    })})
    winding, losses = operating_point_losses(config, 1, iron)
    point = thermal_estimate(config, inputs(housing_h_W_m2K=100), winding, losses, iron, with_copper_feedback=True)
    assert point.copper_feedback.phase_current_rms_A == pytest.approx(10)
    assert point.copper_feedback.reference_copper_loss_W == pytest.approx(300*winding.phase_resistance_20C_ohm)


def test_zero_current_and_aluminium_feedback_preserve_the_conductor_properties():
    config, _, _, iron = records()
    for current in (0, 5):
        config = config.model_copy(update={
            "materials": config.materials.model_copy(update={"conductor":"aluminum"}),
            "solve_params": config.solve_params.model_copy(update={"current_amplitude_A":current}),
        })
        winding, losses = operating_point_losses(config, 1, iron)
        point = thermal_estimate(config, inputs(housing_h_W_m2K=100, conductor_k_W_mK=205), winding, losses, iron, with_copper_feedback=True)
        assert point.status == "experimental"
        assert point.copper_feedback.temperature_coefficient_per_K == .00403
        assert point.copper_feedback.phase_resistance_ohm > winding.phase_resistance_20C_ohm
        if current == 0:
            assert point.copper_feedback.copper_loss_W == 0
            assert point.total_heat_W == iron.iron_loss_W
