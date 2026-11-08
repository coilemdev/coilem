"""Compose immutable versioned suites without inventing one reference identity."""

from __future__ import annotations

import argparse
import copy
import math
import re

from backend.benchmark_suite.contract import CHECKOUT, DATA_ROOT, ROOT, checked_json, checked_path, now, read, run_lock, sha, write
from backend.benchmark_suite.record import check_physics, compare_run, select_record
from backend.benchmark_suite.references import load_bundle, load_suite, reference_provenance
from backend.resources import BUILD_INFO_FILE

COLLECTION_FILE = "benchmarks/public-benchmark-collection.json"
MANIFEST_FILE = "collection_manifest.json"
COLLECTION_SCHEMA = "coilem.benchmark_collection/v1"
RUN_SCHEMA = "coilem.benchmark_collection_run/v1"
PUBLIC_PHASES = tuple("ABCDEF")


def load_collection(phases=PUBLIC_PHASES, *, quick=False, path=None):
    """Validate all selected data before constructing any field requests."""
    path = path or DATA_ROOT / COLLECTION_FILE
    descriptor = read(path)
    components = descriptor.get("components") if isinstance(descriptor, dict) else None
    if (not isinstance(descriptor, dict) or descriptor.get("schema") != COLLECTION_SCHEMA or descriptor.get("phases") != list(PUBLIC_PHASES)
            or not isinstance(components, list) or len(components) != 3
            or any(not isinstance(component, dict) for component in components)):
        raise ValueError("Unsupported public benchmark collection")
    declared = [phase for component in components for phase in component.get("phases", [])]
    if declared != list(PUBLIC_PHASES) or not set(phases) <= set(PUBLIC_PHASES) or not phases:
        raise ValueError("Collection must cover each phase A-F exactly once")
    children, seen_cases, seen_components = [], set(), set()
    for component in components:
        component_id = component.get("id")
        if (not isinstance(component_id, str) or re.fullmatch(r"[a-z][a-z0-9-]*", component_id) is None
                or component_id in seen_components):
            raise ValueError("Invalid or duplicate collection component")
        seen_components.add(component_id)
        expected_experimental = component["phases"] == ["E"]
        if (type(component.get("experimental")) is not bool or component["experimental"] != expected_experimental
                or component["phases"] not in [list("ABCD"), ["E"], ["F"]]):
            raise ValueError("Phase E must retain its separate experimental scope")
        selected_phases = [phase for phase in component["phases"] if phase in phases]
        if not selected_phases:
            continue
        suite, bundle = component.get("suite") or {}, component.get("reference_bundle") or {}
        if (not isinstance(suite, dict) or set(suite) != {"file", "sha256"}
                or not isinstance(bundle, dict) or set(bundle) != {"directory", "manifest_sha256", "identity_sha256"}):
            raise ValueError("Collection suite and reference identities must be explicit")
        spec = checked_json(DATA_ROOT, suite["file"], suite["sha256"])
        suite_path = checked_path(DATA_ROOT, suite["file"])
        version = "1.6.0" if component["phases"] == list("ABCD") else "1.7.0" if expected_experimental else "1.8.0"
        if (load_suite(suite_path) != spec or spec.get("protocol_version") != version
                or {case["phase"] for case in spec["cases"]} != set(component["phases"])):
            raise ValueError("Collection component differs from its registered phases")
        bundle_path = checked_path(DATA_ROOT, bundle["directory"])
        if sha(bundle_path / "manifest.json") != bundle["manifest_sha256"]:
            raise ValueError("Collection reference manifest changed")
        reference_manifest, _, bundle_identity = load_bundle(bundle_path, spec)
        if bundle_identity != bundle["identity_sha256"]:
            raise ValueError("Collection reference dataset changed")
        all_cases = {case["id"]: case for case in spec["cases"]}
        quick_cases = component.get("quick_cases") or {}
        if (not isinstance(quick_cases, dict) or set(quick_cases) != set(component["phases"])
                or any(case_id not in all_cases or all_cases[case_id]["phase"] != phase for phase, case_id in quick_cases.items())):
            raise ValueError("Collection quick selection must contain one registered case per phase")
        cases = [case for case in spec["cases"] if case["phase"] in selected_phases
                 and (not quick or case["id"] == quick_cases[case["phase"]])]
        if not cases or seen_cases.intersection(case["id"] for case in cases):
            raise ValueError("Collection has missing or overlapping case identifiers")
        seen_cases.update(case["id"] for case in cases)
        records = {}
        entries = component.get("records")
        if not isinstance(entries, dict) or (expected_experimental and entries) or (not expected_experimental and not entries):
            raise ValueError("Experimental Phase E has no accepted platform record")
        for platform, entry in entries.items():
            if not isinstance(entry, dict) or set(entry) != {"file", "sha256"}:
                raise ValueError("Collection platform records must be hash-bound")
            record = checked_json(DATA_ROOT, entry["file"], entry["sha256"])
            if (record.get("schema") != "coilem.benchmark_record/v1" or record.get("platform") != platform
                    or record.get("suite_sha256") != suite["sha256"] or record.get("reference_bundle_sha256") != bundle_identity):
                raise ValueError("Collection platform record does not match its suite and reference")
            records[platform] = record
        record, cross_platform = select_record(records)
        selected_component = {**copy.deepcopy(component), "phases": selected_phases}
        children.append({"component": selected_component, "spec": spec, "cases": cases, "suite_path": suite_path,
                         "bundle_path": bundle_path, "reference_manifest": reference_manifest,
                         "bundle_identity": bundle_identity, "record": record, "cross_platform": cross_platform})
    return descriptor, children, sha(path)


