"""Internal full-machine rotor motion with fixed material meshes (#306).

The rotor (including magnets and shaft) moves rigidly, the stator stays fixed,
and only the circular air-gap annulus is triangulated again. The rotor may be
inside the gap or, for an outer-rotor machine, outside it. Every interface
node is shared with the original material cells: there are no penalty ties,
field interpolation, or changes to the loss kernel. Used by the opt-in rotor-loss stage.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math

import numpy as np

from backend.geometry_drawer import compute_3phase_slot_ampere_turns_for_rotor_elec
from backend.gmsh_mesh_rotation import rebake_solve_mesh_artifact_currents
from backend.topology_provenance import build_topology_provenance

METHOD = "fixed_material_conforming_airgap/v1"


def annular_strip(nodes, inner, outer):
    """A conforming, CCW zipper between two complete, concentric polygon rings.

    Advance the next angular vertex on either ring. Each boundary edge is used
    once and the closing radial edge twice. Coincident angles choose the same
    diagonal to roundoff; angular rounding only orders nodes, never moves them.
    """
    xy = np.asarray(nodes)
    rings = []
    angles = []
    for indices in (inner, outer):
        indices = np.asarray(indices, dtype=int)
        a = np.mod(np.arctan2(xy[indices, 1], xy[indices, 0]), 2*math.pi)
        a[np.abs(a-2*math.pi) < 1e-12] = 0.0
        a = np.round(a, 12)
        order = np.argsort(a)
        a, indices = a[order], indices[order]
        if len(a) < 3 or np.any(np.diff(a) <= 0):
            raise ValueError("air-gap rings need distinct angular vertices")
        rings.append(np.r_[indices[-1], indices])
        angles.append(np.r_[a[-1]-2*math.pi, a])
    a, b = rings
    aa, ab = angles
    i = j = 0
    triangles = []
    while i < len(a)-1 or j < len(b)-1:
        if i < len(a)-1 and (j == len(b)-1 or aa[i+1] <= ab[j+1]):
            triangles.append((a[i], b[j], a[i+1]))
            i += 1
        else:
            triangles.append((a[i], b[j], b[j+1]))
            j += 1
    return np.asarray(triangles, dtype=int)


def triangle_metrics(nodes, triangles):
    corners = np.asarray(nodes)[np.asarray(triangles)]
    u, v = corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0]
    area2 = u[:, 0]*v[:, 1]-u[:, 1]*v[:, 0]
    edge_sq = np.sum(u*u, axis=1)+np.sum(v*v, axis=1)+np.sum((u-v)**2, axis=1)
    return area2/2, 2*math.sqrt(3)*area2/edge_sq


def euler_characteristic(node_count, triangles):
    """Nodes - edges + faces: 1 for a filled disk, 0 for a ring with one hole."""
    triangles = np.asarray(triangles)
    edges = np.unique(np.sort(np.concatenate((triangles[:, :2], triangles[:, 1:], triangles[:, [2, 0]])), axis=1), axis=0)
    return int(node_count)-len(edges)+len(triangles)


def validate_conforming_disk(nodes, triangles, boundary_nodes, *, holes=0):
    """All faces positive, all internal edges shared, one region with no orphans.

    ``holes`` is the number of unmeshed openings inside the region: none for a
    filled disk, one for an outer-rotor mesh whose stator bore is left open.
    """
    triangles = np.asarray(triangles)
    if not np.array_equal(np.unique(triangles), np.arange(len(nodes))):
        raise ValueError("motion mesh has orphan or invalid nodes")
    area, quality = triangle_metrics(nodes, triangles)
    if not np.isfinite(area).all() or np.min(area) <= 0 or np.min(quality) < 0.01:
        raise ValueError("motion mesh has inverted, degenerate or poor-quality cells")
    edges = np.sort(np.concatenate((triangles[:, :2], triangles[:, 1:], triangles[:, [2, 0]])), axis=1)
    edges, counts = np.unique(edges, axis=0, return_counts=True)
    if np.max(counts) > 2 or set(np.unique(edges[counts == 1])) != set(boundary_nodes):
        raise ValueError("motion mesh has a nonconforming edge or an internal crack")
    if len(nodes)-len(edges)+len(triangles) != 1-holes:
        raise ValueError("motion mesh is not a single filled disk" if not holes
                         else "motion mesh is not a single ring around its opening")
    return {"minimum_quality": float(np.min(quality)), "area_mm2": float(np.sum(area)),
            "boundary_edges": int(np.sum(counts == 1))}


class FixedMaterialRotorMesh:
    """Reusable geometry template; every pose still requires a fresh field solve.

    Full-circle inner-rotor SPM or IPM, or outer-rotor SPM, with one circular
    sliding gap. Unsupported geometry fails explicitly. The default mesher path
    is unchanged.
    """

    def __init__(self, artifact, *, angular_divisions=1536, radial_layers=4):
        if (isinstance(angular_divisions, bool) or not isinstance(angular_divisions, int) or angular_divisions < 32
                or isinstance(radial_layers, bool) or not isinstance(radial_layers, int) or radial_layers < 2):
            raise ValueError("air-gap motion needs at least 32 angular divisions and two radial layers")
        self.base = copy.deepcopy(artifact)
        self.geometry = self.base["topology_provenance"]["geometry"]
        mesh = self.base["mesh"]
        info = mesh["info"]
        contract = self.base["physics_contract"]
        layout = info.get("rotor_layout", "inner")
        if (mesh["length_units"] != "mm" or info["total_span_deg"] != 360 or mesh.get("sector_edge_pairs")
                or info.get("sector") or layout not in {"inner", "outer"}
                or contract["topology_hint"] not in ({"SPM"} if layout == "outer" else {"SPM", "IPM"})):
            raise ValueError("fixed material motion currently requires a full-circle inner PM or outer SPM mesh")
        # The rotor is the material inside the gap, or outside it for an outer rotor.
        self.outer_rotor = layout == "outer"
        self.base_angle = float(self.base["rotor_angle_mech_deg"])
        self.ri, self.ro = info["airgap_inner_radius_mm"], info["airgap_outer_radius_mm"]
        if not math.isfinite(self.base_angle) or not 0 < self.ri < self.ro:
            raise ValueError("invalid circular air-gap geometry or reference pose")
        if (contract["motion"].get("rotor_state") != "baked_in_mesh"
                or contract["motion"].get("rotor_angle_mech_deg") != self.base_angle):
            raise ValueError("motion template has stale or missing baked rotor state")
        entries = {r["id"]: r for r in contract["regions"]}
        gaps = [r["id"] for r in entries.values() if r["motion_group"] == "sliding_airgap"]
        if len(gaps) != 1 or entries[gaps[0]]["kind"] != "Airgap":
            raise ValueError("fixed material motion requires exactly one circular air-gap region")
        self.gap_id = gaps[0]
        ids = np.asarray(self.base["element_region_ids"])
        source_nodes, source_triangles = np.asarray(mesh["nodes"]), np.asarray(mesh["triangles"], dtype=int)
        self.keep = np.flatnonzero(ids != self.gap_id)
        if len(ids) != len(source_triangles) or not len(self.keep) or len(self.keep) == len(ids):
            raise ValueError("motion template has missing element regions or air-gap cells")
        moving = np.array([entries[r]["motion_group"] == "rotor" for r in ids[self.keep]])
        moving_nodes = np.unique(source_triangles[self.keep[moving]])
        fixed_nodes = np.unique(source_triangles[self.keep[~moving]])
        if len(np.intersect1d(moving_nodes, fixed_nodes)):
            raise ValueError("rotor and stator material meshes intersect across the air gap")
        radius = np.hypot(source_nodes[:, 0], source_nodes[:, 1])
        inside, outside = (fixed_nodes, moving_nodes) if self.outer_rotor else (moving_nodes, fixed_nodes)
        if (np.max(radius[inside]) > self.ri+1e-7 or np.min(radius[outside]) < self.ro-1e-7):
            raise ValueError("material regions do not bound the declared circular gap")
        # An inner-rotor mesh is a filled disk. An outer-rotor mesh may leave the stator bore open.
        self.holes = 1-euler_characteristic(len(np.unique(source_triangles)), source_triangles)
        if self.holes not in ((0, 1) if self.outer_rotor else (0,)):
            raise ValueError("motion template is not a filled disk or a single ring around the stator bore")
        used = np.union1d(moving_nodes, fixed_nodes)
        remap = np.full(len(source_nodes), -1, dtype=int)
        remap[used] = np.arange(len(used))
        self.nodes = source_nodes[used].copy()
        self.triangles = remap[source_triangles[self.keep]]
        self.moving_nodes = remap[moving_nodes]
        self.boundary_nodes = remap[np.asarray(mesh["boundary_nodes"], dtype=int)].tolist()
        if min(self.boundary_nodes) < 0:
            raise ValueError("outer boundary intersects the removed air gap")
        self.inner = remap[inside[np.abs(radius[inside]-self.ri) < 1e-7]]
        self.outer = remap[outside[np.abs(radius[outside]-self.ro) < 1e-7]]
        self.angular_divisions, self.radial_layers = angular_divisions, radial_layers
        self.template_sha256 = hashlib.sha256(json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        # Interface ring edges must be complete material boundaries, rather
        # than merely a set of nearby nodes that would leave hanging nodes.
        edges = np.sort(np.concatenate((self.triangles[:, :2], self.triangles[:, 1:], self.triangles[:, [2, 0]])), axis=1)
        edges, counts = np.unique(edges, axis=0, return_counts=True)
        boundary = {tuple(e) for e in edges[counts == 1]}
        for ring in (self.inner, self.outer):
            angles = np.arctan2(self.nodes[ring, 1], self.nodes[ring, 0])
            ring = ring[np.argsort(angles)]
            if len(ring) < 3 or any(tuple(sorted((a, b))) not in boundary for a, b in zip(ring, np.roll(ring, -1))):
                raise ValueError("air-gap material interface is not a complete polygon ring")

    def at_angle(self, config, mechanical_angle_deg):
        if not math.isfinite(mechanical_angle_deg):
            raise ValueError("motion needs a finite unwrapped mechanical angle")
        if (build_topology_provenance(config)["geometry"] != self.geometry
                or getattr(config.solve_params, "symmetry", "full") != "full"):
            raise ValueError("motion template geometry or full-machine request differs")
        delta = math.radians(math.remainder(mechanical_angle_deg-self.base_angle, 360))
        c, s = math.cos(delta), math.sin(delta)
        rotation = np.array([[c, -s], [s, c]])
        nodes = self.nodes.copy()
        nodes[self.moving_nodes] = nodes[self.moving_nodes] @ rotation.T
        rings = [self.inner]
        chunks = [nodes]
        offset = len(nodes)
        angles = 2*math.pi*np.arange(self.angular_divisions)/self.angular_divisions
        for layer in range(1, self.radial_layers):
            radius = self.ri+(self.ro-self.ri)*layer/self.radial_layers
            # The band layers on the rotor's side of the gap turn with it.
            with_rotor = 2*layer >= self.radial_layers if self.outer_rotor else 2*layer <= self.radial_layers
            a = angles+(delta if with_rotor else 0.0)
            chunks.append(radius*np.column_stack((np.cos(a), np.sin(a))))
            rings.append(np.arange(offset, offset+self.angular_divisions))
            offset += self.angular_divisions
        rings.append(self.outer)
        nodes = np.concatenate(chunks)
        band = np.concatenate([annular_strip(nodes, inner, outer) for inner, outer in zip(rings, rings[1:])])
        triangles = np.concatenate((self.triangles, band))
        qa = validate_conforming_disk(nodes, triangles, self.boundary_nodes, holes=self.holes)
        result = copy.deepcopy(self.base)
        mesh = result["mesh"]
        mesh.update(nodes=nodes.tolist(), triangles=triangles.tolist(), boundary_nodes=self.boundary_nodes.copy())
        mesh["regions"] = [mesh["regions"][i] for i in self.keep]+["Airgap"]*len(band)
        for name, fill in (("element_region_ids", self.gap_id), ("element_magnetization", None),
                           ("element_current_density_a_per_m2", None)):
            result[name] = [result[name][i] for i in self.keep]+[fill]*len(band)
        result["element_magnetization"] = [None if a is None else (a+math.degrees(delta)) % 360
                                           for a in result["element_magnetization"]]
        result["rotor_angle_mech_deg"] = mechanical_angle_deg
        contract = result["physics_contract"]
        contract["motion"]["rotor_angle_mech_deg"] = mechanical_angle_deg
        for entry in contract["regions"]:
            if entry.get("magnetization_angle_deg") is not None:
                entry["magnetization_angle_deg"] = (entry["magnetization_angle_deg"]+math.degrees(delta)) % 360
        provenance = contract["provenance"]
        for name, values in list(provenance.items()):
            if name.startswith("element_") and isinstance(values, list):
                fill = {"element_region_sources": "conforming_airgap_band",
                        "element_material_sources": "geometry_ir"}.get(name, "none")
                provenance[name] = [values[i] for i in self.keep]+[fill]*len(band)
        motion = {"method": METHOD, "template_sha256": self.template_sha256,
                  "angular_divisions": self.angular_divisions, "radial_layers": self.radial_layers,
                  "fixed_material_cells": len(self.keep), "airgap_cells": len(band), "qa": qa}
        provenance["material_motion_mesh"] = motion
        mesh["info"].update(num_nodes=len(nodes), num_triangles=len(triangles), material_motion_mesh=motion)
        return rebake_solve_mesh_artifact_currents(
            result, phase_ampere_turns=lambda elec: compute_3phase_slot_ampere_turns_for_rotor_elec(config, elec),
            current_angle_elec_deg_for_mech=lambda mech: mech*config.rotor.pole_count/2,
        )
