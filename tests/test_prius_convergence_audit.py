"""Newton normalization regression and rejection of untrustworthy evidence."""

import copy

import pytest

from tools.report_prius_benchmark import audit_newton_residual


def field(rhs=9.57800250145694e-9, initial=0.6774101252594844):
    scaled = rhs / initial
    return {
        "solver_method": "sparse_pcg_jacobi+damped_newton", "nonlinear_enabled": True,
        "nonlinear_residual_history": [0.23, scaled],
        "nonlinear_convergence": {
            "method": "newton", "scaled_residual": scaled, "rhs_scaled_residual": rhs,
            "initial_rhs_scaled_residual": initial, "tolerance": 1e-9, "absolute_residual_floor": 1e-8,
            "residual_definition": "scaled_residual = L2(f - K(A) A) / L2(f - K(A0) A0); rhs_scaled_residual = L2(f - K(A) A) / L2(f); after model constraints, each continuation stage",
            "stopping_test": "scaled_residual <= tolerance OR rhs_scaled_residual <= absolute_residual_floor at every continuation stage",
        },
    }


@pytest.mark.parametrize("rhs,initial", [(9.57800250145694e-9, 0.6774101252594844),
                                         (9.981132664323609e-9, 0.6774101252594844)])
def test_prius_floor_accepted_field_retains_both_actual_residuals(rhs, initial):
    info = field(rhs, initial)
    before = copy.deepcopy(info)
    result = audit_newton_residual(info)
    assert result["history_final_residual"] > 1e-8
    assert result["rhs_scaled_residual"] == rhs < 1e-8
    assert result["native_stopping_test_pass"]
    assert info == before


def test_native_relative_convergence_does_not_waive_rhs_protocol_limit():
    result = audit_newton_residual(field(rhs=2e-8, initial=100))
    assert result["native_stopping_test_pass"]
    assert result["rhs_scaled_residual"] > 1e-8


def test_nonconverged_native_field_is_not_accepted():
    result = audit_newton_residual(field(rhs=2e-8))
    assert not result["native_stopping_test_pass"]


@pytest.mark.parametrize("key,value", [
    ("rhs_scaled_residual", None), ("rhs_scaled_residual", float("nan")),
    ("rhs_scaled_residual", float("inf")), ("rhs_scaled_residual", -1e-9),
    ("rhs_scaled_residual", True), ("scaled_residual", 0.),
    ("initial_rhs_scaled_residual", 0.), ("tolerance", 1e-3),
    ("absolute_residual_floor", 1e-6), ("absolute_residual_floor", 0.),
    ("method", "picard"), ("residual_definition", "unknown"), ("stopping_test", "always accept"),
])
def test_invalid_or_relaxed_structured_evidence_is_rejected(key, value):
    info = field()
    info["nonlinear_convergence"][key] = value
    with pytest.raises(ValueError):
        audit_newton_residual(info)


@pytest.mark.parametrize("history", [[], [float("nan")], [-1e-8], [True], [1e-10]])
def test_invalid_or_inconsistent_history_is_rejected(history):
    info = field()
    info["nonlinear_residual_history"] = history
    with pytest.raises(ValueError):
        audit_newton_residual(info)


def test_missing_record_requires_explicit_legacy_opt_in():
    info = field()
    del info["nonlinear_convergence"]
    with pytest.raises(ValueError, match="Missing structured"):
        audit_newton_residual(info)
    result = audit_newton_residual(info, legacy_rhs_history=True)
    assert result["rhs_scaled_residual"] == info["nonlinear_residual_history"][-1]
    assert result["native_stopping_test_pass"] is None
    assert result["history_basis"] == "L2(f)"


def test_legacy_opt_in_cannot_hide_a_bad_present_record():
    info = field()
    info["nonlinear_convergence"]["residual_definition"] = "unknown"
    with pytest.raises(ValueError):
        audit_newton_residual(info, legacy_rhs_history=True)
