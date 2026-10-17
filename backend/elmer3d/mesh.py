"""Validate a conformal tetrahedral volume mesh and its closed air surfaces."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import meshio
import numpy as np

from .model import Case3D


@dataclass
class VolumeMesh:
    mesh: meshio.Mesh
    tetra: np.ndarray
    body_ids: np.ndarray
    triangles: np.ndarray
    surface_ids: np.ndarray
    names: dict[str, tuple[int, int]]
    faces: dict[tuple[int, int, int], list[int]]

    def surface(self, name: str) -> np.ndarray:
        tag, dim = self.names.get(name, (-1, -1))
        if dim != 2:
            raise ValueError(f"missing physical surface: {name}")
        result = self.triangles[self.surface_ids == tag]
        if not len(result):
            raise ValueError(f"empty physical surface: {name}")
        return result


def closed_surface(triangles: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Orient one closed connected manifold outwards without assuming convexity."""
    triangles = np.asarray(triangles, dtype=int).copy()
    if not len(triangles):
        raise ValueError("surface must be nonempty")
    edges = defaultdict(list)
    for i, (a, b, c) in enumerate(triangles):
        for x, y in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((x, y)))].append((i, x < y))
    if any(len(owners) != 2 for owners in edges.values()):
        raise ValueError("surface must be a closed manifold (two faces per edge)")
    signs = {0: 1}
    adjacency = defaultdict(list)
    for (i, direction_i), (j, direction_j) in edges.values():
        relation = -1 if direction_i == direction_j else 1
        adjacency[i].append((j, relation))
        adjacency[j].append((i, relation))
    queue = deque([0])
    while queue:
        i = queue.popleft()
        for j, relation in adjacency[i]:
            expected = signs[i] * relation
            if j in signs and signs[j] != expected:
                raise ValueError("surface is not orientable")
            if j not in signs:
                signs[j] = expected
                queue.append(j)
    if len(signs) != len(triangles):
        raise ValueError("surface must be connected")
    for i, sign in signs.items():
        if sign < 0:
            triangles[i, [1, 2]] = triangles[i, [2, 1]]
    p = points[triangles]
    volume6 = np.einsum("ij,ij->i", p[:, 0], np.cross(p[:, 1], p[:, 2])).sum()
    if abs(volume6) < 1e-24:
        raise ValueError("closed surface encloses zero volume")
    if volume6 < 0:
        triangles[:, [1, 2]] = triangles[:, [2, 1]]
    return triangles


