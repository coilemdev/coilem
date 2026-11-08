"""Data-only reference bundles, already normalized to public clockwise coordinates."""

import copy
import math
import re

from backend.benchmark_suite import CONVENTION, SUPPORTED_PROTOCOL_VERSIONS
from backend.benchmark_suite.contract import DATA_ROOT, canonical, checked_json, read, sha

PHASE_F_BUNDLE_SCHEMA = "coilem.frozen_reference_bundle/v2"
PHASE_F_REVIEW_STATUS = "REVIEWED_FOR_WINDOWS_ENGINEERING_PARITY"
PHASE_F_REVIEW_DECISION = "ACCEPTED_FOR_WINDOWS_ENGINEERING_PARITY"
PHASE_F_REVIEW_SCOPE = "WINDOWS_ONLY_ENGINEERING_PARITY"
PHASE_F_HUB_CASE = "spm_outer_30p27s_hub__baseline"
PHASE_E_REFERENCE_STATUS = "EXPERIMENTAL_REFERENCE"
PHASE_E_REFERENCE_COHORT = "selected_cogging_reference"


def reference_provenance(manifest):
    """A dataset digest is a reference identity, never an adapter Git commit."""
    if manifest.get("schema") == PHASE_F_BUNDLE_SCHEMA:
        return {"reference_id": manifest["reference_id"], "reference_identity_kind": "DATASET_SHA256",
                "reference_review_scope": (PHASE_E_REFERENCE_STATUS if manifest.get("protocol_version") == "1.7.0"
                                           else PHASE_F_REVIEW_SCOPE)}
    return {"reference_commit": manifest.get("reference_commit")}


def reference_manifest_payload_sha256(manifest):
    """Bind the complete manifest without a circular review-file hash."""
    return canonical({key: value for key, value in manifest.items() if key != "review"})


def _sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _public_reference_data(value, key=""):
    """V2 is a portable packet; private producer identities stay in its handback."""
    if isinstance(value, dict):
        for name, item in value.items():
            if (("commit" in name and name != "public_candidate_commit")
                    or "adapter" in name or "path" in name or name in {"source_directory", "producer"}):
                raise ValueError("Private producer identity or path in public reference packet")
            _public_reference_data(item, name)
    elif isinstance(value, list):
        for item in value:
            _public_reference_data(item, key)
    elif isinstance(value, str):
        if re.search(r"[A-Za-z]:[\\/]|\\\\|/(?:Users|home)/", value):
            raise ValueError("Local path in public reference packet")
        if key != "public_candidate_commit" and re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("Git-shaped private identity in public reference packet")


def _phase_f_cohorts(manifest):
    cohorts = manifest.get("source_cohorts")
    if not isinstance(cohorts, dict) or set(cohorts) != {"original", "hub_bulk_mesh_variant"}:
        raise ValueError("Phase F requires the two explicitly reviewed source cohorts")
    original, hub = cohorts["original"], cohorts["hub_bulk_mesh_variant"]
    if (not isinstance(original, dict) or not isinstance(hub, dict)
            or set(original) - {"evidence_sha256", "description"}
            or set(hub) - {"evidence_sha256", "description", "base_cohort", "bulk_mesh_mm"}
            or not _sha256(original.get("evidence_sha256")) or not _sha256(hub.get("evidence_sha256"))
            or original["evidence_sha256"] == hub["evidence_sha256"]
            or hub.get("base_cohort") != "original" or type(hub.get("bulk_mesh_mm")) not in (int, float)
            or hub["bulk_mesh_mm"] != 0.5):
        raise ValueError("Phase F source-cohort evidence or hub mesh contract mismatch")
    return cohorts


def _phase_f_fundamental(values):
    count = len(values)
    cosine = 2 / count * math.fsum(value * math.cos(index * 2 * math.pi / count) for index, value in enumerate(values))
    sine = 2 / count * math.fsum(value * math.sin(index * 2 * math.pi / count) for index, value in enumerate(values))
    return math.hypot(cosine, sine) / math.sqrt(2), math.degrees(math.atan2(-sine, cosine))


def _phase_f_number(actual, expected):
    if (type(actual) not in (int, float) or not math.isfinite(actual)
            or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-10)):
        raise ValueError("Phase F self-check value disagrees with the reference measurements")


def _phase_f_result(record, config, case_id):
    from backend.benchmark_suite.metrics import finite_series, validate_abc

    result = record.get("result") or {}
    try:
        validate_abc(result, config, native=False)
        torque = result["torque_waveform"]["torque_Nm"]
        _phase_f_number(result["summary"]["avg_torque_Nm"], math.fsum(torque) / len(torque))
        fundamental, _ = _phase_f_fundamental(result["back_emf_waveform"]["phase_a_V"])
        _phase_f_number(result["summary"]["back_emf_fundamental_V"], fundamental)
        flux = result.get("no_load_flux_linkage_waveform")
        if flux is not None:
            if not isinstance(flux, dict) or flux.get("electrical_angle_deg") != result["back_emf_waveform"]["electrical_angle_deg"]:
                raise ValueError("Phase F no-load flux differs from the registered grid")
            for phase in "abc":
                finite_series(flux.get(f"phase_{phase}_Wb"), 48)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError(f"Malformed Phase F reference result: {case_id}") from exc
    return result


