"""Phase F qualifies only its separate reviewed Windows engineering scope."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend import phase_f_qualification as phase_f
from backend import qualification
from backend.models import MotorConfig
from backend.models.performance import CoggingTorque, DqFluxLinkage

pytestmark = pytest.mark.pr
ROOT = Path(__file__).resolve().parents[1]
COMMIT = "34de0f4ca1604311f15edf6fb49b5a2a1bf27909"
FAMILY_CASES = (
    "spm_outer_14p12s_drone__baseline", "spm_outer_12p9s_micro__baseline",
    "spm_outer_10p12s_single_layer__baseline", "spm_outer_28p24s_multirotor__baseline",
    "spm_outer_30p27s_hub__baseline",
)


def config(case=FAMILY_CASES[0]):
    return MotorConfig.model_validate_json((ROOT / "benchmarks/abcd-v1.8/fixtures" / (case + ".json")).read_text())


def changed(motor, section, **updates):
    return motor.model_copy(update={section: getattr(motor, section).model_copy(update=updates)})


@pytest.fixture
def measured_windows(monkeypatch):
    monkeypatch.setattr(phase_f, "_platform_key", lambda: "windows-x86_64")
    monkeypatch.setattr(phase_f, "_verified_evidence", lambda: {"measured_commit": COMMIT})


@pytest.mark.parametrize("case", sorted(phase_f.CASE_IDS))
def test_all_ten_measured_requests_use_separate_windows_basis(case, measured_windows):
    result = qualification.classify_qualification(config(case))
    assert result["status"] == "qualified"
    assert "Phase F Windows" in result["basis"] and COMMIT[:8] in result["basis"]
    assert result["basis"] != qualification.QUALIFICATION_BASIS
    assert "mean torque and Back-EMF" in result["reason"]
    assert "FEMM" not in json.dumps(result)


@pytest.mark.parametrize("platform", ["macos-arm64", "macos-x86_64", "linux-x86_64", "windows-arm64", "windows-x86"])
def test_windows_evidence_cannot_qualify_another_platform(platform, measured_windows, monkeypatch):
    monkeypatch.setattr(phase_f, "_platform_key", lambda: platform)
    assert qualification.classify_qualification(config())["status"] == "experimental"


@pytest.mark.parametrize(("section", "updates"), [
    ("stator", {"slot_count": 18}),
    ("rotor", {"pole_count": 16}),
    ("winding", {"layers": 1}),
    ("winding", {"type": "distributed"}),
    ("winding", {"parallel_paths": 2}),
    ("winding", {"turns_per_coil": 24}),
    ("winding", {"coil_span": 1}),
    ("stator", {"OD_mm": 17.9}),
    ("stator", {"tooth_width_mm": 100}),
    ("rotor", {"ID_mm": 32.2}),
    ("rotor", {"flux_barrier_count": 2}),
    ("materials", {"magnet_grade": "N35"}),
    ("materials", {"conductor": "aluminum"}),
    ("materials", {"stator_steel": "custom-steel"}),
    ("solve_params", {"current_amplitude_A": 15.01}),
    ("solve_params", {"current_angle_deg": 30.01}),
    ("solve_params", {"current_angle_deg": -1}),
    ("solve_params", {"current_amplitude_convention": "rms"}),
    ("solve_params", {"excitation_mode": "ideal_six_step_120"}),
    ("solve_params", {"rated_speed_rpm": 1500}),
    ("solve_params", {"magnet_temperature_C": 60}),
    ("solve_params", {"winding_temperature_C": 60}),
    ("solve_params", {"mesh_density": "fine"}),
    ("solve_params", {"mesh_build": "fast"}),
    ("solve_params", {"rotor_rotation_model": "fixed_mesh"}),
    ("solve_params", {"corner_refinement": True}),
    ("solve_params", {"slot_sidewall_refinement": True}),
    ("solve_params", {"linear_steel_mu_rel": 1000}),
    ("solve_params", {"rotor_sweep_range_deg": 180}),
    ("solve_params", {"rotor_step_deg": 15}),
    ("solve_params", {"solve_quality": "standard"}),
    ("solve_params", {"torque_method": "contour"}),
    ("solve_params", {"field_composition_source": "armature"}),
    ("solve_params", {"nonlinear_solver": "newton"}),
])
def test_unmeasured_settings_fail_closed(section, updates, measured_windows):
    assert qualification.classify_qualification(changed(config(), section, **updates))["status"] == "experimental"


@pytest.mark.parametrize("case", FAMILY_CASES)
def test_family_current_limit_and_angle_range(case, measured_windows):
    motor = config(case)
    _, maximum = phase_f.FAMILIES[(motor.stator.slot_count, motor.rotor.pole_count, motor.winding.layers)]
    for current in (0, maximum / 2, maximum):
        tested = changed(motor, "solve_params", current_amplitude_A=current, current_angle_deg=15,
                         magnet_temperature_C=20, winding_temperature_C=20)
        assert qualification.classify_qualification(tested)["status"] == "qualified"
    assert qualification.classify_qualification(changed(motor, "solve_params", current_amplitude_A=maximum + .1))["status"] == "experimental"


def test_owner_accepted_geometry_range_is_not_a_full_configuration_whitelist(measured_windows):
    motor = config()
    factor = 1.1
    stator = motor.stator.model_copy(update={key: value * factor for key, value in motor.stator.model_dump().items()
                                          if key.endswith("_mm") and isinstance(value, (int, float))})
    rotor = motor.rotor.model_copy(update={key: value * factor for key, value in motor.rotor.model_dump().items()
                                        if key.endswith("_mm") and isinstance(value, (int, float))})
    variation = motor.model_copy(update={"stator": stator, "rotor": rotor})
    assert qualification.classify_qualification(variation)["status"] == "qualified"
    assert "not each independently benchmarked" in qualification.classify_qualification(variation)["caveats"][0]


def test_room_temperature_only_and_missing_solve_settings(measured_windows):
    assert qualification.classify_qualification(config().model_copy(update={"solve_params": None}))["status"] == "experimental"


def test_standard_full_grid_is_experimental_because_tolerance_differs(measured_windows):
    from backend.magneto2d_adapter import _magneto2d_env_overrides
    from backend.sweep_planning import loaded_angle_grid

    custom = config()
    standard = changed(custom, "solve_params", solve_quality="standard")
    assert loaded_angle_grid(custom) == loaded_angle_grid(standard) == [7.5 * index for index in range(48)]
    assert "MAGNETO2D_NONLINEAR_TOL" not in _magneto2d_env_overrides(custom)
    assert "MAGNETO2D_NONLINEAR_TOL" in _magneto2d_env_overrides(standard)
    assert qualification.classify_qualification(custom)["status"] == "qualified"
    assert qualification.classify_qualification(standard)["status"] == "experimental"


def test_lrk_reference_keeps_its_own_experimental_status(measured_windows):
    motor = MotorConfig.model_validate_json((ROOT / "backend/reference_models/lrk_12s14p_config.json").read_text())
    result = qualification.classify_qualification(motor)
    assert result["status"] == "experimental"
    assert "all 10 Windows" not in result["reason"]


def test_phase_f_does_not_qualify_derived_performance_outputs(measured_windows):
    motor = config("spm_outer_10p12s_single_layer__baseline")
    assert qualification.classify_qualification(motor)["status"] == "qualified"
    assert qualification.dq_flux_linkage_status(motor)[0] == "experimental"
    assert qualification.magnet_temperature_status(changed(motor, "solve_params", magnet_temperature_C=20))[0] == "experimental"
    caveats = " ".join(qualification.classify_qualification(motor)["caveats"])
    for name in ("cogging", "losses", "efficiency", "d/q", "inductance", "magnet-temperature"):
        assert name in caveats
    assert "Independent analytical qualifications keep their own scope" in caveats
    assert DqFluxLinkage.model_fields["inductance_status"].default == "experimental"
    assert CoggingTorque.model_fields["status"].default == "experimental"


def test_existing_inner_rotor_qualification_does_not_depend_on_phase_f(monkeypatch):
    monkeypatch.setattr(qualification, "evidence_matches_runtime", lambda: True)
    monkeypatch.setattr(phase_f, "_verified_evidence", lambda: None)
    motor = MotorConfig.model_validate_json((ROOT / "benchmarks/abcd-v1.6/fixtures/spm_8p12s_concentrated__dq_I20_g0.json").read_text())
    result = qualification.classify_qualification(motor)
    assert result["status"] == "qualified"
    assert result["basis"] == qualification.QUALIFICATION_BASIS


@pytest.fixture
def packet(tmp_path, monkeypatch):
    from backend import resources
    from backend.benchmark_suite import contract, references
    from backend.benchmark_suite import record as record_module

    def save(relative, value):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {"schema": "coilem.frozen_reference_bundle/v2", "validation_status": phase_f.REVIEW_STATUS,
                "reference_id": "sha256:" + "a" * 64}
    manifest_sha = save(phase_f.BUNDLE_DIR + "/manifest.json", manifest)
    spec = {"protocol_version": "1.8.0"}
    spec_sha = save(phase_f.SUITE_FILE, spec)
    record = {"schema": "coilem.benchmark_record/v1", "platform": "windows-x86_64", "measured_commit": COMMIT,
              "source": "benchmarks/windows-v055-phase-f-20261108/report", "suite_sha256": spec_sha,
              "reference_manifest_sha256": manifest_sha, "reference_id": manifest["reference_id"],
              "reference_bundle_sha256": "b" * 64,
              "qualification_scope": {"platform": "windows-x86_64", "phase": "F", "outputs": ["mean_torque", "back_emf"]},
              "physics_files": {"test-source": "c" * 64},
              "cases": {cid: {"phase": "F", "status": "PASS", "gates": {key: "PASS" for key in phase_f.GATE_IDS},
                              "values": {"mean_torque_Nm": .1, "back_emf_fundamental_V": 1., "back_emf_peak_V": 1.5}}
                        for cid in phase_f.CASE_IDS}}
    monkeypatch.setattr(phase_f, "RECORD_SHA256", save(phase_f.RECORD_FILE, record))
    monkeypatch.setattr(resources, "data_file", lambda relative: tmp_path / relative)
    monkeypatch.setattr(contract, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(references, "load_suite", lambda path: spec)
    monkeypatch.setattr(references, "load_bundle", lambda path, suite: (manifest, {cid: {} for cid in phase_f.CASE_IDS}, "b" * 64))
    monkeypatch.setattr(record_module, "check_physics", lambda record: {"status": "MATCH"})
    return {"root": tmp_path, "record": record, "manifest": manifest, "save": save,
            "record_module": record_module, "references": references}


def test_public_record_review_bundle_and_runtime_physics_are_all_required(packet):
    assert phase_f._verified_evidence() == packet["record"]


def test_missing_or_tampered_record_fails_closed(packet):
    path = packet["root"] / phase_f.RECORD_FILE
    raw = path.read_bytes()
    path.write_bytes(raw + b" ")
    assert phase_f._verified_evidence() is None
    path.unlink()
    assert phase_f._verified_evidence() is None


@pytest.mark.parametrize("physics_status", ["DIFFERS", "UNVERIFIED"])
def test_changed_or_unverifiable_runtime_physics_cannot_keep_claim(packet, monkeypatch, physics_status):
    monkeypatch.setattr(packet["record_module"], "check_physics", lambda record: {"status": physics_status})
    assert phase_f._verified_evidence() is None


@pytest.mark.parametrize("relative", [phase_f.SUITE_FILE, phase_f.BUNDLE_DIR + "/manifest.json"])
def test_changed_suite_or_reference_manifest_fails_closed(packet, relative):
    path = packet["root"] / relative
    path.write_bytes(path.read_bytes() + b" ")
    assert phase_f._verified_evidence() is None


def test_unreviewed_or_changed_reference_packet_fails_closed(packet):
    packet["manifest"]["validation_status"] = "REVIEW_REQUIRED"
    assert phase_f._verified_evidence() is None


@pytest.mark.parametrize("mutation", ["case", "gate", "output", "platform"])
def test_even_a_pinned_malformed_record_cannot_qualify(packet, monkeypatch, mutation):
    record = deepcopy(packet["record"])
    cid = next(iter(record["cases"]))
    if mutation == "case":
        record["cases"].pop(cid)
    elif mutation == "gate":
        record["cases"][cid]["gates"]["mean_torque"] = "FAIL"
    elif mutation == "output":
        record["qualification_scope"]["outputs"].append("cogging")
    else:
        record["platform"] = "macos-arm64"
    monkeypatch.setattr(phase_f, "RECORD_SHA256", packet["save"](phase_f.RECORD_FILE, record))
    assert phase_f._verified_evidence() is None
