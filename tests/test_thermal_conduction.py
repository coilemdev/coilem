"""Frozen conduction registration and synthetic FEMM bundle status gates."""

import copy
import hashlib

import pytest

from backend.benchmark_suite.thermal_conduction import NODES, area_average, check_conduction, registration, request_for_case
from backend.resources import data_file


def test_registration_is_frozen_and_covers_both_winding_layouts():
    spec = registration()
    assert (spec["relative_band"], spec["absolute_floor_K"], spec["mesh_relative_band"], spec["mesh_floor_K"]) == (0.1, 2, 0.01, 0.2)
    assert len(spec["cases"]) == 6
    for case in spec["cases"]:
        assert hashlib.sha256(data_file(case["fixture"]).read_bytes()).hexdigest() == case["fixture_sha256"]
        request = request_for_case(case)
        assert abs(request["energy_balance_error_W"]) < 1e-9
        assert request["rejected_heat_W"] == pytest.approx(sum(case["heat_W"].values()))
        assert check_conduction(request)["status"] == "NOT_COMPARED"
        for node in NODES:
            assert request["prediction_C"][node] > spec["boundary_C"]
        assert all(r["source_W_m3"] >= 0 for r in request["regions"])


def bundle(request, error=0):
    rows = [dict(node=node, area_m2=request["areas_m2"][node], mean_temperature_C=request["prediction_C"][node] + error) for node in NODES]
    return dict(case_id=request["case_id"], request_sha256=request["request_sha256"], solver="FEMM 4.2 heat flow",
                solver_build="Synthetic unit test", raw_artifact_sha256="a" * 64, boundary_C=request["boundary_C"],
                regions=rows, coarse_regions=copy.deepcopy(rows))


@pytest.mark.parametrize("error,expected", [(0, "PASS"), (3, "YELLOW"), (20, "FAIL")])
def test_synthetic_status_bands(error, expected):
    request = request_for_case(registration()["cases"][0])
    request["prediction_C"] = {node: 30 for node in NODES}
    verdict = check_conduction(request, bundle(request, error))
    assert verdict["status"] == expected
    assert verdict["output_status"] == "experimental"
    assert len(verdict["metrics"]) == 3


def test_reference_geometry_identity_and_mesh_must_match():
    request = request_for_case(registration()["cases"][0])
    reference = bundle(request)
    reference["request_sha256"] = "different"
    with pytest.raises(ValueError, match="frozen request"):
        check_conduction(request, reference)
    reference = bundle(request)
    reference["regions"][0]["area_m2"] *= 2
    with pytest.raises(ValueError, match="area"):
        check_conduction(request, reference)
    reference = bundle(request)
    reference["coarse_regions"][0]["mean_temperature_C"] += 10
    assert check_conduction(request, reference)["status"] == "FAIL"


def test_both_sides_use_area_weighted_region_means():
    rows = [dict(node="winding", area_m2=1, mean_temperature_C=20), dict(node="winding", area_m2=3, mean_temperature_C=40)]
    assert area_average(rows, "winding", 4) == 35


def test_legacy_and_corrected_requests_keep_distinct_identities_and_the_same_frozen_problem():
    for case in registration()["cases"]:
        legacy = request_for_case(case, candidate_model="legacy_mean_paths_v1")
        current = request_for_case(case)
        assert "slabs" not in legacy["network"] and "candidate_model" not in legacy
        assert current["candidate_model"] == "surface_mean_v2" and len(current["network"]["slabs"]) == 2
        for key in ("registration_sha256","fixture_sha256","boundary_C","conductivity_W_mK","heat_W","areas_m2","regions"):
            assert legacy[key] == current[key]
        assert legacy["request_sha256"] != current["request_sha256"]
        with pytest.raises(ValueError, match="frozen request"):
            check_conduction(current, bundle(legacy))
        assert check_conduction(legacy, bundle(legacy))["status"] == "PASS"
