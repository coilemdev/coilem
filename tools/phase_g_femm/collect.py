"""Collect one Phase G rotor history in FEMM: a full mechanical turn on one fixed mesh.

Runs on Windows with FEMM 4.2 and tools/femm_reference/requirements.txt (see README.md here), or
on macOS/Linux with FEMM 5 through `python -m tools.phase_g_femm.femm5_run -m tools.phase_g_femm.collect`.

    python -m tools.phase_g_femm.collect --history inner_spm_loaded --out D:/coilem-phase-g-femm [--shard 0/4] [--limit N]

The rotor stays drawn at 0 degrees and an air-gap element turns it (FEMM's periodic air-gap boundary),
so every pose solves the same mesh and each rotor element's field is already in rotor axes. An outer
rotor is outside the band, so the band turns the stator the other way instead, which is the same
relative position. Inner rotors are drawn by the FEMM E adapter, outer rotors by the FEMM F adapter's
geometry lowering, as in the 0.5.9 Phase G stator references. Each pose
writes its rotor fields to fields.npz; its FEMM answer is hashed and then deleted, except for the
first and the closing pose (--keep-answers keeps all). Adapted from the 0.5.9 Phase G collector
(tools/phase_g_loss/femm.py at 9088fd46^).
"""

from __future__ import annotations

import argparse
import math
import os
import re
import time
import uuid
from pathlib import Path

import numpy as np

from tools.phase_g_femm.contract import (
    MATCHED_MAGNET,
    POSITIONS,
    ROOT,
    ROTOR_GROUP,
    SPEC,
    checkpoint,
    enough_disk,
    load_request,
    phase_ampere_turns,
    pose_angle,
    protocol,
    read,
    request_path,
    sha,
    write,
    write_npz,
)

STATOR_GROUP = 11


def export_rotor(femm, output: Path, geometry):
    """The rotor elements' corners and centroid B (rotor axes), checked against the first pose's mesh."""
    from tools.femm_reference.rotor_loss_pilot import lua_path

    path = output / "rotor.csv"
    commands = [
        'mo_smooth("off")',
        f'f=openfile({lua_path(path)},"w")',
        "for i=1,mo_numelements() do",
        "n1,n2,n3,x,y,a,g=mo_getelement(i)",
        f"if g=={ROTOR_GROUP} then",
        "x1,y1=mo_getnode(n1); x2,y2=mo_getnode(n2); x3,y3=mo_getnode(n3)",
        "az,bx,by=mo_getpointvalues(x,y)",
        'write(f,format("%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g\\n",x1,y1,x2,y2,x3,y3,bx,by))',
        "end end",
        "closefile(f)",
    ]
    script = output / "rotor-export.lua"
    script.write_text("\n".join(commands), encoding="ascii")
    femm.callfemm(f"dofile({lua_path(script)})")
    data = np.loadtxt(path, delimiter=",", ndmin=2)
    if data.shape[1] != 8 or not len(data) or not np.isfinite(data).all():
        raise ValueError("Empty or non-finite FEMM rotor export")
    corners = data[:, :6].reshape(-1, 3, 2)
    if geometry is not None and (corners.shape != geometry.shape or not np.allclose(corners, geometry, rtol=0, atol=1e-10)):
        raise ValueError("The FEMM rotor mesh changed during a fixed-mesh history")
    write_npz(output / "fields.npz", rotor=data[:, 6:])
    path.unlink()
    script.unlink()
    return corners


