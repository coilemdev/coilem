"""Physical/topological guards for the explicit 3D path; no mock solver verdicts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import meshio
import numpy as np
import pytest
from pydantic import ValidationError

from backend.elmer3d.mesh import closed_surface, maxwell_stress, read_mesh
from backend.elmer3d.model import Case3D, Coil3D, Material3D
from backend.elmer3d.solver import field_convergence, read_vectors, solve_case, write_case


@pytest.fixture
def tetra_case(tmp_path):
    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float) * 0.01
    faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    mesh = meshio.Mesh(
        points,
        [("tetra", np.array([[0, 1, 2, 3]])), ("triangle", faces)],
        field_data={"Air": [91, 3], "Far": [207, 2]},
        cell_data={"gmsh:physical": [np.array([91]), np.full(4, 207)], "gmsh:geometrical": [np.array([91]), np.full(4, 207)]},
    )
    path = tmp_path / "input.msh"
    meshio.write(path, mesh, file_format="gmsh22", binary=False)
    return Case3D(mesh_file=path, materials={"AirLaw": Material3D()}, bodies={"Air": "AirLaw"}, outer_boundary="Far")


@pytest.mark.parametrize("points", [[(0, 0)], [(0, 1), (1, 2)], [(0, 0), (1, 2), (2, 1)], [(0, 0), (1, float("nan"))]])
def test_nonphysical_material_curve_rejected(points):
    with pytest.raises(ValidationError):
        Material3D(kind="bh_curve", bh_points=points)


def test_missing_axial_boundary_is_rejected(tetra_case):
    volume = read_mesh(tetra_case, tetra_case.mesh_file)
    assert len(volume.tetra) == 1
    with pytest.raises(ValueError, match="closed manifold"):
        closed_surface(volume.triangles[:-1], volume.mesh.points)
    mesh = volume.mesh
    mesh.cell_data["gmsh:physical"][1][-1] = 999
    meshio.write(tetra_case.mesh_file, mesh, file_format="gmsh22", binary=False)
    with pytest.raises(ValueError, match="every exterior face"):
        read_mesh(tetra_case, tetra_case.mesh_file)


def test_truncated_2d_current_column_is_not_a_closed_coil(tetra_case):
    tetra_case.coils = {"Coil": Coil3D(bodies=["Air"], normal=(0, 0, 1), current_A=1)}
    with pytest.raises(ValueError, match="solid torus"):
        read_mesh(tetra_case, tetra_case.mesh_file)


def test_uniform_field_has_zero_net_closed_surface_force_and_torque(tetra_case):
    volume = read_mesh(tetra_case, tetra_case.mesh_file)
    # Deliberately mixed winding and an offset origin exercise orientation and all caps.
    volume.triangles[1] = volume.triangles[1][::-1]
    result = maxwell_stress(volume, "Far", np.tile([0.2, -0.3, 0.7], (4, 1)), (0.1, -0.2, 0.4))
    assert result["force_N"] == pytest.approx([0, 0, 0], abs=1e-12)
    assert result["torque_Nm"] == pytest.approx([0, 0, 0], abs=1e-12)


def test_stress_cannot_cross_magnetic_material(tetra_case):
    tetra_case.stress_surface = "Far"
    with pytest.raises(ValueError, match="internal"):
        read_mesh(tetra_case, tetra_case.mesh_file)


def test_unknown_volume_and_nonlinear_nonconvergence_rejected(tetra_case):
    tetra_case.bodies = {"WrongBody": "AirLaw"}
    with pytest.raises(ValueError, match="missing physical volume"):
        read_mesh(tetra_case, tetra_case.mesh_file)
    log = "ComputeChange: NS (ITER=1) (NRM,RELC): (1.0e-4 0.2) :: magnetostatics3d"
    with pytest.raises(ValueError, match="did not converge"):
        field_convergence(log, 1e-7)
    assert field_convergence(log.replace("0.2)", "1.0e-8)"), 1e-7)["final_relative_change"] == 1e-8
    with pytest.raises(ValueError, match="missing field-solver"):
        field_convergence("ALL DONE", 1e-7)


def test_conversion_renumbering_and_pm_units(tetra_case, tmp_path):
    volume = read_mesh(tetra_case, tetra_case.mesh_file)
    tetra_case.materials["AirLaw"] = Material3D(kind="permanent_magnet", remanence_T=(0, 0, 1.235), relative_permeability=1.12)
    path = write_case(tetra_case, volume, tmp_path, converted_names={"Air": 4, "Far": 8})
    text = path.read_text()
    assert "Target Bodies(1) = 4" in text and "Target Boundaries(1) = 8" in text
    source = float(next(line.split("Real ")[1] for line in text.splitlines() if "Magnetization 3" in line))
    assert source * (4e-7 * np.pi) * 1.12 == pytest.approx(1.235)


def test_vector_reordering_and_coordinate_roundoff(tmp_path):
    points = np.array([[0, 0, 0], [0.12345678912349, 0.2, 0.3], [0.02, 0.03, 0.01], [0.4, 0.1, 0.2]])
    a, b = np.arange(12).reshape((4, 3)), np.arange(12, 24).reshape((4, 3))
    order = [2, 0, 3, 1]
    vtu = meshio.Mesh(
        np.round(points[order], 12),
        [("tetra", np.array([[0, 1, 2, 3]]))],
        point_data={"magnetic vector potential": a[order], "magnetic flux density": b[order]},
    )
    path = tmp_path / "fields.vtu"
    meshio.write(path, vtu)
    actual_a, actual_b = read_vectors(path, points)
    assert np.array_equal(actual_a, a)
    assert np.array_equal(actual_b, b)


def test_mesh_demo_is_true_finite_volume(tmp_path):
    from backend.elmer3d.demo import create_demo

    case = create_demo(tmp_path / "sphere", mesh_scale=2)
    # The Windows Gmsh DLL changes native PATH behind os.environ's back.
    # A bare executable launch must still work after the meshing session.
    if shutil.which("git"):
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    volume = read_mesh(case, case.mesh_file)
    assert np.ptp(volume.mesh.points[:, 2]) > 0.1
    pm_tetra = volume.tetra[volume.body_ids == volume.names["Magnet"][0]]
    p = volume.mesh.points[pm_tetra]
    v = np.abs(np.linalg.det(p[:, 1:] - p[:, :1])).sum() / 6
    assert v == pytest.approx(4 * np.pi * 0.004**3 / 3, rel=0.08)


def test_finite_motor_keeps_magnet_length_separate_and_has_air_end_caps(monkeypatch, tmp_path):
    from backend.elmer3d.motor import AxialGeometry, create_motor_case
    from backend.models import MotorConfig

    config = MotorConfig.model_validate_json((Path(__file__).parent / "fixtures/spm_4p12s_simple.json").read_text())
    config.solve_params.current_amplitude_A = 0
    points = [[0.0, 0.0]]
    for radius in (4, 5, 6, 10):
        points.extend([[radius * np.cos(i * np.pi / 3), radius * np.sin(i * np.pi / 3)] for i in range(6)])
    triangles, regions = [], []
    for i in range(6):
        triangles.append([0, 1 + i, 1 + (i + 1) % 6])
        regions.append("pm")
    for ring in range(3):
        for i in range(6):
            a, b = 1 + 6 * ring + i, 1 + 6 * ring + (i + 1) % 6
            triangles.extend([[a, b, b + 6], [a, b + 6, a + 6]])
            regions.extend(["gap" if ring < 2 else "steel"] * 2)
    artifact = {
        "mesh": {"nodes": points, "triangles": triangles, "info": {"airgap_inner_radius_mm": 4, "airgap_outer_radius_mm": 6}},
        "element_region_ids": regions,
        "physics_contract": {
            "regions": [
                {"id": "pm", "geometry_ir_kind": "Magnet", "material": "magnet", "magnetization_angle_deg": 30},
                {"id": "gap", "geometry_ir_kind": "Airgap", "material": "air"},
                {"id": "steel", "geometry_ir_kind": "RotorCore", "material": "steel:rotor:M350-50A"},
            ]
        },
    }
    monkeypatch.setattr("backend.elmer3d.motor.run_gmsh_mesh_preview", lambda *args, **kwargs: {"solve_mesh_artifact": artifact})
    axial = AxialGeometry(magnet_length_mm=30, magnet_center_mm=2, end_padding_mm=15, exterior_radius_mm=20, core_layers=2, end_layers=1)
    case = create_motor_case(config, axial, tmp_path / "motor")
    volume = read_mesh(case, case.mesh_file)
    pm_tag = volume.names["Region0001"][0]
    pm_tetra = volume.tetra[volume.body_ids == pm_tag]
    p = volume.mesh.points[pm_tetra]
    actual_volume = np.abs(np.linalg.det(p[:, 1:] - p[:, :1])).sum() / 6
    assert actual_volume == pytest.approx(6 * 0.5 * 4**2 * np.sin(np.pi / 3) * 30 * 1e-9)
    assert p[:, :, 2].min() == pytest.approx(-0.013)
    assert p[:, :, 2].max() == pytest.approx(0.017)
    assert volume.mesh.points[:, 2].min() == pytest.approx(-0.035)
    stress_z = volume.mesh.points[volume.surface("Stress")][:, :, 2]
    assert stress_z.max() == pytest.approx(0.0275)
    assert stress_z.min() == pytest.approx(-0.0275)
    config.solve_params.current_amplitude_A = 50
    with pytest.raises(ValueError, match="closed end turns"):
        create_motor_case(config, axial, tmp_path / "loaded")


@pytest.mark.skipif(not os.environ.get("COILEM_ELMER3D_TEST_HOME"), reason="explicit external Elmer runtime required")
def test_real_sphere_against_analytic_solution(tmp_path):
    from backend.elmer3d.demo import create_demo

    case = create_demo(tmp_path / "inputs", mesh_scale=0.8)
    result = solve_case(case, output_dir=tmp_path / "solve", elmer_home=Path(os.environ["COILEM_ELMER3D_TEST_HOME"]))
    fields = np.load(tmp_path / "solve" / result["fields_npz"])
    interior = np.linalg.norm(fields["nodes_m"], axis=1) < 0.002
    average = fields["magnetic_b_T"][interior].mean(axis=0)
    assert average[2] == pytest.approx(2 / (1.12 + 2), rel=0.03)
    assert np.linalg.norm(average[:2]) < 0.002
    assert result["status"] == "COMPLETE" and result["qualified"] is False
    with pytest.raises(FileExistsError):
        solve_case(case, output_dir=tmp_path / "solve", elmer_home=Path(os.environ["COILEM_ELMER3D_TEST_HOME"]))
    assert json.loads((tmp_path / "solve" / "result.json").read_text())["status"] == "COMPLETE"
