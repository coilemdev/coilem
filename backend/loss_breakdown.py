"""Losses and efficiency at the solved operating point (#138).

The solved torque is the electromagnetic torque; nothing here changes it.
Iron and mechanical loss act as a drag on the rotor, so

    P_shaft = T_em · ω − P_iron − P_mech      T_shaft = T_em − (P_iron + P_mech) / ω
    P_in    = P_shaft + P_copper + P_iron + P_mech = T_em · ω + P_copper

Copper loss is 3 · I_rms² · R at the winding temperature, split between the
stack and the end turns by the mean turn length. Efficiency needs the iron
loss, so it is experimental like the iron loss, and unavailable when the iron
loss is, at standstill, or when the motor is not motoring.
"""

from __future__ import annotations

import math

from backend.models import IronLoss, LossBreakdown, MotorConfig, WindingResistance
from backend.winding_resistance import winding_resistance


def phase_current_rms_a(config: MotorConfig) -> float:
    """RMS phase current of the solved excitation."""

    solve_params = config.solve_params
    if solve_params is None:
        return 0.0
    amplitude = float(solve_params.current_amplitude_A)
    convention = solve_params.current_amplitude_convention
    if convention == "rms":
        return amplitude
    if convention == "plateau":
        # Ideal 120° six-step: each phase conducts the plateau current for two thirds of the period.
        return amplitude * math.sqrt(2.0 / 3.0)
    return amplitude / math.sqrt(2.0)


def operating_point_losses(
    config: MotorConfig,
    electromagnetic_torque_nm: float,
    iron_loss: IronLoss | None,
) -> tuple[WindingResistance | None, LossBreakdown | None]:
    """The winding's resistance record and the loss breakdown, or None where they cannot be formed."""

    try:
        winding = winding_resistance(config)
    except (ValueError, KeyError):
        return None, None
    solve_params = config.solve_params
    if solve_params is None or not math.isfinite(electromagnetic_torque_nm):
        return winding, None

    speed_rpm = float(solve_params.rated_speed_rpm)
    omega = 2.0 * math.pi * speed_rpm / 60.0
    current_rms = phase_current_rms_a(config)
    copper = 3.0 * current_rms**2 * winding.phase_resistance_ohm
    copper_active = copper * winding.active_fraction
    iron_available = iron_loss is not None and iron_loss.status != "unavailable" and iron_loss.iron_loss_W is not None
    iron = iron_loss.iron_loss_W if iron_available else None
    mechanical = float(solve_params.mechanical_loss_W or 0.0)
    drag = (iron or 0.0) + mechanical
    electromagnetic_power = electromagnetic_torque_nm * omega
    shaft_power = electromagnetic_power - drag
    total = copper + drag
    input_power = shaft_power + total

    efficiency = None
    if speed_rpm <= 0:
        reason = "Efficiency needs a nonzero speed."
    elif electromagnetic_torque_nm <= 0:
        reason = "Efficiency is reported for motoring, with positive torque."
    elif not iron_available:
        reason = "Efficiency needs the iron loss. " + (iron_loss.status_reason if iron_loss and iron_loss.status_reason else "")
    elif shaft_power <= 0 or input_power <= 0:
        reason = "The losses exceed the electromagnetic power at this operating point."
    else:
        efficiency = 100.0 * shaft_power / input_power
        reason = "Uses the experimental iron loss."

    breakdown = LossBreakdown(
        speed_rpm=speed_rpm,
        phase_current_rms_A=current_rms,
        electromagnetic_torque_Nm=electromagnetic_torque_nm,
        shaft_torque_Nm=electromagnetic_torque_nm - drag / omega if omega > 0 else electromagnetic_torque_nm,
        electromagnetic_power_W=electromagnetic_power,
        phase_resistance_ohm=winding.phase_resistance_ohm,
        winding_temperature_C=winding.winding_temperature_C,
        copper_loss_W=copper,
        copper_active_loss_W=copper_active,
        copper_end_winding_loss_W=copper - copper_active,
        iron_loss_W=iron,
        iron_hysteresis_loss_W=iron_loss.iron_hysteresis_loss_W if iron_available else None,
        iron_eddy_loss_W=iron_loss.iron_eddy_loss_W if iron_available else None,
        iron_loss_status=iron_loss.status if iron_available else "unavailable",
        iron_loss_status_reason=iron_loss.status_reason if iron_loss is not None else "No iron-loss estimate for this run.",
        mechanical_loss_W=mechanical,
        total_loss_W=total,
        shaft_power_W=shaft_power,
        input_power_W=input_power,
        efficiency_pct=efficiency,
        efficiency_status="experimental" if efficiency is not None else "unavailable",
        efficiency_status_reason=reason.strip(),
    )
    return winding, breakdown


def iron_loss_density_on_plot(
    density: dict | None,
    triangles: list,
    regions: list,
) -> tuple[list[float | None], float] | None:
    """Spread the reference frame's W/kg over the field_line_plot mesh, or None when they do not match."""

    if not isinstance(density, dict):
        return None
    indices, values = density.get("element_index"), density.get("w_per_kg")
    if not isinstance(indices, list) or not isinstance(values, list) or len(indices) != len(values) or not indices:
        return None
    if len(regions) != len(triangles):
        return None
    element: list[float | None] = [None] * len(triangles)
    for index, value in zip(indices, values):
        if not isinstance(index, int) or not 0 <= index < len(triangles):
            return None
        if not str(regions[index]).startswith("stator"):
            return None
        element[index] = float(value)
    return element, max(values)
