"""The public command composes versioned data and resumes without repeat fields."""

import copy
from collections import Counter

import pytest

from backend.benchmark_suite import collection, command
from backend.benchmark_suite.contract import ROOT, read, sha, write
from backend.benchmark_suite.references import reference_provenance
from tools.build_benchmark_collection import descriptor


@pytest.fixture
def data(tmp_path):
    path = tmp_path / "collection.json"
    write(path, descriptor())
    _, children, digest = collection.load_collection(quick=True, path=path)
    for child in children:
        child["physics"] = {"status": "MATCH", "files": 0, "differs": [], "unverified": []}
    return path, children, digest


def test_default_and_quick_include_all_six_phases_with_separate_references(data):
    path, quick, _ = data
    _, full, _ = collection.load_collection(path=path)
    assert sum(len(child["cases"]) for child in full) == 69
    assert [child["spec"]["protocol_version"] for child in full] == ["1.6.0", "1.7.0", "1.8.0"]
    assert [case["phase"] for child in quick for case in child["cases"]] == list("ABCDEF")
    assert [child["component"]["experimental"] for child in full] == [False, True, False]
    assert full[1]["record"] is None and full[1]["component"]["records"] == {}
    assert len({child["bundle_identity"] for child in full}) == 3
    assert {case["id"] for child in quick for case in child["cases"]} == set(command.QUICK_PHASE_CASES.values())


def test_default_list_and_phase_filters_never_execute_fields(data, monkeypatch, capsys):
    path, _, _ = data
    monkeypatch.setattr(command, "load_collection", lambda phases, quick: collection.load_collection(phases, quick=quick, path=path))
    monkeypatch.setattr(command, "execute", lambda args: pytest.fail("--list must not execute a solver"))
    assert command.main(["--list"]) == 0
    output = capsys.readouterr().out
    assert "69 cases" in output and "experimental" in output
    assert command.main(["--list", "--quick"]) == 0
    assert "6 cases" in capsys.readouterr().out
    assert command.main(["--list", "--phase", "E", "--phase", "F"]) == 0
    assert "22 cases" in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["suite", "bundle_manifest", "bundle_identity", "record", "e_scope", "quick"])
def test_snapshot_data_rejects_changed_inputs_before_execution(data, kind):
    path, _, _ = data
    document = read(path)
    if kind == "suite":
        document["components"][0]["suite"]["sha256"] = "0" * 64
    elif kind == "bundle_manifest":
        document["components"][2]["reference_bundle"]["manifest_sha256"] = "0" * 64
    elif kind == "bundle_identity":
        document["components"][2]["reference_bundle"]["identity_sha256"] = "0" * 64
    elif kind == "record":
        document["components"][0]["records"]["windows-x86_64"]["sha256"] = "0" * 64
    elif kind == "e_scope":
        document["components"][1]["experimental"] = False
    else:
        document["components"][1]["quick_cases"]["E"] = "not_registered"
    write(path, document)
    with pytest.raises(ValueError):
        collection.load_collection(path=path)


def simulation(children, output, *, e_status="PASS", interrupt=None):
    calls = []
    by_suite = {child["suite_path"]: child for child in children}

    def execute(args):
        calls.append(args)
        snapshot = read(output / collection.MANIFEST_FILE)
        assert len(snapshot["selection"]["components"]) == len(children)
        assert all(entry["reference_bundle"]["identity_sha256"] for entry in snapshot["selection"]["components"])
        child = by_suite[args.suite]
        component_id = child["component"]["id"]
        if component_id == interrupt:
            raise KeyboardInterrupt
        if args.report_only:
            rows = read(args.out_dir / "report/benchmark_summary.json")["rows"]
        else:
            selection = {"case_ids": args.case, "spec_sha256": child["component"]["suite"]["sha256"],
                         "bundle_sha256": child["bundle_identity"], "smoke": False, "no_reference": False}
            identity = {"commit": component_id, "protocol_version": child["spec"]["protocol_version"],
                        "installation": "source", "source_files": (child["record"] or {}).get("physics_files", {})}
            native = {"status": "COMPLETE", "selection": selection, "identity": identity,
                      "reference_mode": "FROZEN_REFERENCE", **reference_provenance(child["reference_manifest"])}
            write(args.out_dir / "run_manifest.json", native)
            rows = [{"id": case["id"], "phase": case["phase"], "status": e_status if case["phase"] == "E" else "PASS",
                     "evaluation": {"status": e_status if case["phase"] == "E" else "PASS", "gates": {}}}
                    for case in child["cases"]]
            rows.sort(key=lambda row: row["phase"])
            status = "INCOMPLETE" if e_status == "ERROR" else "FAIL" if e_status == "FAIL" else "PASS"
            status = status if component_id == "phase-e" else "PASS"
            write(args.out_dir / "report/benchmark_summary.json", {"run": native, "status": status,
                                                                   "counts": dict(Counter(row["status"] for row in rows)), "rows": rows})
        return 2 if any(row["status"] == "ERROR" for row in rows) else 1 if any(row["status"] == "FAIL" for row in rows) else 0

    def reporter(folder, manifest, reports):
        assert [report["summary"]["run"]["identity"]["protocol_version"] for report in reports] == [
            child["spec"]["protocol_version"] for child in children]
        rows = [copy.deepcopy(row) for report in reports for row in report["summary"]["rows"]]
        counts = dict(Counter(row["status"] for row in rows))
        status = "INCOMPLETE" if "ERROR" in counts else "FAIL" if "FAIL" in counts else "PASS"
        return {"status": status, "counts": counts, "rows": rows}, {"status": "MATCH"}

    return calls, execute, reporter


