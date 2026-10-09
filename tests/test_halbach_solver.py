"""HAL-04/HAL-08 analytical, invariant, and report gates."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from functools import lru_cache
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend.gmsh_solver import GMSH_AVAILABLE
from backend.halbach.models import HalbachArrayConfig
from backend.halbach.postprocess import segmented_analytical_factor
from backend.halbach.solver import (
    HALBACH_REPORT_SCHEMA,
    HALBACH_SCHEMA_REGISTRY,
    solve_halbach,
)
from backend.magneto2d_adapter import MAGNETO2D_BINARY

ROOT = Path(__file__).parents[1]
BASE = json.loads(
    (
        ROOT / "schemas" / "v1" / "examples" / "halbach_array_16_segment.json"
    ).read_text(encoding="utf-8")
)

requires_solver = pytest.mark.skipif(
    not GMSH_AVAILABLE
    or not (Path(MAGNETO2D_BINARY).exists() or shutil.which("cargo")),
    reason="Gmsh and a Magneto2D binary or Cargo are required",
)

PRESETS = {
    "quick": {
        "density": "coarse",
        "outer_boundary_radius_factor": 3.0,
        "minimum_elements_across_magnet": 3,
        "tolerance": 1.0e-7,
        "radial_samples": 17,
        "angular_samples": 48,
    },
    "standard": {
        "density": "normal",
        "outer_boundary_radius_factor": 4.0,
        "minimum_elements_across_magnet": 6,
        "tolerance": 1.0e-8,
        "radial_samples": 31,
        "angular_samples": 96,
    },
    "fine": {
        "density": "fine",
        "outer_boundary_radius_factor": 6.0,
        "minimum_elements_across_magnet": 10,
        "tolerance": 1.0e-9,
        "radial_samples": 61,
        "angular_samples": 192,
    },
}


def _reference_payload(
    *,
    segments: int = 16,
    quality: str = "quick",
    direction_deg: float = 0.0,
    scale: float = 1.0,
    br_t: float = 1.3,
    outer_boundary_factor: float | None = None,
) -> dict:
    payload = copy.deepcopy(BASE)
    payload["geometry"].update(
        {
            "inner_radius": 25.0 * scale,
            "outer_radius": 50.0 * scale,
            "axial_length": 100.0 * scale,
            "segment_count": segments,
            "segment_gap_angle": 0.0,
        }
    )
    payload["array"]["field_direction"] = direction_deg
    payload["sample_region"].update(
        {
            "radius": 15.0 * scale,
            "leakage_probe_radius": 75.0 * scale,
        }
    )
    payload["magnet"] = {
        "source": "custom",
        "name": "N42-equivalent linear analytical reference",
        "remanence_t": br_t,
        "relative_permeability": 1.0,
        "intrinsic_coercivity_a_per_m": 955_000.0,
        "density_kg_per_m3": 7450.0,
        "reference_temperature_c": 20.0,
        "temperature_c": 20.0,
        "alpha_br_per_k": -0.0012,
        "alpha_hcj_per_k": -0.0055,
        "source_note": "HAL analytical reference fixture",
    }
    preset = PRESETS[quality]
    payload["solve"]["quality"] = quality
    payload["solve"]["mesh"].update(
        {
            "density": preset["density"],
            "outer_boundary_radius_factor": (
                outer_boundary_factor
                if outer_boundary_factor is not None
                else preset["outer_boundary_radius_factor"]
            ),
            "minimum_elements_across_magnet": preset[
                "minimum_elements_across_magnet"
            ],
        }
    )
    payload["solve"]["linear"]["tolerance"] = preset["tolerance"]
    payload["sample_region"].update(
        {
            "radial_samples": preset["radial_samples"],
            "angular_samples": preset["angular_samples"],
        }
    )
    if outer_boundary_factor is not None:
        payload["solve"]["quality"] = "custom"
    return payload


@lru_cache(maxsize=32)
def _solve_cached(serialized: str) -> dict:
    payload = json.loads(serialized)
    return solve_halbach(
        HalbachArrayConfig.model_validate(payload)
    ).halbach_report


def _solve(payload: dict) -> dict:
    return _solve_cached(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )


@requires_solver
@pytest.mark.parametrize(
    ("segments", "quality", "limit_pct"),
    [
        (8, "quick", 5.0),
        (16, "standard", 2.0),
        (16, "fine", 1.0),
        (32, "fine", 1.0),
    ],
)
def test_analytical_segmented_field_gates(
    segments: int, quality: str, limit_pct: float
) -> None:
    report = _solve(_reference_payload(segments=segments, quality=quality))
    bore = report["bore_field"]
    assert bore["b_parallel_t"]["mean"] > 0.0
    assert abs(bore["mean_field_direction_error_deg"]) < 1.0
    assert abs(bore["solved_vs_segmented_delta_pct"]) <= limit_pct


@requires_solver
def test_32_segment_fine_is_closer_to_continuous_ideal_than_16_segment() -> None:
    sixteen = _solve(_reference_payload(segments=16, quality="fine"))[
        "bore_field"
    ]
    thirty_two = _solve(_reference_payload(segments=32, quality="fine"))[
        "bore_field"
    ]
    assert abs(
        thirty_two["b_parallel_t"]["mean"]
        - thirty_two["ideal_continuous_estimate_t"]
    ) < abs(
        sixteen["b_parallel_t"]["mean"]
        - sixteen["ideal_continuous_estimate_t"]
    )


@requires_solver
@pytest.mark.parametrize("direction_deg", [0.0, 30.0, 90.0])
def test_rotation_covariance(direction_deg: float) -> None:
    report = _solve(
        _reference_payload(
            segments=16, quality="quick", direction_deg=direction_deg
        )
    )
    bore = report["bore_field"]
    assert abs(bore["mean_field_direction_error_deg"]) < 0.5
    baseline = _solve(
        _reference_payload(segments=16, quality="quick", direction_deg=0.0)
    )["bore_field"]["b_parallel_t"]["mean"]
    assert bore["b_parallel_t"]["mean"] == pytest.approx(baseline, rel=2.0e-3)


@requires_solver
def test_seam_rotation_preserves_requested_field_direction() -> None:
    baseline_payload = _reference_payload(segments=9, quality="quick")
    rotated_payload = copy.deepcopy(baseline_payload)
    rotated_payload["geometry"]["segment_start_angle"] = 13.0
    baseline = _solve(baseline_payload)["bore_field"]
    rotated = _solve(rotated_payload)["bore_field"]
    assert abs(rotated["mean_field_direction_error_deg"]) < 0.5
    assert rotated["b_parallel_t"]["mean"] == pytest.approx(
        baseline["b_parallel_t"]["mean"], rel=3.0e-3
    )


@requires_solver
def test_contour_segments_carry_solver_direction_cues() -> None:
    report = _solve(_reference_payload(segments=8, quality="quick"))
    contours = report["field_data"]["contours"]
    assert contours
    for level in contours:
        count = len(level["segments_mm"])
        assert len(level["segment_bx_t"]) == count
        assert len(level["segment_by_t"]) == count
        assert len(level["segment_b_mag_t"]) == count
        assert all(value >= 0.0 for value in level["segment_b_mag_t"])


@requires_solver
def test_geometric_scale_invariance() -> None:
    small = _solve(_reference_payload(quality="quick", scale=0.5))["bore_field"]
    large = _solve(_reference_payload(quality="quick", scale=2.0))["bore_field"]
    assert large["b_parallel_t"]["mean"] == pytest.approx(
        small["b_parallel_t"]["mean"], rel=2.0e-3
    )
    assert large["b_magnitude_t"]["mean"] == pytest.approx(
        small["b_magnitude_t"]["mean"], rel=2.0e-3
    )


@requires_solver
@pytest.mark.parametrize("scale_factor", [0.5, 1.5])
def test_remanence_linearity(scale_factor: float) -> None:
    baseline = _solve(_reference_payload(quality="quick", br_t=1.3))[
        "bore_field"
    ]["b_parallel_t"]["mean"]
    scaled = _solve(
        _reference_payload(quality="quick", br_t=1.3 * scale_factor)
    )["bore_field"]["b_parallel_t"]["mean"]
    assert scaled == pytest.approx(baseline * scale_factor, rel=5.0e-4)


@requires_solver
def test_mesh_and_outer_boundary_convergence_gates() -> None:
    standard = _solve(_reference_payload(quality="standard"))
    fine = _solve(_reference_payload(quality="fine"))
    enlarged = _solve(
        _reference_payload(quality="standard", outer_boundary_factor=5.0)
    )
    standard_mean = standard["bore_field"]["b_parallel_t"]["mean"]
    fine_mean = fine["bore_field"]["b_parallel_t"]["mean"]
    enlarged_mean = enlarged["bore_field"]["b_parallel_t"]["mean"]
    assert abs(fine_mean - standard_mean) / abs(fine_mean) <= 0.01
    assert abs(enlarged_mean - standard_mean) / abs(standard_mean) <= 0.005
    standard_leakage = standard["external_leakage"]["rms_b_t"]
    fine_leakage = fine["external_leakage"]["rms_b_t"]
    assert (
        abs(fine_leakage - standard_leakage)
        <= max(0.05 * abs(fine_leakage), 2.0e-4)
    )
    convergence = fine["bore_field"]["convergence"]
    assert convergence["boundary_sensitivity_rerun"] is True
    assert convergence["enlarged_outer_boundary_radius_factor"] == pytest.approx(
        7.5
    )
    assert abs(convergence["mean_b_parallel_change_pct"]) <= 0.5


@requires_solver
def test_report_contract_provenance_and_non_motor_boundary() -> None:
    report = _solve(_reference_payload(quality="quick"))
    Draft202012Validator(
        HALBACH_REPORT_SCHEMA, registry=HALBACH_SCHEMA_REGISTRY
    ).validate(report)
    assert report["model"]["axial_end_effects_modeled"] is False
    assert "axial end effects" in report["model"]["notice"].lower()
    assert report["artifacts"]["magnetostatic_problem_sha256"]
    assert report["generic_field_report"]["openem_schema_kind"] == (
        "field_solution_report"
    )
    assert report["magnet"]["demagnetization_screening"]["label"] == (
        "screening diagnostic — not a demagnetization certification"
    )
    assert report["magnet"]["demagnetization_screening"]["margin_eligible"] is True
    serialized = json.dumps(report).lower()
    for forbidden_key in ('"torque"', '"winding"', '"rpm"', '"back_emf"'):
        assert forbidden_key not in serialized


@requires_solver
def test_axial_length_scales_only_extruded_outputs() -> None:
    base_payload = _reference_payload(quality="quick")
    long_payload = copy.deepcopy(base_payload)
    long_payload["geometry"]["axial_length"] *= 2.5
    base = _solve(base_payload)
    long = _solve(long_payload)
    assert base["artifacts"]["magnetostatic_problem_sha256"] == (
        long["artifacts"]["magnetostatic_problem_sha256"]
    )
    assert base["generic_field_report"]["solution"]["az_nodal"] == (
        long["generic_field_report"]["solution"]["az_nodal"]
    )
    assert base["generic_field_report"]["solution"]["element_fields"] == (
        long["generic_field_report"]["solution"]["element_fields"]
    )
    assert long["magnet"]["volume_m3"] == pytest.approx(
        base["magnet"]["volume_m3"] * 2.5
    )
    assert long["magnet"]["mass_kg"] == pytest.approx(
        base["magnet"]["mass_kg"] * 2.5
    )
    assert long["energy"]["magnetic_energy_extruded_2d_estimate_j"] == pytest.approx(
        base["energy"]["magnetic_energy_extruded_2d_estimate_j"] * 2.5
    )


def test_closed_form_estimate_matches_documented_reference() -> None:
    ideal = 1.3 * math.log(2.0)
    segmented = ideal * math.sin(2 * math.pi / 16) / (2 * math.pi / 16)
    assert segmented == pytest.approx(0.8781093231908217)


def test_gapped_segmented_estimate_integrates_over_actual_magnet_span() -> None:
    sinc_span, coverage = segmented_analytical_factor(8, 9.0)
    span_rad = math.radians(36.0)
    assert coverage == pytest.approx(0.8)
    assert sinc_span == pytest.approx(math.sin(span_rad) / span_rad)
    assert (
        1.3 * math.log(2.0) * sinc_span * coverage
    ) == pytest.approx(0.6743690298822232)


@requires_solver
def test_gapped_solve_matches_corrected_segmented_estimate() -> None:
    payload = _reference_payload(segments=8, quality="quick")
    payload["geometry"]["segment_gap_angle"] = 9.0
    report = _solve(payload)
    assert abs(report["bore_field"]["solved_vs_segmented_delta_pct"]) <= 1.0


@requires_solver
def test_minimal_custom_magnet_solves_without_null_schema_fields() -> None:
    payload = _reference_payload(quality="quick")
    payload["magnet"] = {
        "source": "custom",
        "name": "Minimal custom magnet",
        "remanence_t": 1.3,
        "source_note": "User-supplied linear reference",
    }
    report = _solve(payload)
    embedded = report["configuration"]["magnet"]
    assert "intrinsic_coercivity_a_per_m" not in embedded
    assert "density_kg_per_m3" not in embedded
    assert report["magnet"]["mass_kg"] is None
    assert report["magnet"]["demagnetization_screening"]["margin_eligible"] is False
    assert any("Custom material has no intrinsic coercivity" in warning for warning in report["warnings"])
    Draft202012Validator(
        HALBACH_REPORT_SCHEMA, registry=HALBACH_SCHEMA_REGISTRY
    ).validate(report)


@requires_solver
def test_retained_problem_bytes_match_both_recorded_input_hashes(
    tmp_path: Path,
) -> None:
    artifacts = solve_halbach(
        HalbachArrayConfig.model_validate(
            _reference_payload(segments=8, quality="quick")
        ),
        artifact_directory=tmp_path,
    )
    retained = tmp_path / "magnetostatic_problem.json"
    retained_hash = hashlib.sha256(retained.read_bytes()).hexdigest()
    report = artifacts.halbach_report
    assert retained_hash == artifacts.magnetostatic_problem_sha256
    assert retained_hash == report["artifacts"]["generic_field_report_input_sha256"]
    assert retained_hash == report["artifacts"]["magnetostatic_problem_sha256"]
    assert b"\n" not in retained.read_bytes()
    assert json.loads(retained.read_bytes()) == artifacts.magnetostatic_problem
