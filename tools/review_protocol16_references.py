"""Audit the retained protocol 1.6 reference collections without executing fields.

This is a code/data review aid, not an independent laboratory certification.
The original bundle and raw collections are read-only. A review does not qualify
V-shape accuracy, inductances, losses, maps or hardware performance.
"""
from __future__ import annotations

import argparse
import math
import re
from collections import Counter
from pathlib import Path

from backend.benchmark_suite.contract import canonical, read, sha, write
from backend.benchmark_suite.dq_metrics import reference_dq
from backend.benchmark_suite.references import load_bundle, load_suite
from backend.winding_utils import flux_linkage_slot_side_turn_factor


def require(condition, message):
    if not condition:
        raise ValueError(message)


def numeric_payload(value):
    """Compare every numerical field while allowing publication path redaction."""
    if isinstance(value, dict):
        return {key: numeric_payload(item) for key, item in value.items() if not isinstance(item, str)}
    if isinstance(value, list):
        return [numeric_payload(item) for item in value]
    if isinstance(value, float):
        require(math.isfinite(value), "nonfinite reference measurement")
    return value


def legacy_signature(result):
    if "summary" not in result:
        keys = ("solver_name", "mesh_element_count", "mesh_density", "mesh_source", "torque_method",
                "loaded_cycle_complete", "electrical_angle_deg", "torque_Nm", "phase_current_waveform")
        return {key: result.get(key) for key in keys}
    keys = ("avg_torque_Nm", "back_emf_fundamental_V", "lambda_pm_Wb",
            "peak_flux_density_teeth_T", "peak_flux_density_yoke_T")
    return {"summary": {key: result["summary"].get(key) for key in keys},
            "torque": result["torque_waveform"], "emf": result["back_emf_waveform"],
            "mesh": result["solve_metadata"]["mesh_element_count"]}


def audit_material_model(text, *, depth_mm, remanence_T, permeability, steel_points):
    """Check the actual saved FEMM problem, not only producer metadata."""
    def value(pattern, body=text):
        match = re.search(pattern + r"\s*=\s*([^\r\n]+)", body)
        require(match is not None, "saved model property is missing")
        return match[1].strip().strip('"')

    require(value(r"\[LengthUnits\]") == "millimeters" and value(r"\[ProblemType\]") == "planar", "wrong model units/type")
    require(float(value(r"\[Depth\]")) == depth_mm and float(value(r"\[Frequency\]")) == 0., "wrong model depth/frequency")
    require(float(value(r"\[Precision\]")) == 1e-8 and float(value(r"\[MinAngle\]")) == 30., "wrong model precision/angle")
    magnets, steels = 0, 0
    for block in re.findall(r"<BeginBlock>(.*?)<EndBlock>", text, re.S):
        name = value(r"<BlockName>", block)
        hc = float(value(r"<H_c>", block))
        if hc != 0.:
            mx, my = float(value(r"<Mu_x>", block)), float(value(r"<Mu_y>", block))
            require(mx == my == permeability, "wrong magnet permeability")
            require(math.isclose(hc*4e-7*math.pi*mx, remanence_T, rel_tol=1e-12, abs_tol=1e-12), "wrong saved magnet Br")
            magnets += 1
        if name.startswith("coilEM_M350_50A_"):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            index = next(i for i, line in enumerate(lines) if line.startswith("<BHPoints>"))
            count = int(lines[index].split("=")[1])
            points = [tuple(map(float, line.split())) for line in lines[index+1:index+1+count]]
            require(len(points) == len(steel_points) and all(len(point) == 2 for point in points), "wrong saved steel curve length")
            require(all(math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-10)
                        for point, expected in zip(points, steel_points) for a, b in zip(point, expected)), "wrong saved steel curve")
            steels += 1
    require(magnets > 0 and steels == 1, "missing saved magnet/steel materials")
    return {"magnet_materials": magnets, "steel_points": len(steel_points)}


