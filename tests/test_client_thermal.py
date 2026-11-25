"""The thermal estimate from scripts: ``coilem thermal`` and the Python client's ``thermal``."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend import client as coilem
from backend.client import _cli, _solve
from backend.client._thermal import COEFFICIENTS, PART_ORDER, STILL_AIR_STARTER, thermal_inputs
from backend.models import IronLoss

ROOT = Path(__file__).resolve().parents[1]
PARITY = json.loads((ROOT / "tests/fixtures/run_setup_parity.json").read_text(encoding="utf-8"))
OUTRUNNER = ROOT / "frontend/src/public/examples/spm_outrunner_14p12s.coilem"


@pytest.fixture
def design(tmp_path) -> Path:
    path = tmp_path / "motor.coilem"
    path.write_text(json.dumps(PARITY["designs"]["high_speed_saved"]), encoding="utf-8")
    return path


def _iron(watts: float) -> dict:
    return IronLoss(status="experimental", steel="M350-50A", electrical_frequency_Hz=160, iron_loss_W=watts,
                    iron_hysteresis_loss_W=0.6 * watts, iron_eddy_loss_W=0.4 * watts, stator_iron_mass_kg=1,
                    validated_max_frequency_Hz=1000, validated_max_flux_density_T=1.5).model_dump(mode="json")


def _solved(iron_W: float | None = 12.0, torque: float | None = 2.5) -> dict:
    summary = {"avg_torque_Nm": torque, "torque_ripple_pct": 3.0}
    if iron_W is not None:
        summary["iron_loss"] = _iron(iron_W)
    return {"summary": summary, "solve_metadata": {"mesh_element_count": 10}}


# The test design has mechanical loss, so every estimate says where that heat goes.
SPLIT = {"bearings": 0, "housing": 1, "rotor": 0}
SPLIT_OPTION = ("--thermal", "mechanical_split=" + json.dumps(SPLIT))


def run(capsys, *argv: str) -> tuple[int, dict | None, str]:
    code = _cli.main(list(argv))
    captured = capsys.readouterr()
    return code, (json.loads(captured.out) if captured.out.strip() else None), captured.err


@pytest.fixture
def fake_solve(monkeypatch):
    """Replace the solver with a fixed result; the requests it was given are returned."""

    requests = []

    def solve(body, on_progress, *, fields=False):
        requests.append(body)
        return _solved()

    monkeypatch.setattr(_solve, "_solve_in_process", solve)
    return requests


@pytest.fixture
def result_file(tmp_path, design, fake_solve, capsys) -> Path:
    out = tmp_path / "result.json"
    assert run(capsys, "solve", str(design), "--analyses", "torque,back_emf,losses", "--out", str(out))[0] == 0
    fake_solve.clear()
    return out


# -- The command --------------------------------------------------------------------------------


def test_thermal_solves_a_design_with_torque_and_losses_added(capsys, design, fake_solve) -> None:
    code, document, err = run(capsys, "thermal", str(design), *SPLIT_OPTION)
    assert code == 0 and document["schema"] == "coilem.cli.thermal/v1" and document["ok"] is True
    # The design's own selection is kept and the two analyses the estimate starts from are added.
    options = fake_solve[0]["solve_options"]
    assert options["torque_sweep"] is True and options["losses_efficiency"] is True
    assert document["source"] == {"kind": "solved"} and document["request"] == fake_solve[0]
    metrics = document["metrics"]
    assert metrics["status"] == "experimental" and metrics["hottest_part"] in document["thermal"]["nodes"]
    assert metrics["hottest_C"] > 25 and metrics["winding_limit_C"] == 140 and metrics["total_heat_W"] > 12
    assert metrics["winding_margin_K"] == pytest.approx(140 - metrics["winding_C"])
    # The starter values that produced the numbers travel with them.
    used = document["thermal_inputs"]
    assert used["cooling"] == "still_air" and used["housing_h_W_m2K"] == 10 and "starter" in used["coefficient_source"]
    assert used["mount_to_ambient_K_W"] is None, "an inner-rotor motor has no mount path"
    assert list(document["thermal"]["nodes"])[0] == "ambient" and "network" not in document["thermal"]
    assert "thermal estimate (experimental): hottest part is the" in err and "solved in" in err


def test_thermal_reads_a_solved_result_without_solving_again(capsys, result_file, fake_solve) -> None:
    code, base, err = run(capsys, "thermal", str(result_file), *SPLIT_OPTION)
    assert code == 0 and base["source"]["kind"] == "result" and "nothing is solved" in err
    code, warmer, _ = run(capsys, "thermal", str(result_file), *SPLIT_OPTION, "--ambient", "40", "--insulation", "H",
                           "--thermal", "contact_m2K_W=0.002")
    assert code == 0 and not fake_solve, "a result file is never solved again"
    assert warmer["thermal_inputs"]["ambient_C"] == 40 and warmer["thermal_inputs"]["contact_m2K_W"] == 0.002
    assert warmer["metrics"]["winding_limit_C"] == 165  # class H, less the 15 K hotspot allowance
    assert warmer["metrics"]["hottest_C"] > base["metrics"]["hottest_C"] + 14


def test_thermal_inputs_come_from_a_file_and_then_the_command_line(capsys, result_file, tmp_path) -> None:
    saved = tmp_path / "cooling.json"
    saved.write_text(json.dumps({"cooling": "forced_air", "housing_h_W_m2K": 60, "end_space_h_W_m2K": 25, "airgap_h_W_m2K": 40,
                                 "coefficient_source": "fan curve", "mechanical_split": SPLIT}), encoding="utf-8")
    code, document, _ = run(capsys, "thermal", str(result_file), "--thermal-inputs", str(saved), "--thermal", "housing_h_W_m2K=80")
    assert code == 0
    used = document["thermal_inputs"]
    assert used["cooling"] == "forced_air" and used["housing_h_W_m2K"] == 80 and used["coefficient_source"] == "fan curve"
    # The document this command writes can be given back as the inputs of the next run.
    again = tmp_path / "again.json"
    again.write_text(json.dumps(document), encoding="utf-8")
    code, repeated, _ = run(capsys, "thermal", str(result_file), "--thermal-inputs", str(again))
    assert code == 0 and repeated["metrics"] == document["metrics"]


@pytest.mark.parametrize(
    ("extra", "error_code", "field"),
    [
        (["--cooling", "forced_air"], "INVALID_INPUT", "thermal.housing_h_W_m2K"),
        (["--thermal", "ambient_C=500"], "INVALID_INPUT", "thermal.ambient_C"),
        (["--thermal", "housing_h=5"], "INVALID_INPUT", "thermal.housing_h"),
        (["--thermal-inputs", "missing.json"], "DESIGN_FILE_UNREADABLE", "thermal_inputs"),
    ],
)
def test_a_thermal_input_that_is_not_accepted_is_named_and_exits_3(capsys, result_file, extra, error_code, field) -> None:
    code, document, err = run(capsys, "thermal", str(result_file), *extra)
    assert code == 3 and document["ok"] is False and document["schema"] == "coilem.cli.error/v1"
    assert document["error"]["error_code"] == error_code and document["error"]["field"] == field
    assert err.strip()


@pytest.mark.parametrize(("wrapper", "extra", "field"), [
    ({"thermal_inputs": []}, [], "thermal_inputs"),
    ({"inputs": dict(STILL_AIR_STARTER)}, ["--cooling", "liquid_jacket"], "thermal.housing_h_W_m2K"),
    ({"inputs": {"ambient_C": 500}}, [], "thermal.ambient_C"),
])
def test_invalid_thermal_setup_stops_before_solving(capsys, design, fake_solve, tmp_path, wrapper, extra, field):
    saved = tmp_path / "thermal-inputs.json"
    saved.write_text(json.dumps(wrapper), encoding="utf-8")
    code, document, _ = run(capsys, "thermal", str(design), "--thermal-inputs", str(saved), *extra, *SPLIT_OPTION)
    assert code == 3 and document["error"]["field"] == field
    assert not fake_solve


def test_point_explains_reported_rotor_loss_scope():
    data = _solved()
    data["summary"]["rotor_iron_loss"] = {"rotor_iron_loss_W": 2.5}
    result = coilem.Result(data, request=PARITY["designs"]["high_speed_saved"])
    estimate = coilem.thermal(result, inputs={"mechanical_split": SPLIT})
    assert any("2.5 W of rotor iron loss" in note and "excludes" in note for note in estimate.data["notes"])


def test_a_result_without_losses_says_how_to_get_them(capsys, tmp_path) -> None:
    path = tmp_path / "result.json"
    coilem.Result(_solved(iron_W=None), request=PARITY["designs"]["high_speed_saved"]).save(path)
    code, document, _ = run(capsys, "thermal", str(path))
    assert code == 3 and document["error"]["error_code"] == "THERMAL_LOSSES_MISSING"
    assert "losses" in document["error"]["suggestion"]


def test_solve_options_do_not_apply_to_a_solved_result(capsys, result_file) -> None:
    code, document, err = run(capsys, "thermal", str(result_file), "--quality", "fine")
    assert code == 2 and document is None and "not solved again" in err
    code, _, err = run(capsys, "thermal", str(result_file), "--thermal", "ambient_C")
    assert code == 2 and "NAME=VALUE" in err


def test_an_estimate_that_cannot_be_given_is_a_result_not_a_failure(capsys, tmp_path) -> None:
    path = tmp_path / "result.json"
    coilem.Result(_solved(iron_W=5000.0), request=PARITY["designs"]["high_speed_saved"]).save(path)
    code, document, err = run(capsys, "thermal", str(path), *SPLIT_OPTION)
    assert code == 0 and document["ok"] is True
    assert document["metrics"]["status"] == "unavailable" and document["metrics"]["hottest_C"] is None
    assert "no estimate:" in err and document["thermal"]["status_reason"] in err


def test_schema_describes_the_thermal_inputs(capsys) -> None:
    code, document, _ = run(capsys, "schema")
    assert code == 0 and document["documents"]["thermal"] == "coilem.cli.thermal/v1"
    described = document["thermal"]
    assert described["still_air_starter"] == STILL_AIR_STARTER and described["cooling"] == ["still_air", "forced_air", "liquid_jacket"]
    properties = described["inputs"]["properties"]
    assert properties["housing_h_W_m2K"]["exclusiveMinimum"] == 0 and "mount_to_ambient_K_W" in properties
    assert "THERMAL_LOSSES_MISSING" in document["error_codes"]


# -- The Python client --------------------------------------------------------------------------


def test_the_python_client_estimates_from_a_result() -> None:
    result = coilem.Result(_solved(), request=PARITY["designs"]["high_speed_saved"])
    estimate = coilem.thermal(result, inputs={"mechanical_split": SPLIT})
    assert isinstance(estimate, coilem.ThermalEstimate) and estimate.available and estimate.status == "experimental"
    assert list(estimate.parts) == [name for name in PART_ORDER if name in estimate.parts] and "housing" in estimate.parts
    assert estimate.hottest_C == estimate.temperatures_C[estimate.hottest_part] and estimate.hottest_C > 25
    assert estimate.metrics()["hottest_part"] == estimate.hottest_part
    assert "hottest part is the" in repr(estimate)
    # Better cooling lowers every part; fixed copper loss removes the feedback rise.
    cooler = coilem.thermal(result, cooling="forced_air", inputs={
        "housing_h_W_m2K": 80, "end_space_h_W_m2K": 25, "airgap_h_W_m2K": 40, "coefficient_source": "test", "mechanical_split": SPLIT})
    assert cooler.hottest_C < estimate.hottest_C
    assert coilem.thermal(result, inputs={"mechanical_split": SPLIT}, copper_feedback=False).hottest_C <= estimate.hottest_C


def test_mechanical_loss_needs_to_be_told_which_parts_it_heats(capsys, result_file) -> None:
    with pytest.raises(coilem.InputError) as raised:
        coilem.thermal(coilem.Result(_solved(), request=PARITY["designs"]["high_speed_saved"]))
    assert raised.value.field == "thermal.mechanical_split" and "mechanical loss" in str(raised.value)
    code, document, _ = run(capsys, "thermal", str(result_file))
    assert code == 3 and document["error"]["field"] == "thermal.mechanical_split" and "mechanical_split=" in document["error"]["suggestion"]


def test_an_estimate_round_trips_through_its_file(tmp_path) -> None:
    estimate = coilem.thermal(coilem.Result(_solved(), request=PARITY["designs"]["high_speed_saved"]), ambient_C=30,
                              inputs={"mechanical_split": SPLIT})
    saved = json.loads(estimate.save(tmp_path / "thermal.json").read_text(encoding="utf-8"))
    assert saved["schema"] == "coilem.client_thermal/v1" and saved["inputs"]["ambient_C"] == 30
    assert coilem.ThermalEstimate(saved["thermal"], saved["inputs"]).metrics() == estimate.metrics()


def test_an_outer_rotor_motor_uses_its_mount() -> None:
    result = coilem.Result(_solved(iron_W=0.5, torque=0.05), request=json.loads(OUTRUNNER.read_text(encoding="utf-8")))
    estimate = coilem.thermal(result)
    assert "mount" in estimate.parts and "housing" not in estimate.parts and estimate.inputs["mount_to_ambient_K_W"] == 10
    better = coilem.thermal(result, inputs={"mount_to_ambient_K_W": 2})
    assert better.hottest_C < estimate.hottest_C


def test_another_kind_of_cooling_cannot_inherit_the_still_air_values() -> None:
    with pytest.raises(coilem.InputError) as raised:
        thermal_inputs(cooling="liquid_jacket", inputs={"housing_h_W_m2K": 1000})
    assert raised.value.field == "thermal.end_space_h_W_m2K" and "still-air starter" in str(raised.value)
    values = thermal_inputs(cooling="liquid_jacket", inputs={name: 100 for name in COEFFICIENTS} | {"coefficient_source": "jacket test"})
    assert values["cooling"] == "liquid_jacket" and values["mount_to_ambient_K_W"] is None
    assert thermal_inputs(outer_rotor=True)["mount_to_ambient_K_W"] == 10


def test_the_starter_values_are_the_apps() -> None:
    source = (ROOT / "frontend/src/public/thermal.ts").read_text(encoding="utf-8")
    block = re.search(r"export const THERMAL_STARTER[^=]*=\s*\{(.*?)\n\};", source, re.S).group(1)
    in_app = dict(re.findall(r"(\w+):\s*'((?:[^'\\]|\\.)*)'", block))
    assert set(in_app) == set(STILL_AIR_STARTER)
    for name, text in in_app.items():
        mine = STILL_AIR_STARTER[name]
        assert (float(text) == mine) if isinstance(mine, float) else (text == mine), name


def test_an_aluminium_winding_is_not_estimated_with_copper_conductivity() -> None:
    import copy

    from backend.client._thermal import ALUMINIUM_CONDUCTOR_K_W_MK, _input_model

    # The estimate reads which inputs were set, so the model must not be rebuilt from its own dump.
    copper = _input_model(outer_rotor=False, aluminium=False, cooling=None, ambient_C=None, insulation_class=None, inputs=None)
    assert "conductor_k_W_mK" not in copper.model_fields_set
    assert thermal_inputs(aluminium=True)["conductor_k_W_mK"] == ALUMINIUM_CONDUCTOR_K_W_MK
    assert thermal_inputs(aluminium=True, inputs={"conductor_k_W_mK": 220})["conductor_k_W_mK"] == 220

    def with_conductor(node, conductor):
        if isinstance(node, dict):
            if isinstance(node.get("materials"), dict):
                node["materials"]["conductor"] = conductor
            for child in node.values():
                with_conductor(child, conductor)
        return node

    request = with_conductor(copy.deepcopy(PARITY["designs"]["high_speed_saved"]), "aluminum")
    estimate = coilem.thermal(coilem.Result(_solved(), request=request), inputs={"mechanical_split": SPLIT})
    assert estimate.available and estimate.inputs["conductor_k_W_mK"] == ALUMINIUM_CONDUCTOR_K_W_MK
    copper_estimate = coilem.thermal(coilem.Result(_solved(), request=PARITY["designs"]["high_speed_saved"]), inputs={"mechanical_split": SPLIT})
    assert copper_estimate.inputs["conductor_k_W_mK"] == 385
