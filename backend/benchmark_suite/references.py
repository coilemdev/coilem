"""Data-only reference bundles, already normalized to public clockwise coordinates."""

import copy
import math

from backend.benchmark_suite import CONVENTION, SUPPORTED_PROTOCOL_VERSIONS
from backend.benchmark_suite.contract import DATA_ROOT, canonical, checked_json, read, sha


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
