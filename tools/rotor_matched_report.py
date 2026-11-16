"""Compare corrected FEMM histories with separately solved native rotor fields.

Keep the loss mathematics gate separate from cross-solver field/loss agreement.
Progressive 96/192 grids are preliminary; spatial and release gates remain open.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.femm_reference import runtime
from tools.femm_reference.rotor_matched_history import model_audit, validate_excitation
from tools.rotor_loss_pilot_report import analyse as analyse_reference
from tools.rotor_native_pilot import sha, write

COMPONENTS = ("hysteresis_W", "lamination_eddy_W", "total_W")


def reference_source_audit(protocol, source_root=None):
    if protocol.get("schema") != "coilem.matched_rotor_reference/v1":
        raise ValueError("legacy FEMM histories are not matched native comparison targets")
    package = Path(runtime.__file__).parent if source_root is None else Path(source_root) / "tools/femm_reference"
    manifest_sha = sha(package / "source-manifest.json")
    if manifest_sha != protocol["reference_identity"]["source_manifest_sha256"]:
        raise ValueError("matched reference source manifest changed")
    for name, digest in protocol["reference_identity"]["implementation_sha256"].items():
        if Path(name).name != name or sha(package / name) != digest:
            raise ValueError("matched reference implementation changed")
    manifest = runtime.verify_sources(package)
    return {"source_manifest_sha256": manifest_sha, "verified_source_files": len(manifest["files"]),
            "explicit_frozen_source": source_root is not None,
            "implementation_sha256": protocol["reference_identity"]["implementation_sha256"]}


def audit_sources(directory, protocol, stride, *, source_root=None):
    source_audit = reference_source_audit(protocol, source_root)
    preparation = json.loads((directory / "preparation.json").read_text())
    for name, digest in preparation["sha256"].items():
        if Path(name).name != name or sha(directory / name) != digest:
            raise ValueError("matched reference preparation artifact changed")
    max_saved = max_solution = 0.
    for index in range(0, protocol["positions"]+1, stride):
        position = directory / f"position-{index:04d}"
        record = json.loads((position / "position.json").read_text())
        applied = json.loads((position / "applied-excitation.json").read_text())
        if record["native_excitation_sha256"] != protocol["native_excitation_sha256"][index]:
            raise ValueError("reference pose uses another native excitation source")
        phases = {}
        for entry in applied.values():
            ni = entry["ampere_turns"]*(1 if entry["direction"] == "in" else -1)
            if entry["phase"] in phases and abs(ni-phases[entry["phase"]]) > 1e-8:
                raise ValueError("reference phase ampere-turns differ among coil sides")
            phases[entry["phase"]] = ni
        angle = protocol["mechanical_angles_deg"][index]
        validate_excitation({"gate": "PASS", "native_rotor_mechanical_deg": angle, "native_gamma_deg": protocol["gamma_deg"],
                             "phase_ampere_turns": phases}, angle)
        saved = model_audit((position / "model.fem").read_text(encoding="latin-1"), angle, applied, protocol["matched_magnet"])
        if record["solution_current_error_At"] > 1e-8 or record["mesh_geometry_sha256"] != preparation["mesh_geometry_sha256"]:
            raise ValueError("reference solution excitation or mesh audit failed")
        max_saved = max(max_saved, saved)
        max_solution = max(max_solution, record["solution_current_error_At"])
    return {"reference_sources": source_audit, "saved_ampere_turn_error_max": max_saved, "solution_ampere_turn_error_max": max_solution,
            "maximum_winding_centroid_difference_mm": max(e["centroid_distance_mm"] for e in preparation["winding_geometry_audit"]),
            "maximum_magnet_centroid_difference_mm": max(e["centroid_distance_mm"] for e in preparation["magnet_geometry_audit"]),
            "mesh_geometry_sha256": preparation["mesh_geometry_sha256"], "preparation_sha256": sha(directory / "preparation.json")}


def compare_results(reference, protocol, native):
    if (protocol.get("schema") != "coilem.matched_rotor_reference/v1"
            or native["protocol_sha256"] != protocol["native_protocol_sha256"]
            or protocol["gamma_deg"] != native["native_gamma_deg"]
            or protocol["speed_rpm"] != native["speed_rpm"] or protocol["current_peak_A"] != native["current_peak_A"]):
        raise ValueError("cross-solver operating points or source identity differ")
    if (reference["material"]["coefficients"] != native["loss_material"]["coefficients"]
            or reference["material"]["stacking_factor"] != native["loss_material"]["stacking_factor"]):
        raise ValueError("cross-solver loss material assumptions differ")
    count = reference["sampling_plan"]["positions"]
    ref_row = next(r for r in reference["results"] if r["positions"] == count)
    native_row = next(r for r in native["results"] if r["positions"] == count)
    ref_loss, native_loss = ref_row["reference"], native_row["production_sampling"]
    errors = {k: native_loss[k]-ref_loss[k] for k in COMPONENTS}
    gates = {k: abs(errors[k]) <= max(0.001, 0.10*ref_loss[k]) for k in COMPONENTS}
    math_pass = all(row["reference_agreement_pass"] for row in reference["results"])
    inputs_pass = (math_pass and reference["closure_gate"] == reference["mesh_invariance_gate"] == "PASS"
                   and native["native_history_numerical_gates_pass"])
    if count == protocol["positions"]:
        inputs_pass = inputs_pass and reference["angular_gate_pass"]
    return {"schema": "coilem.matched_rotor_comparison/v1", "status": "PILOT_NOT_QUALIFIED", "positions": count,
            "progressive_subset": count < protocol["positions"], "registered_positions": protocol["positions"],
            "native_loss_W": {k: native_loss[k] for k in COMPONENTS}, "femm_loss_W": {k: ref_loss[k] for k in COMPONENTS},
            "native_minus_femm_W": errors,
            "relative_difference_of_femm": {k: errors[k]/ref_loss[k] if ref_loss[k] else None for k in COMPONENTS},
            "component_gates": gates,
            "cross_solver_loss_gate": ("PASS" if all(gates.values()) else "FAIL") if inputs_pass else "NOT_ELIGIBLE",
            "input_history_gates_pass": inputs_pass, "femm_loss_math_gate_pass": math_pass,
            "femm_angular_gate_complete": count == 384 and reference["angular_gate_pass"],
            "native_spatial_gate": "NOT_RUN", "femm_spatial_gate": "NOT_RUN", "full_matrix_started": False,
            "tolerances": {"cross_solver_relative_of_femm": 0.10, "absolute_W": 0.001},
            "material": reference["material"], "stack_m": reference["stack_m"],
            "native_mass_kg": native_loss["rotor_iron_mass_kg"], "femm_mass_kg": ref_loss["mass_kg"],
            "femm_loss_above_1kHz_share": ref_loss["share_loss_above_1kHz"],
            "native_loss_above_1kHz_share": native_row["share_loss_above_1kHz"],
            "femm_endpoint_max_T": reference["independent_endpoint_max_component_difference_T"],
            "femm_angular_convergence": reference["angular_convergence"], "reference_timing": reference["timing"],
            "native_protocol_sha256": native["protocol_sha256"], "reference_protocol_sha256": reference["protocol_sha256"]}


def markdown_report(report):
    lines = ["# #306: matched native/FEMM rotor-loss comparison", "", "Status: **PILOT_NOT_QUALIFIED**", "",
             f'{report["positions"]} full-turn samples plus independent endpoint; '
             f'{"preliminary subset" if report["progressive_subset"] else "full registered angular grid"}.', "",
             "| Component | Native W | FEMM W | Native difference | Gate |", "|---|---:|---:|---:|---|"]
    for k in COMPONENTS:
        relative = report["relative_difference_of_femm"][k]
        percent = f"{relative*100:+.3f}%" if relative is not None else "near zero"
        lines.append(f'| {k} | {report["native_loss_W"][k]:.9g} | {report["femm_loss_W"][k]:.9g} | '
                     f'{percent} | {"PASS" if report["component_gates"][k] else "FAIL"} |')
    lines += ["", f'Cross-solver loss gate: **{report["cross_solver_loss_gate"]}**. '
              "Each component uses max(10% of FEMM loss, 0.001 W).", "",
              "Excitation, magnet properties and steel B-H source are explicitly matched. "
              "Each solver integrates its own rotor cells; no mass renormalization.",
              "The reference uses fixed FEMM rotor-material queries and an independent direct DFT with the same empirical loss coefficients.",
              "Spatial convergence and the full release matrix remain unrun. This does not establish measured motor-loss accuracy.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("native", type=Path)
    parser.add_argument("--stride", type=int, choices=(1, 2, 4), default=4)
    parser.add_argument("--reference-source-root", type=Path,
                        help="Verify the frozen collector checkout that actually produced this history")
    parser.add_argument("--out", type=Path, help="Keep reanalysis separate from archived evidence")
    args = parser.parse_args()
    protocol = json.loads((args.reference / "protocol.json").read_text())
    if (sha(args.native / "protocol.json") != protocol["native_protocol_sha256"]
            or sha(args.native / "analysis.json") != protocol["native_analysis_sha256"]
            or sha(args.native / "native-config.json") != protocol["native_config_sha256"]):
        raise ValueError("native comparison inputs changed after reference collection")
    audit = audit_sources(args.reference, protocol, args.stride, source_root=args.reference_source_root)
    reference = analyse_reference(args.reference, sample_stride=args.stride)
    native_config = json.loads((args.native / "native-config.json").read_text())
    if reference["stack_m"] != native_config["stator"]["stack_length_mm"]*1e-3:
        raise ValueError("cross-solver stack lengths differ")
    output = args.out or args.reference
    output.mkdir(parents=True, exist_ok=True)
    write(output / f"analysis-stride-{args.stride}.json", reference)
    native = json.loads((args.native / "analysis.json").read_text())
    report = compare_results(reference, protocol, native)
    report["source_audit"] = audit
    report["matched_magnet"] = protocol["matched_magnet"]
    report["steel_bh_sha256"] = protocol["steel_bh_sha256"]
    report["analysis_sources_sha256"] = {name: sha(Path(__file__).parent / name) for name in
                                         ("rotor_matched_report.py", "rotor_loss_pilot_report.py", "rotor_loss_reference.py")}
    write(output / f"comparison-stride-{args.stride}.json", report)
    (output / f"comparison-stride-{args.stride}.md").write_text(markdown_report(report), encoding="utf-8")
    print(markdown_report(report))


if __name__ == "__main__":
    main()
