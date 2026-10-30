"""Qualification status follows docs/VALIDATION.md#qualification-status."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import qualification as qualification_module
from backend.benchmark_suite.contract import DEFAULT_BUNDLE, SPEC, sha
from backend.benchmark_suite.physics import physics_sources
from backend.benchmark_suite.references import load_bundle, load_suite
from backend.models import MotorConfig
from backend.public_main import app
from backend.public_routes.solve import _store_public_result
from backend.qualification import QUALIFICATION_BASIS, QUALIFICATION_REPORT, classify_qualification
from backend.solve_workspace import SolveRunWriter, SolveWorkspace, _qualification

FIXTURES = Path("benchmarks/main-20261009-bad71d9/fixtures")
SPM_CONCENTRATED = json.loads(Path("tests/fixtures/spm_4p12s_simple.json").read_text(encoding="utf-8"))
REPORT = json.loads(Path(QUALIFICATION_REPORT).read_text(encoding="utf-8"))

# The sources that decide what the report measured (backend/benchmark_suite/physics.py):
# winding layout, current angle and axis, slot and layer geometry, meshes and angle
# grids, materials, field extraction and the native solver. Changing any of them
# needs a new report before a combination keeps its qualified status, and a new
# benchmark record before `coilem benchmark` can match one (#71).
PHYSICS_SOURCES = physics_sources(Path(__file__).resolve().parents[1])


@pytest.fixture
def measured_build(monkeypatch):
    """Exercise combination policy independently of the running build's freshness."""
    monkeypatch.setattr(qualification_module, "evidence_matches_runtime", lambda: True)


def _fixture(name: str) -> MotorConfig:
    return MotorConfig.model_validate_json((FIXTURES / name).read_text(encoding="utf-8"))


def _with(config: MotorConfig, section: str, **changes) -> MotorConfig:
    return config.model_copy(update={section: getattr(config, section).model_copy(update=changes)})


def _status(config: MotorConfig) -> str:
    return classify_qualification(config)["status"]


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda path: path.stem)
def test_every_v11_fixture_has_its_documented_status(path: Path, measured_build) -> None:
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
def test_qualified_combinations_name_their_evidence(fixture: str, reason: str, measured_build) -> None:
    qualification = classify_qualification(_fixture(fixture))
    assert qualification["status"] == "qualified"
    assert qualification["reason"].startswith(reason)
    assert qualification["basis"] == "coilEM benchmark report, measured at 5b6cb61"
    assert qualification["reference"].endswith("docs/VALIDATION.md#qualification-status")


def test_basis_names_the_measured_commit_and_reference() -> None:
    run = REPORT["run"]
    spec = load_suite(SPEC)
    reference, _, bundle_sha = load_bundle(DEFAULT_BUNDLE, spec)
    assert run["status"] == "COMPLETE" and run["identity"]["dirty"] is False
    assert run["identity"]["commit"][:7] in QUALIFICATION_BASIS
    assert run["reference_mode"] == "FROZEN_REFERENCE"
    assert run["reference_commit"] == reference["reference_commit"]
    assert run["selection"]["bundle_sha256"] == bundle_sha
    measured_spec = Path(f"benchmarks/abcd-v{run['identity']['protocol_version'].rsplit('.', 1)[0]}/benchmark_spec.json")
    assert run["selection"]["spec_sha256"] == sha(measured_spec)
    # This run measured the winding-axis protocol directly; the frozen reference
    # still names its own earlier measured commit and registered validation bridge.
    assert run["identity"]["protocol_version"] == "1.3.0"


@pytest.mark.parametrize("path", PHYSICS_SOURCES)
def test_report_measured_the_current_physics_sources(path: str) -> None:
    measured = REPORT["run"]["identity"]["source_files"]
    assert path in measured, f"{QUALIFICATION_REPORT} did not measure {path}; run a new report before qualifying it"
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != measured[path]:
        # Keep the guard: changed physics must lose its qualified claim. The
        # strict release command additionally refuses publication until remeasured.
        assert not qualification_module.evidence_matches_runtime()
        assert classify_qualification(MotorConfig.model_validate(SPM_CONCENTRATED))["status"] == "experimental"


