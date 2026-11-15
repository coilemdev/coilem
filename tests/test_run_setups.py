"""Saved run setups in the Python client mirror the app's rules.

tests/fixtures/run_setup_parity.json is generated from the app's own
solveProfiles.ts by frontend/scripts/test-run-setup-parity.mjs (which also
fails `npm run test:public-ui` when the file is out of date), so these tests
hold the Python port to exactly what the app does.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from backend import client as coilem
from backend.client import _setups as setups
from backend.client import _solve

ROOT = Path(__file__).resolve().parents[1]
PARITY = json.loads((ROOT / "tests/fixtures/run_setup_parity.json").read_text(encoding="utf-8"))
DESIGNS = PARITY["designs"]


def _setup(name: str) -> setups.RunSetup:
    raw = PARITY["setups"][name]
    if raw.get("builtin"):
        return next(setup for setup in setups.REFERENCE_SETUPS if setup.id == raw["id"])
    return setups.parse_setup(raw)


def _design(name: str) -> dict:
    return copy.deepcopy(DESIGNS[name])


@pytest.mark.parametrize("case", PARITY["cases"], ids=lambda case: f"{case['design']}-{case['setup']}")
def test_setups_apply_and_match_as_in_the_app(case) -> None:
    body, setup = _design(case["design"]), _setup(case["setup"])
    assert (setups.incompatibility(setup, body) is None) is case["compatible"]
    assert setups.setup_matches(setup, body) is case["matches_saved"]
    if not case["compatible"]:
        with pytest.raises(coilem.InputError) as refused:
            setups.apply_setup(body, setup)
        assert refused.value.error_code == "SETUP_INCOMPATIBLE"
        return
    applied = setups.apply_setup(body, setup)
    picked = {
        "solve_params": applied["solve_params"],
        "solve_options": applied["solve_options"],
        "torque_speed_analysis": applied.get("torque_speed_analysis"),
        "reference_case": applied.get("reference_case"),
    }
    assert setups.same(picked, case["applied"]), picked
    assert setups.setup_matches(setup, applied) is case["matches_applied"]
    label = setup.label() if case["matches_applied"] else None
    assert label == case["provenance_applied"]
    assert body == DESIGNS[case["design"]], "applying a setup never changes the design it was given"


@pytest.mark.parametrize("case", PARITY["parse"], ids=lambda case: case["name"])
def test_saved_setups_are_read_or_refused_as_in_the_app(case) -> None:
    if not case["valid"]:
        with pytest.raises(setups.SetupFormatError):
            setups.parse_setup(case["raw"])
        return
    parsed = setups.parse_setup(case["raw"])
    expected = case["parsed"]
    assert (parsed.id, parsed.version, parsed.name, parsed.includes_numerics) == (
        expected["id"], expected["version"], expected["name"], expected["includesNumerics"],
    )
    assert setups.same(parsed.parameters, expected["parameters"]) and setups.same(parsed.outputs, expected["outputs"])
    assert setups.same(parsed.map, expected["map"]) and parsed.solver == expected.get("solver")


@pytest.mark.parametrize("case", PARITY["documents"], ids=lambda case: case["name"])
def test_setup_libraries_are_read_tolerantly_as_in_the_app(case) -> None:
    library = setups.read_setup_library(case["raw"])
    assert (library.error is not None, library.skipped, [setup.name for setup in library.setups]) == (
        case["error"], case["skipped"], case["names"],
    )


def test_the_reference_setups_are_the_apps_prius_references() -> None:
    names = {setup.id: setup.name for setup in setups.REFERENCE_SETUPS}
    assert names == {
        "builtin:prius-2004-tutorial-bemf-v1": "Prius · no-load BEMF reference",
        "builtin:prius-2004-loaded-torque-v1": "Prius · loaded torque reference",
    }
    assert all(setup.builtin and setup.kind == "reference" and setup.solver == "magneto2d" for setup in setups.REFERENCE_SETUPS)


# -- Which setup a solve uses ----------------------------------------------------------------


def test_a_requested_setup_is_applied_and_labelled() -> None:
    body, use = setups.resolve_setup(_design("starter"), "high speed")
    assert use.source == "requested" and use.setup.name == "High Speed" and not use.modified
    assert use.label == {"id": "user-high-speed", "version": 3, "name": "High Speed", "kind": "user", "includes_numerics": True}
    assert body["solve_params"]["current_amplitude_A"] == 20 and body["solve_params"]["solve_quality"] == "fine"
    assert setups.resolve_setup(_design("starter"), "user-high-speed")[1].setup.name == "High Speed", "ids work too"


def test_the_active_setup_labels_the_saved_settings_it_still_describes() -> None:
    saved = _design("high_speed_saved")
    body, use = setups.resolve_setup(saved, None)
    assert use.source == "active" and use.label["name"] == "High Speed" and use.notes == ()
    assert body == saved, "the saved settings are solved as saved"


def test_an_edited_active_setup_leaves_the_saved_settings_unlabelled() -> None:
    edited = _design("high_speed_edited")
    body, use = setups.resolve_setup(edited, None)
    assert use.source == "design" and use.setup is None and use.label is None
    assert body["solve_params"]["current_amplitude_A"] == 35, "the design file owns its settings, as in the app"
    assert "edited after it was chosen" in use.notes[0]


def test_a_design_without_setups_is_solved_as_saved() -> None:
    request = json.loads((ROOT / "benchmarks/abcd-v1.9/fixtures/spm_8p12s_concentrated__dq_I20_g30__native.json").read_text())
    body, use = setups.resolve_setup(request, None)
    assert body == request and use.source == "design" and use.notes == ()


def test_a_reference_setup_fits_only_the_unchanged_published_motor() -> None:
    prius = _design("prius_loaded")
    use = setups.resolve_setup(prius, "Prius · no-load BEMF reference")[1]
    assert use.label["kind"] == "reference"
    changed = copy.deepcopy(prius)
    changed["stator"]["stack_length_mm"] += 1
    with pytest.raises(coilem.InputError) as refused:
        setups.resolve_setup(changed, "Prius · no-load BEMF reference")
    assert refused.value.error_code == "SETUP_INCOMPATIBLE" and refused.value.field == "setup"
    names = [status.setup.name for status in setups.setup_statuses(_design("starter"))[0]]
    assert not any(name.startswith("Prius") for name in names), "references are listed only for their own motor"


@pytest.mark.parametrize(
    ("design", "requested", "code"),
    [
        ("starter", "No such setup", "SETUP_NOT_FOUND"),
        ("starter", "Elmer numerics", "SETUP_SOLVER_UNAVAILABLE"),
        ("starter", "Prius advanced angle", "SETUP_NOT_FOUND"),
        ("starter", "  ", "SETUP_NOT_FOUND"),
        ("lrk", "High Speed", "SETUP_NOT_FOUND"),
    ],
)
def test_a_requested_setup_that_cannot_be_used_is_refused_before_solving(design, requested, code) -> None:
    with pytest.raises(coilem.InputError) as refused:
        setups.resolve_setup(_design(design), requested)
    assert refused.value.error_code == code and refused.value.field == "setup"


def test_an_unreadable_saved_setup_is_named_as_such() -> None:
    body = _design("starter")
    newer = copy.deepcopy(body["run_setups"]["profiles"][0])
    newer.update(id="from-newer", name="From a newer coilEM", parameters={**newer["parameters"], "future_setting": 1})
    body["run_setups"]["profiles"].append(newer)
    with pytest.raises(coilem.InputError) as refused:
        setups.resolve_setup(body, "from a newer coilem")
    assert refused.value.error_code == "SETUP_UNREADABLE"
    assert "1 saved run setup could not be read" in setups.resolve_setup(body, None)[1].notes[0]


def test_an_unreadable_library_never_blocks_the_design() -> None:
    body = _design("high_speed_saved")
    body["run_setups"]["schema"] = 2
    solved, use = setups.resolve_setup(body, None)
    assert use.source == "design" and "could not be read" in use.notes[0]
    assert solved["solve_params"] == body["solve_params"]


def test_settings_given_with_the_solve_drop_the_setup_label() -> None:
    motor = coilem.Motor.from_request(_design("starter"))
    kept = coilem.prepare(motor, setup="High Speed")
    assert kept.setup.label is not None and not kept.setup.modified
    changed = coilem.prepare(motor, setup="High Speed", solve_params={"current_amplitude_A": 25})
    assert changed.setup.label is None and changed.setup.modified and changed.setup.source == "requested"
    assert changed.request["solve_params"]["current_amplitude_A"] == 25
    assert changed.request["solve_params"]["solve_quality"] == "fine", "the rest of the setup still applies"
    assert changed.effective_settings()["solve_params"] == changed.request["solve_params"]


def test_setups_lists_every_saved_setup_with_whether_it_can_be_used() -> None:
    statuses = coilem.setups(coilem.Motor.from_request(_design("high_speed_saved")))
    rows = {status.setup.name: (status.usable, status.active, status.matches_saved) for status in statuses}
    assert rows == {
        "High Speed": (True, True, True),
        "Hot operating point": (True, False, False),
        "Map, operating point only": (True, False, False),
        "Elmer numerics": (False, False, False),
    }
    listed = statuses[0].to_dict()
    assert listed["name"] == "High Speed" and listed["parameters"]["solve_quality"] == "fine" and listed["reason"] is None


def test_the_server_request_carries_the_setup_label_as_the_app_does(monkeypatch) -> None:
    sent = {}

    def fake_http(server, body, timeout_s):
        sent.update(body)
        return {"summary": {"avg_torque_Nm": 1.0}}

    monkeypatch.setattr(_solve, "_solve_over_http", fake_http)
    motor = coilem.Motor.from_request(_design("high_speed_saved"))
    result = coilem.solve(motor, server="http://127.0.0.1:1")
    assert sent["run_setup"]["name"] == "High Speed" and sent["run_setups"]["scope"] == "parity-library"
    assert "run_setups" not in sent["config"] and "openem_schema_version" not in sent["config"]
    assert result.setup["source"] == "active" and result.setup["run_setup"]["id"] == "user-high-speed"
    sent.clear()
    coilem.solve(coilem.Motor.from_request(_design("high_speed_edited")), server="http://127.0.0.1:1")
    assert "config" not in sent, "an unlabelled solve sends the design as before"


def test_a_requested_setup_reaches_the_solver_and_the_result(monkeypatch) -> None:
    solved = {}

    def fake_in_process(body, on_progress, *, fields=False):
        solved.update(body)
        return {"summary": {"avg_torque_Nm": 1.0}}

    monkeypatch.setattr(_solve, "_solve_in_process", fake_in_process)
    result = coilem.solve(coilem.Motor.from_request(_design("starter")), setup="Hot operating point")
    assert solved["solve_params"]["magnet_temperature_C"] == 120 and solved["solve_options"]["back_emf"] is False
    assert result.setup["name"] == "Hot operating point" and result.to_dict()["setup"] == result.setup


def test_a_sweep_starts_from_the_requested_setups_operating_point(monkeypatch) -> None:
    points = []

    def fake_in_process(body, on_progress, *, fields=False):
        points.append(body["solve_params"])
        return {"summary": {"avg_torque_Nm": 1.0}}

    monkeypatch.setattr(_solve, "_solve_in_process", fake_in_process)
    monkeypatch.setattr(_solve, "check_main_module", lambda: None)
    coilem.sweep(coilem.Motor.from_request(_design("starter")), current_A=[5, 10], setup="Hot operating point")
    assert [point["current_amplitude_A"] for point in points] == [5, 10]
    assert all(point["magnet_temperature_C"] == 120 and point["rated_speed_rpm"] == 1500 for point in points)
