"""Temperature-bracketed maps (#21); derived estimates, never extrapolated solves."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from backend.flux_linkage_map import MapPreset, MapStore, Solve, map_scope_key, run_flux_linkage_map
from backend.magnet_temperature import br_scale, magnet_temperature_unavailable_reason
from backend.models import FluxLinkageMap, MotorConfig
from backend.models.thermal import ThermalModel

INTERPOLATION_REASON = (
    "Experimental: linearly interpolated between two solved magnet-temperature maps. "
    "Saturation can make torque and iron loss nonlinear in temperature; reference acceptance is recorded separately."
)


class TemperatureMapBracket(ThermalModel):
    design: MotorConfig
    preset: Literal["preview", "standard"]
    low: FluxLinkageMap
    high: FluxLinkageMap

    @model_validator(mode="after")
    def verify_compatible_solved_brackets(self):
        grade = self.design.materials.magnet_grade
        lo, hi = self.low.magnet_temperature_C, self.high.magnet_temperature_C
        if lo is None or hi is None or not lo < hi:
            raise ValueError("Temperature brackets need explicit, strictly increasing temperatures")
        for temperature, flux_map in ((lo, self.low), (hi, self.high)):
            reason = magnet_temperature_unavailable_reason(grade, temperature)
            if reason:
                raise ValueError(reason)
            config = at_temperature(self.design, temperature)
            if flux_map.scope_key != map_scope_key(config, self.preset):
                raise ValueError("Bracket map does not match this design, numerical settings and computation identity")
            if len(flux_map.points) != len(flux_map.current_peak_A) * len(flux_map.gamma_deg):
                raise ValueError("Temperature brackets require every grid point")
            if any(point.status != "ok" for point in flux_map.points):
                raise ValueError("Temperature brackets require complete, successfully solved maps")
            for point in flux_map.points:
                if any(not math.isfinite(getattr(point, name)) for name in ("avg_torque_Nm", "lambda_d_Wb", "lambda_q_Wb")):
                    raise ValueError("Bracket values must be finite")
        for name in ("current_peak_A", "gamma_deg", "pole_pairs", "reference_speed_rpm", "mesh_density", "torque_method"):
            if getattr(self.low, name) != getattr(self.high, name):
                raise ValueError(f"Temperature bracket maps have incompatible {name}")
        return self


class InterpolatedTemperatureMap(ThermalModel):
    status: Literal["experimental"] = "experimental"
    status_reason: str = INTERPOLATION_REASON
    temperature_C: float
    br_weight: float = Field(ge=0, le=1)
    source_scope_keys: tuple[str, str]
    map: FluxLinkageMap


def at_temperature(config: MotorConfig, temperature_C: float) -> MotorConfig:
    """The design at one magnet temperature, as every thermal-only solve uses it.

    Bracket maps, their validation, rating verification solves and the
    interpolation evidence all take their solves and cache identities from
    here. The heat-transfer model uses stator iron loss only, and a rotor
    iron-loss record cannot be interpolated between temperatures, so rotor
    iron loss is turned off: otherwise a source design that selects it pays a
    full rotor turn per map point for a record that is dropped. A design
    without it keeps the same solve options, so its scope keys are unchanged.
    """

    if config.solve_params is None:
        raise ValueError("Temperature maps need solve settings")
    update = {"solve_params": config.solve_params.model_copy(update={"magnet_temperature_C": temperature_C})}
    if config.solve_options is not None and config.solve_options.rotor_iron_loss:
        update["solve_options"] = config.solve_options.model_copy(update={"rotor_iron_loss": False})
    return config.model_copy(update=update)


def solve_temperature_bracket(
    design: MotorConfig, low_C: float, high_C: float, *, peak_current_A: float,
    solve: Solve, store_root: Path, preset: MapPreset = "preview", should_stop=lambda: False, progress=None,
) -> TemperatureMapBracket:
    """Two ordinary resumable map jobs; no solver is called during interpolation.

    ``progress(map_index, done, total)`` is called as each point of a map is
    settled: index 0 is the cold map, 1 the hot one. A point already stored is
    not solved again but still counts, so a resumed job reports its place.
    """

    if not math.isfinite(low_C) or not math.isfinite(high_C) or low_C >= high_C:
        raise ValueError("Temperature brackets must be finite and strictly increasing")
    for temperature in (low_C, high_C):
        reason = magnet_temperature_unavailable_reason(design.materials.magnet_grade, temperature)
        if reason:
            raise ValueError(reason)
    maps = []
    for index, temperature in enumerate((low_C, high_C)):
        config = at_temperature(design, temperature)
        store = MapStore(store_root, map_scope_key(config, preset))
        report = (lambda done, total, point, eta, index=index: progress(index, done, total)) if progress else None
        maps.append(run_flux_linkage_map(config, solve=solve, peak_current_A=peak_current_A,
                                        preset=preset, store=store, should_stop=should_stop, progress=report))
    return TemperatureMapBracket(design=design, preset=preset, low=maps[0], high=maps[1])


def interpolate_temperature_map(bracket: TemperatureMapBracket, temperature_C: float) -> InterpolatedTemperatureMap:
    """Interpolate in Br scale, retain endpoints, and use a separate derived identity.

    Derived maps must not occupy a solved-map cache namespace. Convergence and
    rotor-ripple diagnostics are not manufactured for an unsolved temperature.
    """

    low, high = bracket.low, bracket.high
    lo, hi = low.magnet_temperature_C, high.magnet_temperature_C
    if not math.isfinite(temperature_C):
        raise ValueError("The magnet temperature must be finite. Values are never extrapolated.")
    if not lo <= temperature_C <= hi:
        boundary = "below the cold map" if temperature_C < lo else "above the hot map"
        raise ValueError(f"The magnets would run {boundary}. Their estimated temperature is {temperature_C:.4g} C "
                         f"and the solved range is {lo:g} to {hi:g} C. Values are never extrapolated.")
    grade = bracket.design.materials.magnet_grade
    weight = (br_scale(grade, temperature_C) - br_scale(grade, lo)) / (br_scale(grade, hi) - br_scale(grade, lo))
    weight = min(1.0, max(0.0, weight))
    points = []
    high_points = {(point.current_peak_A, point.gamma_deg): point for point in high.points}
    for first in low.points:
        second = high_points[(first.current_peak_A, first.gamma_deg)]
        update = {}
        for name in ("avg_torque_Nm", "lambda_d_Wb", "lambda_q_Wb", "iron_loss_W", "iron_hysteresis_loss_W", "iron_eddy_loss_W"):
            a, b = getattr(first, name), getattr(second, name)
            update[name] = (1 - weight) * a + weight * b if a is not None and b is not None else None
        # A rotor iron loss record belongs to one solved field history (its hash,
        # sampling plan and status), so it cannot be interpolated between two
        # temperatures. The derived point carries none, and bracket maps solved
        # through at_temperature() never request one.
        update.update(torque_ripple_pct=None, nonlinear_iterations_max=None, nonlinear_residual_max=None,
                      rotor_iron_loss=None)
        points.append(first.model_copy(update=update))
    identity = dict(kind="temperature_interpolation/v1", low=low.scope_key, high=high.scope_key,
                    temperature_C=temperature_C, processing_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    scope_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    derived = low.model_copy(update=dict(scope_key=scope_key, magnet_temperature_C=temperature_C, points=points))
    return InterpolatedTemperatureMap(temperature_C=temperature_C, br_weight=weight,
                                      source_scope_keys=(low.scope_key, high.scope_key), map=derived)
