"""Phase G: the registered files are intact, grading follows the limits, and a work folder only continues for the build
that solved its points. The stored record's own checks are in tests/private_records/test_phase_g_records.py."""

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from backend import rotor_loss_solver as rotor
from backend.benchmark_suite import loss_phase_g as g
from backend.models import MotorConfig
from tests._private_evidence import requires_private_evidence

ROOT = Path(__file__).resolve().parents[1]


# The FEMM references and the stored record are kept in the private repository (tools/release/private_evidence.py).
needs_stator_references = requires_private_evidence("benchmarks/g-v2.0/references/femm-stator-copper-20261117")
# The tests that check the stored record itself are kept privately, in tests/private_records/test_phase_g_records.py.


@needs_stator_references
def test_every_registered_fixture_and_femm_record_is_intact_and_describes_its_case():
    registered = g.spec()
    assert len(registered["cases"]) == 16 and len(registered["rotor_histories"]) == 8
    assert len({row["id"] for row in registered["cases"]}) == 16
    for case in registered["cases"]:
        config = g.fixture(case)
        params = config["solve_params"]
        assert params["rated_speed_rpm"] == case["speed_rpm"] and params["current_amplitude_A"] == case["current_peak_A"]
        assert params["symmetry"] == "full" and config["solve_options"]["losses_efficiency"] is True
        MotorConfig.model_validate(config)
        values = g.reference(case)
        assert values["iron_loss_W"] == pytest.approx(values["iron_hysteresis_loss_W"] + values["iron_eddy_loss_W"], rel=1e-9)
        assert (values["copper_loss_W"] == 0) == (case["current_peak_A"] == 0)
        assert case["rotor_history"] in {row["id"] for row in registered["rotor_histories"]}
    for history in registered["rotor_histories"]:
        config = MotorConfig.model_validate(g.fixture(history))
        assert config.solve_params.rated_speed_rpm == registered["rotor"]["collection_speed_rpm"]
        assert config.rotor_layout == history["rotor_layout"]
        # Every registered motor, the outrunner included, is one the rotor loss stage accepts.
        assert rotor.unavailable_reason(config) is None
    assert {row["rotor_layout"] for row in registered["rotor_histories"]} == {"inner", "outer"}
    assert rotor.POSITIONS == registered["rotor"]["positions"] == registered["rotor"]["position_counts"][-1]


@needs_stator_references
def test_a_changed_fixture_and_a_reference_for_another_point_are_refused():
    first, second = g.spec()["cases"][:2]
    with pytest.raises(ValueError, match="registered file"):
        g.fixture(first | {"fixture_sha256": "0" * 64})
    with pytest.raises(ValueError, match="another operating point"):
        g.reference(first | {"reference": second["reference"], "reference_sha256": second["reference_sha256"]})


def test_stator_grading_allows_ten_percent_or_one_milliwatt_and_one_percent_for_copper():
    gates = g.spec()["gates"]
    femm = {"iron_hysteresis_loss_W": 1.0, "iron_eddy_loss_W": 0.004, "iron_loss_W": 1.004, "copper_loss_W": 10.0,
            "phase_resistance_ohm": 0.05}
    inside = {"iron_hysteresis_loss_W": 1.09, "iron_eddy_loss_W": 0.0049, "iron_loss_W": 1.0949, "copper_loss_W": 10.09,
              "phase_resistance_ohm": 0.0504}
    graded = g.grade_stator(inside, femm, gates)
    assert graded["status"] == "PASS"
    # 0.9 mW on a 4 mW term is 22%, and passes on the 1 mW floor.
    assert graded["values"]["iron_eddy_loss_W"]["difference_pct"] == pytest.approx(22.5)
    for key, value in (("iron_hysteresis_loss_W", 1.11), ("copper_loss_W", 10.11), ("phase_resistance_ohm", 0.0494)):
        failed = g.grade_stator(inside | {key: value}, femm, gates)
        assert failed["status"] == "FAIL"
        assert [name for name, row in failed["values"].items() if row["status"] == "FAIL"] == [key]


def history(closure_max, totals):
    by_count = {str(count): {"hysteresis_W": total * 0.2, "lamination_eddy_W": total * 0.8, "total_W": total}
                for count, total in zip((96, 192, 384), totals)}
    return {"closure": {"max_T": closure_max, "rms_T": closure_max / 10}, "speeds": {"3000": by_count}}


