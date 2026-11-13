"""Run selected operating-point analyses and an optional, resumable drive map."""

from __future__ import annotations

import time
from collections.abc import Callable

from backend.drive_performance import efficiency_map, torque_speed_envelope
from backend.field_artifacts import protect_result_cache
from backend.flux_linkage_map import MapStore, map_agreement_pct, map_grid, map_scope_key, map_solve_count, run_flux_linkage_map
from backend.input_advisories import geometry_input_advisories, partial_sweep_advisory
from backend.models import MotorConfig, SolveOptionsConfig, SolveResult
from backend.models.result import TorqueSpeedAnalysisResult
from backend.solve_workspace import user_data_root
from backend.solver_contract import ProgressCallback, SolveCancelledError, Solver
from backend.winding_resistance import winding_resistance


def solve_selected_analyses(
    solver: Solver,
    config: MotorConfig,
    *,
    on_progress: ProgressCallback | None = None,
    solve_mesh_key: str | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    map_supported: bool = True,
) -> SolveResult:
    started = time.perf_counter()
    options = config.solve_options or SolveOptionsConfig()
    base_config = config.model_copy(update={
        "solve_options": options.model_copy(update={"torque_speed_envelope": False}),
    })

    def base_progress(*args, **kwargs):
        if on_progress is None:
            return
        if options.torque_speed_envelope:
            args = list(args)
            detail = dict((args[9] if len(args) > 9 else kwargs.get("solver_detail")) or {})
            position, total = args[:2]
            detail["analysis_fraction"] = 0.05 * min(1, position / total) if total else 0
            if len(args) > 9:
                args[9] = detail
            else:
                kwargs["solver_detail"] = detail
        on_progress(*args, **kwargs)

    # With only the map selected this is a single zero-current preview, not a
    # loaded sweep. The map computes its own torque, flux and loss dependencies.
    result = solver.solve(base_config, on_progress=base_progress if on_progress else None, solve_mesh_key=solve_mesh_key)
    advisories = geometry_input_advisories(config)
    window_note = partial_sweep_advisory(result.solve_metadata.loaded_cycle_complete)
    if window_note and result.solve_metadata.torque_sweep_computed is not False:
        advisories.append(window_note)
    result.warnings = list(dict.fromkeys([*result.warnings, *advisories]))
    settings = config.torque_speed_analysis
    if settings is None or not map_supported or not options.torque_speed_envelope:
        return result
    with protect_result_cache(result):
        return _attach_map_analysis(solver, config, result, on_progress, should_stop, started)


def _attach_map_analysis(solver, config, result, on_progress, should_stop, started):
    settings = config.torque_speed_analysis
    if should_stop():
        raise SolveCancelledError("Analysis cancelled.")
    store = MapStore(user_data_root() / "performance_maps", map_scope_key(config, settings.preset))
    flux_map = store.covering_map(settings.limits.peak_current_A)

    if flux_map is None:
        total = map_solve_count(*map_grid(settings.limits.peak_current_A, settings.preset))
        if on_progress is not None:
            on_progress(0, total, None, "torque_speed_map", None, None, None, None, None, {"analysis_fraction": 0.05})

        def progress(done, total, point, eta):
            if on_progress is not None:
                on_progress(done, total, None, "torque_speed_map", None, None, None, None, None, {
                    "current_peak_A": point.current_peak_A, "gamma_deg": point.gamma_deg,
                    "eta_s": eta, "map_point_status": point.status,
                    "analysis_fraction": 0.05 + 0.9 * done / total,
                })

        flux_map = run_flux_linkage_map(
            config, solve=solver.solve, peak_current_A=settings.limits.peak_current_A,
            preset=settings.preset, store=store, progress=progress, should_stop=should_stop,
        )
    if should_stop():
        raise SolveCancelledError("Analysis cancelled.")
    try:
        winding = winding_resistance(config)
    except (ValueError, KeyError):
        winding = None
    resistance = winding.phase_resistance_ohm if winding is not None else 0
    temperature = winding.winding_temperature_C if winding is not None else 20
    mechanical = float(config.solve_params.mechanical_loss_W or 0) if config.solve_params else 0
    failed = [point for point in flux_map.points if point.status != "ok"]
    envelope = efficiency = None
    reason = None
    if failed:
        reason = (
            f"{len(failed)} of {len(flux_map.points)} map points have no solved result. "
            "Retry the analysis to reuse completed points and retry failures."
        )
    else:
        envelope = torque_speed_envelope(
            flux_map, settings.limits, phase_resistance_ohm=resistance, winding_temperature_C=temperature,
        )
        efficiency = efficiency_map(
            flux_map, settings.limits, phase_resistance_ohm=resistance, winding_temperature_C=temperature,
            mechanical_loss_W=mechanical, envelope=envelope, control=settings.control,
        )
    result.torque_speed_analysis = TorqueSpeedAnalysisResult(
        settings=settings.model_copy(deep=True), map=flux_map, torque_agreement_pct=map_agreement_pct(flux_map),
        envelope=envelope, efficiency_map=efficiency, winding_resistance=winding, mechanical_loss_W=mechanical,
        status="partial" if failed else "complete", status_reason=reason,
    )
    result.summary.solve_time_s = time.perf_counter() - started
    result.solve_metadata.solve_time_s = result.summary.solve_time_s
    return result
