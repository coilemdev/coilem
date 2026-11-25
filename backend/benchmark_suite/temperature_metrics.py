"""Pre-registered native temperature-interpolation checks, not hardware gates."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

import numpy as np
from pydantic import Field

from backend.drive_performance import MapModel, torque_speed_envelope
from backend.flux_linkage_map import map_scope_key
from backend.loss_breakdown import operating_point_losses
from backend.models import DriveLimits, FluxLinkageMap, FluxLinkageMapPoint, IronLoss
from backend.models.thermal import ThermalInputs, ThermalModel
from backend.resources import data_file, package_resource
from backend.temperature_maps import TemperatureMapBracket, at_temperature, interpolate_temperature_map
from backend.thermal_network import thermal_estimate

# Frozen before native collection. Units/floors and the distinction from a
# physical thermal gate are documented in benchmarks/thermal-v0.6/README.md.
BAND_SPEC = json.loads(data_file("benchmarks/thermal-v0.6/map-interpolation-gates.json").read_text())["bands"]
BANDS = {name: (band["relative"], band["absolute_floor"]) for name, band in BAND_SPEC.items()}


def thermal_processing_identity():
    """Identity of thermal-only propagation; never invalidates native EM maps."""
    return {p: hashlib.sha256(package_resource(*p.split('/')).read_bytes()).hexdigest()
            for p in ('thermal_network.py', 'models/thermal.py', 'benchmark_suite/temperature_metrics.py',
                      'winding_resistance.py', 'loss_breakdown.py')}


def pass_band(name: str, reference: float, *, scale: float | None = None) -> float:
    """Frozen M3a PASS tolerance shared by interpolation and rating verification."""

    relative, floor = BANDS[name]
    return max(relative * abs(reference if scale is None else scale), floor)


class TemperatureReference(ThermalModel):
    temperature_C: float
    computation_scope_key: str
    points: list[FluxLinkageMapPoint] = Field(min_length=1)
    direct_map: FluxLinkageMap | None = None
    source: str = Field(min_length=1)


class InterpolationAcceptance(ThermalModel):
    status: Literal["PASS", "YELLOW", "FAIL", "NOT_COMPARED"]
    status_reason: str
    metrics: list[dict] = Field(default_factory=list)
    # PASS means agreement with direct native solves only. It never grants a
    # physical thermal or efficiency qualification.
    output_status: Literal["experimental"] = "experimental"


def _metric(name, predicted, reference, *, scale=None, context=""):
    tolerance = pass_band(name, reference, scale=scale)
    error = abs(predicted - reference)
    return dict(name=name, context=context, predicted=predicted, reference=reference,
                absolute_error=error, pass_band=tolerance,
                status="PASS" if error <= tolerance else "YELLOW" if error <= BAND_SPEC[name]["yellow_multiplier"] * tolerance else "FAIL")


def _values(model, current, gamma):
    return {key: float(value) for key, value in model.sample_points(np.array(current), np.array(gamma)).items()}


def _voltage(values, point, resistance, omega):
    return math.hypot(resistance * point.i_d_A - omega * values["lambda_q"],
                      resistance * point.i_q_A + omega * values["lambda_d"])


def _thermal_for_point(bracket, temperature, point, values, settings):
    config = at_temperature(bracket.design, temperature)
    config = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={
        "current_amplitude_A": point.current_peak_A, "current_amplitude_convention": "peak", "current_angle_deg": point.gamma_deg,
    })})
    iron = IronLoss(
        status="experimental", steel=config.materials.stator_steel,
        electrical_frequency_Hz=bracket.low.reference_speed_rpm * bracket.low.pole_pairs / 60,
        iron_loss_W=values["iron_h"] + values["iron_e"], iron_hysteresis_loss_W=values["iron_h"], iron_eddy_loss_W=values["iron_e"],
        stator_iron_mass_kg=1, validated_max_frequency_Hz=1000, validated_max_flux_density_T=1.5,
    )
    winding, losses = operating_point_losses(config, values["torque"], iron)
    if winding is None or losses is None:
        return None
    return thermal_estimate(config, settings, winding, losses, iron)


def check_temperature_interpolation(
    bracket: TemperatureMapBracket, references: list[TemperatureReference], *,
    limits: DriveLimits, phase_resistance_ohm: float, thermal_inputs: ThermalInputs,
    required_temperatures_C: tuple[float, ...] = (35.0, 50.0, 65.0),
    required_off_grid: tuple[tuple[float, float], ...] = ((0.375, 22.5), (0.875, 52.5), (0.875, 82.5)),
) -> InterpolationAcceptance:
    """Compare direct grid/off-grid solves, temperatures, voltage and envelopes.

    A complete result needs every requested temperature, off-grid point and
    direct map. Missing evidence stays NOT_COMPARED. A supplied failed metric
    is retained as FAIL even if another piece of evidence is missing.
    """

    if not math.isfinite(phase_resistance_ohm) or phase_resistance_ohm < 0:
        raise ValueError("Phase resistance must be finite and nonnegative")
    if not required_temperatures_C:
        raise ValueError("Acceptance needs pre-registered intermediate temperatures")
    temperatures = [reference.temperature_C for reference in references]
    if len(set(temperatures)) != len(temperatures):
        raise ValueError("Duplicate reference temperatures")
    metrics, missing = [], []
    for temperature in required_temperatures_C:
        if temperature not in temperatures:
            missing.append(f"direct reference at {temperature:g} C")
    for reference in references:
        temperature = reference.temperature_C
        expected_key = map_scope_key(at_temperature(bracket.design, temperature), bracket.preset)
        if reference.computation_scope_key != expected_key:
            raise ValueError("Direct reference computation identity does not match this design and temperature")
        predicted_map = interpolate_temperature_map(bracket, temperature).map
        model = MapModel.from_map(predicted_map)
        omega = bracket.low.reference_speed_rpm * 2 * math.pi / 60 * bracket.low.pole_pairs
        v_max = limits.modulation_index_max * limits.dc_bus_V / 2
        present = {(p.current_peak_A, p.gamma_deg) for p in reference.points}
        for fraction, gamma in required_off_grid:
            target = (fraction * bracket.low.current_peak_A[-1], gamma)
            if target not in present:
                missing.append(f"off-grid point {target} at {temperature:g} C")
        for point in reference.points:
            context = f"T={temperature:g}, I={point.current_peak_A:g}, gamma={point.gamma_deg:g}"
            if point.status != "ok":
                metrics.append(dict(name="direct_point", context=context, status="FAIL"))
                continue
            if not (0 <= point.current_peak_A <= model.currents_A[-1] and model.gammas_deg[0] <= point.gamma_deg <= model.gammas_deg[-1]):
                raise ValueError("Direct reference point lies outside the bracket grids")
            values = _values(model, point.current_peak_A, point.gamma_deg)
            actual = dict(torque=point.avg_torque_Nm, lambda_d=point.lambda_d_Wb, lambda_q=point.lambda_q_Wb,
                          iron_h=point.iron_hysteresis_loss_W, iron_e=point.iron_eddy_loss_W)
            flux_scale = math.hypot(point.lambda_d_Wb, point.lambda_q_Wb)
            metrics += [_metric(name, values[name], actual[name], scale=flux_scale, context=context) for name in ("lambda_d", "lambda_q")]
            metrics.append(_metric("torque", values["torque"], actual["torque"], context=context))
            predicted_voltage = _voltage(values, point, phase_resistance_ohm, omega)
            actual_voltage = _voltage(actual, point, phase_resistance_ohm, omega)
            metrics.append(_metric("voltage", predicted_voltage, actual_voltage, context=context))
            metrics.append(dict(name="voltage_feasibility", context=context,
                                status="PASS" if (predicted_voltage <= v_max) == (actual_voltage <= v_max) else "FAIL"))
            if not model.iron_loss_available or actual["iron_h"] is None or actual["iron_e"] is None:
                missing.append(f"iron loss for {context}")
                continue
            metrics.append(_metric("iron_loss", values["iron_h"] + values["iron_e"], actual["iron_h"] + actual["iron_e"], context=context))
            if min(values["iron_h"], values["iron_e"]) < 0:
                metrics.append(dict(name="nonnegative_loss", context=context, status="FAIL"))
                continue
            predicted_thermal = _thermal_for_point(bracket, temperature, point, values, thermal_inputs)
            direct_thermal = _thermal_for_point(bracket, temperature, point, actual, thermal_inputs)
            if any(item is None or item.status == "unavailable" for item in (predicted_thermal, direct_thermal)):
                missing.append(f"thermal comparison for {context}")
            else:
                for node in ("winding", "end_winding", "teeth", "yoke", "housing"):
                    metrics.append(_metric("temperature", predicted_thermal.nodes[node].temperature_C,
                                           direct_thermal.nodes[node].temperature_C, context=f"{context}, node={node}"))
        if reference.direct_map is None:
            missing.append(f"full direct map for field-weakening check at {temperature:g} C")
        else:
            direct = reference.direct_map
            if (direct.scope_key != expected_key or direct.magnet_temperature_C != temperature
                    or direct.current_peak_A != bracket.low.current_peak_A or direct.gamma_deg != bracket.low.gamma_deg):
                raise ValueError("Direct comparison map does not match the registered temperature and grids")
            curves = [torque_speed_envelope(item, limits, phase_resistance_ohm=phase_resistance_ohm,
                                           winding_temperature_C=20).curves[0] for item in (predicted_map, direct)]
            metrics.append(_metric("base_speed", curves[0].base_speed_rpm, curves[1].base_speed_rpm, context=f"T={temperature:g}"))
            metrics.append(_metric("max_speed", curves[0].max_speed_rpm, curves[1].max_speed_rpm, context=f"T={temperature:g}"))
            if not any(region == "field_weakening" for region in curves[1].region):
                missing.append(f"drive limits that exercise field weakening at {temperature:g} C")
    statuses = {metric["status"] for metric in metrics}
    status = "FAIL" if "FAIL" in statuses else "NOT_COMPARED" if missing else "YELLOW" if "YELLOW" in statuses else "PASS"
    if status == "FAIL":
        reason = "Native interpolation failed a registered comparison; derived and coupled outputs remain experimental."
    elif status == "YELLOW":
        reason = "Native interpolation reached a yellow band; derived and coupled outputs remain experimental."
    else:
        reason = "Native interpolation agreement only; not thermal or efficiency qualification."
    if missing:
        reason += " Missing evidence: " + "; ".join(missing)
    return InterpolationAcceptance(status=status, status_reason=reason, metrics=metrics)
