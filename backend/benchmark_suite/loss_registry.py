"""Hash-bound A-G composition; the historical A-F registry remains replayable."""
from __future__ import annotations

import copy

from backend.benchmark_suite.contract import canonical, checked_json, read, sha
from backend.benchmark_suite.loss_metrics import LOSS_KEYS, validate_reference

AF_SUITE = "benchmarks/af-v1.10/benchmark_spec.json"
LOSS_SUITE = "benchmarks/loss-v1/benchmark_spec.json"
SOURCE_CASES = {f"{fixture}-{load}" for fixture in ("inner-spm", "flat-ipm", "distributed-spm", "outer-spm")
                for load in ("no-load", "loaded")}


def verify_loss_suite(spec, root):
    if spec.get("protocol_version") != "1.12.0" or spec.get("component") != "losses" or len(spec["cases"]) != 16:
        raise ValueError("Phase G requires the complete 16-point stator/DC-copper registry")
    acquisition = spec["qualification"]
    summary = checked_json(root, acquisition["summary"], acquisition["summary_sha256"])
    audit = checked_json(root, acquisition["audit"], acquisition["audit_sha256"])
    requests = checked_json(root, acquisition["requests"], acquisition["requests_sha256"])
    if (not summary["numerical_reference_qualification_complete"] or audit["conditions_passed"] != 8
            or audit["rotor_loss_status"] != "experimental" or audit["full_motor_efficiency_qualified"]
            or set(requests) != SOURCE_CASES):
        raise ValueError("Phase G needs the completed scoped FEMM qualification")
    seen = set()
    for case in spec["cases"]:
        cid, speed = case["loss_case_id"], case["loss_speed_rpm"]
        if case["phase"] != "G" or cid not in SOURCE_CASES or speed not in (1500, 3000) or (cid, speed) in seen:
            raise ValueError("Duplicate or unsupported Phase G operating point")
        seen.add((cid, speed))
        if len(case["jobs"]) != 1 or case["jobs"][0]["stage"] != "native":
            raise ValueError("Phase G measures one full electrical-cycle native job per point")
        job = case["jobs"][0]
        actual = checked_json(root, job["fixture"], job["fixture_sha256"])
        expected = copy.deepcopy(requests[cid])
        expected["solve_params"]["rated_speed_rpm"] = speed
        if actual != expected or canonical(actual) != job["input_sha256"]:
            raise ValueError("Phase G request differs from the measured fixture, wire or sampling contract")
    return summary, audit


def verify_ag(spec, root):
    if spec.get("protocol_version") != "1.12.0" or {e["id"] for e in spec.get("components", [])} != {"af", "losses"}:
        raise ValueError("Protocol 1.12 requires the original A-F registry plus Phase G")
    registered = []
    for entry in spec["components"]:
        if entry["suite"] != (AF_SUITE if entry["id"] == "af" else LOSS_SUITE):
            raise ValueError("A-G component names a different physical registry")
        child = checked_json(root, entry["suite"], entry["suite_sha256"])
        if any(child[k] != spec[k] for k in ("convention", "material_contract", "golden", "golden_sha256")):
            raise ValueError("A-G composition changed the physical contract")
        if entry["id"] == "af":
            from backend.benchmark_suite.composition import components
            components(child, root)
        else:
            verify_loss_suite(child, root)
        registered.append((entry, child))
    expected = [case for entry, child in registered for case in child["cases"]]
    if spec["cases"] != expected or len({c["id"] for c in expected}) != 85:
        raise ValueError("A-G must preserve all 69 A-F cases and all 16 loss points exactly")
    return registered