def _phase_f_self_checks(directory, manifest, spec, records, configs, review):
    from backend.benchmark_suite.metrics import energy_balance_ratio

    control_ids = {"spm_outer_14p12s_drone__tight_airgap", "spm_outer_12p9s_micro__baseline"}
    controls = manifest.get("mesh_controls")
    if not isinstance(controls, dict) or set(controls) != control_ids:
        raise ValueError("Phase F requires exactly both registered half-airgap mesh controls")
    measured_controls = {}
    by_case = {case["id"]: case for case in spec["cases"]}
    for case_id, entry in controls.items():
        job = by_case[case_id]["jobs"][0]
        if (not isinstance(entry, dict) or set(entry) != {"file", "sha256", "input_sha256", "source_cohort"}
                or not _sha256(entry.get("sha256")) or entry.get("input_sha256") != job["input_sha256"]
                or entry.get("source_cohort") != "original"):
            raise ValueError("Phase F mesh-control input or source cohort mismatch")
        record = checked_json(directory, entry["file"], entry["sha256"])
        _public_reference_data(record)
        if (not isinstance(record, dict) or record.get("schema") != "coilem.femm_reference/v2"
                or record.get("case_id") != case_id or record.get("phase") != "F"
                or record.get("input_sha256") != job["input_sha256"] or record.get("convention") != CONVENTION
                or record.get("normalized") is not True or record.get("reference_id") != manifest["reference_id"]
                or record.get("source_cohort") != "original" or record.get("drive_choice") != "production"
                or record.get("public_candidate_commit") != manifest["public_candidate_commit"]
                or record.get("validation_status") != PHASE_F_REVIEW_STATUS):
            raise ValueError("Phase F mesh-control identity mismatch")
        result = _phase_f_result(record, configs[case_id], case_id)
        normal_settings = records[case_id].get("solve_metadata") or {}
        refined_settings = result.get("solve_metadata") or {}
        normal_gap = normal_settings.get("airgap_mesh_size_mm")
        if type(normal_gap) not in (int, float) or not math.isfinite(normal_gap) or normal_gap <= 0:
            raise ValueError("Phase F normal airgap mesh size is missing")
        _phase_f_number(refined_settings.get("airgap_mesh_size_mm"), normal_gap * 0.5)
        for settings in (normal_settings, refined_settings):
            if (settings.get("precision") != 1e-8 or settings.get("min_angle_deg") != 30
                    or settings.get("torque_method") != "weighted_stress" or settings.get("torque_body") != "rotor"):
                raise ValueError("Phase F mesh-control solver recipe changed")
        measured_controls[case_id] = result
    entry = review.get("self_checks") or {}
    if not isinstance(entry, dict) or set(entry) != {"file", "sha256"} or not _sha256(entry.get("sha256")):
        raise ValueError("Phase F requires hash-bound reference self-checks")
    receipt = checked_json(directory, entry["file"], entry["sha256"])
    _public_reference_data(receipt)
    if (not isinstance(receipt, dict) or receipt.get("schema") != "coilem.phase_f_reference_self_checks/v1"
            or receipt.get("original_gates_or_tolerances_changed") is not False):
        raise ValueError("Phase F reference self-check contract changed")
    checks = receipt.get("checks")
    if (not isinstance(checks, list) or len(checks) != 30
            or any(not isinstance(check, dict) or check.get("status") != "PASS" for check in checks)):
        raise ValueError("Phase F requires all 30 reference self-checks to pass")
    actual = {check.get("id"): check for check in checks}
    expected = {}
    spacing = {}
    for case_id, result in records.items():
        phases = [_phase_f_fundamental(result["back_emf_waveform"][f"phase_{phase}_V"]) for phase in "abc"]
        if phases[0][0] <= 0:
            raise ValueError("Phase F reference has no phase fundamental")
        balance = [abs(phase[0] - phases[0][0]) / phases[0][0] * 100 for phase in phases[1:]]
        if max(balance) > 1:
            raise ValueError("Phase F phase-balance self-check failed")
        expected[case_id + ":phase_balance"] = {"B_C_amplitude_delta_pct": balance, "maximum_pct": 1}
        relative = [(phase[1] - phases[0][1]) % 360 for phase in phases[1:]]
        spacing[case_id] = {"B_C_relative_to_A_deg": relative,
                            "distance_to_expected_120_or_240_deg": [min(abs(angle - 120), abs(angle - 240)) for angle in relative]}
        mean = result["summary"]["avg_torque_Nm"]
        if "_noload" not in case_id:
            if mean <= 0:
                raise ValueError("Phase F loaded-sign self-check failed")
            expected[case_id + ":loaded_sign"] = {"mean_rotor_cw_Nm": mean}
            if not case_id.endswith("__high_current"):
                ratio = energy_balance_ratio(result, configs[case_id])
                if ratio is None or abs(ratio - 1) > 0.05:
                    raise ValueError("Phase F energy-balance self-check failed")
                expected[case_id + ":energy_balance"] = {"ratio": ratio, "allowed_baseline_error_fraction": 0.05}
    baseline = records["spm_outer_14p12s_drone__baseline"]["summary"]["avg_torque_Nm"]
    ratio = records["spm_outer_14p12s_drone__angle30"]["summary"]["avg_torque_Nm"] / baseline
    if not 0.8 <= ratio <= 0.9:
        raise ValueError("Phase F angle-30 torque self-check failed")
    expected["drone_angle30_over_baseline"] = {"ratio": ratio, "minimum": 0.8, "maximum": 0.9}
    for case_id in ("spm_outer_14p12s_drone_noload__baseline", "spm_outer_12p9s_micro_noload__baseline"):
        no_load = records[case_id]["summary"]["avg_torque_Nm"]
        loaded = records[case_id.replace("_noload", "")]["summary"]["avg_torque_Nm"]
        ratio = abs(no_load) / abs(loaded) * 100
        if ratio >= 1:
            raise ValueError("Phase F no-load mean self-check failed")
        expected[case_id + ":noload_mean"] = {"noload_mean_Nm": no_load, "loaded_mean_Nm": loaded,
                                               "ratio_pct": ratio, "maximum_exclusive_pct": 1}
    for case_id, refined in measured_controls.items():
        deltas = {}
        for field in ("avg_torque_Nm", "back_emf_fundamental_V"):
            normal = records[case_id]["summary"][field]
            if normal == 0:
                raise ValueError("Phase F mesh control cannot use a zero denominator")
            delta = abs(refined["summary"][field] - normal) / abs(normal) * 100
            if delta >= 2:
                raise ValueError("Phase F half-airgap mesh-control change must remain below 2 percent")
            deltas[field] = delta
        expected[case_id + ":half_airgap_mesh"] = {"delta_pct": deltas, "maximum_exclusive_pct": 2}
    if set(actual) != set(expected) or len(actual) != 30:
        raise ValueError("Phase F self-check names do not match the complete registered scope")

    def match_values(actual_value, expected_value):
        if isinstance(expected_value, dict):
            if not isinstance(actual_value, dict) or set(actual_value) != set(expected_value):
                raise ValueError("Phase F self-check metric names changed")
            for key, value in expected_value.items():
                match_values(actual_value[key], value)
        elif isinstance(expected_value, list):
            if not isinstance(actual_value, list) or len(actual_value) != len(expected_value):
                raise ValueError("Phase F self-check phase values are incomplete")
            for value, expected_number in zip(actual_value, expected_value, strict=True):
                _phase_f_number(value, expected_number)
        else:
            _phase_f_number(actual_value, expected_value)

    for check_id, values in expected.items():
        match_values({key: value for key, value in actual[check_id].items() if key not in {"id", "status"}}, values)
    match_values(receipt.get("phase_spacing"), spacing)
    flags = [{"id": f"inherited_lrk_index_{index}", "status": "FAIL", "review_decision": "ACCEPTED_AS_NUMERICAL_SENSITIVITY"}
             for index in (5, 10)]
    flags.append({"id": "SOURCE_IDENTITY_VARIANT_REQUIRES_OWNER_REVIEW", "status": "REVIEW_REQUIRED",
                  "review_decision": "ACCEPTED_FOR_THIS_WINDOWS_COHORT"})
    if receipt.get("historical_review_flags") != flags:
        raise ValueError("Phase F self-check receipt reclassified a retained review flag")


