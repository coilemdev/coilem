"""Qualification status follows docs/VALIDATION.md#qualification-status."""

from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.models import MotorConfig
from backend.public_main import app
from backend.public_routes.solve import _store_public_result
from backend.qualification import classify_qualification
from backend.solve_workspace import SolveRunWriter, SolveWorkspace, _qualification

FIXTURES = Path("benchmarks/main-20261009-bad71d9/fixtures")
SPM_CONCENTRATED = json.loads(Path("tests/fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"))


def _fixture(name: str) -> MotorConfig:
    return MotorConfig.model_validate_json((FIXTURES / name).read_text(encoding="utf-8"))


def _with(config: MotorConfig, section: str, **changes) -> MotorConfig:
    return config.model_copy(update={section: getattr(config, section).model_copy(update=changes)})


def _status(config: MotorConfig) -> str:
    return classify_qualification(config)["status"]


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda path: path.stem)
def test_every_v11_fixture_has_its_documented_status(path: Path) -> None:
    if path.stem == "ornl_prius_2004_ipm":
        expected = "unsupported"
    elif path.stem.startswith("ipm_vshape_"):
        expected = "experimental"
    else:
        expected = "qualified"
    assert _status(MotorConfig.model_validate_json(path.read_text(encoding="utf-8"))) == expected


@pytest.mark.parametrize(
    ("fixture", "reason"),
    [
        ("spm_8p12s_concentrated__baseline.json", "SPM, single-layer concentrated winding, sinusoidal current"),
        ("bldc_spm_8p12s_reference.json", "SPM, single-layer concentrated winding, ideal six-step"),
        ("spm_8p24s_distributed_femm_validation.json", "SPM, two-layer distributed winding (full pitch)"),
        ("spm_8p48s_chorded_5_6.json", "SPM, two-layer distributed winding (5/6 pitch)"),
        ("ipm_flat_8p12s_fsae_contract.json", "Flat-buried IPM, single-layer concentrated winding"),
    ],
)
def test_qualified_combinations_name_their_evidence(fixture: str, reason: str) -> None:
    qualification = classify_qualification(_fixture(fixture))
    assert qualification["status"] == "qualified"
    assert qualification["reason"].startswith(reason)
    assert qualification["basis"] == "coilEM benchmark report v1.1"
    assert qualification["reference"].endswith("docs/VALIDATION.md#qualification-status")


def test_unmeasured_and_failing_combinations_are_experimental() -> None:
    distributed = _fixture("spm_8p24s_distributed_femm_validation.json")
    six_step = _with(distributed, "solve_params", excitation_mode="ideal_six_step_120", current_amplitude_convention="plateau")
    flat_ipm = _fixture("ipm_flat_8p12s_fsae_contract.json")
    cases = {
        "V-shape IPM: 2 of 6": _fixture("ipm_vshape_8p12s_baseline_contract.json"),
        "SPM with distributed windings under ideal six-step": six_step,
        "Single-layer distributed": _with(distributed, "winding", layers=1),
        "Only full-pitch and 5/6": _with(_fixture("spm_8p48s_distributed_femm_validation.json"), "winding", coil_span=4),
        "IPM with distributed windings": _with(flat_ipm, "winding", type="distributed", layers=2),
        "Custom steel": _with(distributed, "materials", stator_steel="custom:lab-curve"),
    }
    for reason, config in cases.items():
        qualification = classify_qualification(config)
        assert (qualification["status"], qualification["reason"][: len(reason)]) == ("experimental", reason)


def test_rejected_rotors_and_windings_are_unsupported() -> None:
    concentrated = _fixture("spm_8p12s_concentrated__baseline.json")
    flat_ipm = _fixture("ipm_flat_8p12s_fsae_contract.json")
    for config in (
        _fixture("ornl_prius_2004_ipm.json"),
        _with(flat_ipm, "rotor", flux_barrier_count=2),
        _with(concentrated, "winding", layers=2),
    ):
        qualification = classify_qualification(config)
        assert qualification["status"] == "unsupported"
        assert qualification["caveats"] == []


