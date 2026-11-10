"""Sector models (#222): one repeating sector must give the full-circle answer."""
from __future__ import annotations

import copy
import json
import math
from collections import Counter
from pathlib import Path

import pytest

from backend import sector_geometry as sg
from backend.elmer.adapter import ElmerUnsupportedError
from backend.geometry_drawer import compute_geometry
from backend.geometry_ir import build_geometry_ir
from backend.gmsh_mesh_rotation import derive_congruent_solve_report
from backend.gmsh_solver import _outer_boundary_nodes, _rotate_magnets_in_place, run_gmsh_mesh_preview
from backend.magneto2d_adapter import build_magneto2d_mesh_signature, run_magneto2d_report
from backend.models import MotorConfig
from backend.qualification import classify_qualification
from backend.sector_tiling import tile_sector_mesh
from backend.topology_provenance import build_topology_provenance

FIXTURES = Path("benchmarks")
SPM_8P12S = "abcd-v1.9/fixtures/spm_8p12s_concentrated__baseline__native.json"
SPM_4P12S = "abcd-v1.9/fixtures/spm_4p12s_simple__baseline__native.json"
SPM_8P48S = "abcd-v1.7/fixtures/spm_8p48s_distributed_femm_validation__cogging.json"
IPM_24S16P = "abcd-v1.7/fixtures/ipm_flat_24s16p_industrial_contract__cogging.json"
OUTER_14P12S = "abcd-v1.8/fixtures/spm_outer_14p12s_drone__angle30.json"
OUTER_12P9S = "abcd-v1.8/fixtures/spm_outer_12p9s_micro__baseline.json"


def _raw(fixture: str, **solve_params) -> dict:
    raw = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    raw["solve_params"].update(solve_params)
    return raw


def _config(fixture: str, **solve_params) -> MotorConfig:
    return MotorConfig(**_raw(fixture, **solve_params))


def _ir(fixture: str, rotor_angle_deg: float = 0.0):
    config = _config(fixture)
    geom = compute_geometry(config)
    _rotate_magnets_in_place(geom, math.radians(rotor_angle_deg))
    return build_geometry_ir(config, geom=geom, rotor_angle_deg=rotor_angle_deg)


def test_full_circle_is_the_default_and_other_values_are_rejected() -> None:
    assert _config(SPM_8P12S).solve_params.symmetry == "full"
    with pytest.raises(ValueError):
        _config(SPM_8P12S, symmetry="half")


def test_candidates_come_from_slot_and_pole_counts_smallest_sector_first() -> None:
    def candidates(slots: int, poles: int) -> list[tuple[int, bool, int, int]]:
        return [
            (c.repeats, c.anti_periodic, c.n_pole_pitches, c.slots_per_sector)
            for c in sg.candidate_symmetries(slots, poles)
        ]

    assert candidates(12, 4) == [(4, True, 1, 3), (2, False, 2, 6)]
    assert candidates(12, 8)[0] == (4, False, 2, 3)
    assert candidates(48, 8)[0] == (8, True, 1, 6)
    assert candidates(12, 14) == [(2, True, 7, 6)]
    assert candidates(9, 12)[0] == (3, False, 4, 3)
    # 9 slots and 8 poles share no repeat: the full circle is the only model.
    assert candidates(9, 8) == []


@pytest.mark.parametrize(
    ("fixture", "repeats", "anti_periodic", "pole_pitches"),
    [
        (SPM_4P12S, 4, True, 1),
        # A single-layer winding on alternate teeth repeats every six slots,
        # not every three as the slot and pole counts alone would allow.
        (SPM_8P12S, 2, False, 4),
        (SPM_8P48S, 8, True, 1),
        (IPM_24S16P, 4, False, 4),
        (OUTER_14P12S, 2, True, 7),
        (OUTER_12P9S, 3, False, 4),
    ],
)
def test_the_sector_is_the_smallest_one_geometry_and_winding_both_repeat_over(
    fixture, repeats, anti_periodic, pole_pitches
) -> None:
    symmetry = sg.detect_sector_symmetry(_ir(fixture))
    assert symmetry is not None
    assert (symmetry.repeats, symmetry.anti_periodic, symmetry.n_pole_pitches) == (repeats, anti_periodic, pole_pitches)


