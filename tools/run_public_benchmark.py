"""Reproduce the public-native side of the M350-50A launch benchmark."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.material_contract import load_electrical_steel_curve
from backend.public_main import app


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _operating_points(config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    rated = copy.deepcopy(config)
    no_load = copy.deepcopy(config)
    no_load["solve_params"]["current_amplitude_A"] = 0.0
    saturation = copy.deepcopy(config)
    saturation["solve_params"]["current_amplitude_A"] = round(
        1.5 * float(config["solve_params"]["current_amplitude_A"]), 6
    )
    return [
        ("no_load", no_load),
        ("rated_load", rated),
        ("saturation_stress", saturation),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--row", action="append", help="run only this row id")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="use a one-position non-gating grid to validate the public pipeline",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    spec_path = root / "benchmarks" / "m350-launch" / "benchmark_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    selected = [
        row for row in spec["rows"] if not args.row or row["id"] in set(args.row)
    ]
    missing_ids = set(args.row or []) - {row["id"] for row in selected}
    if missing_ids:
        raise SystemExit("unknown benchmark row(s): " + ", ".join(sorted(missing_ids)))

    curve = load_electrical_steel_curve("M350-50A")
    if curve.sha256 != spec["material_contract"]["curve_sha256"]:
        raise SystemExit("M350-50A curve does not match the benchmark specification")

    out_dir = args.out_dir.resolve()
    manifest_path = out_dir / "candidate_manifest.json"
    if manifest_path.exists():
        raise SystemExit(f"refusing to overwrite existing manifest: {manifest_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    client = TestClient(app, base_url="http://127.0.0.1")
    rows: list[dict[str, Any]] = []

    for row in selected:
        fixture_path = root / row["fixture"]
        if _sha256(fixture_path) != row["fixture_sha256"]:
            raise SystemExit(f"fixture SHA-256 mismatch: {row['id']}")
        config = json.loads(fixture_path.read_text(encoding="utf-8"))
        if args.smoke:
            config["solve_params"].update(
                {
                    "solve_quality": "custom",
                    "rotor_sweep_range_deg": 30.0,
                    "rotor_step_deg": 30.0,
                    "mesh_density": "coarse",
                }
            )
            config["solve_options"].update(
                {"back_emf": False, "flux_density": False, "thd_analysis": False}
            )

        point_results: list[dict[str, Any]] = []
        row_dir = out_dir / "rows" / row["id"]
        row_dir.mkdir(parents=True, exist_ok=True)
        for point_id, point_config in _operating_points(config):
            response = client.post("/solve", json=point_config)
            response.raise_for_status()
            payload = response.json()
            result_path = row_dir / f"{point_id}.json"
            result_path.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
            point_results.append(
                {
                    "id": point_id,
                    "result": str(result_path.relative_to(out_dir)),
                    "result_sha256": _sha256(result_path),
                    "solver": (payload.get("solve_metadata") or {}).get("solver_name"),
                }
            )

        rows.append(
            {
                "id": row["id"],
                "status": "NON_GATING_SMOKE" if args.smoke else "CANDIDATE_COMPLETE",
                "fixture": row["fixture"],
                "fixture_sha256": row["fixture_sha256"],
                "material_key": spec["material_contract"]["material_key"],
                "curve_sha256": curve.sha256,
                "curve_source": spec["material_contract"]["source"]["model_url"],
                "magneto2d_version": spec["candidate_lane"]["magneto2d_version"],
                "mesh_source": spec["candidate_lane"]["mesh_source"],
                "points": point_results,
            }
        )

    manifest = {
        "schema_version": "coilem.m350_public_candidate_run/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "non_gating_smoke" if args.smoke else "launch_candidate",
        "commit": _commit(root),
        "platform": platform.platform(),
        "exact_command": shlex.join([sys.executable, *sys.argv]),
        "benchmark_spec_sha256": _sha256(spec_path),
        "femm_reference_mode": spec["reference_lane"]["reference_mode"],
        "reference_availability": "not_in_public_source",
        "rows": rows,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
