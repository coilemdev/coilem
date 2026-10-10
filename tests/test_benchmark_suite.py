"""Regression coverage for frozen-reference reuse and unchanged numerical gates."""

import copy
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tools.benchmark_suite.cli import inputs, verify_artifact
from tools.benchmark_suite.contract import DEFAULT_BUNDLE, ROOT, SPEC, canonical, read, run_lock, sha, write
from tools.benchmark_suite.metrics import evaluate_abc, evaluate_bldc
from tools.benchmark_suite.references import load_bundle, load_suite
from tools.benchmark_suite.report import build, phase_display_status

SPECIFICATION = load_suite(SPEC)
CONFIGS, PROTOCOLS, GOLDEN = inputs(SPECIFICATION, SPECIFICATION["cases"])
_, REFERENCES, _ = load_bundle(DEFAULT_BUNDLE, SPECIFICATION)
HISTORICAL = ROOT / "benchmarks/main-20261009-bad71d9/rows"


def historical(case):
    prefix = "bldc_" if case["phase"] == "D" else ""
    return read(HISTORICAL / (prefix + case["id"] + ".json"))


@pytest.mark.parametrize("case", SPECIFICATION["cases"], ids=lambda c: c["id"])
def test_historical_verdicts_and_gates(case):
    recorded = historical(case)
    if case["phase"] == "D":
        raw = {k: {"result": v} for k, v in recorded["measurements"].items()}
        evaluated = evaluate_bldc(PROTOCOLS[case["id"]], raw, GOLDEN)
        assert len(evaluated["gates"]) == 14
        assert evaluated["gates"] == recorded["evaluation"]["gates"]
        assert evaluated["results"] == recorded["evaluation"]["results"]
        assert evaluated["status"] == "PASS"
    elif not recorded.get("candidate"):
        from backend.public_policy import PublicConfigError, parse_public_solve_request

        with pytest.raises(PublicConfigError):
            parse_public_solve_request(CONFIGS[case["id"], "native"])
        assert case["id"] not in REFERENCES
    else:
        evaluated = evaluate_abc(recorded["candidate"], REFERENCES[case["id"]], CONFIGS[case["id"], "native"])
        assert evaluated["gates"] == recorded["comparison"]["gates"]
        assert evaluated["status"] == recorded["comparison"]["status"]
        for name in ("average_delta_pct", "bemf_fundamental_delta_pct", "bemf_peak_delta_pct", "torque_waveform", "bemf_waveform"):
            assert evaluated[name] == recorded["comparison"][name]


def test_frozen_bundle_matches_all_inputs():
    manifest, refs, digest = load_bundle(DEFAULT_BUNDLE, SPECIFICATION)
    assert len(refs) == 29
    assert len(digest) == 64
    assert manifest["reference_commit"] != manifest["origin_candidate_commit"]
    assert Counter(c["phase"] for c in SPECIFICATION["cases"]) == {"A": 10, "B": 12, "C": 5, "D": 3}


@pytest.mark.parametrize("change", ["material", "convention", "normalized", "input", "hash", "protocol"])
def test_reference_contract_rejects_mismatches(tmp_path, change):
    import shutil

    bundle = tmp_path / "bundle"
    shutil.copytree(DEFAULT_BUNDLE, bundle)
    manifest = read(bundle / "manifest.json")
    if change == "material":
        manifest["material_contract"]["magnets"]["N42"]["Br_T"] = 1.2
    elif change == "convention":
        manifest["convention"] = "unmapped-ccw"
    elif change == "normalized":
        manifest["normalized"] = False
    elif change == "protocol":
        manifest["protocol_version"] = "2.0.0"
    else:
        entry = next(iter(manifest["records"].values()))
        entry["input_sha256" if change == "input" else "sha256"] = "0" * 64
    write(bundle / "manifest.json", manifest)
    with pytest.raises(ValueError):
        load_bundle(bundle, SPECIFICATION)


def test_missing_reference_never_passes():
    case = next(c for c in SPECIFICATION["cases"] if c["phase"] == "A")
    result = historical(case)["candidate"]
    assert evaluate_abc(result, None, CONFIGS[case["id"], "native"])["status"] == "NOT_COMPARED"
    case = next(c for c in SPECIFICATION["cases"] if c["phase"] == "D")
    raw = {k: {"result": v} for k, v in historical(case)["measurements"].items() if k != "femm-standard"}
    evaluation = evaluate_bldc(PROTOCOLS[case["id"]], raw, GOLDEN)
    assert evaluation["status"] == "NOT_COMPARED"
    assert Counter(g["status"] for g in evaluation["gates"]) == {"PASS": 9, "NOT_EVALUATED": 5}
    del raw["analytical"]
    assert evaluate_bldc(PROTOCOLS[case["id"]], raw, GOLDEN)["status"] == "INCOMPLETE"


