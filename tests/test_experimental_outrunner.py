"""Translation invariants for the frozen reference, independent of FEMM installation."""
import math
from collections import Counter

import numpy as np
import pytest

from backend.experimental.femm_outrunner import (
    DEPTH_M,
    MU0,
    build_field_problem,
    contour_torque,
    element_fields,
    material_models,
    phase_linkage,
    source,
)
from backend.experimental.outrunner_geometry import build_ir, faces, generate_native_mesh, loop_area


@pytest.fixture(scope="module")
def mesh():
    return generate_native_mesh(gap_size_mm=0.1, bulk_size_mm=0.5)


def test_exact_region_cover_and_physical_hole():
    regions = build_ir().regions
    assert len(regions) == 29
    assert Counter(x.kind for x in regions) == {"RotorCore": 1, "StatorYoke": 1, "Magnet": 14, "SlotWinding": 12, "Airgap": 1}
    assert math.isclose(sum(x.area_mm2 for x in regions), math.pi*(15.39**2-6.5**2), rel_tol=1e-12)
    assert len(next(x for x in regions if x.kind == "StatorYoke").loops) == 2
    assert len(next(x for x in regions if x.kind == "Airgap").loops) == 16
    assert not build_ir().validation_report().issues
    assert all(loop_area(f.outer) > 0 and all(loop_area(h) < 0 for h in f.holes) for f in faces())


def test_source_boundary_and_material_facts():
    regions = build_ir().regions
    fixed = [(segment.radius_mm, region.kind) for region in regions for loop in region.loops for segment in loop.segments
             if segment.boundary_tag == "dirichlet_az_zero"]
    assert {round(radius, 7) for radius, _ in fixed} == {6.5, 15.39}
    materials = material_models()
    assert materials[1] == {"kind": "linear", "mu_r": 1.049}
    raw = source()["materials"][3]
    b, h = raw["bh_points_T_A_per_m"][1]
    point = materials[3]["bh_curve"]["points"][1]
    assert point["b_t"] == pytest.approx(0.95*b+0.05*MU0*h)
    assert point["h_a_per_m"] == h
    assert materials[4]["bh_curve"]["points"][1]["b_t"] != point["b_t"]


def test_only_the_outer_body_and_its_magnetization_rotate():
    zero, moved = build_ir(), build_ir(23)
    theta = math.radians(23)
    rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    for first, second in zip(zero.regions, moved.regions):
        assert first.area_mm2 == second.area_mm2
        if first.kind == "Airgap":
            # Air is not a rigid body: its stator interfaces stay fixed while
            # its magnet/ring interfaces follow the rotor during remeshing.
            assert first.motion_group == "none"
            continue
        a = first.loops[0].segments[0].start
        b = second.loops[0].segments[0].start
        actual = np.array([b.x_mm, b.y_mm])
        expected = np.array([a.x_mm, a.y_mm])
        if first.motion_group == "rotor":
            expected = rotation @ expected
        np.testing.assert_allclose(actual, expected, atol=1e-10)
        if first.magnetization_xy:
            np.testing.assert_allclose(second.magnetization_xy, rotation @ first.magnetization_xy, atol=1e-12)


def test_native_regions_and_both_boundaries(mesh):
    mesh.validate()
    assert set(mesh.label_ids) == set(range(29))
    assert mesh.provenance["mesh_source"] == "native_Gmsh_geometry_IR"
    fixed = mesh.nodes_mm[mesh.dirichlet_nodes]
    radius = np.linalg.norm(fixed, axis=1)
    polygon_areas = []
    for r in (6.5, 15.39):
        polygon = fixed[abs(radius-r) < 1e-7]
        polygon = polygon[np.argsort(np.arctan2(polygon[:, 1], polygon[:, 0]))]
        polygon_areas.append(abs(np.sum(polygon[:, 0]*np.roll(polygon[:, 1], -1)-polygon[:, 1]*np.roll(polygon[:, 0], -1)))/2)
    # The P1 mesh fills its actual chordal boundary exactly. Curved CAD area
    # and polygonal mesh area differ at a finite boundary discretization.
    assert mesh.geometry()[1].sum()*1e6 == pytest.approx(polygon_areas[1]-polygon_areas[0], rel=1e-11)