def collection_selection(children, options, descriptor_sha256):
    return {
        "descriptor_sha256": descriptor_sha256,
        "options": options,
        "components": [{"id": child["component"]["id"], "phases": child["component"]["phases"],
                        "experimental": child["component"]["experimental"], "suite": child["component"]["suite"],
                        "reference_bundle": child["component"]["reference_bundle"],
                        "reference_provenance": reference_provenance(child["reference_manifest"]),
                        "records": child["component"]["records"],
                        "selected_record_platform": (child["record"] or {}).get("platform"),
                        "case_ids": [case["id"] for case in child["cases"]]}
                       for child in children],
    }


def _comparison_physics(record, identity):
    """Match the measured child as well as the installation reporting it."""
    physics = check_physics(record)
    differs, unverified = set(physics["differs"]), set(physics["unverified"])
    measured = identity.get("source_files") or {}
    stamp = "backend/" + BUILD_INFO_FILE
    stamp_path = ROOT / stamp
    same_package_stamp = (identity.get("installation") == "package" and measured.get(stamp)
                          and stamp_path.is_file() and measured[stamp] == sha(stamp_path))
    for name, expected in record["physics_files"].items():
        if name in measured:
            if measured[name] != expected:
                differs.add(name)
        elif not (name.startswith("solvers/") and same_package_stamp):
            unverified.add(name)
    return {**physics, "status": "DIFFERS" if differs else "UNVERIFIED" if unverified else "MATCH",
            "differs": sorted(differs), "unverified": sorted(unverified)}


def _operational_settings(manifest, min_free_gb, keep_runtime):
    saved = manifest.get("operational_settings", {"min_free_gb": 3.0, "keep_runtime": False})
    if not isinstance(saved, dict) or set(saved) != {"min_free_gb", "keep_runtime"}:
        raise ValueError("Saved collection operational settings are invalid")
    settings = {"min_free_gb": saved["min_free_gb"] if min_free_gb is None else min_free_gb,
                "keep_runtime": saved["keep_runtime"] if keep_runtime is None else keep_runtime}
    floor = settings["min_free_gb"]
    if (type(floor) not in (int, float) or not math.isfinite(floor) or floor < 0
            or type(settings["keep_runtime"]) is not bool):
        raise ValueError("Collection disk floor must be finite and nonnegative; runtime retention must be boolean")
    settings["min_free_gb"] = float(floor)
    return settings


