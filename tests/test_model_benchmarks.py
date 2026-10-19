"""Selection, interrupted evidence, immutable resume and distinct model claims."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.benchmark_suite.contract import read, sha, write
from tools import run_model_benchmarks as runner

ROOT = Path(__file__).resolve().parents[1]
HONDA = ROOT / "docs/hardware-validation/honda-accord-2005/real-winding-comparison"


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    grading = checkout / "target.json"
    grading.write_text('{"frozen": true}', encoding="utf-8")
    state = SimpleNamespace(calls=[], fail_step=None, mutate=False, software_pass=True)

    def identity(models):
        return {"commit": "a" * 40, "grading_inputs": {"target.json": sha(grading)}}

    def step(module, arguments, folder, index):
        state.calls.append((module, arguments))
        if index == state.fail_step:
            return 2
        if state.mutate:
            grading.write_text('{"frozen": false}', encoding="utf-8")
        if module == "tools.honda_accord_comparison":
            command = arguments[0]
            if command in {"no-load", "locked-rotor"}:
                target = Path(arguments[arguments.index("--out") + 1])
                shutil.copyfile(HONDA / f"{command}.json", target)
            else:
                target = Path(arguments[-1])
                target.mkdir()
                shutil.copyfile(HONDA / "comparison.json", target / "comparison.json")
        elif module == "tools.report_prius_benchmark":
            write(folder / "report/app-results.json", {"all_software_checks_pass": state.software_pass,
                                                       "checks": {"software": state.software_pass}})
            (folder / "report/app-results.md").write_text("software evaluation", encoding="utf-8")
            return 0 if state.software_pass else 1
        return 0

    monkeypatch.setattr(runner, "ROOT", checkout)
    monkeypatch.setattr(runner, "current_identity", identity)
    monkeypatch.setattr(runner, "run_step", step)
    output = tmp_path / "evidence"
    return SimpleNamespace(output=output, grading=grading, state=state,
                           run=lambda *args: runner.main(["--out", str(output), *args]),
                           record=lambda: read(output / runner.STATE_FILE))


def test_list_models_requires_no_executable_or_output(monkeypatch, capsys):
    monkeypatch.setattr(runner, "ensure_magneto2d_binary", lambda: pytest.fail("list built a solver"))
    assert runner.main(["--list"]) == 0
    text = capsys.readouterr().out
    assert "Pyleecan Prius 8p48s" in text and "Honda Accord 2005 16p24s" in text
    assert "no hardware pass/fail" in text


def test_honda_is_complete_without_claiming_a_hardware_pass_and_resume_checks_bytes(workflow):
    assert workflow.run("--model", "honda-accord") == 0
    record = workflow.record()
    result = record["results"]["honda-accord"]
    assert record["complete"] and result["result"]["status"] == "COMPLETE_NO_HARDWARE_VERDICT"
    assert (workflow.output / "frozen-inputs/target.json").read_bytes() == workflow.grading.read_bytes()
    before = len(workflow.state.calls)
    assert workflow.run("--resume") == 0
    assert len(workflow.state.calls) == before
    (workflow.output / result["directory"] / "no-load.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence changed"):
        workflow.run("--resume")
    assert len(workflow.state.calls) == before


def test_interrupted_model_retains_attempt_and_retry_uses_a_new_directory(workflow):
    workflow.state.fail_step = 2
    with pytest.raises(RuntimeError, match="exited 2"):
        workflow.run("--model", "honda-accord")
    first = workflow.record()
    assert not first["complete"] and first["states"]["honda-accord"] == "INCOMPLETE"
    assert (workflow.output / first["attempts"]["honda-accord"][0]["directory"] / "no-load.json").exists()
    workflow.state.fail_step = None
    assert workflow.run("--resume") == 0
    attempts = workflow.record()["attempts"]["honda-accord"]
    assert len(attempts) == 2 and attempts[0]["status"] == "INTERRUPTED_OR_FAILED"
    assert attempts[1]["status"] == "COMPLETE" and attempts[1]["directory"] != attempts[0]["directory"]


def test_changed_grading_inputs_stop_collection_before_assembling(workflow):
    workflow.state.mutate = True
    with pytest.raises(ValueError, match="inputs changed"):
        workflow.run("--model", "honda-accord")
    assert len(workflow.state.calls) == 1 and workflow.record()["results"] == {}
    with pytest.raises(ValueError, match="identity differs"):
        workflow.run("--resume")


def test_failed_prius_checks_are_complete_failed_evidence(workflow):
    workflow.state.software_pass = False
    assert workflow.run("--model", "pyleecan-prius") == 1
    record = workflow.record()
    assert record["complete"] and record["results"]["pyleecan-prius"]["result"]["status"] == "FAIL"
    assert "--curve" in workflow.state.calls[0][1] and "--refinement" in workflow.state.calls[0][1]


def test_honda_missing_current_audit_cannot_be_registered(tmp_path):
    (tmp_path / "report").mkdir()
    shutil.copyfile(HONDA / "comparison.json", tmp_path / "report/comparison.json")
    points = read(HONDA / "locked-rotor.json")
    points[0]["coilem_currents_per_Ia"] = None
    write(tmp_path / "locked-rotor.json", points)
    with pytest.raises(ValueError, match="phase-current audit"):
        runner.model_result("honda-accord", tmp_path)


def test_subprocesses_use_private_caches_without_changing_the_running_app(monkeypatch, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setenv("COILEM_USER_DATA_ROOT", "existing-app-root")
    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.run_step("tools.honda_accord_comparison", ["no-load"], tmp_path, 1) == 0
    _, options = calls[0]
    assert options["env"]["COILEM_USER_DATA_ROOT"] == str(tmp_path / "runtime")
    assert options["env"]["COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS"] == "1"
    assert os.environ["COILEM_USER_DATA_ROOT"] == "existing-app-root"


def test_resume_rejects_a_different_model_selection(workflow):
    workflow.run("--model", "honda-accord")
    before = len(workflow.state.calls)
    with pytest.raises(ValueError, match="selection or execution identity"):
        workflow.run("--resume", "--model", "abcd")
    assert len(workflow.state.calls) == before


def test_resume_cannot_turn_failed_software_evidence_into_a_pass_by_editing_the_summary(workflow):
    workflow.state.software_pass = False
    assert workflow.run("--model", "pyleecan-prius") == 1
    record = workflow.record()
    record["results"]["pyleecan-prius"]["result"]["status"] = "PASS"
    write(workflow.output / runner.STATE_FILE, record)
    before = len(workflow.state.calls)
    with pytest.raises(ValueError, match="summary differs"):
        workflow.run("--resume")
    assert len(workflow.state.calls) == before
