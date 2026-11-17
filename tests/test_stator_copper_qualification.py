"""Electrical-period units, independent component gates and evidence integrity."""
import copy
import subprocess
import sys

import numpy as np
import pytest

from tools.phase_g_loss.contract import ROOT, read, sha, suite, write
from tools.phase_g_loss.report import independent_loss, production_loss
from tools.phase_g_loss.stator_contract import checkpoint, config, cycle_repeatability, magnetic_geometry
from tools.phase_g_loss.stator_report import compare


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
    native = {"case_id": "example", "protocol_sha256": "native", "history_pass": True,
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
    bad["history_pass"] = False
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
