"""Opt-in full-motor rotor iron loss from a fresh fixed-material mechanical turn."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import numpy as np

from backend import solve_profile
from backend.field_lines import generate_element_b_components
from backend.gmsh_solver import run_gmsh_mesh_preview
from backend.iron_loss import M350_50A_LOSS, FieldFrame, iron_loss_status_reason
from backend.magneto2d_adapter import Magneto2DExecutionError, Magneto2DUnsupportedError, run_magneto2d_report
from backend.models import MotorConfig, RotorIronLoss
from backend.rotor_iron_loss import (
    RotorLossMaterial,
    RotorSamplingPlan,
    harmonic_rotor_iron_loss,
    rotor_flux_history,
    sample_rotor_field,
)
from backend.rotor_motion_mesh import FixedMaterialRotorMesh
from backend.solver_contract import SolveCancelledError

POSITIONS = 384
MATERIAL = RotorLossMaterial("M350-50A", "EN 10106 grade limits + classical lamination eddy term", M350_50A_LOSS)


def compute_or_cached(config, *, cache_dir=None, direction=-1, **kwargs):
    """Extend the existing field-cache identity with rotor method, sampling and code."""
    from backend import rotor_iron_loss, rotor_motion_mesh

    identity = {"config": config.model_dump(mode="json"), "direction": direction, "positions": POSITIONS,
                "material": asdict(MATERIAL), "sources": {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                for p in (__file__, rotor_iron_loss.__file__, rotor_motion_mesh.__file__)}}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()
    path = Path(cache_dir) / "rotor-iron-loss-v1.json" if cache_dir is not None else None
    if path is not None and path.exists():
        try:
            cached = json.loads(path.read_text())
            if cached["input_sha256"] == digest:
                record = RotorIronLoss.model_validate(cached["record"])
                if record.status != "unavailable":
                    if kwargs.get("check_cancelled") is not None:
                        kwargs["check_cancelled"]()
                    if kwargs.get("on_progress") is not None:
                        kwargs["on_progress"](POSITIONS+1, POSITIONS+1, None)
                    return record
        except (ValueError, KeyError, OSError):
            pass
    record = compute_rotor_iron_loss(config, direction=direction, **kwargs)
    if path is not None and record.status != "unavailable":
        import os

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name+f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps({"input_sha256": digest, "record": record.model_dump(mode="json")},
                                            allow_nan=False), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            pass  # A full cache must not invalidate a successfully computed field history.
    return record


def unavailable_reason(config: MotorConfig):
    params = config.solve_params
    if params is None or params.rated_speed_rpm <= 0:
        return "Rotor iron loss needs a positive mechanical speed."
    if params.symmetry != "full":
        return "Rotor iron loss is available for full-motor solves; sector rotor loss is deferred."
    if config.rotor_layout != "inner":
        return "Rotor iron loss currently supports inner-rotor full-motor models."
    if config.topology == "IPM" and config.rotor.ipm_topology != "flat_buried":
        return "Rotor iron loss currently supports SPM and flat-IPM full-motor models."
    if config.geometry_reference is not None:
        return "Rotor iron loss is not yet supported for pinned imported reference geometries."
    if config.materials.rotor_steel != MATERIAL.steel_id:
        return "Rotor iron loss currently requires the M350-50A rotor loss coefficients."
    if params.excitation_mode != "sinusoidal":
        return "Rotor iron loss currently supports sinusoidal excitation."
    if params.nonlinear_solver != "newton":
        # The convergence acceptance below is defined on Newton's residuals only.
        return "Rotor iron loss needs the Newton nonlinear solver. Change Nonlinear solver to Newton and run again."
    return None


def planned_positions(config):
    opts = config.solve_options
    return POSITIONS+1 if opts is not None and opts.rotor_iron_loss and unavailable_reason(config) is None else 0


def unavailable(config, reason):
    return RotorIronLoss(status="unavailable", status_reason=reason, steel=config.materials.rotor_steel,
                         solved_region="sector" if config.solve_params and config.solve_params.symmetry != "full" else "full_motor")


def field_sample(report, angle):
    if report["mesh_info"]["total_span_deg"] != 360 or report["field_plot"]["total_span_deg"] != 360:
        raise ValueError("rotor loss needs full-motor field reports")
    convergence = report["solve_info"]["nonlinear_convergence"]
    if (convergence.get("method") == "picard" or convergence.get("scaled_residual") is None
            or convergence.get("rhs_scaled_residual") is None):
        # Newton falls back to Picard at a position it cannot converge; Picard
        # reports a different residual that this acceptance does not cover.
        raise ValueError("rotor loss needs Newton-converged fields; a rotor position was solved by the Picard fallback")
    if (convergence["solution_reused"] or not 0 < convergence["tolerance"] < 1
            or not (convergence["scaled_residual"] <= convergence["tolerance"]
                    or convergence["rhs_scaled_residual"] <= convergence["absolute_residual_floor"])):
        raise ValueError("rotor loss needs fresh, converged native field solutions")
    plot = report["field_plot"]
    bx, by = generate_element_b_components(plot["nodes_mm"], plot["triangles"], plot["az_nodal"])
    return sample_rotor_field(FieldFrame(np.asarray(plot["nodes_mm"]), np.asarray(plot["triangles"]), plot["regions"],
                                        np.asarray(bx), np.asarray(by)), mechanical_angle_deg=angle)


def record_from_samples(config, plan, samples):
    first, last = samples[0], samples[-1]
    if (len(samples) != plan.positions+1 or abs(last.mechanical_angle_deg-(plan.start_mechanical_deg+plan.direction*360)) > 1e-8
            or any(s.corners_mm.shape != first.corners_mm.shape
                   or not np.allclose(first.corners_mm, s.corners_mm, atol=1e-9, rtol=0) for s in samples[1:])):
        raise ValueError("rotor loss needs an independent endpoint on the same material mesh")
    difference = np.column_stack((last.bx_t-first.bx_t, last.by_t-first.by_t))
    maximum, rms = float(np.max(abs(difference))), float(np.sqrt(np.mean(difference**2)))
    if maximum > 1e-6 or rms > 1e-7:
        raise ValueError("rotor loss full-turn closure did not converge")
    history = rotor_flux_history(plan, samples[:-1])
    estimate = harmonic_rotor_iron_loss(history, material=MATERIAL, stack_length_m=config.stator.stack_length_mm*1e-3)
    digest = hashlib.sha256(json.dumps(plan.metadata(), sort_keys=True).encode())
    for values in (history.bx_t, history.by_t, history.area_m2):
        digest.update(np.asarray(values, dtype="<f8").tobytes())
    return RotorIronLoss(
        status="experimental", status_reason=iron_loss_status_reason(MATERIAL.steel_id)
        + " Full-turn rotor-material harmonics; DC-bias/minor-loop, rotating-flux and excess-loss corrections are not included.",
        steel=MATERIAL.steel_id, coefficient_source=MATERIAL.coefficient_source, coefficients=asdict(MATERIAL.coefficients),
        stacking_factor=MATERIAL.stacking_factor, speed_rpm=plan.speed_rpm, mechanical_frequency_Hz=plan.base_frequency_hz,
        samples_per_mechanical_turn=plan.positions, rotor_iron_loss_W=estimate.total_W,
        rotor_hysteresis_loss_W=estimate.hysteresis_W, rotor_lamination_eddy_loss_W=estimate.lamination_eddy_W,
        rotor_iron_mass_kg=estimate.rotor_iron_mass_kg,
        share_above_validated_frequency=estimate.share_above_validated_frequency,
        share_above_validated_flux_density=estimate.share_above_validated_flux_density,
        endpoint_max_component_difference_T=maximum, endpoint_rms_component_difference_T=rms, history_sha256=digest.hexdigest())


def compute_rotor_iron_loss(config, *, direction=-1, workers=4, on_progress=None, check_cancelled=None):
    """Config is already in native excitation coordinates; never mirror it twice."""
    reason = unavailable_reason(config)
    if reason:
        return unavailable(config, reason)

    def check():
        if check_cancelled is not None:
            check_cancelled()

    check()
    plan = RotorSamplingPlan(config.solve_params.rated_speed_rpm, POSITIONS, direction)
    samples = [None]*(POSITIONS+1)
    try:
        with solve_profile.span("rotor: prepare material mesh"):
            template = run_gmsh_mesh_preview(config, rotor_angle_deg=0)["solve_mesh_artifact"]
            motion = FixedMaterialRotorMesh(template)
        solve_profile.mark("mesh group ready")
        native_config = config.model_copy(deep=True)
        native_config.solve_params.magneto2d_workers = 1
        angles = (*plan.mechanical_angles_deg, direction*360.)

        def solve(index):
            check()
            angle = angles[index]
            with solve_profile.span("rotor: connect air gap"):
                artifact = motion.at_angle(native_config, angle)
            solve_profile.mark("solve started")
            with solve_profile.span("solve (rotor): one position, total"):
                report = run_magneto2d_report(native_config, sweep=False, rotor_angle_deg=angle, solve_mesh_artifact=artifact)
            with solve_profile.span("rotor: sample material field"):
                sample = field_sample(report, angle)
            solve_profile.mark("solve finished")
            check()
            return index, sample

        with ThreadPoolExecutor(max_workers=max(1, min(8, int(workers)))) as pool:
            pending = [pool.submit(solve, index) for index in range(POSITIONS+1)]
            try:
                for count, future in enumerate(as_completed(pending), 1):
                    check()
                    index, sample = future.result()
                    samples[index] = sample
                    if on_progress is not None:
                        on_progress(count, POSITIONS+1, angles[index])
            except BaseException:
                for future in pending:
                    future.cancel()
                raise
        check()
        return record_from_samples(native_config, plan, samples)
    except SolveCancelledError:
        raise
    except (ValueError, KeyError, TypeError, OSError, Magneto2DExecutionError, Magneto2DUnsupportedError) as exc:
        check()
        return unavailable(config, f"Rotor iron-loss history unavailable: {str(exc)[:300]}")