def _require_phase_f_review(directory, manifest, spec):
    registered = DATA_ROOT / "benchmarks/abcd-v1.8/benchmark_spec.json"
    if (manifest.get("validation_status") != PHASE_F_REVIEW_STATUS
            or manifest.get("suite_sha256") != sha(registered) or read(registered) != spec
            or not isinstance(manifest.get("records"), dict)
            or set(manifest["records"]) != {case["id"] for case in spec["cases"]}):
        raise ValueError("Phase F review does not cover this registered suite")
    entry = manifest.get("review") or {}
    if not isinstance(entry, dict) or set(entry) != {"file", "sha256"} or not _sha256(entry.get("sha256")):
        raise ValueError("Phase F requires a hash-bound Windows review")
    review = checked_json(directory, entry["file"], entry["sha256"])
    if not isinstance(review, dict):
        raise ValueError("Phase F review must be an object")
    _public_reference_data(review)
    expected_cases = {
        case["id"]: {"record_sha256": manifest["records"][case["id"]]["sha256"],
                     "input_sha256": case["jobs"][0]["input_sha256"],
                     "source_cohort": manifest["records"][case["id"]]["source_cohort"]}
        for case in spec["cases"]
    }
    if (review.get("schema") != "coilem.protocol18_reference_review/v1"
            or review.get("decision") != PHASE_F_REVIEW_DECISION
            or review.get("platform") != "windows-x86_64" or review.get("scope") != PHASE_F_REVIEW_SCOPE
            or review.get("reference_id") != manifest["reference_id"]
            or review.get("suite_sha256") != manifest["suite_sha256"]
            or review.get("manifest_payload_sha256") != reference_manifest_payload_sha256(manifest)
            or review.get("source_cohorts_sha256") != canonical(manifest["source_cohorts"])
            or not _sha256(review.get("owner_decision_sha256"))
            or review.get("cases") != expected_cases):
        raise ValueError("Phase F review identity, scope or complete case binding mismatch")
    exceptions = review.get("exceptions") or {}
    if not isinstance(exceptions, dict):
        raise ValueError("Phase F review exceptions must be explicit")
    lrk = exceptions.get("lrk_reference_sensitivity") or {}
    mixed = exceptions.get("mixed_source_cohorts") or {}
    if (not isinstance(lrk, dict) or not isinstance(mixed, dict)
            or lrk.get("decision") != "ACCEPTED_AS_NUMERICAL_SENSITIVITY"
            or lrk.get("preserved_fail_indices") != [5, 10]
            or lrk.get("original_verdicts_retained") is not True or lrk.get("limits_changed") is not False
            or mixed.get("decision") != "ACCEPTED_FOR_THIS_WINDOWS_COHORT"
            or mixed.get("case_ids") != [PHASE_F_HUB_CASE]
            or mixed.get("single_producer_contract_satisfied") is not False):
        raise ValueError("Phase F review must explicitly retain LRK failures and accept the mixed cohort")
    capsules = []
    for exception in (lrk, mixed):
        evidence = exception.get("evidence") or {}
        if not isinstance(evidence, dict) or set(evidence) != {"file", "sha256"} or not _sha256(evidence.get("sha256")):
            raise ValueError("Phase F exception requires hash-bound public evidence")
        capsule = checked_json(directory, evidence["file"], evidence["sha256"])
        _public_reference_data(capsule)
        if (not isinstance(capsule, dict) or capsule.get("platform") != review["platform"]
                or capsule.get("scope") != review["scope"]):
            raise ValueError("Phase F exception evidence has a different platform or scope")
        capsules.append(capsule)
    lrk_data, source_data = capsules
    if (lrk_data.get("schema") != "coilem.lrk_sensitivity_review/v1"
            or lrk_data.get("decision") != lrk["decision"]
            or lrk_data.get("original_check_counts") != {"PASS": 9, "FAIL": 2}
            or lrk_data.get("preserved_fail_indices") != [5, 10]
            or lrk_data.get("original_verdicts_retained") is not True or lrk_data.get("limits_changed") is not False
            or lrk_data.get("controls_not_a_statistical_error_bound") is not True):
        raise ValueError("LRK review evidence must preserve the original failed checks")
    rows = lrk_data.get("rows")
    if (not isinstance(rows, list) or len(rows) != 2 or any(not isinstance(row, dict) for row in rows)
            or {row.get("index") for row in rows} != {5, 10}):
        raise ValueError("LRK review evidence must contain the two original failed points")
    for row in rows:
        target, limit = (3.3944, 0.067888) if row["index"] == 5 else (0.0649, 0.05)
        values = [row.get(name) for name in ("reference_mNm", "rebuilt_mNm", "allowed_error_mNm", "absolute_error_mNm")]
        if (any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
                or row["reference_mNm"] != target or row["allowed_error_mNm"] != limit
                or not math.isclose(row["absolute_error_mNm"], abs(row["rebuilt_mNm"] - target), rel_tol=1e-12, abs_tol=1e-12)
                or row["absolute_error_mNm"] <= limit or row.get("original_status") != "FAIL"
                or row.get("uncertainty_status") != "INSUFFICIENT_EVIDENCE"):
            raise ValueError("LRK reference failures or limits were reclassified")
    if (source_data.get("schema") != "coilem.phase_f_source_review/v1"
            or source_data.get("decision") != mixed["decision"]
            or source_data.get("reference_id") != manifest["reference_id"]
            or source_data.get("source_cohorts") != manifest["source_cohorts"]
            or source_data.get("case_ids") != [PHASE_F_HUB_CASE]
            or source_data.get("single_producer_contract_satisfied") is not False
            or source_data.get("hub_bulk_mesh_mm") != 0.5 or source_data.get("original_bulk_mesh_mm") != 0.25):
        raise ValueError("Mixed-source review evidence changed the approved hub exception")
    return review