@pytest.mark.parametrize("invalid", ["nan", "missing", "wrong_grid", "wrong_solver", "golden"])
def test_invalid_bldc_evidence_is_not_a_pass(invalid):
    case = next(c for c in SPECIFICATION["cases"] if c["phase"] == "D")
    raw = {k: {"result": copy.deepcopy(v)} for k, v in historical(case)["measurements"].items()}
    result = raw["native-standard"]["result"]
    if invalid == "golden":
        currents = result["phase_current_waveform"]
        currents["phase_a_A"], currents["phase_b_A"] = currents["phase_b_A"], currents["phase_a_A"]
        assert evaluate_bldc(PROTOCOLS[case["id"]], raw, GOLDEN)["status"] == "FAIL"
        return
    if invalid == "nan":
        result["torque_Nm"][0] = float("nan")
    elif invalid == "missing":
        result["torque_Nm"].pop()
    elif invalid == "wrong_grid":
        result["electrical_angle_deg"][1] += 0.01
    else:
        result["solver_name"] = "unregistered"
    with pytest.raises(ValueError):
        evaluate_bldc(PROTOCOLS[case["id"]], raw, GOLDEN)


def test_native_only_failure_is_visible():
    case = next(c for c in SPECIFICATION["cases"] if c["phase"] == "D")
    raw = {k: {"result": copy.deepcopy(v)} for k, v in historical(case)["measurements"].items() if k != "femm-standard"}
    raw["analytical"]["result"]["torque_Nm"] = [-v for v in raw["analytical"]["result"]["torque_Nm"]]
    assert evaluate_bldc(PROTOCOLS[case["id"]], raw, GOLDEN)["status"] == "FAIL"


def test_resume_rejects_changed_evidence_or_identity(tmp_path):
    runtime = {"commit": "candidate"}
    request = {"identity": runtime, "config": {"speed": 3000}}
    write(tmp_path / "request.json", request)
    data = {"status": "COMPLETE", "request_sha256": sha(tmp_path / "request.json"), "identity_before": runtime, "identity_after": runtime}
    write(tmp_path / "result.json", data)
    job = {
        "request": "request.json",
        "request_sha256": sha(tmp_path / "request.json"),
        "result": "result.json",
        "result_sha256": sha(tmp_path / "result.json"),
    }
    assert verify_artifact(tmp_path, job, runtime)["status"] == "COMPLETE"
    with pytest.raises(ValueError):
        verify_artifact(tmp_path, job, {"commit": "new candidate"})
    write(tmp_path / "result.json", {**data, "extra": "tampered"})
    with pytest.raises(ValueError):
        verify_artifact(tmp_path, job, runtime)


