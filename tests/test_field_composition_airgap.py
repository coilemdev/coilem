"""Stator-only frames carry the air-gap profile the field viewer reads its poles from (#120)."""

from __future__ import annotations

import math

import numpy as np

from backend.field_composition import _airgap_profile, _slim_armature_frame


def _ring_frame(peak_deg: float, pole_pairs: int = 4, segments: int = 360) -> dict:
    """An air-gap ring (r 10-11 mm) whose radial field peaks at ``peak_deg`` once per pole pair."""

    nodes, triangles, regions, bx, by = [], [], [], [], []
    for index in range(segments):
        a0 = 2 * math.pi * index / segments
        a1 = 2 * math.pi * (index + 1) / segments
        base = len(nodes)
        nodes += [[10 * math.cos(a0), 10 * math.sin(a0)], [11 * math.cos(a0), 11 * math.sin(a0)],
                  [10 * math.cos(a1), 10 * math.sin(a1)], [11 * math.cos(a1), 11 * math.sin(a1)]]
        for triangle in ([base, base + 1, base + 2], [base + 1, base + 3, base + 2]):
            cx = sum(nodes[i][0] for i in triangle) / 3
            cy = sum(nodes[i][1] for i in triangle) / 3
            theta = math.atan2(cy, cx)
            br = math.cos(pole_pairs * (theta - math.radians(peak_deg)))
            triangles.append(triangle)
            regions.append("airgap")
            bx.append(br * math.cos(theta))
            by.append(br * math.sin(theta))
    # A stator element the profile must ignore.
    nodes += [[20.0, 0.0], [21.0, 0.0], [20.0, 1.0]]
    triangles.append([len(nodes) - 3, len(nodes) - 2, len(nodes) - 1])
    regions.append("stator_tooth")
    bx.append(5.0)
    by.append(5.0)
    return {
        "angle_deg": 0.0,
        "nodes_mm": nodes,
        "triangles": triangles,
        "regions": regions,
        "element_bx_t": bx,
        "element_by_t": by,
        "contour_levels": [{"level": 0.0, "segments_mm": []}],
        "total_span_deg": 360.0,
    }


def _fitted_peak_deg(profile: dict, pole_pairs: int = 4) -> float:
    angles = np.radians([b["mech_angle_deg"] for b in profile["bins"]])
    br = np.array([b["br_t"] for b in profile["bins"]])
    coef = np.sum(br * np.exp(-1j * pole_pairs * angles))
    return (-math.degrees(np.angle(coef)) / pole_pairs) % (360 / pole_pairs)


def test_profile_finds_the_working_harmonic_peak() -> None:
    profile = _airgap_profile(_ring_frame(peak_deg=10.0))
    assert profile is not None
    assert profile["span_deg"] == 360.0 and profile["bin_count"] == 120
    assert all(abs(b["mech_angle_deg"] - 1.5 - 3 * i) < 1e-9 for i, b in enumerate(profile["bins"]))
    assert abs(_fitted_peak_deg(profile) - 10.0) < 0.5


def test_slim_stator_frame_keeps_the_profile_and_drops_the_mesh() -> None:
    slim = _slim_armature_frame(_ring_frame(peak_deg=-20.0))
    assert "nodes_mm" not in slim and "element_bx_t" not in slim
    assert abs(_fitted_peak_deg(slim["airgap_brbt"]) - (-20.0 % 90)) < 0.5


def test_frames_without_air_gap_elements_get_no_profile() -> None:
    frame = _ring_frame(peak_deg=0.0)
    frame["regions"] = ["stator_tooth"] * len(frame["regions"])
    assert _airgap_profile(frame) is None
    assert "airgap_brbt" not in _slim_armature_frame(frame)