def _load_phase_f_bundle(directory, manifest, spec):
    registered = DATA_ROOT / "benchmarks/abcd-v1.8/benchmark_spec.json"
    case_ids = [case["id"] for case in spec.get("cases", [])]
    if (spec.get("protocol_version") != "1.8.0" or manifest.get("protocol_version") != "1.8.0"
            or spec != read(registered) or len(case_ids) != 10 or len(set(case_ids)) != 10
            or any(case.get("phase") != "F" for case in spec["cases"])
            or manifest.get("convention") != CONVENTION or manifest.get("normalized") is not True
            or manifest.get("material_contract") != spec["material_contract"]
            or manifest.get("suite_sha256") != sha(registered)
            or not isinstance(manifest.get("reference_id"), str)
            or not manifest["reference_id"].startswith("sha256:") or not _sha256(manifest["reference_id"][7:])
            or not isinstance(manifest.get("public_candidate_commit"), str)
            or re.fullmatch(r"[0-9a-f]{40}", manifest["public_candidate_commit"]) is None
            or not isinstance(manifest.get("records"), dict) or set(manifest["records"]) != set(case_ids)):
        raise ValueError("Unsupported Phase F dataset, suite, material or coordinate contract")
    _public_reference_data(manifest)
    _phase_f_cohorts(manifest)
    records, configs = {}, {}
    for case in spec["cases"]:
        case_id, job = case["id"], case["jobs"][0]
        entry = manifest["records"][case_id]
        expected_cohort = "hub_bulk_mesh_variant" if case_id == PHASE_F_HUB_CASE else "original"
        if (not isinstance(entry, dict) or set(entry) != {"file", "sha256", "input_sha256", "source_cohort"}
                or not _sha256(entry.get("sha256")) or entry.get("source_cohort") != expected_cohort
                or entry.get("input_sha256") != job["input_sha256"]):
            raise ValueError(f"Phase F record input or source-cohort mismatch: {case_id}")
        record = checked_json(directory, entry["file"], entry["sha256"])
        _public_reference_data(record)
        if (not isinstance(record, dict) or record.get("schema") != "coilem.femm_reference/v2" or record.get("case_id") != case_id
                or record.get("phase") != "F" or record.get("input_sha256") != job["input_sha256"]
                or record.get("convention") != CONVENTION or record.get("normalized") is not True
                or record.get("reference_id") != manifest["reference_id"]
                or record.get("source_cohort") != expected_cohort
                or record.get("public_candidate_commit") != manifest.get("public_candidate_commit")
                or record.get("validation_status") != PHASE_F_REVIEW_STATUS or record.get("drive_choice") != "production"):
            raise ValueError(f"Phase F record identity mismatch: {case_id}")
        config = checked_json(DATA_ROOT, job["fixture"], job["fixture_sha256"])
        if canonical(config) != job["input_sha256"]:
            raise ValueError("Phase F registered input changed")
        records[case_id] = _phase_f_result(record, config, case_id)
        configs[case_id] = config
    review = _require_phase_f_review(directory, manifest, spec)
    _phase_f_self_checks(directory, manifest, spec, records, configs, review)
    return manifest, records, canonical({"manifest": sha(directory / "manifest.json"), "records": manifest["records"]})