def test_reasons_match_the_report_outcomes(measured_build) -> None:
    # A reason names the combination, then states its claim after ": ". The two
    # distributed pitches share one claim about the same four fixtures.
    outcomes: dict[tuple[str, str], list[str]] = defaultdict(list)
    gates: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in REPORT["rows"]:
        config = MotorConfig.model_validate_json(Path(row["fixture"]).read_text(encoding="utf-8"))
        qualification = classify_qualification(config)
        key = (qualification["status"], qualification["reason"].partition(": ")[2])
        outcomes[key].append(row["status"])
        if row["phase"] == "D":
            gates[key] += [gate["status"] for gate in row["evaluation"]["gates"]]
    assert {status for status, _ in outcomes} == {"qualified", "experimental", "unsupported"}
    for (status, claim), statuses in outcomes.items():
        if status == "qualified":
            assert set(statuses) == {"PASS"}, claim
            assert claim.startswith(f"all {len(statuses)} benchmark "), claim
        elif status == "experimental":
            assert set(statuses) != {"PASS"}, claim
            assert claim.startswith(f"{statuses.count('PASS')} of {len(statuses)} benchmark fixtures pass"), claim
        else:
            assert set(statuses) == {"UNSUPPORTED"}, claim
    for key, statuses in gates.items():
        assert f"({statuses.count('PASS')} of {len(statuses)} gates)" in key[1]


def test_qualification_text_names_no_excluded_launch_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    # Qualification travels in public preview, solve and saved-run payloads, which
    # must not name the reference solver or thermal analysis (tools/smoke_public_runtime.py).
    monkeypatch.setenv("COILEM_EXPERIMENTAL_ROTORS", "1")
    prius = json.loads(Path("frontend/src/public/examples/ornl_prius_2004_holem50.coilem").read_text(encoding="utf-8"))
    for key in ("openem_schema_version", "openem_version", "name", "description"):
        prius.pop(key, None)
    distributed = _fixture("spm_8p24s_distributed_femm_validation.json")
    concentrated = _fixture("spm_8p12s_concentrated__baseline.json")
    configs = [
        *(MotorConfig.model_validate_json(Path(row["fixture"]).read_text(encoding="utf-8")) for row in REPORT["rows"]),
        *(MotorConfig.model_validate_json(path.read_text(encoding="utf-8")) for path in sorted(FIXTURES.glob("*.json"))),
        _with(distributed, "winding", layers=1),
        _with(distributed, "winding", coil_span=4),
        _with(distributed, "materials", stator_steel="custom:lab-curve"),
        _with(distributed, "solve_params", excitation_mode="ideal_six_step_120", current_amplitude_convention="plateau"),
        _with(concentrated, "winding", layers=2),
        _with(concentrated, "solve_params", solve_quality="quick", mesh_density="coarse"),
        MotorConfig.model_validate(prius),
    ]
    reasons = set()
    for config in configs:
        text = json.dumps(classify_qualification(config)).lower()
        assert "femm" not in text and "thermal" not in text, text
        reasons.add(classify_qualification(config)["reason"])
    assert any(reason.startswith("HoleM50") for reason in reasons)
    assert any(reason.startswith("V-shape IPM") for reason in reasons)


