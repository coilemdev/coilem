"""Independent finite-element reference for cross-section heat conduction.

Linear triangles on a design's own Gmsh mesh: steady conduction with one
conductivity and one uniform heat source per region group, a fixed temperature
on one cylindrical face of the stator and insulated edges everywhere else.

It shares the geometry with the thermal network and nothing else. No network
formula is imported here, so agreement between the two is evidence and not an
identity. The solver is plain numpy (a matrix-free conjugate gradient), so the
check needs no extra dependency and no external program.
"""

from __future__ import annotations

import math

import numpy as np

# Mesh region names of the stator cross-section, by thermal node.
REGION_NODES = {"slot_winding": "winding", "stator_tooth": "teeth", "stator_yoke": "yoke"}


def solve_conduction(nodes_m, triangles, conductivity_W_mK, source_W_m3, fixed_C, *, tolerance=1e-11, max_iterations=40000):
    """Nodal temperatures for ``-div(k grad T) = q`` on linear triangles.

    ``fixed_C`` maps node index to its fixed temperature; every other boundary
    edge is insulated. Returns the temperatures and the solver's iteration count.
    """

    xy = np.asarray(nodes_m, dtype=float)
    tri = np.asarray(triangles, dtype=np.int64)
    k = np.asarray(conductivity_W_mK, dtype=float)
    q = np.asarray(source_W_m3, dtype=float)
    if tri.ndim != 2 or tri.shape[1] != 3 or len(k) != len(tri) or len(q) != len(tri) or not fixed_C:
        raise ValueError("Conduction needs triangles, one conductivity and source per triangle, and a fixed temperature")
    x, y = xy[tri, 0], xy[tri, 1]
    # Gradients of the three shape functions: (b_i, c_i) / (2 * area).
    b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
    c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
    signed = 0.5 * (b[:, 0] * c[:, 1] - b[:, 1] * c[:, 0])
    area = np.abs(signed)
    if np.any(area <= 0) or np.any(k <= 0):
        raise ValueError("Conduction needs triangles with area and positive conductivity")
    local = (k / (4 * area))[:, None, None] * (b[:, :, None] * b[:, None, :] + c[:, :, None] * c[:, None, :])
    rows = np.repeat(tri, 3, axis=1).ravel()
    cols = np.tile(tri, (1, 3)).ravel()
    values = local.ravel()
    count = len(xy)

    def apply(vector):
        return np.bincount(rows, weights=values * vector[cols], minlength=count)

    load = np.bincount(tri.ravel(), weights=np.repeat(q * area / 3, 3), minlength=count)
    fixed = np.zeros(count, dtype=bool)
    temperature = np.zeros(count)
    for index, value in fixed_C.items():
        fixed[index] = True
        temperature[index] = value
    used = np.zeros(count, dtype=bool)
    used[tri.ravel()] = True
    free = used & ~fixed
    rhs = (load - apply(temperature))[free]
    diagonal = np.bincount(tri.ravel(), weights=np.einsum("tii->ti", local).ravel(), minlength=count)[free]

    def apply_free(vector):
        full = np.zeros(count)
        full[free] = vector
        return apply(full)[free]

    # Jacobi-preconditioned conjugate gradient on the free nodes.
    solution = np.zeros(int(free.sum()))
    residual = rhs.copy()
    preconditioned = residual / diagonal
    direction = preconditioned.copy()
    rho = float(residual @ preconditioned)
    scale = float(np.linalg.norm(rhs)) or 1.0
    iterations = 0
    while np.linalg.norm(residual) > tolerance * scale:
        if iterations >= max_iterations:
            raise ValueError("Conduction reference did not converge")
        step = apply_free(direction)
        alpha = rho / float(direction @ step)
        solution += alpha * direction
        residual -= alpha * step
        preconditioned = residual / diagonal
        rho_next = float(residual @ preconditioned)
        direction = preconditioned + (rho_next / rho) * direction
        rho = rho_next
        iterations += 1
    temperature[free] = solution
    return temperature, iterations


def group_means(nodes_m, triangles, temperature_C, groups):
    """Area and area-weighted mean temperature of each named group of triangles."""

    xy = np.asarray(nodes_m, dtype=float)
    tri = np.asarray(triangles, dtype=np.int64)
    x, y = xy[tri, 0], xy[tri, 1]
    area = 0.5 * np.abs((x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0]))
    mean = np.asarray(temperature_C)[tri].mean(axis=1)
    names = np.asarray(groups)
    return {str(name): dict(area_m2=float(area[names == name].sum()),
                            mean_temperature_C=float((area * mean)[names == name].sum() / area[names == name].sum()))
            for name in dict.fromkeys(names.tolist())}


def stator_conduction_reference(mesh, *, fixed_radius_mm, boundary_C, conductivity_W_mK, heat_W, stack_length_m):
    """Solve the isolated stator cross-section on one generated mesh.

    ``mesh`` is a mesh preview (``nodes_mm``, ``triangles``, ``regions``). Each
    group's heat is spread uniformly over its meshed area, so the heat put in is
    exactly ``heat_W``. The face at ``fixed_radius_mm`` is held at ``boundary_C``.
    """

    regions = np.asarray(mesh["regions"])
    keep = np.isin(regions, list(REGION_NODES))
    tri = np.asarray(mesh["triangles"], dtype=np.int64)[keep]
    groups = np.asarray([REGION_NODES[name] for name in regions[keep]])
    nodes = np.asarray(mesh["nodes_mm"], dtype=float)[:, :2] * 1e-3
    means = group_means(nodes, tri, np.zeros(len(nodes)), groups)
    conductivity = np.asarray([conductivity_W_mK[name] for name in groups], dtype=float)
    source = np.asarray([heat_W[name] / (means[name]["area_m2"] * stack_length_m) for name in groups], dtype=float)
    radius = np.hypot(nodes[:, 0], nodes[:, 1])
    on_face = np.zeros(len(nodes), dtype=bool)
    on_face[tri.ravel()] = True
    on_face &= np.abs(radius - fixed_radius_mm * 1e-3) <= 1e-6 * max(1.0, fixed_radius_mm)
    if not on_face.any():
        raise ValueError("No mesh nodes lie on the stator face that is held at the boundary temperature")
    temperature, iterations = solve_conduction(nodes, tri, conductivity, source, dict.fromkeys(np.flatnonzero(on_face).tolist(), boundary_C))
    result = group_means(nodes, tri, temperature, groups)
    return dict(regions=[dict(node=name, **values) for name, values in result.items()], triangles=int(len(tri)),
                fixed_nodes=int(on_face.sum()), iterations=iterations, hottest_C=float(temperature[np.unique(tri)].max()))


def annulus_mean_rise(inner_m, outer_m, conductivity_W_mK, source_W_m3, *, fixed="outer"):
    """Closed-form mean temperature rise of a uniformly heated ring with one face fixed and the other insulated."""

    a, b = inner_m, outer_m
    q, k = source_W_m3, conductivity_W_mK
    if fixed == "outer":
        # T - Tb = q/(4k) (b^2 - r^2) + q a^2/(2k) ln(r/b)
        integral = q / (4 * k) * (b * b - a * a) ** 2 / 4 + q * a * a / (2 * k) * ((a * a - b * b) / 4 - a * a / 2 * math.log(a / b))
    else:
        # T - Ta = q/(4k) (a^2 - r^2) + q b^2/(2k) ln(r/a)
        integral = -q / (4 * k) * (b * b - a * a) ** 2 / 4 + q * b * b / (2 * k) * (b * b / 2 * math.log(b / a) - (b * b - a * a) / 4)
    return 2 * integral / (b * b - a * a)
