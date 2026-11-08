"""Join immutable candidate fields to a reviewed bundle, with zero field solves.

Use --native for a completed full-grid collection, --suite and
--reference-bundle for the registered inputs, and a new --out directory.
Neither the original run nor any measured request/result is modified.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from backend.benchmark_suite import cli
from backend.benchmark_suite.contract import canonical, read, sha, write
from backend.benchmark_suite.physics import physics_sources
from backend.benchmark_suite.record import build_record
from backend.benchmark_suite.references import load_bundle, load_suite, reference_provenance, require_reviewed_bundle
from backend.benchmark_suite.report import build

ROOT = Path(__file__).resolve().parents[1]


def derive(native, *, suite, bundle, output, source, reuse_reviewed_reference=False):
    spec = load_suite(suite)
    original = read(native / "run_manifest.json")
    identity = original["identity"]
    if original["status"] != "COMPLETE" or original.get("smoke") or identity.get("dirty") is not False:
        raise ValueError("Need a complete, clean, full-grid native collection")
    if original["selection"]["spec_sha256"] != sha(suite) or identity["protocol_version"] != spec["protocol_version"]:
        raise ValueError("Native collection did not measure this exact registered suite")
    physical = {name: sha(ROOT/name) for name in physics_sources(ROOT)}
    if any(identity["source_files"].get(name) != digest for name, digest in physical.items()):
        raise ValueError("Candidate physics differ from the measured collection")
    selected = [(case["id"], job["stage"]) for case in spec["cases"] for job in case["jobs"]]
    if [(job["case_id"], job["stage"]) for job in original["jobs"]] != selected:
        raise ValueError("Need exactly the complete registered job selection")
    configs, protocols, golden = cli.inputs(spec, spec["cases"])
    hashes = {}
    for job in original["jobs"]:
        request = read(native/job["request"])
        if (sha(native/job["request"]) != job["request_sha256"] or request["identity"] != identity
                or canonical(request["config"]) != canonical(configs[job["case_id"], job["stage"]])):
            raise ValueError("A measured request changed or differs from the registered physical input")
        hashes[job["request"]] = sha(native/job["request"])
        if job["status"] == "COMPLETE":
            cli.verify_artifact(native, job, identity)
            hashes[job["result"]] = sha(native/job["result"])
        elif job["status"] != "UNSUPPORTED" or job["case_id"] != "ornl_prius_2004_ipm":
            raise ValueError("A supported candidate job did not complete")
    manifest, references, digest = load_bundle(bundle, spec)
    review = require_reviewed_bundle(bundle, manifest, spec)
    if manifest["public_candidate_commit"] != identity["commit"] and not reuse_reviewed_reference:
        raise ValueError("Reference request registration names a different candidate")
    derived = copy.deepcopy(original)
    derived.pop("reference_commit", None)
    derived.update(reference_mode="FROZEN_REFERENCE", **reference_provenance(manifest))
    derived["selection"].update(no_reference=False, bundle_sha256=digest)
    reuse = None
    if manifest["public_candidate_commit"] != identity["commit"]:
        from backend.benchmark_suite.record import identity_platform_key
        from tools.qualification_carry import POLICY, policy_report, reference_compatibility

        policy = read(ROOT / POLICY)
        anchor = policy_report(ROOT, policy["approved_reports"][identity_platform_key(identity)])
        frame = {"run": derived, "rows": [
            {"id": case["id"], "configurations": {j["stage"]: configs[case["id"], j["stage"]] for j in case["jobs"]}}
            for case in spec["cases"]]}
        reuse = reference_compatibility(frame, anchor, suite, bundle)
    derived["comparison"] = {
        "schema": "coilem.reviewed_candidate_reference_join/v1", "native_manifest_sha256": sha(native/"run_manifest.json"),
        "native_artifact_sha256": hashes, "reference_manifest_sha256": sha(bundle/"manifest.json"),
        "reference_review_sha256": manifest["review"]["sha256"], "reference_review_decision": review["decision"],
        "measured_candidate": identity["commit"],
        **({"reference_adapter_commit": manifest["reference_commit"]} if "reference_commit" in manifest else reference_provenance(manifest)),
        "field_solves_executed": 0, "native_manifest_mutated": False,
        "reference_reuse": reuse,
    }
    rows = cli.evaluate(native, derived, spec["cases"], configs, protocols, golden, references, cli.hardware_targets(spec["cases"]))
    if any(row["status"] in {"ERROR", "INCOMPLETE", "NOT_COMPARED"} for row in rows):
        raise ValueError("Candidate comparison is incomplete; preserve and inspect the original collection")
    output.mkdir(parents=True, exist_ok=False)
    write(output/"comparison_manifest.json", derived)
    outcome = build(output, derived, rows, pdf=False)
    summary = read(output/"report/benchmark_summary.json")
    note = (f"Graded from the recorded measurements (harness {identity['harness_version']}, protocol {identity['protocol_version']}) "
            f"against suite {spec['protocol_version']} and the frozen reference bundle, with zero field solves.")
    record = build_record(summary, source=source, physics_files=physical, evaluation_note=note)
    write(output/"platform-record.json", record)
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--reference-bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--record-source", required=True, help="Published repository folder containing benchmark_summary.json")
    parser.add_argument("--reuse-reviewed-reference", action="store_true", help="Verify reuse against the owner-approved reference contract")
    args = parser.parse_args()
    print(derive(args.native, suite=args.suite, bundle=args.reference_bundle, output=args.out, source=args.record_source,
                 reuse_reviewed_reference=args.reuse_reviewed_reference))


if __name__ == "__main__":
    main()
