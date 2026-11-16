"""Fixed material cells must remove false histories without suppressing real ones."""

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from backend.iron_loss import SteinmetzCoefficients
from backend.models import MotorConfig
from backend.rotor_iron_loss import RotorLossMaterial, RotorSamplingPlan, harmonic_rotor_iron_loss, rotor_flux_history
from backend.rotor_motion_mesh import FixedMaterialRotorMesh, annular_strip, triangle_metrics, validate_conforming_disk
from backend.topology_provenance import build_topology_provenance
from tools.rotor_native_pilot import field_sample
from tools.rotor_native_remesh_probe import static_potential

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"


def template():
    """Synthetic disk, gap and stator annulus; no FE solver or mesher needed."""
    config = MotorConfig.model_validate(json.loads(FIXTURE.read_text()))
    config.solve_params.current_angle_deg = 180
    n = 128
    a = 2*math.pi*np.arange(n)/n
    nodes = np.concatenate(([[0., 0.]], *(r*np.column_stack((np.cos(a), np.sin(a))) for r in (29.5, 30., 50.))))
    inner, outer, far = (np.arange(1+k*n, 1+(k+1)*n) for k in range(3))
    core = np.array([[0, i, j] for i, j in zip(inner, np.roll(inner, -1))])
    gap, stator = annular_strip(nodes, inner, outer), annular_strip(nodes, outer, far)
    triangles = np.concatenate((core, gap, stator))
    ids = ["rotor_core"]*len(core)+["airgap"]*len(gap)+["stator_yoke"]*len(stator)
    ids[-1] = "slot_winding_0"
    regions = [{"id": "rotor_core", "kind": "RotorCore", "motion_group": "rotor"},
               {"id": "airgap", "kind": "Airgap", "motion_group": "sliding_airgap"},
               {"id": "stator_yoke", "kind": "StatorYoke", "motion_group": "stationary"},
               {"id": "slot_winding_0", "kind": "SlotWinding", "motion_group": "stationary",
                "winding": {"phase": "A", "direction": "in", "turn_fraction": 1.,
                            "area_mm2": float(triangle_metrics(nodes, triangles[-1:])[0][0]), "current_density_a_per_m2": 0.}}]
    kinds = {r["id"]: r["kind"] for r in regions}
    artifact = {"mesh": {"nodes": nodes.tolist(), "triangles": triangles.tolist(), "regions": [kinds[r] for r in ids],
                         "length_units": "mm", "boundary_nodes": far.tolist(), "sector_edge_pairs": [],
                         "info": {"total_span_deg": 360, "airgap_inner_radius_mm": 29.5, "airgap_outer_radius_mm": 30.}},
                "element_region_ids": ids, "element_magnetization": [None]*len(ids),
                "element_current_density_a_per_m2": [None]*(len(ids)-1)+[0.], "rotor_angle_mech_deg": 0.,
                "topology_provenance": build_topology_provenance(config),
                "physics_contract": {"topology_hint": "SPM", "regions": regions,
                                     "motion": {"rotor_angle_mech_deg": 0., "rotor_state": "baked_in_mesh"},
                                     "provenance": {"element_region_sources": ["synthetic"]*len(ids)}}}
    return config, artifact


@pytest.mark.parametrize("theta", [0, -0.9375, -22.5, 3.7, -360, 725.123])
def test_rigid_rotor_fixed_stator_shared_interfaces_and_fresh_unwrapped_pose(theta):
    config, artifact = template()
    original = copy.deepcopy(artifact)
    motion = FixedMaterialRotorMesh(artifact, angular_divisions=128)
    pose = motion.at_angle(config, theta)
    mesh = pose["mesh"]
    validate_conforming_disk(mesh["nodes"], mesh["triangles"], mesh["boundary_nodes"])
    old = np.asarray(artifact["mesh"]["nodes"])[artifact["mesh"]["triangles"]]
    new = np.asarray(mesh["nodes"])[mesh["triangles"]][:len(motion.keep)]
    rotating = np.asarray(artifact["element_region_ids"])[motion.keep] == "rotor_core"
    a = math.radians(theta)
    to_material = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    np.testing.assert_allclose(new[rotating] @ to_material, old[motion.keep[rotating]], rtol=0, atol=1e-12)
    np.testing.assert_array_equal(new[~rotating], old[motion.keep[~rotating]])
    assert pose["physics_contract"]["motion"]["rotor_angle_mech_deg"] == theta
    assert pose["rotor_angle_mech_deg"] == theta and artifact == original
    coil = pose["physics_contract"]["regions"][-1]["winding"]
    expected = 240*math.sin(math.radians(4*theta+60))
    assert coil["current_density_a_per_m2"]*coil["area_mm2"]*1e-6 == pytest.approx(expected, abs=1e-10)


def test_endpoint_geometry_is_exact_and_unsupported_or_changed_geometry_fails_closed():
    config, artifact = template()
    motion = FixedMaterialRotorMesh(artifact, angular_divisions=128)
    assert motion.at_angle(config, -360)["mesh"]["nodes"] == motion.at_angle(config, 0)["mesh"]["nodes"]
    changed = config.model_copy(deep=True)
    changed.stator.OD_mm += 1
    with pytest.raises(ValueError, match="geometry"):
        motion.at_angle(changed, 0)
    with pytest.raises(ValueError, match="finite"):
        motion.at_angle(config, float("nan"))
    artifact["mesh"]["info"]["sector"] = {"repeats": 2}
    with pytest.raises(ValueError, match="full-circle"):
        FixedMaterialRotorMesh(artifact)