def test_rotor_grading_needs_a_closed_turn_and_a_loss_that_has_stopped_changing():
    gates = g.spec()["gates"]
    settled = g.grade_rotor(history(1e-12, (0.100, 0.103, 0.104)), 3000, gates)
    assert settled["status"] == "PASS" and settled["values"]["total_W"] == 0.104 and settled["reference"] is None
    assert [step["status"] for step in settled["angular_steps"]] == ["PASS", "PASS"]
    # 10 W to 11 W is a 9% step: too large, whatever the later step does.
    moving = g.grade_rotor(history(1e-12, (10.0, 11.0, 11.1)), 3000, gates)
    assert moving["status"] == "FAIL" and [step["status"] for step in moving["angular_steps"]] == ["FAIL", "PASS"]
    # A 0.6 mW step on a 1 mW loss is 60% and still inside the 1 mW floor.
    assert g.grade_rotor(history(1e-12, (0.0004, 0.0009, 0.0010)), 3000, gates)["status"] == "PASS"
    open_turn = g.grade_rotor(history(1e-5, (0.100, 0.103, 0.104)), 3000, gates)
    assert open_turn["status"] == "FAIL" and open_turn["closure"] == "FAIL"


def test_rotor_grading_needs_every_registered_position_count():
    gates = g.spec()["gates"]
    full = history(1e-12, (0.100, 0.103, 0.104))
    femm = {"solver": "FEMM 5", "speeds": copy.deepcopy(full["speeds"])}

    def keeping(*counts):
        return full | {"speeds": {"3000": {count: row for count, row in full["speeds"]["3000"].items() if int(count) in counts}}}

    assert g.grade_rotor(full, 3000, gates, femm)["status"] == "PASS"
    # The 384-position row alone used to pass with no step graded.
    only_final = g.grade_rotor(keeping(384), 3000, gates, femm)
    assert only_final["status"] == "FAIL" and only_final["missing_positions"] == [96, 192]
    assert [(step["from"], step["to"], step["status"]) for step in only_final["angular_steps"]] == [(96, 192, "FAIL"), (192, 384, "FAIL")]
    no_intermediate = g.grade_rotor(keeping(96, 384), 3000, gates, femm)
    assert no_intermediate["status"] == "FAIL" and no_intermediate["missing_positions"] == [192]
    assert [step["status"] for step in no_intermediate["angular_steps"]] == ["FAIL", "FAIL"]
    assert no_intermediate["values"]["total_W"] == 0.104 and no_intermediate["reference"]["status"] == "PASS"
    no_coarse = g.grade_rotor(keeping(192, 384), 3000, gates, femm)
    assert no_coarse["status"] == "FAIL" and [step["status"] for step in no_coarse["angular_steps"]] == ["FAIL", "PASS"]
    # Without the 384-position row the FEMM comparison is a failure too, not one made at 192.
    no_final = g.grade_rotor(keeping(96, 192), 3000, gates, femm)
    assert no_final["status"] == "FAIL" and no_final["missing_positions"] == [384] and no_final["values"] is None
    assert [step["status"] for step in no_final["angular_steps"]] == ["PASS", "FAIL"]
    assert no_final["reference"] == {"solver": "FEMM 5", "status": "FAIL", "values": None}
    assert g.grade_rotor(keeping(96, 192), 3000, gates)["reference"] is None
    # A speed that was not solved has every count missing.
    assert g.grade_rotor(full, 1500, gates)["missing_positions"] == [96, 192, 384]
    # A count that is not registered is not graded, and does not replace 384 against FEMM.
    finer = full | {"speeds": {"3000": full["speeds"]["3000"] | {"768": {key: 1.0 for key in g.ROTOR_KEYS}}}}
    graded = g.grade_rotor(finer, 3000, gates, femm)
    assert graded["status"] == "PASS" and len(graded["angular_steps"]) == 2 and graded["values"]["total_W"] == 0.104
    assert graded["reference"]["values"]["total_W"]["coilem"] == 0.104


def analytic_report(angle):
    """One rotor-steel triangle whose field, seen from the rotor, has a third and a seventh harmonic of the turn."""
    corners = np.array([[10., 0.], [12., 0.], [11., 2.]])
    a = math.radians(angle)
    rotation = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    nodes = corners @ rotation.T
    material_b = np.array([0.2 + 0.1 * math.cos(3 * a), 0.05 * math.sin(7 * a)])
    global_b = material_b @ rotation.T
    az = (global_b[0] * nodes[:, 1] - global_b[1] * nodes[:, 0]) * 1e-3
    return {"mesh_info": {"total_span_deg": 360}, "solve_info": {"nonlinear_convergence": {
        "solution_reused": False, "tolerance": 1e-5, "scaled_residual": 1e-8,
        "rhs_scaled_residual": 1e-8, "absolute_residual_floor": 1e-12}},
        "field_plot": {"total_span_deg": 360, "nodes_mm": nodes.tolist(), "triangles": [[0, 1, 2]],
                       "regions": ["rotor_core"], "az_nodal": az.tolist()}}


