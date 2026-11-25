"""Phase G runner: one run at a time holds a work folder, and the record and its page are written together or not at
all. Every solve here is a stand-in, and every file written is in a temporary folder."""

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from backend.benchmark_suite import loss_phase_g as g
from tests._private_evidence import requires_private_evidence
from tools import run_phase_g

ROOT = Path(__file__).resolve().parents[1]
FIRST = {"commit": "a" * 40, "modified": False, "sha256": "1" * 64}
SECOND = {"commit": "b" * 40, "modified": False, "sha256": "2" * 64}
STATOR = {"iron_hysteresis_loss_W": 2.0, "iron_eddy_loss_W": 0.5, "iron_loss_W": 2.5, "copper_loss_W": 4.0,
          "phase_resistance_ohm": 0.1}
ROTOR = {"hysteresis_W": 0.02, "lamination_eddy_W": 0.08, "total_W": 0.1}

needs_stored_record = requires_private_evidence("benchmarks/g-v2.0/results/coilem.json", "benchmarks/g-v2.0/RESULTS.md",
                                                "benchmarks/g-v2.0/references")


def quiet(*_):
    pass


def solved_history(history_id: str) -> dict:
    rotor = g.spec()["rotor"]
    return {"id": history_id, "closure": {"max_T": 1e-12, "rms_T": 1e-13},
            "speeds": {str(speed): {str(count): dict(ROTOR) for count in rotor["position_counts"]}
                       for speed in rotor["evaluation_speeds_rpm"]}}


@pytest.fixture
def build(monkeypatch, tmp_path):
    """A stand-in build whose source identity a test can change, with counted solves that give complete values, graded
    against stand-in FEMM stator values equal to them and no FEMM rotor record."""
    binary = tmp_path / "magneto2d"
    binary.write_bytes(b"solver 1")
    state = {"source": dict(FIRST), "solved": []}
    monkeypatch.setattr(g, "_solver_binary", lambda: binary)
    monkeypatch.setattr(g, "source_identity", lambda: dict(state["source"]))

    def stator(row):
        state["solved"].append(row["id"])
        return {"id": row["id"], "stator": dict(STATOR)}

    def rotor(row, workers=4):
        state["solved"].append(row["id"])
        return solved_history(row["id"])

    monkeypatch.setattr(g, "solve_stator", stator)
    monkeypatch.setattr(g, "solve_rotor", rotor)
    monkeypatch.setattr(g, "reference", lambda row: dict(STATOR))
    monkeypatch.setattr(g, "rotor_references", lambda: {})
    return state


@pytest.fixture
def repo(monkeypatch, tmp_path):
    """The runner's repository root, moved to a temporary folder so that nothing in the checkout is written."""
    root = tmp_path / "repo"
    (root / run_phase_g.RESULTS).parent.mkdir(parents=True)
    monkeypatch.setattr(run_phase_g, "ROOT", root)
    return root


def files(root: Path) -> dict:
    """The files under ``root`` and their bytes. A lock file is left out: Windows refuses to read it while it is held."""
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != g.WORK_LOCK}


# -- One run at a time ----------------------------------------------------------------------------------------------


def test_a_second_run_cannot_take_the_work_folder_while_the_first_is_solving(tmp_path, build, monkeypatch):
    """The review's case: B opens the folder before A has saved its first point. B is refused at once, discarding
    included, and A's points stay A's."""
    work = tmp_path / "work"
    solve, refusals = g.solve_stator, []

    def first_point(row):
        if not refusals:
            assert json.loads((work / g.WORK_MANIFEST).read_text(encoding="utf-8"))["candidate"]["source"] == FIRST
            build["source"] = dict(SECOND)
            for discard in (False, True):
                with pytest.raises(g.WorkFolderBusy) as refused:
                    g.run(only="outer_spm", work=work, discard=discard, log=quiet)
                refusals.append(str(refused.value))
        return solve(row)

    monkeypatch.setattr(g, "solve_stator", first_point)
    first = g.run(only="outer_spm", work=work, log=quiet)
    assert len(refusals) == 2 and all(f"Another Phase G run is using the work folder {work}" in text
                                      and "nothing in it was changed" in text for text in refusals)
    # Only A solved, and the folder names A, holds A's points and no lock.
    names = {row["id"] for row in g.spec()["cases"] + g.spec()["rotor_histories"] if row["motor"] == "outer_spm"}
    assert sorted(build["solved"]) == sorted(names) and first["candidate"]["source"] == FIRST
    assert json.loads((work / g.WORK_MANIFEST).read_text(encoding="utf-8"))["candidate"]["source"] == FIRST
    assert not (work / g.WORK_LOCK).exists()
    # Once A has finished, B is told the points are another build's, as for runs one after the other.
    with pytest.raises(g.WorkFolderError, match="holds points solved by another build") as refused:
        g.run(only="outer_spm", work=work, log=quiet)
    assert not isinstance(refused.value, g.WorkFolderBusy)


