"""Phase F, the outer-rotor benchmark (protocol 1.8.0): its registered requests and its gates."""

from __future__ import annotations

import json
from pathlib import Path

from backend.benchmark_suite import COMMAND_PHASES, PHASE_LABELS, PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS, cli
from backend.benchmark_suite.cli import evaluate
from backend.benchmark_suite.contract import canonical, sha
from backend.benchmark_suite.references import load_suite
from backend.public_policy import parse_public_solve_request
from backend.qualification import classify_qualification
from backend.rotor_layout import outer_rotor_airgap_mm
from tools import make_outrunner_phase_f

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "benchmarks/abcd-v1.8/benchmark_spec.json"
BASE_SPEC = ROOT / "benchmarks/abcd-v1.6/benchmark_spec.json"


def _fixture(case) -> dict:
    return json.loads((ROOT / case["jobs"][0]["fixture"]).read_text(encoding="utf-8"))


def test_phase_f_is_its_own_suite_and_1_6_stays_the_default() -> None:
    spec = load_suite(SPEC)
    assert PHASE_LABELS["F"] == "Outrunner"
    assert "F" not in COMMAND_PHASES
    assert spec["protocol_version"] == "1.8.0" in SUPPORTED_PROTOCOL_VERSIONS
    assert PROTOCOL_VERSION == "1.6.0"
    assert {case["phase"] for case in spec["cases"]} == {"F"}
    assert len(spec["cases"]) == len({case["id"] for case in spec["cases"]}) == 10
    assert spec["phase_f"]["status"] == "PROPOSED_NOT_REGISTERED"
    assert spec["phase_f"]["reference_bundle"] is None
    assert spec["phase_f"]["base_suite_sha256"] == sha(BASE_SPEC)
    base = load_suite(BASE_SPEC)
    for key in ("schema", "convention", "material_contract", "golden", "golden_sha256"):
        assert spec[key] == base[key]


def test_the_generator_reproduces_the_registered_requests_and_suite() -> None:
    requests = make_outrunner_phase_f.requests()
    spec = load_suite(SPEC)
    assert make_outrunner_phase_f.suite(requests) == json.loads(SPEC.read_text(encoding="utf-8"))
    for case in spec["cases"]:
        job = case["jobs"][0]
        assert sha(ROOT / job["fixture"]) == job["fixture_sha256"]
        assert canonical(_fixture(case)) == job["input_sha256"]
        assert _fixture(case) == requests[case["id"]]


def test_each_request_is_the_phase_a_request_with_an_outer_rotor_motor() -> None:
    template = make_outrunner_phase_f._template()
    motor = ("rotor_layout", "stator", "rotor", "winding")
    for case in load_suite(SPEC)["cases"]:
        request = _fixture(case)
        assert request["rotor_layout"] == "outer" and request["topology"] == "SPM"
        assert request["materials"] == template["materials"]
        assert request["solve_options"] == template["solve_options"]
        changed = {key for key in template["solve_params"] if request["solve_params"][key] != template["solve_params"][key]}
        assert changed <= {"current_amplitude_A", "current_angle_deg"}
        assert {key for key in request if key not in (*motor, "solve_params") and request[key] != template[key]} == set()
        assert (case["slots"], case["poles"]) == (request["stator"]["slot_count"], request["rotor"]["pole_count"])


def test_every_request_is_a_valid_public_outer_rotor_solve() -> None:
    for case in load_suite(SPEC)["cases"]:
        config, _, solver = parse_public_solve_request(_fixture(case))
        assert solver == "magneto2d" and config.rotor_layout == "outer"
        assert outer_rotor_airgap_mm(config) >= 0.25 - 1e-9
        # No outer rotor is benchmarked yet, so none is qualified.
        assert classify_qualification(config)["status"] == "experimental"


def test_variants_change_one_thing_from_their_baseline() -> None:
    cases = {case["id"]: _fixture(case) for case in load_suite(SPEC)["cases"]}
    base = cases["spm_outer_14p12s_drone__baseline"]

    def diff(other, section):
        return {key: (base[section][key], other[section][key]) for key in base[section] if base[section][key] != other[section][key]}

    assert diff(cases["spm_outer_14p12s_drone__high_current"], "solve_params") == {"current_amplitude_A": (10.0, 15.0)}
    assert diff(cases["spm_outer_14p12s_drone__angle30"], "solve_params") == {"current_angle_deg": (0.0, 30.0)}
    assert diff(cases["spm_outer_14p12s_drone_noload__baseline"], "solve_params") == {"current_amplitude_A": (10.0, 0.0)}
    assert diff(cases["spm_outer_14p12s_drone__tight_airgap"], "rotor") == {"ID_mm": (31.8, 31.5)}
    micro = cases["spm_outer_12p9s_micro__baseline"]
    assert cases["spm_outer_12p9s_micro_noload__baseline"]["solve_params"] == {**micro["solve_params"], "current_amplitude_A": 0.0}


def _measurement(torque_Nm: float, emf_V: float):
    angles = [7.5 * index for index in range(48)]
    return {
        "summary": {"avg_torque_Nm": torque_Nm, "back_emf_fundamental_V": emf_V},
        "torque_waveform": {"electrical_angle_deg": angles, "torque_Nm": [torque_Nm] * 48},
        "back_emf_waveform": {
            "electrical_angle_deg": angles,
            **{f"phase_{phase}_V": [emf_V] * 48 for phase in "abc"},
        },
        "solve_metadata": {"solver_name": "magneto2d-0.4.0", "mesh_source": "native", "torque_method": "weighted_stress"},
    }


def test_phase_f_is_graded_with_phase_a_gates_and_a_signed_mean_torque(tmp_path, monkeypatch) -> None:
    case = load_suite(SPEC)["cases"][0]
    request = _fixture(case)
    (tmp_path / "request.json").write_text(json.dumps({"config": request}), encoding="utf-8")
    job = {"case_id": case["id"], "stage": "native", "request": "request.json", "status": "COMPLETE",
           "request_sha256": sha(tmp_path / "request.json")}
    manifest = {"jobs": [job], "smoke": False, "identity": {}}
    monkeypatch.setattr(cli, "verify_artifact", lambda output, job, identity: {"result": _measurement(0.06, 0.5)})

    def grade(reference):
        configs = {(case["id"], "native"): request}
        return evaluate(tmp_path, manifest, [case], configs, {}, None, {case["id"]: reference})[0]["evaluation"]

    assert grade(_measurement(0.062, 0.52))["status"] == "PASS"
    assert grade(_measurement(0.07, 0.5))["gates"]["mean_torque"] == "YELLOW"
    # A reference reporting the stator's torque (opposite sign) fails, however close its magnitude.
    assert grade(_measurement(-0.06, 0.5))["gates"]["mean_torque"] == "FAIL"