def run_collection(output, children, options, descriptor_sha256, *, execute_child, resume=False, report_only=False,
                   min_free_gb=None, keep_runtime=None, reporter=None):
    """Delegate native work to the unchanged per-suite executor; preserve every child identity."""
    if reporter is None:
        from backend.benchmark_suite.collection_report import build_collection_report

        reporter = build_collection_report
    output = output.resolve()
    if output.is_relative_to(ROOT) or (CHECKOUT is not None and output.is_relative_to(CHECKOUT)):
        raise ValueError("Keep benchmark collection output outside the source checkout or installation")
    selection = collection_selection(children, options, descriptor_sha256)
    with run_lock(output):
        path = output / MANIFEST_FILE
        if path.is_file():
            manifest = read(path)
            if not (resume or report_only):
                raise ValueError("Existing collection; use --resume or --report-only")
            if manifest.get("schema") != RUN_SCHEMA or manifest.get("selection") != selection:
                raise ValueError("Collection inputs, references, records or original selection changed")
            states = manifest.get("components")
            if (not isinstance(states, list) or len(states) != len(children)
                    or any(not isinstance(state, dict) or state.get("id") != child["component"]["id"]
                           or state.get("directory") != "suites/" + child["component"]["id"]
                           for state, child in zip(states, children, strict=True))):
                raise ValueError("Collection child identity or output directory changed")
        else:
            if resume or report_only:
                if (output / "run_manifest.json").is_file():
                    raise ValueError("This is a legacy single-suite run. Use python -m tools.run_benchmarks with its original "
                                     "suite/reference options and --out-dir for --resume or --report-only")
                raise ValueError("Collection manifest is missing")
            manifest = {"schema": RUN_SCHEMA, "started_at": now(), "selection": selection, "status": "RUNNING",
                        "components": [{"id": child["component"]["id"], "directory": "suites/" + child["component"]["id"],
                                        "status": "PENDING"} for child in children]}
        if report_only and any(not (output / entry["directory"] / "run_manifest.json").is_file() for entry in manifest["components"]):
            raise ValueError("Report-only requires every selected child run")
        operational = _operational_settings(manifest, min_free_gb, keep_runtime)
        manifest["operational_settings"] = operational
        if not path.is_file():
            write(output / "benchmark-options.json", options)
        manifest["status"] = "REPORTING" if report_only else "RUNNING"
        manifest.pop("error", None)
        write(path, manifest)
        reports, exit_code = [], 0
        try:
            for child, state in zip(children, manifest["components"], strict=True):
                directory = output / state["directory"]
                existing = directory / "run_manifest.json"
                completed = existing.is_file() and read(existing).get("status") in {"COMPLETE", "COMPLETE_WITH_ERRORS"}
                only_report = report_only or (resume and completed)
                state.update(status="REPORTING" if only_report else "RUNNING", started_at=state.get("started_at") or now())
                write(path, manifest)
                args = argparse.Namespace(
                    phases=child["component"]["phases"], case=[case["id"] for case in child["cases"]],
                    suite=child["suite_path"], reference_bundle=child["bundle_path"], out_dir=directory,
                    list=False, resume=resume and existing.is_file() and not only_report, report_only=only_report,
                    no_reference=False, smoke=False, allow_dirty=True, pdf=False,
                    min_free_gb=operational["min_free_gb"], keep_runtime=operational["keep_runtime"],
                )
                code = execute_child(args)
                summary_path = directory / "report/benchmark_summary.json"
                summary = read(summary_path)
                expected = {"case_ids": [case["id"] for case in child["cases"]],
                            "spec_sha256": child["component"]["suite"]["sha256"],
                            "bundle_sha256": child["bundle_identity"], "smoke": False, "no_reference": False}
                rows = summary["rows"]
                phases_by_case = {case["id"]: case["phase"] for case in child["cases"]}
                if (summary["run"].get("selection") != expected or len(rows) != len(phases_by_case)
                        or {row["id"] for row in rows} != set(phases_by_case)
                        or any(row["phase"] != phases_by_case[row["id"]] for row in rows)):
                    raise ValueError("Child report changed the registered collection selection")
                physics = _comparison_physics(child["record"], summary["run"]["identity"]) if child["record"] is not None else None
                comparison = compare_run(summary["rows"], child["record"], cross_platform=child["cross_platform"], physics=physics)
                if physics and physics["status"] != "MATCH":
                    comparison["status"] = "NOT_COMPARABLE"
                comparison_path = directory / "record-comparison.json"
                write(comparison_path, comparison)
                state.update(status="COMPLETE" if code < 2 else "COMPLETE_WITH_ERRORS", completed_at=now(),
                             summary_sha256=sha(summary_path), comparison_sha256=sha(comparison_path),
                             native_manifest_sha256=sha(existing), recorded_outcome=summary["status"], exit_code=code)
                write(path, manifest)
                reports.append({"component": child["component"], "summary": summary, "comparison": comparison,
                                "relative_directory": state["directory"]})
                execution_error = code >= 2 or any(row["status"] in {"ERROR", "INCOMPLETE"} for row in summary["rows"])
                if execution_error:
                    exit_code = 2
                elif not child["component"]["experimental"] and (code or comparison["status"] != "MATCH"):
                    exit_code = max(exit_code, 1)
            manifest.update(status="COMPLETE_WITH_ERRORS" if exit_code == 2 else "COMPLETE", completed_at=now())
            write(path, manifest)
            summary, comparison = reporter(output, manifest, reports)
            return exit_code, summary, comparison
        except BaseException as exc:
            manifest.update(status="STOPPED", stopped_at=now(), error=str(exc))
            write(path, manifest)
            raise
