"""Reference attachment verifies evidence and preserves failures without solving."""

import argparse
import copy
import math

import pytest

from tools import report_benchmark_against_reference as late
from tools.benchmark_suite import cli
from tools.benchmark_suite.contract import ROOT, SPEC, canonical, read, sha, write


def test_requires_measured_commit_and_source_hashes(tmp_path, monkeypatch):
    path = tmp_path / "backend" / "example.py"
    path.parent.mkdir()
    path.write_text("value = 1\n")
    identity = {"commit": "pin", "dirty": False, "source_files": {"backend/example.py": sha(path)}}
    monkeypatch.setattr(late.subprocess, "check_output", lambda command, **kw: "pin" if command[-1] == "HEAD" else "")
    late.require_source(tmp_path, "pin", identity)
    path.write_text("value = 2\n")
    with pytest.raises(ValueError, match="source hash differs"):
        late.require_source(tmp_path, "pin", identity)
    identity["commit"] = "other"
    with pytest.raises(ValueError, match="candidate identity"):
        late.require_source(tmp_path, "pin", identity)


def test_selection_rejects_live_run_or_reference_switch():
    spec = {"cases": [{"id": "one", "phase": "A", "jobs": [{"stage": "native"}]}]}
    manifest = {
        "schema": "coilem.benchmark_run/v1", "status": "COMPLETE", "smoke": False,
        "selection": {"case_ids": ["one"], "no_reference": True, "bundle_sha256": None, "spec_sha256": "spec"},
        "jobs": [{"case_id": "one", "phase": "A", "stage": "native", "status": "COMPLETE"}],
    }
    assert len(late.require_selection(manifest, spec, "spec")) == 1
    for key, value in (("no_reference", False), ("bundle_sha256", "old-bundle")):
        bad = copy.deepcopy(manifest)
        bad["selection"][key] = value
        with pytest.raises(ValueError):
            late.require_selection(bad, spec, "spec")
    manifest["jobs"][0]["status"] = "RUNNING"
    with pytest.raises(ValueError, match="still running"):
        late.require_selection(manifest, spec, "spec")