def _phase_e_capsule(directory, entry):
    if not isinstance(entry, dict) or set(entry) != {"file", "sha256"} or not _sha256(entry.get("sha256")):
        raise ValueError("Phase E requires a hash-bound public evidence capsule")
    value = checked_json(directory, entry["file"], entry["sha256"])
    _public_reference_data(value)
    if not isinstance(value, dict):
        raise ValueError("Phase E evidence capsule must be an object")
    return value


def _phase_e_result(record, config):
    from backend.benchmark_suite.cogging_metrics import _summary_mismatches
    from backend.benchmark_suite.metrics import finite_series
    from backend.cogging import cogging_period, cogging_record

    result = record.get("result")
    if not isinstance(result, dict):
        raise ValueError("Phase E reference result must be an object")
    wave = result.get("cogging_torque_waveform") or {}
    if not isinstance(wave, dict) or set(wave) - {"electrical_angle_deg", "mechanical_angle_deg", "torque_Nm"}:
        raise ValueError("Phase E reference waveform must be an object")
    angles, torque = wave.get("electrical_angle_deg"), wave.get("torque_Nm")
    finite_series(angles, 25)
    finite_series(torque, 25)
    slots, poles = config["stator"]["slot_count"], config["rotor"]["pole_count"]
    period, _, _ = cogging_period(slots, poles)
    if any(abs(angle - index * period / 24) > 1e-7 for index, angle in enumerate(angles)):
        raise ValueError("Phase E reference differs from the registered closed cogging grid")
    if "mechanical_angle_deg" in wave:
        finite_series(wave["mechanical_angle_deg"], 25)
        if any(abs(mechanical - electrical / (poles / 2)) > 1e-7
               for mechanical, electrical in zip(wave["mechanical_angle_deg"], angles, strict=True)):
            raise ValueError("Phase E mechanical and electrical grids disagree")
    metadata = result.get("solve_metadata") or {}
    selection = "half_airgap_mesh" if "distributed_femm_validation" in record["case_id"] else "baseline"
    if (not isinstance(metadata, dict) or metadata.get("femm_version") != "4.2"
            or metadata.get("torque_method") != "weighted_stress" or metadata.get("torque_body") != "rotor"
            or metadata.get("independent_endpoints") is not True or metadata.get("reference_selection") != selection):
        raise ValueError("Phase E reference extraction or retained mesh selection mismatch")
    summary = result.get("summary")
    stored = summary.get("cogging") if isinstance(summary, dict) else None
    actual = cogging_record(angles, torque, slot_count=slots, pole_count=poles, method="reference")
    if (not isinstance(stored, dict) or actual is None or stored.get("method") != "reference"
            or stored.get("status") != "experimental" or _summary_mismatches(stored, actual.model_dump(mode="json"))):
        raise ValueError("Phase E stored reference summary disagrees with its waveform or experimental status")
    return result, actual