def audit_sources(data, circuit):
    cfg = data["reference_config"]
    paths = max(1, cfg["winding"]["parallel_paths"])
    source_errors = []
    rows_checked = 0
    for frame in data["source_extraction_evidence"]:
        for row in frame["rows"]:
            area = row["slot_area_m2"]
            actual = row["integrated_amp_turns_a"]
            ideal = row["turns_per_coil"] * row["turn_fraction"] * row["phase_current_a"] / paths
            require(area > 0 and all(map(math.isfinite, (area, actual, ideal))), "invalid source integral")
            require(math.isclose(actual / area, row["effective_current_density_a_per_m2"], rel_tol=1e-12, abs_tol=1e-6),
                    "current density/integral mismatch")
            if circuit:
                require(abs(actual-ideal) <= max(1e-6, abs(ideal)*1e-6), "circuit ampere-turns do not match the request")
            if abs(ideal) > 1e-3:
                source_errors.append(abs(actual-ideal) / abs(ideal)*100)
            rows_checked += 1
    require(rows_checked > 0, "missing source extraction evidence")
    flux_frames = data["flux_extraction_evidence"]
    require(flux_frames, "missing flux extraction evidence")
    factor = flux_linkage_slot_side_turn_factor(cfg["winding"]["type"], cfg["winding"]["layers"], paths)
    for frame in flux_frames:
        if circuit:
            expected = [float(props[2])/paths for props in frame["circuit_properties"]]
            require(len(expected) == 3 and expected == frame["terminal_flux_Wb"], "terminal circuit flux normalization mismatch")
        else:
            balance = Counter()
            for row in frame["rows"]:
                sign = 1 if row["direction"] == "in" else -1
                balance[row["phase"]] += sign*row["turn_fraction"]
                expected = sign*row["turn_fraction"]*factor*cfg["winding"]["turns_per_coil"]*cfg["stator"]["stack_length_mm"]*1e-3
                expected *= row["az_effective_wb_per_m"]
                require(math.isclose(expected, row["flux_linkage_contribution_wb"], rel_tol=1e-12, abs_tol=1e-14),
                        "slot-flux reduction mismatch")
            require(all(abs(value) < 1e-12 for value in balance.values()), "unbalanced phase turn credit makes gauge subtraction unsafe")
    return {"source_rows_checked": rows_checked, "flux_frames_checked": len(flux_frames),
            "parallel_paths": paths, "method": "explicit_series_circuits" if circuit else "retained_v3_density_and_slot_flux",
            "max_ideal_NI_deviation_pct": max(source_errors, default=0.)}


