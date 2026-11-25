"""Steady-state EM/thermal coupling and constrained torque search (#22)."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import Field

from backend.benchmark_suite.temperature_metrics import InterpolationAcceptance, pass_band
from backend.drive_performance import MapModel
from backend.flux_linkage_map import point_config
from backend.loss_breakdown import operating_point_losses
from backend.models import DriveLimits, IronLoss
from backend.models.thermal import ThermalInputs, ThermalModel, ThermalResult
from backend.solver_contract import SolveCancelledError
from backend.temperature_maps import TemperatureMapBracket, at_temperature, interpolate_temperature_map
from backend.thermal_network import thermal_estimate


class CouplingSettings(ThermalModel):
    tolerance_K: float = Field(default=0.1, gt=0, le=5)
    max_iterations: int = Field(default=50, ge=1, le=500)
    relaxation: float = Field(default=0.5, gt=0, le=1)


class CoupledPoint(ThermalModel):
    status: Literal["experimental", "unavailable"]
    status_reason: str
    speed_rpm: float
    current_peak_A: float
    gamma_deg: float
    torque_Nm: float | None = None
    phase_voltage_peak_V: float | None = None
    winding_temperature_C: float | None = None
    magnet_temperature_C: float | None = None
    thermal: ThermalResult | None = None
    iterations: int = 0
    temperature_residual_K: float | None = None
    relaxation: float
    temperature_history: list[dict] = Field(default_factory=list)
    copper_loss_W: float | None = None
    iron_loss_W: float | None = None
    verification_status: Literal["PASS", "FAIL", "NOT_COMPARED"] = "NOT_COMPARED"
    verification_reason: str = "Final operating point has not been re-solved directly."
    verification_metrics: dict[str, float] = Field(default_factory=dict)


class ThermalRatingPoint(ThermalModel):
    speed_rpm: float
    status: Literal["experimental", "unavailable"]
    status_reason: str
    limiting_constraint: str
    point: CoupledPoint | None = None
    user_magnet_case: CoupledPoint | None = None


class ThermalRating(ThermalModel):
    kind: Literal["thermally_limited_rating"] = "thermally_limited_rating"
    status: Literal["experimental"] = "experimental"
    status_reason: str
    inputs: ThermalInputs
    limits: DriveLimits
    coupling: CouplingSettings
    control: Literal["mtpa", "least_loss"]
    source_scope_keys: tuple[str, str]
    points: list[ThermalRatingPoint]
    acceptance_status: str = "NOT_COMPARED"
    cancelled: bool = False
    notes: list[str] = Field(default_factory=list)


def coupled_point(
    bracket: TemperatureMapBracket, inputs: ThermalInputs, *, speed_rpm: float,
    current_peak_A: float, gamma_deg: float, settings: CouplingSettings | None = None,
    fixed_magnet_C: float | None = None, should_stop=lambda: False,
) -> CoupledPoint:
    """No FEM in the fixed-point loop; outside-bracket temperatures are explicit."""

    settings = settings or CouplingSettings()
    history = []
    base = dict(speed_rpm=speed_rpm, current_peak_A=current_peak_A, gamma_deg=gamma_deg,
                relaxation=settings.relaxation)

    def unavailable(reason, thermal=None):
        return CoupledPoint(**base, status="unavailable", status_reason=reason,
            thermal=thermal, iterations=len(history), temperature_history=history,
            temperature_residual_K=history[-1]["residual_K"] if history else None)

    if (not all(math.isfinite(value) for value in (speed_rpm, current_peak_A, gamma_deg))
            or speed_rpm < 0 or not 0 <= current_peak_A <= bracket.low.current_peak_A[-1]
            or not bracket.low.gamma_deg[0] <= gamma_deg <= bracket.low.gamma_deg[-1]):
        return unavailable("Operating point outside the speed/current/angle domain.")
    winding_T = inputs.ambient_C
    magnet_T = fixed_magnet_C if fixed_magnet_C is not None else min(max(inputs.ambient_C,
        bracket.low.magnet_temperature_C), bracket.high.magnet_temperature_C)
    last_residual = math.inf
    growing = 0
    for iteration in range(1, settings.max_iterations + 1):
        if should_stop():
            return unavailable("Thermal calculation cancelled.")
        try:
            interpolated = interpolate_temperature_map(bracket, magnet_T)
            model = MapModel.from_map(interpolated.map)
            values = {name: float(value) for name, value in model.sample_points(np.array(current_peak_A), np.array(gamma_deg)).items()}
            if not model.iron_loss_available or min(values["iron_h"], values["iron_e"]) < 0:
                return unavailable("Stator iron-loss data unavailable or interpolated loss is negative.")
            ratio = speed_rpm / model.reference_frequency_Hz * model.pole_pairs / 60
            iron_h, iron_e = values["iron_h"] * ratio, values["iron_e"] * ratio**2
            config = at_temperature(bracket.design, magnet_T)
            config = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={
                "rated_speed_rpm": int(round(speed_rpm)), "current_amplitude_A": current_peak_A,
                "current_amplitude_convention": "peak", "current_angle_deg": gamma_deg, "winding_temperature_C": winding_T,
            })})
            # Ephemeral adapter for the existing loss allocator: maps retain
            # watt totals, not mass/material validation provenance. The required
            # placeholder mass/caps are never copied into CoupledPoint/ThermalResult.
            iron = IronLoss(status="experimental", steel=config.materials.stator_steel,
                electrical_frequency_Hz=model.reference_frequency_Hz, iron_loss_W=iron_h + iron_e,
                iron_hysteresis_loss_W=iron_h, iron_eddy_loss_W=iron_e, stator_iron_mass_kg=1,
                validated_max_frequency_Hz=1000, validated_max_flux_density_T=1.5)
            winding, losses = operating_point_losses(config, values["torque"], iron)
            if winding is None or losses is None:
                return unavailable("Winding resistance or loss inputs are unavailable.")
            thermal = thermal_estimate(config, inputs, winding, losses, iron, with_copper_feedback=True)
            if thermal.status == "unavailable":
                return unavailable(thermal.status_reason, thermal)
            new_winding = thermal.nodes["winding"].temperature_C
            new_magnet = thermal.nodes["magnets"].temperature_C
            if new_magnet is None and fixed_magnet_C is None:
                return unavailable(thermal.nodes["magnets"].status_reason, thermal)
            target_magnet = fixed_magnet_C if fixed_magnet_C is not None else new_magnet
            residual = max(abs(new_winding - winding_T), abs(target_magnet - magnet_T))
            history.append(dict(iteration=iteration, winding_C=new_winding, magnet_C=new_magnet, residual_K=residual))
            if max(new_winding, target_magnet) > 1000 or (iteration > 6 and residual > last_residual * 1.2):
                growing += 1
            else:
                growing = 0
            if growing >= 3 or max(new_winding, target_magnet) > 1000:
                return unavailable("No stable thermal equilibrium: temperature growth/runaway through R(T).", thermal)
            if residual <= settings.tolerance_K:
                angle = math.radians(gamma_deg)
                i_d, i_q = -current_peak_A * math.sin(angle), current_peak_A * math.cos(angle)
                omega = speed_rpm * 2 * math.pi / 60 * model.pole_pairs
                resistance = thermal.copper_feedback.phase_resistance_ohm
                voltage = math.hypot(resistance * i_d - omega * values["lambda_q"],
                                     resistance * i_q + omega * values["lambda_d"])
                return CoupledPoint(**base, status="experimental",
                    status_reason="Coupled experimental estimate under entered heat assumptions. Rotor/magnet internal losses are not calculated; "
                                  "temperatures and margins omit their unknown contribution.",
                    torque_Nm=values["torque"], phase_voltage_peak_V=voltage,
                    winding_temperature_C=new_winding, magnet_temperature_C=target_magnet,
                    thermal=thermal, iterations=iteration, temperature_residual_K=residual,
                    temperature_history=history, copper_loss_W=thermal.copper_feedback.copper_loss_W, iron_loss_W=iron_h + iron_e)
            winding_T += settings.relaxation * (new_winding - winding_T)
            magnet_T += settings.relaxation * (target_magnet - magnet_T)
            last_residual = residual
        except (ValueError, KeyError) as exc:
            return unavailable(str(exc))
    return unavailable("Thermal iteration failed to converge within its iteration limit.")


def _constraints(point: CoupledPoint, limits: DriveLimits):
    if point.status == "unavailable":
        return [point.status_reason]
    violated = []
    if point.phase_voltage_peak_V > limits.dc_bus_V * limits.modulation_index_max / 2:
        violated.append("voltage")
    for name in ("winding", "end_winding", "magnets"):
        node = point.thermal.nodes[name]
        margin = node.limit_C - point.magnet_temperature_C if name == "magnets" and node.limit_C is not None else node.margin_K
        if margin is None:
            violated.append("missing temperature limit: " + name)
        elif margin < 0:
            violated.append("temperature: " + name)
    return violated


def thermal_rating(
    bracket: TemperatureMapBracket, inputs: ThermalInputs, limits: DriveLimits, *,
    coupling: CouplingSettings | None = None, control: Literal["mtpa", "least_loss"] = "mtpa",
    speed_samples: int = 13, current_samples: int = 9, angle_samples: int = 10,
    user_magnet_C: float | None = None, acceptance: InterpolationAcceptance | None = None,
    direct_solve=None, should_stop=lambda: False, progress=None,
) -> ThermalRating:
    """Greatest feasible sampled torque, with three local grid refinements.

    This is a bounded numerical search, not a proof of a global optimum. At a
    torque tie, MTPA selects lower current; least-loss selects lower losses.
    Every final point can be re-solved directly, outside the coupling loop.
    """

    if control not in ("mtpa", "least_loss") or min(speed_samples, current_samples, angle_samples) < 2:
        raise ValueError("Invalid control strategy or search grid")
    coupling = coupling or CouplingSettings()
    current_caps = {"drive peak": limits.peak_current_A, "map domain": bracket.low.current_peak_A[-1]}
    if limits.continuous_current_A is not None:
        current_caps["drive continuous"] = limits.continuous_current_A
    cap = min(current_caps.values())
    current_limit = "current: " + " + ".join(name for name, value in current_caps.items() if value == cap)
    rows = []
    cancelled = False
    # The native motor contract uses integer rpm. Search and report the same
    # bounded integer speeds that final direct verification will solve.
    speeds = [float(min(math.floor(limits.max_speed_rpm), round(speed)))
              for speed in np.linspace(0, limits.max_speed_rpm, speed_samples)]
    for index, rpm in enumerate(speeds):
        if should_stop():
            cancelled = True
            rows.extend(ThermalRatingPoint(speed_rpm=float(speed), status="unavailable",
                status_reason="Thermal rating cancelled.", limiting_constraint="cancelled")
                for speed in speeds[index:])
            break
        feasible, failures = [], []
        cache = {}

        def evaluate(current, gamma):
            key = (round(float(current), 8), round(float(gamma), 8))
            if key in cache:
                return cache[key]
            point = coupled_point(bracket, inputs, speed_rpm=float(rpm), current_peak_A=key[0], gamma_deg=key[1],
                                  settings=coupling, should_stop=should_stop)
            cache[key] = point
            problems = _constraints(point, limits)
            if problems:
                failures.extend(problems)
            elif point.torque_Nm > 1e-9:
                feasible.append(point)
            return point

        for current in np.linspace(0, cap, current_samples):
            for gamma in np.linspace(bracket.low.gamma_deg[0], bracket.low.gamma_deg[-1], angle_samples):
                evaluate(current, gamma)
        dc, da = cap / (current_samples - 1), (bracket.low.gamma_deg[-1] - bracket.low.gamma_deg[0]) / (angle_samples - 1)

        def score(point):
            tie = -(point.copper_loss_W + point.iron_loss_W) if control == "least_loss" else -point.current_peak_A
            return (round(point.torque_Nm, 6), tie)

        for _ in range(3):
            if not feasible:
                break
            best = max(feasible, key=score)
            for current in np.linspace(max(0, best.current_peak_A - dc), min(cap, best.current_peak_A + dc), 5):
                for gamma in np.linspace(max(bracket.low.gamma_deg[0], best.gamma_deg - da), min(bracket.low.gamma_deg[-1], best.gamma_deg + da), 5):
                    evaluate(current, gamma)
            dc /= 2
            da /= 2
        if not feasible:
            reason = "; ".join(dict.fromkeys(failures)) or "No positive feasible torque in the sampled domain."
            rows.append(ThermalRatingPoint(speed_rpm=float(rpm), status="unavailable", status_reason=reason, limiting_constraint=reason))
        else:
            best = max(feasible, key=score)
            # Name the closest active constraint in normalized headroom units.
            margins = {current_limit: (cap - best.current_peak_A) / max(cap, 1e-9),
                       "voltage": 1 - best.phase_voltage_peak_V / (limits.dc_bus_V * limits.modulation_index_max / 2)}
            for name in ("winding", "end_winding", "magnets"):
                node = best.thermal.nodes[name]
                margins["temperature: " + name] = node.margin_K / max(abs(node.limit_C - inputs.ambient_C), 1)
            limiting = min(margins, key=margins.get)
            if direct_solve is not None:
                try:
                    verify_limiting_point(bracket, inputs, limits, best, direct_solve)
                except SolveCancelledError:
                    # A cancel during the direct check ends the rating as a cancel between speeds does.
                    cancelled = True
                    rows.extend(ThermalRatingPoint(speed_rpm=float(speed), status="unavailable",
                        status_reason="Thermal rating cancelled.", limiting_constraint="cancelled")
                        for speed in speeds[index:])
                    break
            sensitivity = None if user_magnet_C is None else coupled_point(bracket, inputs, speed_rpm=float(rpm),
                current_peak_A=best.current_peak_A, gamma_deg=best.gamma_deg, settings=coupling, fixed_magnet_C=user_magnet_C)
            rows.append(ThermalRatingPoint(speed_rpm=float(rpm), status=best.status, status_reason=best.status_reason,
                                           limiting_constraint=limiting, point=best, user_magnet_case=sensitivity))
        if progress:
            progress(index + 1, speed_samples)
    acceptance_status = acceptance.status if acceptance else "NOT_COMPARED"
    acceptance_reason = acceptance.status_reason if acceptance else "Native interpolation evidence has not been collected for this bracket."
    failed_bands = sorted({str(metric.get("name")) for metric in acceptance.metrics if metric.get("status") == "FAIL"}) if acceptance else []
    if failed_bands:
        acceptance_reason += " Failed bands: " + ", ".join(failed_bands) + "."
    return ThermalRating(inputs=inputs, limits=limits, coupling=coupling, control=control,
        source_scope_keys=(bracket.low.scope_key, bracket.high.scope_key), points=rows,
        acceptance_status=acceptance_status, cancelled=cancelled,
        status_reason=(f"Experimental: weakest thermal/magnet inputs are unqualified; native interpolation acceptance: {acceptance_status}. "
                       + acceptance_reason + " Rotor/magnet internal losses are not calculated; "
                       "this rating applies only to the entered heat assumptions."),
        notes=["Search grid with local refinement; global optimality is not certified.",
               "Continuous means thermally limited under the stated cooling, not a measured motor rating.",
               "Rotor/magnet temperatures include heat transfer and any supplied heat, with no calculated rotor/magnet internal losses. "
               "Omitted losses can reduce the predicted rating.",
               "Temperature outside brackets is unsupported; no FEM is performed inside the coupling loop.",
               "Final direct verification is NOT_COMPARED unless a native solver was supplied."])


def verify_limiting_point(bracket, inputs, limits, point, solve):
    """Direct FEM at the converged temperatures, with fixed pre-registered bands."""

    try:
        config = at_temperature(bracket.design, point.magnet_temperature_C)
        config = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={
            "rated_speed_rpm": int(round(point.speed_rpm)), "winding_temperature_C": point.winding_temperature_C,
        })})
        config = point_config(config, point.current_peak_A, point.gamma_deg, bracket.preset)
        result = solve(config)
        summary = result.summary
        direct_iron = summary.iron_loss
        if point.speed_rpm == 0:
            direct_iron = IronLoss(status="experimental", steel=config.materials.stator_steel,
                electrical_frequency_Hz=bracket.low.reference_speed_rpm * bracket.low.pole_pairs / 60,
                iron_loss_W=0, iron_hysteresis_loss_W=0, iron_eddy_loss_W=0, stator_iron_mass_kg=1,
                validated_max_frequency_Hz=1000, validated_max_flux_density_T=1.5)
        winding, losses = operating_point_losses(config, summary.avg_torque_Nm, direct_iron)
        if winding is None or losses is None:
            raise ValueError("Direct solve has no usable winding/loss record")
        thermal = thermal_estimate(config, inputs, winding, losses, direct_iron, with_copper_feedback=True)
        if thermal.status == "unavailable":
            raise ValueError(thermal.status_reason)
        failures = []
        dq = summary.dq_flux_linkage
        if dq is None:
            raise ValueError("Direct solve has no d/q flux linkage")
        predicted = MapModel.from_map(interpolate_temperature_map(bracket, point.magnet_temperature_C).map).sample_points(
            np.array(point.current_peak_A), np.array(point.gamma_deg))
        flux_scale = math.hypot(dq.lambda_d_Wb, dq.lambda_q_Wb)
        for name in ("lambda_d", "lambda_q"):
            if abs(float(predicted[name]) - getattr(dq, name + "_Wb")) > pass_band(name, getattr(dq, name + "_Wb"), scale=flux_scale):
                failures.append(name)
        omega = point.speed_rpm * 2 * math.pi / 60 * bracket.low.pole_pairs
        resistance = thermal.copper_feedback.phase_resistance_ohm
        voltage = math.hypot(resistance * dq.i_d_A - omega * dq.lambda_q_Wb,
                             resistance * dq.i_q_A + omega * dq.lambda_d_Wb)
        if abs(voltage - point.phase_voltage_peak_V) > pass_band("voltage", voltage):
            failures.append("voltage")
        violations = []
        if voltage > limits.dc_bus_V * limits.modulation_index_max / 2:
            violations.append("voltage limit")
        for name in ("winding", "end_winding", "magnets"):
            node = thermal.nodes[name]
            if node.margin_K is None or node.margin_K < 0:
                violations.append("temperature limit: " + name)
        point.verification_metrics = dict(torque_Nm=summary.avg_torque_Nm, phase_voltage_peak_V=voltage,
                                           iron_loss_W=losses.iron_loss_W, winding_temperature_C=thermal.nodes["winding"].temperature_C)
        if violations:
            point.status = "unavailable"
            # Each limit in its own words: a voltage is needed, a part's temperature is passed.
            hot = " and ".join(name.removeprefix("temperature limit: ").replace("_", " ")
                               for name in violations if name != "voltage limit")
            crossed = [*(["needs more voltage than the drive limit allows"] if "voltage limit" in violations else []),
                       *([f"puts the {hot} past the temperature limit"] if hot else [])]
            point.status_reason = (f"A direct solve at this point {' and '.join(crossed)}, "
                                   "so the value read from the maps is not reported.")
            failures.extend(violations)
        if abs(summary.avg_torque_Nm - point.torque_Nm) > pass_band("torque", summary.avg_torque_Nm):
            failures.append("torque")
        if abs(losses.iron_loss_W - point.iron_loss_W) > pass_band("iron_loss", losses.iron_loss_W):
            failures.append("iron loss")
        for name in ("winding", "end_winding", "teeth", "yoke", "housing", "mount"):
            if name not in thermal.nodes:
                continue  # housing for an inner rotor, mount for an outer one
            error = abs(thermal.nodes[name].temperature_C - point.thermal.nodes[name].temperature_C)
            if error > pass_band("temperature", thermal.nodes[name].temperature_C):
                failures.append("temperature: " + name)
        point.verification_status = "FAIL" if failures else "PASS"
        point.verification_reason = "Direct limiting-point comparison: " + (", ".join(failures) if failures else "within registered bands")
        differing = [name for name in failures if name not in violations]
        if differing:
            point.status_reason += " The direct solve differs from the maps beyond the registered band in: " + ", ".join(differing) + "."
    except SolveCancelledError:
        raise  # A cancel stops the rating; it is not a failed check of this speed.
    except (ValueError, KeyError, RuntimeError) as exc:
        # A speed whose direct check cannot run is not confirmed, so it is not a
        # result: it leaves the curve with the exception as its reason.
        detail = str(exc).strip() or type(exc).__name__
        point.status = "unavailable"
        point.status_reason = (f"A direct solve at this point could not run ({detail}), "
                               "so the value read from the maps is not reported.")
        point.verification_status = "FAIL"
        point.verification_reason = "Direct limiting-point solve failed: " + detail