def test_a_winding_that_does_not_repeat_keeps_the_full_circle() -> None:
    ir = _ir(SPM_8P12S)
    regions = list(ir.regions)
    index = next(i for i, region in enumerate(regions) if region.kind == "SlotWinding")
    phase = regions[index].source_group.split(":")[1]
    other = "A" if phase != "A" else "B"
    regions[index] = sg.replace(
        regions[index], source_group=regions[index].source_group.replace(f":{phase}:", f":{other}:")
    )
    assert sg.detect_sector_symmetry(sg.replace(ir, regions=tuple(regions))) is None


@pytest.mark.parametrize("fixture", [SPM_4P12S, SPM_8P12S, SPM_8P48S, IPM_24S16P, OUTER_14P12S, OUTER_12P9S])
@pytest.mark.parametrize("rotor_angle_deg", [0.0, 3.7, 29.9999, 97.3])
def test_the_sector_holds_one_repeat_of_every_region_and_cuts_no_magnet_or_slot(fixture, rotor_angle_deg) -> None:
    ir = _ir(fixture, rotor_angle_deg)
    symmetry = sg.detect_sector_symmetry(ir)
    sector = sg.build_sector_ir(ir, symmetry)

    full_area = Counter()
    sector_area = Counter()
    for region in ir.regions:
        full_area[region.kind] += region.area_mm2
    for region in sector.ir.regions:
        sector_area[region.kind] += region.area_mm2
    for kind, area in full_area.items():
        assert sector_area[kind] * symmetry.repeats == pytest.approx(area, rel=1e-9)

    whole = {region.region_id: region.area_mm2 for region in ir.regions}
    for region in sector.ir.regions:
        if region.kind in {"Magnet", "SlotWinding"}:
            assert len(sector.pieces_by_region[region.region_id]) == 1
            assert region.area_mm2 == pytest.approx(whole[region.region_id], rel=1e-9)
    assert sum(region.kind == "SlotWinding" for region in sector.ir.regions) * symmetry.repeats == sum(
        region.kind == "SlotWinding" for region in ir.regions
    )

    # Every tied curve's partner is the curve turned by exactly one sector.
    for pair in sector.curve_pairs:
        cos_a, sin_a = math.cos(pair.rotation_rad), math.sin(pair.rotation_rad)
        for (mx, my), (sx, sy) in ((pair.master_start, pair.slave_start), (pair.master_end, pair.slave_end)):
            assert (mx * cos_a - my * sin_a, mx * sin_a + my * cos_a) == pytest.approx((sx, sy), abs=1e-9)
        assert abs(abs(pair.rotation_rad) - symmetry.span_rad) < 1e-12


def test_full_keeps_the_mesh_request_unchanged_and_auto_gets_its_own_signature() -> None:
    default, full, auto = _config(SPM_8P12S), _config(SPM_8P12S, symmetry="full"), _config(SPM_8P12S, symmetry="auto")
    assert "symmetry" not in build_topology_provenance(full)["mesh_policy"]
    assert build_topology_provenance(full) == build_topology_provenance(default)
    assert build_topology_provenance(auto)["mesh_policy"]["symmetry"] == "auto"
    assert build_magneto2d_mesh_signature(full) != build_magneto2d_mesh_signature(auto)


