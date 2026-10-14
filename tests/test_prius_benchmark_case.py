"""ORNL 2004 Prius as a measured benchmark case (#82): suite 1.2.0, corrected fixture, hardware correlation.

Measurements here are synthetic; no Prius prediction is computed.
"""

from __future__ import annotations

import json
import math
from argparse import Namespace
from pathlib import Path

import pytest

from tools.benchmark_suite.contract import ROOT, SPEC, canonical, read, sha, write
from tools.benchmark_suite.hardware import no_load_back_emf_line_to_line
from tools.benchmark_suite.references import load_suite

SUITE = ROOT / "benchmarks/abcd-v1.2/benchmark_spec.json"
FOLDER = ROOT / "docs/hardware-validation/ornl-prius-2004"
CASE_ID = "ornl_prius_2004_ipm"
TARGETS = read(FOLDER / "target-back-emf.json")


def prius_case():
    return next(c for c in load_suite(SUITE)["cases"] if c["id"] == CASE_ID)


def prius_config():
    return read(ROOT / prius_case()["jobs"][0]["fixture"])


def synthetic_result(config, phase_peak_V=100.0):
    """A clean sinusoidal no-load Back-EMF and a flat torque on the registered grids."""

    params = config["solve_params"]
    torque_angles = [i * params["rotor_step_deg"] for i in range(round(params["rotor_sweep_range_deg"] / params["rotor_step_deg"]) + 1)]
    emf_angles = [i * params["rotor_step_deg"] for i in range(round(360 / params["rotor_step_deg"]))]
    phases = {
        f"phase_{name}_V": [phase_peak_V * math.sin(math.radians(a - shift)) for a in emf_angles]
        for name, shift in (("a", 0), ("b", 120), ("c", 240))
    }
    return {
        "summary": {"avg_torque_Nm": 1.0, "back_emf_fundamental_V": phase_peak_V},
        "torque_waveform": {"electrical_angle_deg": torque_angles, "torque_Nm": [1.0] * len(torque_angles)},
        "back_emf_waveform": {"electrical_angle_deg": emf_angles, **phases},
        "solve_metadata": {"solver_name": "magneto2d-test", "mesh_source": "native", "torque_method": "weighted_stress"},
    }


def test_suite_1_2_changes_only_the_prius_request():
    previous, current = load_suite(SPEC), load_suite(SUITE)
    assert (previous["protocol_version"], current["protocol_version"]) == ("1.1.0", "1.2.0")
    assert current["golden"] == previous["golden"] and current["convention"] == previous["convention"]
    before = {c["id"]: c for c in previous["cases"]}
    changed = [c["id"] for c in current["cases"] if c != before[c["id"]]]
    assert changed == [CASE_ID] and len(current["cases"]) == len(previous["cases"])
    case = prius_case()
    job = case["jobs"][0]
    assert job["fixture_sha256"] == sha(ROOT / job["fixture"])
    assert job["input_sha256"] == canonical(read(ROOT / job["fixture"]))
    assert case["experimental_rotor"] is True
    assert case["hardware_reference"]["sha256"] == sha(ROOT / case["hardware_reference"]["file"])
    # The material contract gains only the ORNL magnet, with the catalog's solver inputs.
    from backend.public_material_catalog import MAGNET_SOLVER_INPUTS

    magnets = current["material_contract"]["magnets"]
    assert set(magnets) - set(previous["material_contract"]["magnets"]) == {"ORNL_Prius_2004_NdFeB"}
    assert MAGNET_SOLVER_INPUTS["ORNL_Prius_2004_NdFeB"][1:3] == (magnets["ORNL_Prius_2004_NdFeB"]["Br_T"], magnets["ORNL_Prius_2004_NdFeB"]["mu_r"])


def test_default_suite_is_unchanged():
    from tools.benchmark_suite import PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS

    assert SPEC.relative_to(ROOT).as_posix() == "benchmarks/abcd-v1.1/benchmark_spec.json"
    assert PROTOCOL_VERSION == "1.1.0" and "1.2.0" in SUPPORTED_PROTOCOL_VERSIONS


