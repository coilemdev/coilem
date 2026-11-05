"""Exact inputs and field diagnostics for the pinned FEMM LRK outrunner.

This module does not coerce an outrunner into the inner-rotor MotorConfig.
Its first consumer is an experimental comparison tool, not a public route.
The generic Magneto2D field contract keeps all materials and sources explicit.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

FIXTURE_ID = "femm_lrk_12s14p_v1"
SOURCE_SHA256 = "e69cce40a56f0c9840892a122cda86e5b3fa69d0b0c6ccc718d4d430b059253e"
ASSET_SHA256 = "474c5ce06d530a9c6281da165f83e28eeba40ba3458617001b18d11b5e17d608"
MU0 = 4e-7 * math.pi
DEPTH_M = 0.010


@lru_cache(maxsize=1)
def source() -> dict[str, Any]:
    path = Path(__file__).with_name("data") / f"{FIXTURE_ID}.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ASSET_SHA256:
        raise ValueError("Outrunner source asset changed; create and audit a new fixture version")
    result = json.loads(raw)
    if result["sha256"] != SOURCE_SHA256 or result["fixture_id"] != FIXTURE_ID:
        raise ValueError("Outrunner source identity mismatch")
    return result


@dataclass
class FixtureMesh:
    nodes_mm: np.ndarray
    triangles: np.ndarray
    label_ids: np.ndarray
    dirichlet_nodes: np.ndarray
    reference_az: np.ndarray | None = None
    provenance: dict[str, Any] | None = None

    def geometry(self) -> tuple[np.ndarray, np.ndarray]:
        xyz = self.nodes_mm[self.triangles] * 1e-3
        a, b = xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0]
        cross = a[:, 0]*b[:, 1]-a[:, 1]*b[:, 0]
        areas = abs(cross) * 0.5
        if not np.isfinite(areas).all() or (areas <= 0).any():
            raise ValueError("Nonfinite or degenerate outrunner mesh triangles")
        return xyz.mean(axis=1), areas

    def validate(self) -> None:
        if self.nodes_mm.ndim != 2 or self.nodes_mm.shape[1] != 2 or not np.isfinite(self.nodes_mm).all():
            raise ValueError("Expected finite XY mesh nodes in mm")
        if self.triangles.ndim != 2 or self.triangles.shape[1] != 3:
            raise ValueError("Expected P1 triangle connectivity")
        if self.triangles.size == 0 or self.triangles.min() < 0 or self.triangles.max() >= len(self.nodes_mm):
            raise ValueError("Invalid triangle node index")
        if len(self.label_ids) != len(self.triangles) or set(self.label_ids.tolist()) != set(range(29)):
            raise ValueError("The full source fixture requires all 29 exact block-label regions")
        if len(self.dirichlet_nodes) == 0 or self.dirichlet_nodes.min() < 0 or self.dirichlet_nodes.max() >= len(self.nodes_mm):
            raise ValueError("Missing or invalid prescribed-boundary nodes")
        radii = np.linalg.norm(self.nodes_mm[self.dirichlet_nodes], axis=1)
        # FEMM's Triangle mesh may subdivide straight chords of its 5-degree
        # bore arcs. The maximum source chord sagitta is 0.00619 mm.
        boundary_tolerance_mm = 0.007
        if not np.logical_or(abs(radii - 6.5) < boundary_tolerance_mm, abs(radii - 15.39) < boundary_tolerance_mm).all():
            raise ValueError("Source Dirichlet nodes must lie on the bore and outer back-iron circles")
        if not (np.any(abs(radii - 6.5) < boundary_tolerance_mm) and np.any(abs(radii - 15.39) < boundary_tolerance_mm)):
            raise ValueError("Both source Dirichlet circles must be retained")
        self.geometry()


def boundary_nodes(triangles: np.ndarray) -> np.ndarray:
    edges = np.sort(np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]])), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    if (counts > 2).any():
        raise ValueError("Non-manifold mesh edge")
    return np.unique(unique[counts == 1])


def read_femm_answer(path: Path) -> FixtureMesh:
    """Read the full, non-sliding planar FEMM answer, retaining block-label IDs."""
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    if "[Solution]" not in text or "[ProblemType] =  planar" not in text:
        raise ValueError("Expected a planar FEMM answer")
    header, solution = text.split("[Solution]", 1)
    for fact in ("[LengthUnits] =  millimeters", "[Depth]       =  10", "[NumBlockLabels] = 29"):
        if fact not in header:
            raise ValueError(f"Answer differs from the pinned full fixture: {fact}")
    rows = iter(solution.strip().splitlines())
    count = int(next(rows))
    nodes = np.asarray([[float(v) for v in next(rows).split()] for _ in range(count)])
    count = int(next(rows))
    elements = np.asarray([[int(v) for v in next(rows).split()[:4]] for _ in range(count)], dtype=np.int64)
    mesh = FixtureMesh(nodes[:, :2], elements[:, :3], elements[:, 3], boundary_nodes(elements[:, :3]), nodes[:, 2],
                       {"mesh_source": "FEMM_reference_diagnostic", "answer_sha256": hashlib.sha256(raw).hexdigest()})
    mesh.validate()
    return mesh


def material_models() -> list[dict[str, Any]]:
    """Explicit source points with in-plane fill homogenization.

    This initial law is intentionally named piecewise-linear: FEMM's spline
    equivalence remains a separate coupon/qualification obligation.
    """
    result = []
    for raw in source()["materials"]:
        points = raw["bh_points_T_A_per_m"]
        if points:
            fill = float(raw["LamFill"])
            resolved = [{"b_t": fill * b + (1 - fill) * MU0 * h, "h_a_per_m": h} for b, h in points]
            result.append({"kind": "nonlinear", "bh_curve": {"points": resolved, "mu_r_min": 1, "mu_r_max": 1e6}})
        else:
            result.append({"kind": "linear", "mu_r": float(raw["Mu_x"])})
    return result


def build_field_problem(mesh: FixtureMesh, currents: tuple[float, float, float] = (0, 4, -4),
                        rotor_angle_ccw_deg: float = 0) -> dict[str, Any]:
    mesh.validate()
    current = np.asarray(currents, dtype=float)
    if current.shape != (3,) or not np.isfinite(current).all() or abs(current.sum()) > 1e-10:
        raise ValueError("Specify three finite balanced circuit currents [A,B,C]")
    if not math.isfinite(rotor_angle_ccw_deg):
        raise ValueError("Rotor angle must be finite")
    _, areas = mesh.geometry()
    region_areas = np.bincount(mesh.label_ids, weights=areas, minlength=29)
    labels = source()["labels"]
    materials = source()["materials"]
    per_label = []
    for label in labels:
        raw = materials[label["material_index_1based"] - 1]
        density = 0.0
        if label["circuit"]:
            density = label["signed_turns"] * current["ABC".index(label["circuit"])] / region_areas[label["index"]]
        br = raw.get("derived_Br_T_if_isotropic_linear_recoil", 0.0)
        angle = math.radians(label["magnetization_angle_deg_raw"] + rotor_angle_ccw_deg)
        per_label.append({"material_id": label["material_index_1based"] - 1,
                          "current_density_z_a_per_m2": float(density),
                          "remanence_t": [br * math.cos(angle), br * math.sin(angle)]})
    return {
        "kind": "magnetostatic_problem", "version": "1.0", "units": {"length": "mm"},
        "mesh": {"nodes": mesh.nodes_mm.tolist(), "triangles": mesh.triangles.tolist()},
        "materials": material_models(), "elements": [per_label[int(i)] for i in mesh.label_ids],
        "boundaries": {"dirichlet_az_zero_nodes": mesh.dirichlet_nodes.tolist()},
        "options": {"linear": {"solver": "direct", "tolerance": 1e-8, "max_iterations": 10000},
                    "nonlinear": {"algorithm": "newton", "tolerance": 1e-5, "max_iterations": 300}},
    }


def element_fields(mesh: FixtureMesh, az_nodal: np.ndarray) -> np.ndarray:
    xyz = mesh.nodes_mm[mesh.triangles] * 1e-3
    a, b, c = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    signed2 = (b[:, 0]-a[:, 0])*(c[:, 1]-a[:, 1]) - (b[:, 1]-a[:, 1])*(c[:, 0]-a[:, 0])
    values = np.asarray(az_nodal)[mesh.triangles]
    dx = ((b[:, 1]-c[:, 1])*values[:, 0] + (c[:, 1]-a[:, 1])*values[:, 1] + (a[:, 1]-b[:, 1])*values[:, 2]) / signed2
    dy = ((c[:, 0]-b[:, 0])*values[:, 0] + (a[:, 0]-c[:, 0])*values[:, 1] + (b[:, 0]-a[:, 0])*values[:, 2]) / signed2
    return np.column_stack((dy, -dx))


def phase_linkage(mesh: FixtureMesh, az_nodal: np.ndarray) -> np.ndarray:
    _, areas = mesh.geometry()
    az = np.asarray(az_nodal, dtype=float)
    if az.shape != (len(mesh.nodes_mm),) or not np.isfinite(az).all():
        raise ValueError("Expected one finite Az value per mesh node")
    region_areas = np.bincount(mesh.label_ids, weights=areas, minlength=29)
    integral = np.bincount(mesh.label_ids, weights=areas * az[mesh.triangles].mean(axis=1), minlength=29)
    result = np.zeros(3)
    for label in source()["labels"]:
        if label["circuit"]:
            i = label["index"]
            result["ABC".index(label["circuit"])] += DEPTH_M * label["signed_turns"] * integral[i] / region_areas[i]
    return result


def summarize_field(mesh: FixtureMesh, az_nodal: np.ndarray) -> dict[str, Any]:
    from backend.experimental.outrunner_stress import weighted_stress_torque

    centers, areas = mesh.geometry()
    field = element_fields(mesh, az_nodal)
    radius = np.linalg.norm(centers, axis=1)
    radial = centers / radius[:, None]
    br = (field * radial).sum(axis=1)
    bt = -field[:, 0]*radial[:, 1] + field[:, 1]*radial[:, 0]
    air_labels = [x["index"] for x in source()["labels"] if x["material"] == "Air"]
    in_gap = (radius >= 0.0128) & (radius <= 0.0130) & np.isin(mesh.label_ids, air_labels)
    if not in_gap.any():
        raise ValueError("No physical main air-gap elements")
    enclosed = DEPTH_M / (MU0 * 0.0002) * float(np.sum(radius[in_gap] * br[in_gap] * bt[in_gap] * areas[in_gap]))
    contours = contour_torque(mesh, az_nodal)
    return {"phase_linkage_Wb": phase_linkage(mesh, az_nodal).tolist(),
            "torque_outer_rotor_arkkio_Nm": -enclosed,
            "torque_enclosed_stator_arkkio_Nm": enclosed,
            "torque_method": "centroid-filtered-main-gap-Arkkio-diagnostic; requires convergence",
            "torque_contours": contours,
            "torque_weighted_stress": weighted_stress_torque(mesh, az_nodal),
            "gap_element_count": int(in_gap.sum()), "nodes": len(mesh.nodes_mm), "elements": len(mesh.triangles)}


def contour_torque(mesh: FixtureMesh, az_nodal: np.ndarray,
                   radii_mm: tuple[float, ...] = (12.85, 12.9, 12.95)) -> list[dict[str, float]]:
    """Integrate P1 Maxwell stress exactly on each circle/triangle intersection.

    For constant Cartesian element B, Br*Bt is a second angular harmonic.
    Analytic arc integration avoids point-location sampling and angular aliasing.
    Return the outer body's action/reaction torque with complete-circle checks.
    """
    xyz = mesh.nodes_mm[mesh.triangles] * 1e-3
    centers = xyz.mean(axis=1)
    extent = np.linalg.norm(xyz-centers[:, None], axis=2).max(axis=1)
    center_radius = np.linalg.norm(centers, axis=1)
    field = element_fields(mesh, az_nodal)
    air_labels = [x["index"] for x in source()["labels"] if x["material"] == "Air"]
    air = np.isin(mesh.label_ids, air_labels)
    results = []
    for radius_mm in radii_mm:
        if not 12.81 < radius_mm < 12.99:
            raise ValueError("Torque contours must stay inside the physical main air gap")
        radius = radius_mm*1e-3
        candidates = np.flatnonzero(air & (abs(center_radius-radius) <= extent+1e-14))
        total, coverage = 0.0, 0.0
        for index in candidates:
            points = xyz[index]
            cuts = []
            for j in range(3):
                a, b = points[j], points[(j+1) % 3]
                delta = b-a
                qa = float(np.dot(delta, delta))
                qb = 2*float(np.dot(a, delta))
                qc = float(np.dot(a, a))-radius*radius
                disc = qb*qb-4*qa*qc
                if disc < 0:
                    continue
                root = math.sqrt(max(0, disc))
                for t in ((-qb-root)/(2*qa), (-qb+root)/(2*qa)):
                    if -1e-10 <= t <= 1+1e-10:
                        point = a+min(1, max(0, t))*delta
                        cuts.append(math.atan2(point[1], point[0]) % (2*math.pi))
            cuts.sort()
            unique = []
            for cut in cuts:
                if not unique or abs(cut-unique[-1]) > 1e-11:
                    unique.append(cut)
            if len(unique) < 2:
                continue
            for start, stop in zip(unique, [*unique[1:], unique[0]+2*math.pi]):
                theta = (start+stop)/2
                point = radius*np.array([math.cos(theta), math.sin(theta)])
                edge = np.roll(points, -1, axis=0)-points
                relative = point-points
                cross = edge[:, 0]*relative[:, 1]-edge[:, 1]*relative[:, 0]
                if not ((cross >= -1e-20).all() or (cross <= 1e-20).all()):
                    continue
                bx, by = field[index]
                total += 0.5*bx*by*(math.sin(2*stop)-math.sin(2*start))-0.25*(by*by-bx*bx)*(math.cos(2*stop)-math.cos(2*start))
                coverage += stop-start
        if not math.isclose(coverage, 2*math.pi, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(f"Torque contour lacks unique full coverage: r={radius_mm} mm, span={coverage}")
        results.append({"radius_mm": radius_mm, "outer_rotor_torque_Nm": -DEPTH_M*radius*radius/MU0*total,
                        "coverage_rad": coverage})
    return results