def test_new_axis_diagnostic_keeps_historical_failure():
    golden = read(ROOT / read(SPEC)["golden"])
    angles = [i * 7.5 for i in range(48)]
    currents = [golden["sector_table_A"][int(((angle + 30) % 360) // 60)] for angle in angles]
    result = {
        "electrical_angle_deg": angles,
        "phase_current_waveform": {f"phase_{phase}_A": [row[index] for row in currents] for index, phase in enumerate("abc")},
    }
    before = copy.deepcopy(result)
    protocol = {"excitation": {"product_current_A": 10.0, "commutation_advance_deg": 0.0},
                "gates": {"current_plateau_abs_A_max": 1e-9}}
    diagnostic = late.winding_axis_diagnostic(result, {}, protocol, golden, 30.0)
    assert diagnostic["pr100_winding_axis_sequence"] == "PASS"
    assert diagnostic["historical_fixed_axis_sequence"] == "FAIL"
    assert diagnostic["historical_gates_replaced"] is False
    assert result == before


def synthetic_run(tmp_path):
    """Explicit test-only waveforms; never written as measured benchmark evidence."""
    spec = read(SPEC)
    case = spec["cases"][0]
    configs, _, _ = cli.inputs(spec, [case])
    config = configs[case["id"], "native"]
    angles = [i * config["solve_params"]["rotor_step_deg"] for i in range(48)]
    emf = [5 * math.sin(math.radians(a)) for a in angles]
    result = {
        "summary": {"avg_torque_Nm": 1.0, "back_emf_fundamental_V": 5.0},
        "torque_waveform": {"electrical_angle_deg": angles, "torque_Nm": [1.0] * len(angles)},
        "back_emf_waveform": {"electrical_angle_deg": angles, "phase_a_V": emf, "phase_b_V": emf, "phase_c_V": emf},
        "solve_metadata": {"solver_name": "magneto2d-test-only", "mesh_source": "native", "torque_method": "weighted_stress",
                           "mesh_density": "normal", "solve_time_s": 0.0},
    }
    identity = {"commit": "test-only-pin", "dirty": False, "source_files": {}, "harness_version": "1.3.0",
                "protocol_version": "1.1.0"}
    native = tmp_path / "native"
    request = {"config": config, "config_sha256": canonical(config), "identity": identity, "binary": "test-only"}
    request_relative, result_relative = "jobs/one/request.json", "jobs/one/result.json"
    write(native / request_relative, request)
    artifact = {"status": "COMPLETE", "request_sha256": sha(native / request_relative), "result": result,
                "identity_before": identity, "identity_after": identity, "runtime_s": 0.0}
    write(native / result_relative, artifact)
    manifest = {
        "schema": "coilem.benchmark_run/v1", "status": "COMPLETE", "smoke": False, "identity": identity,
        "reference_mode": "NATIVE_ONLY", "reference_commit": None,
        "selection": {"case_ids": [case["id"]], "no_reference": True, "bundle_sha256": None, "spec_sha256": sha(SPEC)},
        "jobs": [{"case_id": case["id"], "phase": case["phase"], "stage": "native", "status": "COMPLETE",
                  "request": request_relative, "result": result_relative, "request_sha256": sha(native / request_relative),
                  "result_sha256": sha(native / result_relative)}],
    }
    write(native / "run_manifest.json", manifest)
    bundle = tmp_path / "bundle"
    record = {"case_id": case["id"], "phase": case["phase"], "input_sha256": case["jobs"][0]["input_sha256"],
              "convention": spec["convention"], "normalized": True, "reference_commit": identity["commit"], "result": result}
    write(bundle / "one.json", record)
    write(bundle / "manifest.json", {
        "schema": "coilem.frozen_reference_bundle/v1", "protocol_version": spec["protocol_version"],
        "convention": spec["convention"], "normalized": True, "material_contract": spec["material_contract"],
        "reference_commit": identity["commit"], "validation_status": "TEST_ONLY",
        "records": {case["id"]: {"file": "one.json", "sha256": sha(bundle / "one.json"), "input_sha256": record["input_sha256"]}},
    })
    return argparse.Namespace(source_root=ROOT, expected_commit=identity["commit"], native_out=native,
                              reference_bundle=bundle, out_dir=tmp_path / "comparison", suite=SPEC.relative_to(ROOT), pdf=False)


def test_join_renders_without_solves_or_mutating_evidence(tmp_path, monkeypatch):
    args = synthetic_run(tmp_path)
    monkeypatch.setattr(late, "require_source", lambda *a: None)
    # The production path never uses execute, which owns native build/launch.
    monkeypatch.setattr(cli, "execute", lambda *a: pytest.fail("A report-only join launched a benchmark"))
    hashes = {p: sha(p) for p in args.native_out.rglob("*.json")}
    assert late.compare(args) == 0
    assert all(sha(p) == before for p, before in hashes.items())
    provenance = read(args.out_dir / "comparison_manifest.json")["comparison"]
    assert provenance["field_solves_executed"] == 0
    assert provenance["native_manifest_mutated"] is False
    assert (args.out_dir / "report/coilem_benchmark_report.html").is_file()


def test_join_rejects_tampered_native_result_and_stale_reference(tmp_path, monkeypatch):
    args = synthetic_run(tmp_path)
    monkeypatch.setattr(late, "require_source", lambda *a: None)
    reference = args.reference_bundle / "manifest.json"
    saved = read(reference)
    changed = copy.deepcopy(saved)
    changed["reference_commit"] = "old"
    write(reference, changed)
    with pytest.raises(ValueError, match="identity mismatch|same measured source"):
        late.compare(args)
    write(reference, saved)
    result = args.native_out / "jobs/one/result.json"
    modified = read(result)
    modified["result"]["summary"]["avg_torque_Nm"] = 999.0
    write(result, modified)
    with pytest.raises(ValueError, match="changed completed native"):
        late.compare(args)


def test_six_step_join_preserves_fixed_axis_failures_and_reports_new_frame(tmp_path, monkeypatch):
    args = synthetic_run(tmp_path)
    spec = read(SPEC)
    case = next(c for c in spec["cases"] if c["id"] == "spm_8p12s_reference")
    configs, protocols, golden = cli.inputs(spec, [case])
    protocol = protocols[case["id"]]
    manifest = read(args.native_out / "run_manifest.json")
    manifest["selection"]["case_ids"] = [case["id"]]
    manifest["jobs"] = []
    reference = None
    for registered in case["jobs"]:
        stage = registered["stage"]
        config = configs[case["id"], stage]
        grid_key = {"native-fine": "native_fine_convergence", "analytical": "low_current_power_discriminator"}.get(stage, "cross_lane_product")
        grid = protocol["matrix"][grid_key]
        angles = [i * grid["electrical_angle_step_deg"] for i in range(grid["sample_count"])]
        current = protocol["excitation"]["analytical_current_A" if stage == "analytical" else "product_current_A"]
        currents = [[v * current / golden["plateau_current_A"] for v in golden["sector_table_A"][int(((a + 30) % 360) // 60)]]
                    for a in angles]
        torque = 2.0 if stage == "analytical" else 20.0
        omega = protocol["matrix"]["low_current_power_discriminator"]["rated_speed_rpm"] * 2 * math.pi / 60
        factor = omega * torque / (2 * current**2)
        result = {
            "summary": {"avg_torque_Nm": torque, "back_emf_fundamental_V": 5.0},
            "torque_waveform": {"electrical_angle_deg": angles, "torque_Nm": [torque] * len(angles)},
            "phase_current_waveform": {"electrical_angle_deg": angles,
                                       **{f"phase_{p}_A": [row[i] for row in currents] for i, p in enumerate("abc")}},
            "back_emf_waveform": {"electrical_angle_deg": angles,
                                  **{f"phase_{p}_V": [row[i] * factor for row in currents] for i, p in enumerate("abc")}},
            "solve_metadata": {"solver_name": "magneto2d-test-only", "mesh_source": "native", "mesh_density": "normal",
                               "loaded_cycle_complete": True, "torque_method": "weighted_stress", "solve_time_s": 0.0},
        }
        request_path = f"jobs/{stage}/request.json"
        result_path = f"jobs/{stage}/result.json"
        write(args.native_out / request_path, {"config": config, "config_sha256": canonical(config),
                                              "identity": manifest["identity"], "binary": "test-only"})
        write(args.native_out / result_path, {"status": "COMPLETE", "request_sha256": sha(args.native_out / request_path),
                                             "result": result, "identity_before": manifest["identity"],
                                             "identity_after": manifest["identity"], "runtime_s": 0.0})
        manifest["jobs"].append({"case_id": case["id"], "phase": "D", "stage": stage, "status": "COMPLETE",
                                 "request": request_path, "result": result_path, "request_sha256": sha(args.native_out / request_path),
                                 "result_sha256": sha(args.native_out / result_path)})
        if stage == "native-standard":
            reference = cli.compact(result)
            reference["solver_name"] = "femm-test-only"
    write(args.native_out / "run_manifest.json", manifest)
    bundle_manifest = read(args.reference_bundle / "manifest.json")
    write(args.reference_bundle / "one.json", {"case_id": case["id"], "phase": "D", "input_sha256": case["jobs"][0]["input_sha256"],
                                              "convention": spec["convention"], "normalized": True,
                                              "reference_commit": args.expected_commit, "protocol_sha256": case["protocol_sha256"],
                                              "result": reference})
    bundle_manifest["records"] = {case["id"]: {"file": "one.json", "sha256": sha(args.reference_bundle / "one.json"),
                                              "input_sha256": case["jobs"][0]["input_sha256"]}}
    write(args.reference_bundle / "manifest.json", bundle_manifest)
    monkeypatch.setattr(late, "require_source", lambda *a: None)
    assert late.compare(args) == 1
    row = read(args.out_dir / "report/benchmark_summary.json")["rows"][0]
    golden_failures = [g for g in row["evaluation"]["gates"] if g["id"].endswith("golden_current_sequence")]
    assert len(golden_failures) == 4 and all(g["status"] == "FAIL" for g in golden_failures)
    diagnostics = read(args.out_dir / "winding_axis_diagnostics.json")[case["id"]]
    assert len(diagnostics) == 4 and all(d["pr100_winding_axis_sequence"] == "PASS" for d in diagnostics.values())
