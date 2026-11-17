"""Windows FEMM Phase G fields, isolated from production backend imports."""

from __future__ import annotations

import argparse
import math
import os
import re
import time
import uuid
from pathlib import Path

import numpy as np

from tools.phase_g_loss.contract import (
    POSITIONS,
    ROOT,
    SUITE,
    case_by_id,
    checkpoint,
    config_for,
    enough_disk,
    phase_ampere_turns,
    protocol,
    read,
    reference_resistance,
    sha,
    write,
    write_npz,
)


def export_material(femm, output, geometry, rotor_supported, *, fixed):
    from tools.femm_reference.rotor_loss_pilot import lua_path

    regions = ("stator", "rotor") if rotor_supported else ("stator",)
    commands = ['mo_smooth("off")']
    for name, group in (("stator", 11), ("rotor", 10)):
        if name not in regions:
            continue
        path = output / (name + ".csv")
        commands += [
            f'f=openfile({lua_path(path)},"w")',
            "for i=1,mo_numelements() do",
            "n1,n2,n3,x,y,a,g=mo_getelement(i)",
            f"if g=={group} then",
            "x1,y1=mo_getnode(n1); x2,y2=mo_getnode(n2); x3,y3=mo_getnode(n3)",
            "az,bx,by=mo_getpointvalues(x,y)",
            'write(f,format("%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g\\n",x1,y1,x2,y2,x3,y3,bx,by))',
            "end end",
            "closefile(f)",
        ]
    script = output / "material-export.lua"
    script.write_text("\n".join(commands), encoding="ascii")
    femm.callfemm(f"dofile({lua_path(script)})")
    payload, new_geometry = {}, {}
    for name in regions:
        path = output / (name + ".csv")
        data = np.loadtxt(path, delimiter=",", ndmin=2)
        if data.shape[1] != 8 or not len(data) or not np.isfinite(data).all():
            raise ValueError("Empty/nonfinite FEMM material export")
        corners = data[:, :6].reshape(-1, 3, 2)
        reference = geometry[name + "_corners"] if geometry is not None else corners
        new_geometry[name + "_corners"] = reference
        if corners.shape == reference.shape and np.allclose(corners, reference, rtol=0, atol=1e-10):
            payload[name] = data[:, 6:]
        else:
            if fixed or name != "stator":
                raise ValueError("FEMM material mesh changed during fixed-mesh history")
            # Outrunner rotor loss is unavailable. Stator queries stay at the
            # zero-pose stator centroids when its ordinary reference mesh changes.
            points = reference.mean(axis=1)
            query_path = output / "stator-queries.csv"
            query = [f'f=openfile({lua_path(query_path)},"w")']
            for x, y in points:
                query += [f"az,bx,by=mo_getpointvalues({x:.17g},{y:.17g})", 'write(f,format("%.17g,%.17g\\n",bx,by))']
            query += ["closefile(f)"]
            query_script = output / "stator-query.lua"
            query_script.write_text("\n".join(query), encoding="ascii")
            femm.callfemm(f"dofile({lua_path(query_script)})")
            payload[name] = np.loadtxt(query_path, delimiter=",", ndmin=2)
            if payload[name].shape != (len(points), 2) or not np.isfinite(payload[name]).all():
                raise ValueError("Outrunner fixed-stator queries failed")
            query_path.unlink()
        path.unlink()  # fields.npz and the original .ans retain the solved data.
    write_npz(output / "fields.npz", **payload)
    return new_geometry


def mark_outer_regions(femm, ir, lowered):
    """Change diagnostic groups only; retain Phase F materials/circuits/turns."""
    from tools.femm_reference.rotor_matched_history import coil_group

    coils = []
    for region in ir.regions:
        point = lowered["labels"][region.region_id]
        if region.kind in ("StatorYoke", "StatorTooth"):
            femm.mi_selectlabel(*point)
            femm.mi_setblockprop("Steel_stator", 0, 0.25, "<None>", 0, 11, 0)
            femm.mi_clearselected()
        if region.kind == "SlotWinding":
            side = lowered["winding_specs"][region.region_id]
            group = coil_group(side["slot_index"], side["layer"])
            femm.mi_selectlabel(*point)
            femm.mi_setblockprop("Copper", 0, 0.25, side["phase"], 0, group, side["signed_turns"])
            femm.mi_clearselected()
            coils.append(
                {
                    "point": point,
                    "group": group,
                    "slot": side["slot_index"],
                    "phase": side["phase"],
                    "direction": side["direction"],
                    "turn_fraction": side["turn_fraction"],
                }
            )
    return coils


