"""Hash-bound composition of existing physical suites and reference collections."""
from __future__ import annotations

import copy
from collections import Counter

from backend.benchmark_suite.contract import canonical, checked_json, read, sha

SCHEMA = "coilem.combined_reference_bundle/v1"


def components(spec, root):
    """Verify complete, nonoverlapping coverage and only declared native Newton changes."""
    if spec.get("protocol_version") != "1.10.0" or not spec.get("components"):
        raise ValueError("Unsupported combined benchmark protocol")
    if (Counter(c["phase"] for c in spec["cases"]) != {"A": 19, "B": 20, "C": 5, "D": 3, "E": 12, "F": 10}
            or {entry["id"] for entry in spec["components"]} != {"abcd", "e-normal", "e-refined", "f-original", "f-hub"}):
        raise ValueError("Protocol 1.10 requires the complete registered A-F coverage")
    selected = {case["id"]: case for case in spec["cases"]}
    if len(selected) != len(spec["cases"]):
        raise ValueError("Duplicate combined benchmark case")
    seen, names, result = set(), set(), []
    for entry in spec["components"]:
        if entry["id"] in names:
            raise ValueError("Duplicate benchmark component")
        names.add(entry["id"])
        source = checked_json(root, entry["suite"], entry["suite_sha256"])
        if source.get("components") or source["protocol_version"] == "1.10.0":
            raise ValueError("Combined benchmark components cannot be nested")
        if any(source[key] != spec[key] for key in ("convention", "material_contract", "golden", "golden_sha256")):
            raise ValueError("Combined benchmark changed a component's physical contract")
        change = entry.get("native_solve_option_change")
        if change is not None and change != {"nonlinear_solver": {"from": "picard", "to": "newton"}}:
            raise ValueError("Combined benchmark permits only an explicit native Picard to Newton change")
        for before in source["cases"]:
            cid = before["id"]
            if cid in seen or cid not in selected:
                raise ValueError("Missing or overlapping combined benchmark coverage")
            seen.add(cid)
            after = selected[cid]
            if ({k: v for k, v in before.items() if k != "jobs"} != {k: v for k, v in after.items() if k != "jobs"}
                    or len(before["jobs"]) != len(after["jobs"])):
                raise ValueError("Combined benchmark changed component cases, floors, grids or gates")
            for old_job, job in zip(before["jobs"], after["jobs"], strict=True):
                old = checked_json(root, old_job["fixture"], old_job["fixture_sha256"])
                current = checked_json(root, job["fixture"], job["fixture_sha256"])
                expected = copy.deepcopy(old)
                if change is not None and old["solve_params"].get("nonlinear_solver") == "picard":
                    expected["solve_params"]["nonlinear_solver"] = "newton"
                if (current != expected or canonical(old) != old_job["input_sha256"] or canonical(current) != job["input_sha256"]
                        or old_job["stage"] != job["stage"] or old_job.keys() != job.keys()):
                    raise ValueError("Combined benchmark request differs from its registered component")
        result.append((entry, source))
    if seen != set(selected):
        raise ValueError("Combined benchmark does not cover every registered case")
    return result


def load(directory, spec, root, loader, reviewer):
    manifest = read(directory / "manifest.json")
    registered = components(spec, root)
    if (manifest.get("schema") != SCHEMA or manifest.get("protocol_version") != "1.10.0"
            or manifest.get("convention") != spec["convention"] or manifest.get("normalized") is not True
            or manifest.get("material_contract") != spec["material_contract"]
            or manifest.get("components") != spec["components"]
            or manifest.get("suite_sha256") != sha(root / manifest["suite"])):
        raise ValueError("Combined reference registry differs from the registered suite")
    if checked_json(root, manifest["suite"], manifest["suite_sha256"]) != spec:
        raise ValueError("Combined reference registry names a different suite")
    records, bindings, commits, reviews = {}, {}, set(), {}
    for entry, source in registered:
        child_dir = root / entry["reference_bundle"]
        checked_json(root, entry["reference_bundle"] + "/manifest.json", entry["reference_manifest_sha256"])
        child, fields, digest = loader(child_dir, source)
        if digest != entry["reference_bundle_sha256"]:
            raise ValueError("Combined reference component content hash mismatch")
        review = reviewer(child_dir, child, source)
        reviews[entry["id"]] = {"decision": review["decision"], "review_sha256": child["review"]["sha256"]}
        for case in source["cases"]:
            cid = case["id"]
            if cid not in fields:
                if cid != "ornl_prius_2004_ipm":
                    raise ValueError("Combined reference component is incomplete")
                continue
            records[cid] = fields[cid]
            bindings[cid] = {"component": entry["id"], **child["records"][cid],
                             "reference_commit": child["reference_commit"]}
        commits.add(child["reference_commit"])
    if manifest.get("records") != bindings or manifest.get("reference_commits") != sorted(commits):
        raise ValueError("Combined reference record or source identity changed")
    review = checked_json(directory, manifest["review"]["file"], manifest["review"]["sha256"])
    if (manifest.get("validation_status") != "REVIEWED_FOR_REGISTERED_PARITY"
            or review.get("schema") != "coilem.combined_reference_review/v1"
            or review.get("decision") != "ACCEPTED_FOR_REGISTERED_PARITY"
            or review.get("suite_sha256") != manifest["suite_sha256"] or review.get("components") != reviews):
        raise ValueError("Combined reference review is incomplete or changed")
    digest = canonical({"manifest": sha(directory / "manifest.json"), "records": bindings,
                        "components": {entry["id"]: entry["reference_bundle_sha256"] for entry, _ in registered}})
    return manifest, records, digest