def inner_model(femm, Solver, adapter, config, geom, arc_step_deg: float) -> list[dict]:
    """The inner-rotor model at rotor 0 with the air-gap band (FEMM E adapter); returns its coil blocks."""
    from backend.geometry_ir import slot_layer_assignments
    from tools.femm_reference.rotor_airgap import add_periodic_airgap
    from tools.femm_reference.rotor_matched_history import coil_group

    class LossSolver(Solver):
        def _set_femm_blockprop(self, *a, **kw):
            if a[4] == "rotor_core":
                kw["group"] = ROTOR_GROUP
            elif a[1] == getattr(self, "_stator_steel_material_name", None):
                kw["group"] = STATOR_GROUP
            match = re.fullmatch(r"Coil_v3_s(\d+)_l(\d+)", a[1])
            if match:
                kw["group"] = coil_group(int(match[1]), int(match[2]))
            return super()._set_femm_blockprop(*a, **kw)

    solver = LossSolver()
    solver._last_geom, solver._last_rotor_offset_rad = geom, 0.0
    solver._setup_problem(femm, config, geom)
    femm.mi_probdef(0, "millimeters", "planar", 1e-8, config.stator.stack_length_mm, 30, 0)
    for name in ["Magnet", *solver._magnet_label_names]:
        for key, value in ((1, MATCHED_MAGNET["relative_permeability"]), (2, MATCHED_MAGNET["relative_permeability"]),
                           (3, MATCHED_MAGNET["remanence_T"] / (MATCHED_MAGNET["relative_permeability"] * 4 * math.pi * 1e-7))):
            femm.mi_modifymaterial(name, key, value)
    solver._draw_full_geometry(femm, config, geom, rotor_offset_deg=0)
    solver._apply_winding_current(femm, config, geom, 0)
    add_periodic_airgap(femm, solver, config, geom, arc_step_deg=arc_step_deg)
    solver._apply_boundary(femm, geom)
    coils = []
    for region in adapter.winding_regions(config, geom):
        slot, layer, phase, direction = adapter.assignment(region)
        side = next(s for s in slot_layer_assignments(config, slot) if s.layer == layer)
        coils.append({"name": f"Coil_v3_s{slot}_l{layer}", "group": coil_group(slot, layer), "point": adapter.label_point(region),
                      "slot": slot, "phase": phase, "direction": direction, "turn_fraction": side.turn_fraction})
    return coils


def outer_model(femm, runtime, config, steel, arc_step_deg: float):
    """The outer-rotor model at rotor 0 with an unmeshed air-gap band; returns its coil blocks and mesh settings."""
    from tools.femm_reference import phase_f
    from tools.femm_reference.rotor_airgap import BOUNDARY, band_radii
    from tools.femm_reference.rotor_matched_history import coil_group

    ir, _ = phase_f.rotated_ir(runtime, config, 0)
    lowered = phase_f.lower_model(femm, runtime, config, ir, (0, 0, 0), steel)
    steel_mesh = lowered["other_mesh_size_mm"]
    coils, airgap_labels = [], []
    for region in ir.regions:
        point = lowered["labels"][region.region_id]
        femm.mi_selectlabel(*point)
        if region.kind == "RotorCore":
            femm.mi_setblockprop("Steel_rotor", 0, steel_mesh, "<None>", 0, ROTOR_GROUP, 0)
        elif region.kind in ("StatorYoke", "StatorTooth"):
            femm.mi_setblockprop("Steel_stator", 0, steel_mesh, "<None>", 0, STATOR_GROUP, 0)
        elif region.kind == "SlotWinding":
            side = lowered["winding_specs"][region.region_id]
            group = coil_group(side["slot_index"], side["layer"])
            femm.mi_setblockprop("Copper", 0, steel_mesh, side["phase"], 0, group, side["signed_turns"])
            coils.append({"name": region.region_id, "group": group, "point": list(point), "slot": side["slot_index"],
                          "phase": side["phase"], "direction": side["direction"], "turn_fraction": side["turn_fraction"]})
        elif region.kind == "Airgap":
            airgap_labels.append(point)
        femm.mi_clearselected()
    stator_side = float(ir.metadata["airgap_stator_side_radius_mm"])
    rotor_side = float(ir.metadata["airgap_rotor_side_radius_mm"])
    # band_radii takes the inner surface first; here that is the stator.
    inner, outer = band_radii(stator_side, rotor_side)
    if len(airgap_labels) != 1 or not outer < math.hypot(*airgap_labels[0]) < rotor_side:
        raise ValueError("Expected one air-gap label between the band and the rotor")
    femm.mi_addboundprop(BOUNDARY, 0, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0)
    for radius in (inner, outer):
        femm.mi_drawarc(radius, 0, -radius, 0, 180, arc_step_deg)
        femm.mi_drawarc(-radius, 0, radius, 0, 180, arc_step_deg)
        for degrees in (90, 270):
            femm.mi_selectarcsegment(radius * math.cos(math.radians(degrees)), radius * math.sin(math.radians(degrees)))
        femm.mi_setarcsegmentprop(arc_step_deg, BOUNDARY, 0, 0)
        femm.mi_clearselected()
    # The existing air-gap label now covers the strip on the rotor side; add the band and the stator-side strip.
    label_angle = math.atan2(airgap_labels[0][1], airgap_labels[0][0])
    for radius, material in (((inner + outer) / 2, "<No Mesh>"), ((stator_side + inner) / 2, "Air")):
        point = (radius * math.cos(label_angle), radius * math.sin(label_angle))
        femm.mi_addblocklabel(*point)
        femm.mi_selectlabel(*point)
        if material == "Air":
            femm.mi_setblockprop("Air", 0, lowered["airgap_mesh_size_mm"], "<None>", 0, 0, 0)
        else:
            femm.mi_setblockprop(material, 1, 0, "<None>", 0, 0, 0)
        femm.mi_clearselected()
    settings = {key: lowered[key] for key in ("airgap_mesh_size_mm", "max_arc_segment_deg", "precision", "min_angle_deg",
                                              "smartmesh", "magnet_and_pocket_mesh_size_mm", "other_mesh_size_mm")}
    return coils, {**settings, "band_inner_radius_mm": inner, "band_outer_radius_mm": outer, "band_arc_step_deg": arc_step_deg}


