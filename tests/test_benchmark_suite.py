"""Regression coverage for frozen-reference reuse and unchanged numerical gates."""

import copy
import csv
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from backend.benchmark_suite.cli import inputs, verify_artifact
from backend.benchmark_suite.contract import ROOT, SPEC, canonical, read, run_lock, sha, write
from backend.benchmark_suite.metrics import energy_balance_ratio, evaluate_abc, evaluate_bldc
from backend.benchmark_suite.references import load_bundle, load_suite
from backend.benchmark_suite.report import build, phase_display_status

HISTORICAL_SPEC = ROOT / "benchmarks/abcd-v1/benchmark_spec.json"
HISTORICAL_BUNDLE = ROOT / "benchmarks/reference-baselines/main-bad71d9"
SPECIFICATION = load_suite(HISTORICAL_SPEC)
CONFIGS, PROTOCOLS, GOLDEN = inputs(SPECIFICATION, SPECIFICATION["cases"])
_, REFERENCES, _ = load_bundle(HISTORICAL_BUNDLE, SPECIFICATION)
HISTORICAL = ROOT / "benchmarks/main-20261009-bad71d9/rows"


def historical(case):
    prefix = "bldc_" if case["phase"] == "D" else ""
    return read(HISTORICAL / (prefix + case["id"] + ".json"))