@pytest.fixture
def record_matching(monkeypatch):
    monkeypatch.setattr(collection, "check_physics", lambda record: {"status": "MATCH", "differs": [], "unverified": []})
    monkeypatch.setattr(collection, "compare_run", lambda rows, record, **kwargs: {
        "status": "MATCH" if record else "NO_RECORD", "matched": len(rows) if record else 0, "compared": len(rows) if record else 0,
        "cases": {row["id"]: {"match": True, "differences": []} for row in rows} if record else {},
    })


def test_experimental_failures_remain_visible_without_becoming_qualification_gates(data, tmp_path, record_matching):
    _, children, digest = data
    output = tmp_path / "run"
    calls, execute, reporter = simulation(children, output, e_status="FAIL")
    code, summary, _ = collection.run_collection(output, children, {"phases": list("ABCDEF"), "quick": True}, digest,
                                                 execute_child=execute, reporter=reporter)
    assert code == 0 and summary["status"] == "FAIL" and summary["counts"] == {"PASS": 5, "FAIL": 1}
    assert len(calls) == 3 and read(output / collection.MANIFEST_FILE)["status"] == "COMPLETE"


def test_experimental_execution_failure_still_makes_collection_incomplete(data, tmp_path, record_matching):
    _, children, digest = data
    output = tmp_path / "run"
    _, execute, reporter = simulation(children, output, e_status="ERROR")
    code, summary, _ = collection.run_collection(output, children, {"phases": list("ABCDEF"), "quick": True}, digest,
                                                 execute_child=execute, reporter=reporter)
    assert code == 2 and summary["status"] == "INCOMPLETE"


def test_full_reports_can_group_phases_without_changing_registered_job_order(data, tmp_path, record_matching):
    path, _, _ = data
    _, children, digest = collection.load_collection(path=path)
    for child in children:
        child["physics"] = {"status": "MATCH"}
    output = tmp_path / "full"
    _, execute, reporter = simulation(children, output)
    code, summary, _ = collection.run_collection(output, children, {"phases": list("ABCDEF"), "quick": False}, digest,
                                                 execute_child=execute, reporter=reporter)
    assert code == 0 and sum(summary["counts"].values()) == 69
    native = read(output / "suites/abcd/run_manifest.json")
    assert native["selection"]["case_ids"] == [case["id"] for case in children[0]["cases"]]


def test_explicit_experimental_phase_runs_without_other_components(data, tmp_path, record_matching):
    path, _, _ = data
    _, children, digest = collection.load_collection(["E"], quick=True, path=path)
    output = tmp_path / "e-only"
    calls, execute, reporter = simulation(children, output, e_status="FAIL")
    code, summary, _ = collection.run_collection(output, children, {"phases": ["E"], "quick": True}, digest,
                                                 execute_child=execute, reporter=reporter)
    assert code == 0 and summary["counts"] == {"FAIL": 1}
    assert len(calls) == 1 and calls[0].phases == ["E"]


def test_resume_and_report_only_reuse_complete_native_children(data, tmp_path, record_matching):
    _, children, digest = data
    output = tmp_path / "run"
    options = {"phases": list("ABCDEF"), "quick": True}
    calls, execute, reporter = simulation(children, output)
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter)
    native_before = {path.relative_to(output).as_posix(): sha(path) for path in output.glob("suites/*/run_manifest.json")}
    calls.clear()
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter, resume=True)
    assert len(calls) == 3 and all(call.report_only and not call.resume for call in calls)
    calls.clear()
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter, report_only=True)
    assert len(calls) == 3 and all(call.report_only for call in calls)
    assert {path.relative_to(output).as_posix(): sha(path) for path in output.glob("suites/*/run_manifest.json")} == native_before


