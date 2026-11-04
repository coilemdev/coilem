"""Read-only convergence presentation shared by the public UI, PDF and CSV.

Never infer residuals or limits from iteration counts or today's solver defaults.
Picard permeability mismatch and Newton equation residuals stay separate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from statistics import median
from sys import float_info
from typing import Any

from pydantic import ValidationError

from backend.models.result import NonlinearConvergence

ITERATION_WARNING_FRACTION = 0.8
CONVERGENCE_REPORT_SCHEMA = "coilem.solver_convergence.v1"
CONVERGENCE_NOTES = (
    "Review convergence at 80% of any total or per-stage iteration limit, or when the final stopping ratio exceeds 1.",
    "Picard uses the final unrelaxed permeability mismatch. Newton uses its recorded relative equation residual "
    "or absolute RHS-scaled floor; either passing test satisfies its stopping rule.",
    "Iteration statistics exclude reused fields and linear solves. Convergence does not establish mesh accuracy or benchmark qualification.",
)


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value: Any) -> str:
    return f"{value:.4g}" if _finite(value) else "Not recorded"


def _row(key: str, label: str, value: Any) -> dict:
    return {"key": key, "label": label, "value": str(value) if value is not None else "Not recorded"}


def _values(values: list) -> str:
    return ", ".join(_number(v) for v in sorted(set(values))) or "Not recorded"


def _stopping_ratio(record: dict) -> float | None:
    residual = record["raw_max_residual"] if record["method"] == "picard" else record["scaled_residual"]
    ratios = []
    if residual is not None and record["tolerance"] > 0:
        ratios.append(residual / record["tolerance"])
    if record["method"] == "newton" and record["absolute_residual_floor"] and record["rhs_scaled_residual"] is not None:
        ratios.append(record["rhs_scaled_residual"] / record["absolute_residual_floor"])
    # Keep JSON finite for an extreme but valid historical tolerance. A ratio
    # above the floating-point range still unambiguously requires review.
    return min(min(ratios), float_info.max) if ratios else None


def convergence_report(result: Mapping[str, Any]) -> dict[str, Any]:
    """Describe only recorded evidence, without modifying the result or inputs."""
    metadata = _mapping(result.get("solve_metadata"))
    positions = []
    for sweep, waveform in (("loaded", "torque_waveform"), ("no_load", "back_emf_waveform")):
        records = _list(result.get(f"{sweep}_nonlinear_convergence"))
        computed_flag = "torque_sweep_computed" if sweep == "loaded" else "back_emf_computed"
        if metadata.get(computed_flag) is False and not records:
            # Omitted sweeps can retain aligned legacy iteration placeholders.
            continue
        counts = _list(result.get(f"{sweep}_nonlinear_iterations"))
        angles = _list(_mapping(result.get(waveform)).get("electrical_angle_deg"))
        size = max(len(records), len(counts), len(angles))
        for index in range(size):
            raw = records[index] if index < len(records) else None
            try:
                record = NonlinearConvergence.model_validate(raw).model_dump(mode="json")
            except (ValidationError, TypeError, ValueError):
                record = None
            ratio = _stopping_ratio(record) if record and record["method"] != "linear" else None
            fraction = None
            if record and record["method"] != "linear":
                fraction = max(
                    [
                        record["iterations"] / record["max_iterations"],
                        *(v / record["stage_iteration_cap"] for v in record["stage_iterations"]),
                    ]
                )
            positions.append(
                {
                    "sweep": sweep,
                    "index": index,
                    # Native no-load and expanded public waveform grids can differ.
                    # A position index is preferable to an incorrectly paired angle.
                    "electrical_angle_deg": angles[index]
                    if len(angles) == size and (not records or len(records) == size) and _finite(angles[index])
                    else None,
                    "record": record,
                    "stopping_ratio": ratio,
                    "iteration_fraction": fraction,
                    "review": fraction is not None and fraction >= ITERATION_WARNING_FRACTION or ratio is not None and ratio > 1,
                }
            )

    recorded = [p for p in positions if p["record"] is not None]
    nonlinear = [p for p in recorded if p["record"]["method"] != "linear"]
    solved = [p["record"]["iterations"] for p in nonlinear if not p["record"]["solution_reused"]]
    missing = len(positions) - len(recorded)
    near_cap = sum(p["iteration_fraction"] is not None and p["iteration_fraction"] >= ITERATION_WARNING_FRACTION for p in nonlinear)
    above_threshold = sum(p["stopping_ratio"] is not None and p["stopping_ratio"] > 1 for p in nonlinear)
    missing_residual = sum(p["stopping_ratio"] is None for p in nonlinear)
    warnings = []
    if near_cap:
        warnings.append(f"{near_cap} position{'s' if near_cap != 1 else ''} reached at least 80% of a total or per-stage iteration limit.")
    if above_threshold:
        warnings.append(f"{above_threshold} position{'s' if above_threshold != 1 else ''} finished above their recorded stopping thresholds.")
    if recorded and missing:
        warnings.append(f"Convergence records are missing for {missing} position{'s' if missing != 1 else ''}; their limits cannot be checked.")
    if missing_residual:
        warnings.append(f"Final residual evidence is missing for {missing_residual} nonlinear position{'s' if missing_residual != 1 else ''}.")

    status = "not_recorded" if not recorded else "review" if near_cap or above_threshold else "partial" if missing or missing_residual else "ok"
    label = {"not_recorded": "Not recorded", "review": "Review convergence", "partial": "Incomplete records", "ok": "Within recorded limits"}[status]
    if status == "ok" and not nonlinear:
        label = "Linear solves"
    plan = {"quick": "Preview", "standard": "Standard", "fine": "High accuracy", "custom": "Custom"}.get(metadata.get("solve_quality"))
    iteration_text = f"{max(solved)} / {_number(median(solved))}" if solved else "Not applicable" if recorded and not nonlinear else "Not recorded"
    summary = [
        _row("accuracy_plan", "Accuracy plan", plan),
        _row("mesh_density", "Mesh density", metadata.get("mesh_density")),
        _row("mesh_elements", "Mesh elements", metadata.get("mesh_element_count")),
        _row("iterations_max_median", "Iterations (max / median)", iteration_text),
        _row("recorded_positions", "Recorded / expected positions", f"{len(recorded)} / {len(positions)}" if positions else None),
        _row("reused_positions", "Reused fields", sum(p["record"]["solution_reused"] for p in recorded)),
    ]
    methods = []
    for method, title in (("picard", "Picard"), ("newton", "Newton")):
        points = [p for p in nonlinear if p["record"]["method"] == method]
        if not points:
            continue
        records = [p["record"] for p in points]
        residual_field = "raw_max_residual" if method == "picard" else "scaled_residual"
        residuals = [r[residual_field] for r in records if r[residual_field] is not None]
        ratios = [p["stopping_ratio"] for p in points if p["stopping_ratio"] is not None]
        residual_label = "Final unrelaxed mismatch (max)" if method == "picard" else "Final relative equation residual (max)"
        methods.append(
            {
                "method": method,
                "label": title,
                "summary": [
                    _row("final_residual_max", residual_label, _number(max(residuals)) if residuals else None),
                    _row("stopping_ratio_max", "Final stopping ratio (max)", _number(max(ratios)) if ratios else None),
                ],
                "details": [
                    _row("tolerances", "Recorded tolerance(s)", _values([r["tolerance"] for r in records])),
                    _row("iteration_caps", "Total iteration limit(s)", _values([r["max_iterations"] for r in records])),
                    _row("stage_iteration_caps", "Per-stage iteration limit(s)", _values([r["stage_iteration_cap"] for r in records])),
                    _row(
                        "absolute_floors",
                        "Absolute RHS-scaled floor(s)",
                        "Not applicable"
                        if method == "picard"
                        else _values([r["absolute_residual_floor"] for r in records if r["absolute_residual_floor"] is not None]),
                    ),
                    _row("residual_definitions", "Residual definition(s)", "; ".join(sorted({r["residual_definition"] for r in records}))),
                    _row("stopping_tests", "Stopping test(s)", "; ".join(sorted({r["stopping_test"] for r in records}))),
                ],
            }
        )
    return {
        "schema_version": CONVERGENCE_REPORT_SCHEMA,
        "status": status,
        "status_label": label,
        "summary": summary,
        "methods": methods,
        "warnings": warnings,
        "notes": list(CONVERGENCE_NOTES),
        "positions": positions,
    }
