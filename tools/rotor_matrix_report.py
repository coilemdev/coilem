"""Audited 1500/3000 rpm postprocessing of immutable rotor field histories."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from tools.rotor_loss_pilot_report import analyse as femm_analyse
from tools.rotor_matched_report import audit_sources, compare_results
from tools.rotor_native_pilot import sha, write
from tools.rotor_native_report import analyse as native_analyse

COMPONENTS = ("hysteresis_W", "lamination_eddy_W", "total_W")


def speed_scaling(low, high):
    expected = {"hysteresis_W": 2*low["hysteresis_W"],
        "lamination_eddy_W": 4*low["lamination_eddy_W"]}
    expected["total_W"] = sum(expected.values())
    errors = {key: high[key]-expected[key] for key in COMPONENTS}
    return {"expected_3000rpm_W": expected, "difference_W": errors,
        "pass": all(math.isfinite(high[key]) and abs(errors[key]) <= max(1e-12, 1e-10*abs(expected[key]))
                    for key in COMPONENTS)}


def native_reports(directory, output, source_root, *, seal=False):
    protocol_sha = sha(directory / "protocol.json")
    reports = {}
    output.mkdir(parents=True, exist_ok=True)
    for speed in (3000, 1500):
        path = output / f"native-rpm{speed}.json"
        if path.exists():
            report = json.loads(path.read_text())
            if report["protocol_sha256"] != protocol_sha or report["speed_rpm"] != speed:
                raise ValueError("Cached native report belongs to another field history or evaluation speed")
        else:
            report = native_analyse(directory, source_root=source_root, evaluation_speed_rpm=speed)
            write(path, report)
        if not report["native_history_numerical_gates_pass"]:
            raise ValueError(f"Native input/closure/angular/loss-math gate failed at {speed} rpm")
        reports[speed] = report
        if seal and speed == 3000:
            target = directory / "analysis.json"
            if target.exists():
                if json.loads(target.read_text()) != report:
                    raise ValueError("Existing bound native analysis differs; use a new output location")
            else:
                write(target, report)
    loss = {speed: next(row["production_sampling"] for row in report["results"] if row["positions"] == 384)
            for speed, report in reports.items()}
    scaling = speed_scaling(loss[1500], loss[3000])
    write(output / "native-speed-scaling.json", scaling)
    if not scaling["pass"]:
        raise ValueError("Native speed-reuse check failed")
    return reports


def reference_reports(directory, native_directory, output, native_source, reference_source, stride):
    protocol = json.loads((directory / "protocol.json").read_text())
    for name, field in (("protocol.json", "native_protocol_sha256"), ("analysis.json", "native_analysis_sha256"),
                        ("native-config.json", "native_config_sha256")):
        if sha(native_directory / name) != protocol[field]:
            raise ValueError("Bound native input changed after reference registration")
    output.mkdir(parents=True, exist_ok=True)
    native = native_reports(native_directory, output, native_source)
    audit = audit_sources(directory, protocol, stride, source_root=reference_source)
    reports = {}
    for speed in (3000, 1500):
        reference = femm_analyse(directory, sample_stride=stride, evaluation_speed_rpm=speed,
                                 fixture_root=reference_source)
        report = compare_results(reference, protocol, native[speed])
        report.update(evaluation_speed_rpm=speed, field_history_speed_rpm=protocol["speed_rpm"],
            source_audit=audit, matrix_case_id=protocol.get("matrix_case_id", "spm-loaded-pilot"),
            full_matrix_started=True)
        write(output / f"femm-n{384//stride}-rpm{speed}.json", reference)
        write(output / f"comparison-n{384//stride}-rpm{speed}.json", report)
        print(json.dumps({"samples": 384//stride, "speed_rpm": speed, "gate": report["cross_solver_loss_gate"],
            "femm_loss_W": report["femm_loss_W"], "native_loss_W": report["native_loss_W"]}), flush=True)
        if report["cross_solver_loss_gate"] != "PASS":
            raise ValueError(f"Native/FEMM comparison failed at {speed} rpm")
        reports[speed] = report
    scaling = speed_scaling(reports[1500]["femm_loss_W"], reports[3000]["femm_loss_W"])
    write(output / f"femm-n{384//stride}-speed-scaling.json", scaling)
    if not scaling["pass"]:
        raise ValueError("Independent FEMM speed-reuse check failed")
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("native", "reference"))
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--native-source", type=Path, required=True)
    parser.add_argument("--reference-source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stride", type=int, choices=(1, 2, 4), default=1)
    args = parser.parse_args()
    if args.mode == "native":
        native_reports(args.native, args.out, args.native_source, seal=True)
        print(json.dumps({"native_gate": "PASS", "speeds_rpm": [1500, 3000]}), flush=True)
    else:
        if args.reference is None or args.reference_source is None:
            parser.error("Reference reporting needs --reference and --reference-source")
        reference_reports(args.reference, args.native, args.out, args.native_source, args.reference_source, args.stride)


if __name__ == "__main__":
    main()