def outer_model_audit(model: str, angle: float, phases: dict, turns_per_coil: int, magnet: dict) -> float:
    """The saved outer-rotor pose: no seed, the stator turned by -angle, the registered currents and magnets."""
    from tools.femm_reference.rotor_airgap import BOUNDARY

    if not re.search(r'^\[PrevSoln\]\s*=\s*""', model, re.M):
        raise ValueError("reference solve has a previous-solution seed")
    band = next(b for b in re.findall(r"<BeginBdry>(.*?)<EndBdry>", model, re.S) if f'"{BOUNDARY}"' in b)
    if (float(re.search(r"<innerangle>\s*=\s*([^\s]+)", band)[1]) != -angle
            or float(re.search(r"<outerangle>\s*=\s*([^\s]+)", band)[1]) != 0):
        raise ValueError("saved reference boundary pose differs")
    circuits = {}
    for circuit in re.findall(r"<BeginCircuit>(.*?)<EndCircuit>", model, re.S):
        name = re.search(r'<CircuitName>\s*=\s*"([^"]+)"', circuit)[1]
        if int(re.search(r"<CircuitType>\s*=\s*([^\s]+)", circuit)[1]) != 1:
            raise ValueError("reference windings must be series circuits")
        circuits[name] = float(re.search(r"<TotalAmps_re>\s*=\s*([^\s]+)", circuit)[1])
    if set(circuits) != set("ABC"):
        raise ValueError("saved reference circuits differ")
    error = max(abs(circuits[phase] * turns_per_coil - phases[phase]) for phase in "ABC")
    if error > 1e-8:
        raise ValueError("saved reference phase currents differ")
    blocks = {}
    for block in re.findall(r"<BeginBlock>(.*?)<EndBlock>", model, re.S):
        name = re.search(r'<BlockName>\s*=\s*"([^"]+)"', block)[1]
        blocks[name] = {key: float(value) for key, value in re.findall(r"<(Mu_x|Mu_y|H_c)>\s*=\s*([^\s]+)", block)}
    entry = blocks["PermanentMagnet"]
    if (abs(entry["H_c"] * entry["Mu_x"] * 4 * math.pi * 1e-7 - magnet["remanence_T"]) > 1e-10
            or any(abs(entry[k] - magnet["relative_permeability"]) > 1e-12 for k in ("Mu_x", "Mu_y"))):
        raise ValueError("saved FEMM magnet properties differ from native")
    return error


