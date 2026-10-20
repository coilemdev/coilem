"""Torque–speed envelope and efficiency map from a flux-linkage map (#140, #141).

Every number here is read off the map by Catmull-Rom (cubic) interpolation
over its (|I|, γ) grid; nothing is extrapolated from a single operating point
or beyond the map's currents and angles. The
map's FEM torque gives the torque; its loaded λd and λq give the voltage:

    v_d = R·i_d − ω_e·λ_q,    v_q = R·i_q + ω_e·λ_d,    |v| ≤ m·V_dc / 2

with amplitude-invariant peak quantities, so |v| is the peak phase voltage.
The steady state is sinusoidal current; inverter drops, dead time and the
voltage of the iron-loss resistance are ignored.

At each speed the envelope is the largest torque over current angles, with the
current at its limit unless the voltage limit stops it lower. Along a ray of
fixed γ inside (−90°, 90°) the torque rises with the current, so the best
point on each ray is its largest feasible current, found to the voltage
boundary by interpolation. The torques are electromagnetic, as the solve
reports them; the losses follow backend/loss_breakdown.py:

    P_in = T·ω + P_copper,    P_shaft = T·ω − P_iron − P_mech

with copper loss 1.5·R·I² for a peak current I, and iron loss scaled from the
map's reference speed with hysteresis ∝ f and eddy current ∝ f².
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from backend.models.performance import (
    DriveLimits,
    EfficiencyMap,
    FluxLinkageMap,
    TorqueSpeedCurve,
    TorqueSpeedEnvelope,
)

_ANGLE_STEP_DEG = 0.1
_CURRENT_SAMPLES = 401
_MAP_ANGLE_STEP_DEG = 0.1
_MAP_CURRENT_SAMPLES = 201
_BOUNDARY = 1.0 - 1e-6


@dataclass(frozen=True)
class MapModel:
    """The map's points as matrices over (current, angle), with cubic lookup."""

    pole_pairs: int
    currents_A: np.ndarray
    gammas_deg: np.ndarray
    torque_Nm: np.ndarray
    lambda_d_Wb: np.ndarray
    lambda_q_Wb: np.ndarray
    iron_hysteresis_W: np.ndarray
    iron_eddy_W: np.ndarray
    iron_loss_available: bool
    reference_frequency_Hz: float

    @classmethod
    def from_map(cls, flux_map: FluxLinkageMap) -> "MapModel":
        currents = np.asarray(flux_map.current_peak_A, dtype=float)
        gammas = np.asarray(flux_map.gamma_deg, dtype=float)
        if currents.size < 2 or gammas.size < 2:
            raise ValueError("the map needs at least two currents and two current angles")
        shape = (currents.size, gammas.size)
        grids = {name: np.full(shape, np.nan) for name in ("torque", "ld", "lq", "fh", "fe")}
        row = {value: index for index, value in enumerate(flux_map.current_peak_A)}
        column = {value: index for index, value in enumerate(flux_map.gamma_deg)}
        for point in flux_map.points:
            if point.status != "ok":
                continue
            at = (row[point.current_peak_A], column[point.gamma_deg])
            grids["torque"][at] = point.avg_torque_Nm
            grids["ld"][at] = point.lambda_d_Wb
            grids["lq"][at] = point.lambda_q_Wb
            if point.iron_hysteresis_loss_W is not None and point.iron_eddy_loss_W is not None:
                grids["fh"][at] = point.iron_hysteresis_loss_W
                grids["fe"][at] = point.iron_eddy_loss_W
        missing = int(np.isnan(grids["torque"]).sum())
        if missing:
            raise ValueError(f"{missing} of {grids['torque'].size} map points have no solved result")
        iron_available = not np.isnan(grids["fh"]).any()
        if not iron_available:
            grids["fh"][:] = 0.0
            grids["fe"][:] = 0.0
        return cls(
            pole_pairs=flux_map.pole_pairs,
            currents_A=currents,
            gammas_deg=gammas,
            torque_Nm=grids["torque"],
            lambda_d_Wb=grids["ld"],
            lambda_q_Wb=grids["lq"],
            iron_hysteresis_W=grids["fh"],
            iron_eddy_W=grids["fe"],
            iron_loss_available=iron_available,
            reference_frequency_Hz=flux_map.reference_speed_rpm * flux_map.pole_pairs / 60.0,
        )

    def sample(self, currents_A: np.ndarray, gammas_deg: np.ndarray) -> dict[str, np.ndarray]:
        """Interpolated values on the outer grid currents × angles, clamped to the map."""

        currents = np.asarray(currents_A, dtype=float)[:, None]
        gammas = np.asarray(gammas_deg, dtype=float)[None, :]
        shape = np.broadcast_shapes(currents.shape, gammas.shape)
        return self.sample_points(np.broadcast_to(currents, shape), np.broadcast_to(gammas, shape))

    def sample_points(self, currents_A: np.ndarray, gammas_deg: np.ndarray) -> dict[str, np.ndarray]:
        """Interpolated values at paired (current, angle) points of any matching shape."""

        currents = np.asarray(currents_A, dtype=float)
        gammas = np.asarray(gammas_deg, dtype=float)
        out = {}
        for name, grid in (
            ("torque", self.torque_Nm), ("lambda_d", self.lambda_d_Wb), ("lambda_q", self.lambda_q_Wb),
            ("iron_h", self.iron_hysteresis_W), ("iron_e", self.iron_eddy_W),
        ):
            out[name] = _interpolate(self.currents_A, self.gammas_deg, grid, currents, gammas)
        return out


