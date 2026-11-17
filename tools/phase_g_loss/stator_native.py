"""One electrical cycle through the production solve API, with rotor loss off."""
from __future__ import annotations

import argparse
import os
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from tools.phase_g_loss.contract import ROOT, protocol, read, sha, write, write_npz
from tools.phase_g_loss.stator_contract import PROFILE, config
from tools.phase_g_loss.stator_reproduction import measurement_protocol, reproduction


def validate_production_grid(payload, count):
    metadata = payload["solve_metadata"]
    angles = np.asarray(payload["torque_waveform"]["electrical_angle_deg"])
    if metadata["rotor_positions"] != count or metadata.get("sector_repeats"):
        raise ValueError("Production stator solve is not full-machine")
    if angles.shape != (count,) or not np.allclose(angles, np.arange(count) * 360 / count, rtol=0, atol=1e-9):
        raise ValueError("Production stator solve is not a complete uniform electrical cycle")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for key in tuple(os.environ):
        if key.startswith(("COILEM_", "MAGNETO2D_", "GMSH_", "FEMM_")):
            os.environ.pop(key)
    os.environ.update(COILEM_MAGNETO2D_BINARY=str(args.binary.resolve()),
                      COILEM_MAGNETO2D_PERSIST_RAW_ARTIFACTS="1", COILEM_MAGNETO2D_PERSIST_SUMMARY_ARTIFACTS="1",
                      COILEM_SOLVE_CACHE_MAX_BYTES=str(32 * 1024**3))
    from backend import field_artifacts
    from backend.field_lines import generate_element_b_components
    from backend.gmsh_solver import run_gmsh_mesh_preview
    from backend.iron_loss import M350_50A_LOSS, FieldFrame, estimate_iron_loss_and_density, stator_field_sample, stator_flux_history
    from backend.magneto2d_adapter import run_magneto2d_report
    from backend.models import MotorConfig
    from backend.solver import Magneto2DSolver, _clockwise_excitation_config
    from tools.rotor_native_pilot import source_identity, validate_convergence

    identity = source_identity(args.binary)
    for name in ("tools/phase_g_loss/stator_native.py", "tools/phase_g_loss/stator_contract.py",
                 "backend/mesh_profiles/gmsh_profiles.json", "materials/electrical-steel/M350-50A.csv"):
        identity["source_sha256"][name] = sha(ROOT / name)
    requested = config(args.case)
    native = _clockwise_excitation_config(MotorConfig.model_validate(requested))
    expected = {"schema": "coilem.stator_production_history/v1", "case_id": args.case,
                "profile_sha256": sha(PROFILE), "requested_config": requested,
                "native_config": native.model_dump(mode="json"), "identity": identity,
                "coefficients": asdict(M350_50A_LOSS), "electrical_samples": 96,
                "rotor_loss_requested": False}
    archive_sources = {name: sha(ROOT / name) for name in
                       ("tools/phase_g_loss/stator_native.py", "tools/phase_g_loss/stator_reproduction.py")}
    protocol(out, measurement_protocol(out, expected))
    if (out / "completed.json").exists():
        done = read(out / "completed.json")
        if any(sha(out / name) != digest for name, digest in done["sha256"].items()):
            raise ValueError("Completed stator production evidence changed")
        print(args.case + ": verified completed production history", flush=True)
        return

    def sample(report):
        plot = report["field_plot"]
        bx, by = generate_element_b_components(plot["nodes_mm"], plot["triangles"], plot["az_nodal"])
        frame = FieldFrame(np.asarray(plot["nodes_mm"]), np.asarray(plot["triangles"]), plot["regions"], np.asarray(bx), np.asarray(by))
        return frame.stator_sample()

    results, finest = {}, None
    for count in (24, 48, 96):
        os.environ["COILEM_USER_DATA_ROOT"] = str(out / ("runtime-" + str(count)))
        for speed in (3000, 1500):
            request = config(args.case, count, speed)
            path = out / f"result-{count}-{speed}.json"
            if path.exists():
                payload = read(path)
            else:
                model = MotorConfig.model_validate(request)
                started = time.perf_counter()
                def progress(position, total, torque, stage, angle=None, *rest):
                    if stage == "magneto2d_sweep" or position == total:
                        print(f"{args.case} N={count} rpm={speed}: {stage} {position}/{total}", flush=True)
                result = Magneto2DSolver(launch_surface=True).solve(model, on_progress=progress)
                payload = result.model_dump(mode="json")
                payload["benchmark_request"] = request
                payload["benchmark_elapsed_s"] = time.perf_counter() - started
                write(path, payload)
            if payload["benchmark_request"] != request:
                raise ValueError("Production request changed")
            metadata = payload["solve_metadata"]
            validate_production_grid(payload, count)
            if metadata.get("nonlinear_worst_tolerance_ratio") is None or metadata["nonlinear_worst_tolerance_ratio"] > 1:
                raise ValueError("Production field convergence is incomplete")
            if payload["summary"].get("rotor_iron_loss") is not None:
                raise ValueError("Rotor loss participated in a stator-only solve")
            if payload["summary"]["iron_loss"]["status"] == "unavailable":
                raise ValueError("Production stator loss unavailable")
            results[f"{count}-{speed}"] = {"file": path.name, "sha256": sha(path)}
            if count == 96 and speed == 3000:
                finest = payload
    cache = Path(finest["solve_metadata"]["solve_cache_dir"])
    samples, raw_index = [], {}
    for frame in finest["field_line_frames"]:
        ref = frame.get("full_field_frame_artifact") or frame["field_frame_artifact"]
        path = (cache.parent / ref["relative_path"]).resolve()
        if not path.is_relative_to(cache.resolve()):
            raise ValueError("Production field artifact left the declared solve cache")
        payload = field_artifacts.read_field_line_frame_artifact(path)["field_line_frame"]
        samples.append(stator_field_sample(payload))
        raw_index[str(path)] = sha(path)
    if len(samples) != 96 or any(sample is None for sample in samples):
        raise ValueError("Production field artifact coverage is incomplete")
    for path in cache.glob("sweep_pos*_loaded_report.json"):
        report = read(path)
        validate_convergence(report["solve_info"]["nonlinear_convergence"], 1e-5)
        raw_index[str(path)] = sha(path)
    reproduced, _ = estimate_iron_loss_and_density(MotorConfig.model_validate(requested), samples, np.arange(96) * 3.75)
    original = finest["summary"]["iron_loss"]
    receipt = reproduction(original, {key: getattr(reproduced, key) for key in
                                      ("iron_loss_W", "iron_hysteresis_loss_W", "iron_eddy_loss_W")})
    write(out / "field-reproduction.json", receipt)
    if not receipt["pass"]:
        raise ValueError("Serialized field archive exceeds its precision budget; see field-reproduction.json")
    history = stator_flux_history(samples)
    values = np.stack((history.bx_t, history.by_t), axis=-1)
    pairs = requested["rotor"]["pole_count"] // 2
    endpoint_angle = -360 / pairs
    template = run_gmsh_mesh_preview(native, rotor_angle_deg=0)["solve_mesh_artifact"]
    write(out / "template.json", template)
    artifact = run_gmsh_mesh_preview(native, rotor_angle_deg=endpoint_angle)["solve_mesh_artifact"]
    report = run_magneto2d_report(native, sweep=False, rotor_angle_deg=endpoint_angle, solve_mesh_artifact=artifact)
    validate_convergence(report["solve_info"]["nonlinear_convergence"], 1e-5)
    write(out / "endpoint-report.json", report)
    endpoint = stator_flux_history([samples[0], sample(report)])
    write_npz(out / "fields.npz", stator=values, endpoint=np.column_stack((endpoint.bx_t[1], endpoint.by_t[1])),
              area_m2=history.area_m2, stator_corners=samples[0].corners_mm)
    write(out / "result-index.json", {"results": results, "raw_field_sha256": raw_index})
    if sha(args.binary) != identity["binary_sha256"] or any(sha(ROOT / name) != digest for name, digest in identity["source_sha256"].items()):
        raise ValueError("Native source identity changed during measurement")
    if any(sha(ROOT / name) != digest for name, digest in archive_sources.items()):
        raise ValueError("Field archive processor changed during measurement")
    names = ["protocol.json", "template.json", "endpoint-report.json", "fields.npz", "result-index.json", "field-reproduction.json",
             *[r["file"] for r in results.values()]]
    write(out / "completed.json", {"schema": "coilem.stator_production_completed/v1", "archive_source_sha256": archive_sources,
                                  "sha256": {name: sha(out / name) for name in names}})


if __name__ == "__main__":
    main()
