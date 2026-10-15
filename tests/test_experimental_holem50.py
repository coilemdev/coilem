"""Experimental HoleM50 rotor path for the ORNL 2004 Prius (#70).

The mapping fits ORNL's lamination drawing within its read-off error, the mapped
rotor builds valid geometry, public requests still reject HoleM50, and only the
non-HTTP research tool can opt in.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIUS_FIXTURE = REPO_ROOT / "benchmarks/main-20261009-bad71d9/fixtures/ornl_prius_2004_ipm.json"
MAPPING = json.loads((REPO_ROOT / "docs/hardware-validation/ornl-prius-2004/holem50-mapping.json").read_text(encoding="utf-8"))
SPM_CONFIG = json.loads((REPO_ROOT / "tests/fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"))
PUBLIC_IPM_MESSAGE = "The public launch supports flat-buried and V-shape IPM only."


def ornl_design() -> dict:
    """The Prius benchmark fixture with the rotor mapped from ORNL's lamination drawing."""

    design = json.loads(PRIUS_FIXTURE.read_text(encoding="utf-8"))
    design["rotor"].update(MAPPING["recommended"]["rotor"])
    return design


def test_mapping_fits_the_drawing_within_the_read_off_error():
    recommended = MAPPING["recommended"]
    fit, rotor = recommended["fit"], recommended["rotor"]
    limit = MAPPING["read_off_error_mm"]["positions"]
    assert fit["rms_mm"] < limit and fit["p95_mm"] < limit
    assert all(abs(feature["mean_signed_mm"]) < limit for feature in fit["per_feature"].values())
    assert fit["rms_mm"] < MAPPING["variants"]["A_pyleecan_toyota_prius"]["rms_mm"]
    # The rotor block is exactly the fitted set, with the bridge at the stated 0.056-0.060 in callouts.
    assert {k: rotor[f"holem50_{k}_mm"] for k in fit["holem50_mm"]} == fit["holem50_mm"]
    assert rotor["holem50_h1_mm"] == round((0.056 + 0.060) / 2 * 25.4, 2)
    assert (rotor["holem50_w1_mm"], rotor["holem50_h4_mm"]) == (0.0, 0.0)
    assert (rotor["magnet_width_mm"], rotor["magnet_thickness_mm"]) == (rotor["holem50_w4_mm"], rotor["holem50_h3_mm"])
    assert (rotor["OD_mm"], rotor["ID_mm"]) == (round(6.314 * 25.4, 2), round(4.356 * 25.4, 2))


def test_mapped_rotor_geometry_is_valid():
    from backend.geometry import validate_geometry
    from backend.geometry_drawer import compute_geometry, point_in_polygon
    from backend.geometry_ir import build_geometry_ir, validate_geometry_ir
    from backend.models import MotorConfig

    config = MotorConfig.model_validate(ornl_design())
    rotor = config.rotor
    assert validate_geometry(config) == []
    geom = compute_geometry(config)
    assert len(geom.magnets) == 2 * rotor.pole_count
    assert len(geom.rotor_air_pockets) == 3 * rotor.pole_count
    report = validate_geometry_ir(build_geometry_ir(config))
    assert report.issues == ()
    assert report.magnet_area_mm2 == pytest.approx(2 * rotor.pole_count * rotor.holem50_w4_mm * rotor.holem50_h3_mm, rel=1e-9)
    # Rotor regions tile the rotor disc: no overlaps and no gaps.
    rotor_kinds = ("RotorCore", "Shaft", "MagnetPocketAir", "Magnet")
    tiled = sum(report.region_area_by_kind_mm2[kind] for kind in rotor_kinds)
    assert tiled == pytest.approx(math.pi * (rotor.OD_mm / 2) ** 2, rel=1e-3)
    # Every hole stays inside the outer bridge and outside the shaft.
    polygons = [m.corners_mm for m in geom.magnets] + [p.corners_mm for p in geom.rotor_air_pockets]
    radii = [math.hypot(x, y) for polygon in polygons for x, y in polygon]
    assert max(radii) == pytest.approx(rotor.OD_mm / 2 - rotor.holem50_h1_mm, abs=1e-6)
    assert min(radii) > rotor.ID_mm / 2
    # Magnets and air pockets do not overlap one another.
    for magnet in geom.magnets:
        cx = sum(x for x, _ in magnet.corners_mm) / len(magnet.corners_mm)
        cy = sum(y for _, y in magnet.corners_mm) / len(magnet.corners_mm)
        assert not any(point_in_polygon(cx, cy, pocket.corners_mm) for pocket in geom.rotor_air_pockets)
    for pocket in geom.rotor_air_pockets:
        x, y = pocket.label_mm
        assert not any(point_in_polygon(x, y, magnet.corners_mm) for magnet in geom.magnets)
        assert sum(point_in_polygon(x, y, other.corners_mm) for other in geom.rotor_air_pockets) == 1


