"""Independent 96-pose electrical-cycle FEMM reference; stator and DC copper only."""
from __future__ import annotations

import argparse
import shutil
import time
import uuid
from pathlib import Path

import numpy as np

from tools.phase_g_loss.contract import case_by_id, protocol, read, reference_resistance, sha, write, write_npz
from tools.phase_g_loss.contract import checkpoint as legacy_checkpoint
from tools.phase_g_loss.femm import audit_spatial_sources, export_material, mark_outer_regions
from tools.phase_g_loss.stator_contract import PROFILE, SAMPLES, checkpoint, magnetic_geometry


def verify_old_pose(source, index):
    record = legacy_checkpoint(source, index)
    if record is None:
        return None
    if record["protocol_sha256"] != sha(source / "protocol.json"):
        raise ValueError("Legacy reference pose belongs to different inputs")
    old = read(source / "protocol.json")
    if "reused_source_history" in old:
        original = Path(old["reused_source_history"]) / f"position-{index:04d}"
        if sha(original / "model.ans") != record["source_answer_sha256"] or sha(original / "position.json") != record["original_checkpoint_sha256"]:
            raise ValueError("Original immutable FEMM answer changed")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--shard", default="0/1")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    shard, shards = map(int, args.shard.split("/"))
    if not 0 <= shard < shards or shards > 2:
        raise ValueError("Use one or two nonoverlapping FEMM shards")
    case = case_by_id(args.case)
    native = read(args.native / "protocol.json")
    completed = read(args.native / "completed.json")
    if any(sha(args.native / name) != digest for name, digest in completed["sha256"].items()):
        raise ValueError("Production evidence changed")
    requested = native["requested_config"]
    pairs = requested["rotor"]["pole_count"] // 2
    outer = not case["rotor_supported"]
    directory = args.out.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    legacy = args.legacy.resolve()
    source = legacy / "femm" / args.case
    reuse_fields = (source / "protocol.json").exists()
    if reuse_fields:
        old = read(source / "protocol.json")
        if magnetic_geometry(old["requested_config"]) != magnetic_geometry(requested):
            raise ValueError("Legacy reference magnetic geometry differs")
        reuse_fields = old["requested_config"]["solve_params"]["current_amplitude_A"] == requested["solve_params"]["current_amplitude_A"]
        reuse_fields &= old["positions"] == SAMPLES * pairs
    base_source = next((legacy / "femm" / cid for cid in (args.case, args.case.replace("loaded", "no-load"),
                       args.case.replace("no-load", "loaded"))
                       if (legacy / "femm" / cid / "preparation.json").exists()), None)
    if base_source is not None:
        old = read(base_source / "protocol.json")
        if magnetic_geometry(old["requested_config"]) != magnetic_geometry(requested):
            raise ValueError("Legacy base model geometry differs")
    geometry_path = directory / "material-geometry.npz"
    if not geometry_path.exists() and reuse_fields:
        with np.load(source / "material-geometry.npz") as data:
            write_npz(geometry_path, stator_corners=data["stator_corners"])
    prep_path = directory / "preparation.json"
    base = directory / "unsolved-base.fem"
    if not prep_path.exists() and base_source is not None:
        original = read(base_source / "preparation.json")
        if any(sha(base_source / name) != digest for name, digest in original["sha256"].items()):
            raise ValueError("Legacy base mesh or model changed")
        for name in original["sha256"]:
            shutil.copy2(base_source / name, directory / name)
        prep = {**original, "geometry_source": str(base_source), "source_preparation_sha256": sha(base_source / "preparation.json")}
        prep["spatial_winding_audit"] = audit_spatial_sources(prep["coils"], read(args.native / "template.json"))
        write(prep_path, prep)
        if not geometry_path.exists():
            with np.load(base_source / "material-geometry.npz") as data:
                write_npz(geometry_path, stator_corners=data["stator_corners"])
    from tools.femm_reference import automation as automation_module
    from tools.femm_reference import e_producer, runtime
    e_producer.clear_solver_environment()
    identity = runtime.identity("f" if outer else "e")
    expected = {"schema": "coilem.stator_femm_history/v1", "case_id": args.case, "profile_sha256": sha(PROFILE),
                "native_protocol_sha256": sha(args.native / "protocol.json"), "native_completed_sha256": sha(args.native / "completed.json"),
                "requested_config": requested, "electrical_samples": SAMPLES, "mechanical_span_deg": 360 / pairs,
                "collector_sha256": sha(__file__), "reference_identity": identity,
                "native_fields_used_to_compute_reference": False, "rotor_loss_included": False,
                "coefficients": native["coefficients"],
                "projection_source": str(source) if reuse_fields else None,
                "projection_protocol_sha256": sha(source / "protocol.json") if reuse_fields else None}
    # Complete saved references need no COM session or new field solve.
    if reuse_fields and not prep_path.exists():
        prep = {"electrical_contract": read(source / "protocol.json")["electrical_contract"],
                "source_protocol_sha256": sha(source / "protocol.json"), "projection_only": True}
        write(prep_path, prep)
    femm = None
    automation = None
    runtime_f = None
    model = None
    steel = None
    try:
        def open_session():
            nonlocal femm, automation
            if automation is None:
                worker = directory / f"worker-{shard}-of-{shards}-{uuid.uuid4().hex[:8]}"
                worker.mkdir()
                automation = automation_module.Automation(worker)
                automation.open(1)
                femm = automation.femm

        if outer:
            from tools.femm_reference import phase_f
            runtime_f = phase_f.load_runtime()
            model = runtime_f["MotorConfig"].model_validate(native["native_config"])
            steel = runtime_f["steel"]("M350-50A")
        if not prep_path.exists():
            if not outer or shards != 1:
                raise ValueError("Prepare a verified legacy inner model or bootstrap the outer model alone")
            open_session()
            from tools.femm_reference.rotor_matched_history import export_centroids
            ir, _ = phase_f.rotated_ir(runtime_f, model, 0)
            lowered = phase_f.lower_model(femm, runtime_f, model, ir, (0, 0, 0), steel)
            coils = mark_outer_regions(femm, ir, lowered)
            femm.mi_saveas(str(base))
            femm.mi_saveas(str(directory / "area-probe.fem"))
            femm.mi_createmesh()
            femm.mi_analyze(1)
            femm.mi_loadsolution()
            for coil in coils:
                femm.mo_clearblock()
                femm.mo_selectblock(*coil["point"])
                coil["area_mm2"] = float(femm.mo_blockintegral(5)) * 1e6
            centres = export_centroids(femm, directory, [c["group"] for c in coils])
            for coil in coils:
                coil["centroid_mm"] = centres[coil["group"]]
            from tools.femm_reference.rotor_airgap import mesh_signature
            prep = {"coils": coils, "electrical_contract": reference_resistance(requested, coils),
                    "spatial_winding_audit": audit_spatial_sources(coils, read(args.native / "template.json")),
                    "mesh_signature": mesh_signature(directory / "area-probe.ans"),
                    "sha256": {name: sha(directory / name) for name in ("unsolved-base.fem", "area-probe.fem", "area-probe.ans")}}
            write(prep_path, prep)
            femm.mo_close()
            femm.mi_close()
        prep = read(prep_path)
        expected.update(preparation_sha256=sha(prep_path), electrical_contract=prep["electrical_contract"])
        protocol(directory, expected)
        if reuse_fields:
            for index in range(SAMPLES + 1):
                if checkpoint(directory, index):
                    continue
                original = verify_old_pose(source, index)
                if original is None:
                    continue
                if abs(original["angle_deg"] + 360 * index / (SAMPLES * pairs)) > 1e-9:
                    raise ValueError("Legacy angle does not lie on the electrical-cycle grid")
                target = directory / f"position-{index:04d}"
                target.mkdir(exist_ok=True)
                with np.load(source / f"position-{index:04d}" / "fields.npz") as data:
                    write_npz(target / "fields.npz", stator=data["stator"])
                write(target / "position.json", {"index": index, "electrical_angle_deg": -360 * index / SAMPLES,
                      "mechanical_angle_deg": original["angle_deg"], "protocol_sha256": sha(directory / "protocol.json"),
                      "geometry_sha256": sha(geometry_path), "source_checkpoint": str(source / f"position-{index:04d}" / "position.json"),
                      "source_checkpoint_sha256": sha(source / f"position-{index:04d}" / "position.json"),
                      "new_field_solve": False, "sha256": {"fields.npz": sha(target / "fields.npz")}})
        if args.prepare_only and checkpoint(directory, 0):
            return
        if all(checkpoint(directory, i) for i in range(SAMPLES + 1)):
            return
        if prep.get("projection_only"):
            raise ValueError("Projected reference incomplete; no verified base model for fresh poses")
        if any(sha(directory / name) != digest for name, digest in prep["sha256"].items()):
            raise ValueError("Reference preparation changed")
        open_session()
        from tools.femm_reference.rotor_airgap import BOUNDARY, mesh_signature
        from tools.femm_reference.rotor_matched_history import model_audit
        from tools.phase_g_loss.contract import phase_ampere_turns
        geometry = None
        if geometry_path.exists():
            with np.load(geometry_path) as data:
                geometry = {name: data[name] for name in data.files}
        for index in range(SAMPLES + 1):
            if index % shards != shard or checkpoint(directory, index):
                continue
            if args.prepare_only and index != 0:
                break
            output = directory / f"position-{index:04d}"
            output.mkdir(exist_ok=True)
            angle = -360 * index / (SAMPLES * pairs)
            phases = phase_ampere_turns(requested, angle)
            started = time.perf_counter()
            if outer:
                ir, _ = phase_f.rotated_ir(runtime_f, model, -angle * pairs)
                lowered = phase_f.lower_model(femm, runtime_f, model, ir, tuple(phases[p] / model.winding.turns_per_coil for p in "ABC"), steel)
                mark_outer_regions(femm, ir, lowered)
            else:
                femm.opendocument(str(base))
                femm.mi_modifyboundprop(BOUNDARY, 10, angle)
                for coil in prep["coils"]:
                    ni = phases[coil["phase"]] * coil["turn_fraction"] * (1 if coil["direction"] == "in" else -1)
                    femm.mi_modifymaterial(coil["name"], 4, ni / coil["area_mm2"])
            model_path = output / "model.fem"
            femm.mi_saveas(str(model_path))
            if not outer:
                applied = {c["name"]: {**c, "ampere_turns": phases[c["phase"]] * c["turn_fraction"] * (1 if c["direction"] == "in" else -1)}
                           for c in prep["coils"]}
                model_audit(model_path.read_text(encoding="latin-1"), angle, applied, {"remanence_T": 1.315, "relative_permeability": 1.05})
            femm.mi_createmesh()
            femm.mi_analyze(1)
            femm.mi_loadsolution()
            error = 0.0
            for coil in prep["coils"]:
                femm.mo_clearblock()
                femm.mo_selectblock(*coil["point"])
                target = phases[coil["phase"]] * coil["turn_fraction"] * (1 if coil["direction"] == "in" else -1)
                error = max(error, abs(complex(femm.mo_blockintegral(7)) - target))
            if error > 1e-8:
                raise ValueError("FEMM winding excitation differs")
            signature = mesh_signature(model_path.with_suffix(".ans"))
            if not outer and signature != prep["mesh_signature"]:
                raise ValueError("Fixed FEMM mesh changed")
            geometry = export_material(femm, output, geometry, False, fixed=not outer)
            if not geometry_path.exists():
                write_npz(geometry_path, **geometry)
            femm.mo_close()
            femm.mi_close()
            write(output / "position.json", {"index": index, "electrical_angle_deg": -360 * index / SAMPLES,
                  "mechanical_angle_deg": angle, "wall_s": time.perf_counter() - started,
                  "protocol_sha256": sha(directory / "protocol.json"), "geometry_sha256": sha(geometry_path),
                  "new_field_solve": True, "current_error_At": error, "mesh_signature": signature,
                  "sha256": {p.name: sha(p) for p in output.iterdir() if p.is_file() and p.name != "position.json"}})
            print(f"{args.case}: electrical pose {index}/{SAMPLES}", flush=True)
    finally:
        if automation is not None:
            automation.close()


if __name__ == "__main__":
    main()
