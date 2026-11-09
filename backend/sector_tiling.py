"""Tile one solved sector around the full circle.

A sector mesh covers ``1 / repeats`` of the motor. Copy ``k`` is the sector
turned by ``k`` sector spans; for an anti-periodic sector the vector potential
changes sign in every other copy. Nodes that land on the same point (the cut
edges of neighbouring copies, and the mid-gap arcs where the stator and rotor
wedges are offset) are merged, so the tiled mesh is one conforming mesh of the
whole motor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Merged nodes agree to round-off; this only has to beat the mesh spacing [mm].
_MERGE_TOL_MM = 1.0e-5


@dataclass(frozen=True)
class SectorTiling:
    """Index maps from a tiled full-circle mesh back to its sector."""

    repeats: int
    anti_periodic: bool
    span_deg: float
    nodes_mm: np.ndarray  # (N, 2)
    triangles: np.ndarray  # (T, 3)
    # Sector node each tiled node came from, and the sign its potential carries.
    node_source: np.ndarray
    node_sign: np.ndarray
    # Sector element and copy number of each tiled element.
    element_source: np.ndarray
    element_copy: np.ndarray

    def copy_sign(self, copy: int | np.ndarray) -> np.ndarray | float:
        if not self.anti_periodic:
            return np.ones_like(copy, dtype=float) if isinstance(copy, np.ndarray) else 1.0
        return 1.0 - 2.0 * (copy % 2)

    def tile_nodal(self, values) -> np.ndarray:
        """A nodal scalar that follows the potential's sign rule, e.g. A_z."""

        return np.asarray(values, dtype=float)[self.node_source] * self.node_sign

    def tile_element_scalar(self, values, *, signed: bool = False) -> np.ndarray:
        """A per-element scalar; ``signed`` ones (J, A_z) flip with the potential."""

        tiled = np.asarray(values, dtype=float)[self.element_source]
        return tiled * self.copy_sign(self.element_copy) if signed else tiled

    def tile_element_vector(self, vx, vy) -> tuple[np.ndarray, np.ndarray]:
        """A per-element in-plane vector that follows the field, e.g. B."""

        angle = np.radians(self.span_deg) * self.element_copy
        sign = self.copy_sign(self.element_copy)
        x = np.asarray(vx, dtype=float)[self.element_source]
        y = np.asarray(vy, dtype=float)[self.element_source]
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        return sign * (x * cos_a - y * sin_a), sign * (x * sin_a + y * cos_a)


def tile_sector_mesh(
    nodes_mm,
    triangles,
    *,
    repeats: int,
    anti_periodic: bool,
) -> SectorTiling:
    """Tile a sector mesh ``repeats`` times around the origin, merging coincident nodes."""

    nodes = np.asarray(nodes_mm, dtype=float).reshape(-1, 2)
    tris = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if repeats < 2:
        raise ValueError("a sector mesh needs at least two repeats")
    span = 2.0 * math.pi / repeats
    count = len(nodes)

    all_nodes = np.empty((repeats * count, 2))
    for copy in range(repeats):
        cos_a, sin_a = math.cos(copy * span), math.sin(copy * span)
        all_nodes[copy * count:(copy + 1) * count, 0] = nodes[:, 0] * cos_a - nodes[:, 1] * sin_a
        all_nodes[copy * count:(copy + 1) * count, 1] = nodes[:, 0] * sin_a + nodes[:, 1] * cos_a

    # Coincident nodes are exact rotations of each other up to round-off, far
    # below the grid, so they share a cell unless they straddle a cell edge.
    # A straddling pair would stay two nodes at one point: a display seam of
    # zero width, with every value on it still correct.
    keys = np.round(all_nodes / _MERGE_TOL_MM).astype(np.int64)
    _, kept_array, merged = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    merged = merged.reshape(-1)
    # Number merged nodes in first-appearance order, so copy 0 keeps the sector's own order.
    order = np.argsort(kept_array, kind="stable")
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    kept_array = kept_array[order]
    merged = rank[merged]

    node_copy = kept_array // count
    node_source = kept_array % count
    node_sign = (1.0 - 2.0 * (node_copy % 2)) if anti_periodic else np.ones(len(kept_array))

    tiled_tris = np.concatenate([merged[tris + copy * count] for copy in range(repeats)])
    element_source = np.tile(np.arange(len(tris), dtype=np.int64), repeats)
    element_copy = np.repeat(np.arange(repeats, dtype=np.int64), len(tris))
    return SectorTiling(
        repeats=repeats,
        anti_periodic=anti_periodic,
        span_deg=360.0 / repeats,
        nodes_mm=all_nodes[kept_array],
        triangles=tiled_tris,
        node_source=node_source,
        node_sign=node_sign,
        element_source=element_source,
        element_copy=element_copy,
    )


