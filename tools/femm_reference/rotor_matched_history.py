"""Corrected #306 FEMM history, bound to audited native poses and materials.

Run only in the isolated pinned FEMM environment. The frozen E implementation
supplies geometry/steel; explicit native ampere-turns, measured coil areas and
the native Rust magnet properties replace historical excitation/catalog defaults.
The 384 grid can be collected progressively with --stride 4, 2, then 1.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
import uuid
from pathlib import Path

import numpy as np

from tools.femm_reference import e_producer, phase_e, runtime
from tools.femm_reference.rotor_airgap import BOUNDARY, add_periodic_airgap, mesh_signature
from tools.femm_reference.rotor_excitation_probe import coil_group
from tools.femm_reference.rotor_loss_pilot import FIXTURE, ROOT, export_fields, lua_path, sha


def selected_indices(positions, stride, shard=0, shards=1):
    if stride not in (1, 2, 4) or positions % stride or not 0 <= shard < shards:
        raise ValueError("invalid progressive grid or shard")
    # Keep the same coarse block on one worker at each progressive stage, so
    # newly inserted half/quarter steps remain balanced after old poses skip.
    return [i for i in range(0, positions+1, stride) if (i//4) % shards == shard]


def mesh_controls(mesh, airgap_target_mm, airgap_arc_step_deg):
    if (mesh not in ("normal", "fine", "very_fine")
            or not all(math.isfinite(v) and v > 0 for v in (airgap_target_mm, airgap_arc_step_deg))
            or airgap_arc_step_deg >= 180):
        raise ValueError("invalid explicit reference mesh controls")
    return {"mesh": mesh, "airgap_target_mm": airgap_target_mm, "airgap_arc_step_deg": airgap_arc_step_deg}


def validate_excitation(excitation, angle):
    if excitation["gate"] != "PASS" or excitation["native_rotor_mechanical_deg"] != angle or excitation["native_gamma_deg"] != 180:
        raise ValueError("native excitation audit or signed pose differs")
    # Independent golden contract for this one 8p/12s, 12-turn, 20 A fixture.
    for phase, offset in zip("ABC", (0, 120, 240)):
        expected = 240*math.sin(math.radians(4*angle+60-offset))
        actual = excitation["phase_ampere_turns"][phase]
        if not math.isfinite(actual) or abs(actual-expected) > 1e-8:
            raise ValueError("native ampere-turns differ from the independent constant-gamma sine")


def native_inputs(directory):
    directory = Path(directory)
    protocol = json.loads((directory / "protocol.json").read_text())
    analysis = json.loads((directory / "analysis.json").read_text())
    config = json.loads((directory / "native-config.json").read_text())
    if (protocol["kind"] != "full_turn_history" or protocol["positions"] != 384 or protocol.get("motion_model") != "fixed-material"
            or protocol["fixture_sha256"] != sha(FIXTURE) or not analysis["native_history_numerical_gates_pass"]
            or protocol["requested_gamma_deg"] != 0 or protocol["native_gamma_deg"] != 180
            or protocol["current_peak_A"] != 20 or protocol["speed_rpm"] != 3000
            or protocol["mechanical_angles_deg"] != [-360*i/384 for i in range(385)]
            or analysis["protocol_sha256"] != sha(directory / "protocol.json")
            or config["solve_params"].get("magnet_temperature_C") is not None):
        raise ValueError("matched reference requires the registered converged native pilot")
    if config["materials"]["magnet_grade"] != "N42" or any(config["materials"][k] != "M350-50A" for k in ("stator_steel", "rotor_steel")):
        raise ValueError("matched pilot materials differ")
    for name, digest in protocol["identity"]["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f"native collection source changed: {name}")
    material_source = ROOT / "solvers/magneto2d/src/materials.rs"
    match = re.search(r'"N42"\s*=>\s*\(([0-9.]+),\s*([0-9.]+)\)', material_source.read_text())
    if match is None:
        raise ValueError("native N42 material constants are not explicit")
    magnet = {"grade": "N42", "remanence_T": float(match[1]), "relative_permeability": float(match[2]),
              "native_source_sha256": sha(material_source)}
    first_report_path = directory / "position-0000/native_report.json"
    first_report = json.loads(first_report_path.read_text())
    if first_report["solver_environment"]["policy"] != "request-only-v1" or "COILEM_MAGNET_BR_SCALE" in first_report["solver_environment"]["options"]:
        raise ValueError("native magnet scale or environment policy differs")
    excitations, digests = [], []
    for i, angle in enumerate(protocol["mechanical_angles_deg"]):
        folder = directory / f"position-{i:04d}"
        record = json.loads((folder / "position.json").read_text())
        path = folder / "excitation.json"
        digest = sha(path)
        if angle != -360*i/384 or digest != record["sha256"]["excitation.json"]:
            raise ValueError("native excitation evidence changed")
        if i == 0 and sha(first_report_path) != record["sha256"]["native_report.json"]:
            raise ValueError("native source-report evidence changed")
        excitation = json.loads(path.read_text())
        validate_excitation(excitation, angle)
        excitations.append(excitation)
        digests.append(digest)
    template_path = directory / "material-template.json"
    if sha(template_path) != protocol["material_template_sha256"]:
        raise ValueError("native material template changed")
    template = json.loads(template_path.read_text())
    nodes, triangles = np.asarray(template["mesh"]["nodes"]), np.asarray(template["mesh"]["triangles"])
    ids = np.asarray(template["element_region_ids"])
    regions = []
    for region in template["physics_contract"]["regions"]:
        if region["kind"] not in ("Magnet", "SlotWinding"):
            continue
        corners = nodes[triangles[ids == region["id"]]]
        u, v = corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0]
        weights = abs(u[:, 0]*v[:, 1]-u[:, 1]*v[:, 0])
        centre = np.average(corners.mean(axis=1), weights=weights, axis=0)
        regions.append(region | {"centroid_mm": centre.tolist()})
    return {"protocol": protocol, "analysis": analysis, "config": config, "magnet": magnet,
            "excitations": excitations, "excitation_sha256": digests, "regions": regions,
            "protocol_sha256": sha(directory / "protocol.json"), "analysis_sha256": sha(directory / "analysis.json"),
            "first_report_sha256": sha(first_report_path), "config_sha256": sha(directory / "native-config.json")}


def match_geometry(observed, native, *, magnet=False):
    candidates = [r for r in native if r["kind"] == ("Magnet" if magnet else "SlotWinding")]
    if len(observed) != len(candidates):
        raise ValueError("native and FEMM material-region counts differ")
    matched, used = [], set()
    for name, entry in observed.items():
        distances = [float(np.linalg.norm(np.asarray(entry["centroid_mm"])-r["centroid_mm"])) for r in candidates]
        k = int(np.argmin(distances))
        target = candidates[k]
        if k in used or distances[k] > 0.1:
            raise ValueError("FEMM/native region centroids do not identify the same spatial sources")
        if magnet:
            delta = math.remainder(entry["magnetization_angle_deg"]-target["magnetization_angle_deg"], 360)
            if abs(delta) > 1e-8:
                raise ValueError("FEMM/native magnetization directions differ")
        elif any(entry[key] != target["winding"][key] for key in ("phase", "direction")):
            raise ValueError("FEMM/native spatial winding assignments differ")
        used.add(k)
        matched.append({"reference_region": name, "native_region": target["id"], "centroid_distance_mm": distances[k]})
    return matched


def model_audit(model, angle, applied, magnet):
    if not re.search(r'^\[PrevSoln\]\s*=\s*""', model, re.M):
        raise ValueError("reference solve has a previous-solution seed")
    boundaries = re.findall(r"<BeginBdry>(.*?)<EndBdry>", model, re.S)
    band = next(b for b in boundaries if f'"{BOUNDARY}"' in b)
    if (float(re.search(r"<innerangle>\s*=\s*([^\s]+)", band)[1]) != angle
            or float(re.search(r"<outerangle>\s*=\s*([^\s]+)", band)[1]) != 0):
        raise ValueError("saved reference boundary pose differs")
    blocks = {}
    for block in re.findall(r"<BeginBlock>(.*?)<EndBlock>", model, re.S):
        name = re.search(r'<BlockName>\s*=\s*"([^"]+)"', block)[1]
        blocks[name] = {key: float(value) for key, value in re.findall(r"<(Mu_x|Mu_y|H_c|J_re)>\s*=\s*([^\s]+)", block)}
    error = max(abs(blocks[name]["J_re"]*e["area_mm2"]-e["ampere_turns"]) for name, e in applied.items())
    if {name for name in blocks if name.startswith("Coil_v3_")} != set(applied):
        raise ValueError("saved reference winding set differs")
    magnets = [v for name, v in blocks.items() if name == "Magnet" or name.startswith("Magnet_")]
    if len(magnets) != 9 or error > 1e-8:
        raise ValueError("saved reference source materials differ")
    for entry in magnets:
        br = entry["H_c"]*entry["Mu_x"]*4*math.pi*1e-7
        if abs(br-magnet["remanence_T"]) > 1e-10 or any(abs(entry[k]-magnet["relative_permeability"]) > 1e-12 for k in ("Mu_x", "Mu_y")):
            raise ValueError("saved FEMM magnet properties differ from native")
    return error


def export_centroids(femm, directory, groups):
    output = directory / "source-centroids.csv"
    commands = ["area={}; mx={}; my={}"]
    commands += [f"area[{g}]=0; mx[{g}]=0; my[{g}]=0" for g in groups]
    commands += ["for i=1,mo_numelements() do", "n1,n2,n3,x,y,a,g=mo_getelement(i)",
                 "if area[g] then area[g]=area[g]+a; mx[g]=mx[g]+a*x; my[g]=my[g]+a*y end end",
                 f'f=openfile({lua_path(output)},"w")']
    commands += [f'write(f,format("%d,%.17g,%.17g\\n",{g},mx[{g}]/area[{g}],my[{g}]/area[{g}]))' for g in groups]
    commands += ["closefile(f)"]
    script = directory / "source-centroids.lua"
    script.write_text("\n".join(commands), encoding="ascii")
    femm.callfemm(f"dofile({lua_path(script)})")
    return {int(g): [x, y] for g, x, y in np.loadtxt(output, delimiter=",", ndmin=2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-history", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stride", type=int, choices=(1, 2, 4), default=4)
    parser.add_argument("--mesh", choices=("normal", "fine", "very_fine"), default="normal")
    parser.add_argument("--airgap-target-mm", type=float, default=0.125)
    parser.add_argument("--airgap-arc-step-deg", type=float, default=0.25)
    parser.add_argument("--shard", default="0/1")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    controls = mesh_controls(args.mesh, args.airgap_target_mm, args.airgap_arc_step_deg)
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    shard, shards = map(int, args.shard.split("/"))
    indices = selected_indices(384, args.stride, shard, shards)
    native = native_inputs(args.native_history.resolve())
    directory = args.out.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    identity = runtime.identity("e")
    protocol = {"schema": "coilem.matched_rotor_reference/v1", "collection_kind": "full_turn_history",
                "motion_model": "periodic-air-gap", "positions": 384,
                "mechanical_angles_deg": native["protocol"]["mechanical_angles_deg"],
                "raw_mesh_frame": "rotor_material", "raw_field_frame": "rotor_material", "independent_base_reload": True,
                "fixture": FIXTURE.relative_to(ROOT).as_posix(), "fixture_sha256": sha(FIXTURE),
                "speed_rpm": 3000, "current_peak_A": 20, "gamma_deg": 180, "requested_public_gamma_deg": 0,
                **controls, "mesh_control_contract": "explicit_preset_airgap/v1", "smoothing": "off",
                "native_protocol_sha256": native["protocol_sha256"], "native_analysis_sha256": native["analysis_sha256"],
                "native_config_sha256": native["config_sha256"],
                "native_excitation_sha256": native["excitation_sha256"], "native_loss_material": native["analysis"]["loss_material"],
                "native_first_report_sha256": native["first_report_sha256"], "matched_magnet": native["magnet"],
                "excitation_contract": "audited native phase ampere-turns / actual FEMM coil areas; boundary angle is native CCW theta",
                "reference_identity": identity, "collector_sha256": sha(__file__),
                "steel_bh_sha256": sha(ROOT / "materials/electrical-steel/M350-50A.csv"),
                "closure_tolerances": {"max_component_T": 1e-6, "rms_component_T": 1e-7},
                "cross_solver_tolerances": {"relative": 0.10, "absolute_W": 0.001}, "full_matrix_started": False}
    protocol_path = directory / "protocol.json"
    if protocol_path.exists():
        if not args.resume or json.loads(protocol_path.read_text()) != protocol:
            raise ValueError("matched reference request, native input or implementation changed")
    else:
        runtime.write(protocol_path, protocol)
    Solver, Model, geometry, curve, _, femm, automation_module, adapter = phase_e.load_adapter()
    e_producer.clear_solver_environment()
    os.environ["FEMM_AIRGAP_MESHSIZE_MM"] = str(args.airgap_target_mm)
    if curve("M350-50A").sha256 != sha(ROOT / "materials/electrical-steel/M350-50A.csv"):
        raise ValueError("native and FEMM steel B-H curves differ")
    config = Model.model_validate(json.loads(FIXTURE.read_text()))
    config.solve_params.current_angle_deg, config.solve_params.mesh_density = 180, args.mesh
    geom = geometry(config)

    class MatchedSolver(Solver):
        def _set_femm_blockprop(self, *a, **kw):
            if a[4] == "rotor_core":
                kw["group"] = 10
            match = re.fullmatch(r"Coil_v3_s(\d+)_l(\d+)", a[1])
            if match:
                kw["group"] = coil_group(int(match[1]), int(match[2]))
            elif a[1] in getattr(self, "_magnet_label_names", []):
                kw["group"] = 200+self._magnet_label_names.index(a[1])
                self.directions[a[1]] = kw.get("magnetization_direction", 0)
            return super()._set_femm_blockprop(*a, **kw)

    worker = directory / f"stride-{args.stride}-worker-{shard}-of-{shards}-{uuid.uuid4().hex[:8]}"
    worker.mkdir()
    automation = automation_module.Automation(worker)
    reference_path, preparation_path = directory / "reference-points.csv", directory / "preparation.json"
    new_positions, started = 0, time.perf_counter()
    try:
        automation.open(1)
        base = directory / "unsolved-base.fem"
        if not preparation_path.exists():
            if shards != 1:
                raise ValueError("prepare one zero pose before launching shards")
            solver = MatchedSolver()
            solver.directions = {}
            solver._last_geom, solver._last_rotor_offset_rad = geom, 0.
            solver._setup_problem(femm, config, geom)
            femm.mi_probdef(0, "millimeters", "planar", 1e-8, config.stator.stack_length_mm, 30, 0)
            hc = native["magnet"]["remanence_T"]/(native["magnet"]["relative_permeability"]*4*math.pi*1e-7)
            for name in ["Magnet", *solver._magnet_label_names]:
                mu = native["magnet"]["relative_permeability"]
                for key, value in ((1, mu), (2, mu), (3, hc)):
                    femm.mi_modifymaterial(name, key, value)
            solver._draw_full_geometry(femm, config, geom, rotor_offset_deg=0)
            solver._apply_winding_current(femm, config, geom, 0)
            add_periodic_airgap(femm, solver, config, geom, arc_step_deg=args.airgap_arc_step_deg)
            solver._apply_boundary(femm, geom)
            femm.mi_saveas(str(base))
            femm.mi_saveas(str(directory / "area-probe.fem"))
            femm.mi_createmesh()
            femm.mi_analyze(1)
            femm.mi_loadsolution()
            coils = {}
            for region in adapter.winding_regions(config, geom):
                slot, layer, phase, direction = adapter.assignment(region)
                group = coil_group(slot, layer)
                femm.mo_groupselectblock(group)
                area = float(femm.mo_blockintegral(5))*1e6
                femm.mo_clearblock()
                if not math.isfinite(area) or area <= 0:
                    raise ValueError("empty winding block in reference area probe")
                coils[f"Coil_v3_s{slot}_l{layer}"] = {"group": group, "phase": phase, "direction": direction, "area_mm2": area}
            centres = export_centroids(femm, directory, [e["group"] for e in coils.values()]+list(range(200, 208)))
            for entry in coils.values():
                entry["centroid_mm"] = centres[entry["group"]]
            magnets = {name: {"centroid_mm": centres[200+i], "magnetization_angle_deg": solver.directions[name]}
                       for i, name in enumerate(solver._magnet_label_names)}
            preparation = {"coils": coils, "magnets": magnets,
                           "winding_geometry_audit": match_geometry(coils, native["regions"]),
                           "magnet_geometry_audit": match_geometry(magnets, native["regions"], magnet=True),
                           "mesh_geometry_sha256": mesh_signature(directory / "area-probe.ans"),
                           "sha256": {name: sha(directory / name) for name in ("unsolved-base.fem", "area-probe.fem", "area-probe.ans")}}
            femm.mo_close()
            femm.mi_close()
            runtime.write(preparation_path, preparation)
        preparation = json.loads(preparation_path.read_text())
        if any(sha(directory / name) != digest for name, digest in preparation["sha256"].items()):
            raise ValueError("matched reference preparation changed")
        points = np.loadtxt(reference_path, delimiter=",", ndmin=2) if reference_path.exists() else None
        for index in indices:
            angle = protocol["mechanical_angles_deg"][index]
            output = directory / f"position-{index:04d}"
            checkpoint = output / "position.json"
            if checkpoint.exists():
                record = json.loads(checkpoint.read_text())
                if record["index"] != index or any(sha(output / name) != digest for name, digest in record["sha256"].items()):
                    raise ValueError("matched reference checkpoint changed")
                continue
            if args.limit is not None and new_positions >= args.limit:
                break
            if shards != 1 and points is None:
                raise ValueError("zero pose must establish the material query grid first")
            output.mkdir(exist_ok=True)
            begin = time.perf_counter()
            femm.opendocument(str(base))
            femm.mi_modifyboundprop(BOUNDARY, 10, angle)
            applied = {}
            for name, entry in preparation["coils"].items():
                ni = native["excitations"][index]["phase_ampere_turns"][entry["phase"]]*(1 if entry["direction"] == "in" else -1)
                density = ni/entry["area_mm2"]
                femm.mi_modifymaterial(name, 4, density)
                applied[name] = entry | {"ampere_turns": ni, "current_density_A_mm2": density}
            model = output / "model.fem"
            femm.mi_saveas(str(model))
            saved_error = model_audit(model.read_text(encoding="latin-1"), angle, applied, native["magnet"])
            femm.mi_createmesh()
            femm.mi_analyze(1)
            femm.mi_loadsolution()
            points, rotor_elements = export_fields(femm, output, 0., points)
            if not reference_path.exists():
                np.savetxt(reference_path, points, delimiter=",", fmt="%.17g")
            observed_error = 0.
            for entry in applied.values():
                femm.mo_groupselectblock(entry["group"])
                actual = complex(femm.mo_blockintegral(7))
                femm.mo_clearblock()
                observed_error = max(observed_error, abs(actual-entry["ampere_turns"]))
            if observed_error > 1e-8:
                raise ValueError("FEMM solution currents differ from requested native ampere-turns")
            signature = mesh_signature(model.with_suffix(".ans"))
            if signature != preparation["mesh_geometry_sha256"]:
                raise ValueError("reference mesh changed between fresh base reloads")
            runtime.write(output / "applied-excitation.json", applied)
            record = {"index": index, "mechanical_angle_deg": angle, "rotor_elements": rotor_elements,
                      "total_elements": int(femm.mo_numelements()), "mesh_geometry_sha256": signature,
                      "airgap_target_mm": args.airgap_target_mm, "airgap_arc_step_deg": args.airgap_arc_step_deg,
                      "native_excitation_sha256": native["excitation_sha256"][index],
                      "saved_current_error_At": saved_error, "solution_current_error_At": observed_error,
                      "wall_s": time.perf_counter()-begin, "sha256": {p.name: sha(p) for p in output.iterdir() if p.is_file()}}
            femm.mo_close()
            femm.mi_close()
            runtime.write(checkpoint, record)
            new_positions += 1
            print(json.dumps({k: record[k] for k in ("index", "mechanical_angle_deg", "rotor_elements", "total_elements", "wall_s")}), flush=True)
    finally:
        automation.close()
    runtime.write(worker / "collection.json", {"stride": args.stride, "new_positions": new_positions,
                  "invocation_wall_s": time.perf_counter()-started, "positions_present": len(list(directory.glob("position-*/position.json")))})


if __name__ == "__main__":
    main()