def test_interrupted_collection_resumes_pending_children_without_repeating_completed_fields(data, tmp_path, record_matching):
    _, children, digest = data
    output = tmp_path / "run"
    options = {"phases": list("ABCDEF"), "quick": True}
    _, interrupting, reporter = simulation(children, output, interrupt="phase-e")
    with pytest.raises(KeyboardInterrupt):
        collection.run_collection(output, children, options, digest, execute_child=interrupting, reporter=reporter)
    assert read(output / collection.MANIFEST_FILE)["status"] == "STOPPED"
    calls, execute, reporter = simulation(children, output)
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter, resume=True)
    assert calls[0].report_only and all(not call.report_only and not call.resume for call in calls[1:])


@pytest.mark.parametrize("kind", ["descriptor", "options", "records", "directory"])
def test_resume_refuses_changed_snapshots_before_touching_children(data, tmp_path, record_matching, kind):
    _, children, digest = data
    output = tmp_path / "run"
    options = {"phases": list("ABCDEF"), "quick": True}
    calls, execute, reporter = simulation(children, output)
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter)
    calls.clear()
    if kind == "descriptor":
        digest = "0" * 64
    elif kind == "options":
        options = {**options, "quick": False}
    elif kind == "records":
        children = copy.deepcopy(children)
        children[0]["component"]["records"]["windows-x86_64"]["sha256"] = "0" * 64
    else:
        manifest = read(output / collection.MANIFEST_FILE)
        manifest["components"][0]["directory"] = "../outside"
        write(output / collection.MANIFEST_FILE, manifest)
    with pytest.raises(ValueError):
        collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter, resume=True)
    assert not calls


def test_collection_refuses_output_inside_installation(data, record_matching):
    _, children, digest = data
    with pytest.raises(ValueError, match="outside"):
        collection.run_collection(ROOT / "not-created", children, {"phases": list("ABCDEF"), "quick": True}, digest,
                                  execute_child=lambda args: pytest.fail("must not execute"), reporter=lambda *args: None)


def test_modes_require_an_existing_collection_folder(capsys):
    with pytest.raises(SystemExit):
        command.main(["--report-only"])
    assert "needs --out" in capsys.readouterr().err


def test_legacy_single_suite_run_is_not_reinterpreted_as_a_collection(data, tmp_path, record_matching):
    _, children, digest = data
    output = tmp_path / "legacy"
    write(output / "run_manifest.json", {"schema": "coilem.benchmark_run/v1", "status": "COMPLETE"})
    before = sha(output / "run_manifest.json")
    with pytest.raises(ValueError, match="legacy single-suite.*tools.run_benchmarks"):
        collection.run_collection(output, children, {"phases": list("ABCDEF"), "quick": True}, digest,
                                  execute_child=lambda args: pytest.fail("must not execute"), reporter=lambda *args: None, resume=True)
    assert sha(output / "run_manifest.json") == before


def test_record_matching_checks_the_child_measurement_not_only_startup_physics(data, record_matching):
    _, children, _ = data
    record = children[0]["record"]
    measured = copy.deepcopy(record["physics_files"])
    changed = next(iter(measured))
    measured[changed] = "0" * 64
    result = collection._comparison_physics(record, {"installation": "source", "source_files": measured})
    assert result["status"] == "DIFFERS" and changed in result["differs"]


def test_mocked_collection_uses_real_html_json_and_share_reporter(data, tmp_path, record_matching):
    _, children, digest = data
    output = tmp_path / "actual-reporter"
    _, simulate, _ = simulation(children, output, e_status="FAIL")
    by_suite = {child["suite_path"]: child for child in children}

    def execute(args):
        code = simulate(args)
        summary = read(args.out_dir / "report/benchmark_summary.json")
        cases = {case["id"]: case for case in by_suite[args.suite]["cases"]}
        for row in summary["rows"]:
            row.update(fixture=cases[row["id"]]["jobs"][0]["fixture"], configurations={"native": {"test_case": row["id"]}})
            if row["phase"] == "D":
                row["measurements"] = {}
            elif row["phase"] == "E":
                row["measurements"] = {"native": {"summary": {"cogging": {"peak_to_peak_Nm": 0.002, "first_harmonic_Nm": 0.001}}}}
            else:
                row["measurements"] = {"native": {"summary": {"avg_torque_Nm": 1, "back_emf_fundamental_V": 1},
                                                   "back_emf_waveform": {"phase_a_V": [1, -1]}}}
        write(args.out_dir / "report/benchmark_summary.json", summary)
        return code

    code, summary, comparison = collection.run_collection(
        output, children, {"phases": list("ABCDEF"), "quick": True}, digest, execute_child=execute,
    )
    assert code == 0 and summary["status"] == "FAIL" and comparison["status"] == "MATCH"
    assert comparison["matched"] == comparison["compared"] == 5
    assert summary["run"]["identity"]["protocol_version"] == "collection/1"
    assert "reference_commit" not in summary["run"]
    assert [component["protocol_version"] for component in summary["collection"]["components"]] == ["1.6.0", "1.7.0", "1.8.0"]
    assert (output / "report/coilem_benchmark_report.html").is_file()
    portable = read(output / "share/coilem-benchmark.json")
    assert next(case for case in portable["cases"] if case["phase"] == "E")["experimental"] is True
    assert "experimental" in (output / "share/coilem-benchmark.md").read_text(encoding="utf-8").lower()


