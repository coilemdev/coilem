"""Solve an experimental rotor family natively. Research only: not public support.

The application and the A/B/C/D benchmark reject these rotors. This tool applies
every public request check except the IPM rotor family, accepts only the
families in ``EXPERIMENTAL_IPM_TOPOLOGIES``, and labels its output experimental.
It is not reachable from the HTTP API. Results carry no qualification claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Any

NOTICE = "Experimental rotor path (#70): not public support and no qualification claim."
RESULT_FIELDS = {"summary", "torque_waveform", "back_emf_waveform", "phase_current_waveform", "solve_metadata"}
ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str | None:
    try:
        completed = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def solve(body: dict[str, Any]) -> dict[str, Any]:
    """Validate and solve one experimental-rotor design; return the labelled record."""

    from backend import __version__
    from backend.magneto2d_adapter import ensure_magneto2d_binary
    from backend.public_policy import EXPERIMENTAL_IPM_TOPOLOGIES, PublicConfigError, parse_public_motor_config
    from backend.solver import Magneto2DSolver

    if str(body.get("solver") or "magneto2d").strip().lower() not in {"auto", "magneto2d"}:
        raise PublicConfigError("Experimental rotors are solved with Magneto2D only.", field="solver")
    config = parse_public_motor_config(body, allow_experimental_rotors=True)
    family = str(config.rotor.ipm_topology or "") if config.topology == "IPM" else ""
    if family not in EXPERIMENTAL_IPM_TOPOLOGIES:
        raise PublicConfigError(
            "This tool solves experimental rotor families only; use coilEM or the benchmark runner for supported designs.",
            field="rotor.ipm_topology",
        )
    binary = ensure_magneto2d_binary()
    result = Magneto2DSolver(launch_surface=True).solve(config)
    return {
        "schema": "coilem.experimental_solve/v1",
        "experimental": True,
        "notice": NOTICE,
        "rotor_family": family,
        "application_version": __version__,
        "source_commit": _git("rev-parse", "HEAD"),
        "source_dirty": bool(_git("status", "--porcelain")),
        "magneto2d_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "runtime": {"os": platform.system(), "architecture": platform.machine(), "python": platform.python_version()},
        "request": body,
        "result": result.model_dump(mode="json", include=RESULT_FIELDS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="motor configuration JSON with an experimental rotor family")
    parser.add_argument("--output", required=True, type=Path, help="new JSON output file; existing files are never overwritten")
    parser.add_argument("--no-load", action="store_true", help="solve with zero phase current")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    if not args.output.parent.is_dir():
        parser.error("output parent directory does not exist")
    body = json.loads(args.config.read_text(encoding="utf-8"))
    if args.no_load:
        body.setdefault("solve_params", {})["current_amplitude_A"] = 0.0

    from backend.public_policy import PublicConfigError

    try:
        record = solve(body)
    except PublicConfigError as exc:
        parser.error(str(exc))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
        stream.write("\n")
    summary = record["result"]["summary"]
    print(f"{NOTICE}\nback-EMF fundamental {summary['back_emf_fundamental_V']:.4g} V, mean torque {summary['avg_torque_Nm']:.4g} N·m")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
