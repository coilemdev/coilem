"""``coilem benchmark`` (#71): packaged data, published records, the match policy and the shareable report."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from backend import launcher, resources
from backend.benchmark_suite import command, record
from backend.benchmark_suite.contract import DATA_ROOT, SPEC, read
from backend.benchmark_suite.physics import BUILD_INFO_KEY, physics_sources
from backend.benchmark_suite.references import load_suite
from backend.benchmark_suite.share import SHARE_DIR, SHARE_NAME, write_share_report
from backend.local_paths import LOCAL_PATH_PLACEHOLDER, contains_local_path, redact_local_paths
from tools.build_benchmark_record import main as build_record_main
from tools.build_benchmark_record import regrade

REPO_ROOT = Path(__file__).resolve().parents[1]
RECORDS = REPO_ROOT / resources.BENCHMARK_RECORDS_DIR
EVIDENCE = {
    "macos-arm64": REPO_ROOT / "benchmarks/macos-native-20261015-738d951",
    "windows-x86_64": REPO_ROOT / "benchmarks/windows-v3-20261015-738d951",
}
MATCHING_PHYSICS = {"status": "MATCH", "files": 0, "differs": [], "unverified": []}
# Home-directory paths, joined at run time so this file passes the publication path check.
WINDOWS_HOME = "\\".join(("C:", "Users", "someone"))
LINUX_HOME = "/".join(("", "home", "someone"))
MAC_HOME = "/".join(("", "Users", "ana"))


@pytest.fixture(scope="module")
def graded():
    return {key: regrade(read(path / "benchmark_summary.json"))[0] for key, path in EVIDENCE.items()}


def test_wheel_data_covers_everything_the_suite_registers() -> None:
    files = set(resources.benchmark_data_files(REPO_ROOT))
    spec = load_suite(SPEC)
    assert DATA_ROOT == REPO_ROOT and SPEC == REPO_ROOT / resources.BENCHMARK_SUITE_FILE
    assert {resources.BENCHMARK_SUITE_FILE, spec["golden"]} <= files
    for case in spec["cases"]:
        assert {job["fixture"] for job in case["jobs"]} <= files
        if case["phase"] == "D":
            assert case["protocol"] in files
    bundle = [path for path in files if path.startswith(resources.BENCHMARK_REFERENCE_BUNDLE_DIR)]
    assert len(bundle) == 1 + len(read(REPO_ROOT / resources.BENCHMARK_REFERENCE_BUNDLE_DIR / "manifest.json")["records"])
    assert {f"{resources.BENCHMARK_RECORDS_DIR}/{key}.json" for key in EVIDENCE} <= files
    assert all((REPO_ROOT / path).is_file() for path in files)


@pytest.mark.parametrize("key", sorted(EVIDENCE))
def test_records_are_rebuilt_exactly_from_the_committed_evidence(key: str, tmp_path: Path) -> None:
    assert build_record_main([str(EVIDENCE[key]), "--out", str(tmp_path / "record.json")]) == 0
    assert (tmp_path / "record.json").read_text(encoding="utf-8") == (RECORDS / f"{key}.json").read_text(encoding="utf-8")
    published = read(RECORDS / f"{key}.json")
    assert published["platform"] == key and published["measured_commit"].startswith("738d951")
    assert set(published["physics_files"]) == set(physics_sources(REPO_ROOT))


def test_regrading_reproduces_the_published_windows_comparison(graded) -> None:
    published = {row["id"]: row for row in read(EVIDENCE["windows-x86_64"] / "benchmark_summary.json")["rows"]}
    for row in graded["windows-x86_64"]["rows"]:
        assert row["status"] == published[row["id"]]["status"]
        assert record.gate_statuses(row["evaluation"]) == record.gate_statuses(published[row["id"]]["evaluation"])


@pytest.mark.parametrize(("run", "against"), [("macos-arm64", "windows-x86_64"), ("windows-x86_64", "macos-arm64")])
def test_each_platform_matches_the_other_platforms_record(graded, run: str, against: str) -> None:
    # The tolerances come from this spread, so it must stay inside them.
    comparison = record.compare_run(graded[run]["rows"], read(RECORDS / f"{against}.json"), physics=MATCHING_PHYSICS)
    assert comparison["status"] == "MATCH" and comparison["matched"] == comparison["compared"] == 30
    worst = max(abs(v["value"] - v["record"]) / v["tolerance"] for case in comparison["cases"].values() for v in case["values"].values())
    assert 0.3 < worst < 0.5


def test_match_policy_needs_identical_verdicts_and_gates_and_close_values(graded) -> None:
    published = read(RECORDS / "windows-x86_64.json")
    rows = {row["id"]: row for row in graded["windows-x86_64"]["rows"]}
    row = copy.deepcopy(rows["spm_8p12s_concentrated__baseline"])
    assert record.compare_case(row, published["cases"][row["id"]])["match"]

    summary = row["measurements"]["native"]["summary"]
    summary["avg_torque_Nm"] *= 1.004
    assert record.compare_case(row, published["cases"][row["id"]])["match"], "0.4% is inside the 0.5% torque tolerance"
    summary["avg_torque_Nm"] *= 1.004
    outcome = record.compare_case(row, published["cases"][row["id"]])
    assert not outcome["match"] and outcome["differences"][0].startswith("mean_torque_Nm")

    row = copy.deepcopy(rows["spm_8p12s_concentrated__baseline"])
    row["evaluation"]["gates"]["bemf_peak"] = "YELLOW"
    row["status"] = "YELLOW"
    differences = record.compare_case(row, published["cases"][row["id"]])["differences"]
    assert differences == ["verdict YELLOW, record PASS", "gate bemf_peak YELLOW, record PASS"]

    # No-load torque sits near zero, where the absolute floor applies.
    row = copy.deepcopy(rows["spm_4p12s_simple_noload__baseline"])
    row["measurements"]["native"]["summary"]["avg_torque_Nm"] += 0.0009
    assert record.compare_case(row, published["cases"][row["id"]])["match"]
    assert record.compare_case(row, None) == {"match": False, "differences": ["not in the record"], "values": {}}


def test_unsupported_and_failed_cases_must_match_too(graded) -> None:
    published = read(RECORDS / "windows-x86_64.json")
    prius = next(row for row in graded["windows-x86_64"]["rows"] if row["id"] == "ornl_prius_2004_ipm")
    assert record.compare_case(prius, published["cases"]["ornl_prius_2004_ipm"])["match"]
    errored = {**prius, "status": "ERROR", "evaluation": {"status": "ERROR", "gates": [], "errors": ["boom"]}}
    assert record.compare_case(errored, published["cases"]["ornl_prius_2004_ipm"])["differences"] == [
        "verdict ERROR, record UNSUPPORTED"
    ]


def test_physics_check_reads_this_checkout_and_names_a_change(monkeypatch) -> None:
    published = read(RECORDS / "macos-arm64.json")
    assert record.check_physics(published) == {"status": "MATCH", "files": 50, "differs": [], "unverified": []}
    changed = copy.deepcopy(published)
    changed["physics_files"]["backend/torque_metrics.py"] = "0" * 64
    assert record.check_physics(changed)["differs"] == ["backend/torque_metrics.py"]
    monkeypatch.setenv("COILEM_MAGNETO2D_BINARY", "/somewhere/magneto2d")
    unverified = record.check_physics(published)
    assert unverified["status"] == "UNVERIFIED" and unverified["unverified"][0] == "solvers/magneto2d/Cargo.lock"
    comparison = record.compare_run([], changed, physics=record.check_physics(changed))
    assert comparison["status"] == "NOT_COMPARABLE"


def test_installed_package_checks_the_solver_by_its_stamped_hashes(monkeypatch) -> None:
    monkeypatch.delenv("COILEM_MAGNETO2D_BINARY", raising=False)
    published = read(RECORDS / "windows-x86_64.json")
    stamped = {path: digest for path, digest in published["physics_files"].items() if path.startswith("solvers/")}
    monkeypatch.setattr(record, "CHECKOUT", None)
    monkeypatch.setattr(record, "stamped_build_info", lambda: {BUILD_INFO_KEY: stamped})
    assert record.check_physics(published)["status"] == "MATCH"
    monkeypatch.setattr(record, "stamped_build_info", lambda: {BUILD_INFO_KEY: {**stamped, "solvers/magneto2d/src/new.rs": "1" * 64}})
    assert record.check_physics(published)["differs"] == ["solvers/magneto2d/src/new.rs"]
    monkeypatch.setattr(record, "stamped_build_info", lambda: None)
    assert record.check_physics(published)["status"] == "UNVERIFIED"


@pytest.mark.parametrize(
    ("system", "machine", "key", "cross"),
    [
        ("Darwin", "arm64", "macos-arm64", False),
        ("Windows", "AMD64", "windows-x86_64", False),
        ("Linux", "x86_64", "windows-x86_64", True),
        ("Linux", "aarch64", "macos-arm64", True),
        ("Linux", "riscv64", None, False),
    ],
)
def test_each_platform_selects_its_record_or_the_closest(system, machine, key, cross) -> None:
    selected, cross_platform = record.select_record(record.load_records(), record.platform_key(system, machine))
    assert (selected["platform"] if selected else None, cross_platform) == (key, cross)


def test_platform_key_survives_an_environment_without_the_processor_variable(monkeypatch) -> None:
    # Windows Python 3.11 reads platform.machine() from PROCESSOR_ARCHITECTURE; a minimal
    # environment, like the wheel acceptance test's, leaves it empty.
    from backend.benchmark_suite import contract

    monkeypatch.setattr(contract.platform, "machine", lambda: "")
    monkeypatch.setattr(contract.sysconfig, "get_platform", lambda: "win-amd64")
    monkeypatch.setattr(record.platform, "system", lambda: "Windows")
    assert contract.machine_name() == "amd64"
    assert record.platform_key() == "windows-x86_64"


def test_quick_subset_is_one_passing_case_per_phase() -> None:
    cases = command.select_cases(load_suite(SPEC), list("ABCD"), quick=True)
    assert [case["phase"] for case in cases] == list("ABCD")
    assert [case["id"] for case in cases] == list(command.QUICK_CASES)
    for published in record.load_records().values():
        assert all(published["cases"][case["id"]]["status"] == "PASS" for case in cases)
        assert command.estimate(published, cases) < 6 * 60
        assert 40 * 60 < command.estimate(published, load_suite(SPEC)["cases"]) < 60 * 60
    assert [case["id"] for case in command.select_cases(load_suite(SPEC), ["B"], quick=True)] == [command.QUICK_CASES[1]]


def test_launcher_runs_the_benchmark_subcommand(monkeypatch) -> None:
    received = []
    monkeypatch.setattr(command, "main", lambda argv: received.append(argv) or 7)
    assert launcher.main(["benchmark", "--quick", "--list"]) == 7
    assert received == [["--quick", "--list"]]


def test_resume_needs_the_run_folder(capsys) -> None:
    with pytest.raises(SystemExit):
        command.main(["--resume"])
    assert "--resume needs --out" in capsys.readouterr().err


def test_shareable_report_removes_local_paths(graded, tmp_path: Path) -> None:
    summary = copy.deepcopy(graded["macos-arm64"])
    summary["rows"] = [row for row in summary["rows"] if row["id"] in command.QUICK_CASES]
    output = tmp_path / "run"
    summary["rows"][0] = {
        **summary["rows"][0],
        "status": "ERROR",
        "evaluation": {"status": "ERROR", "gates": [], "errors": [
            f"Disk full writing {output}/jobs/x/native-runtime/solve_cache",
            WINDOWS_HOME + "\\coilem-benchmark\\jobs\\x failed",
            LINUX_HOME + "/cache/mesh.msh missing",
        ]},
    }
    published = read(RECORDS / "macos-arm64.json")
    comparison = record.compare_run(summary["rows"], published, physics=MATCHING_PHYSICS)
    selection = {"phases": list("ABCD"), "quick": True, "case_ids": list(command.QUICK_CASES)}
    markdown = write_share_report(output, summary, comparison, selection=selection).read_text(encoding="utf-8")
    payload = json.loads((output / SHARE_DIR / f"{SHARE_NAME}.json").read_text(encoding="utf-8"))
    text = json.dumps(payload)
    for content in (markdown, *[str(error) for error in payload["cases"][0]["errors"]]):
        assert not contains_local_path(content)
    assert str(output) not in markdown and str(output) not in text and str(Path.home()) not in markdown
    assert payload["cases"][0]["errors"][0] == f"Disk full writing {LOCAL_PATH_PLACEHOLDER}/jobs/x/native-runtime/solve_cache"
    assert "## Record match: DIFFERS" in markdown and "3 of 4 cases match" in markdown
    assert "coilem benchmark --quick`" in markdown
    assert payload["record_match"]["record"]["measured_commit"].startswith("738d951")


def test_publication_check_and_shareable_report_use_one_set_of_path_rules() -> None:
    spec = importlib.util.spec_from_file_location("verify_snapshot_under_test", REPO_ROOT / "tools/verify_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from backend import local_paths

    assert [p.pattern for p in module.ABSOLUTE_USER_PATH_PATTERNS] == [p.pattern for p in local_paths.ABSOLUTE_USER_PATH_PATTERNS]
    assert redact_local_paths(f"see {MAC_HOME}/coilem-out/report.md now") == f"see {LOCAL_PATH_PLACEHOLDER} now"
    assert redact_local_paths(WINDOWS_HOME + "\\out\\a.json failed") == f"{LOCAL_PATH_PLACEHOLDER} failed"
    assert redact_local_paths("D:\\runs\\x\\a.json", known=["D:\\runs\\x"]) == f"{LOCAL_PATH_PLACEHOLDER}\\a.json"