def test_unmeasured_and_failing_combinations_are_experimental() -> None:
    distributed = _fixture("spm_8p24s_distributed_femm_validation.json")
    six_step = _with(distributed, "solve_params", excitation_mode="ideal_six_step_120", current_amplitude_convention="plateau")
    flat_ipm = _fixture("ipm_flat_8p12s_fsae_contract.json")
    cases = {
        "V-shape IPM: 5 of 6": _fixture("ipm_vshape_8p12s_baseline_contract.json"),
        "SPM with distributed windings under ideal six-step": six_step,
        "Single-layer distributed": _with(distributed, "winding", layers=1),
        "Only full-pitch and 5/6": _with(_fixture("spm_8p48s_distributed_femm_validation.json"), "winding", coil_span=4),
        "IPM with distributed windings": _with(flat_ipm, "winding", type="distributed", layers=2),
        "Custom steel": _with(distributed, "materials", stator_steel="custom:lab-curve"),
        "Two-layer concentrated windings": _with(_fixture("spm_8p12s_concentrated__baseline.json"), "winding", layers=2),
    }
    for reason, config in cases.items():
        qualification = classify_qualification(config)
        assert (qualification["status"], qualification["reason"][: len(reason)]) == ("experimental", reason)


def test_rejected_rotors_and_windings_are_unsupported() -> None:
    flat_ipm = _fixture("ipm_flat_8p12s_fsae_contract.json")
    for config in (
        _fixture("ornl_prius_2004_ipm.json"),
        _with(flat_ipm, "rotor", flux_barrier_count=2),
        # Two layers wind a coil on every tooth; q = 1 has no tooth coils to double up.
        _with(MotorConfig.model_validate(SPM_CONCENTRATED), "winding", layers=2),
    ):
        qualification = classify_qualification(config)
        assert qualification["status"] == "unsupported"
        assert qualification["caveats"] == []


def test_preview_plan_carries_a_mesh_caveat_without_changing_status(measured_build) -> None:
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
    expected = "qualified" if qualification_module.evidence_matches_runtime() else "experimental"
    assert validation.json()["qualification"]["status"] == expected


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
    assert qualification["reason"].startswith("V-shape IPM: 5 of 6")

    rows = list(csv.reader(io.StringIO((location.path / "report" / "report.csv").read_text(encoding="utf-8"))))
    assert ["provenance", "qualification.status", "", "experimental", ""] in rows
    limitations = [row[3] for row in rows if row[0] == "known_limitation"]
    assert f"Experimental combination: {qualification['reason']}" in limitations

    pdf_text = " ".join(
        (page.extract_text() or "") for page in pypdf.PdfReader(location.path / "report" / "report.pdf").pages
    )
    pdf_text = " ".join(pdf_text.split())
    assert "Qualification Experimental: V-shape IPM: 5 of 6" in pdf_text
    assert "Experimental combination: V-shape IPM" in pdf_text


def test_completed_result_carries_the_stored_status(tmp_path: Path) -> None:
    workspace, writer, result = _v_shape_run(tmp_path)
    returned = _store_public_result(workspace, writer, result)
    assert returned["qualification"]["status"] == "experimental"
    assert returned["saved_run"]["run_id"]


def test_run_without_a_valid_config_records_no_status(measured_build) -> None:
    config = deepcopy(SPM_CONCENTRATED)
    del config["stator"]
    assert _qualification(config) is None
    assert _qualification(SPM_CONCENTRATED)["status"] == "qualified"


def test_changed_or_unverifiable_physics_cannot_keep_a_qualified_label(monkeypatch):
    monkeypatch.setattr(qualification_module, "evidence_matches_runtime", lambda: False)
    result = classify_qualification(MotorConfig.model_validate(SPM_CONCENTRATED))
    assert result["status"] == "experimental"
    assert "qualification is pending" in result["reason"]


def test_installed_evidence_requires_matching_record_identity(monkeypatch):
    from backend import resources
    from backend.benchmark_suite import record
    historical = resources.read_data_json(f"{resources.BENCHMARK_RECORDS_DIR}/windows-x86_64.json")
    monkeypatch.setattr(resources, "read_data_json", lambda _: historical)
    for status in ("DIFFERS", "UNVERIFIED", "MATCH"):
        monkeypatch.setattr(record, "check_physics", lambda _, status=status: {"status": status})
        assert qualification_module.evidence_matches_runtime() is (status == "MATCH")
    monkeypatch.setattr(resources, "read_data_json", lambda _: {**historical, "measured_commit": "0" * 40})
    assert not qualification_module.evidence_matches_runtime()