def tile_sector_field_plot(raw_plot: dict, sector: dict) -> dict:
    """A solver report's sector ``field_plot`` tiled to the full circle."""

    tiling = tile_sector_mesh(
        raw_plot["nodes_mm"],
        raw_plot["triangles"],
        repeats=int(sector["repeats"]),
        anti_periodic=bool(sector["anti_periodic"]),
    )
    regions = raw_plot["regions"]
    tiled = dict(raw_plot)
    tiled["nodes_mm"] = tiling.nodes_mm.tolist()
    tiled["triangles"] = tiling.triangles.tolist()
    tiled["regions"] = [regions[index] for index in tiling.element_source.tolist()]
    tiled["az_nodal"] = tiling.tile_nodal(raw_plot["az_nodal"]).tolist()
    tiled["total_span_deg"] = 360.0
    if "n_pole_pitches" in tiled:
        tiled["n_pole_pitches"] = int(tiled["n_pole_pitches"]) * tiling.repeats
    return tiled


# --------------------------------------------------------------------------
# Stored field frames: keep one sector, rebuild the full motor on read
# --------------------------------------------------------------------------

SECTOR_FOLD_KEY = "sector_fold"
_ELEMENT_KEYS = ("element_b_mag_t", "element_bx_t", "element_by_t")
_SEGMENT_KEYS = ("segments_mm", "segment_b_mag_t", "segment_bx_t", "segment_by_t")


def sector_tiling_info(raw_mesh_info: dict) -> dict | None:
    """What a tiled frame must remember to be stored as its sector again."""

    sector = raw_mesh_info.get("sector")
    if not isinstance(sector, dict):
        return None
    return {
        "repeats": int(sector["repeats"]),
        "anti_periodic": bool(sector["anti_periodic"]),
        "nodes": int(raw_mesh_info["num_nodes"]),
        "triangles": int(raw_mesh_info["num_triangles"]),
        "stator_start_deg": float(sector["stator_start_deg"]),
        "rotor_start_deg": float(sector["rotor_start_deg"]),
        "mid_gap_radius_mm": float(sector["mid_gap_radius_mm"]),
        "outer_rotor": raw_mesh_info.get("rotor_layout") == "outer",
    }


def _copy_of_points(points: np.ndarray, info: dict) -> np.ndarray:
    """Which sector copy each point lies in; the stator and rotor wedges start at different angles."""

    span = 2.0 * math.pi / info["repeats"]
    radius = np.hypot(points[:, 0], points[:, 1])
    in_outer_half = radius >= info["mid_gap_radius_mm"]
    on_stator_side = in_outer_half != bool(info["outer_rotor"])
    start = np.where(on_stator_side, math.radians(info["stator_start_deg"]), math.radians(info["rotor_start_deg"]))
    offset = (np.arctan2(points[:, 1], points[:, 0]) - start) % (2.0 * math.pi)
    return np.minimum((offset / span).astype(np.int64), info["repeats"] - 1)


def _fold_plot(plot: dict, info: dict) -> dict:
    """One plot (a frame or its no-load plot) cut back to what a sector must store."""

    nodes, triangles = info["nodes"], info["triangles"]
    # An anti-periodic motor's contours repeat every two sectors: copy 1 holds
    # the lines of the negated levels, which copy 0 does not.
    kept_copies = 2 if info["anti_periodic"] else 1
    folded = dict(plot)
    if isinstance(plot.get("nodes_mm"), list):
        folded["nodes_mm"] = plot["nodes_mm"][:nodes]
    if isinstance(plot.get("triangles"), list):
        folded["triangles"] = plot["triangles"][:triangles]
    if isinstance(plot.get("regions"), list):
        folded["regions"] = plot["regions"][:triangles]
    for key in _ELEMENT_KEYS:
        if isinstance(plot.get(key), list):
            folded[key] = plot[key][:triangles]
    contours = plot.get("contour_levels")
    if isinstance(contours, list):
        kept_levels = []
        for level in contours:
            segments = np.asarray(level.get("segments_mm") or [], dtype=float).reshape(-1, 4)
            if len(segments) == 0:
                kept_levels.append(dict(level))
                continue
            midpoints = 0.5 * (segments[:, 0:2] + segments[:, 2:4])
            keep = np.flatnonzero(_copy_of_points(midpoints, info) < kept_copies).tolist()
            kept_level = dict(level)
            for key in _SEGMENT_KEYS:
                values = level.get(key)
                if isinstance(values, list) and len(values) == len(segments):
                    kept_level[key] = [values[index] for index in keep]
            kept_levels.append(kept_level)
        folded["contour_levels"] = kept_levels
    return folded


def fold_sector_frame(frame: dict) -> dict:
    """A tiled sector frame as its one sector, for storage; any other frame unchanged.

    The stored frame is ``1 / repeats`` the size. ``unfold_sector_frame``
    rebuilds the full-motor frame from it.
    """

    mesh_info = frame.get("mesh_info")
    info = mesh_info.get("sector_tiling") if isinstance(mesh_info, dict) else None
    if not isinstance(info, dict) or not isinstance(frame.get("triangles"), list):
        return frame
    if len(frame["triangles"]) != info["triangles"] * info["repeats"]:
        return frame
    folded = _fold_plot(frame, info)
    noload = frame.get("noload_plot")
    if isinstance(noload, dict) and isinstance(noload.get("triangles"), list):
        noload_mesh_info = noload.get("mesh_info")
        noload_info = noload_mesh_info.get("sector_tiling") if isinstance(noload_mesh_info, dict) else None
        if not isinstance(noload_info, dict) or len(noload["triangles"]) != noload_info["triangles"] * noload_info["repeats"]:
            return frame
        folded["noload_plot"] = {**_fold_plot(noload, noload_info), SECTOR_FOLD_KEY: noload_info}
    folded[SECTOR_FOLD_KEY] = info
    return folded


