"""Body-selected weighted Maxwell stress for the experimental reference adapter.

Only the auxiliary harmonic weighting problem is solved here. The magnetic
field always comes from Magneto2D (or the retained FEMM reference answer).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.experimental.femm_outrunner import DEPTH_M, MU0, FixtureMesh, element_fields, source


@dataclass
class Weighting:
    element_indices: np.ndarray
    gradients_per_m: np.ndarray
    areas_m2: np.ndarray
    centers_m: np.ndarray
    relative_residual: float
    iterations: int
    weight_min: float
    weight_max: float


def build_outer_body_weighting(mesh: FixtureMesh, tolerance: float = 1e-10, max_iterations: int = 4000) -> Weighting:
    labels = source()["labels"]
    air_labels = [x["index"] for x in labels if x["material"] == "Air"]
    rotor_labels = [x["index"] for x in labels if x["group"] == 2]
    air = np.isin(mesh.label_ids, air_labels)
    rotor = np.isin(mesh.label_ids, rotor_labels)
    stationary = ~air & ~rotor
    indices = np.flatnonzero(air)
    triangles_global = mesh.triangles[indices]
    nodes = np.unique(triangles_global)
    local = np.full(len(mesh.nodes_mm), -1, dtype=np.int64)
    local[nodes] = np.arange(len(nodes))
    triangles = local[triangles_global]
    xyz = mesh.nodes_mm[triangles_global]*1e-3
    a, b, c = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    signed2 = (b[:, 0]-a[:, 0])*(c[:, 1]-a[:, 1])-(b[:, 1]-a[:, 1])*(c[:, 0]-a[:, 0])
    area = abs(signed2)/2
    grad = np.stack((np.column_stack((b[:, 1]-c[:, 1], c[:, 0]-b[:, 0])),
                     np.column_stack((c[:, 1]-a[:, 1], a[:, 0]-c[:, 0])),
                     np.column_stack((a[:, 1]-b[:, 1], b[:, 0]-a[:, 0]))), axis=1)/signed2[:, None, None]
    stiff = area[:, None, None]*np.einsum("tik,tjk->tij", grad, grad)
    rows = np.repeat(triangles, 3, axis=1).ravel()
    columns = np.tile(triangles, (1, 3)).ravel()
    entries = stiff.ravel()
    body = local[np.unique(mesh.triangles[rotor])]
    fixed_zero = local[np.unique(mesh.triangles[stationary])]
    body, fixed_zero = body[body >= 0], fixed_zero[fixed_zero >= 0]
    if not len(body) or not len(fixed_zero) or np.intersect1d(body, fixed_zero).size:
        raise ValueError("Weighting requires disjoint rotating and stationary boundary nodes")
    fixed = np.unique(np.concatenate((body, fixed_zero)))
    known = np.zeros(len(nodes))
    known[body] = 1

    def matrix_product(value):
        return np.bincount(rows, weights=entries*value[columns], minlength=len(nodes))

    rhs = -matrix_product(known)
    rhs[fixed] = 0

    def product(value):
        free_value = value.copy()
        free_value[fixed] = 0
        result = matrix_product(free_value)
        result[fixed] = value[fixed]
        return result

    diagonal = np.bincount(rows[rows == columns], weights=entries[rows == columns], minlength=len(nodes))
    diagonal[fixed] = 1
    if (diagonal <= 0).any():
        raise ValueError("Auxiliary weighting has a non-positive diagonal")
    weights = np.zeros(len(nodes))
    residual = rhs.copy()
    norm_rhs = np.linalg.norm(rhs)
    z = residual/diagonal
    direction = z.copy()
    rz = float(np.dot(residual, z))
    relative = 1.0
    for iteration in range(1, max_iterations+1):
        action = product(direction)
        denominator = float(np.dot(direction, action))
        if denominator <= 0:
            raise ValueError("Weighting conjugate-gradient operator is not positive definite")
        alpha = rz/denominator
        weights += alpha*direction
        residual = rhs-product(weights) if iteration % 50 == 0 else residual-alpha*action
        relative = float(np.linalg.norm(residual)/norm_rhs)
        if relative <= tolerance:
            # Confirm convergence using the true residual, not only recurrence.
            residual = rhs-product(weights)
            relative = float(np.linalg.norm(residual)/norm_rhs)
            if relative <= tolerance:
                break
        z = residual/diagonal
        updated = float(np.dot(residual, z))
        direction = z+(updated/rz)*direction
        rz = updated
    else:
        raise ValueError(f"Auxiliary weighting did not converge: residual={relative}")
    weights += known
    gradient = np.einsum("ti,tij->tj", weights[triangles], grad)
    return Weighting(indices, gradient, area, xyz.mean(axis=1), relative, iteration, float(weights.min()), float(weights.max()))


def weighted_stress_torque(mesh: FixtureMesh, az_nodal: np.ndarray, weighting: Weighting | None = None) -> dict[str, float | str | int]:
    weighting = weighting or build_outer_body_weighting(mesh)
    field = element_fields(mesh, az_nodal)[weighting.element_indices]
    bx, by = field[:, 0], field[:, 1]
    sxx = (bx*bx-by*by)/(2*MU0)
    sxy = bx*by/MU0
    wx, wy = weighting.gradients_per_m[:, 0], weighting.gradients_per_m[:, 1]
    force_x = sxx*wx+sxy*wy
    force_y = sxy*wx-sxx*wy
    centers = weighting.centers_m
    torque = -DEPTH_M*np.sum(weighting.areas_m2*(-centers[:, 1]*force_x+centers[:, 0]*force_y))
    return {"outer_rotor_torque_Nm": float(torque), "body": "all_outer_rotor_magnets_and_back_iron",
            "method": "P1_weighted_Maxwell_stress_full_connected_air_domain",
            "weighting_relative_residual": weighting.relative_residual, "weighting_iterations": weighting.iterations,
            "weight_min": weighting.weight_min, "weight_max": weighting.weight_max}
