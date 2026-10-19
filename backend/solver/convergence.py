"""Map recorded native convergence without inventing evidence for saved runs."""

from statistics import median

from backend.models.result import NonlinearConvergence


def convergence_fields(sweep: dict) -> tuple[dict, dict]:
    """Return result and metadata fields, retaining missing positions as null.

    Iteration summaries exclude congruence-reused solutions. Mismatch summaries
    include them because their source field's convergence still applies.
    Threshold settings are labelled by method and residual definition. For
    Newton's OR stopping test, use the smaller relative/floor threshold ratio.
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
    mismatches = []
    ratios = []
    for value in nonlinear:
        mismatch = value.raw_max_residual if value.method == "picard" else value.scaled_residual
        if mismatch is not None and value.tolerance > 0:
            mismatches.append(mismatch)
            ratio = mismatch / value.tolerance
            if value.method == "newton" and value.rhs_scaled_residual is not None and value.absolute_residual_floor is not None:
                ratio = min(ratio, value.rhs_scaled_residual / value.absolute_residual_floor)
            ratios.append(ratio)
    settings = sorted({(v.method, v.residual_definition, v.tolerance, v.absolute_residual_floor) for v in nonlinear},
                      key=lambda setting: (*setting[:3], setting[3] or 0))
    return result, {
        "nonlinear_tolerance": settings[0][2] if len(settings) == 1 else None,
        "nonlinear_tolerance_method": settings[0][0] if len(settings) == 1 else None,
        "nonlinear_tolerance_settings": [dict(method=method, residual_definition=definition, tolerance=tolerance,
                                              absolute_residual_floor=floor) for method, definition, tolerance, floor in settings] or None,
        "nonlinear_max_iterations_used": max(solved) if solved else None,
        "nonlinear_median_iterations": median(solved) if solved else None,
        "nonlinear_worst_final_mismatch": max(mismatches, default=None),
        "nonlinear_worst_tolerance_ratio": max(ratios, default=None),
        "nonlinear_residual_definitions": sorted({v.residual_definition for v in nonlinear}),
    }