def _load_phase_e_bundle(directory, manifest, spec):
    """Load retained cogging evidence without granting review or qualification."""
    registered = DATA_ROOT / "benchmarks/abcd-v1.7/benchmark_spec.json"
    case_ids = [case["id"] for case in spec.get("cases", [])]
    if (spec.get("protocol_version") != "1.7.0" or manifest.get("protocol_version") != "1.7.0"
            or spec != read(registered) or len(case_ids) != 12 or len(set(case_ids)) != 12
            or any(case.get("phase") != "E" for case in spec["cases"])
            or manifest.get("validation_status") != PHASE_E_REFERENCE_STATUS or "review" in manifest
            or manifest.get("convention") != CONVENTION or manifest.get("normalized") is not True
            or manifest.get("material_contract") != spec["material_contract"]
            or manifest.get("suite_sha256") != sha(registered)
            or not isinstance(manifest.get("public_candidate_commit"), str)
            or re.fullmatch(r"[0-9a-f]{40}", manifest["public_candidate_commit"]) is None
            or not isinstance(manifest.get("records"), dict) or set(manifest["records"]) != set(case_ids)):
        raise ValueError("Unsupported experimental Phase E dataset, suite, material or coordinate contract")
    _public_reference_data(manifest)
    cohorts = manifest.get("source_cohorts")
    if (not isinstance(cohorts, dict) or set(cohorts) != {PHASE_E_REFERENCE_COHORT}
            or not isinstance(cohorts[PHASE_E_REFERENCE_COHORT], dict)
            or set(cohorts[PHASE_E_REFERENCE_COHORT]) != {"evidence_sha256", "description"}
            or not isinstance(cohorts[PHASE_E_REFERENCE_COHORT]["description"], str)):
        raise ValueError("Phase E retained source cohort is missing or changed")
    dataset = _phase_e_capsule(directory, manifest.get("dataset"))
    if (manifest.get("reference_id") != "sha256:" + manifest["dataset"]["sha256"]
            or dataset.get("schema") != "coilem.phase_e_selected_waveforms/v1"
            or dataset.get("protocol_version") != "1.7.0" or dataset.get("convention") != CONVENTION
            or dataset.get("normalized") is not True or dataset.get("material_contract") != spec["material_contract"]
            or not isinstance(dataset.get("cases"), dict) or set(dataset["cases"]) != set(case_ids)):
        raise ValueError("Phase E dataset identity does not bind the complete selected waveform packet")
    source = _phase_e_capsule(directory, manifest.get("source_evidence"))
    if (cohorts[PHASE_E_REFERENCE_COHORT]["evidence_sha256"] != manifest["source_evidence"]["sha256"]
            or source.get("schema") != "coilem.phase_e_retained_source_evidence/v1"
            or source.get("status") != PHASE_E_REFERENCE_STATUS
            or source.get("original_gates_or_tolerances_changed") is not False
            or source.get("selection_counts") != {"baseline": 9, "half_airgap_mesh": 3}):
        raise ValueError("Phase E retained source evidence or mesh selection changed")
    source_files = source.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise ValueError("Phase E requires retained public source-file evidence")
    source_data = {}
    for entry in source_files:
        if (not isinstance(entry, dict) or set(entry) != {"file", "sha256"}
                or not _sha256(entry.get("sha256")) or not isinstance(entry.get("file"), str)
                or not entry["file"].startswith("benchmarks/")):
            raise ValueError("Phase E source evidence must name hash-bound public benchmark artifacts")
        retained = checked_json(DATA_ROOT, entry["file"], entry["sha256"])
        if not isinstance(retained, dict) or retained.get("measured_commit") != manifest["public_candidate_commit"]:
            raise ValueError("Phase E retained source has a different measured candidate")
        if retained.get("schema") in source_data:
            raise ValueError("Phase E retained source evidence is duplicated")
        source_data[retained.get("schema")] = retained
    if set(source_data) != {"coilem.windows_v051_waveforms/v1", "coilem.windows_v051_benchmark_evidence/v1",
                            "coilem.windows_v051_publication_provenance/v1"}:
        raise ValueError("Phase E requires the original waveform, results and provenance artifacts")
    provenance = source_data["coilem.windows_v051_publication_provenance/v1"]
    if (provenance.get("material_contract") != spec["material_contract"]
            or (provenance.get("suite_sha256") or {}).get("1.7") != manifest["suite_sha256"]):
        raise ValueError("Phase E retained source changed its registered material or request suite")
    retained_waves = source_data["coilem.windows_v051_waveforms/v1"]
    retained_cases = retained_waves.get("cogging")
    if (retained_waves.get("convention") != CONVENTION or not isinstance(retained_cases, list)
            or len(retained_cases) != 12 or any(not isinstance(row, dict) for row in retained_cases)
            or {row.get("case_id") for row in retained_cases} != set(case_ids)):
        raise ValueError("Phase E retained waveform selection is incomplete")
    retained_cases = {row["case_id"]: row for row in retained_cases}
    checks = _phase_e_capsule(directory, manifest.get("self_checks"))
    if (checks.get("schema") != "coilem.phase_e_reference_self_checks/v1"
            or checks.get("status") != PHASE_E_REFERENCE_STATUS
            or checks.get("original_gates_or_tolerances_changed") is not False
            or checks.get("selection_policy") != "RETAINED_CORRECTED_HALF_MESH_SELECTION"
            or not isinstance(checks.get("cases"), dict) or set(checks["cases"]) != set(case_ids)):
        raise ValueError("Phase E self-check metadata is incomplete or reclassified")
    records = {}
    for case in spec["cases"]:
        case_id, job = case["id"], case["jobs"][0]
        entry = manifest["records"][case_id]
        if (not isinstance(entry, dict) or set(entry) != {"file", "sha256", "input_sha256", "source_cohort"}
                or not _sha256(entry.get("sha256")) or entry.get("source_cohort") != PHASE_E_REFERENCE_COHORT
                or entry.get("input_sha256") != job["input_sha256"]):
            raise ValueError("Phase E record input or source cohort mismatch")
        record = checked_json(directory, entry["file"], entry["sha256"])
        _public_reference_data(record)
        if (not isinstance(record, dict) or record.get("schema") != "coilem.femm_reference/v2"
                or record.get("case_id") != case_id or record.get("phase") != "E"
                or record.get("input_sha256") != job["input_sha256"] or record.get("convention") != CONVENTION
                or record.get("normalized") is not True or record.get("reference_id") != manifest["reference_id"]
                or record.get("source_cohort") != PHASE_E_REFERENCE_COHORT
                or record.get("public_candidate_commit") != manifest["public_candidate_commit"]
                or record.get("validation_status") != PHASE_E_REFERENCE_STATUS):
            raise ValueError("Phase E record identity or experimental status mismatch")
        config = checked_json(DATA_ROOT, job["fixture"], job["fixture_sha256"])
        if canonical(config) != job["input_sha256"]:
            raise ValueError("Phase E registered input changed")
        result, actual = _phase_e_result(record, config)
        expected_dataset = {"input_sha256": job["input_sha256"],
                            "reference_selection": result["solve_metadata"]["reference_selection"],
                            "cogging_torque_waveform": result["cogging_torque_waveform"]}
        if dataset["cases"][case_id] != expected_dataset:
            raise ValueError("Phase E record waveform differs from its identified dataset")
        selected_wave = retained_cases[case_id].get("femm_selected")
        if (not isinstance(selected_wave, dict)
                or any(value != selected_wave.get(key) for key, value in result["cogging_torque_waveform"].items())):
            raise ValueError("Phase E packet changed the retained selected reference waveform")
        selection = result["solve_metadata"]["reference_selection"]
        source_mesh = "half-gap" if selection == "half_airgap_mesh" else "normal"
        measurements = provenance.get("cogging_measurements") or []
        if not isinstance(measurements, list) or any(not isinstance(row, dict) for row in measurements):
            raise ValueError("Phase E retained position provenance is malformed")
        selected = [row for row in measurements if row.get("case_id") == case_id and row.get("mesh") == source_mesh]
        if (len(selected) != 1 or selected[0].get("input_sha256") != job["input_sha256"]
                or selected[0].get("positions") != 25):
            raise ValueError("Phase E selected mesh has no matching retained position evidence")
        method, settings = selected[0].get("method") or {}, result["solve_metadata"]
        if (not isinstance(method, dict) or method.get("femm_version") != "4.2"
                or method.get("torque_method") != "weighted_stress_tensor"
                or type(method.get("precision")) not in (int, float) or not 0 < method["precision"] <= 1e-8
                or method.get("min_angle_deg") != 30
                or type(method.get("airgap_mesh_size_mm")) not in (int, float) or method["airgap_mesh_size_mm"] <= 0):
            raise ValueError("Phase E retained FEMM extraction recipe is incomplete")
        counts = method.get("mesh_element_count")
        if not isinstance(counts, list) or len(counts) != 25 or any(type(value) is not int or value <= 0 for value in counts):
            raise ValueError("Phase E requires per-position retained mesh counts")
        if any(settings.get(key) != method[key] for key in ("precision", "min_angle_deg", "airgap_mesh_size_mm", "mesh_element_count")):
            raise ValueError("Phase E reference metadata changed its retained FEMM mesh recipe")
        floor = case["cogging_floor_Nm"]
        expected_check = {"input_sha256": job["input_sha256"], "record_sha256": entry["sha256"],
                          "reference_selection": result["solve_metadata"]["reference_selection"],
                          "endpoint_mismatch_Nm": actual.endpoint_mismatch_Nm, "mean_Nm": actual.mean_Nm,
                          "registered_floor_Nm": floor,
                          "reference_cogging_period": "PASS" if actual.endpoint_mismatch_Nm <= floor else "FAIL",
                          "reference_cogging_mean": "PASS" if abs(actual.mean_Nm) <= floor else "FAIL"}
        check = checks["cases"][case_id]
        if not isinstance(check, dict) or set(check) != set(expected_check):
            raise ValueError("Phase E reference self-check names changed")
        for key, expected in expected_check.items():
            value = check[key]
            if isinstance(expected, (int, float)):
                if type(value) not in (int, float) or not math.isfinite(value) or not math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-12):
                    raise ValueError("Phase E self-check value disagrees with the selected reference")
            elif value != expected:
                raise ValueError("Phase E self-check input or original verdict changed")
        records[case_id] = result
    return manifest, records, canonical({"manifest": sha(directory / "manifest.json"), "records": manifest["records"]})