def test_broken_material_interface_and_inverted_cells_cannot_pass():
    _, artifact = template()
    artifact["element_region_ids"][0] = "airgap"
    with pytest.raises(ValueError, match="complete polygon"):
        FixedMaterialRotorMesh(artifact)
    _, artifact = template()
    triangles = np.asarray(artifact["mesh"]["triangles"])
    triangles[0] = triangles[0, ::-1]
    with pytest.raises(ValueError, match="inverted"):
        validate_conforming_disk(artifact["mesh"]["nodes"], triangles, artifact["mesh"]["boundary_nodes"])


def test_magnetization_rotates_once_and_operating_current_can_be_rebaked():
    config, artifact = template()
    artifact["physics_contract"]["regions"].append({"id": "magnet_0", "kind": "Magnet", "motion_group": "rotor",
                                                 "magnetization_angle_deg": 25.})
    artifact["element_region_ids"][0] = "magnet_0"
    artifact["mesh"]["regions"][0] = "Magnet"
    artifact["element_magnetization"][0] = 25.
    motion = FixedMaterialRotorMesh(artifact, angular_divisions=128)
    full = motion.at_angle(config, -22.5)
    assert full["element_magnetization"][0] == pytest.approx(2.5)
    assert full["physics_contract"]["regions"][-1]["magnetization_angle_deg"] == pytest.approx(2.5)
    config.solve_params.current_amplitude_A *= 0.5
    half = motion.at_angle(config, -22.5)
    full_coil = full["physics_contract"]["regions"][-2]["winding"]["current_density_a_per_m2"]
    half_coil = half["physics_contract"]["regions"][-2]["winding"]["current_density_a_per_m2"]
    assert half_coil == pytest.approx(full_coil*0.5)


@pytest.mark.parametrize("shift", [0, 0.0317, -0.17, math.pi])
def test_annular_zipper_preserves_area_and_every_interface_edge(shift):
    a, b = 2*math.pi*np.arange(17)/17+shift, 2*math.pi*np.arange(29)/29
    nodes = np.concatenate((np.column_stack((np.cos(a), np.sin(a))), 2*np.column_stack((np.cos(b), np.sin(b)))))
    triangles = annular_strip(nodes, np.arange(17), np.arange(17, 46))
    area, _ = triangle_metrics(nodes, triangles)
    expected = 0.5*(29*4*math.sin(2*math.pi/29)-17*math.sin(2*math.pi/17))
    assert len(triangles) == 46 and np.min(area) > 0 and area.sum() == pytest.approx(expected, abs=1e-12)
    edges = np.sort(np.concatenate((triangles[:, :2], triangles[:, 1:], triangles[:, [2, 0]])), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    assert np.sum(counts == 1) == 46 and np.max(counts) == 2


@pytest.mark.parametrize("direction", [-1, 1])
@pytest.mark.parametrize("varying", [False, True])
def test_static_spatial_field_has_zero_loss_and_real_time_harmonics_are_preserved(direction, varying):
    config, artifact = template()
    motion = FixedMaterialRotorMesh(artifact, angular_divisions=128)
    plan = RotorSamplingPlan(3000, 32, direction, 3.7)
    samples = []
    for k, angle in enumerate(plan.mechanical_angles_deg):
        mesh = motion.at_angle(config, angle)["mesh"]
        a = math.radians(angle)
        xy = np.asarray(mesh["nodes"]) @ np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        amplitude = 1+0.1*math.cos(2*math.pi*3*k/32)+0.03*math.cos(2*math.pi*7*k/32) if varying else 1
        report = {"mesh_info": {"total_span_deg": 360}, "field_plot": {"total_span_deg": 360,
                  "nodes_mm": mesh["nodes"], "triangles": mesh["triangles"], "regions": mesh["regions"],
                  "az_nodal": (amplitude*static_potential(xy)).tolist()}}
        samples.append(field_sample(report, angle))
    history = rotor_flux_history(plan, samples)
    coefficients = SteinmetzCoefficients(kh=0.02, alpha=2.1, kc=0.0003, density_kg_m3=7650)
    loss = harmonic_rotor_iron_loss(history, material=RotorLossMaterial("synthetic", "analytical", coefficients), stack_length_m=0.05)
    if not varying:
        assert loss.total_W < 1e-16
    else:
        base = np.hypot(samples[0].bx_t, samples[0].by_t)/1.13
        mass = history.area_m2*0.05*coefficients.density_kg_m3
        h = sum(np.sum(mass*coefficients.kh*(50*order)*(amplitude*base)**coefficients.alpha) for order, amplitude in [(3, 0.1), (7, 0.03)])
        e = sum(np.sum(mass*coefficients.kc*(50*order)**2*(amplitude*base)**2) for order, amplitude in [(3, 0.1), (7, 0.03)])
        assert loss.hysteresis_W == pytest.approx(h, rel=1e-10)
        assert loss.lamination_eddy_W == pytest.approx(e, rel=1e-10)