def _cubic_weights(axis: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Four node indices into the padded axis and Catmull-Rom weights per value.

    Treats the axis steps as even, which the map runner's grids are. Unlike
    linear interpolation, the result has a continuous slope, so a maximum
    over the current angle can fall between the map's angles.
    """

    clipped = np.clip(values, axis[0], axis[-1])
    base = np.clip(np.searchsorted(axis, clipped, side="right") - 1, 0, axis.size - 2)
    t = (clipped - axis[base]) / (axis[base + 1] - axis[base])
    t2, t3 = t * t, t * t * t
    weights = np.stack([(-t3 + 2 * t2 - t) / 2, (3 * t3 - 5 * t2 + 2) / 2, (-3 * t3 + 4 * t2 + t) / 2, (t3 - t2) / 2])
    # Padded indices: node k of the axis is k + 1 in the padded grid.
    return np.stack([base, base + 1, base + 2, base + 3]), weights


def _padded(grid: np.ndarray) -> np.ndarray:
    """The grid with a linearly extrapolated ghost node on each side, so straight lines stay exact at the edges."""

    rows = np.vstack([2 * grid[:1] - grid[1:2], grid, 2 * grid[-1:] - grid[-2:-1]])
    return np.hstack([2 * rows[:, :1] - rows[:, 1:2], rows, 2 * rows[:, -1:] - rows[:, -2:-1]])


def _interpolate(x_axis: np.ndarray, y_axis: np.ndarray, grid: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    xi, xw = _cubic_weights(x_axis, x)
    yi, yw = _cubic_weights(y_axis, y)
    padded = _padded(grid)
    out = np.zeros(np.broadcast_shapes(x.shape, y.shape))
    for a in range(4):
        for b in range(4):
            out += xw[a] * yw[b] * padded[xi[a], yi[b]]
    return out


@dataclass(frozen=True)
class _Plane:
    """Map values over a fine (current, angle) grid; rows are currents, columns angles."""

    currents: np.ndarray
    gammas: np.ndarray
    i_d: np.ndarray
    i_q: np.ndarray
    values: dict[str, np.ndarray]


def _plane(model: MapModel, current_limit_A: float, angle_step_deg: float, current_samples: int) -> _Plane:
    # Rays beyond ±90° only lose torque; keep the map's angles inside them.
    low = max(float(model.gammas_deg[0]), -90.0)
    high = min(float(model.gammas_deg[-1]), 90.0)
    gammas = np.linspace(low, high, max(2, int(round((high - low) / angle_step_deg)) + 1))
    currents = np.linspace(0.0, current_limit_A, current_samples)
    radians = np.radians(gammas)[None, :]
    return _Plane(
        currents=currents,
        gammas=gammas,
        i_d=-currents[:, None] * np.sin(radians),
        i_q=currents[:, None] * np.cos(radians),
        values=model.sample(currents, gammas),
    )


def _voltage(plane: _Plane, resistance_ohm: float, omega_e: float) -> np.ndarray:
    v_d = resistance_ohm * plane.i_d - omega_e * plane.values["lambda_q"]
    v_q = resistance_ohm * plane.i_q + omega_e * plane.values["lambda_d"]
    return np.hypot(v_d, v_q)


def _iron_loss(model: MapModel, iron_h: np.ndarray, iron_e: np.ndarray, frequency_Hz: float) -> np.ndarray:
    ratio = frequency_Hz / model.reference_frequency_Hz
    return iron_h * ratio + iron_e * ratio * ratio


@dataclass(frozen=True)
class _EnvelopePoint:
    torque: float
    current: float
    gamma: float
    i_d: float
    i_q: float
    voltage: float
    region: str


def _best_point(model: MapModel, plane: _Plane, resistance_ohm: float, rpm: float, v_max: float) -> _EnvelopePoint | None:
    """The largest torque at this speed, each ray taken to its voltage boundary.

    The point stays on the current-limit circle (MTPA or field weakening)
    unless a smaller current gives measurably more torque: that is MTPV.
    """

    omega_e = rpm * 2 * math.pi / 60 * model.pole_pairs
    voltage = _voltage(plane, resistance_ohm, omega_e)
    feasible = voltage <= v_max
    if not feasible.any():
        return None
    rows = plane.currents.size
    columns = np.arange(plane.gammas.size)
    torque_grid = plane.values["torque"]
    # On the current-limit circle.
    circle = np.where(feasible[-1], torque_grid[-1], -np.inf)
    # Inside it: the largest feasible current on each ray, then the boundary between it and the next.
    last = rows - 1 - np.argmax(feasible[::-1, :], axis=0)
    has_any = feasible.any(axis=0)
    nxt = np.minimum(last + 1, rows - 1)
    v_low, v_high = voltage[last, columns], voltage[nxt, columns]
    rising = (nxt > last) & (v_high > v_low)
    fraction = np.where(rising, np.clip((v_max - v_low) / np.where(rising, v_high - v_low, 1.0), 0.0, 1.0), 0.0)
    current = plane.currents[last] + fraction * (plane.currents[nxt] - plane.currents[last])
    inside = np.where(has_any, torque_grid[last, columns] + fraction * (torque_grid[nxt, columns] - torque_grid[last, columns]), -np.inf)
    best_circle, best_inside = int(np.argmax(circle)), int(np.argmax(inside))
    amps_limit = float(plane.currents[-1])

    def at(amps: float, gamma: float) -> tuple[float, float]:
        values = model.sample_points(np.array(amps), np.array(gamma))
        i_d, i_q = -amps * math.sin(math.radians(gamma)), amps * math.cos(math.radians(gamma))
        volts = math.hypot(resistance_ohm * i_d - omega_e * float(values["lambda_q"]), resistance_ohm * i_q + omega_e * float(values["lambda_d"]))
        return float(values["torque"]), volts

    circle_torque = -math.inf
    if math.isfinite(circle[best_circle]):
        gamma = float(plane.gammas[best_circle])
        region = "mtpa" if feasible[-1, int(np.argmax(torque_grid[-1]))] else "field_weakening"
        if region == "field_weakening":
            # Walk the circle from the best feasible column to the voltage boundary beside it.
            for neighbour in (best_circle - 1, best_circle + 1):
                if 0 <= neighbour < plane.gammas.size and not feasible[-1, neighbour] and torque_grid[-1, neighbour] > torque_grid[-1, best_circle]:
                    low, high = gamma, float(plane.gammas[neighbour])
                    for _ in range(30):
                        middle = 0.5 * (low + high)
                        low, high = (middle, high) if at(amps_limit, middle)[1] <= v_max else (low, middle)
                    gamma = low
                    break
        circle_point = (amps_limit, gamma, region)
        circle_torque = at(amps_limit, gamma)[0]
    # MTPV only when a smaller current gives measurably more torque than the circle.
    if math.isfinite(inside[best_inside]) and inside[best_inside] > circle_torque * (1 + 1e-3) + 1e-12:
        amps, gamma, region = float(current[best_inside]), float(plane.gammas[best_inside]), "mtpv"
    elif math.isfinite(circle_torque):
        amps, gamma, region = circle_point
    else:
        return None
    torque, volts = at(amps, gamma)
    if not math.isfinite(torque) or torque <= 0:
        return None
    i_d, i_q = -amps * math.sin(math.radians(gamma)), amps * math.cos(math.radians(gamma))
    return _EnvelopePoint(torque, amps, gamma, i_d, i_q, volts, region)


def _boundary_speed(predicate, low: float, high: float, iterations: int = 40) -> float:
    """Largest speed in [low, high] where predicate still holds, by bisection (predicate(low) holds)."""

    for _ in range(iterations):
        middle = 0.5 * (low + high)
        if predicate(middle):
            low = middle
        else:
            high = middle
    return low


def _curve(model: MapModel, limits: DriveLimits, resistance_ohm: float, current_limit_A: float, label: str, samples: int) -> TorqueSpeedCurve:
    plane = _plane(model, current_limit_A, _ANGLE_STEP_DEG, _CURRENT_SAMPLES)
    v_max = limits.modulation_index_max * limits.dc_bus_V / 2
    top = limits.max_speed_rpm

    def best(rpm: float) -> _EnvelopePoint | None:
        return _best_point(model, plane, resistance_ohm, rpm, v_max)

    standstill = best(0.0)
    if standstill is None:
        raise ValueError("the map gives no positive torque within the current limit")
    # Base speed: where the standstill (MTPA) point first meets the voltage limit.
    def mtpa_holds(rpm: float) -> bool:
        point = best(rpm)
        return point is not None and point.region == "mtpa"

    base = top if mtpa_holds(top) else _boundary_speed(mtpa_holds, 0.0, top)
    def reachable(rpm: float) -> bool:
        return best(rpm) is not None

    end = top if reachable(top) else _boundary_speed(reachable, base, top)
    speeds = sorted({*np.linspace(0.0, end, samples).tolist(), base})
    speeds = [speed for index, speed in enumerate(speeds) if index == 0 or speed - speeds[index - 1] > end * 1e-6]
    points = [(speed, best(speed)) for speed in speeds]
    points = [(speed, point) for speed, point in points if point is not None]
    omega = [speed * 2 * math.pi / 60 for speed, _ in points]
    power = [point.torque * w for (_, point), w in zip(points, omega)]
    return TorqueSpeedCurve(
        limit=label,
        speed_rpm=[speed for speed, _ in points],
        torque_Nm=[point.torque for _, point in points],
        power_W=power,
        i_d_A=[point.i_d for _, point in points],
        i_q_A=[point.i_q for _, point in points],
        phase_voltage_peak_V=[point.voltage for _, point in points],
        region=[point.region for _, point in points],
        base_speed_rpm=base,
        max_speed_rpm=points[-1][0],
        peak_power_W=max(0.0, max(power)),
    )


def _status(model: MapModel, current_limit_A: float) -> tuple[str, str]:
    notes = [
        "Interpolated from the flux-linkage map with sinusoidal current; inverter drops and dead time are ignored."
    ]
    if current_limit_A > model.currents_A[-1] * (1 + 1e-9):
        notes.append(f"The current limit is clamped to the map's largest current, {model.currents_A[-1]:g} A.")
    return "experimental", " ".join(notes)


def torque_speed_envelope(
    flux_map: FluxLinkageMap,
    limits: DriveLimits,
    *,
    phase_resistance_ohm: float,
    winding_temperature_C: float,
    speed_samples: int = 61,
) -> TorqueSpeedEnvelope:
    """Peak (and, when set, continuous) torque–speed curves under the drive limits."""

    model = MapModel.from_map(flux_map)
    peak = min(limits.peak_current_A, float(model.currents_A[-1]))
    curves = [_curve(model, limits, phase_resistance_ohm, peak, "peak", speed_samples)]
    if limits.continuous_current_A is not None:
        continuous = min(limits.continuous_current_A, float(model.currents_A[-1]))
        curves.append(_curve(model, limits, phase_resistance_ohm, continuous, "continuous", speed_samples))
    status, reason = _status(model, limits.peak_current_A)
    return TorqueSpeedEnvelope(
        map_scope_key=flux_map.scope_key,
        limits=limits,
        phase_resistance_ohm=phase_resistance_ohm,
        winding_temperature_C=winding_temperature_C,
        curves=curves,
        status=status,
        status_reason=reason,
    )


def _first_crossing(currents: np.ndarray, torque: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Current at which a ray first reaches each target torque; NaN where it never does."""

    rising = np.maximum.accumulate(torque)
    out = np.full(targets.shape, np.nan)
    reachable = targets <= rising[-1]
    if reachable.any():
        index = np.searchsorted(rising, targets[reachable], side="left").clip(1, currents.size - 1)
        low, high = rising[index - 1], rising[index]
        fraction = np.where(high > low, (targets[reachable] - low) / np.where(high > low, high - low, 1), 0.0)
        out[reachable] = currents[index - 1] + fraction * (currents[index] - currents[index - 1])
    return out


def efficiency_map(
    flux_map: FluxLinkageMap,
    limits: DriveLimits,
    *,
    phase_resistance_ohm: float,
    winding_temperature_C: float,
    mechanical_loss_W: float = 0.0,
    speed_points: int = 41,
    torque_points: int = 41,
    envelope: TorqueSpeedEnvelope | None = None,
) -> EfficiencyMap:
    """Minimum-loss efficiency over the torque–speed plane inside the peak envelope.

    At each (speed, torque) every current angle is tried at the current that
    gives the torque; the one with the least copper plus iron loss that stays
    inside the voltage limit is kept.
    """

    model = MapModel.from_map(flux_map)
    current_limit = min(limits.peak_current_A, float(model.currents_A[-1]))
    envelope = envelope or torque_speed_envelope(
        flux_map, limits, phase_resistance_ohm=phase_resistance_ohm, winding_temperature_C=winding_temperature_C
    )
    peak = next(curve for curve in envelope.curves if curve.limit == "peak")
    top_speed = peak.max_speed_rpm
    top_torque = max(peak.torque_Nm)
    if top_speed <= 0 or top_torque <= 0:
        raise ValueError("the envelope has no motoring region to map")
    speeds = np.linspace(top_speed / speed_points, top_speed, speed_points)
    torques = np.linspace(top_torque / torque_points, top_torque, torque_points)
    plane = _plane(model, current_limit, _MAP_ANGLE_STEP_DEG, _MAP_CURRENT_SAMPLES)
    v_max = limits.modulation_index_max * limits.dc_bus_V / 2
    shape = (torques.size, speeds.size)
    efficiency = np.full(shape, np.nan)
    copper = np.full(shape, np.nan)
    iron = np.full(shape, np.nan)
    current_rms = np.full(shape, np.nan)
    current_angle = np.full(shape, np.nan)
    # Per-ray current at each target torque does not depend on speed.
    crossings = np.stack(
        [_first_crossing(plane.currents, plane.values["torque"][:, column], torques) for column in range(plane.gammas.size)],
        axis=1,
    )  # (torques, angles)
    valid = ~np.isnan(crossings)
    amps = np.where(valid, crossings, 0.0)
    gammas = np.broadcast_to(plane.gammas[None, :], amps.shape)
    # Near the top speed only a sliver of the current-limit circle reaches a torque, narrower
    # than the ray spacing, so the circle's own point at each torque is a candidate too: the
    # angle past the circle's peak where its torque falls to the target.
    circle = model.sample_points(np.full(plane.gammas.shape, current_limit), plane.gammas)["torque"]
    peak = int(np.argmax(circle))
    falling = np.minimum.accumulate(circle[peak:])
    circle_gamma = np.interp(-torques, -falling, plane.gammas[peak:], left=np.nan, right=np.nan)
    circle_ok = (torques <= circle[peak]) & (torques >= falling[-1]) & ~np.isnan(circle_gamma)
    amps = np.hstack([amps, np.where(circle_ok, current_limit, 0.0)[:, None]])
    gammas = np.hstack([gammas, np.where(circle_ok, circle_gamma, 0.0)[:, None]])
    valid = np.hstack([valid, circle_ok[:, None]])
    radians = np.radians(gammas)
    looked = model.sample_points(amps, gammas)
    lambda_d, lambda_q, iron_h, iron_e = (looked[name] for name in ("lambda_d", "lambda_q", "iron_h", "iron_e"))
    i_d, i_q = -amps * np.sin(radians), amps * np.cos(radians)
    copper_all = 1.5 * phase_resistance_ohm * amps * amps
    for column, rpm in enumerate(speeds):
        omega_m = rpm * 2 * math.pi / 60
        omega_e = omega_m * model.pole_pairs
        volts = np.hypot(phase_resistance_ohm * i_d - omega_e * lambda_q, phase_resistance_ohm * i_q + omega_e * lambda_d)
        iron_all = _iron_loss(model, iron_h, iron_e, rpm * model.pole_pairs / 60)
        loss = np.where(valid & (volts <= v_max * _BOUNDARY), copper_all + iron_all, np.inf)
        choice = np.argmin(loss, axis=1)
        rows = np.arange(torques.size)
        ok = np.isfinite(loss[rows, choice])
        cu, fe = copper_all[rows, choice], iron_all[rows, choice]
        electromagnetic = torques * omega_m
        shaft = electromagnetic - fe - mechanical_loss_W
        eta = np.clip(100.0 * shaft / (electromagnetic + cu), 0.0, 100.0)
        efficiency[ok, column] = eta[ok]
        copper[ok, column] = cu[ok]
        iron[ok, column] = fe[ok]
        current_rms[ok, column] = amps[rows, choice][ok] / math.sqrt(2)
        current_angle[ok, column] = gammas[rows, choice][ok]

    def matrix(values: np.ndarray) -> list[list[float | None]]:
        return [[None if math.isnan(value) else float(value) for value in row] for row in values]

    notes = [
        "Minimum-loss current at each point, interpolated from the flux-linkage map; torque is electromagnetic.",
        "Copper loss at the winding temperature; iron loss scaled from the map's reference speed, "
        "hysteresis with frequency and eddy current with its square."
        if model.iron_loss_available else "Iron loss is not included: the map has no iron loss.",
    ]
    return EfficiencyMap(
        map_scope_key=flux_map.scope_key,
        speed_rpm=speeds.tolist(),
        torque_Nm=torques.tolist(),
        efficiency_pct=matrix(efficiency),
        copper_loss_W=matrix(copper),
        iron_loss_W=matrix(iron),
        phase_current_rms_A=matrix(current_rms),
        current_angle_deg=matrix(current_angle),
        mechanical_loss_W=mechanical_loss_W,
        winding_temperature_C=winding_temperature_C,
        status="experimental",
        status_reason=" ".join(notes),
    )
