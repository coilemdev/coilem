"""Fresh Magneto2D material histories for Phase G; no FEMM imports."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import numpy as np

from tools.phase_g_loss.contract import (
    POSITIONS,
    ROOT,
    SUITE,
    canonical,
    case_by_id,
    checkpoint,
    config_for,
    enough_disk,
    phase_ampere_turns,
    protocol,
    read,
    sha,
    write,
    write_npz,
)


def material_fields(report, angle, rotor_supported):
    from backend.field_lines import generate_element_b_components
    from backend.iron_loss import FieldFrame
    from backend.rotor_iron_loss import sample_rotor_field

    plot = report["field_plot"]
    if plot["total_span_deg"] != 360:
        raise ValueError("Phase G needs full-machine fields")
    bx, by = generate_element_b_components(plot["nodes_mm"], plot["triangles"], plot["az_nodal"])
    frame = FieldFrame(np.asarray(plot["nodes_mm"]), np.asarray(plot["triangles"]), plot["regions"], np.asarray(bx), np.asarray(by))
    stator = frame.stator_sample()
    output = {"stator_corners": stator.corners_mm, "stator_b": np.column_stack((stator.bx_t, stator.by_t))}
    if rotor_supported:
        rotor = sample_rotor_field(frame, mechanical_angle_deg=angle, coordinate_frame="global")
        output.update(rotor_corners=rotor.corners_mm, rotor_b=np.column_stack((rotor.bx_t, rotor.by_t)))
    return output


def excitation(artifact, native, requested, angle):
    expected = phase_ampere_turns(requested, angle)
    from backend.geometry_drawer import compute_3phase_slot_ampere_turns_for_rotor_elec

    actual_phases = compute_3phase_slot_ampere_turns_for_rotor_elec(native, angle * native.rotor.pole_count / 2)
    if any(abs(actual_phases[k] - expected[k]) > 1e-8 for k in expected):
        raise ValueError("Native phase trajectory differs from independent Phase G sine")
    regions = []
    for region in artifact["physics_contract"]["regions"]:
        if region["kind"] != "SlotWinding":
            continue
        winding = region["winding"]
        target = expected[winding["phase"]] * winding["turn_fraction"] * (1 if winding["direction"] == "in" else -1)
        actual = winding["current_density_a_per_m2"] * winding["area_mm2"] * 1e-6
        if abs(target - actual) > max(1e-8, abs(target) * 1e-10):
            raise ValueError("Native winding turn share or current density differs")
        regions.append({"id": region["id"], **winding, "ampere_turns": actual})
    expected_count = requested["stator"]["slot_count"] * requested["winding"]["layers"]
    if len(regions) != expected_count:
        raise ValueError("Missing winding layers in native excitation audit")
    return {"phase_ampere_turns": expected, "windings": regions}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--shard", default="0/1")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    shard, shards = map(int, args.shard.split("/"))
    if not 0 <= shard < shards or args.limit is not None and args.limit < 1:
        parser.error("Invalid shard or limit")
    for key in tuple(os.environ):
        if key.startswith(("COILEM_", "MAGNETO2D_", "FEMM_", "GMSH_")):
            os.environ.pop(key)
    directory = args.out.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.environ["COILEM_MAGNETO2D_BINARY"] = str(args.binary.resolve())
    os.environ["COILEM_USER_DATA_ROOT"] = str(directory / f"user-{shard}")
    from dataclasses import asdict

    from backend.gmsh_solver import run_gmsh_mesh_preview
    from backend.iron_loss import M350_50A_LOSS, _locate
    from backend.magneto2d_adapter import run_magneto2d_report
    from backend.models import MotorConfig
    from backend.rotor_motion_mesh import FixedMaterialRotorMesh
    from backend.solver import _clockwise_excitation_config
    from backend.winding_resistance import winding_resistance
    from tools.rotor_native_pilot import source_identity, validate_convergence

    case = case_by_id(args.case)
    requested = config_for(case)
    config = _clockwise_excitation_config(MotorConfig.model_validate(requested))
    identity = source_identity(args.binary)
    for name in (
        "tools/phase_g_loss/contract.py",
        "tools/phase_g_loss/native.py",
        "backend/mesh_profiles/gmsh_profiles.json",
        "materials/electrical-steel/M350-50A.csv",
    ):
        identity["source_sha256"][name] = sha(ROOT / name)
    template_path = directory / "template.json"
    if not template_path.exists():
        if shards != 1 or (directory / "protocol.json").exists():
            raise ValueError("Bootstrap the zero pose before sharding")
        write(template_path, run_gmsh_mesh_preview(config, rotor_angle_deg=0)["solve_mesh_artifact"])
    template = read(template_path)
    motion = FixedMaterialRotorMesh(template, angular_divisions=case["native_airgap_divisions"], radial_layers=4) if case["rotor_supported"] else None
    resistance = winding_resistance(config).model_dump(mode="json")
    expected = {
        "schema": "coilem.phase_g_history/v1",
        "solver": "magneto2d",
        "case": case,
        "suite_sha256": sha(SUITE),
        "requested_config": requested,
        "native_config": config.model_dump(mode="json"),
        "positions": POSITIONS,
        "collection_speed_rpm": 3000,
        "evaluation_speeds_rpm": [1500, 3000],
        "identity": identity,
        "template_sha256": sha(template_path),
        "coefficients": asdict(M350_50A_LOSS),
        "winding_resistance": resistance,
        "material_frames": {"stator": "global_static", "rotor": "rotor_material"},
        "motion": "fixed-material" if motion else "direct full-motor remesh; stator-only queries",
        "rotor_status": "experimental" if case["rotor_supported"] else "unavailable",
        "rotor_unavailable_reason": None if motion else "Outrunner rotor material motion is not implemented.",
    }
    protocol(directory, expected)
    reference_path = directory / "material-geometry.npz"
    if reference_path.exists():
        with np.load(reference_path) as data:
            geometry = {key: data[key] for key in data.files}
    else:
        geometry = None
    new = 0
    for index in range(POSITIONS + 1):
        if index % shards != shard or checkpoint(directory, index):
            continue
        if args.limit is not None and new >= args.limit:
            break
        enough_disk(directory)
        angle = -360 * index / POSITIONS
        output = directory / f"position-{index:04d}"
        output.mkdir(exist_ok=True)
        started = time.perf_counter()
        artifact = motion.at_angle(config, angle) if motion else run_gmsh_mesh_preview(config, rotor_angle_deg=angle)["solve_mesh_artifact"]
        audited = excitation(artifact, config, requested, angle)
        report = run_magneto2d_report(config, sweep=False, rotor_angle_deg=angle, solve_mesh_artifact=artifact)
        convergence = report["solve_info"]["nonlinear_convergence"]
        validate_convergence(convergence, 1e-5)
        fields = material_fields(report, angle, case["rotor_supported"])
        if geometry is None:
            if shards != 1 or index != 0:
                raise ValueError("A fresh zero pose must establish material integration cells")
            geometry = {k: v for k, v in fields.items() if k.endswith("_corners")}
            write_npz(reference_path, **geometry)
        payload = {}
        mesh_hashes = {}
        for region in ("stator", "rotor") if case["rotor_supported"] else ("stator",):
            corners = fields[region + "_corners"]
            reference = geometry[region + "_corners"]
            mesh_hashes[region] = canonical(np.round(corners, 8).tolist())
            if corners.shape == reference.shape and np.allclose(corners, reference, rtol=0, atol=1e-7):
                payload[region] = fields[region + "_b"]
            else:
                if motion:
                    raise ValueError("Fixed material cells changed in their material frame")
                located = _locate(reference.mean(axis=1), corners)
                if np.any(located < 0):
                    raise ValueError("A stator material query left the stator domain")
                payload[region] = fields[region + "_b"][located]
        write_npz(output / "fields.npz", **payload)
        write(output / "excitation.json", audited)
        write(
            output / "position.json",
            {
                "index": index,
                "angle_deg": angle,
                "wall_s": time.perf_counter() - started,
                "nonlinear_convergence": convergence,
                "material_mesh_hashes": mesh_hashes,
                "geometry_sha256": sha(reference_path),
                "protocol_sha256": sha(directory / "protocol.json"),
                "sha256": {p.name: sha(p) for p in output.iterdir() if p.is_file() and p.name != "position.json"},
            },
        )
        print(f"{args.case}: {index}/{POSITIONS}", flush=True)
        new += 1


if __name__ == "__main__":
    main()
