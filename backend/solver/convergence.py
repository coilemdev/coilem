"""Map recorded native convergence without inventing evidence for saved runs."""

from statistics import median

from backend.models.result import NonlinearConvergence


def convergence_fields(sweep: dict) -> tuple[dict, dict]:
    """Return result and metadata fields, retaining missing positions as null.

    Iteration summaries exclude congruence-reused solutions. Mismatch summaries
    include them because their source field's convergence still applies.
    Different residual definitions are named explicitly; the tolerance ratio
    is the comparable warning quantity (above 1 means above its threshold).
    """
    result = {}
    records = []
    for kind in ("loaded", "no_load"):
        key = f"{kind}_nonlinear_convergence"
        values = sweep.get(key)
        result[key] = [NonlinearConvergence.model_validate(v) if v is not None else None for v in values] if isinstance(values, list) else None
        records.extend(v for v in result[key] or [] if v is not None)
        iteration_key = f"{kind}_nonlinear_iterations"
        result[iteration_key] = sweep.get(iteration_key)
    if not records:
        return result, {"nonlinear_tolerance": None}
    nonlinear = [v for v in records if v.method != "linear"]
    solved = [v.iterations for v in nonlinear if not v.solution_reused]
    mismatches = [(v.raw_max_residual if v.method == "picard" else v.scaled_residual, v.tolerance) for v in nonlinear]
    mismatches = [(value, tol) for value, tol in mismatches if value is not None and tol > 0]
    # Echo the actual recorded tolerance, including the Newton-specific one.
    tolerances = {v.tolerance for v in nonlinear}
    return result, {
        "nonlinear_tolerance": next(iter(tolerances)) if len(tolerances) == 1 else None,
        "nonlinear_max_iterations_used": max(solved) if solved else None,
        "nonlinear_median_iterations": median(solved) if solved else None,
        "nonlinear_worst_final_mismatch": max((v for v, _ in mismatches), default=None),
        "nonlinear_worst_tolerance_ratio": max((v / tol for v, tol in mismatches), default=None),
        "nonlinear_residual_definitions": sorted({v.residual_definition for v in nonlinear}),
    }
