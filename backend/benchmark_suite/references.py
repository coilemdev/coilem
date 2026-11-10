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


# coilEM solve options that a reference solver never reads, with the one change a bridge may register for
# each. FEMM solves its own nonlinear problem, so changing coilEM's nonlinear method leaves a frozen FEMM
# record valid for the changed request (protocol 1.9.0). Anything else needs a new reference bundle.
REFERENCE_INDEPENDENT_SOLVE_OPTIONS = {"nonlinear_solver": ("picard", "newton")}


def _solve_option_compatible_inputs(spec, bridge):
    """Reuse frozen records for requests that differ from the measured suite only in reference-independent options."""
    change = (bridge or {}).get("solve_option_change")
    if change is None:
        return {}
    options = change.get("solve_params")
    if (
        change.get("schema") != "coilem.solve_option_bridge/v1"
        or not isinstance(options, dict)
        or not options
        or any(
            not isinstance(rule, dict) or REFERENCE_INDEPENDENT_SOLVE_OPTIONS.get(name) != (rule.get("from"), rule.get("to"))
            for name, rule in options.items()
        )
    ):
        raise ValueError("Unsupported reference solve-option bridge")
    measured = checked_json(DATA_ROOT, change["measured_suite"], change["measured_suite_sha256"])
    if measured["protocol_version"] != bridge["measured_protocol_version"] or len(measured["cases"]) != len(spec["cases"]):
        raise ValueError("Reference solve-option bridge requires the complete measured suite")
    if any(measured[key] != spec[key] for key in ("material_contract", "convention", "golden", "golden_sha256")):
        raise ValueError("Reference solve-option bridge changed the material or golden contract")
    compatible = {}
    for old_case, case in zip(measured["cases"], spec["cases"], strict=True):
        old_frame = {k: v for k, v in old_case.items() if k != "jobs"}
        frame = {k: v for k, v in case.items() if k != "jobs"}
        if old_frame != frame or len(old_case["jobs"]) != len(case["jobs"]):
            raise ValueError("Reference solve-option bridge changed cases, grids or gates")
        for old_job, job in zip(old_case["jobs"], case["jobs"], strict=True):
            if old_job == job:
                continue
            if old_job["stage"] != job["stage"] or old_job.keys() != job.keys():
                raise ValueError("Reference solve-option bridge changed job stages")
            old = checked_json(DATA_ROOT, old_job["fixture"], old_job["fixture_sha256"])
            current = checked_json(DATA_ROOT, job["fixture"], job["fixture_sha256"])
            expected = copy.deepcopy(old)
            for name, rule in options.items():
                if old["solve_params"].get(name) == rule["from"]:
                    expected["solve_params"][name] = rule["to"]
            if (current == old or current != expected or canonical(old) != old_job["input_sha256"]
                    or canonical(current) != job["input_sha256"]):
                raise ValueError("Reference solve-option bridge permits only its registered solve-option changes")
            compatible[case["id"]] = old_case["jobs"][0]["input_sha256"]
    if not compatible:
        raise ValueError("Reference solve-option bridge has no changed requests")
    return compatible


def _compatible_inputs(spec, bridge):
    kinds = {"iteration_cap_change", "solve_option_change", "cogging_native_mesh_change"}
    if bridge and len(kinds & bridge.keys()) > 1:
        raise ValueError("A reference bridge registers one kind of request change")
    return {**_cap_compatible_inputs(spec, bridge), **_solve_option_compatible_inputs(spec, bridge),
            **_cogging_mesh_compatible_inputs(spec, bridge)}


def _cogging_mesh_compatible_inputs(spec, bridge):
    """Bind very-fine native requests to the separately fixed half-gap reference recipe."""
    change = (bridge or {}).get("cogging_native_mesh_change")
    if change is None:
        return {}
    if (spec["protocol_version"] != "1.7.1" or change.get("schema") != "coilem.cogging_native_mesh_bridge/v1"
            or change.get("from") != "normal" or change.get("to") != "very_fine"):
        raise ValueError("Unsupported cogging native-mesh bridge")
    measured = checked_json(DATA_ROOT, change["measured_suite"], change["measured_suite_sha256"])
    if (measured["protocol_version"] != "1.7.0" or len(measured["cases"]) != 3 or len(spec["cases"]) != 3
            or any(measured[key] != spec[key] for key in ("material_contract", "convention", "golden", "golden_sha256"))):
        raise ValueError("Cogging mesh bridge requires the three-case measured physical contract")
    compatible = {}
    for old_case, case in zip(measured["cases"], spec["cases"], strict=True):
        if (case["phase"] != "E" or {k:v for k,v in case.items() if k != "jobs"} != {k:v for k,v in old_case.items() if k != "jobs"}
                or len(case["jobs"]) != 1 or len(old_case["jobs"]) != 1):
            raise ValueError("Cogging mesh bridge changed cases, floors or stages")
        old_job, job = old_case["jobs"][0], case["jobs"][0]
        old = checked_json(DATA_ROOT, old_job["fixture"], old_job["fixture_sha256"])
        current = checked_json(DATA_ROOT, job["fixture"], job["fixture_sha256"])
        expected = copy.deepcopy(old)
        expected["solve_params"]["mesh_density"] = "very_fine"
        if (old["solve_params"]["mesh_density"] != "normal" or current != expected or job["stage"] != old_job["stage"]
                or canonical(old) != old_job["input_sha256"] or canonical(current) != job["input_sha256"]):
            raise ValueError("Cogging mesh bridge permits only normal to very_fine native mesh density")
        compatible[case["id"]] = old_job["input_sha256"]
    return compatible


