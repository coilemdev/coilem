"""Phase G integrates qualified scalar losses without modifying the frozen A-F suite."""
import copy
import math
import shutil

import pytest

from backend import resources
from backend.benchmark_suite import COMMAND_PHASES, PROTOCOL_VERSION, command, references
from backend.benchmark_suite.contract import DEFAULT_BUNDLE, ROOT, SPEC, canonical, read, sha, write
from backend.benchmark_suite.loss_metrics import evaluate_loss
from backend.benchmark_suite.loss_registry import verify_ag
from backend.benchmark_suite.record import gated_values


@pytest.fixture(scope="module")
def registered():
    spec = references.load_suite(SPEC)
    manifest, values, digest = references.load_bundle(DEFAULT_BUNDLE, spec)
    return spec, manifest, values, digest


def test_default_suite_adds_all_16_loss_points_without_rewriting_af(registered):
    spec, manifest, values, digest = registered
    assert PROTOCOL_VERSION == "1.12.0" and COMMAND_PHASES == tuple("ABCDEFG")
    original = read(ROOT / resources.BENCHMARK_AF_SUITE_FILE)
    assert spec["cases"][:69] == original["cases"]
    assert len(spec["cases"]) == 85 and len(values) == 84 and len(digest) == 64
    assert len([c for c in spec["cases"] if c["phase"] == "G"]) == 16
    assert manifest["protocol_version"] == "1.12.0"
    assert [c["phase"] for c in command.select_cases(spec, COMMAND_PHASES, True)] == list("ABCDEFG")
    with pytest.raises(ValueError, match="preserve all 69"):
        verify_ag({**spec, "cases": spec["cases"][1:]}, ROOT)


def test_loss_requests_use_qualified_full_motor_grid_and_keep_rotor_off(registered):
    from backend.models import MotorConfig
    from backend.public_policy import parse_public_solve_request
    from backend.sweep_planning import loaded_angle_grid
    spec = registered[0]
    for case in (c for c in spec["cases"] if c["phase"] == "G"):
        config = read(ROOT / case["jobs"][0]["fixture"])
        assert canonical(config) == case["jobs"][0]["input_sha256"]
        parsed, _, _ = parse_public_solve_request(config)
        assert parsed == MotorConfig.model_validate(config)
        assert parsed.solve_options.losses_efficiency and not parsed.solve_options.rotor_iron_loss
        assert parsed.solve_params.symmetry == "full" and len(loaded_angle_grid(parsed)) == 96
        assert parsed.solve_params.rated_speed_rpm in (1500, 3000)


def synthetic(case, reference):
    config = read(ROOT / case["jobs"][0]["fixture"])
    ref = reference["values"]
    result = {"summary": {"iron_loss": {"status":"experimental", **{k:ref[k] for k in tuple(ref)[:3]}},
                          "loss_breakdown":{"copper_loss_W":ref["copper_loss_W"]},
                          "winding_resistance":{"phase_resistance_ohm":ref["phase_resistance_ohm"]}},
              "solve_metadata":{"mesh_source":"native", "rotor_positions":96, "nonlinear_worst_tolerance_ratio":.5},
              "torque_waveform":{"electrical_angle_deg":[i*3.75 for i in range(96)]}}
    return config, result


def test_loss_comparison_rejects_missing_components_wrong_cycle_or_rotor_inclusion(registered):
    spec, _, refs, _ = registered
    for case in (c for c in spec["cases"] if c["phase"] == "G"):
        config, result = synthetic(case, refs[case["id"]])
        evaluation = evaluate_loss(result, refs[case["id"]], config)
        assert evaluation["status"] == "PASS" and evaluation["rotor_loss_status"] == "experimental"
        assert not evaluation["full_motor_efficiency_qualified"]
        row = {"phase":"G","status":"PASS","measurements":{"native":result}}
        assert set(gated_values(row)) == set(refs[case["id"]]["values"])
        broken = copy.deepcopy(result)
        broken["torque_waveform"]["electrical_angle_deg"][-1] = 360
        assert evaluate_loss(broken, refs[case["id"]], config)["status"] == "FAIL"
        broken = copy.deepcopy(result)
        broken["summary"]["rotor_iron_loss"] = {"iron_loss_W":1.}
        assert evaluate_loss(broken, refs[case["id"]], config)["status"] == "FAIL"
        broken = copy.deepcopy(result)
        broken["summary"]["iron_loss"]["iron_eddy_loss_W"] = math.nan
        with pytest.raises(ValueError, match="nonfinite"):
            evaluate_loss(broken, refs[case["id"]], config)