def test_a_sector_solve_is_experimental_and_elmer_refuses_it(monkeypatch) -> None:
    monkeypatch.setattr("backend.qualification.evidence_matches_runtime", lambda: True)
    qualified = MotorConfig.model_validate_json(
        Path("benchmarks/main-20261009-bad71d9/fixtures/spm_8p12s_concentrated__baseline.json").read_text(encoding="utf-8")
    )
    assert classify_qualification(qualified)["status"] == "qualified"
    sector = qualified.model_copy(update={"solve_params": qualified.solve_params.model_copy(update={"symmetry": "auto"})})
    result = classify_qualification(sector)
    assert (result["status"], result["reason"]) == ("experimental", "Sector solve: the benchmark measured full-circle solves.")

    from types import SimpleNamespace

    from backend.elmer.adapter import ElmerSolver

    elmer = ElmerSolver.__new__(ElmerSolver)
    elmer.capabilities = SimpleNamespace(require_available=lambda: None)
    elmer_request = sector.model_copy(
        update={
            "solve_params": sector.solve_params.model_copy(
                update={"nonlinear_solver": "picard", "rotor_rotation_model": "remesh_per_step", "torque_method": "arkkio"}
            )
        }
    )
    with pytest.raises(ElmerUnsupportedError, match="symmetry='auto'"):
        elmer._validate_config(elmer_request, None)


def _mesh(fixture: str, symmetry: str, rotor_angle_deg: float = 3.7, **solve_params) -> tuple[MotorConfig, dict]:
    config = _config(fixture, symmetry=symmetry, mesh_density="coarse", nonlinear_solver="newton", **solve_params)
    return config, run_gmsh_mesh_preview(config, rotor_angle_deg=rotor_angle_deg)["solve_mesh_artifact"]


@pytest.mark.parametrize("fixture", [SPM_4P12S, SPM_8P12S, OUTER_14P12S])
def test_sector_mesh_is_one_repeat_with_matched_edge_nodes(fixture) -> None:
    _, full = _mesh(fixture, "full")
    _, sector = _mesh(fixture, "auto")
    info = sector["mesh"]["info"]
    repeats = info["sector"]["repeats"]
    assert full["mesh"]["info"]["total_span_deg"] == 360.0 and "sector" not in full["mesh"]["info"]
    assert full["mesh"]["sector_edge_pairs"] == []
    assert info["total_span_deg"] == pytest.approx(360.0 / repeats)
    assert info["n_pole_pitches"] * repeats == full["mesh"]["info"]["n_pole_pitches"]
    assert len(sector["mesh"]["triangles"]) * repeats == pytest.approx(len(full["mesh"]["triangles"]), rel=0.12)
    assert sector["physics_contract"]["boundary_policy"]["sector_edges"] == (
        "anti_periodic" if info["sector"]["anti_periodic"] else "periodic"
    )

    nodes = sector["mesh"]["nodes"]
    pairs = sector["mesh"]["sector_edge_pairs"]
    span = math.radians(info["total_span_deg"])
    seen: set[int] = set()
    for master, slave in pairs:
        assert master not in seen and slave not in seen
        seen.update((master, slave))
        if master == slave:
            # Only the motor axis lies on both cut edges.
            assert math.hypot(*nodes[master]) < 1e-9
            continue
        (mx, my), (sx, sy) = nodes[master], nodes[slave]
        assert math.hypot(mx, my) == pytest.approx(math.hypot(sx, sy), abs=1e-9)
        turn = (math.atan2(sy, sx) - math.atan2(my, mx)) % (2 * math.pi)
        assert min(abs(turn - span), abs(turn - (2 * math.pi - span))) < 1e-9
    assert len(pairs) > 20


