"""Lesson 6 meshes the rotor only from 0 to 90 degrees and mirrors the rest."""

from __future__ import annotations

from typing import Any

import pytest

from backend import tutorial_fields


def _signed_area(nodes: list[list[float]], triangle: list[int]) -> float:
    (ax, ay), (bx, by), (cx, cy) = (nodes[index][:2] for index in triangle)
    return 0.5 * ((bx - ax) * (cy - ay) - (cx - ax) * (by - ay))


def test_mirrored_mesh_reflects_x_and_keeps_triangles_anticlockwise() -> None:
    mesh = {
        "nodes_mm": [[0.0, 0.0], [2.0, 0.0], [0.0, 1.0], [2.0, 1.0]],
        "triangles": [[0, 1, 2], [1, 3, 2]],
        "boundary_nodes": [0, 1, 2, 3],
        "source_detail": "test",
    }

    mirrored = tutorial_fields._mirror_mesh_left_right(mesh)

    assert mirrored["nodes_mm"] == [[-0.0, 0.0], [-2.0, 0.0], [-0.0, 1.0], [-2.0, 1.0]]
    assert all(_signed_area(mirrored["nodes_mm"], triangle) > 0 for triangle in mirrored["triangles"])
    assert mirrored["boundary_nodes"] == mesh["boundary_nodes"]
    # The cached source mesh is shared between requests and must stay as built.
    assert mesh["nodes_mm"][1] == [2.0, 0.0]
    assert mesh["triangles"][0] == [0, 1, 2]


@pytest.mark.parametrize(
    ("requested_deg", "built_deg", "mirrored"),
    [
        (0.0, 0.0, False),
        (60.0, 60.0, False),
        (90.0, 90.0, False),
        (120.0, 60.0, True),
        (165.0, 15.0, True),
        (180.0, 0.0, False),
        (200.0, 20.0, False),
        (300.0, 60.0, True),
    ],
)
def test_angles_fold_onto_the_first_quarter_turn(
    monkeypatch: pytest.MonkeyPatch, requested_deg: float, built_deg: float, mirrored: bool
) -> None:
    built: list[dict[str, Any]] = []

    def fake_build(**kwargs: Any) -> dict[str, Any]:
        built.append(kwargs)
        return {"nodes_mm": [[1.0, 0.0], [3.0, 0.0], [1.0, 1.0]], "triangles": [[0, 1, 2]], "boundary_nodes": [0]}

    monkeypatch.setattr(tutorial_fields, "_build_rotor_chase_gmsh_mesh", fake_build)

    mesh = tutorial_fields._rotor_chase_mesh(
        rotor_angle_deg=requested_deg, pole_gap_mm=8.0, source_kind="pm", mesh_density="normal"
    )

    assert built == [
        {"rotor_angle_deg": built_deg, "pole_gap_mm": 8.0, "source_kind": "pm", "mesh_density": "normal"}
    ]
    assert (mesh["nodes_mm"][1][0] < 0) is mirrored


def test_meshes_are_released_once_idle() -> None:
    calls: list[int] = []

    @tutorial_fields._cached_teaching_mesh
    def build(*, size: int) -> dict[str, Any]:
        calls.append(size)
        return {"size": size}

    first = build(size=3)
    assert build(size=3) is first
    assert calls == [3]

    tutorial_fields._release_teaching_meshes()

    assert build(size=3) is not first
    assert calls == [3, 3]