def test_corrected_fixture_uses_the_ornl_mappings():
    config = prius_config()
    rotor = read(FOLDER / "holem50-mapping.json")["recommended"]["rotor"]
    stator_mapping = read(FOLDER / "stator-slot-mapping.json")
    stator = stator_mapping["candidates"][stator_mapping["recommended"]]["stator"]
    assert {k: config["rotor"][k] for k in rotor} == rotor
    assert {k: config["stator"][k] for k in stator} == stator
    assert config["materials"]["magnet_grade"] == "ORNL_Prius_2004_NdFeB"
    assert stator_mapping["candidates"][stator_mapping["recommended"]]["fit"]["max_mm"] < 0.1
    # Everything else is the registered 1.1.0 request.
    previous = read(ROOT / "benchmarks/main-20261009-bad71d9/fixtures/ornl_prius_2004_ipm.json")
    for section in ("solve_params", "solve_options", "winding"):
        assert config[section] == previous[section]


def test_corrected_fixture_builds_valid_geometry_on_the_experimental_path():
    from backend.geometry import validate_geometry
    from backend.geometry_ir import build_geometry_ir, validate_geometry_ir
    from backend.public_policy import PublicConfigError, parse_public_solve_request

    with pytest.raises(PublicConfigError, match="flat-buried and V-shape IPM only"):
        parse_public_solve_request(prius_config())
    config, _, solver = parse_public_solve_request(prius_config(), allow_experimental_rotors=True)
    assert solver == "magneto2d"
    assert validate_geometry(config) == []
    report = validate_geometry_ir(build_geometry_ir(config))
    assert report.issues == ()
    area = report.region_area_by_kind_mm2
    stator_annulus = math.pi * ((config.stator.OD_mm / 2) ** 2 - (config.stator.ID_mm / 2) ** 2)
    assert sum(area[k] for k in ("StatorYoke", "StatorTooth", "SlotWinding")) == pytest.approx(stator_annulus, rel=1e-3)
    rotor_disc = math.pi * (config.rotor.OD_mm / 2) ** 2
    assert sum(area[k] for k in ("RotorCore", "Shaft", "MagnetPocketAir", "Magnet")) == pytest.approx(rotor_disc, rel=1e-3)


def test_line_to_line_conversion_and_speed_scaling():
    config = prius_config()
    comparison = no_load_back_emf_line_to_line(synthetic_result(config), config, TARGETS)
    assert comparison["status"] == "NO_VERDICT" and "no pass/fail" in comparison["label"]
    solved = config["solve_params"]["rated_speed_rpm"]
    for row, target in zip(comparison["rows"], TARGETS["rows"], strict=True):
        scale = target["motor_shaft_rpm"] / solved
        # A 100 V phase-peak sine gives sqrt(3) x 100 V line-to-line peak; RMS is peak / sqrt(2).
        assert row["predicted_ll_peak_V"] == pytest.approx(math.sqrt(3) * 100 * scale)
        assert row["predicted_ll_rms_V"] == pytest.approx(math.sqrt(3) * 100 / math.sqrt(2) * scale)
        assert row["rms_error_pct"] == pytest.approx((row["predicted_ll_rms_V"] / target["back_emf_ll_rms_V"] - 1) * 100)
    assert len(comparison["rows"]) == 12
    no_emf = json.loads(json.dumps(config))
    no_emf["solve_options"]["back_emf"] = False
    with pytest.raises(ValueError, match="no no-load Back-EMF"):
        no_load_back_emf_line_to_line(synthetic_result(config), no_emf, TARGETS)