def test_one_solved_turn_gives_the_loss_at_either_speed_and_at_fewer_positions():
    config = MotorConfig.model_validate(g.fixture(g.spec()["rotor_histories"][0]))
    angles = [-360 * k / 32 for k in range(33)]
    samples = [rotor.field_sample(analytic_report(angle), angle) for angle in angles]
    mass = 2e-6 * config.stator.stack_length_mm * 1e-3 * rotor.MATERIAL.coefficients.density_kg_m3
    c = rotor.MATERIAL.coefficients

    def expected(mechanical_hz):
        f3, f7 = 3 * mechanical_hz, 7 * mechanical_hz
        return (mass * c.kh * (f3 * 0.1**c.alpha + f7 * 0.05**c.alpha), mass * c.kc * (f3**2 * 0.1**2 + f7**2 * 0.05**2))

    history = g.rotor_history(samples, speed_rpm=3000, direction=-1)
    for speed in (3000, 1500):
        got = g.rotor_losses(config, history, speed_rpm=speed, positions=32)
        hysteresis, eddy = expected(speed / 60)
        assert got["hysteresis_W"] == pytest.approx(hysteresis, rel=1e-10)
        assert got["lamination_eddy_W"] == pytest.approx(eddy, rel=1e-10)
        assert got["total_W"] == pytest.approx(hysteresis + eddy, rel=1e-10)
    # Sixteen positions still resolve the seventh harmonic. Eight do not, and the loss changes.
    assert g.rotor_losses(config, history, speed_rpm=3000, positions=16)["total_W"] == pytest.approx(sum(expected(50)), rel=1e-10)
    assert g.rotor_losses(config, history, speed_rpm=3000, positions=8)["total_W"] < 0.9 * sum(expected(50))
    with pytest.raises(ValueError, match="do not divide"):
        g.rotor_losses(config, history, speed_rpm=3000, positions=12)


# -- The work folder ------------------------------------------------------------------------------------------


def quiet(*_):
    pass


@pytest.fixture
def build(monkeypatch, tmp_path):
    """A stand-in build: a Magneto2D executable and a source identity a test can change, and solves that are counted."""
    binary = tmp_path / "magneto2d"
    binary.write_bytes(b"solver 1")
    state = {"source": {"commit": "a" * 40, "modified": False, "sha256": "1" * 64}, "solved": [], "binary": binary}
    monkeypatch.setattr(g, "_solver_binary", lambda: binary)
    monkeypatch.setattr(g, "source_identity", lambda: dict(state["source"]))

    def stator(row):
        state["solved"].append(row["id"])
        return {"id": row["id"], "stator": {"iron_loss_W": 1.0}}

    def rotor_history_solve(row, workers=4):
        state["solved"].append(row["id"])
        return {"id": row["id"], "speeds": {}}

    monkeypatch.setattr(g, "solve_stator", stator)
    monkeypatch.setattr(g, "solve_rotor", rotor_history_solve)
    return state


def test_a_work_folder_continues_only_for_the_build_that_solved_its_points(tmp_path, build, monkeypatch):
    work = tmp_path / "work"
    first = g.run(only="outer_spm", work=work, log=quiet)
    assert len(build["solved"]) == 6 and (work / g.WORK_MANIFEST).is_file()
    assert first["candidate"]["solver_sha256"] == g._sha256(build["binary"]) and first["candidate"]["source"] == build["source"]
    # The same build continues: nothing is solved again.
    assert g.run(only="outer_spm", work=work, log=quiet) == first and len(build["solved"]) == 6
    kept = {path.name: path.read_bytes() for path in work.iterdir()}

    def refused(match):
        with pytest.raises(g.WorkFolderError, match=match):
            g.run(only="outer_spm", work=work, log=quiet)
        assert len(build["solved"]) == 6 and {path.name: path.read_bytes() for path in work.iterdir()} == kept

    build["binary"].write_bytes(b"solver 2, after a fix")
    refused(r"What differs: the Magneto2D executable\. Use a new work folder, or run again with --discard-work")
    build["binary"].write_bytes(b"solver 1")
    build["source"] = {"commit": "b" * 40, "modified": False, "sha256": "2" * 64}
    refused(r"the source commit \(aaaaaaaaaa there, bbbbbbbbbb here\); the Python sources")
    # An uncommitted edit at the same commit is another build too.
    build["source"] = {"commit": "a" * 40, "modified": True, "sha256": "3" * 64}
    refused(r"local changes to the sources \(no there, yes here\); the Python sources")
    build["source"] = {"commit": "a" * 40, "modified": False, "sha256": "1" * 64}
    # A Gmsh upgrade can change a mesh with every source unchanged.
    with monkeypatch.context() as upgraded:
        upgraded.setattr(g, "_version", lambda name: "99.0")
        refused(r"the gmsh version \(\S+ there, 99\.0 here\); the meshio version")
    assert g.run(only="outer_spm", work=work, log=quiet) == first and len(build["solved"]) == 6