def test_operational_settings_survive_interruption_without_changing_selection(data, tmp_path, record_matching):
    _, children, digest = data
    output = tmp_path / "retained-runtime"
    options = {"phases": list("ABCDEF"), "quick": True}
    _, interrupting, reporter = simulation(children, output, interrupt="phase-e")
    with pytest.raises(KeyboardInterrupt):
        collection.run_collection(output, children, options, digest, execute_child=interrupting, reporter=reporter,
                                  min_free_gb=5.5, keep_runtime=True)
    before = read(output / collection.MANIFEST_FILE)
    assert before["operational_settings"] == {"min_free_gb": 5.5, "keep_runtime": True}
    calls, execute, reporter = simulation(children, output)
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter, resume=True)
    assert all(call.min_free_gb == 5.5 and call.keep_runtime is True for call in calls)
    assert calls[0].report_only and not calls[1].report_only
    after = read(output / collection.MANIFEST_FILE)
    assert after["selection"] == before["selection"]
    assert read(output / command.OPTIONS_FILE) == options


def test_explicit_operational_overrides_persist_and_report_only_inherits_them(data, tmp_path, record_matching):
    _, children, digest = data
    output = tmp_path / "overridden-settings"
    options = {"phases": list("ABCDEF"), "quick": True}
    calls, execute, reporter = simulation(children, output)
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter)
    before = read(output / collection.MANIFEST_FILE)
    assert before["operational_settings"] == {"min_free_gb": 3.0, "keep_runtime": False}
    calls.clear()
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter, resume=True,
                              min_free_gb=7.0, keep_runtime=True)
    assert all(call.min_free_gb == 7.0 and call.keep_runtime for call in calls)
    calls.clear()
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter, report_only=True)
    assert all(call.min_free_gb == 7.0 and call.keep_runtime and call.report_only for call in calls)
    after = read(output / collection.MANIFEST_FILE)
    assert after["selection"] == before["selection"]
    assert after["operational_settings"] == {"min_free_gb": 7.0, "keep_runtime": True}


def test_legacy_collection_operational_defaults_remain_available(data, tmp_path, record_matching):
    _, children, digest = data
    output = tmp_path / "legacy-settings"
    options = {"phases": list("ABCDEF"), "quick": True}
    calls, execute, reporter = simulation(children, output)
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter)
    manifest = read(output / collection.MANIFEST_FILE)
    manifest.pop("operational_settings")
    write(output / collection.MANIFEST_FILE, manifest)
    calls.clear()
    collection.run_collection(output, children, options, digest, execute_child=execute, reporter=reporter, resume=True)
    assert all(call.min_free_gb == 3.0 and call.keep_runtime is False for call in calls)


def test_parser_preserves_absent_operational_settings_for_resume():
    parser = command.build_parser()
    absent = parser.parse_args([])
    assert absent.min_free_gb is None and absent.keep_runtime is None
    explicit = parser.parse_args(["--min-free-gb", "4.5", "--keep-runtime"])
    assert explicit.min_free_gb == 4.5 and explicit.keep_runtime is True


@pytest.mark.parametrize("floor", [-1, float("nan"), float("inf"), True])
def test_invalid_operational_floor_is_rejected_before_field_requests(data, tmp_path, record_matching, floor):
    _, children, digest = data
    output = tmp_path / "invalid-settings"
    calls, execute, reporter = simulation(children, output)
    with pytest.raises(ValueError, match="disk floor"):
        collection.run_collection(output, children, {"phases": list("ABCDEF"), "quick": True}, digest,
                                  execute_child=execute, reporter=reporter, min_free_gb=floor)
    assert not calls and not (output / collection.MANIFEST_FILE).exists()