def test_run_lock_excludes_duplicate_process_and_releases(tmp_path):
    code = "from pathlib import Path; from tools.benchmark_suite.contract import run_lock;\nwith run_lock(Path(__import__('sys').argv[1])): pass"
    with run_lock(tmp_path):
        result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode != 0
        assert "already owns" in result.stderr
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_help_does_not_import_a_reference_or_native_backend():
    code = (
        "import sys; from tools.benchmark_suite.cli import main; sys.argv=['benchmark','--list']; main(); "
        "assert not any(n.startswith('backend') for n in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_smoke_execution_error_remains_incomplete(tmp_path):
    manifest = {
        "identity": {"harness_version": "1.0.0", "protocol_version": "1.0.0", "commit": "candidate"},
        "smoke": True,
        "reference_mode": "NONE_SMOKE",
    }
    case = SPECIFICATION["cases"][0]
    rows = [
        {
            "id": case["id"],
            "phase": case["phase"],
            "fixture": case["jobs"][0]["fixture"],
            "status": "ERROR",
            "evaluation": {"status": "ERROR", "gates": []},
            "measurements": {},
        }
    ]
    assert build(tmp_path, manifest, rows) == "INCOMPLETE"
    assert 'class="ERROR"' in (tmp_path / "report/coilem_benchmark_report.html").read_text()


@pytest.mark.parametrize(
    "counts,expected",
    [
        ({"PASS": 10}, "PASS"),
        ({"PASS": 10, "FAIL": 2}, "YELLOW"),
        ({"PASS": 4, "UNSUPPORTED": 1}, "YELLOW"),
        ({"PASS": 1, "FAIL": 1}, "YELLOW"),
        ({"PASS": 1, "FAIL": 2}, "FAIL"),
        ({"INCOMPLETE": 3}, "YELLOW"),
    ],
)
def test_phase_summary_color_threshold(counts, expected):
    assert phase_display_status(counts) == expected


def test_report_orders_phases_and_retains_hashed_input_copies(tmp_path):
    manifest = {
        "identity": {"harness_version": "1.0.0", "protocol_version": "1.0.0", "commit": "candidate"},
        "smoke": False,
        "reference_mode": "FROZEN_REFERENCE",
    }
    rows = []
    for phase in ("D", "A"):
        case = next(c for c in SPECIFICATION["cases"] if c["phase"] == phase)
        rows.append(
            {
                "id": case["id"],
                "phase": phase,
                "fixture": case["jobs"][0]["fixture"],
                "status": "UNSUPPORTED",
                "evaluation": {"status": "UNSUPPORTED", "gates": []},
                "measurements": {},
                "configurations": {case["jobs"][0]["stage"]: CONFIGS[case["id"], case["jobs"][0]["stage"]]},
            }
        )
    assert build(tmp_path, manifest, rows) == "PASS_WITH_UNSUPPORTED"
    summary = read(tmp_path / "report/benchmark_summary.json")
    assert [r["phase"] for r in summary["rows"]] == ["A", "D"]
    artifacts = read(tmp_path / "report/artifact_manifest.json")
    for row in summary["rows"]:
        for stage, name in row["fixture_files"].items():
            fixture = tmp_path / "report" / name
            assert artifacts[name] == sha(fixture)
            assert read(fixture) == row["configurations"][stage]


def test_canonical_request_hash_includes_speed_and_geometry():
    config = copy.deepcopy(next(iter(CONFIGS.values())))
    original = canonical(config)
    config["solve_params"]["rated_speed_rpm"] += 1
    assert canonical(config) != original
    config = copy.deepcopy(next(iter(CONFIGS.values())))
    config["rotor"]["OD_mm"] += 0.1
    assert canonical(config) != original


def test_provenance_survives_native_environment_path_isolation(monkeypatch):
    from tools.benchmark_suite.contract import git

    before = git("rev-parse", "HEAD")
    monkeypatch.setenv("PATH", "")
    assert git("rev-parse", "HEAD") == before


@pytest.mark.parametrize("phase", ["A", "D"])
def test_orchestrator_resume_and_report_only_preserve_completed_jobs(tmp_path, monkeypatch, phase):
    from argparse import Namespace

    from backend import magneto2d_adapter
    from tools.benchmark_suite import cli

    case = next(c for c in SPECIFICATION["cases"] if c["phase"] == phase)
    recorded = historical(case)
    runtime = {"commit": "test-candidate", "dirty": False, "harness_version": "1.0.0", "protocol_version": "1.0.0"}
    monkeypatch.setattr(cli, "identity", lambda _: runtime)
    monkeypatch.setattr(magneto2d_adapter, "ensure_magneto2d_binary", lambda: ROOT / "solvers/magneto2d/Cargo.toml")
    launches = []

    class RecordedWorker:
        pid = 12345

        def __init__(self, command, **kwargs):
            launches.append(command)
            request_path = Path(command[command.index("--request") + 1])
            output_path = Path(command[command.index("--output") + 1])
            request = read(request_path)
            if phase == "A":
                result = recorded["candidate"]
            else:
                result = copy.deepcopy(recorded["measurements"][output_path.parent.name])
                result["torque_waveform"] = {k: result[k] for k in ("electrical_angle_deg", "torque_Nm")}
                result["solve_metadata"] = {
                    k: result[k] for k in ("solver_name", "mesh_density", "mesh_source", "torque_method", "loaded_cycle_complete")
                }
            write(
                output_path,
                {
                    "status": "COMPLETE",
                    "request_sha256": sha(request_path),
                    "identity_before": request["identity"],
                    "identity_after": request["identity"],
                    "result": result,
                },
            )

        def wait(self):
            return 0

    monkeypatch.setattr(cli.subprocess, "Popen", RecordedWorker)
    args = Namespace(
        phases=[phase],
        case=[case["id"]],
        list=False,
        out_dir=tmp_path,
        no_reference=False,
        smoke=False,
        reference_bundle=DEFAULT_BUNDLE,
        report_only=False,
        allow_dirty=False,
        resume=False,
        pdf=False,
    )
    assert cli.execute(args) == 0
    assert len(launches) == len(case["jobs"])
    manifest = read(tmp_path / "run_manifest.json")
    assert manifest["status"] == "COMPLETE"
    before = [j["result_sha256"] for j in manifest["jobs"]]
    args.resume = True
    assert cli.execute(args) == 0
    assert len(launches) == len(case["jobs"])
    assert before == [j["result_sha256"] for j in read(tmp_path / "run_manifest.json")["jobs"]]
    args.resume, args.report_only = False, True
    monkeypatch.setattr(magneto2d_adapter, "ensure_magneto2d_binary", lambda: pytest.fail("report-only must not build"))
    assert cli.execute(args) == 0
    args.resume, args.report_only = True, False
    monkeypatch.setattr(magneto2d_adapter, "ensure_magneto2d_binary", lambda: ROOT / "solvers/magneto2d/Cargo.toml")
    monkeypatch.setattr(cli, "identity", lambda _: {**runtime, "commit": "changed"})
    with pytest.raises(ValueError, match="Resume refused"):
        cli.execute(args)