@pytest.mark.parametrize("body", [json.loads(PRIUS_FIXTURE.read_text(encoding="utf-8")), ornl_design()], ids=["fixture", "ornl-mapped"])
def test_public_requests_still_reject_holem50(body):
    from backend.public_policy import PublicConfigError, parse_public_solve_request

    with pytest.raises(PublicConfigError) as caught:
        parse_public_solve_request(body)
    assert str(caught.value) == PUBLIC_IPM_MESSAGE
    assert caught.value.field == "rotor.ipm_topology"


@pytest.mark.parametrize("route", ["/solve/validate", "/solve", "/solver/mesh-preview"])
def test_http_routes_reject_holem50_with_the_public_message(route):
    from backend.public_main import app

    response = TestClient(app, base_url="http://127.0.0.1").post(route, json=ornl_design())
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["message"] == PUBLIC_IPM_MESSAGE
    assert detail["field"] == "rotor.ipm_topology"


def test_only_research_tools_can_enable_experimental_rotors():
    # HTTP routes never pass the opt-in. The research tool does, and the benchmark
    # harness does only for suite cases registered as experimental rotors.
    mentions = {
        path.relative_to(REPO_ROOT).as_posix()
        for directory in ("backend", "tools")
        for path in (REPO_ROOT / directory).rglob("*.py")
        if "allow_experimental_rotors" in path.read_text(encoding="utf-8")
    }
    assert mentions == {
        "backend/public_policy.py",
        "tools/experimental_solve.py",
        "backend/benchmark_suite/cli.py",
        "backend/benchmark_suite/worker.py",
    }
    cli = (REPO_ROOT / "backend/benchmark_suite/cli.py").read_text(encoding="utf-8")
    worker = (REPO_ROOT / "backend/benchmark_suite/worker.py").read_text(encoding="utf-8")
    assert 'experimental = bool(case.get("experimental_rotor"))' in cli
    assert 'allow_experimental_rotors=bool(request.get("experimental_rotor"))' in worker


def test_experimental_opt_in_accepts_only_experimental_rotors():
    from backend.public_policy import EXPERIMENTAL_IPM_TOPOLOGIES, PublicConfigError, parse_public_motor_config

    assert EXPERIMENTAL_IPM_TOPOLOGIES == {"pyleecan_holem50"}
    config = parse_public_motor_config(ornl_design(), allow_experimental_rotors=True)
    assert config.rotor.ipm_topology == "pyleecan_holem50"
    for family in ("spoke", "barrier"):
        body = ornl_design()
        body["rotor"]["ipm_topology"] = family
        with pytest.raises(PublicConfigError, match="flat-buried and V-shape IPM only"):
            parse_public_motor_config(body, allow_experimental_rotors=True)
    # Every other public check still applies.
    cogging = ornl_design()
    cogging["solve_options"]["cogging_torque"] = True
    with pytest.raises(PublicConfigError) as caught:
        parse_public_motor_config(cogging, allow_experimental_rotors=True)
    assert caught.value.field == "solve_options.cogging_torque"


@pytest.mark.parametrize("family", [None, "flat_buried", "v_shape"])
def test_research_tool_refuses_supported_designs_before_solving(family, monkeypatch):
    import backend.solver as solver_module
    from backend.public_policy import PublicConfigError
    from tools import experimental_solve

    monkeypatch.setattr(solver_module.Magneto2DSolver, "solve", lambda *a, **k: pytest.fail("must not solve"))
    body = deepcopy(SPM_CONFIG) if family is None else ornl_design()
    if family is not None:
        body["rotor"]["ipm_topology"] = family
    with pytest.raises(PublicConfigError, match="experimental rotor families only"):
        experimental_solve.solve(body)


def test_research_tool_solves_with_magneto2d_only(monkeypatch):
    import backend.solver as solver_module
    from backend.public_policy import PublicConfigError
    from tools import experimental_solve

    monkeypatch.setattr(solver_module.Magneto2DSolver, "solve", lambda *a, **k: pytest.fail("must not solve"))
    body = ornl_design()
    body["solver"] = "elmer"
    with pytest.raises(PublicConfigError, match="Magneto2D only"):
        experimental_solve.solve(body)


@pytest.mark.weekly
def test_mapped_rotor_meshes_and_solves_at_no_load(tmp_path, monkeypatch):
    from tools import experimental_solve

    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    design = ornl_design()
    design["solve_params"].update(current_amplitude_A=0.0, rotor_sweep_range_deg=7.5, rotor_step_deg=7.5, mesh_density="coarse")
    record = experimental_solve.solve(design)
    assert record["experimental"] is True
    assert record["rotor_family"] == "pyleecan_holem50"
    assert record["notice"] == experimental_solve.NOTICE
    metadata, summary = record["result"]["solve_metadata"], record["result"]["summary"]
    assert metadata["solver_name"].startswith("magneto2d-")
    assert (metadata["mesh_source"], metadata["torque_method"]) == ("native", "weighted_stress")
    assert metadata["mesh_element_count"] > 10_000
    assert math.isfinite(summary["back_emf_fundamental_V"]) and summary["back_emf_fundamental_V"] > 0
    assert summary["lambda_pm_Wb"] > 0