def test_the_run_command_refuses_a_folder_another_run_holds_and_changes_nothing(tmp_path, build, capsys):
    work = tmp_path / "work"
    g.run(only="outer_spm", work=work, log=quiet)
    before = files(work)
    build["solved"].clear()
    with g.work_lock(work):
        assert run_phase_g.main(["--work", str(work), "--only", "outer_spm", "--discard-work"]) == 1
        output = capsys.readouterr().out
        assert f"Phase G: Another Phase G run is using the work folder {work}" in output and "another work folder" in output
        with pytest.raises(g.WorkFolderBusy):
            with g.work_lock(work):
                pass
    assert build["solved"] == [] and files(work) == before


def test_the_lock_is_released_when_a_run_ends_fails_or_is_refused(tmp_path, build, monkeypatch):
    work = tmp_path / "work"
    g.run(only="outer_spm", work=work, log=quiet)
    assert not (work / g.WORK_LOCK).exists()
    with g.work_lock(work) as lock:
        assert lock == work / g.WORK_LOCK and lock.exists()
    assert not lock.exists()

    def broken(row):
        raise RuntimeError("the solver stopped")

    other = tmp_path / "other"
    monkeypatch.setattr(g, "solve_stator", broken)
    with pytest.raises(RuntimeError, match="the solver stopped"):
        g.run(only="outer_spm", work=other, log=quiet)
    assert not (other / g.WORK_LOCK).exists()
    build["source"] = dict(SECOND)
    with pytest.raises(g.WorkFolderError, match="another build"):
        g.run(only="outer_spm", work=work, log=quiet)
    assert not (work / g.WORK_LOCK).exists()
    # Both folders can be taken again at once.
    with g.work_lock(work), g.work_lock(other):
        pass


HOLDER = """
import sys
from pathlib import Path

from backend.benchmark_suite import loss_phase_g as g

with g.work_lock(Path(sys.argv[1])):
    print("held", flush=True)
    sys.stdin.readline()
print("released", flush=True)
"""


