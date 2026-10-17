"""Finite-length, no-load lowering of the existing motor cross-section.

The stack, magnets, radial exterior and axial exterior are separate inputs.
This deliberately does not manufacture end-turn current paths from 2D slots.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path

import meshio
import numpy as np
from pydantic import Field

from backend.elmer.case import _is_steel, _steel_grade
from backend.gmsh_solver import run_gmsh_mesh_preview
from backend.material_catalog import MAGNET_PROPERTIES
from backend.material_contract import load_electrical_steel_curve
from backend.models import MotorConfig

from .gmsh_environment import preserve_process_path
from .model import Case3D, InputModel, Material3D


class AxialGeometry(InputModel):
    magnet_length_mm: float = Field(gt=0)
    magnet_center_mm: float = 0.0
    end_padding_mm: float = Field(gt=0)
    exterior_radius_mm: float = Field(gt=0)
    core_layers: int = Field(default=4, ge=2, le=128)
    end_layers: int = Field(default=2, ge=1, le=32)
    max_tetrahedra: int = Field(default=500000, ge=1)


def split_airgap_contour(nodes, triangles, regions, radius, contracts):
    """Insert a conformal piecewise-linear radial level set in air only.

    This partitions existing triangles without moving a motor boundary or
    changing any region's area. Shared-edge intersections are created once.
    """
    points = nodes.tolist()
    level = np.linalg.norm(nodes, axis=1) - radius
    level[np.abs(level) < 1e-8] = 0
    crossings = {}
    output, region_ids, inside = [], [], []
    for t, region in zip(triangles, regions, strict=True):
        if np.all(level[t] <= 0) or np.all(level[t] >= 0):
            output.append(t.tolist())
            region_ids.append(region)
            inside.append(bool(np.all(level[t] <= 0)))
            continue
        if contracts[region].get("geometry_ir_kind") != "Airgap":
            raise ValueError("torque contour would cut a non-airgap region")
        for side in (1, -1):
            polygon = []
            for i, a in enumerate(t):
                b = t[(i + 1) % 3]
                if side * level[a] <= 0:
                    polygon.append(int(a))
                if level[a] * level[b] < 0:
                    edge = tuple(sorted((int(a), int(b))))
                    if edge not in crossings:
                        fraction = level[a] / (level[a] - level[b])
                        crossings[edge] = len(points)
                        points.append((nodes[a] + fraction * (nodes[b] - nodes[a])).tolist())
                    polygon.append(crossings[edge])
            for i in range(1, len(polygon) - 1):
                output.append([polygon[0], polygon[i], polygon[i + 1]])
                region_ids.append(region)
                inside.append(side == 1)
    return np.asarray(points), np.asarray(output), region_ids, inside


def create_motor_case(config: MotorConfig, axial: AxialGeometry, directory: Path, *, rotor_angle_mech_deg: float = 0.0) -> Case3D:
    """Extrude the actual solver triangulation, preserving its region/material mapping."""
    if config.solve_params is None or config.solve_params.current_amplitude_A != 0:
        raise ValueError("motor extrusion currently requires explicit zero current; loaded cases need meshed closed end turns")
    if not math.isfinite(rotor_angle_mech_deg):
        raise ValueError("rotor angle must be finite")
    stack = float(config.stator.stack_length_mm)
    magnet_start = axial.magnet_center_mm - axial.magnet_length_mm / 2
    magnet_end = axial.magnet_center_mm + axial.magnet_length_mm / 2
    if magnet_start < -stack / 2 - 1e-9 or magnet_end > stack / 2 + 1e-9:
        raise ValueError("this axial model requires magnets contained within the steel stack")
    with preserve_process_path():
        preview = run_gmsh_mesh_preview(config, rotor_angle_deg=rotor_angle_mech_deg)
    artifact = preview["solve_mesh_artifact"]
    nodes = np.asarray(artifact["mesh"]["nodes"], dtype=float)
    triangles = np.asarray(artifact["mesh"]["triangles"], dtype=int)
    region_ids = list(artifact["element_region_ids"])
    contracts = {r["id"]: r for r in artifact["physics_contract"]["regions"]}
    info = artifact["mesh"]["info"]
    stress_radius = (info["airgap_inner_radius_mm"] + info["airgap_outer_radius_mm"]) / 2
    nodes, triangles, region_ids, rotor_inside = split_airgap_contour(nodes, triangles, region_ids, stress_radius, contracts)
    edge_count = Counter(tuple(sorted((t[i], t[(i + 1) % 3]))) for t in triangles for i in range(3))
    edges = [e for e, count in edge_count.items() if count == 1]
    outer_nodes = sorted({v for edge in edges for v in edge})
    radii = np.linalg.norm(nodes[outer_nodes], axis=1)
    old_radius = float(radii.mean())
    if np.ptp(radii) > 1e-5 or axial.exterior_radius_mm <= old_radius:
        raise ValueError("exterior radius must exceed the circular cross-section boundary")
    # Add an explicit exterior annulus without stretching the motor itself.
    outer_map = {v: len(nodes) + i for i, v in enumerate(outer_nodes)}
    expanded = nodes[outer_nodes] * (axial.exterior_radius_mm / old_radius)
    nodes = np.vstack((nodes, expanded))
    extra = []
    for a, b in edges:
        extra.extend(((a, b, outer_map[b]), (a, outer_map[b], outer_map[a])))
    triangles = np.vstack((triangles, np.asarray(extra)))
    region_ids.extend(["__exterior"] * len(extra))
    rotor_inside.extend([False] * len(extra))
    core_z = list(np.linspace(-stack / 2, stack / 2, axial.core_layers + 1))
    left = np.linspace(-stack / 2 - axial.end_padding_mm, -stack / 2, axial.end_layers + 1)
    right = np.linspace(stack / 2, stack / 2 + axial.end_padding_mm, axial.end_layers + 1)
    stress_lower, stress_upper = -stack / 2 - axial.end_padding_mm / 2, stack / 2 + axial.end_padding_mm / 2
    z_mm = sorted({round(float(z), 10) for z in (*left, *core_z, magnet_start, magnet_end, *right, stress_lower, stress_upper)})
    predicted = 3 * len(triangles) * (len(z_mm) - 1)
    if predicted > axial.max_tetrahedra:
        raise ValueError(f"3D mesh would contain {predicted} tetrahedra; limit is {axial.max_tetrahedra}")
    count = len(nodes)
    points = np.vstack([np.column_stack((nodes, np.full(count, z))) for z in z_mm]) * 1e-3
    materials = {"AirLaw": Material3D()}
    body_laws = {"Exterior": "AirLaw"}
    source_names = {}
    steel_laws = {}
    for i, (region, entry) in enumerate(contracts.items(), 1):
        name = f"Region{i:04d}"
        source_names[region] = name
        key = entry.get("material", "")
        if entry.get("geometry_ir_kind") == "Magnet":
            props = MAGNET_PROPERTIES[config.materials.magnet_grade]
            angle = math.radians(entry["magnetization_angle_deg"])
            law = f"MagnetLaw{i:04d}"
            br = float(props["remanence_T"])
            materials[law] = Material3D(
                kind="permanent_magnet",
                relative_permeability=props["relative_permeability"],
                remanence_T=(br * math.cos(angle), br * math.sin(angle), 0),
            )
        elif _is_steel(key):
            grade = _steel_grade(key)
            if grade not in steel_laws:
                steel_laws[grade] = f"SteelLaw{len(steel_laws):04d}"
                curve = load_electrical_steel_curve(grade)
                materials[steel_laws[grade]] = Material3D(kind="bh_curve", bh_points=list(curve.points))
            law = steel_laws[grade]
        else:
            law = "AirLaw"
        body_laws[name] = law
    body_tags = {name: i for i, name in enumerate(body_laws, 1)}
    tetra, tags, enclosed = [], [], []
    for layer, (z0, z1) in enumerate(zip(z_mm, z_mm[1:])):
        z = (z0 + z1) / 2
        for t, region, rotor in zip(triangles, region_ids, rotor_inside, strict=True):
            body = "Exterior"
            if region != "__exterior" and -stack / 2 < z < stack / 2:
                entry = contracts[region]
                if entry.get("geometry_ir_kind") != "Magnet" or magnet_start < z < magnet_end:
                    body = source_names[region]
            a, b, c = sorted(int(v) for v in t)
            a, b, c = a + layer * count, b + layer * count, c + layer * count
            prism = ((a, b, c, c + count), (a, b, b + count, c + count), (a, a + count, b + count, c + count))
            inside = stress_lower < z < stress_upper and rotor
            tetra.extend(prism)
            tags.extend([body_tags[body]] * 3)
            enclosed.extend([inside] * 3)
    tetra = np.asarray(tetra, dtype=int)
    p = points[tetra]
    negative = np.linalg.det(p[:, 1:] - p[:, :1]) < 0
    tetra[negative, :2] = tetra[negative, 1::-1]
    owners = defaultdict(list)
    for i, t in enumerate(tetra):
        for f in ((t[0], t[1], t[2]), (t[0], t[1], t[3]), (t[0], t[2], t[3]), (t[1], t[2], t[3])):
            owners[tuple(sorted(f))].append(i)
    outer = [f for f, elements in owners.items() if len(elements) == 1]
    stress = [f for f, elements in owners.items() if len(elements) == 2 and enclosed[elements[0]] != enclosed[elements[1]]]
    used_tags = set(tags)
    bodies = {name: law for name, law in body_laws.items() if body_tags[name] in used_tags}
    field_data = {name: [body_tags[name], 3] for name in bodies}
    field_data.update({"Far": [10001, 2], "Stress": [10002, 2]})
    faces = np.asarray(outer + stress)
    surface_tags = np.asarray([10001] * len(outer) + [10002] * len(stress))
    mesh = meshio.Mesh(
        points,
        [("tetra", tetra), ("triangle", faces)],
        field_data=field_data,
        cell_data={"gmsh:physical": [np.asarray(tags), surface_tags], "gmsh:geometrical": [np.asarray(tags), surface_tags]},
    )
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / "input.msh"
    meshio.write(target, mesh, file_format="gmsh22", binary=False)
    case = Case3D(
        mesh_file=target,
        materials=materials,
        bodies=bodies,
        outer_boundary="Far",
        stress_surface="Stress",
        assumptions=[
            "Finite straight stack; no skew, end plates, shaft extension or end-turn conductors.",
            "Steel uses the same scalar in-plane catalog H-B law in every direction; axial lamination law is unvalidated.",
            "Magnet axial dimensions and placement are explicit assumptions unless separately sourced.",
            "No-load field/cogging case only; loaded motor excitation requires meshed closed end turns.",
        ],
    )
    case.numerics.nonlinear_relaxation = 0.5
    (directory / "case.json").write_text(case.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (directory / "axial-geometry.json").write_text(axial.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (directory / "motor.json").write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return case