def review(*, suite, bundle, runs, legacy_measurements):
    spec = load_suite(suite)
    manifest, references, bundle_sha = load_bundle(bundle, spec)
    required = {case["id"]: case for case in spec["cases"] if case["id"] != "ornl_prius_2004_ipm"}
    require(spec["protocol_version"] == "1.6.0" and set(references) == set(required), "need all 46 protocol 1.6 references")
    rows, collections = {}, []
    for run in runs:
        registration = read(run / "run_manifest.json")
        require(registration["status"] == "COMPLETE", "reference collection is incomplete")
        collections.append({"manifest_sha256": sha(run / "run_manifest.json"), "identity_sha256": canonical(registration["identity"])})
        for job in registration["jobs"]:
            cid = job["case_id"]
            require(cid in required and cid not in rows and job["status"] == "COMPLETE", "unexpected, duplicated or incomplete reference job")
            require(sha(run/job["request"]) == job["request_sha256"] and sha(run/job["result"]) == job["result_sha256"], "raw artifact hash mismatch")
            envelope = read(run/job["result"])
            require(envelope["status"] == "COMPLETE" and envelope["identity_before"] == envelope["identity_after"] == registration["identity"],
                    "reference execution identity changed")
            data = envelope["measurement"]
            require(data["identity_before"] == data["identity_after"], "physical producer identity changed")
            require(data["reference_commit"] == manifest["reference_commit"] and data["input_sha256"] == required[cid]["jobs"][0]["input_sha256"],
                    "wrong producer or physical request")
            require(numeric_payload(data["result"]) == numeric_payload(references[cid]), "published numerical fields differ from the raw collection")
            case = required[cid]
            cfg = read(suite.parents[2]/case["jobs"][0]["fixture"])
            expected_br = case.get("magnet_remanence_T", spec["material_contract"]["magnets"][cfg["materials"]["magnet_grade"]]["Br_T"])
            material = data["material_settings"]
            expected_mu = spec["material_contract"]["magnets"][cfg["materials"]["magnet_grade"]]["mu_r"]
            require(material["Br_T"] == expected_br and material["mu_r"] == expected_mu,
                    "magnet contract mismatch")
            require(material["precision"] == 1e-8 and material["minimum_angle_deg"] == 30, "normal reference mesh/precision contract changed")
            circuit = bool(case.get("dq_reference")) or cid == "spm_8p12s_example_shoed"
            row = {"case_id": cid, "raw_result_sha256": job["result_sha256"], "material_settings": material,
                   **audit_sources(data, circuit)}
            old = legacy_measurements/cid/"measurement.json"
            if old.is_file():
                require(legacy_signature(read(old)["result"]) == legacy_signature(data["result"]), "legacy reference reproduction differs")
                row.update(legacy_exact=True, legacy_measurement_sha256=sha(old))
            if case.get("dq_reference"):
                dq = reference_dq(references[cid], cfg)
                require(dq is not None, "missing circuit waveforms")
                error = abs(dq["torque_agreement_pct"]-100)
                require(error <= 2., "registered reference d/q self-check fails")
                row["reference_dq_torque_error_pct"] = error
            rows[cid] = row
    require(set(rows) == set(required), "missing supported references")
    require(sum(row.get("legacy_exact", False) for row in rows.values()) == 29, "need exact reproduction of all 29 legacy cases")
    require(len({c["identity_sha256"] for c in collections}) == 1, "multiple producer execution identities")
    return {"schema": "coilem.protocol16_reference_review/v1", "decision": "ACCEPTED_FOR_REGISTERED_PARITY",
            "reviewer": {"name": "Codex assistant", "method": "code and raw-data review requested by the owner",
                         "independence": ("Same assistant that prepared the earlier evidence; "
                                          "no independent human or laboratory approval is implied.")},
            "parent_manifest_sha256": sha(bundle/"manifest.json"), "parent_bundle_sha256": bundle_sha,
            "reference_commit": manifest["reference_commit"], "suite_sha256": sha(suite),
            "accepted_scope": ("Data-only references for the registered protocol 1.6 torque/EMF comparisons, "
                               "12 loaded flux-vector points and four declared-Br temperature cases."),
            "limits": ["Legacy density sources preserve their measured area/NI approximation; no fitted correction is applied.",
                       "V-shape accuracy remains experimental and its mixed version change is retained.",
                       "A single refined control does not establish spatial convergence.",
                       "No qualification of inductances, maps, losses, thermal behavior, catalogue coefficients or hardware performance."],
            "primary_documentation": [{"url": "https://www.femm.info/Archives/doc/manual.pdf",
                "sections": ["2.2.7 circuit properties and signed turns", "3.3.4 circuit construction", "3.4.1 block integrals and circuit flux"]}],
            "source_normalization": ("Series circuits use signed block turns and branch current I/a. "
                                     "Circuit linkage is divided by a for terminal linkage. "
                                     "This is a declared balanced-parallel-path model, not fitted scaling."),
            "collections": collections, "supported_records": len(rows),
            "legacy_exact_records": 29, "circuit_records": sum(row["method"] == "explicit_series_circuits" for row in rows.values()),
            "max_legacy_ideal_NI_deviation_pct": max(
                row["max_ideal_NI_deviation_pct"] for row in rows.values() if row["method"].startswith("retained")),
            "max_circuit_ideal_NI_deviation_pct": max(
                row["max_ideal_NI_deviation_pct"] for row in rows.values() if row["method"] == "explicit_series_circuits"),
            "max_reference_dq_torque_error_pct": max(row.get("reference_dq_torque_error_pct", 0.) for row in rows.values()),
            "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--legacy-measurements", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = review(suite=args.suite.resolve(), bundle=args.bundle, runs=args.run, legacy_measurements=args.legacy_measurements)
    require(not args.out.exists(), "write a new review artifact; never overwrite a prior review")
    write(args.out, result)
    print(f"{result['decision']}: {result['supported_records']} records, {result['legacy_exact_records']} exact legacy reproductions")


if __name__ == "__main__":
    main()
