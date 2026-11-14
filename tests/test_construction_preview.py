"""An unfinished winding must not hide valid iron/magnets or become solvable."""

import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.public_main import app


def unfinished_motor():
    path = Path(__file__).parent / "fixtures" / "spm_4p12s_simple.json"
    config = json.loads(path.read_text())
    config["stator"].update(OD_mm=150, ID_mm=90, slot_count=15, yoke_thickness_mm=8, tooth_width_mm=11.5)
    config["rotor"].update(OD_mm=80, ID_mm=20, pole_count=6, magnet_thickness_mm=3.5,
                           magnet_width_mm=2 * math.pi * 41.75 / 6 * 0.75)
    config["winding"].update(type="concentrated", layers=2, parallel_paths=1)
    return config


def test_construction_draws_the_requested_poles_without_inventing_a_winding():
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post("/preview?construction=true", json=unfinished_motor())
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["metadata"]["pole_count"] == 6
    assert preview["metadata"]["construction_only"] is True
    assert len([r for r in preview["regions"] if r["region_type"].startswith("magnet_")]) == 6
    assert not any(any(token in r["region_type"] for token in ("slot", "coil", "winding")) for r in preview["regions"])
    assert preview["winding_layout"] == preview["winding_coils"] == []
    assert "winding_resistance" not in preview["metadata"]
    assert "qualification" not in preview["metadata"]
    assert not {"coil_span_label", "coil_span_slots", "mmf_harmonics"} & preview["metadata"].keys()
    assert any("winding" in issue["message"].lower() for issue in preview["validation_errors"])


@pytest.mark.parametrize("route", ["/preview", "/solve/validate", "/solve/validate?construction=true"])
def test_construction_does_not_bypass_normal_winding_gates(route):
    response = TestClient(app, base_url="http://127.0.0.1").post(route, json=unfinished_motor())
    if route.startswith("/solve/validate"):
        assert response.status_code == 200, response.text
        assert response.json()["valid"] is False
        assert any("winding" in error["message"].lower() for error in response.json()["errors"])
    else:
        assert response.status_code == 400, response.text
        assert "winding" in response.json()["detail"]["message"].lower()


def test_construction_still_rejects_magnets_intersecting_the_stator():
    config = unfinished_motor()
    config["rotor"]["magnet_thickness_mm"] = 8
    response = TestClient(app, base_url="http://127.0.0.1").post("/preview?construction=true", json=config)
    assert response.status_code == 400, response.text
    assert "winding" not in response.json()["detail"]["message"].lower()


def test_construction_still_rejects_unsupported_materials():
    config = unfinished_motor()
    config["materials"]["stator_steel"] = "unobtainium"
    response = TestClient(app, base_url="http://127.0.0.1").post("/preview?construction=true", json=config)
    assert response.status_code == 400, response.text
    assert "material" in response.json()["detail"]["field"]


def unfinished_v_ipm():
    config = unfinished_motor()
    config["topology"] = "IPM"
    config["stator"].update(
        ID_mm=70, slot_count=21, yoke_thickness_mm=10, stack_length_mm=100,
        tooth_width_mm=4.1, tooth_shoe_enabled=True, tooth_shoe_height_mm=1,
        tooth_shoe_overhang_mm=0.5, slot_opening_mm=math.pi * 70 / 21 - 4.8 + 1,
    )
    # The large starter's pocket defaults do not fit this unconfigured rotor.
    config["rotor"].update(OD_mm=58, ID_mm=20, pole_count=8, ipm_topology="v_shape",
                           magnet_width_mm=28, magnet_thickness_mm=4,
                           v_angle_deg=40, v_depth_mm=30, inner_web_thickness_mm=6)
    return config


def test_stator_construction_is_independent_of_unconfigured_v_ipm_pockets():
    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/preview?construction=true&stator_only=true", json=unfinished_v_ipm())
    assert response.status_code == 200, response.text
    preview = response.json()
    teeth = [region for region in preview["regions"] if region["region_type"] == "stator_tooth"]
    assert len(teeth) == 21
    assert min(math.hypot(x, y) for tooth in teeth for x, y in tooth["points"]) == pytest.approx(35)
    assert max(math.hypot(x, y) for tooth in teeth for x, y in tooth["points"]) == pytest.approx(65)
    # The actual tooth flanks at each exact face agree with the width metadata.
    for radius, width in [(35, 4.8), (65, 4.1)]:
        angles = [math.atan2(y, x) for x, y in teeth[0]["points"]
                  if math.isclose(math.hypot(x, y), radius, abs_tol=1e-8)]
        assert (max(angles) - min(angles)) * radius == pytest.approx(width)
    assert {region["region_type"] for region in preview["regions"]} == {"stator_yoke", "stator_tooth"}
    assert preview["metadata"]["bore_tooth_width_mm"] == pytest.approx(4.8)
    assert preview["metadata"]["tooth_width_at_yoke_mm"] == pytest.approx(4.1)
    assert preview["metadata"]["construction_parts"] == "stator"
    assert preview["metadata"]["construction_only"] is True
    assert "qualification" not in preview["metadata"]
    assert "winding_resistance" not in preview["metadata"]
    assert preview["winding_layout"] == preview["winding_coils"] == []


