"""Collection failures and frozen grading policy, using no native field solves."""

from __future__ import annotations

import copy
import gzip
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.benchmark_suite.contract import read, sha, write
from tools import benchmark_prius as runner
from tools import report_prius_benchmark as reporter
from tools.prius_benchmark_contract import GRADING_INPUTS, LEGACY_SCHEMA, SCHEMA, freeze_inputs, grading_inputs, job_folder

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.pr


@pytest.fixture
def collection(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    for name in GRADING_INPUTS.values():
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    binary = tmp_path / "solver"
    binary.write_bytes(b"original executable")
    source = checkout / "source.py"
    source.write_bytes(b"original source")
    state = SimpleNamespace(calls=[], fail_calls=set(), during=None, commit="a" * 40, dirty=False)

    def identity():
        return {"commit": state.commit, "dirty": state.dirty, "binary_sha256": sha(binary),
                "source_files": {"source.py": sha(source)}, "collector_source_sha256": {},
                "platform": "test", "python": "test", "dependencies": {}}

    def solve(config, progress):
        state.calls.append(config.reference_case)
        if state.during:
            state.during()
        if len(state.calls) in state.fail_calls:
            raise RuntimeError("simulated solve failure")
        cache = tmp_path / f"cache-{len(state.calls)}"
        cache.mkdir()
        (cache / "field.json").write_bytes(b'{"mocked_field": true}')
        raw = {"summary": {"avg_torque_Nm": 1.}, "solve_metadata": {"solve_cache_dir": str(cache)},
               "torque_waveform": {"torque_Nm": [1.]},
               "back_emf_waveform": {"phase_a_V": [0.], "phase_b_V": [0.], "phase_c_V": [0.]}}
        return SimpleNamespace(
            model_dump=lambda **kwargs: copy.deepcopy(raw),
            solve_metadata=SimpleNamespace(solve_cache_dir=str(cache), rotor_positions=1),
            back_emf_waveform=SimpleNamespace(phase_a_V=[0.], phase_b_V=[0.], phase_c_V=[0.]),
            summary=SimpleNamespace(avg_torque_Nm=1., back_emf_fundamental_V=0.),
        )

    monkeypatch.setattr(runner, "ROOT", checkout)
    monkeypatch.setattr(runner, "current_identity", identity)
    monkeypatch.setattr(runner, "solve_config", solve)
    output = tmp_path / "run"
    return SimpleNamespace(root=checkout, output=output, binary=binary, source=source, state=state, identity=identity,
                           run=lambda *args: runner.main(["--out", str(output), *args]),
                           registration=lambda: read(output / "registration.json"))


def test_collection_pins_inputs_and_job_identities_and_restores_environment(collection, monkeypatch):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", "original-data-location")
    monkeypatch.delenv("COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS", raising=False)
    collection.run()
    import os

    reg = collection.registration()
    assert reg["schema"] == SCHEMA and reg["status"] == "COMPLETE" and reg["complete"]
    assert len(reg["jobs"]) == 2
    assert all(job["identity_before"] == job["identity_after"] == reg["identity"] for job in reg["jobs"])
    assert all(state["status"] == "COMPLETE" for state in reg["job_states"].values())
    _, provenance = grading_inputs(collection.output, reg)
    assert provenance["frozen_before_fields"] and len(provenance["input_sha256"]) == 5
    assert os.environ["COILEM_USER_DATA_ROOT"] == "original-data-location"
    assert "COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS" not in os.environ


@pytest.mark.parametrize("change", ["binary", "source", "commit", "dirty"])
def test_identity_changes_during_a_solve_never_produce_a_completed_job(collection, change):
    def mutate():
        if change in ("binary", "source"):
            getattr(collection, change).write_bytes(b"changed during solve")
        elif change == "commit":
            collection.state.commit = "b" * 40
        else:
            collection.state.dirty = True

    collection.state.during = mutate
    with pytest.raises(ValueError, match="identity changed"):
        collection.run()
    reg = collection.registration()
    assert not reg["complete"] and reg["status"] == "FAILED" and not reg["jobs"]
    assert next(iter(reg["job_states"].values()))["attempts"][0]["status"] == "FAILED"


def test_identity_is_checked_before_the_next_job(collection, monkeypatch):
    original = runner.write

    def change_after_completed_write(path, value):
        original(path, value)
        if path.name == "registration.json" and len(value.get("jobs", [])) == 1:
            collection.binary.write_bytes(b"rebuilt between jobs")

    monkeypatch.setattr(runner, "write", change_after_completed_write)
    with pytest.raises(ValueError, match="identity changed"):
        collection.run()
    assert len(collection.state.calls) == 1
    assert not collection.registration()["complete"]


def test_resume_restores_full_selection_and_reuses_only_verified_completed_jobs(collection):
    collection.state.fail_calls = {2}
    with pytest.raises(RuntimeError, match="simulated solve failure"):
        collection.run("--curve", "--refinement")
    failed = collection.registration()
    first = copy.deepcopy(failed["jobs"][0])
    first_hash = sha(job_folder(collection.output, first) / "result.json")
    collection.run("--resume")
    resumed = collection.registration()
    assert resumed["complete"] and len(resumed["jobs"]) == 17 and len(collection.state.calls) == 18
    assert resumed["jobs"][0] == first and sha(job_folder(collection.output, first) / "result.json") == first_hash
    attempts = resumed["job_states"]["loaded-torque-32"]["attempts"]
    assert [entry["status"] for entry in attempts] == ["FAILED", "COMPLETE"]
    assert (collection.output / attempts[0]["directory"]).is_dir()
    assert attempts[0]["directory"] != attempts[1]["directory"]
    collection.run("--resume")
    assert len(collection.state.calls) == 18, "An already complete verified run executes no fields"


def test_resume_recovers_an_interrupted_attempt_without_overwriting_it(collection):
    collection.state.fail_calls = {2}
    with pytest.raises(RuntimeError):
        collection.run()
    reg = collection.registration()
    reg["status"] = "RUNNING"
    state = reg["job_states"]["loaded-torque-32"]
    state["status"] = state["attempts"][-1]["status"] = "RUNNING"
    write(collection.output / "registration.json", reg)
    collection.run("--resume")
    attempts = collection.registration()["job_states"]["loaded-torque-32"]["attempts"]
    assert [entry["status"] for entry in attempts] == ["INTERRUPTED", "COMPLETE"]
    assert len(collection.state.calls) == 3


@pytest.mark.parametrize("file", ["request.json", "result.json", "result-original.json", "environment.json", "artifact-index.json", "retained"])
def test_resume_refuses_changed_completed_artifacts(collection, file):
    collection.run()
    reg = collection.registration()
    folder = job_folder(collection.output, reg["jobs"][0])
    if file == "retained":
        with gzip.open(folder / "retained/field.json.gz", "wb") as stream:
            stream.write(b"changed raw field")
    else:
        with (folder / file).open("ab") as stream:
            stream.write(b"\n")
    with pytest.raises(ValueError, match="artifact changed"):
        collection.run("--resume")
    assert len(collection.state.calls) == 2


@pytest.mark.parametrize("change", ["binary", "source", "commit"])
def test_resume_refuses_changed_execution_identity(collection, change):
    collection.run()
    if change == "commit":
        collection.state.commit = "b" * 40
    else:
        getattr(collection, change).write_bytes(b"changed after run")
    with pytest.raises(ValueError, match="identity changed"):
        collection.run("--resume")
    assert len(collection.state.calls) == 2


def test_resume_refuses_changed_selection(collection):
    collection.run("--only", "tutorial-bemf-100")
    with pytest.raises(ValueError, match="selection differs"):
        collection.run("--resume", "--only", "loaded-torque-32")
    assert len(collection.state.calls) == 1


def test_resume_refuses_changed_registered_request(collection, monkeypatch):
    collection.run()
    original = runner.jobs

    def changed_jobs(*args):
        for name, config in original(*args):
            config["solve_params"]["current_amplitude_A"] += 1
            yield name, config

    monkeypatch.setattr(runner, "jobs", changed_jobs)
    with pytest.raises(ValueError, match="requests differ"):
        collection.run("--resume")
    assert len(collection.state.calls) == 2


def test_frozen_input_mutation_blocks_completion_and_resume(collection):
    path = collection.output / "frozen-inputs/protocol.json"
    collection.state.during = lambda: path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen grading input changed"):
        collection.run()
    assert not collection.registration()["complete"]
    collection.state.during = None
    with pytest.raises(ValueError, match="Frozen grading input changed"):
        collection.run("--resume")
    assert len(collection.state.calls) == 1


def test_dirty_checkout_and_legacy_resume_are_rejected_before_solving(collection):
    collection.state.dirty = True
    with pytest.raises(ValueError, match="clean committed"):
        collection.run()
    assert not collection.state.calls
    write(collection.output / "registration.json", {"schema": LEGACY_SCHEMA})
    with pytest.raises(ValueError, match="Legacy registrations cannot resume"):
        collection.run("--resume")


@pytest.fixture
def analysis_fixture(collection, monkeypatch):
    """Published waves isolate grading-policy tests; field auditing has its own tests."""
    published = ROOT / "docs/benchmarks/pyleecan-prius-v1"
    reg = read(published / "app-registration.json")
    actual = read(published / "app-results.json")
    collection.output.mkdir()
    frozen = freeze_inputs(collection.root, collection.output)
    identity = collection.identity()
    for job in reg["jobs"]:
        folder = collection.output / job["job"]
        folder.mkdir()
        result = {"summary": {"avg_torque_Nm": job["metrics"]["mean_torque_Nm"]},
                  **{key: job[key] for key in ("torque_waveform", "back_emf_waveform", "solve_metadata")}}
        for name, value in [("request.json", job["request"]), ("environment.json", job["environment"]),
                            ("result.json", result), ("result-original.json", result), ("artifact-index.json", [])]:
            write(folder / name, value)
        for name, key in [("request.json", "request_sha256"), ("environment.json", "environment_sha256"),
                          ("result.json", "result_sha256"), ("result-original.json", "result_original_sha256"),
                          ("artifact-index.json", "artifact_index_sha256")]:
            job[key] = sha(folder / name)
        job.update(identity_before=identity, identity_after=identity)
    reg.update(schema=SCHEMA, status="COMPLETE", frozen_inputs=frozen, identity=identity, binary_sha256=identity["binary_sha256"],
               source_commit=identity["commit"], source_dirty=False, source_sha256=identity["source_files"],
               platform=identity["platform"], python=identity["python"], dependencies=identity["dependencies"])
    write(collection.output / "registration.json", reg)
    monkeypatch.setattr(reporter, "ROOT", collection.root)
    monkeypatch.setattr(reporter, "audit_job", lambda run, job, asset: actual["audits"][job["job"]])
    return collection


def test_analysis_uses_frozen_protocol_and_reference_bytes_when_checkout_changes(analysis_fixture):
    fixture = analysis_fixture
    before = reporter.analyze(fixture.output)
    for key, relative in GRADING_INPUTS.items():
        (fixture.root / relative).write_text("{}", encoding="utf-8")
    after = reporter.analyze(fixture.output)
    assert before == after
    assert after["all_software_checks_pass"] and after["grading_provenance"]["frozen_before_fields"]
    assert "frozen-at-collection" in reporter.markdown(after)


@pytest.mark.parametrize("key", list(GRADING_INPUTS))
def test_analysis_refuses_modified_frozen_grading_inputs(analysis_fixture, key):
    fixture = analysis_fixture
    reg = fixture.registration()
    (fixture.output / reg["frozen_inputs"][key]["file"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen grading input changed"):
        reporter.analyze(fixture.output)


def test_legacy_reanalysis_requires_opt_in_and_labels_post_hoc_policy(analysis_fixture):
    fixture = analysis_fixture
    reg = fixture.registration()
    reg["schema"] = LEGACY_SCHEMA
    reg.pop("frozen_inputs")
    write(fixture.output / "registration.json", reg)
    with pytest.raises(ValueError, match="legacy-unpinned"):
        reporter.analyze(fixture.output)
    data = reporter.analyze(fixture.output, legacy_unpinned=True)
    assert data["grading_provenance"]["mode"] == "legacy-unpinned-reanalysis"
    assert not data["grading_provenance"]["frozen_before_fields"]
    assert "Post-hoc reanalysis" in data["interpretation"]
    assert "Post-hoc reanalysis" in reporter.markdown(data)


@pytest.mark.parametrize("field", ["source_commit", "source_sha256", "binary_sha256"])
def test_analysis_rejects_inconsistent_execution_provenance(analysis_fixture, field):
    fixture = analysis_fixture
    reg = fixture.registration()
    reg[field] = "changed"
    write(fixture.output / "registration.json", reg)
    with pytest.raises(ValueError, match="frozen execution identity"):
        reporter.analyze(fixture.output)


def test_resume_recovers_a_failed_completion_write(collection, monkeypatch):
    original = runner.write
    failed = False

    def fail_once(path, value):
        nonlocal failed
        if path.name == "registration.json" and value.get("jobs") and not failed:
            failed = True
            raise OSError("simulated registration write failure")
        original(path, value)

    monkeypatch.setattr(runner, "write", fail_once)
    with pytest.raises(OSError, match="registration write failure"):
        collection.run()
    assert collection.registration()["jobs"] == []
    collection.run("--resume")
    assert collection.registration()["complete"] and len(collection.state.calls) == 3