def test_preview_plan_carries_a_mesh_caveat_without_changing_status() -> None:
    config = _fixture("spm_8p12s_concentrated__baseline.json")
    quick = classify_qualification(_with(config, "solve_params", solve_quality="quick", mesh_density="coarse"))
    standard = classify_qualification(_with(config, "solve_params", solve_quality="standard", mesh_density="normal"))
    assert quick["status"] == standard["status"] == "qualified"
    assert quick["caveats"] == ["The coarse Preview mesh was not qualified; the benchmark used the Standard plan's normal mesh."]
    assert standard["caveats"] == []


def test_preview_and_validate_return_the_status() -> None:
    client = TestClient(app, base_url="http://127.0.0.1")
    v_shape = json.loads(
        Path("frontend/src/public/examples/validation_ipm_10p_v_shape_medium.openem").read_text(encoding="utf-8")
    )
    preview = client.post("/preview", json=v_shape)
    assert preview.status_code == 200, preview.text
    assert preview.json()["metadata"]["qualification"]["status"] == "experimental"

    validation = client.post("/solve/validate", json=SPM_CONCENTRATED)
    assert validation.status_code == 200, validation.text
    assert validation.json()["qualification"]["status"] == "qualified"


def _v_shape_run(tmp_path: Path) -> tuple[SolveWorkspace, SolveRunWriter, dict]:
    config = json.loads((FIXTURES / "ipm_vshape_8p12s_baseline_contract.json").read_text(encoding="utf-8"))
    workspace = SolveWorkspace(tmp_path / "data")
    writer = workspace.begin_run(
        project_name="v-shape.coilem",
        config=MotorConfig.model_validate(config).model_dump(mode="json"),
        submitted_request={"config": config, "project_name": "v-shape"},
    )
    angles = [0.0, 30.0, 60.0, 90.0]
    result = {
        "summary": {"avg_torque_Nm": 4.25, "solve_time_s": 12.5},
        "torque_waveform": {"electrical_angle_deg": angles, "torque_Nm": [4.1, 4.3, 4.2, 4.4]},
        "back_emf_waveform": {
            "electrical_angle_deg": angles,
            "phase_a_V": [0.0, 9.0, 18.0, 9.0],
            "phase_b_V": [-15.6, -18.0, -9.0, 0.0],
            "phase_c_V": [15.6, 9.0, -9.0, -9.0],
        },
        "solve_metadata": {"solver_name": "magneto2d-rust-0.3.2", "mesh_element_count": 1, "rotor_positions": 4},
    }
    return workspace, writer, result


def test_saved_run_records_status_in_provenance_and_exports(tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    workspace, writer, result = _v_shape_run(tmp_path)
    location = writer.complete(result)
    loaded = workspace.load_run(location.project_slug, location.run_id)
    qualification = loaded["manifest"]["provenance"]["qualification"]
    assert qualification["status"] == "experimental"
    assert qualification["reason"].startswith("V-shape IPM: 2 of 6")

    rows = list(csv.reader(io.StringIO((location.path / "report" / "report.csv").read_text(encoding="utf-8"))))
    assert ["provenance", "qualification.status", "", "experimental", ""] in rows
    limitations = [row[3] for row in rows if row[0] == "known_limitation"]
    assert f"Experimental combination: {qualification['reason']}" in limitations

    pdf_text = " ".join(
        (page.extract_text() or "") for page in pypdf.PdfReader(location.path / "report" / "report.pdf").pages
    )
    pdf_text = " ".join(pdf_text.split())
    assert "Qualification Experimental: V-shape IPM: 2 of 6" in pdf_text
    assert "Experimental combination: V-shape IPM" in pdf_text


def test_completed_result_carries_the_stored_status(tmp_path: Path) -> None:
    workspace, writer, result = _v_shape_run(tmp_path)
    returned = _store_public_result(workspace, writer, result)
    assert returned["qualification"]["status"] == "experimental"
    assert returned["saved_run"]["run_id"]


def test_run_without_a_valid_config_records_no_status() -> None:
    config = deepcopy(SPM_CONCENTRATED)
    del config["stator"]
    assert _qualification(config) is None
    assert _qualification(SPM_CONCENTRATED)["status"] == "qualified"