def test_a_design_that_cannot_be_cut_falls_back_to_the_full_circle(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise sg.SectorUnsupportedError("the rotor cut passes through magnet_0")

    monkeypatch.setattr("backend.gmsh_solver.build_sector_ir", refuse)
    _, artifact = _mesh(SPM_8P12S, "auto")
    info = artifact["mesh"]["info"]
    assert info["total_span_deg"] == 360.0 and "sector" not in info
    assert info["sector_fallback_reason"] == "the rotor cut passes through magnet_0"
    assert artifact["mesh"]["sector_edge_pairs"] == []


def _tiled_full_circle_artifact(artifact: dict, config: MotorConfig) -> dict:
    """The sector mesh copied around the circle as an ordinary full-circle solve mesh."""

    info = artifact["mesh"]["info"]
    sector = info["sector"]
    repeats, anti = sector["repeats"], sector["anti_periodic"]
    span = 360.0 / repeats
    tiling = tile_sector_mesh(artifact["mesh"]["nodes"], artifact["mesh"]["triangles"], repeats=repeats, anti_periodic=anti)
    source, copies = tiling.element_source.tolist(), tiling.element_copy.tolist()

    def magnetization(value, copy_index):
        return None if value is None else (value + copy_index * span + (180.0 if anti and copy_index % 2 else 0.0)) % 360.0

    def current(value, copy_index):
        return None if value is None else value * (-1.0 if anti and copy_index % 2 else 1.0)

    out = copy.deepcopy(artifact)
    mesh = out["mesh"]
    mesh["nodes"] = tiling.nodes_mm.tolist()
    mesh["triangles"] = tiling.triangles.tolist()
    mesh["regions"] = [artifact["mesh"]["regions"][i] for i in source]
    mesh["sector_edge_pairs"] = []
    out["element_region_ids"] = [
        f"copy{c}__{artifact['element_region_ids'][i]}" if c else artifact["element_region_ids"][i]
        for i, c in zip(source, copies)
    ]
    out["element_magnetization"] = [magnetization(artifact["element_magnetization"][i], c) for i, c in zip(source, copies)]
    out["element_current_density_a_per_m2"] = [
        current(artifact["element_current_density_a_per_m2"][i], c) for i, c in zip(source, copies)
    ]
    regions = []
    for copy_index in range(repeats):
        for region in artifact["physics_contract"]["regions"]:
            entry = copy.deepcopy(region)
            if copy_index:
                # A prefix: the solver reads a coil side's layer from the end of its id.
                entry["id"] = f"copy{copy_index}__{region['id']}"
            if "magnetization_angle_deg" in entry:
                entry["magnetization_angle_deg"] = magnetization(entry["magnetization_angle_deg"], copy_index)
            if "current_density_a_per_m2" in entry:
                entry["current_density_a_per_m2"] = current(entry["current_density_a_per_m2"], copy_index)
            regions.append(entry)
    contract = out["physics_contract"]
    contract["regions"] = regions
    contract["boundary_policy"]["sector_edges"] = "none"
    for key in ("element_region_sources", "element_current_density_sources", "element_magnetization_sources", "element_material_sources"):
        contract["provenance"][key] = [artifact["physics_contract"]["provenance"][key][i] for i in source]
    mesh["info"] = {
        key: value for key, value in info.items() if key not in {"sector", "gmsh_physical_names"}
    } | {
        "n_pole_pitches": config.rotor.pole_count,
        "total_span_deg": 360.0,
        "num_nodes": len(mesh["nodes"]),
        "num_triangles": len(mesh["triangles"]),
    }
    if info.get("outer_rotor"):
        boundary = set(artifact["mesh"]["boundary_nodes"])
        mesh["boundary_nodes"] = [i for i, s in enumerate(tiling.node_source.tolist()) if s in boundary]
    else:
        mesh["boundary_nodes"] = _outer_boundary_nodes(mesh["nodes"], config.stator.OD_mm / 2.0)
    return out


_COMPARED = (
    "torque_nm",
    "torque_arkkio_nm",
    "torque_weighted_stress_nm",
    "flux_linkage_a_wb",
    "flux_linkage_b_wb",
    "flux_linkage_c_wb",
    "peak_b_tooth_point_t",
    "peak_b_yoke_point_t",
)


@pytest.mark.parametrize(
    "fixture",
    [
        SPM_4P12S,  # quarter, anti-periodic, one pole: the wedge reaches the motor axis
        SPM_8P12S,  # half, periodic
        SPM_8P48S,  # eighth, anti-periodic, distributed winding
        OUTER_14P12S,  # half, anti-periodic, outer rotor
        OUTER_12P9S,  # third, periodic, outer rotor
    ],
)
def test_a_sector_solve_equals_the_full_circle_solve_of_the_same_mesh(fixture) -> None:
    """The sector mesh, copied around the circle and solved with no edge ties,
    is an ordinary full-circle problem on the very same elements. The sector
    solve must reproduce it: that checks the edge ties, the offset stator and
    rotor wedges, and every sector-aware torque and flux-linkage step at once,
    with no mesh difference to hide behind.
    """

    config, sector = _mesh(fixture, "auto")
    sector_report = run_magneto2d_report(config, sweep=False, rotor_angle_deg=3.7, solve_mesh_artifact=sector)
    tiled_report = run_magneto2d_report(
        config,
        sweep=False,
        rotor_angle_deg=3.7,
        solve_mesh_artifact=_tiled_full_circle_artifact(sector, config),
    )
    a, b = sector_report["results"], tiled_report["results"]
    scale = max(abs(b["flux_linkage_a_wb"]), abs(b["flux_linkage_b_wb"]), abs(b["flux_linkage_c_wb"]))
    for key in _COMPARED:
        if a[key] is None or b[key] is None:
            assert a[key] is None and b[key] is None, key
            continue
        tolerance = 1e-6 * (scale if key.startswith("flux") else max(abs(b["torque_nm"]), abs(b[key]), 1e-9))
        assert a[key] == pytest.approx(b[key], abs=tolerance), key
    assert a["energy_functional"]["coenergy_j"] == pytest.approx(b["energy_functional"]["coenergy_j"], rel=1e-8)
    # The contour torque that grades benchmarks is available on a sector.
    assert a["torque_contour_selection"] == b["torque_contour_selection"] == "az"


@pytest.mark.parametrize("fixture", [SPM_4P12S, SPM_8P12S, OUTER_14P12S])
@pytest.mark.parametrize("current_a", [None, 0.0])
def test_a_sector_turned_by_slot_pitches_solves_like_a_fresh_mesh_and_reuses_its_solution(fixture, current_a) -> None:
    from backend.solver import _rotate_gmsh_artifact_for_config

    extra = {} if current_a is None else {"current_amplitude_A": current_a}
    config, base = _mesh(fixture, "auto", rotor_angle_deg=3.7, **extra)
    slot_count = config.stator.slot_count
    pole_pairs = config.rotor.pole_count // 2
    base_report = run_magneto2d_report(config, sweep=False, rotor_angle_deg=3.7, solve_mesh_artifact=base)

    for n_slots in (1, 5):
        turn = n_slots * 360.0 / slot_count
        target = 3.7 + turn
        derived = _rotate_gmsh_artifact_for_config(base, config, target)
        assert derived["mesh"]["info"]["sector"]["stator_start_deg"] == pytest.approx(
            base["mesh"]["info"]["sector"]["stator_start_deg"] + turn
        )
        solved = run_magneto2d_report(config, sweep=False, rotor_angle_deg=target, solve_mesh_artifact=derived)["results"]

        # The turned wedge holds other slots than the base wedge; a freshly
        # meshed sector at the target angle agrees with it to mesh noise.
        _, fresh = _mesh(fixture, "auto", rotor_angle_deg=target, **extra)
        fresh_results = run_magneto2d_report(config, sweep=False, rotor_angle_deg=target, solve_mesh_artifact=fresh)["results"]
        scale = max(abs(fresh_results[f"flux_linkage_{p}_wb"]) for p in "abc")
        for phase in "abc":
            key = f"flux_linkage_{phase}_wb"
            assert solved[key] == pytest.approx(fresh_results[key], abs=0.02 * scale), key

        if current_a != 0.0:
            continue
        # With no current the turned mesh's solution is the base solution turned
        # with it, so relabelling the base report must reproduce the solve.
        reused = derive_congruent_solve_report(
            base_report,
            slot_count=slot_count,
            n_slot_pitches=n_slots,
            rotation_delta_deg=turn,
            elec_delta_deg=turn * pole_pairs,
        )["results"]
        for phase in "abc":
            key = f"flux_linkage_{phase}_wb"
            assert reused[key] == pytest.approx(solved[key], abs=1e-6 * scale), key
        assert reused["torque_nm"] == base_report["results"]["torque_nm"]
        assert sorted(row["slot_index_global"] for row in reused["slot_flux_linkage_contributions"]) == sorted(
            row["slot_index_global"] for row in solved["slot_flux_linkage_contributions"]
        )


def test_tiling_merges_shared_nodes_and_signs_alternate_copies() -> None:
    _, sector = _mesh(SPM_4P12S, "auto")
    mesh = sector["mesh"]
    tiling = tile_sector_mesh(mesh["nodes"], mesh["triangles"], repeats=4, anti_periodic=True)
    assert len(tiling.triangles) == 4 * len(mesh["triangles"])
    # Shared edge nodes are counted once: fewer nodes than four separate copies.
    assert len(mesh["nodes"]) * 4 - 4 * len(mesh["sector_edge_pairs"]) <= len(tiling.nodes_mm) < len(mesh["nodes"]) * 4
    values = tiling.tile_nodal([1.0] * len(mesh["nodes"]))
    assert set(values.tolist()) == {1.0, -1.0}
    bx, by = tiling.tile_element_vector([1.0] * len(mesh["triangles"]), [0.0] * len(mesh["triangles"]))
    count = len(mesh["triangles"])
    # Copy 1 is a quarter turn on and negated: (1, 0) -> -(0, 1).
    assert (bx[count], by[count]) == pytest.approx((0.0, -1.0), abs=1e-12)
    # The tiled mesh closes the circle: every edge is shared by two triangles
    # except those on the outer boundary and the shaft-free axis.
    edges = Counter()
    for a, b, c in tiling.triangles.tolist():
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(min(u, v), max(u, v))] += 1
    outer_radius = max(math.hypot(x, y) for x, y in tiling.nodes_mm.tolist())
    for (u, v), uses in edges.items():
        if uses == 1:
            assert math.hypot(*tiling.nodes_mm[u]) == pytest.approx(outer_radius, rel=1e-6)
            assert math.hypot(*tiling.nodes_mm[v]) == pytest.approx(outer_radius, rel=1e-6)


