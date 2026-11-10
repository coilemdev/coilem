"""Reproduce protocol 1.10.0 and its data-only, explicitly sourced E/F registry."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from backend.benchmark_suite.contract import canonical, read, sha
from backend.benchmark_suite.ef_review import audit

ROOT = Path(__file__).resolve().parents[1]
SUITE = "benchmarks/af-v1.10/benchmark_spec.json"
BUNDLE = "benchmarks/reference-baselines/protocol110-combined-20261110"
EVIDENCE = "benchmarks/femm-ef-20261110"


def build_files(root=ROOT):
    files = {}

    def put(name, value):
        files[name] = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
        return hashlib.sha256(files[name]).hexdigest()

    def digest(name):
        return hashlib.sha256(files[name]).hexdigest() if name in files else sha(root / name)

    rows = {row["alias"]: row for row in read(root / EVIDENCE / "femm-results.json")["cases_and_controls"]}
    jobs = read(root / "tools/femm_reference/data/jobs.json")
    normal_alias = {row["case_id"]: row["alias"] for row in jobs["e_jobs"] if row["kind"] == "normal"}
    normal_alias.update({row["case_id"]: alias for alias, row in jobs["f_jobs"].items() if alias not in {"f10", "f11"}})
    evidence_files = {f"{EVIDENCE}/{name}": sha(root / EVIDENCE / name)
                      for name in ("femm-results.json", "field-hashes.json", "assembly-comparison.json")}
    policy_name = "benchmarks/af-v1.10/phase-f-source-policy.json"
    policy = read(root / policy_name)
    components, cases, entries, reviews = [], [], {}, {}

    def component(name, source_path, bundle, active=None, newton=False):
        source = json.loads(files[source_path]) if source_path in files else read(root / source_path)
        manifest = json.loads(files[bundle + "/manifest.json"]) if bundle + "/manifest.json" in files else read(root / bundle / "manifest.json")
        entry = {"id": name, "suite": source_path, "suite_sha256": digest(source_path), "reference_bundle": bundle,
                 "reference_manifest_sha256": digest(bundle + "/manifest.json"),
                 "reference_bundle_sha256": canonical({"manifest": digest(bundle + "/manifest.json"), "records": manifest["records"]})}
        if newton:
            entry["native_solve_option_change"] = {"nonlinear_solver": {"from": "picard", "to": "newton"}}
        components.append(entry)
        cases.extend(active if active is not None else source["cases"])
        reviews[name] = {"decision": "ACCEPTED_FOR_REGISTERED_PARITY", "review_sha256": manifest["review"]["sha256"]}
        for cid, record in manifest["records"].items():
            entries[cid] = {"component": name, **record, "reference_commit": manifest["reference_commit"]}

    base = read(root / "benchmarks/abcd-v1.9/benchmark_spec.json")
    component("abcd", "benchmarks/abcd-v1.9/benchmark_spec.json", "benchmarks/reference-baselines/protocol16-reviewed-20261103")
    refined = read(root / "benchmarks/cogging-refined-v1/benchmark_spec.json")
    refined_ids = {c["id"] for c in refined["cases"]}

    for name, phase, include, cohort in (
        ("e-normal", "E", lambda cid: cid not in refined_ids, None),
        ("f-original", "F", lambda cid: "30p27s_hub" not in cid, "original"),
        ("f-hub", "F", lambda cid: "30p27s_hub" in cid, "hub_variant"),
    ):
        old = read(root / f"tools/femm_reference/data/spec_{phase.lower()}.json")
        measured = copy.deepcopy(old)
        measured["cases"] = [c for c in measured["cases"] if include(c["id"])]
        measured.pop("phase_e" if phase == "E" else "phase_f", None)
        for case in measured["cases"]:
            for job in case["jobs"]:
                source = root / "tools/femm_reference/data" / job["fixture"]
                target = f"benchmarks/af-v1.10/measured-fixtures/{case['id']}.json"
                files[target] = source.read_bytes()
                job["fixture"] = target
                if digest(target) != job["fixture_sha256"] or canonical(read(source)) != job["input_sha256"]:
                    raise ValueError("Original E/F request differs from its sealed bytes")
        measured_path = f"benchmarks/af-v1.10/components/{name}.json"
        measured_sha = put(measured_path, measured)
        commit = "341cd09342d58323689491ca060a913a34474ed1" if phase == "E" else policy["cohorts"][cohort]["reference_commit"]
        child = f"benchmarks/reference-baselines/{name}-20261110"
        manifest = {"schema": "coilem.frozen_reference_bundle/v1", "protocol_version": old["protocol_version"],
                    "convention": old["convention"], "normalized": True, "material_contract": old["material_contract"],
                    "reference_commit": commit, "suite_sha256": measured_sha,
                    "validation_status": "REVIEWED_FOR_REGISTERED_PARITY", "records": {}}
        review = {"schema": "coilem.ef_component_reference_review/v1", "decision": "ACCEPTED_FOR_REGISTERED_PARITY",
                  "suite": measured_path, "suite_sha256": measured_sha, "reference_commit": commit,
                  "field_ledger": EVIDENCE + "/field-hashes.json", "evidence_files": evidence_files, "cases": {},
                  "scope": "Frozen reference fields for registered software parity only; native platform qualification is separate"}
        if phase == "F":
            review.update(source_cohort=cohort, source_policy={"file": policy_name, "sha256": digest(policy_name)})
        for case in measured["cases"]:
            cid = case["id"]
            alias = normal_alias[cid]
            row = rows[alias]
            if row["input_sha256"] != case["jobs"][0]["input_sha256"]:
                raise ValueError("Measured E/F record input mismatch")
            record = {"schema": "coilem.frozen_reference_record/v1", "case_id": cid, "phase": phase,
                      "input_sha256": row["input_sha256"], "reference_commit": commit,
                      "normalized": True, "convention": old["convention"], "result": row["result"],
                      "assembly_envelope_sha256": row["assembly_envelope_sha256"],
                      "historical_self_checks": row["self_checks"]}
            record_sha = put(f"{child}/{cid}.json", record)
            manifest["records"][cid] = {"file": cid + ".json", "sha256": record_sha, "input_sha256": row["input_sha256"]}
            cfg = json.loads(files[case["jobs"][0]["fixture"]])
            review["cases"][cid] = {"record_sha256": record_sha, "alias": alias, "audit": audit(case, row["result"], cfg)}
        review_sha = put(child + "/review.json", review)
        manifest["review"] = {"file": "review.json", "sha256": review_sha}
        manifest["review_artifacts"] = [manifest["review"]]
        put(child + "/manifest.json", manifest)
        current = read(root / f"benchmarks/abcd-v{'1.7' if phase == 'E' else '1.8'}/benchmark_spec.json")
        component(name, measured_path, child, [c for c in current["cases"] if include(c["id"])], newton=True)
        if phase == "E":
            component("e-refined", "benchmarks/cogging-refined-v1/benchmark_spec.json",
                      "benchmarks/reference-baselines/cogging-refined-20261110")
    spec = {key: copy.deepcopy(base[key]) for key in ("schema", "convention", "material_contract", "golden", "golden_sha256")}
    order = {case["id"]: index for index, case in enumerate(base["cases"]
             + read(root / "benchmarks/abcd-v1.7/benchmark_spec.json")["cases"]
             + read(root / "benchmarks/abcd-v1.8/benchmark_spec.json")["cases"])}
    cases.sort(key=lambda case: order[case["id"]])
    spec.update(protocol_version="1.10.0", components=components, cases=cases,
                scope="Combined A-F benchmark; existing grids and numerical gates; three registered very-fine E requests")
    suite_sha = put(SUITE, spec)
    combined_review = {"schema": "coilem.combined_reference_review/v1", "decision": "ACCEPTED_FOR_REGISTERED_PARITY",
                       "suite_sha256": suite_sha, "components": reviews,
                       "scope": "Reference acceptance only; complete candidate/platform records require new measured runs"}
    review_sha = put(BUNDLE + "/review.json", combined_review)
    put(BUNDLE + "/manifest.json", {"schema": "coilem.combined_reference_bundle/v1", "protocol_version": "1.10.0",
        "suite": SUITE, "suite_sha256": suite_sha, "convention": spec["convention"], "normalized": True,
        "material_contract": spec["material_contract"], "reference_commit": None,
        "reference_commits": sorted({row["reference_commit"] for row in entries.values()}),
        "validation_status": "REVIEWED_FOR_REGISTERED_PARITY", "components": components, "records": entries,
        "review": {"file": "review.json", "sha256": review_sha},
        "review_artifacts": [{"file": "review.json", "sha256": review_sha}]})
    return files


def main():
    files = build_files()
    for name, data in files.items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"Registered protocol 1.10.0: 69 cases, 68 reference records; {len(files)} reproducible files")


if __name__ == "__main__":
    main()