def _unfold_plot(plot: dict, info: dict) -> dict:
    repeats, anti = info["repeats"], info["anti_periodic"]
    tiling = tile_sector_mesh(plot["nodes_mm"], plot["triangles"], repeats=repeats, anti_periodic=anti)
    source = tiling.element_source
    unfolded = {key: value for key, value in plot.items() if key != SECTOR_FOLD_KEY}
    unfolded["nodes_mm"] = tiling.nodes_mm.tolist()
    unfolded["triangles"] = tiling.triangles.tolist()
    regions = plot.get("regions")
    if isinstance(regions, list) and len(regions) == info["triangles"]:
        unfolded["regions"] = [regions[index] for index in source.tolist()]
    b_mag = plot.get("element_b_mag_t")
    if isinstance(b_mag, list) and len(b_mag) == info["triangles"]:
        unfolded["element_b_mag_t"] = tiling.tile_element_scalar(b_mag).tolist()
    bx, by = plot.get("element_bx_t"), plot.get("element_by_t")
    if isinstance(bx, list) and isinstance(by, list) and len(bx) == len(by) == info["triangles"]:
        tiled_bx, tiled_by = tiling.tile_element_vector(bx, by)
        unfolded["element_bx_t"] = tiled_bx.tolist()
        unfolded["element_by_t"] = tiled_by.tolist()

    contours = plot.get("contour_levels")
    if isinstance(contours, list):
        span = 2.0 * math.pi / repeats
        # Stored copies are 0 (and 1 when anti-periodic); the rest are these turned.
        stored_copies = 2 if anti else 1
        turns = [(copy % stored_copies, (copy - copy % stored_copies) * span) for copy in range(repeats)]
        unfolded_levels = []
        for level in contours:
            segments = np.asarray(level.get("segments_mm") or [], dtype=float).reshape(-1, 4)
            if len(segments) == 0:
                unfolded_levels.append(dict(level))
                continue
            stored_copy = _copy_of_points(0.5 * (segments[:, 0:2] + segments[:, 2:4]), info)
            vectors = {}
            for key in ("segment_bx_t", "segment_by_t", "segment_b_mag_t"):
                values = level.get(key)
                vectors[key] = (
                    np.asarray(values, dtype=float) if isinstance(values, list) and len(values) == len(segments) else None
                )
            parts: dict[str, list[np.ndarray]] = {key: [] for key in _SEGMENT_KEYS}
            for from_copy, angle in turns:
                index = np.flatnonzero(stored_copy == from_copy)
                if len(index) == 0:
                    continue
                cos_a, sin_a = math.cos(angle), math.sin(angle)
                chosen = segments[index]
                turned = np.empty_like(chosen)
                turned[:, 0] = chosen[:, 0] * cos_a - chosen[:, 1] * sin_a
                turned[:, 1] = chosen[:, 0] * sin_a + chosen[:, 1] * cos_a
                turned[:, 2] = chosen[:, 2] * cos_a - chosen[:, 3] * sin_a
                turned[:, 3] = chosen[:, 2] * sin_a + chosen[:, 3] * cos_a
                parts["segments_mm"].append(turned)
                if vectors["segment_b_mag_t"] is not None:
                    parts["segment_b_mag_t"].append(vectors["segment_b_mag_t"][index])
                if vectors["segment_bx_t"] is not None and vectors["segment_by_t"] is not None:
                    sx, sy = vectors["segment_bx_t"][index], vectors["segment_by_t"][index]
                    parts["segment_bx_t"].append(sx * cos_a - sy * sin_a)
                    parts["segment_by_t"].append(sx * sin_a + sy * cos_a)
            unfolded_level = dict(level)
            for key in _SEGMENT_KEYS:
                if parts[key]:
                    unfolded_level[key] = np.concatenate(parts[key]).tolist()
            unfolded_levels.append(unfolded_level)
        unfolded["contour_levels"] = unfolded_levels
    return unfolded


def unfold_sector_frame(frame: dict) -> dict:
    """The full-motor frame a folded sector frame stands for; any other frame unchanged."""

    info = frame.get(SECTOR_FOLD_KEY)
    if not isinstance(info, dict):
        return frame
    unfolded = _unfold_plot(frame, info)
    noload = frame.get("noload_plot")
    if isinstance(noload, dict) and isinstance(noload.get(SECTOR_FOLD_KEY), dict):
        unfolded["noload_plot"] = _unfold_plot(noload, noload[SECTOR_FOLD_KEY])
    return unfolded