def load_suite(path):
    spec = read(path)
    if spec["schema"] != "coilem.benchmark_spec/v1" or spec["protocol_version"] not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ValueError("Unsupported suite protocol")
    if spec["convention"] != CONVENTION:
        raise ValueError("Suite coordinate convention mismatch")
    for case in spec["cases"]:
        # A Phase E case is graded against its own registered absolute floor (protocol 1.7.0).
        floor = case.get("cogging_floor_Nm")
        if case["phase"] == "E" and not (isinstance(floor, (int, float)) and not isinstance(floor, bool) and math.isfinite(floor) and floor > 0):
            raise ValueError(f"Cogging case without a registered floor: {case['id']}")
    return spec


def _cap_compatible_inputs(spec, bridge):
    """Reuse measured fields only for registered 100 -> 200 iteration-cap changes."""
    change = (bridge or {}).get("iteration_cap_change")
    if change is None:
        return {}
    if change.get("schema") != "coilem.iteration_cap_bridge/v1" or spec["protocol_version"] != "1.4.0":
        raise ValueError("Unsupported reference iteration-cap bridge")
    measured = checked_json(DATA_ROOT, change["measured_suite"], change["measured_suite_sha256"])
    if measured["protocol_version"] != "1.3.0" or len(measured["cases"]) != len(spec["cases"]):
        raise ValueError("Reference iteration-cap bridge requires the complete 1.3 suite")
    if any(measured[key] != spec[key] for key in ("material_contract", "convention", "golden", "golden_sha256")):
        raise ValueError("Reference iteration-cap bridge changed the material or golden contract")
    compatible = {}
    for old_case, case in zip(measured["cases"], spec["cases"], strict=True):
        old_frame = {k: v for k, v in old_case.items() if k != "jobs"}
        frame = {k: v for k, v in case.items() if k != "jobs"}
        if old_frame != frame or len(old_case["jobs"]) != len(case["jobs"]):
            raise ValueError("Reference iteration-cap bridge changed cases, grids or gates")
        for old_job, job in zip(old_case["jobs"], case["jobs"], strict=True):
            if old_job == job:
                continue
            if old_job["stage"] != job["stage"] or old_job.keys() != job.keys():
                raise ValueError("Reference iteration-cap bridge changed job stages")
            old = checked_json(DATA_ROOT, old_job["fixture"], old_job["fixture_sha256"])
            current = checked_json(DATA_ROOT, job["fixture"], job["fixture_sha256"])
            expected = copy.deepcopy(old)
            if old["solve_params"].get("max_nonlinear_iterations") != 100:
                raise ValueError("Reference iteration-cap bridge requires an original cap of 100")
            expected["solve_params"]["max_nonlinear_iterations"] = 200
            if (current != expected or canonical(old) != old_job["input_sha256"]
                    or canonical(current) != job["input_sha256"]):
                raise ValueError("Reference iteration-cap bridge permits only a cap change from 100 to 200")
            compatible[case["id"]] = old_case["jobs"][0]["input_sha256"]
    if not compatible:
        raise ValueError("Reference iteration-cap bridge has no changed requests")
    return compatible