def _reviewed_suite(spec):
    """The suite a reviewed bundle was accepted for: this one, or the measured suite a solve-option bridge reuses."""
    bridge = spec.get("reference_compatibility") or {}
    mesh = bridge.get("cogging_native_mesh_change")
    if mesh is not None:
        _cogging_mesh_compatible_inputs(spec, bridge)
        return checked_json(DATA_ROOT, mesh["measured_suite"], mesh["measured_suite_sha256"])
    change = bridge.get("solve_option_change")
    if change is None:
        return spec
    _solve_option_compatible_inputs(spec, bridge)  # raises unless only registered options changed
    return checked_json(DATA_ROOT, change["measured_suite"], change["measured_suite_sha256"])


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
    compatible_inputs = _compatible_inputs(spec, bridge)
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
    # A solve-option bridge (protocol 1.9.0) reuses the review of the suite it was measured for.
    reviewed = _reviewed_suite(spec)
    if review.get("schema") == "coilem.cogging_reference_review/v1":
        return _require_cogging_review(directory, manifest, reviewed, review)
    required = {case["id"] for case in reviewed["cases"]} - {"ornl_prius_2004_ipm"}
    registered = DATA_ROOT / "benchmarks/abcd-v1.6/benchmark_spec.json"
    if (review.get("schema") != "coilem.protocol16_reference_review/v1"
            or review.get("decision") != "ACCEPTED_FOR_REGISTERED_PARITY"
            or review.get("suite_sha256") != manifest.get("suite_sha256")
            or sha(registered) != review.get("suite_sha256") or read(registered) != reviewed
            or review.get("reference_commit") != manifest["reference_commit"]
            or review.get("parent_manifest_sha256") != manifest.get("parent_manifest_sha256")
            or review.get("parent_bundle_sha256") != manifest.get("parent_bundle_sha256")
            or set(review.get("cases", {})) != required):
        raise ValueError("Reference review does not cover this bundle and suite")
    return review


def _require_cogging_review(directory, manifest, reviewed, review):
    registered = DATA_ROOT / "benchmarks/cogging-refined-v1/measured-suite.json"
    required = {case["id"] for case in reviewed["cases"]}
    if (review.get("decision") != "ACCEPTED_FOR_REGISTERED_PARITY" or manifest["protocol_version"] != "1.7.0"
            or sha(registered) != review.get("suite_sha256") or review["suite_sha256"] != manifest.get("suite_sha256")
            or read(registered) != reviewed or len(required) != 3 or set(review.get("cases", {})) != required
            or review.get("reference_commit") != manifest["reference_commit"]
            or review.get("reference_mesh_policy") != {"mesh_density": "normal", "airgap_mesh_scale": 0.5,
                                                       "precision": 1e-8, "min_angle_deg": 30}):
        raise ValueError("Cogging reference review does not cover the registered refined cohort")
    geometry_entry = review.get("current_geometry_review") or {}
    geometry = checked_json(directory, geometry_entry["file"], geometry_entry["sha256"])
    if (geometry.get("schema") != "coilem.cogging_geometry_review/v1" or set(geometry.get("cases", {})) != required
            or any(row.get("old_graph_projection_differences") != 0 for row in geometry["cases"].values())
            or any(sha(DATA_ROOT / name) != digest for name, digest in geometry["current_sources"].items())):
        raise ValueError("Refined reference geometry review does not match current geometry sources")
    for case in reviewed["cases"]:
        cid = case["id"]
        entry = manifest["records"][cid]
        record = checked_json(directory, entry["file"], entry["sha256"])
        audit = review["cases"][cid]
        wave = record["result"]["cogging_torque_waveform"]
        angles, values = wave["electrical_angle_deg"], wave["torque_Nm"]
        cfg = checked_json(DATA_ROOT, case["jobs"][0]["fixture"], case["jobs"][0]["fixture_sha256"])
        period = 180 * math.gcd(cfg["stator"]["slot_count"], cfg["rotor"]["pole_count"]) / cfg["stator"]["slot_count"]
        if (case["phase"] != "E" or audit.get("record_sha256") != entry["sha256"] or audit.get("positions_verified") != 25
                or audit.get("self_checks") != {"reference_cogging_period": "PASS", "reference_cogging_mean": "PASS"}
                or len(angles) != 25 or len(values) != 25 or not all(math.isfinite(value) for value in values)
                or any(abs(theta - i * period / 24) > 1e-10 for i, theta in enumerate(angles))
                or abs(values[-1] - values[0]) > case["cogging_floor_Nm"]
                or abs(sum(values[:-1]) / 24) > case["cogging_floor_Nm"]):
            raise ValueError(f"Invalid or incomplete refined cogging reference: {cid}")
    return review


def verify_materials(expected):
    from backend.material_contract import load_electrical_steel_curve
    from backend.public_material_catalog import MAGNET_SOLVER_INPUTS

    if load_electrical_steel_curve(expected["steel_grade"]).sha256 != expected["curve_sha256"]:
        raise ValueError("Steel curve changed; register a new reference bundle")
    for grade, props in expected["magnets"].items():
        if MAGNET_SOLVER_INPUTS[grade][1:3] != (props["Br_T"], props["mu_r"]):
            raise ValueError(f"Magnet contract changed: {grade}; register a new reference bundle")
