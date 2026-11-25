"""Benchmark Phase H (thermal): the frozen cases, coilEM's stored answers and the grading.

The checks of the stored FEMM 5 references and of coilEM's grades against them are kept privately with those
references, in tests/private_records/test_thermal_records.py.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from backend.benchmark_suite import thermal_phase_h
from backend.benchmark_suite.thermal_phase_h import RESULTS, compare, design, grade, planar_problem, references, run, spec
from tests._private_evidence import requires_private_evidence, skip_without_private_evidence
from tools.run_phase_h import PAGE, page, record, request

ROOT = Path(__file__).resolve().parents[1]
RERUN = "run python -m tools.run_phase_h and review what moved"
# The FEMM 5 answers to the 21 in-plane cases, kept in the private repository.
needs_femm_references = requires_private_evidence("benchmarks/h-v1.0/references/femm5")


@pytest.fixture(scope="module")
def fresh():
    return record()


@pytest.fixture(scope="module")
def stored():
    skip_without_private_evidence(RESULTS, PAGE)
    return json.loads((ROOT / RESULTS).read_text(encoding="utf-8"))


def test_the_specification_is_complete_and_its_fixtures_are_the_frozen_ones():
    registered = spec()
    assert registered["protocol_version"] == "H-1.0.0" and registered["phase"] == "H"
    assert len(registered["designs"]) == 7 and len(registered["cases"]) == 42
    assert {row["layout"] for row in registered["designs"]} == {"inner", "outer"}
    split = registered["heat_split"]
    for row in registered["designs"]:
        design(row["id"])  # refuses a fixture that differs from its registered hash
    for row in registered["cases"]:
        layout = next(d["layout"] for d in registered["designs"] if d["id"] == row["design"])
        assert row["phase"] == "H" and row["cooling"] in registered["cooling"][layout] and row["scope"] in ("in_plane", "full")
        total = sum(row["heat_W"].values())
        for part, share in split.items():
            assert row["heat_W"][part] == pytest.approx(total * share / sum(split.values()), rel=2e-3)
    # The two scopes of a design and cooling level take the same heat, so they can be read side by side.
    for row in registered["cases"]:
        if row["scope"] == "full":
            sibling = thermal_phase_h.case(row["id"].replace("__full", "__in_plane"))
            assert sibling["heat_W"] == row["heat_W"]


def test_every_case_balances_its_heat_and_reports_where_it_leaves(fresh):
    for row in fresh["cases"]:
        assert abs(row["energy_balance_W"]) < 1e-6 * max(1.0, row["total_heat_W"])
        assert sum(row["exit_W"].values()) == pytest.approx(row["total_heat_W"], rel=1e-6)
        assert set(row["exit_W"]) == ({"mount", "shell"} if row["layout"] == "outer" else {"housing"})
        if row["scope"] == "in_plane":
            # No end windings in a flat cross-section: no heat there, and the heat sets the winding near 80 K of rise.
            assert row["end_winding_heat_W"] == 0
            assert row["temperature_C"]["winding"] - fresh["surroundings_C"] == pytest.approx(80, abs=1)
        else:
            assert 0 < row["end_winding_heat_W"] < row["heat_W"]["winding"]


def test_the_record_writes_a_zero_balance_the_same_way_on_every_platform():
    from tools.run_phase_h import plain_zeros

    # Windows and macOS can round a vanishing balance to -0.0 and 0.0; the record is compared as text.
    written = json.dumps(plain_zeros({"energy_balance_W": -0.0, "cases": [{"a": -0.0, "b": -1e-12, "c": [0.0, -0.0]}]}))
    assert "-0.0" not in written and json.loads(written)["cases"][0]["b"] == -1e-12
    assert math.copysign(1, plain_zeros(-0.0)) == 1 and plain_zeros(-2.5) == -2.5 and plain_zeros(True) is True


def test_stronger_cooling_takes_more_heat_for_the_same_winding_temperature(fresh):
    heat = {(row["design"], row["cooling"]): row["total_heat_W"] for row in fresh["cases"] if row["scope"] == "in_plane"}
    for (name, cooling), watts in heat.items():
        if cooling == "still_air":
            assert all(other > watts for (n, c), other in heat.items() if n == name and c != "still_air")


def test_the_stored_record_and_page_are_what_this_build_gives(fresh, stored):
    assert stored["spec_sha256"] == fresh["spec_sha256"], RERUN
    for now, then in zip(fresh["cases"], stored["cases"], strict=True):
        assert then["id"] == now["id"]
        for part, value in now["temperature_C"].items():
            assert then["temperature_C"][part] == pytest.approx(value, abs=1e-3), f"{now['id']} {part}: {RERUN}"
    assert (ROOT / PAGE).read_text(encoding="utf-8") == page(stored), RERUN


@needs_femm_references
def test_the_reference_was_given_the_problem_this_build_states():
    # FEMM's answer stands for the problem it was given. If this build now states another, it must be solved again.
    for case_id, bundle in references()["femm5"].items():
        problem = planar_problem(thermal_phase_h.case(case_id))
        for name, value in bundle["given"]["conductivity_W_mK"].items():
            assert problem["conductivity_W_mK"][name] == pytest.approx(value, rel=1e-9), "re-run python -m tools.phase_h_femm"
        for name, face in bundle["given"]["faces"].items():
            assert problem["faces"][name]["h_W_m2K"] == pytest.approx(face["h_W_m2K"], rel=1e-9), "re-run python -m tools.phase_h_femm"


def test_grading_uses_the_registered_band_on_the_rise_above_the_surroundings():
    result = {"id": "x", "total_heat_W": 10.0, "temperature_C": {"winding": 105.0, "teeth": 60.0}, "exit_W": {"housing": 10.0}}

    def status(winding_reference):
        return grade(result, {"tool": "T", "temperature_C": {"winding": winding_reference}})["status"]

    assert status(100.0) == "PASS"      # 5 K on a 75 K rise: inside 10%
    assert status(96.0) == "YELLOW"     # 9 K on a 71 K rise: between one and two bands
    assert status(85.0) == "FAIL"       # 20 K on a 60 K rise
    # Near the surroundings the 2 K floor applies, so a small rise cannot make the band vanish.
    near = grade({**result, "temperature_C": {"winding": 28.5}}, {"tool": "T", "temperature_C": {"winding": 27.0}})
    assert near["status"] == "PASS" and near["parts"][0]["band_K"] == 2.0
    # A part the reference does not report is not graded, and a reference with no shared part compares nothing.
    assert grade(result, {"tool": "T", "temperature_C": {"shaft": 50.0}})["status"] == "NOT_COMPARED"


def test_a_reference_for_another_specification_is_refused(tmp_path, monkeypatch):
    folder = tmp_path / "other-tool"
    folder.mkdir()
    (folder / "case.json").write_text(json.dumps({"case_id": "x", "spec_sha256": "0" * 64, "tool": "T", "temperature_C": {}}))
    monkeypatch.setattr(thermal_phase_h, "REFERENCES", str(tmp_path))
    with pytest.raises(ValueError, match="different Phase H specification"):
        references()


def test_a_request_states_the_whole_in_plane_problem():
    exported = request("outrunner_14p12s__still_air__in_plane")
    assert set(exported["cooled_faces"]) == {"mount", "shell"}
    assert {region["material"] for region in exported["regions"]} >= {"winding", "teeth", "yoke", "gap", "magnets", "rotor"}
    assert sum(exported["heat_W"].values()) == pytest.approx(5.59, abs=0.01)
    with pytest.raises(ValueError, match="in_plane"):
        request("outrunner_14p12s__still_air__full")


@needs_femm_references
def test_compare_marks_cases_without_a_reference(fresh):
    graded = compare(run())["femm5"]
    assert {row["status"] for row in graded["cases"] if "__full" in row["case_id"]} == {"NOT_COMPARED"}
    assert len(graded["cases"]) == len(fresh["cases"])
