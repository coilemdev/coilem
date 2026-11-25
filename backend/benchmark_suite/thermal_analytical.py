"""Run versioned analytical thermal checks, including mean-path discrepancies.

Runnable from source or an installed package with `python -m`.
No FEM, measurements, solver calibration or qualification status changes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from backend.benchmark_suite.thermal_analytical_reference import reference_for
from backend.models.thermal import ThermalLink, ThermalNetwork, ThermalSlab
from backend.resources import data_file, package_resource
from backend.thermal_network import boundary_heat_flows, cylindrical_resistance, slab_mean_resistance, solve_copper_feedback, solve_network

REGISTRATION = "benchmarks/thermal-v0.6/analytical-fixtures.json"
REGISTRATION_SHA256 = "f8db8a260f870a04d5f4c9c9687312a40ea09566d9cf6b2921f5e98e564fbd4d"
SOURCES = ("thermal_network.py", "models/thermal.py", "benchmark_suite/thermal_analytical.py",
           "benchmark_suite/thermal_analytical_reference.py")
REASON = "Analytical evidence for specified idealized problems only; physical motor temperatures remain experimental."
LEGACY_MODEL = "legacy_mean_paths_v1"
DEFAULT_MODEL = "surface_mean_v2"
CANDIDATE_MODELS = (LEGACY_MODEL, DEFAULT_MODEL)


def registration():
    raw = data_file(REGISTRATION).read_bytes()
    if hashlib.sha256(raw).hexdigest() != REGISTRATION_SHA256:
        raise ValueError("Analytical fixtures differ from the frozen registration; use a new protocol version for changes")
    return json.loads(raw)


def _network(links, heat, fixed):
    nodes = list(dict.fromkeys([*fixed, *heat, *(n for a, b, _ in links for n in (a, b))]))
    return ThermalNetwork(nodes=nodes, fixed_C=fixed, heat_W=heat,
        links=[ThermalLink(a=a, b=b, resistance_K_W=r, assumption="Registered analytical adapter; see ANALYTICAL_PROTOCOL.md")
               for a, b, r in links])


def _legacy_candidate_network(case):
    """Explicit adapters to production primitives; never read reference results."""
    p, family = case["parameters"], case["family"]
    if family in {"series", "parallel"}:
        r1, r2 = p["resistances_K_W"]
        links = [("winding", "housing", r1), ("housing", "ambient", r2)] if family == "series" else [
            ("winding", "ambient", r1), ("winding", "ambient", r2)]
        return _network(links, {"winding": p["heat_W"]}, {"ambient": p["ambient_C"]})
    if family == "two_boundaries":
        r1, r2 = p["resistances_K_W"]
        return _network([("winding", "left", r1), ("winding", "right", r2)], {"winding": p["heat_W"]},
                        {"left": p["left_C"], "right": p["right_C"]})
    if family == "disconnected":
        return _network([("winding", "ambient", 2)], {"winding": 10, "floating": 0}, {"ambient": 20})
    if family in {"slab", "split_slab"}:
        resistance = slab_mean_resistance(p["length_m"], p["k_W_mK"], p["area_m2"],
                                          two_sided=p.get("two_sided", True))
        if family == "split_slab":
            # Two equal mean-to-face branches recover the existing symmetric
            # mean resistance in parallel. This extension is a diagnostic, not
            # an exact three-terminal model or a shipped motor geometry adapter.
            return _network([("mean", "left", 2 * resistance), ("mean", "right", 2 * resistance)],
                            {"mean": p["heat_W"]}, {"left": p["left_C"], "right": p["right_C"]})
        return _network([("mean", "ambient", resistance)], {"mean": p["heat_W"]}, {"ambient": p["boundary_C"]})
    if family == "cylinder":
        resistance = cylindrical_resistance(p["inner_radius_m"], p["outer_radius_m"], p["length_m"], p["k_W_mK"])
        return _network([("inner", "ambient", resistance)], {"inner": p["heat_W"]}, {"ambient": p["boundary_C"]})
    if family == "layered":
        # Isolate the one-face source-mean chaining used for tooth/yoke paths.
        # This is an idealized 1D diagnostic, not the full motor network.
        layers, links = p["layers"], []
        for i, layer in enumerate(layers):
            r = slab_mean_resistance(layer["length_m"], layer["k_W_mK"], p["area_m2"], two_sided=False)
            if i < len(layers) - 1:
                r += p["contacts_K_W"][i]
                target = layers[i + 1]["name"]
            else:
                r += p["outer_resistance_K_W"]
                target = "ambient"
            links.append((layer["name"], target, r))
        return _network(links, {layer["name"]: layer["heat_W"] for layer in layers}, {"ambient": p["ambient_C"]})
    if family == "copper_one":
        return _network([("winding", "ambient", p["resistance_K_W"])], {"winding": p["heat_20C_W"]}, {"ambient": p["ambient_C"]})
    if family == "copper_two":
        return _network([("winding", "housing", p["active_resistance_K_W"]),
                         ("end_winding", "housing", p["end_resistance_K_W"]),
                         ("housing", "ambient", p["housing_resistance_K_W"])],
                        {"winding": p["active_heat_20C_W"], "end_winding": p["end_heat_20C_W"], "housing": p["housing_heat_W"]},
                        {"ambient": p["ambient_C"]})
    raise ValueError(f"Unknown analytical family: {family}")


def _candidate_network(case, candidate_model=DEFAULT_MODEL):
    if candidate_model not in CANDIDATE_MODELS:
        raise ValueError("Unknown analytical candidate model")
    if candidate_model == LEGACY_MODEL or case["family"] not in {"layered", "split_slab"}:
        return _legacy_candidate_network(case)
    p = case["parameters"]
    assumption = "Exact planar surface/mean slab element; analytical protocol inputs unchanged"
    if case["family"] == "split_slab":
        return ThermalNetwork(nodes=["mean", "left", "right"], links=[],
            slabs=[ThermalSlab(mean="mean", a="left", b="right", assumption=assumption,
                               resistance_K_W=p["length_m"] / (p["k_W_mK"] * p["area_m2"]))],
            heat_W={"mean": p["heat_W"]}, fixed_C={"left": p["left_C"], "right": p["right_C"]})
    nodes, links, slabs, heat = ["ambient"], [], [], {}
    left = "insulated_face"
    nodes.append(left)
    for i, layer in enumerate(p["layers"]):
        mean, right = layer["name"], f"face_{i}_right"
        nodes.extend((mean, right))
        heat[mean] = layer["heat_W"]
        slabs.append(ThermalSlab(mean=mean, a=left, b=right, assumption=assumption,
                                resistance_K_W=layer["length_m"] / (layer["k_W_mK"] * p["area_m2"])))
        if i == len(p["layers"]) - 1:
            target, resistance = "ambient", p["outer_resistance_K_W"]
        else:
            resistance = p["contacts_K_W"][i]
            target = f"face_{i + 1}_left" if resistance else right
            if resistance:
                nodes.append(target)
        if resistance:
            links.append(ThermalLink(a=right, b=target, resistance_K_W=resistance,
                                     assumption="Surface contact or outer boundary resistance"))
        left = target
    return ThermalNetwork(nodes=nodes, links=links, slabs=slabs, heat_W=heat, fixed_C={"ambient": p["ambient_C"]})


def prediction_for(case, *, candidate_model=DEFAULT_MODEL):
    network = _candidate_network(case, candidate_model)
    feedback = case["family"] in {"copper_one", "copper_two"}
    if feedback:
        nodes = ("winding",) if case["family"] == "copper_one" else ("winding", "end_winding")
        network, temperatures, _, balance, gain, _ = solve_copper_feedback(network, case["parameters"]["alpha_per_K"], nodes)
    else:
        temperatures, _, balance = solve_network(network)
    selected = ({layer["name"] for layer in case["parameters"]["layers"]} if case["family"] == "layered"
                else {"mean"} if case["family"] == "split_slab" else set(network.nodes) - set(network.fixed_C))
    values = {"T_" + node: t for node, t in temperatures.items() if node in selected}
    values["Q_balance"] = balance
    values.update({"Q_" + boundary: flow for boundary, flow in boundary_heat_flows(network, temperatures).items()})
    if feedback:
        values.update({"Q_" + node: network.heat_W[node] for node in nodes})
        values["loop_gain"] = gain
    return values


def compare(case, tolerances, candidate_model=DEFAULT_MODEL):
    reference = reference_for(case)
    result = dict(id=case["id"], family=case["family"], scope=case["scope"], parameters=case["parameters"],
                  output_status="experimental", output_status_reason=REASON, reference=reference.values,
                  reference_details=reference.details, expected_rejection=reference.rejection_contains, metrics=[])
    try:
        actual = prediction_for(case, candidate_model=candidate_model)
    except Exception as exc:
        correct_rejection = isinstance(exc, ValueError) and reference.rejection_contains and reference.rejection_contains in str(exc)
        return dict(result, status="PASS" if correct_rejection else "FAIL", prediction={},
                    observed_rejection=dict(type=type(exc).__name__, message=str(exc)),
                    status_reason="Correctly rejected the registered invalid/unstable problem." if correct_rejection
                    else "Candidate raised an unexpected exception; no temperatures accepted.")
    # Keep failure evidence serializable even if a rejected/coverage-broken
    # candidate returns non-finite values.
    result["prediction"] = {k: v if math.isfinite(v) else None for k, v in actual.items()}
    if reference.rejection_contains:
        return dict(result, status="FAIL", status_reason="Candidate returned values for a problem that must be rejected.")
    if actual.keys() != reference.values.keys():
        return dict(result, status="FAIL", status_reason="Candidate metric coverage differs from the analytical reference.")
    for name, expected in reference.values.items():
        value = actual[name]
        unit = "K" if name.startswith("T_") else "W" if name.startswith("Q_") else "1"
        floor_key = {"K": "absolute_temperature_K", "W": "absolute_heat_W", "1": "absolute_dimensionless"}[unit]
        scale = abs(expected - reference.datum_C) if unit == "K" else abs(expected)
        band = max(tolerances[floor_key], tolerances["relative"] * scale)
        finite = math.isfinite(value) and math.isfinite(expected)
        error = abs(value - expected) if finite else None
        result["metrics"].append(dict(name=name, unit="C" if unit == "K" else unit, error_unit=unit,
            reference=expected, predicted=value if math.isfinite(value) else None,
            absolute_error=error, numerical_tolerance=band,
            status="PASS" if finite and error <= band else "FAIL"))
    result["status"] = "FAIL" if any(m["status"] == "FAIL" for m in result["metrics"]) else "PASS"
    result["status_reason"] = ("Matches the independent closed-form reference within numerical tolerances." if result["status"] == "PASS"
        else "Disagrees with the independent analytical reference; retain this result without changing tolerances.")
    return result


def run_suite(case_ids=None, *, candidate_model=DEFAULT_MODEL):
    if candidate_model not in CANDIDATE_MODELS:
        raise ValueError("Unknown analytical candidate model")
    spec = registration()
    cases = spec["cases"]
    if case_ids is not None:
        ids = set(case_ids)
        if not ids or len(ids) != len(case_ids) or not ids.issubset({c["id"] for c in cases}):
            raise ValueError("Select distinct registered analytical case IDs; empty selections are not a PASS")
        cases = [case for case in cases if case["id"] in ids]
    results = [compare(case, spec["tolerances"], candidate_model) for case in cases]
    scopes = {}
    for scope in sorted({row["scope"] for row in results}):
        selected = [row for row in results if row["scope"] == scope]
        scopes[scope] = dict(status="FAIL" if any(row["status"] == "FAIL" for row in selected) else "PASS",
                             counts=dict(Counter(row["status"] for row in selected)))
    return dict(schema_version=1, protocol=spec["protocol"], candidate_model=candidate_model,
                evidence_kind=spec["evidence_kind"], claim=spec["claim"],
                output_status="experimental", output_status_reason=REASON,
                selection="full" if len(cases) == len(spec["cases"]) else "subset", registration_sha256=REGISTRATION_SHA256,
                source_sha256={name: hashlib.sha256(package_resource(*name.split("/")).read_bytes()).hexdigest() for name in SOURCES},
                runtime=dict(python=platform.python_version(), numpy=np.__version__, platform=platform.platform()),
                tolerances=spec["tolerances"], comparison_rule=spec["comparison_rule"], scopes=scopes,
                status="FAIL" if any(row["status"] == "FAIL" for row in results) else "PASS", cases=results)


def markdown_report(bundle):
    lines = ["# Analytical thermal benchmark", "", f"Protocol: `{bundle['protocol']}`. Overall: **{bundle['status']}**.",
             f"Candidate model: `{bundle.get('candidate_model', LEGACY_MODEL)}`.",
             f"Selection: {bundle['selection']}. Evidence: analytical; app outputs remain experimental.", "", bundle["claim"], "",
             *[f"- {scope}: **{row['status']}** ({', '.join(f'{count} {status}' for status, count in sorted(row['counts'].items()))})."
               for scope, row in bundle["scopes"].items()], "",
             "Solver checks and model-reduction comparisons are reported separately. A reduction FAIL measures disagreement",
             "with an idealized exact solution; it is not a measured full-motor accuracy verdict.", "",
             "| Case | Scope | Result | Largest temperature error (K) | Largest heat error (W) |",
             "| --- | --- | --- | ---: | ---: |"]
    for case in bundle["cases"]:
        errors = {unit: max((m["absolute_error"] for m in case["metrics"] if m["error_unit"] == unit and m["absolute_error"] is not None),
                            default=None) for unit in ("K", "W")}
        shown = {u: f"{e:.8g}" if e is not None else "--" for u, e in errors.items()}
        lines.append(f"| {case['id']} | {case['scope']} | {case['status']} | {shown['K']} | {shown['W']} |")
    lines += ["", "## Cases needing attention", ""]
    failed = [case for case in bundle["cases"] if case["status"] == "FAIL"]
    if not failed:
        lines.append("None in this selection.")
    for case in failed:
        lines += [f"- **{case['id']}**: {case['status_reason']}"]
        for metric in case["metrics"]:
            if metric["status"] == "FAIL":
                lines.append(f"  - {metric['name']}: predicted {metric['predicted']}, reference {metric['reference']} {metric['unit']}; "
                             f"absolute error {metric['absolute_error']} {metric['error_unit']}.")
    lines += ["", "## Reproduction", "", f"Registration SHA-256: `{bundle['registration_sha256']}`.", "",
              "The companion JSON preserves inputs, reference details, all comparisons, rejection reasons,",
              "runtime versions and candidate/reference source hashes. The CSV preserves every numerical comparison.", "",
              "No convection coefficient, contact property, real motor temperature, hotspot, rotor loss or continuous rating is qualified."]
    return "\n".join(lines) + "\n"


def write_reports(bundle, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "results.json").write_text(json.dumps(bundle, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (destination / "summary.md").write_text(markdown_report(bundle), encoding="utf-8")
    with (destination / "metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["case", "scope", "status", "metric", "unit", "reference", "predicted", "absolute_error", "error_unit",
                         "numerical_tolerance", "reason", "protocol", "registration_sha256", "source_identity_sha256",
                         "evidence_kind", "output_status", "output_status_reason", "candidate_model"])
        source_identity = hashlib.sha256(json.dumps(bundle["source_sha256"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        provenance = [bundle["protocol"], bundle["registration_sha256"], source_identity,
                      bundle["evidence_kind"], bundle["output_status"], bundle["output_status_reason"],
                      bundle.get("candidate_model", LEGACY_MODEL)]
        for case in bundle["cases"]:
            for metric in case["metrics"]:
                writer.writerow([case["id"], case["scope"], metric["status"], *[metric[key] for key in
                    ("name", "unit", "reference", "predicted", "absolute_error", "error_unit", "numerical_tolerance")],
                    case["status_reason"], *provenance])
            if not case["metrics"]:
                writer.writerow([case["id"], case["scope"], case["status"], "outcome", "", "", "", "", "", "",
                                 case["status_reason"] + " " + json.dumps(case.get("observed_rejection")), *provenance])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=[case["id"] for case in registration()["cases"]], help="Repeat for a subset")
    parser.add_argument("--out-dir", type=Path, help="New directory for JSON, CSV and Markdown; existing evidence is never overwritten")
    parser.add_argument("--candidate-model", choices=CANDIDATE_MODELS, default=DEFAULT_MODEL,
                        help="Versioned candidate; original failed evidence is retained separately")
    args = parser.parse_args(argv)
    if args.out_dir is not None and args.out_dir.exists():
        parser.error("Output directory already exists; choose a new path to preserve evidence")
    result = run_suite(args.case, candidate_model=args.candidate_model)
    if args.out_dir is not None:
        write_reports(result, args.out_dir)
    sys.stdout.write(markdown_report(result))
    return int(result["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