@pytest.mark.parametrize("fixture", [SPM_4P12S, SPM_8P12S, OUTER_14P12S])
def test_a_sector_frame_is_stored_as_one_sector_and_read_back_as_the_full_motor(fixture, tmp_path, monkeypatch) -> None:
    import numpy as np

    from backend import field_artifacts
    from backend.sector_tiling import SECTOR_FOLD_KEY, fold_sector_frame, unfold_sector_frame
    from backend.solver._helpers import _field_line_frame_from_report

    config, sector = _mesh(fixture, "auto")
    report = run_magneto2d_report(config, sweep=False, rotor_angle_deg=3.7, solve_mesh_artifact=sector)
    noload_config = config.model_copy(update={"solve_params": config.solve_params.model_copy(update={"current_amplitude_A": 0.0})})
    noload_report = run_magneto2d_report(noload_config, sweep=False, rotor_angle_deg=3.7, solve_mesh_artifact=sector)
    frame = _field_line_frame_from_report(report, 14.8, noload_report)
    repeats = sector["mesh"]["info"]["sector"]["repeats"]
    assert frame["total_span_deg"] == 360.0
    assert len(frame["triangles"]) == repeats * len(sector["mesh"]["triangles"])

    folded = fold_sector_frame(frame)
    assert len(folded["triangles"]) == len(sector["mesh"]["triangles"])
    assert len(folded["nodes_mm"]) == len(sector["mesh"]["nodes"])
    assert len(folded["noload_plot"]["triangles"]) == len(sector["mesh"]["triangles"])
    assert SECTOR_FOLD_KEY in folded and SECTOR_FOLD_KEY in folded["noload_plot"]

    def assert_same_plot(restored: dict, original: dict) -> None:
        assert restored["triangles"] == original["triangles"]
        assert restored["regions"] == original["regions"]
        np.testing.assert_allclose(restored["nodes_mm"], original["nodes_mm"], atol=1e-9)
        scale = max(original["element_b_mag_t"])
        for key in ("element_b_mag_t", "element_bx_t", "element_by_t"):
            np.testing.assert_allclose(restored[key], original[key], atol=1e-9 * scale)
        assert [level["level"] for level in restored["contour_levels"]] == [
            level["level"] for level in original["contour_levels"]
        ]
        for restored_level, level in zip(restored["contour_levels"], original["contour_levels"]):
            # The same line segments, in another order.
            assert len(restored_level["segments_mm"]) == len(level["segments_mm"])
            assert len(restored_level["segment_bx_t"]) == len(level["segment_bx_t"])
            key = lambda segment: tuple(round(value, 6) for value in segment)  # noqa: E731
            assert sorted(map(key, restored_level["segments_mm"])) == sorted(map(key, level["segments_mm"]))

    unfolded = unfold_sector_frame(folded)
    assert SECTOR_FOLD_KEY not in unfolded and SECTOR_FOLD_KEY not in unfolded["noload_plot"]
    assert_same_plot(unfolded, frame)
    assert_same_plot(unfolded["noload_plot"], frame["noload_plot"])

    # Through the stored artifact: the file holds one sector, the reader returns the motor.
    monkeypatch.setattr(field_artifacts, "solve_cache_root", lambda: tmp_path)
    ref = field_artifacts.write_field_line_frame_artifact(frame, tmp_path / "run", pos_idx=0, elec_angle_deg=14.8)
    assert ref is not None
    stored = next((tmp_path / "run" / "field_line_frames").glob("*.json.gz"))
    import gzip

    raw = json.loads(gzip.open(stored, "rt", encoding="utf-8").read())["field_line_frame"]
    assert len(raw["triangles"]) == len(sector["mesh"]["triangles"])
    for path in (stored, field_artifacts.compact_field_frame_path(stored)):
        read_back = field_artifacts.read_field_line_frame_artifact(path)["field_line_frame"]
        assert len(read_back["triangles"]) == len(frame["triangles"])
        np.testing.assert_allclose(read_back["element_bx_t"], frame["element_bx_t"], atol=2e-6 * max(frame["element_b_mag_t"]))
        assert len(read_back["noload_plot"]["triangles"]) == len(frame["triangles"])


