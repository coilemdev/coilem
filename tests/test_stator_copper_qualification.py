"""Electrical-period units, independent component gates and evidence integrity."""
import copy
import subprocess
import sys

import numpy as np
import pytest

from tools.phase_g_loss.contract import ROOT, read, sha, suite, write
from tools.phase_g_loss.report import independent_loss, production_loss
from tools.phase_g_loss.stator_contract import checkpoint, config, cycle_repeatability, magnetic_geometry
from tools.phase_g_loss.stator_report import compare, loss_history_pass


@pytest.mark.parametrize("case", [c["id"] for c in suite()["cases"]])
def test_profile_runs_full_motor_production_loss_without_rotor(case):
    from backend.models import MotorConfig
    from backend.sweep_planning import loaded_angle_grid
    cfg = MotorConfig.model_validate(config(case))
    assert cfg.solve_options.losses_efficiency
    assert not cfg.solve_options.rotor_iron_loss
    assert cfg.solve_params.symmetry == "full"
    assert len(loaded_angle_grid(cfg)) == 96
    assert cfg.winding.wire is not None


def test_electrical_cycle_uses_pole_pair_frequency_and_independent_dft():
    from dataclasses import asdict

    from backend.iron_loss import M350_50A_LOSS
    n = 96
    theta = 2 * np.pi * np.arange(n) / n
    values = np.zeros((n, 1, 2))
    values[:, 0, 0] = .3 + np.sin(theta)
    area = np.array([1e-4])
    coefficients = asdict(M350_50A_LOSS)
    native = production_loss(values, area, 3000 * 4, .1, coefficients)
    ref = independent_loss(values, -360 * np.arange(n) / n, area, 3000 * 4, .1, coefficients)
    mass = 1e-4 * .1 * coefficients["density_kg_m3"]
    assert native["hysteresis_W"] == pytest.approx(mass * coefficients["kh"] * 200)
    assert native["lamination_eddy_W"] == pytest.approx(mass * coefficients["kc"] * 200**2)
    assert ref["total_W"] == pytest.approx(native["total_W"], rel=1e-10)


def test_repeatability_keeps_rotor_style_failure_and_never_repairs_raw_fields():
    theta = 2 * np.pi * np.arange(96) / 96
    values = np.stack((1 + .2 * np.sin(theta), .3 * np.cos(theta)), axis=-1)[:, None, :]
    original = values.copy()
    def calculate(v, speed):
        return {"total_W": float(np.mean(v**2) * speed / 3000)}
    result = cycle_repeatability(values, values[0] + 1e-5, np.array([1.]), calculate)
    assert result["pass"]
    assert not result["strict_rotor_style_closure_pass"]
    assert not result["raw_fields_corrected"]
    np.testing.assert_array_equal(values, original)
    assert not cycle_repeatability(values, values[0] + .1, np.array([1.]), calculate)["pass"]


def test_component_qualification_does_not_read_rotor_verdicts():
    watts = {"hysteresis_W": 1., "lamination_eddy_W": 2., "total_W": 3.}
    stator = {str(s): {"samples": {"96": watts}} for s in (1500, 3000)}
    native = {"case_id": "example", "protocol_sha256": "native", "history_pass": False, "stator_loss_history_pass": True,
              "stator": stator, "copper": {"W": 6., "phase_resistance_ohm": .1},
              "cycle_repeatability": {"pass": True}, "rotor": {"pass": False}}
    ref = {**native, "protocol_sha256": "reference", "native_protocol_sha256": "native", "new_field_solves": 0, "reused_poses": 97}
    result = compare(native, ref)
    assert result["reference_checks_pass"]
    assert not result["rotor_gates_used"]
    assert not result["full_motor_efficiency_qualified"]
    assert result["rotor_loss_status"] == "experimental"
    wrong = copy.deepcopy(ref)
    wrong["copper"]["phase_resistance_ohm"] = .2
    assert not compare(native, wrong)["dc_copper_reference_pass"]
    bad = copy.deepcopy(ref)
    bad["stator_loss_history_pass"] = False
    assert not compare(native, bad)["stator_reference_pass"]


def test_new_reference_checkpoint_distinguishes_electrical_and_mechanical_angles(tmp_path):
    write(tmp_path / "protocol.json", {"requested_config": {"rotor": {"pole_count": 10}}})
    np.savez(tmp_path / "material-geometry.npz", stator_corners=np.ones((1, 3, 2)))
    folder = tmp_path / "position-0001"
    folder.mkdir()
    np.savez(folder / "fields.npz", stator=np.ones((1, 2)))
    record = {"index": 1, "electrical_angle_deg": -3.75, "mechanical_angle_deg": -.75,
              "protocol_sha256": sha(tmp_path / "protocol.json"), "geometry_sha256": sha(tmp_path / "material-geometry.npz"),
              "sha256": {"fields.npz": sha(folder / "fields.npz")}}
    write(folder / "position.json", record)
    assert checkpoint(tmp_path, 1)["mechanical_angle_deg"] == -.75
    write(folder / "position.json", {**record, "mechanical_angle_deg": -.9375})
    with pytest.raises(ValueError, match="mechanical angle"):
        checkpoint(tmp_path, 1)