def verify_loss_review(directory, manifest, spec, review, root):
    summary, audit = verify_loss_suite(spec, root)
    if (review.get("schema") != "coilem.loss_reference_review/v1"
            or review.get("decision") != "ACCEPTED_FOR_REGISTERED_PARITY"
            or review.get("suite_sha256") != sha(root / LOSS_SUITE)
            or review.get("suite_sha256") != manifest.get("suite_sha256")
            or manifest.get("reference_commit") != audit["source_commit"]
            or review.get("rotor_loss_included") is not False
            or review.get("material_accuracy_qualified") is not False
            or review.get("full_motor_efficiency_qualified") is not False
            or review.get("completion_audit_sha256") != spec["qualification"]["audit_sha256"]):
        raise ValueError("Loss reference review does not cover the numerical-only scope")
    for path, digest in review["evidence_files"].items():
        checked_json(root, path, digest)
    original = {row["case_id"]: row for row in summary["cases"]}
    for case in spec["cases"]:
        entry = manifest["records"][case["id"]]
        record = checked_json(directory, entry["file"], entry["sha256"])
        result = record["result"]
        config = checked_json(root, case["jobs"][0]["fixture"], case["jobs"][0]["fixture_sha256"])
        validate_reference(result, config)
        old = original[case["loss_case_id"]]
        watts = old["stator"][str(case["loss_speed_rpm"])]["femm_W"]
        expected = dict(zip(LOSS_KEYS, (watts["hysteresis_W"], watts["lamination_eddy_W"], watts["total_W"],
                                      old["copper"]["femm_geometry_reference"]["W"],
                                      old["copper"]["femm_geometry_reference"]["phase_resistance_ohm"]), strict=True))
        if (result["values"] != expected or result["source_reference_protocol_sha256"] != old["reference_protocol_sha256"]
                or old["reference_protocol_sha256"] != audit["evidence"][case["loss_case_id"]]["femm_protocol_sha256"]):
            raise ValueError("Frozen loss values differ from the completed FEMM evidence")
    return review


def load_ag(directory, spec, root, loader, reviewer):
    registered = verify_ag(spec, root)
    manifest = read(directory / "manifest.json")
    if (manifest.get("schema") != "coilem.combined_reference_bundle/v1" or manifest.get("protocol_version") != "1.12.0"
            or manifest.get("components") != spec["components"] or manifest.get("normalized") is not True
            or manifest.get("convention") != spec["convention"] or manifest.get("material_contract") != spec["material_contract"]
            or manifest.get("suite_sha256") != sha(root / manifest["suite"])
            or checked_json(root, manifest["suite"], manifest["suite_sha256"]) != spec):
        raise ValueError("A-G reference registry differs from its registered suite")
    records, bindings, commits, reviews = {}, {}, set(), {}
    for entry, child in registered:
        child_dir = root / entry["reference_bundle"]
        checked_json(child_dir, "manifest.json", entry["reference_manifest_sha256"])
        child_manifest, values, digest = loader(child_dir, child)
        if digest != entry["reference_bundle_sha256"]:
            raise ValueError("A-G reference component hash changed")
        accepted = reviewer(child_dir, child_manifest, child)
        reviews[entry["id"]] = {"decision": accepted["decision"], "review_sha256": child_manifest["review"]["sha256"]}
        for cid, value in values.items():
            if cid in records:
                raise ValueError("Overlapping A-G reference records")
            records[cid] = value
            bindings[cid] = {"component": entry["id"], "record": child_manifest["records"][cid]}
        commits.update(child_manifest.get("reference_commits") or [child_manifest["reference_commit"]])
    review = checked_json(directory, manifest["review"]["file"], manifest["review"]["sha256"])
    if (manifest.get("records") != bindings or manifest.get("reference_commits") != sorted(commits)
            or manifest.get("validation_status") != "REVIEWED_FOR_REGISTERED_PARITY"
            or review.get("schema") != "coilem.combined_reference_review/v1"
            or review.get("decision") != "ACCEPTED_FOR_REGISTERED_PARITY"
            or review.get("suite_sha256") != manifest["suite_sha256"] or review.get("components") != reviews):
        raise ValueError("A-G reference coverage or scoped review changed")
    digest = canonical({"manifest": sha(directory / "manifest.json"), "records": bindings,
                        "components": {e["id"]: e["reference_bundle_sha256"] for e, _ in registered}})
    return manifest, records, digest