def assert_same_metrics(actual, expected):
    """Allow platform rounding in derived metrics, never in verdicts or limits."""
    if isinstance(expected, float):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_same_metrics(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for value, stored in zip(actual, expected, strict=True):
            assert_same_metrics(value, stored)
    else:
        assert actual == expected


@pytest.mark.parametrize("case", SPECIFICATION["cases"], ids=lambda c: c["id"])
def test_historical_verdicts_and_gates(case):
    recorded = historical(case)
    if case["phase"] == "D":
        raw = {k: {"result": v} for k, v in recorded["measurements"].items()}
        evaluated = evaluate_bldc(PROTOCOLS[case["id"]], raw, GOLDEN)
        assert len(evaluated["gates"]) == 14
        for gate, stored in zip(evaluated["gates"], recorded["evaluation"]["gates"], strict=True):
            assert {k: v for k, v in gate.items() if k != "value"} == {k: v for k, v in stored.items() if k != "value"}
            assert_same_metrics(gate["value"], stored["value"])
        assert_same_metrics(evaluated["results"], recorded["evaluation"]["results"])
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
            assert_same_metrics(evaluated[name], recorded["comparison"][name])


def test_energy_balance_exposes_the_halved_flux_linkage_credit():
    # The v1.1 record predates #80: single-layer concentrated windings show about
    # twice the torque their own back-EMF and current imply; distributed windings
    # balance. Native and FEMM shared the credit, so the parity gates passed.
    by_id = {case["id"]: case for case in SPECIFICATION["cases"]}
    for case_id, low, high in (
        ("spm_4p12s_simple__baseline", 1.95, 2.05),
        ("spm_8p48s_distributed_femm_validation", 0.9, 1.05),
    ):
        recorded = historical(by_id[case_id])
        config = CONFIGS[case_id, "native"]
        assert low < energy_balance_ratio(recorded["candidate"], config) < high
        assert low < energy_balance_ratio(REFERENCES[case_id], config) < high
    six_step = copy.deepcopy(CONFIGS["spm_4p12s_simple__baseline", "native"])
    six_step["solve_params"]["excitation_mode"] = "ideal_six_step_120"
    assert energy_balance_ratio(recorded["candidate"], six_step) is None


def test_frozen_bundle_matches_all_inputs():
    manifest, refs, digest = load_bundle(HISTORICAL_BUNDLE, SPECIFICATION)
    assert len(refs) == 29
    assert len(digest) == 64
    assert manifest["reference_commit"] != manifest["origin_candidate_commit"]
    assert Counter(c["phase"] for c in SPECIFICATION["cases"]) == {"A": 10, "B": 12, "C": 5, "D": 3}


@pytest.mark.parametrize("change", ["material", "convention", "normalized", "input", "hash", "protocol"])
def test_reference_contract_rejects_mismatches(tmp_path, change):
    import shutil

    bundle = tmp_path / "bundle"
    shutil.copytree(HISTORICAL_BUNDLE, bundle)
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
    code = "from pathlib import Path; from backend.benchmark_suite.contract import run_lock;\nwith run_lock(Path(__import__('sys').argv[1])): pass"
    with run_lock(tmp_path):
        result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode != 0
        assert "already owns" in result.stderr
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_help_does_not_import_a_reference_or_native_backend():
    # The harness lives in the backend package (#71); listing still loads no solver or policy module.
    code = (
        "import sys; from backend.benchmark_suite.cli import main; sys.argv=['benchmark','--list']; main(); "
        "loaded = [n for n in sys.modules if n.startswith('backend.') and not n.startswith('backend.benchmark_suite')]; "
        "assert loaded == ['backend.resources'], loaded"
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


def test_pdf_report_links_fixtures_relative_to_the_report(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from tools.verify_snapshot import pdf_hygiene_failures

    case = next(c for c in SPECIFICATION["cases"] if c["phase"] == "A")
    stage = case["jobs"][0]["stage"]
    manifest = {
        "identity": {"harness_version": "1.0.0", "protocol_version": "1.0.0", "commit": "candidate"},
        "smoke": False,
        "reference_mode": "FROZEN_REFERENCE",
    }
    row = {
        "id": case["id"],
        "phase": "A",
        "fixture": case["jobs"][0]["fixture"],
        "status": "UNSUPPORTED",
        "evaluation": {"status": "UNSUPPORTED", "gates": []},
        "measurements": {},
        "configurations": {stage: CONFIGS[case["id"], stage]},
    }
    build(tmp_path, manifest, [row], pdf=True)
    pdf = tmp_path / "report/coilem_benchmark_report.pdf"
    links = [
        annotation.get_object()["/A"]["/URI"]
        for page in pypdf.PdfReader(pdf).pages
        if "/Annots" in page
        for annotation in page["/Annots"]
    ]
    assert links == [f"fixtures/{case['id']}__{stage}.json"]
    assert (pdf.parent / links[0]).is_file()
    assert pdf_hygiene_failures("coilem_benchmark_report.pdf", pdf) == []


def test_prius_planned_label_preserves_policy_rejection_and_numerical_status(tmp_path):
    from backend.benchmark_suite.report import display_outcome
    from backend.magneto2d_adapter import get_magneto2d_winding_support_error
    from backend.models import MotorConfig
    from backend.public_policy import PublicConfigError, parse_public_solve_request

    cid = "ornl_prius_2004_ipm"
    config = CONFIGS[cid, "native"]
    assert get_magneto2d_winding_support_error(MotorConfig.model_validate(config)) is None
    with pytest.raises(PublicConfigError) as caught:
        parse_public_solve_request(config)
    assert caught.value.field == "rotor.ipm_topology"
    row = {"id": cid, "phase": "C", "fixture": next(c for c in SPECIFICATION["cases"] if c["id"] == cid)["jobs"][0]["fixture"],
           "status": "UNSUPPORTED", "evaluation": {"status": "UNSUPPORTED", "reason": str(caught.value), "gates": []},
           "measurements": {}, "configurations": {"native": config}}
    manifest = {"identity": {"harness_version": "1.2.1", "protocol_version": "1.1.0", "commit": "candidate"},
                "smoke": False, "reference_mode": "FROZEN_REFERENCE"}
    assert build(tmp_path, manifest, [row]) == "PASS_WITH_UNSUPPORTED"
    summary = read(tmp_path / "report/benchmark_summary.json")
    assert summary["counts"] == {"UNSUPPORTED": 1}
    assert summary["rows"][0]["status"] == summary["rows"][0]["evaluation"]["status"] == "UNSUPPORTED"
    assert summary["phase_summary_presentation"]["C"] == "DEFERRED"
    assert summary["planned_coverage"][cid]["numerical_status"] == "UNSUPPORTED"
    assert display_outcome(row) == "Deferred hardware coverage (v0.5.0)"
    for name in ("coilem_benchmark_report.html", "benchmark_report.md"):
        content = (tmp_path / "report" / name).read_text(encoding="utf-8")
        assert "Deferred hardware coverage (v0.5.0)" in content
        assert "HoleM50" in content
        assert "no comparison was performed" in content
    with (tmp_path / "report/benchmark_results.csv").open(newline="", encoding="utf-8") as stream:
        record = next(csv.DictReader(stream))
    assert record["status"] == "UNSUPPORTED"
    assert record["coverage_label"] == "Deferred hardware coverage (v0.5.0)"
    # The roadmap label must not hide other outcomes or imply arbitrary unsupported cases are planned.
    for status in ("PASS", "FAIL", "INCOMPLETE", "NOT_COMPARED"):
        assert display_outcome({"id": cid, "status": status}) == status
    assert display_outcome({"id": "other", "status": "UNSUPPORTED"}) == "UNSUPPORTED"


def test_deferred_scope_does_not_hide_active_warnings_or_other_unsupported_cases():
    from backend.benchmark_suite.report import phase_presentation, presentation_status

    deferred = {"id": "ornl_prius_2004_ipm", "status": "UNSUPPORTED"}
    passed = {"id": "measured", "status": "PASS"}
    assert phase_presentation([passed, deferred]) == "PASS"
    assert presentation_status(deferred) == "DEFERRED"
    assert phase_presentation([passed, {**deferred, "id": "unexpected"}]) == "YELLOW"
    assert phase_presentation([deferred, {**passed, "status": "YELLOW"}]) == "YELLOW"
    assert phase_presentation([{**deferred, "status": "FAIL"}]) == "FAIL"
    assert presentation_status({**deferred, "status": "FAIL"}) == "FAIL"


def test_canonical_request_hash_includes_speed_and_geometry():
    config = copy.deepcopy(next(iter(CONFIGS.values())))
    original = canonical(config)
    config["solve_params"]["rated_speed_rpm"] += 1
    assert canonical(config) != original
    config = copy.deepcopy(next(iter(CONFIGS.values())))
    config["rotor"]["OD_mm"] += 0.1
    assert canonical(config) != original


def test_provenance_survives_native_environment_path_isolation(monkeypatch):
    from backend.benchmark_suite.contract import git

    before = git("rev-parse", "HEAD")
    monkeypatch.setenv("PATH", "")
    assert git("rev-parse", "HEAD") == before


@pytest.mark.parametrize("phase", ["A", "D"])
def test_orchestrator_resume_and_report_only_preserve_completed_jobs(tmp_path, monkeypatch, phase):
    from argparse import Namespace

    from backend import magneto2d_adapter
    from backend.benchmark_suite import cli

    case = next(c for c in SPECIFICATION["cases"] if c["phase"] == phase)
    recorded = historical(case)
    runtime = {"commit": "test-candidate", "dirty": False, "harness_version": "1.0.0", "protocol_version": "1.0.0"}
    monkeypatch.setattr(cli, "identity", lambda _, **kwargs: runtime)
    monkeypatch.setattr(magneto2d_adapter, "ensure_magneto2d_binary", lambda: ROOT / "solvers/magneto2d/Cargo.toml")
    launches = []

    class RecordedWorker:
        pid = 12345

        def __init__(self, command, **kwargs):
            launches.append(command)
            request_path = Path(command[command.index("--request") + 1])
            output_path = Path(command[command.index("--output") + 1])
            cache_root = kwargs["env"]["COILEM_USER_DATA_ROOT"]
            if os.name == "nt":
                assert cache_root.startswith("\\\\?\\")
                cache_root = cache_root[4:]
            assert cache_root == str(output_path.parent / "native-runtime")
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
        suite=HISTORICAL_SPEC,
        reference_bundle=HISTORICAL_BUNDLE,
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
    monkeypatch.setattr(cli, "identity", lambda _, **kwargs: {**runtime, "commit": "changed"})
    with pytest.raises(ValueError, match="Resume refused"):
        cli.execute(args)


def test_runner_deletes_each_job_runtime_and_stops_at_the_disk_floor(tmp_path, monkeypatch):
    """#71: solver files go once a job is measured, and no job starts below the free-space floor."""
    from argparse import Namespace

    from backend import magneto2d_adapter
    from backend.benchmark_suite import cli

    case = next(c for c in SPECIFICATION["cases"] if c["phase"] == "A")
    recorded = historical(case)
    runtime = {"commit": "test-candidate", "dirty": False, "harness_version": "1.0.0", "protocol_version": "1.0.0"}
    monkeypatch.setattr(cli, "identity", lambda _, **kwargs: runtime)
    monkeypatch.setattr(magneto2d_adapter, "ensure_magneto2d_binary", lambda: ROOT / "solvers/magneto2d/Cargo.toml")
    launches = []

    class Worker:
        pid = 12345

        def __init__(self, command, **kwargs):
            launches.append(command)
            request_path = Path(command[command.index("--request") + 1])
            output_path = Path(command[command.index("--output") + 1])
            cache = output_path.parent / "native-runtime" / "solve_cache"
            cache.mkdir(parents=True)
            (cache / "fields.bin").write_bytes(b"0" * 1024)
            request = read(request_path)
            write(output_path, {"status": "COMPLETE", "request_sha256": sha(request_path), "identity_before": request["identity"],
                                "identity_after": request["identity"], "result": recorded["candidate"]})

        def wait(self):
            return 0

    monkeypatch.setattr(cli.subprocess, "Popen", Worker)
    args = Namespace(phases=["A"], case=[case["id"]], list=False, out_dir=tmp_path, no_reference=False, smoke=False,
                     suite=HISTORICAL_SPEC, reference_bundle=HISTORICAL_BUNDLE, report_only=False, allow_dirty=False,
                     resume=False, pdf=False, min_free_gb=1e9)
    with pytest.raises(cli.DiskFloorError, match=f"Stopped before {case['id']} / native: .* below the 1e\\+09 GB floor.*--resume"):
        cli.execute(args)
    assert launches == [] and read(tmp_path / "run_manifest.json")["status"] == "STOPPED_LOW_DISK"
    args.resume, args.min_free_gb = True, 0
    assert cli.execute(args) == 0
    assert len(launches) == 1 and read(tmp_path / "run_manifest.json")["status"] == "COMPLETE"
    job = tmp_path / "jobs" / case["id"] / "native"
    assert (job / "result.json").is_file() and not (job / "native-runtime").exists()


def test_release_suite_replaces_only_two_requests_and_preserves_archives():
    current = load_suite(ROOT / "benchmarks/abcd-v1.1/benchmark_spec.json")
    historical_current_bundle = ROOT / "benchmarks/reference-baselines/ipm-high-output-v1"
    configurations, _, _ = inputs(current, current["cases"])
    manifest, refs, _ = load_bundle(historical_current_bundle, current)
    assert current["protocol_version"] == "1.1.0"
    assert Counter(c["phase"] for c in current["cases"]) == {"A": 10, "B": 12, "C": 5, "D": 3}
    assert len(refs) == 29
    current_cases = {c["id"]: c for c in current["cases"]}
    historical_manifest = read(HISTORICAL_BUNDLE / "manifest.json")
    replaced = set(current["extension"]["replacements"])
    assert replaced == {"ipm_vshape_8p12s_deep_apex_contract", "ipm_vshape_8p12s_wide_angle_contract"}
    assert replaced.isdisjoint(current_cases)
    for case in SPECIFICATION["cases"]:
        if case["id"] in replaced:
            assert historical(case)["comparison"]["status"] == "FAIL"
        else:
            assert current_cases[case["id"]] == case
    for cid, entry in historical_manifest["records"].items():
        if cid in replaced:
            assert cid not in manifest["records"]
            continue
        assert manifest["records"][cid] == entry
        assert sha(historical_current_bundle / entry["file"]) == sha(HISTORICAL_BUNDLE / entry["file"])
    added = [c for c in current["cases"] if c["id"] not in {c["id"] for c in SPECIFICATION["cases"]}]
    assert len(added) == 2
    for case in added:
        from backend.public_policy import parse_public_solve_request

        config = configurations[case["id"], "native"]
        parse_public_solve_request(config)
        reference = refs[case["id"]]
        assert reference["summary"]["avg_torque_Nm"] >= 0.5
        name = "deep_apex" if "deep_apex" in case["id"] else "wide_angle"
        original = copy.deepcopy(CONFIGS[f"ipm_vshape_8p12s_{name}_contract", "native"])
        original["rotor"]["magnet_width_mm"] = 12 if name == "deep_apex" else 10
        assert config == original
        source = read(ROOT / "benchmarks/ipm-high-output-20261011-af56962/rows" / (case["id"] + ".json"))
        evaluation = evaluate_abc(source["candidate"], reference, config)
        assert_same_metrics(evaluation, source["comparison"])
        assert evaluation["status"] == "PASS"
        assert source["native_runtime_before"] == source["native_runtime_after"]
        assert source["reference_runtime_before"] == source["reference_runtime_after"]
        assert source["candidate_commit"] != source["reference_commit"]


def test_protocol_selection_is_recorded_and_unknown_protocols_rejected(tmp_path):
    from backend.benchmark_suite.contract import identity

    binary = ROOT / "solvers/magneto2d/Cargo.toml"
    assert identity(binary)["protocol_version"] == "1.3.0"
    assert identity(binary, protocol_version="1.0.0")["protocol_version"] == "1.0.0"
    with pytest.raises(ValueError, match="Unsupported suite protocol"):
        identity(binary, protocol_version="2.0.0")
    invalid = copy.deepcopy(SPECIFICATION)
    invalid["protocol_version"] = "2.0.0"
    write(tmp_path / "spec.json", invalid)
    with pytest.raises(ValueError, match="Unsupported suite protocol"):
        load_suite(tmp_path / "spec.json")


def test_release_baseline_retains_actual_measured_candidates_and_unaffected_evidence():
    package = ROOT / "benchmarks/release-baseline-20261011-v1.2"
    baseline = read(package / "benchmark_summary.json")
    prior_package = ROOT / "benchmarks/main-20261010-45e0a5c-rerun"
    prior = read(prior_package / "benchmark_summary.json")
    current = load_suite(SPEC)
    original_rows = {row["id"]: row for row in prior["rows"]}
    replacements = set(current["extension"]["replacements"].values())
    assert [row["id"] for row in baseline["rows"]] == [case["id"] for case in current["cases"]]
    assert baseline["counts"] == {"PASS": 29, "UNSUPPORTED": 1}
    assert baseline["status"] == "PASS_WITH_UNSUPPORTED"
    assert baseline["planned_coverage"]["ornl_prius_2004_ipm"]["label"] == "Planned coverage (not yet supported)"
    assert baseline["planned_coverage"]["ornl_prius_2004_ipm"]["numerical_status"] == "UNSUPPORTED"
    assert baseline["phase_order"] == ["A", "B", "C", "D"]
    assert baseline["phase_summary_presentation"] == {"A": "PASS", "B": "PASS", "C": "YELLOW", "D": "PASS"}
    assert baseline["evidence_kind"] == "COMPILED_MEASURED_BASELINE; NOT_A_NEW_SINGLE_CANDIDATE_RUN"
    for row in baseline["rows"]:
        origin = row["measurement_provenance"]
        assert sha(package / origin["source_record"]) == origin["source_record_sha256"]
        assert origin["candidate_commit"] != origin["reference_commit"]
        if row["id"] in replacements:
            source = read(package / origin["source_record"])
            assert origin["candidate_commit"] == source["candidate_commit"]
            assert row["measurements"]["native"] == source["candidate"]
            assert row["reference"] == source["reference"]
            assert row["evaluation"] == source["comparison"]
        else:
            assert origin["candidate_commit"] == prior["run"]["identity"]["commit"]
            for key, value in original_rows[row["id"]].items():
                if key != "fixture_files":
                    assert row[key] == value
            assert row["fixture_files"] == {
                stage: (Path("../main-20261010-45e0a5c-rerun") / path).as_posix()
                for stage, path in original_rows[row["id"]]["fixture_files"].items()
            }
    gates = [gate for row in baseline["rows"] if row["phase"] == "D" for gate in row["evaluation"]["gates"]]
    assert len(gates) == 42 and all(gate["status"] == "PASS" for gate in gates)
    for name in ("release-baseline-20261011-v1.2", "ipm-high-output-20261011-af56962"):
        root = ROOT / "benchmarks" / name
        for file, digest in read(root / "artifact_manifest.json").items():
            assert sha(root / file) == digest


@pytest.mark.parametrize("protocol_version", ["1.0.0", "1.1.0"])
def test_worker_preserves_selected_protocol_for_runtime_verification(tmp_path, monkeypatch, protocol_version):
    """Legacy jobs must not be checked against the new default protocol identity."""
    from argparse import Namespace

    from backend import solver
    from backend.benchmark_suite.contract import identity
    from backend.benchmark_suite.worker import measure

    case = SPECIFICATION["cases"][0]
    config = CONFIGS[case["id"], "native"]
    result = historical(case)["candidate"]

    class RecordedMeasurement:
        def model_dump(self, **kwargs):
            return copy.deepcopy(result)

    class RecordedSolver:
        def __init__(self, *, launch_surface):
            assert launch_surface is True

        def solve(self, parsed, **kwargs):
            return RecordedMeasurement()

    monkeypatch.setattr(solver, "Magneto2DSolver", RecordedSolver)
    binary = ROOT / "solvers/magneto2d/Cargo.toml"
    runtime = identity(binary, protocol_version=protocol_version)
    request = tmp_path / "request.json"
    output = tmp_path / "result.json"
    write(request, {"identity": runtime, "binary": binary.relative_to(ROOT).as_posix(), "config": config, "config_sha256": canonical(config)})
    assert measure(Namespace(request=request, output=output)) == 0
    measured = read(output)
    assert measured["identity_before"] == measured["identity_after"] == runtime
    assert measured["identity_before"]["protocol_version"] == protocol_version
