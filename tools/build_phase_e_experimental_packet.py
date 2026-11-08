"""Project retained public cogging evidence into an explicitly experimental bundle.

    python -m tools.build_phase_e_experimental_packet --write
    python -m tools.build_phase_e_experimental_packet --check

Neither operation runs a field solver or qualifies cogging.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import math
import re
from collections import Counter

from backend.benchmark_suite.cogging_metrics import evaluate_cogging
from backend.benchmark_suite.contract import ROOT, canonical, read, sha
from backend.cogging import cogging_record

BUNDLE = "benchmarks/reference-baselines/phase-e-experimental-20261108"
PACKET = "benchmarks/windows-phase-e-retained-20261108"
SOURCE = "benchmarks/windows-v051-20261105-a4f9f4d"
MEASURED = "a4f9f4dccf2ba3aad530e7bd1604ece8eeaca86f"
STATUS = "EXPERIMENTAL_REFERENCE"


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def byte_sha(value):
    return hashlib.sha256(value).hexdigest()


def public_errors(text):
    errors = []
    if re.search(r"(?:^|[\s\"'<>=])[A-Za-z]:[\\/]|\\\\|/(?:Users|home|bench)/", text):
        errors.append("local machine path")
    if any(token in text for token in ("adapter_commit", "producer_sha256", "reference_commit", "private_python_sources")):
        errors.append("private producer identity field")
    if any(value != MEASURED for value in re.findall(r"\b[0-9a-f]{40}\b", text)):
        errors.append("unexpected Git-shaped identity")
    return errors


def generated_files(root=ROOT):
    spec = read(root / "benchmarks/abcd-v1.7/benchmark_spec.json")
    saved = read(root / SOURCE / "results.json")
    waves = read(root / SOURCE / "waveforms.json")
    provenance = read(root / SOURCE / "provenance.json")
    if saved["measured_commit"] != MEASURED or waves["measured_commit"] != MEASURED:
        raise ValueError("Retained native identity changed")
    retained = saved["cogging"]
    source_rows = {row["case_id"]: row for row in retained["cases"]}
    source_waves = {row["case_id"]: row for row in waves["cogging"]}
    expected = {case["id"] for case in spec["cases"]}
    if len(expected) != 12 or set(source_rows) != expected or set(source_waves) != expected:
        raise ValueError("Retained Phase E cases do not match the unchanged twelve-case suite")
    files = {}
    dataset = {"schema": "coilem.phase_e_selected_waveforms/v1", "protocol_version": "1.7.0",
               "convention": spec["convention"], "normalized": True, "material_contract": spec["material_contract"], "cases": {}}
    source_evidence = {
        "schema": "coilem.phase_e_retained_source_evidence/v1", "status": STATUS,
        "original_gates_or_tolerances_changed": False,
        "selection_counts": {"baseline": 9, "half_airgap_mesh": 3},
        "source_files": [{"file": SOURCE + "/" + name, "sha256": sha(root / SOURCE / name)}
                         for name in ("waveforms.json", "results.json", "provenance.json")],
        "description": ("Retained public FEMM cogging waveforms, including the previously selected corrected half-gap records; "
                        "no accepted reference review or new native collection is implied."),
    }
    source_bytes = encoded(source_evidence)
    cohorts = {"selected_cogging_reference": {"evidence_sha256": byte_sha(source_bytes),
               "description": ("Mixed retained selection: nine baseline and three distributed half-airgap-mesh reference records. "
                               "This is an experimental dataset identity.")}}
    reference_results, native_results, historical = {}, {}, {}
    selection_counts = Counter()
    for case in spec["cases"]:
        cid = case["id"]
        config = read(root / case["jobs"][0]["fixture"])
        if canonical(config) != case["jobs"][0]["input_sha256"]:
            raise ValueError("Registered Phase E input changed")
        row, wave = source_rows[cid], source_waves[cid]
        selection = row["reference_selection"]
        if selection not in {"baseline", "half_airgap_mesh"}:
            raise ValueError("Unknown retained reference selection")
        selection_counts[selection] += 1
        reference_wave = {key: copy.deepcopy(wave["femm_selected"][key]) for key in ("electrical_angle_deg", "torque_Nm")}
        native_wave = {key: copy.deepcopy(wave["native"][key]) for key in ("electrical_angle_deg", "torque_Nm")}
        measured = next(item for item in provenance["cogging_measurements"]
                        if item["case_id"] == cid and item["mesh"] == ("half-gap" if selection == "half_airgap_mesh" else "normal"))
        method = measured["method"]
        if measured["positions"] != 25 or len(method["mesh_element_count"]) != 25:
            raise ValueError("Retained FEMM endpoint provenance is incomplete")
        summary = cogging_record(reference_wave["electrical_angle_deg"], reference_wave["torque_Nm"],
                                  slot_count=config["stator"]["slot_count"], pole_count=config["rotor"]["pole_count"],
                                  method="reference", independent_endpoints=True)
        if summary is None:
            raise ValueError("Retained reference is not a complete cogging period")
        reference_results[cid] = {
            "cogging_torque_waveform": reference_wave, "summary": {"cogging": summary.model_dump(mode="json")},
            "solve_metadata": {"femm_version": "4.2", "torque_method": "weighted_stress", "torque_body": "rotor",
                               "reference_selection": selection, "independent_endpoints": True,
                               "precision": method["precision"], "min_angle_deg": method["min_angle_deg"],
                               "airgap_mesh_size_mm": method["airgap_mesh_size_mm"],
                               "mesh_element_count": method["mesh_element_count"],
                               "mesh_element_counts_per_position": method["mesh_element_count"]},
        }
        candidate_summary = copy.deepcopy(row["selected_reference_evaluation"]["cogging"]["candidate"])
        native_results[cid] = {
            "cogging_torque_waveform": native_wave, "summary": {"cogging": candidate_summary},
            "solve_metadata": {"solver_name": "magneto2d-retained-public-projection", "mesh_source": "native",
                               "torque_method": "weighted_stress", "independent_endpoints": False},
        }
        dataset["cases"][cid] = {"input_sha256": case["jobs"][0]["input_sha256"],
                                 "reference_selection": selection, "cogging_torque_waveform": reference_wave}
        historical[cid] = row
    if selection_counts != {"baseline": 9, "half_airgap_mesh": 3}:
        raise ValueError("Retained mixed reference selection changed")
    dataset_bytes = encoded(dataset)
    reference_id = "sha256:" + byte_sha(dataset_bytes)
    records, checks, comparisons = {}, {}, []
    for case in spec["cases"]:
        cid, result = case["id"], reference_results[case["id"]]
        config = read(root / case["jobs"][0]["fixture"])
        reference = {"schema": "coilem.femm_reference/v2", "case_id": cid, "phase": "E",
                     "input_sha256": case["jobs"][0]["input_sha256"], "convention": spec["convention"], "normalized": True,
                     "reference_id": reference_id, "source_cohort": "selected_cogging_reference",
                     "public_candidate_commit": MEASURED, "validation_status": STATUS, "result": result}
        relative = cid + ".json"
        record_bytes = encoded(reference)
        files[BUNDLE + "/" + relative] = record_bytes
        records[cid] = {"file": relative, "sha256": byte_sha(record_bytes), "input_sha256": reference["input_sha256"],
                        "source_cohort": "selected_cogging_reference"}
        summary = result["summary"]["cogging"]
        floor = case["cogging_floor_Nm"]
        checks[cid] = {"input_sha256": reference["input_sha256"], "record_sha256": byte_sha(record_bytes),
                       "reference_selection": result["solve_metadata"]["reference_selection"],
                       "endpoint_mismatch_Nm": summary["endpoint_mismatch_Nm"], "mean_Nm": summary["mean_Nm"],
                       "registered_floor_Nm": floor,
                       "reference_cogging_period": "PASS" if summary["endpoint_mismatch_Nm"] <= floor else "FAIL",
                       "reference_cogging_mean": "PASS" if abs(summary["mean_Nm"]) <= floor else "FAIL"}
        evaluation = evaluate_cogging(native_results[cid], result, config, floor)
        old = historical[cid]["selected_reference_evaluation"]
        if evaluation["status"] != old["status"] or evaluation["gates"] != old["gates"]:
            raise ValueError("Retained cogging grade changed: " + cid)
        for key in ("peak_to_peak_error_Nm", "peak_to_peak_error_pct", "first_harmonic_error_Nm", "first_harmonic_error_pct"):
            if not math.isclose(evaluation["cogging"][key], old["cogging"][key], rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Retained cogging metric changed: " + cid + ":" + key)
        job = next(job for job in provenance["native_jobs"]["cogging"] if job["case_id"] == cid)
        native_projection = {"schema": "coilem.native_measurement_projection/v1", "case_id": cid, "phase": "E",
                             "measured_commit": MEASURED, "input_sha256": reference["input_sha256"],
                             "source_artifact_sha256": job["result_sha256"], "result": native_results[cid]}
        files[PACKET + "/native/" + relative] = encoded(native_projection)
        comparisons.append({"case_id": cid, "status": evaluation["status"], "experimental": True,
                            "reference_selection": result["solve_metadata"]["reference_selection"], "evaluation": evaluation,
                            "historical_baseline_status": historical[cid]["baseline_evaluation"]["status"],
                            "historical_baseline_gates": historical[cid]["baseline_evaluation"]["gates"]})
    self_checks = {"schema": "coilem.phase_e_reference_self_checks/v1", "status": STATUS,
                   "original_gates_or_tolerances_changed": False,
                   "selection_policy": "RETAINED_CORRECTED_HALF_MESH_SELECTION", "cases": checks}
    checks_bytes = encoded(self_checks)
    manifest = {"schema": "coilem.frozen_reference_bundle/v2", "protocol_version": "1.7.0",
                "validation_status": STATUS, "reference_id": reference_id, "reference_identity_kind": "DATASET_SHA256",
                "suite_sha256": sha(root / "benchmarks/abcd-v1.7/benchmark_spec.json"),
                "material_contract": spec["material_contract"], "convention": spec["convention"], "normalized": True,
                "public_candidate_commit": MEASURED, "source_cohorts": cohorts, "records": records,
                "dataset": {"file": "selected-waveforms.json", "sha256": byte_sha(dataset_bytes)},
                "source_evidence": {"file": "source-evidence.json", "sha256": byte_sha(source_bytes)},
                "self_checks": {"file": "self-checks.json", "sha256": byte_sha(checks_bytes)}}
    counts = dict(Counter(row["status"] for row in comparisons))
    if counts != {"PASS": 10, "YELLOW": 2}:
        raise ValueError("Retained Phase E outcomes changed")
    comparison = {"schema": "coilem.experimental_cogging_comparison/v1", "status": "EXPERIMENTAL",
                  "native_measured_commit": MEASURED, "new_v055_native_collection": False,
                  "reference_id": reference_id, "counts": counts, "rows": comparisons,
                  "field_solves_executed": 0, "registered_gates_changed": False,
                  "qualification_performed": False}
    files.update({BUNDLE + "/manifest.json": encoded(manifest), BUNDLE + "/selected-waveforms.json": dataset_bytes,
                  BUNDLE + "/source-evidence.json": source_bytes, BUNDLE + "/self-checks.json": checks_bytes,
                  PACKET + "/comparison.json": encoded(comparison)})
    lines = ["# Retained experimental Windows Phase E comparison", "", "**EXPERIMENTAL — cogging remains unqualified.**", "",
             "These are unchanged native measurements at `" + MEASURED + "`, regraded against their retained selected FEMM references.",
             "No new v0.5.5 native collection or field solve was performed.", "",
             "| Case | Verdict | Peak-to-peak error | First-harmonic error |", "|---|---|---:|---:|"]
    html_rows = []
    for row in comparisons:
        values = row["evaluation"]["cogging"]
        cells = [row["case_id"], row["status"], f"{values['peak_to_peak_error_pct']:.4f}%", f"{values['first_harmonic_error_pct']:.4f}%"]
        lines.append("| " + " | ".join(cells) + " |")
        html_rows.append("<tr>" + "".join("<td>" + html.escape(cell) + "</td>" for cell in cells) + "</tr>")
    lines += ["", ("Original outcomes remain 10 PASS / 2 YELLOW. Nine baseline references and three previously selected "
                   "half-gap distributed references are retained."),
              ("All twelve selected reference period/mean self-checks pass. The historical three baseline reference failures "
               "remain in comparison.json."),
              ("The fixed relative PASS/YELLOW limits are 10%/20%, with each registered absolute floor. This dataset has no "
               "accepted reference review or qualification record."),
              "", "Reference dataset: `" + reference_id + "`."]
    files[PACKET + "/comparison.md"] = ("\n".join(lines) + "\n").encode()
    document = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                "<title>Experimental Phase E retained comparison</title><style>body{font:16px/1.5 system-ui;max-width:1100px;"
                "margin:30px auto;padding:0 20px}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;"
                "text-align:left}.notice{padding:12px;background:#fff3cd}</style>"
                "<h1>Phase E — retained Windows cogging evidence</h1><p class='notice'><strong>EXPERIMENTAL.</strong> "
                "10 PASS / 2 YELLOW; cogging remains unqualified. Native measurements retain their older public source pin. "
                "No new v0.5.5 fields were run.</p>"
                "<table><tr><th>Case</th><th>Numerical verdict</th><th>Peak-to-peak error</th><th>First-harmonic error</th></tr>"
                + "".join(html_rows) + "</table><p>Fixed gates and historical reference self-check failures are retained. "
                "This is a public projection of existing evidence, with no accepted reference review or qualification claim.</p>"
                "<p><a href='comparison.json'>Machine-readable comparison</a> · <a href='comparison.md'>Markdown</a></p></html>")
    files[PACKET + "/comparison.html"] = document.encode()
    for name, data in files.items():
        problems = public_errors(data.decode())
        if problems:
            raise ValueError("Public packet privacy failure: " + name + ": " + ", ".join(problems))
    return files


def build(*, check, root=ROOT):
    files = generated_files(root)
    changed = []
    for relative, data in files.items():
        path = root / relative
        if check:
            if not path.is_file() or path.read_bytes() != data:
                changed.append(relative)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    return {"schema": "coilem.experimental_cogging_projection_check/v1", "status": "FAIL" if changed else "PASS",
            "files": len(files), "retained_counts": {"PASS": 10, "YELLOW": 2}, "field_solves_executed": 0,
            "qualification_performed": False, "changed": changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build(check=args.check)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