def load_bundle(directory, spec):
    manifest = read(directory / "manifest.json")
    if manifest.get("schema") == PHASE_F_BUNDLE_SCHEMA:
        if manifest.get("protocol_version") == "1.7.0":
            return _load_phase_e_bundle(directory, manifest, spec)
        return _load_phase_f_bundle(directory, manifest, spec)
    # A new validation frame can reuse unchanged physical fields only through
    # an explicit, hash-bound bridge. This never rewrites a measured record.
    bridge = None
    if manifest["protocol_version"] != spec["protocol_version"]:
        bridge = spec.get("reference_compatibility")
        if (
            not isinstance(bridge, dict)
            or bridge.get("schema") != "coilem.reference_validation_bridge/v1"
            or bridge.get("manifest_sha256") != sha(directory / "manifest.json")
            or bridge.get("measured_protocol_version") != manifest["protocol_version"]
            or bridge.get("reference_commit") != manifest["reference_commit"]
        ):
            raise ValueError("Reference protocol mismatch; an exact registered validation bridge is required")
    if (
        manifest["schema"] != "coilem.frozen_reference_bundle/v1"
        or manifest["convention"] != CONVENTION
        or manifest.get("normalized") is not True
        or manifest["material_contract"] != spec["material_contract"]
    ):
        raise ValueError("Reference material, protocol or coordinate contract mismatch; register a new bundle")
    compatible_inputs = _cap_compatible_inputs(spec, bridge)
    records = {}
    for case in spec["cases"]:
        entry = manifest["records"].get(case["id"])
        if entry is None:
            continue
        record = checked_json(directory, entry["file"], entry["sha256"])
        if (
            entry["input_sha256"] != compatible_inputs.get(case["id"], case["jobs"][0]["input_sha256"])
            or record["input_sha256"] != entry["input_sha256"]
            or record["case_id"] != case["id"]
            or record["phase"] != case["phase"]
            or record["convention"] != CONVENTION
            or record.get("normalized") is not True
            or record["reference_commit"] != manifest["reference_commit"]
            or (case["phase"] == "D" and record["protocol_sha256"] != (
                bridge.get("six_step_protocol_sha256", {}).get(case["id"]) if bridge else case["protocol_sha256"]
            ))
        ):
            raise ValueError(f"Reference input or identity mismatch: {case['id']}; register a new bundle")
        records[case["id"]] = record["result"]
    if manifest.get("validation_status") == "REVIEWED_FOR_REGISTERED_PARITY":
        require_reviewed_bundle(directory, manifest, spec)
    return manifest, records, canonical({"manifest": sha(directory / "manifest.json"), "records": manifest["records"]})


def require_reviewed_bundle(directory, manifest, spec):
    """An accepted reference status must bind the actual scoped review receipt."""
    if manifest.get("schema") == PHASE_F_BUNDLE_SCHEMA:
        if manifest.get("protocol_version") == "1.7.0":
            raise ValueError("Phase E is an experimental reference, without qualification acceptance")
        return _require_phase_f_review(directory, manifest, spec)
    if manifest.get("validation_status") != "REVIEWED_FOR_REGISTERED_PARITY":
        raise ValueError("Reference bundle still requires review")
    entry = manifest.get("review") or {}
    review = checked_json(directory, entry["file"], entry["sha256"])
    required = {case["id"] for case in spec["cases"]} - {"ornl_prius_2004_ipm"}
    registered = DATA_ROOT / "benchmarks/abcd-v1.6/benchmark_spec.json"
    if (review.get("schema") != "coilem.protocol16_reference_review/v1"
            or review.get("decision") != "ACCEPTED_FOR_REGISTERED_PARITY"
            or review.get("suite_sha256") != manifest.get("suite_sha256")
            or sha(registered) != review.get("suite_sha256") or read(registered) != spec
            or review.get("reference_commit") != manifest["reference_commit"]
            or review.get("parent_manifest_sha256") != manifest.get("parent_manifest_sha256")
            or review.get("parent_bundle_sha256") != manifest.get("parent_bundle_sha256")
            or set(review.get("cases", {})) != required):
        raise ValueError("Reference review does not cover this bundle and suite")
    return review


def verify_materials(expected):
    from backend.material_contract import load_electrical_steel_curve
    from backend.public_material_catalog import MAGNET_SOLVER_INPUTS

    if load_electrical_steel_curve(expected["steel_grade"]).sha256 != expected["curve_sha256"]:
        raise ValueError("Steel curve changed; register a new reference bundle")
    for grade, props in expected["magnets"].items():
        if MAGNET_SOLVER_INPUTS[grade][1:3] != (props["Br_T"], props["mu_r"]):
            raise ValueError(f"Magnet contract changed: {grade}; register a new reference bundle")
