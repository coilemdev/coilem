"""Real Magneto2D one-sided-field and report-contract gates."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend.gmsh_solver import GMSH_AVAILABLE
from backend.halbach.linear_geometry import LINEAR_MODEL_NOTICE
from backend.halbach.linear_models import canonical_linear_halbach_config
from backend.halbach.linear_solver import (
    LINEAR_HALBACH_REPORT_SCHEMA,
    LINEAR_HALBACH_SCHEMA_REGISTRY,
    solve_linear_halbach,
)
from backend.magneto2d_adapter import MAGNETO2D_BINARY

ROOT = Path(__file__).parents[1]
requires_solver = pytest.mark.skipif(
    not GMSH_AVAILABLE
    or not (Path(MAGNETO2D_BINARY).exists() or shutil.which("cargo")),
    reason="Gmsh and a Magneto2D binary or Cargo are required",
)


def _standard_config(strong_side: str):
    config = canonical_linear_halbach_config()
    config.array.strong_side = strong_side
    config.solve.field_line_count = 4
    return config


@pytest.fixture(scope="module")
def mirrored_reports() -> tuple[dict, dict]:
    if not GMSH_AVAILABLE or not (
        Path(MAGNETO2D_BINARY).exists() or shutil.which("cargo")
    ):
        pytest.skip("Gmsh and Magneto2D are required")
    positive = solve_linear_halbach(
        _standard_config("positive_y")
    ).linear_halbach_report
    negative = solve_linear_halbach(
        _standard_config("negative_y")
    ).linear_halbach_report
    return positive, negative


@requires_solver
def test_selected_side_is_strong_and_report_validates(
    mirrored_reports: tuple[dict, dict],
) -> None:
    for report in mirrored_reports:
        Draft202012Validator(
            LINEAR_HALBACH_REPORT_SCHEMA,
            registry=LINEAR_HALBACH_SCHEMA_REGISTRY,
        ).validate(report)
        working = report["working_field"]["b_magnitude_t"]["rms"]
        leakage = report["leakage_field"]["b_magnitude_t"]["rms"]
        assert working > 5.0 * leakage
        assert report["one_sidedness"]["leakage_ratio_rms"] == pytest.approx(
            leakage / working
        )
        assert report["model"]["notice"] == LINEAR_MODEL_NOTICE
        assert "bore_field" not in report
        assert "external_leakage" not in report


@requires_solver
def test_flipping_strong_side_mirrors_metrics_and_preserves_mesh(
    mirrored_reports: tuple[dict, dict],
) -> None:
    positive, negative = mirrored_reports
    positive_working = positive["working_field"]["b_magnitude_t"]["rms"]
    negative_working = negative["working_field"]["b_magnitude_t"]["rms"]
    positive_leakage = positive["leakage_field"]["b_magnitude_t"]["rms"]
    negative_leakage = negative["leakage_field"]["b_magnitude_t"]["rms"]
    # The independent analytical oracle freezes exact reflection symmetry.
    # This real-solver gate allows the small asymmetry introduced by an
    # unstructured finite mesh, especially on the near-zero weak side.
    assert negative_working == pytest.approx(positive_working, rel=3.0e-2)
    assert negative_leakage == pytest.approx(positive_leakage, rel=8.0e-2)
    assert positive["artifacts"]["mesh_hash"] == negative["artifacts"]["mesh_hash"]
    assert (
        positive["artifacts"]["magnetostatic_problem_sha256"]
        != negative["artifacts"]["magnetostatic_problem_sha256"]
    )
    assert positive["working_field"]["line_y_mm"] == pytest.approx(
        -negative["working_field"]["line_y_mm"]
    )
    assert len(positive["field_data"]["triangles"]) == len(
        positive["field_data"]["element_fields_t"]
    )
    assert len(positive["field_data"]["nodes_mm"]) == len(
        positive["field_data"]["az_nodal_t_m"]
    )
    assert json.dumps(positive).lower().count('"bore"') == 0