def test_a_full_circle_frame_is_stored_as_it_is() -> None:
    from backend.sector_tiling import fold_sector_frame, unfold_sector_frame
    from backend.solver._helpers import _field_line_frame_from_report

    config, full = _mesh(SPM_8P12S, "full")
    report = run_magneto2d_report(config, sweep=False, rotor_angle_deg=3.7, solve_mesh_artifact=full)
    frame = _field_line_frame_from_report(report, 14.8)
    assert fold_sector_frame(frame) is frame
    assert unfold_sector_frame(frame) is frame
    assert "sector_tiling" not in frame["mesh_info"]


def test_the_mesh_preview_draws_a_sector_as_the_whole_motor_and_keeps_the_solved_count() -> None:
    from backend.magneto2d_adapter import run_magneto2d_mesh_preview

    sector_config = _config(SPM_4P12S, symmetry="auto", mesh_density="coarse")
    preview = run_magneto2d_mesh_preview(sector_config, rotor_angle_deg=0.0)
    solved = preview["mesh_info"]["num_triangles"]
    assert preview["mesh_info"]["sector"]["repeats"] == 4
    assert len(preview["triangles"]) == 4 * solved
    assert len(preview["regions"]) == len(preview["element_region_ids"]) == len(preview["triangles"])
    assert preview["total_span_deg"] == 360.0
    # The drawn mesh goes all the way round.
    angles = sorted(math.degrees(math.atan2(y, x)) % 360.0 for x, y in preview["nodes_mm"] if math.hypot(x, y) > 1.0)
    assert max(b - a for a, b in zip(angles, angles[1:])) < 5.0
    assert preview["solve_mesh_key"]

    full = run_magneto2d_mesh_preview(_config(SPM_4P12S, mesh_density="coarse"), rotor_angle_deg=0.0)
    assert len(full["triangles"]) == full["mesh_info"]["num_triangles"]
    assert len(preview["triangles"]) == pytest.approx(len(full["triangles"]), rel=0.12)