def test_base_reuse_only_ignores_nonmagnetic_sampling_and_current():
    original = config("distributed-spm-no-load")
    loaded = config("distributed-spm-loaded", 48, 1500)
    assert magnetic_geometry(original) == magnetic_geometry(loaded)
    loaded["materials"]["magnet"] = "N35"
    assert magnetic_geometry(original) != magnetic_geometry(loaded)


def test_reference_import_is_independent_of_production_backend():
    subprocess.run([sys.executable, "-c", "import sys; import tools.phase_g_loss.stator_femm; "
                    "assert not any(k == 'backend' or k.startswith('backend.') for k in sys.modules)"], cwd=ROOT, check=True)


def test_profile_has_separate_scope_without_changing_old_rotor_plan():
    profile = read(ROOT / "benchmarks/phase-g-v1/stator-copper-59.json")
    assert profile["electrical_samples"] == 96
    assert profile["rotor_gates_included"] is False
    assert read(ROOT / "benchmarks/phase-g-v1/benchmark_spec.json")["positions"] == 384


def test_sinusoidal_grid_is_verified_from_angles_not_six_step_metadata():
    from tools.phase_g_loss.stator_native import validate_production_grid
    payload = {"solve_metadata": {"rotor_positions": 24, "sector_repeats": None, "loaded_cycle_complete": None},
               "torque_waveform": {"electrical_angle_deg": list(range(0, 360, 15))}}
    validate_production_grid(payload, 24)
    payload["torque_waveform"]["electrical_angle_deg"][-1] = 360
    with pytest.raises(ValueError, match="uniform electrical cycle"):
        validate_production_grid(payload, 24)


def test_loss_policy_keeps_failed_point_field_diagnostic_without_correcting_fields():
    stator = {str(s): {"angular_pass": True} for s in (1500, 3000)}
    repeat = {"pass": False, "raw_fields_corrected": False,
              "loss_sensitivity": {str(s): {"gates": {"hysteresis_W": True, "lamination_eddy_W": True, "total_W": True}}
                                   for s in (1500, 3000)}}
    assert loss_history_pass(stator, repeat)
    assert repeat["pass"] is False
    assert repeat["raw_fields_corrected"] is False
    repeat["loss_sensitivity"]["3000"]["gates"]["lamination_eddy_W"] = False
    assert not loss_history_pass(stator, repeat)


def test_float32_archive_budget_is_separate_from_physics_and_retains_old_failure():
    from tools.phase_g_loss.stator_reproduction import reproduction
    original = {key: value for key, value in zip(
        ("iron_loss_W", "iron_hysteresis_loss_W", "iron_eddy_loss_W"), (492.476463481, 203.642084302, 288.834379179), strict=True)}
    before = original.copy()
    reconstructed = {key: value * (1 - 3.5e-6) for key, value in original.items()}
    receipt = reproduction(original, reconstructed)
    assert receipt["pass"]
    assert all(not row["predecessor_1ppm_pass"] for row in receipt["components"].values())
    assert not receipt["reported_api_losses_modified"]
    assert not receipt["component_qualification_gates_modified"]
    assert original == before
    assert not reproduction(original, {key: value * 1.001 for key, value in original.items()})["pass"]


def test_archive_resume_preserves_old_collector_and_refuses_other_source_changes(tmp_path, monkeypatch):
    from tools.phase_g_loss import stator_reproduction as archive
    directory = tmp_path / "native/example"
    directory.mkdir(parents=True)
    source = tmp_path / "backend.py"
    source.write_text("physics")
    expected = {"identity": {"source_sha256": {archive.COLLECTOR: "current", "backend.py": sha(source)}}, "request": 96}
    previous = copy.deepcopy(expected)
    previous["identity"]["source_sha256"][archive.COLLECTOR] = archive.PREDECESSOR
    write(directory / "protocol.json", previous)
    assert archive.measurement_protocol(directory, expected) == previous
    assert expected["identity"]["source_sha256"][archive.COLLECTOR] == "current"
    monkeypatch.setattr(archive, "ROOT", tmp_path)
    archive.verify_measurement_sources(tmp_path)
    source.write_text("different physics")
    with pytest.raises(ValueError, match="backend.py"):
        archive.verify_measurement_sources(tmp_path)