@pytest.mark.parametrize("flagged", [True, False])
def test_worker_opts_in_only_for_registered_experimental_requests(tmp_path, monkeypatch, flagged):
    from backend import solver
    from tools.benchmark_suite.contract import identity
    from tools.benchmark_suite.worker import measure

    config = prius_config()

    class RecordedSolver:
        def __init__(self, *, launch_surface):
            pass

        def solve(self, parsed, **kwargs):
            class Measured:
                def model_dump(self, **kwargs):
                    return synthetic_result(config)

            return Measured()

    monkeypatch.setattr(solver, "Magneto2DSolver", RecordedSolver)
    binary = ROOT / "solvers/magneto2d/Cargo.toml"
    runtime = identity(binary, protocol_version="1.2.0")
    request = {"identity": runtime, "binary": binary.relative_to(ROOT).as_posix(), "config": config, "config_sha256": canonical(config)}
    if flagged:
        request["experimental_rotor"] = True
    write(tmp_path / "request.json", request)
    code = measure(Namespace(request=tmp_path / "request.json", output=tmp_path / "result.json"))
    measured = read(tmp_path / "result.json")
    assert (code, measured["status"]) == ((0, "COMPLETE") if flagged else (2, "ERROR"))
    if not flagged:
        assert "flat-buried and V-shape IPM only" in measured["error"]


@pytest.mark.parametrize("smoke", [False, True])
def test_runner_reports_the_hardware_correlation_without_a_verdict(tmp_path, monkeypatch, smoke):
    from backend import magneto2d_adapter
    from tools.benchmark_suite import cli

    runtime = {"commit": "test-candidate", "dirty": False, "harness_version": "1.3.0", "protocol_version": "1.2.0"}
    monkeypatch.setattr(cli, "identity", lambda _, **kwargs: runtime)
    monkeypatch.setattr(magneto2d_adapter, "ensure_magneto2d_binary", lambda: ROOT / "solvers/magneto2d/Cargo.toml")
    requests = []

    class RecordedWorker:
        pid = 12345

        def __init__(self, command, **kwargs):
            request_path = Path(command[command.index("--request") + 1])
            output_path = Path(command[command.index("--output") + 1])
            request = read(request_path)
            requests.append(request)
            write(output_path, {"status": "COMPLETE", "request_sha256": sha(request_path), "identity_before": request["identity"],
                                "identity_after": request["identity"], "result": synthetic_result(request["config"])})

        def wait(self):
            return 0

    monkeypatch.setattr(cli.subprocess, "Popen", RecordedWorker)
    args = Namespace(phases=["C"], case=[CASE_ID], list=False, out_dir=tmp_path, no_reference=True, smoke=smoke, suite=SUITE,
                     reference_bundle=ROOT / "benchmarks/reference-baselines/ipm-high-output-v1", report_only=False,
                     allow_dirty=False, resume=False, pdf=not smoke)
    cli.execute(args)
    assert len(requests) == 1 and requests[0]["experimental_rotor"] is True
    manifest = read(tmp_path / "run_manifest.json")
    assert manifest["jobs"][0]["status"] == "COMPLETE"
    summary = read(tmp_path / "report/benchmark_summary.json")
    row = summary["rows"][0]
    assert row["experimental_rotor"] is True
    html_report = (tmp_path / "report/coilem_benchmark_report.html").read_text(encoding="utf-8")
    assert "Experimental rotor path (#70)" in html_report
    if smoke:
        # A reduced grid never feeds the hardware correlation.
        assert "hardware_comparison" not in row and row["status"] == "NON_GATING_SMOKE"
        return
    assert row["status"] == "NOT_COMPARED"  # no 1.2.0 FEMM bundle yet
    comparison = row["hardware_comparison"]
    assert comparison["status"] == "NO_VERDICT" and len(comparison["rows"]) == 12
    assert "gates" in row["evaluation"] and "hardware_comparison" not in row["evaluation"]
    assert "Exploratory hardware correlation; no pass/fail" in html_report and "ORNL RMS" in html_report
    markdown = (tmp_path / "report/benchmark_report.md").read_text(encoding="utf-8")
    assert "| Speed (rpm) | Measured LL RMS (V) |" in markdown
    assert (tmp_path / "report/coilem_benchmark_report.pdf").stat().st_size > 0