def holder(work: Path) -> subprocess.Popen:
    """Another process that holds the work folder until told to stop."""
    process = subprocess.Popen([sys.executable, "-c", HOLDER, str(work)], cwd=ROOT, text=True,
                               env=os.environ | {"PYTHONPATH": str(ROOT)}, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        assert process.stdout.readline().strip() == "held"
    except BaseException:
        process.kill()
        process.wait(timeout=60)
        raise
    return process


def test_a_run_in_another_process_holds_the_folder_until_it_ends_or_dies(tmp_path, build):
    work = tmp_path / "work"
    process = holder(work)
    try:
        with pytest.raises(g.WorkFolderBusy, match="Another Phase G run is using the work folder"):
            g.run(only="outer_spm", work=work, log=quiet)
        assert build["solved"] == [] and not (work / g.WORK_MANIFEST).exists()
    finally:
        output, _ = process.communicate("\n", timeout=60)
    assert output.strip() == "released" and process.returncode == 0 and not (work / g.WORK_LOCK).exists()
    first = g.run(only="outer_spm", work=work, log=quiet)
    kept, solved = files(work), len(build["solved"])

    # A run that dies holding the folder leaves the lock file behind, but not the lock: the system releases it.
    process = holder(work)
    try:
        with pytest.raises(g.WorkFolderBusy):
            g.run(only="outer_spm", work=work, discard=True, log=quiet)
        assert files(work) == kept and (work / g.WORK_LOCK).exists()
    finally:
        process.kill()
        process.wait(timeout=60)
    assert (work / g.WORK_LOCK).exists()
    # Windows may take a moment to release a dead process's lock.
    deadline = time.monotonic() + 10
    while True:
        try:
            resumed = g.run(only="outer_spm", work=work, log=quiet)
            break
        except g.WorkFolderBusy:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
    assert resumed == first and len(build["solved"]) == solved and files(work) == kept


# -- Writing the record and the page --------------------------------------------------------------------------------


def stored_record(build) -> dict:
    """A complete record from the stand-in build, as a full run stores it."""
    registered = g.spec()
    return run_phase_g.record({
        "schema": "coilem.phase_g_result/v1", "protocol_version": registered["protocol_version"],
        "spec_sha256": g.spec_sha256(), "coilem_version": "0.0.0", "candidate": {},
        "cases": [{"id": row["id"], "stator": dict(STATOR)} for row in registered["cases"]],
        "rotor_histories": [solved_history(row["id"]) for row in registered["rotor_histories"]]})


def without(record: dict, history_id: str, speed: str, count: str) -> dict:
    damaged = copy.deepcopy(record)
    del next(row for row in damaged["rotor_histories"] if row["id"] == history_id)["speeds"][speed][count]
    return damaged


def store(root: Path, record: dict, page_text: str = "the page as it was\n") -> dict:
    (root / run_phase_g.RESULTS).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    (root / run_phase_g.PAGE).write_text(page_text, encoding="utf-8")
    return files(root)


@pytest.mark.parametrize("existing", [True, False])
def test_failed_page_replacement_restores_outputs_and_allows_retry(repo, build, monkeypatch, existing):
    record = stored_record(build)
    report = repo / run_phase_g.PAGE
    if existing:
        run_phase_g.write_outputs(record)
    before = files(repo)
    record["platform"] = "updated test platform"
    replace = os.replace

    def refuse_report(source, destination):
        if destination == report:
            raise PermissionError("report replacement refused")
        replace(source, destination)

    with pytest.raises(PermissionError):
        if sys.platform == "win32" and existing:
            with report.open("rb"):
                run_phase_g.write_outputs(record)
        else:
            with monkeypatch.context() as patch:
                patch.setattr(os, "replace", refuse_report)
                run_phase_g.write_outputs(record)
    assert files(repo) == before

    run_phase_g.write_outputs(record)
    assert json.loads((repo / run_phase_g.RESULTS).read_bytes()) == record
    assert run_phase_g.check() == []


def test_missing_grading_inputs_stop_before_any_solve(tmp_path, monkeypatch, capsys):
    def missing(case):
        raise FileNotFoundError(2, "missing reference", "registered-reference.json")

    monkeypatch.setattr(g, "reference", missing)
    monkeypatch.setattr(run_phase_g, "run", lambda **kwargs: pytest.fail("started a solve with missing references"))
    work = tmp_path / "work"
    assert run_phase_g.main(["--only", "inner_spm", "--skip-rotor", "--work", str(work)]) == 1
    assert "registered-reference.json" in capsys.readouterr().out
    assert not work.exists()


def test_a_full_run_writes_the_record_and_page_that_check_accepts(tmp_path, build, repo, capsys):
    assert run_phase_g.main(["--work", str(tmp_path / "work")]) == 0
    assert f"wrote {run_phase_g.RESULTS} and {run_phase_g.PAGE}" in capsys.readouterr().out
    written = files(repo)
    assert sorted(written) == [run_phase_g.PAGE, run_phase_g.RESULTS] and all(b"\r\n" not in text for text in written.values())
    assert run_phase_g.check() == []
    stored = json.loads(written[run_phase_g.RESULTS])
    assert stored["comparisons"]["stator_copper_vs_femm"] == {"PASS": 16, "FAIL": 0, "NOT_RUN": 0}
    assert stored["comparisons"]["rotor_own_checks"] == {"PASS": 16, "FAIL": 0, "NOT_RUN": 0}


def test_a_full_run_with_an_incomplete_record_writes_nothing(tmp_path, build, repo, monkeypatch, capsys):
    before = store(repo, stored_record(build))
    history_id = g.spec()["rotor_histories"][0]["id"]
    solve = g.solve_rotor

    def short_history(row, workers=4):
        solved = solve(row)
        if row["id"] == history_id:
            del solved["speeds"]["3000"]["192"]
        return solved

    monkeypatch.setattr(g, "solve_rotor", short_history)
    assert run_phase_g.main(["--work", str(tmp_path / "work")]) == 1
    output = capsys.readouterr().out
    assert f"Phase G: {history_id} does not hold every registered speed and position count" in output
    assert "so it was not stored" in output and "were left as they are" in output
    assert files(repo) == before


def test_a_full_run_whose_page_cannot_be_rendered_writes_nothing(tmp_path, build, repo, monkeypatch):
    before = store(repo, stored_record(build))

    def broken(result):
        raise KeyError("192")

    monkeypatch.setattr(run_phase_g, "page", broken)
    with pytest.raises(KeyError):
        run_phase_g.main(["--work", str(tmp_path / "work")])
    assert files(repo) == before


def test_regrade_refuses_an_incomplete_record_and_leaves_both_files(build, repo, capsys):
    """The review's case: the 192-position row removed. Neither file is touched."""
    history_id = g.spec()["rotor_histories"][1]["id"]
    before = store(repo, without(stored_record(build), history_id, "3000", "192"))
    assert run_phase_g.main(["--regrade"]) == 1
    output = capsys.readouterr().out
    assert f"Phase G: {history_id} does not hold every registered speed and position count" in output
    assert "so it was not regraded" in output
    assert files(repo) == before


def test_regrade_writes_both_files_or_neither(build, repo, monkeypatch, capsys):
    complete = stored_record(build)
    before = store(repo, complete | {"comparisons": {}})
    real_fsync, synced = os.fsync, []

    def full_disk(descriptor):
        synced.append(descriptor)
        if len(synced) == 2:
            raise OSError(28, "No space left on device")
        real_fsync(descriptor)

    # The record's temporary file is written; the page's is not. Neither replaces anything, and no temporary is left.
    with monkeypatch.context() as patched:
        patched.setattr(run_phase_g.os, "fsync", full_disk)
        with pytest.raises(OSError, match="No space left"):
            run_phase_g.main(["--regrade"])
    assert len(synced) == 2 and files(repo) == before
    with monkeypatch.context() as patched:
        patched.setattr(run_phase_g, "page", lambda result: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            run_phase_g.main(["--regrade"])
    assert files(repo) == before
    assert run_phase_g.main(["--regrade"]) == 0
    assert "regraded" in capsys.readouterr().out
    assert run_phase_g.check() == [] and json.loads(files(repo)[run_phase_g.RESULTS]) == complete


def test_the_page_names_a_missing_position_count_instead_of_failing(build, monkeypatch):
    registered = g.spec()
    history_id = registered["rotor_histories"][0]["id"]
    femm = solved_history(history_id) | {"solver": "FEMM 5"}
    monkeypatch.setattr(g, "rotor_references", lambda: {history_id: femm})
    complete = stored_record(build)
    for count in ("192", "384"):
        damaged = without(complete, history_id, "3000", count)
        damaged["comparisons"] = run_phase_g._rounded(g.compare(damaged))
        text = run_phase_g.page(damaged)
        case = next(row for row in registered["cases"] if row["rotor_history"] == history_id and row["speed_rpm"] == 3000)
        motor = next(row["description"] for row in registered["motors"] if row["id"] == case["motor"])
        assert f"Position counts missing from the record, so those rows fail: {motor}, " in text
        assert f"3000 rpm: {count}." in text
        rows = [line for line in text.splitlines() if line.startswith(f"| {motor} | ") and "| 3000 |" in line
                and "| missing |" in line]
        assert rows and all(line.endswith("| FAIL |") for line in rows)
    # Without the 384-position row the comparison with FEMM has nothing to show, and fails.
    assert any(line.endswith("| FEMM 5 | missing | n/a | n/a | n/a | n/a | FAIL |") for line in text.splitlines())
    # A complete record's page names nothing as missing.
    complete["comparisons"] = run_phase_g._rounded(g.compare(complete))
    assert "missing" not in run_phase_g.page(complete)


@needs_stored_record
def test_regrade_of_a_copy_of_the_stored_record(repo, capsys):
    """On a temporary copy of the stored record: without its 192-position row it is refused with both files left;
    complete, it is rewritten to the same bytes."""
    stored = json.loads((ROOT / g.RESULTS).read_text(encoding="utf-8"))
    original = {path: (ROOT / path).read_bytes() for path in (run_phase_g.RESULTS, run_phase_g.PAGE)}
    (repo / run_phase_g.RESULTS).write_text(json.dumps(without(stored, "inner_spm_loaded", "3000", "192"), indent=1) + "\n",
                                            encoding="utf-8")
    (repo / run_phase_g.PAGE).write_bytes(original[run_phase_g.PAGE])
    before = files(repo)
    assert run_phase_g.main(["--regrade"]) == 1
    assert "inner_spm_loaded does not hold every registered speed and position count" in capsys.readouterr().out
    assert files(repo) == before
    (repo / run_phase_g.RESULTS).write_bytes(original[run_phase_g.RESULTS])
    assert run_phase_g.main(["--regrade"]) == 0
    assert run_phase_g.check() == []
    assert {path: text.replace(b"\r\n", b"\n") for path, text in original.items()} == files(repo)
