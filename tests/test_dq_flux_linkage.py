"""Loaded d/q flux linkage from phase quantities (#113), on an analytic motor."""

from __future__ import annotations

import math

import pytest

from backend.dq_flux_linkage import dq_flux_linkage

POLE_PAIRS = 4
LAMBDA_PM = 0.05
L_D, L_Q = 0.4e-3, 0.9e-3


def _abc(d: float, q: float, theta: float, direction: int) -> tuple[float, float, float]:
    """Phase values of a d/q vector whose d-axis sits at electrical angle theta."""
    # q is 90° ahead of d in the rotor's direction of rotation.
    alpha = d * math.cos(theta) - direction * q * math.sin(theta)
    beta = d * math.sin(theta) + direction * q * math.cos(theta)
    a = alpha
    b = -0.5 * alpha + math.sqrt(3) / 2 * beta
    c = -0.5 * alpha - math.sqrt(3) / 2 * beta
    return a, b, c


def _motor(current: float, gamma_deg: float, *, direction: int = 1, offset_deg: float = 37.0, positions: int = 24):
    i_d = -current * math.sin(math.radians(gamma_deg))
    i_q = current * math.cos(math.radians(gamma_deg))
    lambda_d, lambda_q = LAMBDA_PM + L_D * i_d, L_Q * i_q
    angles = [360.0 * k / positions for k in range(positions)]
    theta = [direction * math.radians(angle) + math.radians(offset_deg) for angle in angles]
    flux = list(zip(*(_abc(lambda_d, lambda_q, t, direction) for t in theta)))
    amps = list(zip(*(_abc(i_d, i_q, t, direction) for t in theta)))
    no_load = list(zip(*(_abc(LAMBDA_PM, 0.0, t, direction) for t in theta)))
    torque = 1.5 * POLE_PAIRS * (lambda_d * i_q - lambda_q * i_d)
    return dict(
        pole_pairs=POLE_PAIRS,
        loaded_angles_deg=angles,
        loaded_flux_linkage_abc=flux,
        phase_current_abc=amps,
        no_load_angles_deg=angles,
        no_load_flux_linkage_abc=no_load,
        solved_torque_nm=torque,
    ), (i_d, i_q, lambda_d, lambda_q, torque)


@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("gamma", [0.0, 30.0, -20.0, 60.0])
def test_recovers_the_d_q_quantities_and_torque(direction, gamma):
    inputs, (i_d, i_q, lambda_d, lambda_q, torque) = _motor(20.0, gamma, direction=direction)
    record = dq_flux_linkage(**inputs)
    assert record.i_d_A == pytest.approx(i_d, abs=1e-9)
    assert record.i_q_A == pytest.approx(i_q, abs=1e-9)
    assert record.lambda_d_Wb == pytest.approx(lambda_d)
    assert record.lambda_q_Wb == pytest.approx(lambda_q, abs=1e-12)
    assert record.torque_dq_Nm == pytest.approx(torque)
    assert record.torque_agreement_pct == pytest.approx(100.0)
    assert record.current_angle_deg == pytest.approx(gamma, abs=1e-9)
    assert record.lambda_pm_Wb == pytest.approx(LAMBDA_PM)
    assert record.positions == 24


def test_apparent_inductances_follow_the_currents():
    record = dq_flux_linkage(**_motor(20.0, 30.0)[0])
    assert record.apparent_L_d_H == pytest.approx(L_D)
    assert record.apparent_L_q_H == pytest.approx(L_Q)
    on_q_axis = dq_flux_linkage(**_motor(20.0, 0.0)[0])
    assert on_q_axis.apparent_L_d_H is None  # id = 0: no d-axis inductance to read
    assert on_q_axis.apparent_L_q_H == pytest.approx(L_Q)


def test_reluctance_torque_is_included():
    # With Lq > Ld and negative id, the d/q torque exceeds the magnet torque alone.
    inputs, (i_d, i_q, _, _, torque) = _motor(20.0, 40.0)
    magnet_only = 1.5 * POLE_PAIRS * LAMBDA_PM * i_q
    assert torque > magnet_only
    assert dq_flux_linkage(**inputs).torque_dq_Nm == pytest.approx(torque)


def test_agreement_reports_a_solver_torque_that_differs():
    inputs, (*_, torque) = _motor(20.0, 0.0)
    inputs["solved_torque_nm"] = torque * 0.97
    assert dq_flux_linkage(**inputs).torque_agreement_pct == pytest.approx(97.0)


def test_no_load_samples_that_do_not_follow_the_rotor_give_no_record():
    inputs, _ = _motor(20.0, 0.0)
    inputs["no_load_flux_linkage_abc"] = [[0.01 * ((k * 7) % 5) for k in range(24)] for _ in range(3)]
    assert dq_flux_linkage(**inputs) is None
    inputs, _ = _motor(20.0, 0.0)
    inputs["phase_current_abc"] = [series[:-1] for series in inputs["phase_current_abc"]]
    assert dq_flux_linkage(**inputs) is None



@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("gamma", [0.0, 30.0, -20.0, 60.0])
def test_without_a_no_load_sweep_the_commanded_angle_places_the_d_axis(direction, gamma):
    inputs, (i_d, i_q, lambda_d, lambda_q, torque) = _motor(20.0, gamma, direction=direction)
    del inputs["no_load_angles_deg"], inputs["no_load_flux_linkage_abc"]
    assert dq_flux_linkage(**inputs) is None  # nothing to place the axis with
    record = dq_flux_linkage(**inputs, commanded_current_angle_deg=gamma)
    assert record.d_axis_source == "applied_current_angle"
    assert record.lambda_d_Wb == pytest.approx(lambda_d)
    assert record.lambda_q_Wb == pytest.approx(lambda_q, abs=1e-12)
    assert record.i_d_A == pytest.approx(i_d, abs=1e-9)
    assert record.torque_agreement_pct == pytest.approx(100.0)
    assert record.lambda_pm_Wb is None and record.apparent_L_d_H is None


def test_the_no_load_sweep_wins_over_the_commanded_angle():
    inputs, _ = _motor(20.0, 30.0)
    record = dq_flux_linkage(**inputs, commanded_current_angle_deg=0.0)
    assert record.d_axis_source == "no_load_flux_linkage"
    assert record.current_angle_deg == pytest.approx(30.0)  # measured, not the commanded 0°


def test_the_run_pdf_reports_an_open_circuit_run_as_such():
    """A back-EMF run has no current: the PDF gives the flux linkages, not empty current and inductance rows."""
    import io

    pypdf = pytest.importorskip("pypdf")
    from backend.public_report import build_public_run_pdf
    from tests.test_loss_breakdown import RAW, _stored_result

    def text(result):
        pdf = build_public_run_pdf(project=RAW, request={"resolved_config": RAW}, result=result, material={}, manifest={})
        return " ".join(" ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages).split())

    loaded = _stored_result()
    assert "Characteristic current" in text(loaded) and "Open-circuit run" not in text(loaded)
    open_circuit = _stored_result()
    open_circuit["summary"]["dq_flux_linkage"].update(
        i_d_A=3.6e-14, i_q_A=-5.2e-14, torque_dq_Nm=0.0, torque_agreement_pct=None, current_angle_deg=None,
        apparent_L_d_H=None, apparent_L_q_H=None,
    )
    report = text(open_circuit)
    assert "Open-circuit run" in report and "Magnet flux linkage" in report
    assert "Characteristic current" not in report and "Needs d-axis current" not in report and "Torque agreement" not in report
