"""Flux-linkage map: the loaded d/q record over a grid of currents and angles (#139).

Each grid point is an ordinary solve of the design at a peak current |I|
and current angle γ (id = −I·sin γ, iq = I·cos γ), without the no-load sweep
except at zero current. Its loaded λd and λq come
from the solve's d/q record (#113), its torque and ripple from the solve
summary, and its iron loss, at the design's rated speed, from #138. The
geometry does not change between points, so the solver's per-angle mesh cache
serves every point after the first.

Points are written to a store as they finish, keyed by a hash of everything
but the operating point, so a cancelled or failed map resumes without solving
finished points again. The zero-current point is the same at every angle and
is solved once.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

from backend.models import MotorConfig, SolveOptionsConfig
from backend.models.performance import FluxLinkageMap, FluxLinkageMapPoint, dq_currents
from backend.solver_contract import SolveCancelledError

MapPreset = Literal["preview", "standard"]

# Settings that pick the operating point rather than the machine; the map varies or ignores them.
_OPERATING_POINT_FIELDS = (
    "current_amplitude_A",
    "current_amplitude_convention",
    "current_angle_deg",
    "commutation_advance_deg",
    "winding_temperature_C",
    "mechanical_loss_W",
    "motor_input_dc_bus_V",
    "stream_noload_field_lines",
    "field_composition_source",
    "magneto2d_workers",
)
# Each point sweeps one full electrical cycle in equal steps: the iron loss needs a
# whole period (#138), and the d/q averages then cover every ripple harmonic.
_PRESETS: dict[str, dict[str, Any]] = {
    # Five currents to the peak and 15° angle steps, 24 rotor positions: 29 solves.
    "preview": {"currents": 5, "gamma_step_deg": 15.0, "sweep_step_deg": 15.0},
    # Seven currents and 10° angle steps, 48 rotor positions: 61 solves.
    "standard": {"currents": 7, "gamma_step_deg": 10.0, "sweep_step_deg": 7.5},
}

Solve = Callable[[MotorConfig], Any]
Progress = Callable[[int, int, FluxLinkageMapPoint, float | None], None]


def map_grid(peak_current_A: float, preset: MapPreset = "preview") -> tuple[list[float], list[float]]:
    """Currents from zero to the peak, and current angles from 0° to 90°."""

    if not (peak_current_A > 0 and math.isfinite(peak_current_A)):
        raise ValueError("the map needs a positive peak current")
    settings = _PRESETS[preset]
    count = settings["currents"]
    currents = [round(peak_current_A * index / (count - 1), 9) for index in range(count)]
    step = settings["gamma_step_deg"]
    gammas = [round(step * index, 9) for index in range(int(round(90.0 / step)) + 1)]
    return currents, gammas


def map_solve_count(currents: Sequence[float], gammas: Sequence[float]) -> int:
    """Solves the grid needs: the zero-current point once, every other point once."""

    nonzero = sum(1 for current in currents if current > 0)
    return nonzero * len(gammas) + (1 if any(current == 0 for current in currents) else 0)


def map_scope_key(config: MotorConfig, preset: MapPreset = "preview") -> str:
    """Hash of everything that would invalidate the map's points."""

    raw = config.model_dump(mode="json")
    solve_params = dict(raw.get("solve_params") or {})
    for name in _OPERATING_POINT_FIELDS:
        solve_params.pop(name, None)
    raw["solve_params"] = solve_params
    raw.pop("name", None)
    raw["__map_preset__"] = {"name": preset, **_PRESETS[preset]}
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def point_config(
    config: MotorConfig, current_peak_A: float, gamma_deg: float, preset: MapPreset = "preview", *, no_load_sweep: bool | None = None
) -> MotorConfig:
    """The design at one map point: sinusoidal peak current at angle γ.

    Only the zero-current point runs the no-load sweep (by default); the others
    place their d-axis from the applied currents and the commanded angle,
    which is most of the solve time saved (#113).
    """

    solve_params = config.solve_params
    if solve_params is None:
        raise ValueError("the map needs the design's solve settings")
    update: dict[str, Any] = {
        "current_amplitude_A": current_peak_A,
        "current_amplitude_convention": "peak",
        "current_angle_deg": gamma_deg,
        "excitation_mode": "sinusoidal",
        "commutation_advance_deg": 0.0,
        "stream_noload_field_lines": False,
    }
    update.update(solve_quality="custom", rotor_sweep_range_deg=360.0, rotor_step_deg=_PRESETS[preset]["sweep_step_deg"])
    options = (config.solve_options or SolveOptionsConfig()).model_copy(
        update={
            "back_emf": current_peak_A == 0 if no_load_sweep is None else no_load_sweep,
            "cogging_torque": False,
            "thd_analysis": False,
            "torque_speed_envelope": False,
        }
    )
    return config.model_copy(update={"solve_params": solve_params.model_copy(update=update), "solve_options": options})