def read_mesh(case: Case3D, path: Path) -> VolumeMesh:
    mesh = meshio.read(path)
    if mesh.points.shape[1] != 3 or not np.isfinite(mesh.points).all():
        raise ValueError("finite three-dimensional mesh coordinates required")
    if any(block.type not in {"tetra", "triangle", "line", "vertex"} for block in mesh.cells):
        raise ValueError("only first-order tetrahedral volume meshes are supported")
    physical = mesh.cell_data.get("gmsh:physical", [])
    if len(physical) != len(mesh.cells):
        raise ValueError("every mesh element requires a Gmsh physical group")
    tetra, ids, triangles, surfaces = [], [], [], []
    for block, tags in zip(mesh.cells, physical, strict=True):
        if block.type == "tetra":
            tetra.extend(block.data)
            ids.extend(tags)
        elif block.type == "triangle":
            triangles.extend(block.data)
            surfaces.extend(tags)
    tetra = np.asarray(tetra, dtype=int).reshape((-1, 4))
    if not len(tetra):
        raise ValueError("mesh contains no tetrahedra")
    if len({tuple(sorted(t)) for t in tetra}) != len(tetra):
        raise ValueError("duplicate tetrahedra")
    if tetra.min() < 0 or tetra.max() >= len(mesh.points):
        raise ValueError("tetrahedron references an unavailable node")
    p = mesh.points[tetra]
    determinants = np.linalg.det(p[:, 1:] - p[:, :1])
    if np.any(np.abs(determinants) <= 1e-24):
        raise ValueError("degenerate tetrahedron")
    names = {name: (int(value[0]), int(value[1])) for name, value in mesh.field_data.items()}
    expected = set()
    for body in case.bodies:
        tag, dim = names.get(body, (-1, -1))
        if dim != 3:
            raise ValueError(f"missing physical volume: {body}")
        if tag in expected:
            raise ValueError("volume names must refer to distinct physical groups")
        expected.add(tag)
    if set(ids) != expected:
        raise ValueError("case bodies must cover exactly the meshed physical volumes")
    faces = defaultdict(list)
    for i, t in enumerate(tetra):
        for f in ((t[0], t[1], t[2]), (t[0], t[1], t[3]), (t[0], t[2], t[3]), (t[1], t[2], t[3])):
            faces[tuple(sorted(f))].append(i)
    if any(len(owners) > 2 for owners in faces.values()):
        raise ValueError("non-manifold volume mesh")
    result = VolumeMesh(mesh, tetra, np.asarray(ids), np.asarray(triangles, dtype=int).reshape((-1, 3)), np.asarray(surfaces), names, dict(faces))
    exterior = {f for f, owners in faces.items() if len(owners) == 1}
    outer = result.surface(case.outer_boundary)
    if {tuple(sorted(f)) for f in outer} != exterior:
        raise ValueError("outer_boundary must cover every exterior face, including axial ends")
    closed_surface(outer, mesh.points)
    if case.stress_surface:
        stress = result.surface(case.stress_surface)
        closed_surface(stress, mesh.points)
        body_material = {names[b][0]: case.materials[m] for b, m in case.bodies.items()}
        for f in stress:
            owners = faces.get(tuple(sorted(f)), [])
            if len(owners) != 2:
                raise ValueError("stress surface must be internal to the exterior domain")
            for i in owners:
                law = body_material[ids[i]]
                if law.kind != "linear" or law.relative_permeability != 1.0:
                    raise ValueError("both sides of stress surface must be nonmagnetic air")
                if any(ids[i] == names[b][0] for coil in case.coils.values() for b in coil.bodies):
                    raise ValueError("stress surface must not touch a current-carrying coil")
    for coil in case.coils.values():
        coil_ids = {names[b][0] for b in coil.bodies}
        skin = [f for f, owners in faces.items() if sum(ids[i] in coil_ids for i in owners) == 1]
        closed_surface(np.asarray(skin), mesh.points)
        vertices = {v for f in skin for v in f}
        edges = {tuple(sorted((f[i], f[(i + 1) % 3]))) for f in skin for i in range(3)}
        if len(vertices) - len(edges) + len(skin) != 0:
            raise ValueError("each closed coil must be one solid torus, including end connections")
    return result


def maxwell_stress(mesh: VolumeMesh, surface: str, magnetic_b: np.ndarray, origin: tuple[float, ...]) -> dict:
    """Integrate vacuum Maxwell traction over a closed surface with degree-three quadrature."""
    triangles = closed_surface(mesh.surface(surface), mesh.mesh.points)
    p = mesh.mesh.points[triangles]
    b = magnetic_b[triangles]
    area_vectors = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]) / 2
    force = np.zeros(3)
    torque = np.zeros(3)
    quadrature = [((1 / 3, 1 / 3, 1 / 3), -27 / 48), ((0.6, 0.2, 0.2), 25 / 48), ((0.2, 0.6, 0.2), 25 / 48), ((0.2, 0.2, 0.6), 25 / 48)]
    for weights, weight in quadrature:
        bg = np.einsum("j,ijk->ik", weights, b)
        r = np.einsum("j,ijk->ik", weights, p) - np.asarray(origin)
        traction = (bg * np.einsum("ij,ij->i", bg, area_vectors)[:, None] - 0.5 * np.einsum("ij,ij->i", bg, bg)[:, None] * area_vectors) / (
            4e-7 * np.pi
        )
        force += traction.sum(axis=0) * weight
        torque += np.cross(r, traction).sum(axis=0) * weight
    return {"force_N": force.tolist(), "torque_Nm": torque.tolist(), "method": "closed_air_surface_maxwell_stress"}