def test_reference_change_and_copper_regression_fail_independently(registered):
    spec, _, refs, _ = registered
    case = next(c for c in spec["cases"] if c["id"] == "loss_inner_spm_loaded_3000rpm")
    config, result = synthetic(case, refs[case["id"]])
    result["summary"]["loss_breakdown"]["copper_loss_W"] *= 1.02
    result["summary"]["winding_resistance"]["phase_resistance_ohm"] *= 1.02
    outcome = evaluate_loss(result, refs[case["id"]], config)
    assert outcome["status"] == "FAIL"
    gates = {g["id"]:g["status"] for g in outcome["gates"]}
    assert gates["iron_loss_W"] == "PASS" and gates["copper_loss_W"] == "FAIL"
    altered = copy.deepcopy(refs[case["id"]])
    altered["speed_rpm"] = 1500
    with pytest.raises(ValueError, match="registered full-motor point"):
        evaluate_loss(result, altered, config)


def test_sector_loss_is_explicitly_deferred():
    with pytest.raises(SystemExit):
        command.main(["--sector", "--phase", "G", "--list"])


def test_loss_kernel_is_guarded_for_g_without_relabeling_legacy_af_physics(monkeypatch):
    from backend.benchmark_suite import record
    monkeypatch.setattr(record, "installed_physics_hashes", lambda: ({"backend/iron_loss.py":"new", "backend/torque_metrics.py":"same"}, {}))
    monkeypatch.setattr(record, "installed_physics_dependencies", lambda: {})
    af = {"physics_files":{"backend/torque_metrics.py":"same"}, "cases":{"a":{"phase":"A"}}}
    assert record.check_physics(af)["status"] == "MATCH"
    g = {"physics_files":{**af["physics_files"],"backend/iron_loss.py":"old"}, "cases":{"g":{"phase":"G"}}}
    assert record.check_physics(g)["differs"] == ["backend/iron_loss.py"]


def test_package_includes_scalar_loss_refs_and_source_evidence(registered):
    files = set(resources.benchmark_data_files(ROOT))
    spec = registered[0]
    assert resources.BENCHMARK_AF_SUITE_FILE in files
    assert resources.BENCHMARK_SUITE_FILE in files
    assert "docs/qualification/stator-copper-femm-20261117/summary.json" in files
    for case in (c for c in spec["cases"] if c["phase"] == "G"):
        assert case["jobs"][0]["fixture"] in files
        assert f"benchmarks/reference-baselines/loss-stator-dc-20261117/{case['id']}.json" in files
    assert all((ROOT / path).is_file() for path in files)


def test_rehashed_loss_reference_cannot_replace_the_measured_value(tmp_path):
    from backend.benchmark_suite.loss_registry import LOSS_SUITE, verify_loss_review
    original = ROOT / "benchmarks/reference-baselines/loss-stator-dc-20261117"
    shutil.copytree(original, tmp_path / "bundle")
    bundle = tmp_path / "bundle"
    manifest = read(bundle / "manifest.json")
    spec = read(ROOT / LOSS_SUITE)
    entry = manifest["records"][spec["cases"][0]["id"]]
    record = read(bundle / entry["file"])
    record["result"]["values"]["iron_eddy_loss_W"] *= 1.01
    write(bundle / entry["file"], record)
    entry["sha256"] = sha(bundle / entry["file"])
    with pytest.raises(ValueError, match="differ from the completed FEMM"):
        verify_loss_review(bundle, manifest, spec, read(bundle / "review.json"), ROOT)


def test_loss_record_regrade_keeps_components_and_experimental_scope(registered):
    from tools.build_benchmark_record import regrade
    spec = read(ROOT / "benchmarks/loss-v1/benchmark_spec.json")
    rows = []
    for case in spec["cases"]:
        config, result = synthetic(case, registered[2][case["id"]])
        rows.append({"id":case["id"],"phase":"G","status":"PASS", "configurations":{"native":config},
                     "measurements":{"native":result}, "reference_mode":"FROZEN_REFERENCE"})
    summary = {"run":{"identity":{"protocol_version":"1.12.0"},"selection":{}}, "rows":rows}
    result, _ = regrade(summary, suite=ROOT / "benchmarks/loss-v1/benchmark_spec.json",
                        bundle=ROOT / "benchmarks/reference-baselines/loss-stator-dc-20261117")
    assert len(result["rows"]) == 16 and all(row["evaluation"]["status"] == "PASS" for row in result["rows"])
    assert all(not row["evaluation"]["full_motor_efficiency_qualified"] for row in result["rows"])