def audit_spatial_sources(coils, template):
    """Match independently lowered FEMM winding blocks to actual native cells."""
    nodes = np.asarray(template["mesh"]["nodes"])
    triangles = np.asarray(template["mesh"]["triangles"])
    ids = np.asarray(template["element_region_ids"])
    native = []
    for region in template["physics_contract"]["regions"]:
        if region["kind"] != "SlotWinding":
            continue
        corners = nodes[triangles[ids == region["id"]]]
        u, v = corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]
        weights = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
        native.append(region | {"centroid_mm": np.average(corners.mean(axis=1), weights=weights, axis=0)})
    if len(native) != len(coils):
        raise ValueError("FEMM/native winding block counts differ")
    used, result = set(), []
    for coil in coils:
        distances = [float(np.linalg.norm(np.asarray(coil["centroid_mm"]) - r["centroid_mm"])) for r in native]
        k = int(np.argmin(distances))
        target = native[k]
        if k in used or distances[k] > 0.1:
            raise ValueError("FEMM/native winding regions differ spatially")
        if any(coil[key] != target["winding"][key] for key in ("phase", "direction", "turn_fraction")):
            raise ValueError("FEMM/native winding phase, direction or turn-sharing differs")
        used.add(k)
        result.append({"native_region": target["id"], "centroid_difference_mm": distances[k]})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--shard", default="0/1")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    shard, shards = map(int, args.shard.split("/"))
    if not 0 <= shard < shards or args.limit is not None and args.limit < 1:
        parser.error("Invalid shard or limit")
    reuse_path = args.out.resolve().parent.parent / "reuse-femm.json"
    if reuse_path.exists():
        reuse = read(reuse_path)
        if args.case in reuse:
            from tools.phase_g_loss.femm_answers import collect

            return collect(args, reuse[args.case])
    case = case_by_id(args.case)
    native = read(args.native / "protocol.json")
    analysis = read(args.native / "analysis.json")
    if native["case"] != case or not analysis["numerical_history_pass"] or analysis["protocol_sha256"] != sha(args.native / "protocol.json"):
        raise ValueError("FEMM requires completed, audited Magneto2D history first")
    for name, digest in native["identity"]["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError("Native physics/collector sources changed after measurement: " + name)
    requested = config_for(case)
    if requested != native["requested_config"]:
        raise ValueError("FEMM/native registered input differs")
    if sha(args.native / "template.json") != native["template_sha256"]:
        raise ValueError("Bound native winding geometry changed")
    native_template = read(args.native / "template.json")
    from tools.femm_reference import e_producer, phase_e, runtime
    from tools.femm_reference.rotor_airgap import BOUNDARY, add_periodic_airgap, mesh_signature
    from tools.femm_reference.rotor_matched_history import coil_group, export_centroids, model_audit

    e_producer.clear_solver_environment()
    directory = args.out.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    outer = not case["rotor_supported"]
    expected = {
        "schema": "coilem.phase_g_history/v1",
        "solver": "femm",
        "case": case,
        "suite_sha256": sha(SUITE),
        "requested_config": requested,
        "positions": POSITIONS,
        "collection_speed_rpm": 3000,
        "evaluation_speeds_rpm": [1500, 3000],
        "coefficients": native["coefficients"],
        "native_protocol_sha256": sha(args.native / "protocol.json"),
        "native_analysis_sha256": sha(args.native / "analysis.json"),
        "reference_identity": runtime.identity("f" if outer else "e"),
        "collector_sha256": sha(__file__),
        "contract_sha256": sha(ROOT / "tools/phase_g_loss/contract.py"),
        "steel_bh_sha256": sha(ROOT / "materials/electrical-steel/M350-50A.csv"),
        "matched_magnet": {"Br_T": 1.315, "mu_r": 1.05},
        "rotor_status": native["rotor_status"],
        "rotor_unavailable_reason": native["rotor_unavailable_reason"],
        "native_fields_used_to_compute_reference": False,
        "motion": "remesh; stator-only fixed physical queries" if outer else "FEMM periodic air gap; fixed material mesh",
    }
    preparation_path = directory / "preparation.json"
    geometry_path = directory / "material-geometry.npz"
    if outer:
        from tools.femm_reference import phase_f

        adapter_runtime = phase_f.load_runtime()
        Model = adapter_runtime["MotorConfig"]
        from tools.femm_reference import automation as automation_module

        femm = automation_module.femm_module()
        config = Model.model_validate(native["native_config"])
        steel = adapter_runtime["steel"]("M350-50A")
        if steel.sha256 != expected["steel_bh_sha256"]:
            raise ValueError("Reference/native B-H data differ")
    else:
        Solver, Model, geometry_builder, curve, _, femm, automation_module, adapter = phase_e.load_adapter()
        config = Model.model_validate(native["native_config"])
        config.solve_params.mesh_density = case["femm_mesh"]
        os.environ["FEMM_AIRGAP_MESHSIZE_MM"] = str(case["femm_airgap_target_mm"])
        geom = geometry_builder(config)
        if curve("M350-50A").sha256 != expected["steel_bh_sha256"]:
            raise ValueError("Reference/native B-H data differ")

        class LossSolver(Solver):
            def _set_femm_blockprop(self, *a, **kw):
                if a[4] == "rotor_core":
                    kw["group"] = 10
                elif a[1] == getattr(self, "_stator_steel_material_name", None):
                    kw["group"] = 11
                match = re.fullmatch(r"Coil_v3_s(\d+)_l(\d+)", a[1])
                if match:
                    kw["group"] = coil_group(int(match[1]), int(match[2]))
                return super()._set_femm_blockprop(*a, **kw)

    worker = directory / f"worker-{shard}-of-{shards}-{uuid.uuid4().hex[:8]}"
    worker.mkdir()
    automation = automation_module.Automation(worker)
    try:
        automation.open(1)
        base = directory / "unsolved-base.fem"
        if not preparation_path.exists():
            if shards != 1:
                raise ValueError("Prepare the zero pose before sharding FEMM")
            if outer:
                ir, _ = phase_f.rotated_ir(adapter_runtime, config, 0)
                lowered = phase_f.lower_model(femm, adapter_runtime, config, ir, (0, 0, 0), steel)
                coils = mark_outer_regions(femm, ir, lowered)
            else:
                solver = LossSolver()
                solver._last_geom, solver._last_rotor_offset_rad = geom, 0.0
                solver._setup_problem(femm, config, geom)
                femm.mi_probdef(0, "millimeters", "planar", 1e-8, config.stator.stack_length_mm, 30, 0)
                for name in ["Magnet", *solver._magnet_label_names]:
                    for key, value in ((1, 1.05), (2, 1.05), (3, 1.315 / (1.05 * 4 * math.pi * 1e-7))):
                        femm.mi_modifymaterial(name, key, value)
                solver._draw_full_geometry(femm, config, geom, rotor_offset_deg=0)
                solver._apply_winding_current(femm, config, geom, 0)
                add_periodic_airgap(femm, solver, config, geom, arc_step_deg=case["femm_arc_step_deg"])
                solver._apply_boundary(femm, geom)
                from backend.geometry_ir import slot_layer_assignments

                coils = []
                for region in adapter.winding_regions(config, geom):
                    slot, layer, phase, direction = adapter.assignment(region)
                    side = next(s for s in slot_layer_assignments(config, slot) if s.layer == layer)
                    coils.append(
                        {
                            "name": f"Coil_v3_s{slot}_l{layer}",
                            "group": coil_group(slot, layer),
                            "point": adapter.label_point(region),
                            "slot": slot,
                            "phase": phase,
                            "direction": direction,
                            "turn_fraction": side.turn_fraction,
                        }
                    )
            femm.mi_saveas(str(base))
            femm.mi_saveas(str(directory / "area-probe.fem"))
            femm.mi_createmesh()
            femm.mi_analyze(1)
            femm.mi_loadsolution()
            for coil in coils:
                femm.mo_clearblock()
                femm.mo_selectblock(*coil["point"])
                coil["area_mm2"] = float(femm.mo_blockintegral(5)) * 1e6
                if coil["area_mm2"] <= 0:
                    raise ValueError("Empty FEMM winding block")
            centres = export_centroids(femm, directory, [c["group"] for c in coils])
            for coil in coils:
                coil["centroid_mm"] = centres[coil["group"]]
            electrical = reference_resistance(requested, coils)
            preparation = {
                "coils": coils,
                "spatial_winding_audit": audit_spatial_sources(coils, native_template),
                "electrical_contract": electrical,
                "mesh_signature": mesh_signature(directory / "area-probe.ans"),
                "sha256": {name: sha(directory / name) for name in ("unsolved-base.fem", "area-probe.fem", "area-probe.ans")},
            }
            write(preparation_path, preparation)
            femm.mo_close()
            femm.mi_close()
        preparation = read(preparation_path)
        if any(sha(directory / name) != digest for name, digest in preparation["sha256"].items()):
            raise ValueError("FEMM preparation changed")
        expected["electrical_contract"] = preparation["electrical_contract"]
        expected["preparation_sha256"] = sha(preparation_path)
        protocol(directory, expected)
        geometry = None
        if geometry_path.exists():
            with np.load(geometry_path) as data:
                geometry = {key: data[key] for key in data.files}
        new = 0
        for index in range(POSITIONS + 1):
            if index % shards != shard or checkpoint(directory, index):
                continue
            if args.limit is not None and new >= args.limit:
                break
            enough_disk(directory)
            output = directory / f"position-{index:04d}"
            output.mkdir(exist_ok=True)
            angle = -360 * index / POSITIONS
            started = time.perf_counter()
            phases = phase_ampere_turns(requested, angle)
            if outer:
                ir, _ = phase_f.rotated_ir(adapter_runtime, config, -angle * config.rotor.pole_count / 2)
                lowered = phase_f.lower_model(
                    femm, adapter_runtime, config, ir, tuple(phases[p] / config.winding.turns_per_coil for p in "ABC"), steel
                )
                mark_outer_regions(femm, ir, lowered)
            else:
                femm.opendocument(str(base))
                femm.mi_modifyboundprop(BOUNDARY, 10, angle)
                for coil in preparation["coils"]:
                    ni = phases[coil["phase"]] * coil["turn_fraction"] * (1 if coil["direction"] == "in" else -1)
                    femm.mi_modifymaterial(coil["name"], 4, ni / coil["area_mm2"])
            model = output / "model.fem"
            femm.mi_saveas(str(model))
            if not outer:
                applied = {
                    c["name"]: {**c, "ampere_turns": phases[c["phase"]] * c["turn_fraction"] * (1 if c["direction"] == "in" else -1)}
                    for c in preparation["coils"]
                }
                model_audit(model.read_text(encoding="latin-1"), angle, applied, {"remanence_T": 1.315, "relative_permeability": 1.05})
            femm.mi_createmesh()
            femm.mi_analyze(1)
            femm.mi_loadsolution()
            current_error = 0.0
            for coil in preparation["coils"]:
                femm.mo_clearblock()
                femm.mo_selectblock(*coil["point"])
                actual = complex(femm.mo_blockintegral(7))
                target = phases[coil["phase"]] * coil["turn_fraction"] * (1 if coil["direction"] == "in" else -1)
                current_error = max(current_error, abs(actual - target))
            if current_error > 1e-8:
                raise ValueError("Solved FEMM coil ampere-turns differ from registered excitation")
            signature = mesh_signature(model.with_suffix(".ans"))
            if not outer and signature != preparation["mesh_signature"]:
                raise ValueError("FEMM mesh changed during material history")
            geometry = export_material(femm, output, geometry, case["rotor_supported"], fixed=not outer)
            if not geometry_path.exists():
                if shards != 1 or index != 0:
                    raise ValueError("Bootstrap zero-pose integration geometry before sharding")
                write_npz(geometry_path, **geometry)
            femm.mo_close()
            femm.mi_close()
            write(output / "excitation.json", {"phase_ampere_turns": phases, "current_error_At": current_error})
            write(
                output / "position.json",
                {
                    "index": index,
                    "angle_deg": angle,
                    "wall_s": time.perf_counter() - started,
                    "mesh_signature": signature,
                    "geometry_sha256": sha(geometry_path),
                    "protocol_sha256": sha(directory / "protocol.json"),
                    "sha256": {p.name: sha(p) for p in output.iterdir() if p.is_file() and p.name != "position.json"},
                },
            )
            print(f"{args.case}: {index}/{POSITIONS}", flush=True)
            new += 1
    finally:
        automation.close()


if __name__ == "__main__":
    main()
