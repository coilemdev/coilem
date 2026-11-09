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
