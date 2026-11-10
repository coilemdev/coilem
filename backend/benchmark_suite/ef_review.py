"""Recheck scoped E/F reference receipts without reading native comparison fields."""
from __future__ import annotations

import math

from backend.benchmark_suite.contract import checked_json, read, sha
from backend.benchmark_suite.metrics import validate_abc


def audit(case, result, config):
    if case["phase"] == "E":
        wave = result["cogging_torque_waveform"]
        angles, values = wave["electrical_angle_deg"], wave["torque_Nm"]
        period = 180 * math.gcd(config["stator"]["slot_count"], config["rotor"]["pole_count"]) / config["stator"]["slot_count"]
        if (len(values) != 25 or len(angles) != 25 or not all(math.isfinite(v) for v in values)
                or any(abs(theta - i * period / 24) > 1e-10 for i, theta in enumerate(angles))):
            raise ValueError("Incomplete E reference period")
        mean, closure = math.fsum(values[:-1]) / 24, abs(values[-1] - values[0])
        if abs(mean) > case["cogging_floor_Nm"] or closure > case["cogging_floor_Nm"]:
            raise ValueError("E reference failed its original mean or periodicity floor")
        return {"positions": 25, "mean_Nm": mean, "endpoint_mismatch_Nm": closure}
    if case["phase"] != "F":
        raise ValueError("E/F review contains another phase")
    validate_abc(result, config, native=False)
    metadata = result["solve_metadata"]
    if (metadata["precision"] != 1e-8 or metadata["min_angle_deg"] != 30
            or metadata["torque_body"] != "rotor" or metadata["torque_method"] != "weighted_stress"
            or not metadata["back_emf_derivative_policy"].get("no_fitting_filtering_interpolation_resampling_or_rescaling")):
        raise ValueError("F reference extraction contract changed")
    phases = metadata["phase_fundamentals"]
    balance = [100 * abs(phases[p]["rms_V"] - phases["A"]["rms_V"]) / phases["A"]["rms_V"] for p in ("B", "C")]
    if max(balance) > 1:
        raise ValueError("F reference phase amplitudes are unbalanced")
    # Reconstruct the registered one-sided/central native-grid derivative from
    # public flux using scalar differences, independently of the producer.
    angles = [math.radians(i * 7.5) for i in range(48)]
    order = [(-i) % 48 for i in range(48)]
    omega_e = config["solve_params"]["rated_speed_rpm"] * 2 * math.pi / 60 * config["rotor"]["pole_count"] / 2
    for phase in ("a", "b", "c"):
        flux = result["no_load_flux_linkage_waveform"][f"phase_{phase}_Wb"]
        native = [flux[i] for i in order]
        derivative = [(native[1] - native[0]) / (angles[1] - angles[0])]
        for i in range(1, 47):
            before, after = angles[i] - angles[i - 1], angles[i + 1] - angles[i]
            derivative.append(-after / (before * (before + after)) * native[i - 1]
                              + (after - before) / (before * after) * native[i]
                              + before / (after * (before + after)) * native[i + 1])
        derivative.append((native[-1] - native[-2]) / (angles[-1] - angles[-2]))
        voltage = result["back_emf_waveform"][f"phase_{phase}_V"]
        if any(not math.isclose(value, -omega_e * derivative[index], rel_tol=1e-10, abs_tol=1e-10)
               for value, index in zip(voltage, order, strict=True)):
            raise ValueError("F reference voltage differs from its registered flux derivative")
        real = math.fsum(v * math.cos(theta) for v, theta in zip(voltage, angles, strict=True)) / 48
        imag = -math.fsum(v * math.sin(theta) for v, theta in zip(voltage, angles, strict=True)) / 48
        if not math.isclose(math.sqrt(2) * math.hypot(real, imag), phases[phase.upper()]["rms_V"], rel_tol=1e-12):
            raise ValueError("F reference harmonic differs from its waveform")
    current = config["solve_params"]["current_amplitude_A"]
    if current > 0:
        from backend.benchmark_suite.metrics import energy_balance_ratio

        ratio = energy_balance_ratio(result, config)
        if result["summary"]["avg_torque_Nm"] <= 0 or ratio is None or abs(ratio - 1) > .05:
            raise ValueError("F reference loaded sign or energy-balance check failed")
    return {"positions": 96, "phase_balance_pct": balance,
            "voltage_from_flux": "PASS", "harmonic_from_waveform": "PASS",
            "loaded_sign_and_energy": "PASS" if current > 0 else "NOT_APPLICABLE_NOLOAD_CASE",
            "mean_torque_Nm": result["summary"]["avg_torque_Nm"],
            "back_emf_fundamental_V": result["summary"]["back_emf_fundamental_V"]}


def verify(directory, manifest, spec, review, root):
    if (review.get("decision") != "ACCEPTED_FOR_REGISTERED_PARITY"
            or manifest.get("suite_sha256") != review.get("suite_sha256")
            or checked_json(root, review["suite"], review["suite_sha256"]) != spec
            or manifest["reference_commit"] != review.get("reference_commit")
            or set(review.get("cases", {})) != {c["id"] for c in spec["cases"]}):
        raise ValueError("E/F reference review does not cover its component")
    for name, digest in review["evidence_files"].items():
        if sha(root / name) != digest:
            raise ValueError("E/F reference review evidence changed")
    ledger = read(root / review["field_ledger"])["positions"]
    assembled = {row["alias"]: row for row in read(root / "benchmarks/femm-ef-20261110/femm-results.json")["cases_and_controls"]}
    for case in spec["cases"]:
        cid = case["id"]
        entry = manifest["records"][cid]
        record = checked_json(directory, entry["file"], entry["sha256"])
        row = review["cases"][cid]
        cfg = checked_json(root, case["jobs"][0]["fixture"], case["jobs"][0]["fixture_sha256"])
        actual = audit(case, record["result"], cfg)
        points = [p for p in ledger if p["alias"] == row["alias"]]
        source = assembled[row["alias"]]
        if (row["record_sha256"] != entry["sha256"] or row["audit"] != actual
                or record["result"] != source["result"] or record["input_sha256"] != source["input_sha256"]
                or record["assembly_envelope_sha256"] != source["assembly_envelope_sha256"]
                or source["case_id"] != cid or source["phase"] != case["phase"]
                or len(points) != actual["positions"] or len({p["position_id"] for p in points}) != len(points)
                or any(len(p[key]) != 64 for p in points for key in ("model_sha256", "answer_sha256", "physical_payload_sha256"))):
            raise ValueError("E/F reference review differs from its numerical fields or source ledger")
    if any(c["phase"] == "F" for c in spec["cases"]):
        policy = checked_json(root, review["source_policy"]["file"], review["source_policy"]["sha256"])
        if (policy.get("schema") != "coilem.phase_f_source_policy/v1"
                or policy.get("historical_lrk_failures_preserved") != 2
                or policy.get("uncertainty_bound_established") is not False
                or policy.get("single_producer_contract_satisfied") is not False
                or policy.get("cohorts", {}).get(review["source_cohort"], {}).get("reference_commit") != manifest["reference_commit"]):
            raise ValueError("F reference source-cohort policy is incomplete")
        inherited = checked_json(root, policy["evidence"]["inherited_lrk"], policy["evidence"]["inherited_lrk_sha256"])
        if any(counts.get("FAIL") != 2 for counts in inherited["corrected_counts"].values()):
            raise ValueError("Historical LRK failures must remain in the scoped reference policy")
    return review