@pytest.mark.parametrize("route", [
    "/preview?construction=true", "/preview?stator_only=true", "/solver/mesh-preview?construction=true&stator_only=true",
])
def test_partial_stator_flags_cannot_bypass_complete_motor_validation(route):
    response = TestClient(app, base_url="http://127.0.0.1").post(route, json=unfinished_v_ipm())
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("change", [
    {"tooth_width_mm": 25},
    {"slot_opening_mm": 15},
    {"tooth_shoe_overhang_mm": 4},
    {"yoke_thickness_mm": 45},
])
def test_stator_construction_still_rejects_invalid_stator_dimensions(change):
    config = unfinished_v_ipm()
    config["stator"].update(change)
    response = TestClient(app, base_url="http://127.0.0.1").post(
        "/preview?construction=true&stator_only=true", json=config)
    assert response.status_code == 400, response.text


def test_diagnostic_v_magnets_show_requested_length_outside_the_rotor():
    config = unfinished_v_ipm()
    config["rotor"].update(v_depth_mm=0.1, magnet_width_mm=12, magnet_thickness_mm=4)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post("/preview?construction=true&diagnostic=true", json=config)
    assert response.status_code == 200, response.text
    preview = response.json()
    magnets = [region for region in preview["regions"] if region["region_type"].startswith("magnet_")]
    assert len(magnets) == 16
    for magnet in magnets:
        points = magnet["points"]
        lengths = sorted(math.dist(points[i], points[(i + 1) % 4]) for i in range(4))
        assert lengths == pytest.approx([4, 4, 12, 12])
    assert max(math.hypot(x, y) for magnet in magnets for x, y in magnet["points"]) > 29
    assert preview["metadata"]["diagnostic_only"] is True
    assert preview["metadata"]["diagnostic_rotor"] is True
    assert preview["metadata"]["construction_only"] is True
    assert preview["validation_errors"]
    assert "qualification" not in preview["metadata"]
    assert preview["winding_layout"] == preview["winding_coils"] == []
    # The same invalid motor remains rejected by the real preview/mesh gates.
    for route in ["/preview?construction=true", "/preview?diagnostic=true", "/solver/mesh-preview?diagnostic=true&construction=true"]:
        assert client.post(route, json=config).status_code == 400


def test_diagnostic_depth_suggestion_passes_the_production_validator():
    import re

    from backend.geometry import validate_geometry
    from backend.models import MotorConfig
    config = unfinished_v_ipm()
    config["rotor"].update(OD_mm=65, pole_count=6, v_angle_deg=30, v_depth_mm=0.1, magnet_width_mm=4.7, magnet_thickness_mm=2)
    response = TestClient(app, base_url="http://127.0.0.1").post("/preview?construction=true&diagnostic=true", json=config)
    assert response.status_code == 200, response.text
    errors = response.json()["validation_errors"]
    suggestion = next(error["suggestion"] for error in errors if "try V Depth" in (error["suggestion"] or ""))
    proposed = float(re.search(r"try V Depth ([\d.]+) mm", suggestion).group(1))
    config["rotor"]["v_depth_mm"] = proposed
    assert not any((error.field or "").startswith("rotor.") for error in validate_geometry(MotorConfig.model_validate(config)))


def test_diagnostic_v_magnets_agree_with_shared_geometry_when_valid():
    from backend.geometry_drawer import compute_v_shape_magnet_placements
    from backend.models import MotorConfig
    config = unfinished_v_ipm()
    config["rotor"].update(v_depth_mm=12, magnet_width_mm=5, magnet_thickness_mm=2)
    parsed = MotorConfig.model_validate(config)
    expected = compute_v_shape_magnet_placements(parsed)
    assert all(not magnet.length_clamped_mm for magnet in expected)
    response = TestClient(app, base_url="http://127.0.0.1").post("/preview?construction=true&diagnostic=true", json=config)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["metadata"]["diagnostic_only"] is False
    assert preview["validation_errors"] == []
    magnets = [region for region in preview["regions"] if region["region_type"].startswith("magnet_")]
    for region, magnet in zip(magnets, expected, strict=True):
        for actual, reference in zip(region["points"], magnet.corners_mm, strict=True):
            assert actual == pytest.approx(reference)


@pytest.mark.parametrize("change", [{"tooth_width_mm": 25}, {"yoke_thickness_mm": 45}, {"tooth_shoe_overhang_mm": 4}])
def test_diagnostic_rotor_does_not_bypass_invalid_stator_checks(change):
    config = unfinished_v_ipm()
    config["stator"].update(change)
    response = TestClient(app, base_url="http://127.0.0.1").post("/preview?construction=true&diagnostic=true", json=config)
    assert response.status_code == 400, response.text


def test_flat_diagnostic_bars_keep_the_requested_dimensions_and_require_straight_shape():
    config = unfinished_v_ipm()
    config["rotor"].update(ipm_topology="flat_buried", flat_buried_magnet_shape="straight", magnet_width_mm=8,
                           magnet_thickness_mm=2, bridge_thickness_mm=1.5)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post("/preview?construction=true&diagnostic=true", json=config)
    assert response.status_code == 200, response.text
    magnets = [region for region in response.json()["regions"] if region["region_type"].startswith("magnet_")]
    assert len(magnets) == 8
    for magnet in magnets:
        points = magnet["points"]
        assert sorted(math.dist(points[i], points[(i + 1) % 4]) for i in range(4)) == pytest.approx([2, 2, 8, 8])
    config["rotor"]["flat_buried_magnet_shape"] = "legacy_arc"
    assert client.post("/preview?construction=true&diagnostic=true", json=config).status_code == 400