def test_meshed_current_conservation_and_noload_isolation(mesh):
    loaded = build_field_problem(mesh)
    noload = build_field_problem(mesh, (0, 0, 0))
    _, area = mesh.geometry()
    j = np.array([x["current_density_z_a_per_m2"] for x in loaded["elements"]])
    integrated = np.bincount(mesh.label_ids, weights=area*j, minlength=29)
    for label in source()["labels"]:
        expected = label["signed_turns"]*(dict(A=0, B=4, C=-4).get(label["circuit"], 0))
        assert integrated[label["index"]] == pytest.approx(expected, abs=1e-9)
    assert all(x["current_density_z_a_per_m2"] == 0 for x in noload["elements"])
    assert any(x["current_density_z_a_per_m2"] != 0 for x in loaded["elements"])
    assert [x["remanence_t"] for x in loaded["elements"]] == [x["remanence_t"] for x in noload["elements"]]


def test_winding_function_is_gauge_invariant_and_reciprocal(mesh):
    az = (mesh.nodes_mm[:, 0]+0.3*mesh.nodes_mm[:, 1])*1e-4
    np.testing.assert_allclose(phase_linkage(mesh, az+3.2), phase_linkage(mesh, az), atol=2e-14)
    problem = build_field_problem(mesh)
    _, area = mesh.geometry()
    j = np.array([x["current_density_z_a_per_m2"] for x in problem["elements"]])
    integral = DEPTH_M*np.dot(area*j, az[mesh.triangles].mean(axis=1))
    assert np.dot(phase_linkage(mesh, az), [0, 4, -4]) == pytest.approx(integral, abs=1e-14)


def test_field_recovery_units_and_orientation(mesh):
    az = (mesh.nodes_mm[:, 0]+2*mesh.nodes_mm[:, 1])*1e-3
    field = element_fields(mesh, az)
    np.testing.assert_allclose(field[:, 0], 2, atol=5e-10)
    np.testing.assert_allclose(field[:, 1], -1, atol=5e-10)


def test_unbalanced_current_request_is_rejected(mesh):
    with pytest.raises(ValueError, match="balanced"):
        build_field_problem(mesh, (1, 2, 3))


def test_contour_torque_matches_analytic_annular_harmonic(mesh):
    xy = mesh.nodes_mm*1e-3
    radius = np.linalg.norm(xy, axis=1)/0.0129
    theta = np.arctan2(xy[:, 1], xy[:, 0])
    a, b, c, d = 0.001, 0.0002, 0.0003, 0.0001
    az = (a*radius+b/radius)*np.cos(theta)+(c*radius+d/radius)*np.sin(theta)
    expected_outer = -2*math.pi*DEPTH_M/MU0*(b*c-a*d)
    results = contour_torque(mesh, az)
    assert len(results) == 3
    for row in results:
        assert row["coverage_rad"] == pytest.approx(2*math.pi, abs=1e-9)
        assert row["outer_rotor_torque_Nm"] == pytest.approx(expected_outer, rel=0.02)


def test_body_selected_weighted_stress_matches_analytic_torque(mesh):
    from backend.experimental.outrunner_stress import weighted_stress_torque

    xy = mesh.nodes_mm*1e-3
    radius = np.linalg.norm(xy, axis=1)/0.0129
    theta = np.arctan2(xy[:, 1], xy[:, 0])
    a, b, c, d = 0.001, 0.0002, 0.0003, 0.0001
    az = (a*radius+b/radius)*np.cos(theta)+(c*radius+d/radius)*np.sin(theta)
    expected_outer = -2*math.pi*DEPTH_M/MU0*(b*c-a*d)
    result = weighted_stress_torque(mesh, az)
    assert result["outer_rotor_torque_Nm"] == pytest.approx(expected_outer, rel=0.02)
    assert result["weighting_relative_residual"] <= 1e-10
    assert -1e-8 <= result["weight_min"] <= result["weight_max"] <= 1+1e-8