def test_a_work_folder_without_a_record_of_its_build_is_refused_until_discarded(tmp_path, build):
    work = tmp_path / "work"
    work.mkdir()
    case_id = next(row["id"] for row in g.spec()["cases"] if row["motor"] == "outer_spm")
    (work / f"stator-{case_id}.json").write_text(json.dumps({"id": case_id, "stator": {"iron_loss_W": 9.0}}), encoding="utf-8")
    (work / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(g.WorkFolderError, match="no candidate.json naming the build that solved them"):
        g.run(only="outer_spm", work=work, log=quiet)
    assert build["solved"] == []
    result = g.run(only="outer_spm", work=work, discard=True, log=quiet)
    assert len(build["solved"]) == 6 and all(row["stator"] == {"iron_loss_W": 1.0} for row in result["cases"])
    assert (work / "notes.txt").read_text(encoding="utf-8") == "mine" and (work / g.WORK_MANIFEST).is_file()
    # A folder with a record but no points yet is taken over by whichever build solves into it first.
    other = tmp_path / "other"
    other.mkdir()
    (other / g.WORK_MANIFEST).write_text(json.dumps({"schema": g.WORK_SCHEMA, "candidate": {"source": {}}}), encoding="utf-8")
    g.run(only="outer_spm", rotor=False, work=other, log=quiet)
    assert json.loads((other / g.WORK_MANIFEST).read_text(encoding="utf-8"))["candidate"]["source"] == build["source"]


def test_a_point_whose_write_was_interrupted_is_solved_again_and_the_others_are_kept(tmp_path, build, monkeypatch):
    work = tmp_path / "work"
    cases = [row["id"] for row in g.spec()["cases"] if row["motor"] == "outer_spm"]
    solve = g.solve_stator

    def stopped_while_writing(row):
        value = solve(row)
        # json.dump has written part of the file when it reaches this.
        return value | {"stator": {"iron_loss_W": 1.0, "later": object()}} if row["id"] == cases[2] else value

    monkeypatch.setattr(g, "solve_stator", stopped_while_writing)
    with pytest.raises(TypeError):
        g.run(only="outer_spm", rotor=False, work=work, log=quiet)
    assert sorted(path.name for path in work.iterdir()) == sorted([g.WORK_MANIFEST, *(f"stator-{case}.json" for case in cases[:2])])
    monkeypatch.setattr(g, "solve_stator", solve)
    build["solved"].clear()
    result = g.run(only="outer_spm", rotor=False, work=work, log=quiet)
    assert build["solved"] == cases[2:] and [row["id"] for row in result["cases"]] == cases


def test_the_source_identity_follows_the_files_as_they_are(tmp_path, monkeypatch):
    for name in ("backend/solver.py", "backend/data.json", "coilem/__init__.py", "materials/steel.csv", "backend/notes.txt"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(name, encoding="utf-8")
    monkeypatch.setattr(g, "ROOT", tmp_path)
    before = g.source_identity()
    (tmp_path / "backend" / "notes.txt").write_text("not a source", encoding="utf-8")
    (tmp_path / "backend" / "__pycache__").mkdir()
    (tmp_path / "backend" / "__pycache__" / "solver.py").write_text("cached", encoding="utf-8")
    assert g.source_identity() == before
    (tmp_path / "materials" / "steel.csv").write_text("an edit that is not committed", encoding="utf-8")
    assert g.source_identity()["sha256"] != before["sha256"]


def test_the_run_command_says_why_it_refuses_a_work_folder(tmp_path, build, capsys):
    from tools.run_phase_g import main

    work = tmp_path / "work"
    g.run(only="outer_spm", work=work, log=quiet)
    build["binary"].write_bytes(b"solver 2")
    assert main(["--work", str(work), "--only", "outer_spm"]) == 1
    output = capsys.readouterr().out
    assert "holds points solved by another build. What differs: the Magneto2D executable." in output and "--discard-work" in output
