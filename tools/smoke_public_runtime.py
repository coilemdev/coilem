"""Run real native-mesh and launch-safe solve checks from the candidate."""

from __future__ import annotations

import argparse
import json
import time
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from backend.public_main import app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh-only", action="store_true")
    parser.add_argument("--corner-refinement", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "tests" / "fixtures" / "spm_4p12s_simple.json").read_text(encoding="utf-8"))
    config["solve_params"].update(
        {
            "solve_quality": "custom",
            "rotor_sweep_range_deg": 30,
            "rotor_step_deg": 30,
            "mesh_density": "coarse",
            "mesh_source": "native",
            "mesher": "gmsh",
            "corner_refinement": args.corner_refinement,
        }
    )
    config["solve_options"] = {
        "torque_sweep": True,
        "back_emf": False,
        "flux_density": False,
        "cogging_torque": False,
        "torque_speed_envelope": False,
        "thd_analysis": False,
    }
    # Keep one ASGI portal alive for the full sequence. A bare TestClient used
    # without its context manager tears down the event loop (and its native
    # worker state) after every request, which is not how the long-lived local
    # backend runs in production.
    client = TestClient(app, base_url="http://127.0.0.1")
    client.__enter__()

    started = time.perf_counter()
    mesh = client.post("/solver/mesh-preview", json=config)
    mesh.raise_for_status()
    mesh_payload = mesh.json()
    refinement_applied = bool(mesh_payload["mesh_info"].get("corner_refinement"))
    if refinement_applied is not args.corner_refinement:
        raise SystemExit("mesh response did not apply the requested corner-refinement setting")
    print(
        json.dumps(
            {
                "mesh_status": mesh.status_code,
                "triangles": len(mesh_payload["triangles"]),
                "corner_refinement": refinement_applied,
                "elapsed_s": round(time.perf_counter() - started, 3),
            }
        )
    )
    if args.mesh_only:
        motor_solve_skipped = True
    else:
        motor_solve_skipped = False

    if not motor_solve_skipped:
        started = time.perf_counter()
        solve = client.post("/solve", json=config)
        solve.raise_for_status()
        payload = solve.json()
        serialized = json.dumps(payload).lower()
        if "femm" in serialized or "thermal" in serialized:
            raise SystemExit("public solve payload contains excluded launch terms")
        print(
            json.dumps(
                {
                    "solve_status": solve.status_code,
                    "solver": payload.get("solve_metadata", {}).get("solver_name"),
                    "elapsed_s": round(time.perf_counter() - started, 3),
                }
            )
        )

        six_step_config = deepcopy(config)
        six_step_config["solve_params"].update(
            {
                "excitation_mode": "ideal_six_step_120",
                "current_amplitude_convention": "plateau",
                "commutation_advance_deg": 0.0,
                "phase_connection": "wye",
                "rotor_sweep_range_deg": 360,
                "rotor_step_deg": 30,
            }
        )
        started = time.perf_counter()
        six_step = client.post("/solve", json=six_step_config)
        if not six_step.is_success:
            raise SystemExit(f"six-step public solve rejected: {six_step.text}")
        six_step_payload = six_step.json()
        current_waveform = six_step_payload.get("phase_current_waveform") or {}
        metadata = six_step_payload.get("solve_metadata") or {}
        if metadata.get("excitation_mode") != "ideal_six_step_120":
            raise SystemExit("public six-step solve lost its excitation identity")
        if len(current_waveform.get("electrical_angle_deg") or []) != 12:
            raise SystemExit("public six-step solve did not return its full-cycle current grid")
        print(
            json.dumps(
                {
                    "six_step_status": six_step.status_code,
                    "six_step_positions": len(current_waveform["electrical_angle_deg"]),
                    "six_step_cycle_complete": metadata.get("loaded_cycle_complete"),
                    "elapsed_s": round(time.perf_counter() - started, 3),
                }
            )
        )

    halbach = json.loads(
        (
            root
            / "schemas"
            / "v1"
            / "examples"
            / "halbach_array_16_segment.json"
        ).read_text(encoding="utf-8")
    )
    halbach["solve"]["quality"] = "quick"
    halbach["sample_region"]["radial_samples"] = 5
    halbach["sample_region"]["angular_samples"] = 16

    started = time.perf_counter()
    halbach_preview = client.post("/halbach/preview", json=halbach)
    halbach_preview.raise_for_status()
    halbach_mesh = client.post("/halbach/mesh-preview", json=halbach)
    halbach_mesh.raise_for_status()
    halbach_mesh_payload = halbach_mesh.json()
    print(
        json.dumps(
            {
                "halbach_preview_status": halbach_preview.status_code,
                "halbach_mesh_status": halbach_mesh.status_code,
                "halbach_triangles": len(halbach_mesh_payload["triangles"]),
                "problem_sha256": halbach_mesh_payload[
                    "magnetostatic_problem_sha256"
                ],
                "elapsed_s": round(time.perf_counter() - started, 3),
            }
        )
    )
    if args.mesh_only:
        client.__exit__(None, None, None)
        return 0

    started = time.perf_counter()
    halbach_solve = client.post("/halbach/solve", json=halbach)
    halbach_solve.raise_for_status()
    halbach_report = halbach_solve.json()
    if halbach_report.get("openem_schema_kind") != "halbach_solution_report":
        raise SystemExit("Halbach solve did not return its versioned report")
    if halbach_report.get("model", {}).get("axial_end_effects_modeled") is not False:
        raise SystemExit("Halbach report lost the finite-length model boundary")
    forbidden_motor_keys = {"torque", "winding", "rpm", "back_emf"}
    if forbidden_motor_keys & set(halbach_report):
        raise SystemExit("Halbach report contains motor-only policy")
    export = client.post("/halbach/export/pdf", json={"report": halbach_report})
    export.raise_for_status()
    if not export.content.startswith(b"%PDF"):
        raise SystemExit("Halbach PDF export is not a PDF")
    print(
        json.dumps(
            {
                "halbach_solve_status": halbach_solve.status_code,
                "mean_bore_field_t": halbach_report["bore_field"][
                    "b_parallel_t"
                ]["mean"],
                "direction_error_deg": halbach_report["bore_field"][
                    "mean_field_direction_error_deg"
                ],
                "pdf_bytes": len(export.content),
                "elapsed_s": round(time.perf_counter() - started, 3),
            }
        )
    )
    client.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