def audit_windings(coils: list[dict], native: list[dict]) -> list[dict]:
    """Match each FEMM coil block to a native coil side: same place, phase, direction and turn share."""
    if len(native) != len(coils):
        raise ValueError("FEMM and native coil-side counts differ")
    used, result = set(), []
    for coil in coils:
        distances = [float(np.linalg.norm(np.asarray(coil["centroid_mm"]) - np.asarray(side["centroid_mm"]))) for side in native]
        k = int(np.argmin(distances))
        target = native[k]
        if k in used or distances[k] > 0.1:
            raise ValueError("FEMM and native coil sides are in different places")
        if any(coil[key] != target[key] for key in ("phase", "direction", "turn_fraction")):
            raise ValueError("FEMM and native coil sides differ in phase, direction or turn share")
        used.add(k)
        result.append({"native_region": target["region"], "centroid_difference_mm": distances[k]})
    return result


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--history", required=True)
    parser.add_argument("--out", type=Path, required=True, help="Base folder; the history is collected in <out>/<history>")
    parser.add_argument("--shard", default="0/1", help="i/n: solve every n-th pose starting at i (prepare with 0/1 first)")
    parser.add_argument("--limit", type=int, help="Stop after this many new poses")
    parser.add_argument("--keep-answers", action="store_true", help="Keep every pose's FEMM answer (about 8-22 MB each)")
    parser.add_argument("--min-free-gb", type=float, default=6.0)
    args = parser.parse_args(argv)
    shard, shards = map(int, args.shard.split("/"))
    if not 0 <= shard < shards or (args.limit is not None and args.limit < 1):
        parser.error("Invalid shard or limit")

    request = load_request(args.history)
    row = request["history"]
    outer = row["rotor_layout"] == "outer"
    from tools.femm_reference import e_producer, phase_e, runtime
    from tools.femm_reference.rotor_airgap import BOUNDARY, mesh_signature
    from tools.femm_reference.rotor_matched_history import export_centroids, model_audit

    e_producer.clear_solver_environment()
    directory = (args.out / args.history).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    requested = request["requested_config"]
    mesh = request["femm_mesh"]
    expected = {
        "schema": "coilem.phase_g_femm_rotor_history/v1",
        "history": row,
        "spec_sha256": sha(SPEC),
        "request_sha256": sha(request_path(args.history)),
        "positions": POSITIONS,
        "coefficients": request["coefficients"],
        "reference_identity": runtime.identity("f" if outer else "e"),
        "collector_sha256": {name: sha(ROOT / "tools/phase_g_femm" / name) for name in ("collect.py", "contract.py")},
        "steel_bh_sha256": request["steel_bh_sha256"],
        "matched_magnet": MATCHED_MAGNET,
        "femm_mesh": mesh,
        "motion": ("FEMM periodic air-gap element turning the stator by minus the rotor angle; one fixed mesh; rotor fields in rotor axes"
                   if outer else "FEMM periodic air-gap element; one fixed mesh; rotor fields in rotor axes"),
    }
    if outer:
        from tools.femm_reference import automation as automation_module
        from tools.femm_reference import phase_f

        adapter_runtime = phase_f.load_runtime()
        config = adapter_runtime["MotorConfig"].model_validate(request["native_config"])
        steel = adapter_runtime["steel"]("M350-50A")
        if steel.sha256 != request["steel_bh_sha256"]:
            raise ValueError("FEMM and coilEM use different M350-50A B-H data")
        femm = automation_module.femm_module()
    else:
        Solver, Model, geometry_builder, curve, _, femm, automation_module, adapter = phase_e.load_adapter()
        config = Model.model_validate(request["native_config"])
        config.solve_params.mesh_density = mesh["density"]
        os.environ["FEMM_AIRGAP_MESHSIZE_MM"] = str(mesh["airgap_target_mm"])
        geom = geometry_builder(config)
        if curve("M350-50A").sha256 != request["steel_bh_sha256"]:
            raise ValueError("FEMM and coilEM use different M350-50A B-H data")

    preparation_path = directory / "preparation.json"
    geometry_path = directory / "rotor-geometry.npz"
    worker = directory / f"worker-{shard}-of-{shards}-{uuid.uuid4().hex[:8]}"
    worker.mkdir()
    automation = automation_module.Automation(worker)
    try:
        automation.open(1)
        base = directory / "unsolved-base.fem"
        if not preparation_path.exists():
            if shards != 1:
                raise ValueError("Prepare the first pose with --shard 0/1 before sharding")
            outer_settings = None
            if outer:
                coils, outer_settings = outer_model(femm, adapter_runtime, config, steel, mesh["airgap_arc_step_deg"])
            else:
                coils = inner_model(femm, Solver, adapter, config, geom, mesh["airgap_arc_step_deg"])
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
                    raise ValueError("Empty FEMM coil block")
            centres = export_centroids(femm, directory, [c["group"] for c in coils])
            for coil in coils:
                coil["centroid_mm"] = centres[coil["group"]]
            write(preparation_path, {
                "coils": coils,
                **({"outer_model": outer_settings} if outer else {}),
                "winding_audit": audit_windings(coils, request["native_windings"]),
                "mesh_signature": mesh_signature(directory / "area-probe.ans"),
                "sha256": {name: sha(directory / name) for name in ("unsolved-base.fem", "area-probe.fem")},
            })
            (directory / "area-probe.ans").unlink()
            femm.mo_close()
            femm.mi_close()
        preparation = read(preparation_path)
        if any(sha(directory / name) != digest for name, digest in preparation["sha256"].items()):
            raise ValueError("The FEMM preparation changed")
        expected["preparation_sha256"] = sha(preparation_path)
        protocol(directory, expected)
        geometry = None
        if geometry_path.exists():
            with np.load(geometry_path) as data:
                geometry = data["rotor_corners"]
        new = 0
        for index in range(POSITIONS + 1):
            if index % shards != shard or checkpoint(directory, index):
                continue
            if args.limit is not None and new >= args.limit:
                break
            enough_disk(directory, args.min_free_gb)
            output = directory / f"position-{index:04d}"
            output.mkdir(exist_ok=True)
            angle = pose_angle(index)
            started = time.perf_counter()
            phases = phase_ampere_turns(requested, angle)
            femm.opendocument(str(base))
            model = output / "model.fem"
            if outer:
                # The stator is FEMM's inner side here: turning it by -angle puts the rotor at angle relative to it.
                femm.mi_modifyboundprop(BOUNDARY, 10, -angle)
                for phase in "ABC":
                    femm.mi_modifycircprop(phase, 1, phases[phase] / config.winding.turns_per_coil)
                femm.mi_saveas(str(model))
                outer_model_audit(model.read_text(encoding="latin-1"), angle, phases, config.winding.turns_per_coil, MATCHED_MAGNET)
            else:
                femm.mi_modifyboundprop(BOUNDARY, 10, angle)
                for coil in preparation["coils"]:
                    ni = phases[coil["phase"]] * coil["turn_fraction"] * (1 if coil["direction"] == "in" else -1)
                    femm.mi_modifymaterial(coil["name"], 4, ni / coil["area_mm2"])
                femm.mi_saveas(str(model))
                applied = {c["name"]: {**c, "ampere_turns": phases[c["phase"]] * c["turn_fraction"] * (1 if c["direction"] == "in" else -1)}
                           for c in preparation["coils"]}
                model_audit(model.read_text(encoding="latin-1"), angle, applied, MATCHED_MAGNET)
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
                raise ValueError("Solved FEMM coil ampere-turns differ from the registered excitation")
            answer = model.with_suffix(".ans")
            signature = mesh_signature(answer)
            if signature != preparation["mesh_signature"]:
                raise ValueError("The FEMM mesh changed during the history")
            corners = export_rotor(femm, output, geometry)
            if geometry is None:
                if shards != 1 or index != 0:
                    raise ValueError("Collect the first pose with --shard 0/1 before sharding")
                write_npz(geometry_path, rotor_corners=corners)
                geometry = corners
            femm.mo_close()
            femm.mi_close()
            answer_sha = sha(answer)
            if not args.keep_answers and index not in (0, POSITIONS):
                answer.unlink()
            write(output / "excitation.json", {"phase_ampere_turns": phases, "current_error_At": current_error})
            write(output / "position.json", {
                "index": index,
                "angle_deg": angle,
                "wall_s": time.perf_counter() - started,
                "mesh_signature": signature,
                "answer_sha256": answer_sha,
                "geometry_sha256": sha(geometry_path),
                "protocol_sha256": sha(directory / "protocol.json"),
                "sha256": {p.name: sha(p) for p in output.iterdir() if p.is_file() and p.name != "position.json"},
            })
            print(f"{args.history}: {index}/{POSITIONS}", flush=True)
            new += 1
    finally:
        automation.close()


if __name__ == "__main__":
    main()