def _finite(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def point_from_result(current_peak_A: float, gamma_deg: float, result: Any) -> FluxLinkageMapPoint:
    """The map point a solve result gives; failed when it has no d/q record."""

    i_d, i_q = dq_currents(current_peak_A, gamma_deg)
    summary = result.summary
    dq = summary.dq_flux_linkage
    metadata = result.solve_metadata
    base = dict(current_peak_A=current_peak_A, gamma_deg=gamma_deg, i_d_A=i_d, i_q_A=i_q)
    if dq is None or _finite(summary.avg_torque_Nm) is None:
        return FluxLinkageMapPoint(**base, status="failed", error="The solve returned no loaded d/q flux linkage.")
    iron = summary.iron_loss
    ripple = _finite(summary.torque_ripple_pct)
    return FluxLinkageMapPoint(
        **base,
        status="ok",
        avg_torque_Nm=float(summary.avg_torque_Nm),
        torque_ripple_pct=abs(ripple) if ripple is not None else None,
        lambda_d_Wb=dq.lambda_d_Wb,
        lambda_q_Wb=dq.lambda_q_Wb,
        iron_loss_W=_finite(getattr(iron, "iron_loss_W", None)),
        iron_hysteresis_loss_W=_finite(getattr(iron, "iron_hysteresis_loss_W", None)),
        iron_eddy_loss_W=_finite(getattr(iron, "iron_eddy_loss_W", None)),
        nonlinear_iterations_max=getattr(metadata, "nonlinear_max_iterations_used", None),
        nonlinear_residual_max=_finite(getattr(metadata, "nonlinear_worst_final_mismatch", None)),
    )


class MapStore:
    """Finished points of one map on disk, one JSON file each."""

    def __init__(self, root: Path, scope_key: str) -> None:
        self.directory = root / scope_key
        self.scope_key = scope_key

    @staticmethod
    def _name(current: float, gamma: float) -> str:
        return f"I{current:.9g}_g{gamma:.9g}.json".replace("-", "m")

    def load(self, current: float, gamma: float) -> FluxLinkageMapPoint | None:
        path = self.directory / self._name(current, gamma)
        try:
            point = FluxLinkageMapPoint.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return point if point.status == "ok" else None

    def save(self, point: FluxLinkageMapPoint) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / self._name(point.current_peak_A, point.gamma_deg)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(point.model_dump_json(), encoding="utf-8")
        temporary.replace(path)

    def save_map(self, flux_map: FluxLinkageMap) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / "map.tmp"
        temporary.write_text(flux_map.model_dump_json(), encoding="utf-8")
        temporary.replace(self.directory / "map.json")

    def load_map(self) -> FluxLinkageMap | None:
        try:
            return FluxLinkageMap.model_validate_json((self.directory / "map.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


def run_flux_linkage_map(
    config: MotorConfig,
    *,
    solve: Solve,
    peak_current_A: float,
    preset: MapPreset = "preview",
    store: MapStore | None = None,
    progress: Progress | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> FluxLinkageMap:
    """Solve every grid point not already in the store, then assemble the map.

    A point whose solve fails is recorded as failed and the map goes on; a
    cancellation stops it, keeping the finished points for a resume.
    """

    solve_params = config.solve_params
    if solve_params is None:
        raise ValueError("the map needs the design's solve settings")
    if solve_params.rated_speed_rpm <= 0:
        raise ValueError("the map needs a rated speed above 0 rpm for its iron loss")
    currents, gammas = map_grid(peak_current_A, preset)
    total = map_solve_count(currents, gammas)
    points: dict[tuple[float, float], FluxLinkageMapPoint] = {}
    done = 0
    solve_seconds: list[float] = []
    positions = 0

    def finish(point: FluxLinkageMapPoint, *, solved: bool) -> None:
        nonlocal done
        done += 1
        if store is not None and solved and point.status == "ok":
            store.save(point)
        if progress is not None:
            remaining = total - done
            eta = sum(solve_seconds) / len(solve_seconds) * remaining if solve_seconds else None
            progress(done, total, point, eta)

    def solve_point(current: float, gamma: float) -> FluxLinkageMapPoint:
        nonlocal positions
        if should_stop():
            raise SolveCancelledError("Map cancelled.")
        started = time.perf_counter()
        try:
            result = solve(point_config(config, current, gamma, preset))
        except SolveCancelledError:
            raise
        except Exception as exc:  # one failed point should not lose the rest of the map
            i_d, i_q = dq_currents(current, gamma)
            return FluxLinkageMapPoint(
                current_peak_A=current, gamma_deg=gamma, i_d_A=i_d, i_q_A=i_q, status="failed",
                error=str(exc) or type(exc).__name__,
            )
        solve_seconds.append(time.perf_counter() - started)
        positions = max(positions, int(getattr(result.solve_metadata, "rotor_positions", 0) or 0))
        return point_from_result(current, gamma, result)

    for current in currents:
        if current == 0:
            stored = store.load(0.0, gammas[0]) if store is not None else None
            zero = stored or solve_point(0.0, 0.0)
            for gamma in gammas:
                points[(0.0, gamma)] = zero.model_copy(update={"gamma_deg": gamma})
            finish(points[(0.0, gammas[0])], solved=stored is None)
            if store is not None and stored is None and zero.status == "ok":
                for gamma in gammas[1:]:
                    store.save(points[(0.0, gamma)])
            continue
        for gamma in gammas:
            stored = store.load(current, gamma) if store is not None else None
            point = stored or solve_point(current, gamma)
            points[(current, gamma)] = point
            finish(point, solved=stored is None)

    flux_map = FluxLinkageMap(
        scope_key=map_scope_key(config, preset),
        pole_pairs=config.rotor.pole_count // 2,
        current_peak_A=currents,
        gamma_deg=gammas,
        reference_speed_rpm=solve_params.rated_speed_rpm,
        magnet_temperature_C=solve_params.magnet_temperature_C,
        rotor_positions=max(2, positions),
        mesh_density=str(solve_params.mesh_density),
        torque_method=solve_params.torque_method,
        points=[points[(current, gamma)] for current in currents for gamma in gammas],
    )
    if store is not None:
        store.save_map(flux_map)
    return flux_map


def map_agreement_pct(flux_map: FluxLinkageMap, *, floor_share: float = 0.05) -> list[float | None]:
    """Each point's FEM torque as a percentage of its d/q torque.

    None where there is nothing meaningful to compare: failed points, zero
    current, and points whose d/q torque is under floor_share of the map's
    largest (near 90°, where both torques are close to zero).
    """

    torques: list[float | None] = []
    for point in flux_map.points:
        if point.status != "ok" or point.current_peak_A == 0:
            torques.append(None)
            continue
        torques.append(1.5 * flux_map.pole_pairs * (point.lambda_d_Wb * point.i_q_A - point.lambda_q_Wb * point.i_d_A))
    largest = max((abs(value) for value in torques if value is not None), default=0.0)
    return [
        100.0 * point.avg_torque_Nm / torque if torque is not None and largest > 0 and abs(torque) >= floor_share * largest else None
        for point, torque in zip(flux_map.points, torques)
    ]
