"""The loadable published reference keeps exact curves, sources and ampere-turns."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from backend.excitation import resolve_phase_current_sample
from backend.geometry_drawer import compute_geometry
from backend.geometry_ir import build_geometry_ir
from backend.gmsh_solver import GMSH_AVAILABLE, _rotate_magnets_in_place, run_gmsh_mesh_preview
from backend.models import MotorConfig
from backend.public_policy import PublicConfigError, parse_public_motor_config
from backend.reference_models import prius
from backend.solver import _clockwise_excitation_config, _rebake_gmsh_artifact_for_config
from backend.topology_provenance import build_mesh_signature_payload

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.pr


def config():
    return MotorConfig.model_validate(copy.deepcopy(prius.fixture()))


def test_bundled_design_and_canonical_reference_are_the_same_model():
    ui = json.loads((ROOT / "frontend/src/public/examples/prius-2004-loaded-torque-v1.coilem").read_text(encoding="utf-8"))
    assert MotorConfig.model_validate(ui) == config()
    assert config().solve_options.back_emf is True
    assert prius.source()["source_machine_sha256"] == "a8922c4f712c38696e6dcf7e800ad5615a0b22dd45a802574f749a59945c8036"
    assert len(prius.source()["surfaces"]) == 90
    assert prius.MAGNET_BR_FACTOR * 1.24 == pytest.approx(1.1904)


@pytest.mark.parametrize("section,field,value", [
    ("stator", "tooth_width_mm", 7.1), ("rotor", "holem50_w4_mm", 19),
    ("winding", "turns_per_coil", 10), ("winding", "coil_span", 5),
    ("materials", "magnet_grade", "N42"), ("solve_params", "magnet_temperature_C", 20),
])
def test_reference_cannot_silently_change_its_model(section, field, value):
    payload = copy.deepcopy(prius.fixture())
    payload[section][field] = value
    with pytest.raises(ValueError):
        MotorConfig.model_validate(payload)


def test_operating_point_is_editable_and_only_exact_reference_bypasses_generic_opt_in(monkeypatch):
    payload = copy.deepcopy(prius.fixture())
    payload["solve_params"].update(current_amplitude_A=100, current_angle_deg=60, rated_speed_rpm=3000)
    monkeypatch.delenv("COILEM_EXPERIMENTAL_ROTORS", raising=False)
    assert parse_public_motor_config(payload).reference_case == "prius-2004-loaded-torque-v1"
    monkeypatch.setenv("COILEM_EXPERIMENTAL_ROTORS", "1")
    assert parse_public_motor_config(payload).solve_params.current_angle_deg == 60
    ordinary = json.loads((ROOT / "tests/fixtures/spm_4p12s_simple.json").read_text())
    ordinary["solve_params"]["magnet_temperature_C"] = 150  # beyond N42's linear range
    with pytest.raises(PublicConfigError, match="temperature"):
        parse_public_motor_config(ordinary)
    ordinary["solve_params"]["magnet_temperature_C"] = None
    ordinary["stator"]["slot_opening_mm"] = 1.93
    with pytest.raises(PublicConfigError, match="slot_opening"):
        parse_public_motor_config(ordinary)
    payload["topology"] = "SPM"
    with pytest.raises(PublicConfigError, match="IPM topology"):
        parse_public_motor_config(payload)


def test_exact_curves_tile_the_published_annulus_without_a_shaft_region():
    ir = build_geometry_ir(config())
    report = ir.validation_report()
    assert report.issues == ()
    assert Counter(r.kind for r in ir.regions) == {
        "StatorYoke": 1, "Airgap": 1, "RotorCore": 1, "SlotWinding": 48, "MagnetPocketAir": 24, "Magnet": 16,
    }
    assert report.magnet_area_mm2 == pytest.approx(16 * 18.9 * 6.5, abs=1e-8)
    assert report.slot_winding_area_mm2 == pytest.approx(48 * 215.58274122871848, abs=1e-8)
    assert report.region_area_by_kind_mm2["StatorYoke"] == pytest.approx(25906.845668312733, abs=1e-8)
    assert sum(report.region_area_by_kind_mm2.values()) == pytest.approx(math.pi * (134.62**2 - 55.32**2), abs=1e-8)
    slots = [r for r in ir.regions if r.kind == "SlotWinding"]
    assert all(any(s.kind == "arc" and s.radius_mm == pytest.approx(4) for s in r.loops[0].segments) for r in slots)
    # Every copied curve remains analytic: no polygon tessellation in the IR.
    assert any(s.kind == "arc" and s.radius_mm == pytest.approx(134.62) for s in ir.regions[0].loops[0].segments)


def test_rotor_motion_is_a_rigid_rotation_and_keeps_the_stator_fixed():
    cfg = config()
    geom = compute_geometry(cfg)
    before = build_geometry_ir(cfg, geom=geom)
    _rotate_magnets_in_place(geom, math.radians(7.5))
    after = build_geometry_ir(cfg, geom=geom)
    z = complex(math.cos(math.radians(7.5)), math.sin(math.radians(7.5)))
    for a, b in zip(before.regions, after.regions, strict=True):
        assert a.area_mm2 == pytest.approx(b.area_mm2, abs=1e-8)
        if a.motion_group != "rotor" and a.kind != "Airgap":
            assert a.loops == b.loops
        if a.motion_group == "rotor":
            p, q = a.loops[0].segments[0].start, b.loops[0].segments[0].start
            assert complex(q.x_mm, q.y_mm) == pytest.approx(complex(p.x_mm, p.y_mm) * z, abs=1e-8)


def test_preview_preserves_separate_bore_and_pocket_contours_without_changing_ir():
    from backend.geometry_ir_tessellation import tessellate_ir_loop
    from backend.preview import generate_preview

    cfg = config()
    ir = build_geometry_ir(cfg)
    preview = generate_preview(cfg)
    assert not preview.validation_errors
    rotor = next(region for region in preview.regions if region.region_type == "rotor_core")
    # Rotor OD, hollow bore and eight independent HoleM50 cavities.
    assert rotor.loops is not None and len(rotor.loops) == 10
    assert len(next(r for r in preview.regions if r.region_type == "stator_yoke").loops) == 2
    for native, rendered in zip(ir.regions, preview.regions, strict=False):
        assert rendered.loops == [
            [[float(x), float(y)] for x, y in tessellate_ir_loop(loop)] for loop in native.loops
        ]
        def area(loop):
            return abs(sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(loop, loop[1:] + loop[:1]))) / 2
        assert area(rendered.loops[0]) - sum(area(loop) for loop in rendered.loops[1:]) == pytest.approx(
            native.area_mm2, rel=0.001
        )
    assert build_geometry_ir(cfg) == ir


@pytest.mark.parametrize("rotor_deg", [0, 7.5, 90])
def test_preview_polarity_alternates_in_pairs_without_changing_native_vectors(rotor_deg):
    from backend.preview_from_ir import preview_regions_from_geometry_ir

    cfg = config()
    geom = compute_geometry(cfg)
    _rotate_magnets_in_place(geom, math.radians(rotor_deg))
    ir = build_geometry_ir(cfg, geom=geom)
    before = [r.magnetization_xy for r in ir.regions if r.kind == "Magnet"]
    magnets = [r for r in preview_regions_from_geometry_ir(ir) if r.region_type.startswith("magnet_")]
    expected = [polarity for _ in range(4) for polarity in ("s", "s", "n", "n")]
    assert [r.region_type.split("_")[1] for r in magnets] == expected
    assert Counter(r.fill for r in magnets) == {"#E53E3E": 8, "#3182CE": 8}
    assert [r.text_label for r in magnets if r.text_label] == ["S", "N"] * 4
    assert before == [r.magnetization_xy for r in ir.regions if r.kind == "Magnet"]


@pytest.mark.parametrize("angle,clockwise,expected", [
    (0, False, (-191.51111077974448, 234.9231551964771, -43.412044416732584)),
    (90, False, (160.69690242163483, 85.5050358314172, -246.201938253052)),
    (90, True, (-160.69690242163483, -85.5050358314172, 246.201938253052)),
])
def test_published_phi0_phase_current_golden_vectors(angle, clockwise, expected):
    cfg = config()
    assert _clockwise_excitation_config(cfg) == cfg
    sample = resolve_phase_current_sample(cfg, angle, clockwise_positive=clockwise)
    assert sample.phase_current_a == pytest.approx(expected, abs=1e-10)
    assert sum(sample.phase_current_a) == pytest.approx(0, abs=1e-10)


def test_cache_signature_distinguishes_exported_geometry_and_its_revision(monkeypatch):
    cfg = config()
    signature = build_mesh_signature_payload(cfg)
    generic = cfg.model_copy(update={"geometry_reference": None})
    assert build_mesh_signature_payload(generic) != signature
    geometry = signature["topology_provenance"]["geometry"]
    assert geometry["geometry_asset_sha256"] == hashlib.sha256(
        (ROOT / "backend/reference_models/pyleecan_prius_2004.json").read_bytes()
    ).hexdigest()
    monkeypatch.setattr(prius, "geometry_asset_sha256", lambda: "0" * 64)
    assert build_mesh_signature_payload(cfg) != signature


def test_temperature_factor_keeps_armature_only_field_composition():
    from backend.magneto2d_adapter import _magneto2d_env_overrides

    cfg = config()
    assert float(_magneto2d_env_overrides(cfg)["COILEM_MAGNET_BR_SCALE"]) == pytest.approx(.96)
    cfg.solve_params.field_composition_source = "armature"
    assert _magneto2d_env_overrides(cfg)["COILEM_MAGNET_BR_SCALE"] == "0"


@pytest.mark.skipif(not GMSH_AVAILABLE, reason="requires Gmsh")
def test_real_mesh_is_connected_and_rebake_conserves_each_slots_ampere_turns():
    cfg = config()
    preview = run_gmsh_mesh_preview(cfg, rotor_angle_deg=7.5)
    artifact = preview["solve_mesh_artifact"]
    qa = preview["mesh_qa"]
    assert qa["connected_components"] == 1
    assert qa["max_region_area_delta_pct"] < 1
    cfg.solve_params.current_angle_deg = 60
    rebaked = _rebake_gmsh_artifact_for_config(artifact, cfg)
    nodes = np.asarray(rebaked["mesh"]["nodes"])
    tri = np.asarray(rebaked["mesh"]["triangles"])
    a, b = nodes[tri[:, 1]] - nodes[tri[:, 0]], nodes[tri[:, 2]] - nodes[tri[:, 0]]
    areas = abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) * .5e-6
    ids = np.asarray(rebaked["element_region_ids"])
    densities = np.asarray(rebaked["element_current_density_a_per_m2"])
    # At native 30 electrical degrees and Phi0=60, source angle is 30 degrees.
    expected = {"A": 216.50635094610965, "B": 0., "C": -216.50635094610965}
    for region in rebaked["physics_contract"]["regions"]:
        if region["kind"] == "SlotWinding":
            w = region["winding"]
            signed_turns = 9 if w["direction"] == "in" else -9
            mask = ids == region["id"]
            assert sum(densities[mask] * areas[mask]) == pytest.approx(signed_turns * expected[w["phase"]], abs=1e-8)


@pytest.mark.parametrize("case_id", list(prius.CASES))
def test_both_registered_cases_are_loadable_without_research_flags(case_id, monkeypatch):
    monkeypatch.delenv("COILEM_EXPERIMENTAL_ROTORS", raising=False)
    cfg = parse_public_motor_config(prius.case_config(case_id))
    ui = json.loads((ROOT / f"frontend/src/public/examples/{case_id}.coilem").read_text(encoding="utf-8"))
    assert MotorConfig.model_validate(ui) == cfg
    assert parse_public_motor_config(json.loads(cfg.model_dump_json())) == cfg
    expected = prius.CASES[case_id]
    assert cfg.solve_params.rated_speed_rpm == expected["speed_rpm"]
    from backend.magneto2d_adapter import _magneto2d_env_overrides
    assert float(_magneto2d_env_overrides(cfg)["COILEM_MAGNET_BR_SCALE"]) == pytest.approx(1 if expected["magnet_temperature_C"] == 20 else .96)
    # Removing the reference identity cannot enable the generic experimental rotor.
    ui.pop("geometry_reference")
    with pytest.raises(PublicConfigError):
        parse_public_motor_config(ui)


def test_saved_native_report_names_the_actual_explicit_current_convention():
    cfg = config()
    original = {"current_angle_reference": "gamma from q-axis"}
    report = {"operating_point": original}
    currents = [-191.51111077974448, 234.9231551964771, -43.412044416732584]
    artifact = {"physics_contract": {"provenance": {"phase_current_A": currents}}}
    prius.report_reference_sources(report, cfg, artifact)
    assert report["native_input_operating_point"] is original
    actual = report["operating_point"]
    assert actual["phase_current_A"] == currents
    assert "Pyleecan d-axis Phi0" in actual["current_angle_reference"]
    assert "generic CLI sine formula is unused" in actual["resolution_rule"]
    assert actual["magnet_temperature_C"] == 60
    assert actual["geometry_asset_sha256"] == prius.geometry_asset_sha256()
    with pytest.raises(ValueError, match="explicit native Gmsh"):
        prius.report_reference_sources({}, cfg, None)


def test_no_load_report_does_not_retain_the_loaded_phase_current_provenance():
    from backend.solver import _zero_current_solve_mesh_artifact

    cfg = config()
    original = {"physics_contract": {"regions": [], "provenance": {"phase_current_A": [100, -50, -50]}},
                "element_current_density_a_per_m2": [1, -1]}
    zeroed = _zero_current_solve_mesh_artifact(original)
    report = {}
    prius.report_reference_sources(report, cfg, zeroed)
    assert report["operating_point"]["phase_current_A"] == [0, 0, 0]
    assert original["physics_contract"]["provenance"]["phase_current_A"] == [100, -50, -50]
    assert zeroed["element_current_density_a_per_m2"] == [0, 0]


@pytest.mark.skipif(not GMSH_AVAILABLE, reason="requires Gmsh")
def test_exact_winding_linkage_is_dual_to_the_applied_mesh_current():
    cfg = config()
    artifact = run_gmsh_mesh_preview(cfg, rotor_angle_deg=-7.5)["solve_mesh_artifact"]
    nodes = np.asarray(artifact["mesh"]["nodes"])
    az = .01 * np.sin(nodes[:, 0] / 100) + .015 * np.cos(nodes[:, 1] / 100)
    report = {"results": {}, "field_plot": {"az_nodal": az.tolist()}}
    prius.extract_winding_report(report, cfg, artifact)
    audit = report["reference_winding_extraction"]
    assert audit["sum_phase_flux_current_J"] == pytest.approx(audit["integral_Az_Jz_L_J"], abs=1e-12)
    assert len(report["results"]["slot_flux_linkage_contributions"]) == 48
    currents = artifact["physics_contract"]["provenance"]["phase_current_A"]
    for row in report["results"]["slot_excitation_contributions"]:
        assert row["phase_current_a"] == pytest.approx(currents["ABC".index(row["phase"])], abs=1e-10)
    # Gauge invariance follows from the signed, balanced turns of each phase.
    shifted = {"results": {}, "field_plot": {"az_nodal": (az + .3).tolist()}}
    prius.extract_winding_report(shifted, cfg, artifact)
    assert shifted["reference_winding_extraction"]["phase_flux_linkage_Wb"] == pytest.approx(audit["phase_flux_linkage_Wb"], abs=1e-14)


def test_preview_symbols_and_winding_layout_use_the_same_published_labels_as_the_solver():
    from backend.preview import generate_preview

    preview = generate_preview(config())
    actual = {slot.slot_index: (slot.phase, slot.direction) for slot in preview.winding_layout}
    expected = {s["winding"]["slot"]: (s["winding"]["phase"], s["winding"]["direction"])
                for s in prius.source()["surfaces"] if "winding" in s}
    assert actual == expected
    assert len(preview.winding_coils) == 24
    for coil in preview.winding_coils:
        assert actual[coil.slot_in][0] == actual[coil.slot_out][0] == coil.phase
        assert actual[coil.slot_in][1] != actual[coil.slot_out][1]


def test_published_app_evidence_keeps_complete_actual_grids_and_its_measured_sources():
    folder = ROOT / "docs/benchmarks/pyleecan-prius-v1"
    report = json.loads((folder / "app-results.json").read_text(encoding="utf-8"))
    registration = json.loads((folder / "app-registration.json").read_text(encoding="utf-8"))
    assert registration["complete"] is True and registration["source_dirty"] is False
    assert report["field_source_commit"] == registration["source_commit"]
    assert report["registration_sha256"] == hashlib.sha256((folder / "app-registration.json").read_bytes()).hexdigest()
    assert report["protocol_sha256"] == hashlib.sha256((folder / "protocol.json").read_bytes()).hexdigest()
    # The original v1 collector/analyzer versions remain accessible at
    # 377ea0ccb1e2d3b02cd17012c1e04ec424e43df1 before tooling hardening.
    # Preserve those historical tool identities; current numerical sources
    # below must still match. Collection-only fixes do not restamp old fields.
    assert report["analysis_runner_sha256"] == "97ba2c2c2921161f868ca05b9eeab903c66bbbb40e88b5555b006db95984a274"
    assert report["source_sha256"] == registration["source_sha256"]
    for name, digest in report["source_sha256"].items():
        if name == "tools/benchmark_prius.py":
            assert digest == "6acec522ac60bdeeea110667c3d9b3a3c539ae6c526f86cee538c032ccc78c0c"
        else:
            assert registration["source_sha256"][name] == digest, name
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                from backend.qualification import classify_qualification
                config = MotorConfig.model_validate_json((ROOT / "backend/reference_models/pyleecan_prius_2004_config.json").read_text())
                assert classify_qualification(config)["status"] == "experimental"
    for name, digest in report["historical_evidence_sha256"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
    assert report["all_software_checks_pass"] and all(report["checks"].values())
    assert len(report["checks"]) == 10 and len(report["jobs"]) == 17
    assert sum(a["actual_loaded_fields"] for a in report["audits"].values()) == 436
    assert sum(a["actual_noload_fields"] for a in report["audits"].values()) == 132
    assert sum(len(a["field_reports"]) for a in report["audits"].values()) == 568
    assert [row["Phi0_deg"] for row in report["curve"]] == list(range(60, 181, 10))
    # Reproduce the declared waveform metric from the actual published samples.
    phases = np.asarray(report["tutorial"]["app_phase_voltage_V"])
    ab = phases[:, 0] - phases[:, 1]
    assert np.sqrt(np.mean(ab**2)) == pytest.approx(report["tutorial"]["sampled_AB_rms_V"], abs=1e-12)
    assert report["qualified"] is False
