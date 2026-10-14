"""Compare coilEM's frozen Prius request with ORNL's hardware measurements (#82, #69).

Two steps, both on the frozen request benchmarks/abcd-v1.2/fixtures/ornl_prius_2004_ipm.json:

    # 1. Locked-rotor torque, reproducing ORNL's DC test (resumable; about 160 static solves)
    python tools/ornl_prius_comparison.py locked-rotor --out ../prius/locked-rotor.json

    # 2. Assemble the comparison from a protocol 1.2.0 benchmark run of the case and step 1
    python tools/ornl_prius_comparison.py assemble --run ../prius/run --locked ../prius/locked-rotor.json \\
        --out docs/hardware-validation/ornl-prius-2004/first-comparison

Then tools/plot_ornl_prius_comparison.py draws the charts. Nothing here is fitted:
the request is the frozen one, and the locked-rotor runs change only the
excitation and the rotor angle.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / "benchmarks/abcd-v1.2/fixtures/ornl_prius_2004_ipm.json"
FOLDER = ROOT / "docs/hardware-validation/ornl-prius-2004"
CURRENTS_A = (50, 75, 100, 125, 150, 200, 250)
DELTAS_DEG = tuple(range(0, 177, 8))
# ORNL holds the currents at (Ia, -Ia/2, -Ia/2) and turns the rotor. coilEM's source
# angle is rotor_elec - 90 + gamma with I_a = I sin(angle), so gamma = 180 at sweep
# position 0 gives exactly that set. The rotor is turned with magnet_angle_deg. Its
# zero (delta = 0: no torque, ORNL's definition) sits half a slot pitch, 15 deg
# electrical, from coilEM's rotor zero, measured on coilEM's own 50 A cycle; delta
# runs in the direction that puts the IPM torque peak beyond 90 deg (Lq > Ld).
ZERO_OFFSET_ELEC_DEG = 105.0


def rotor_offset_mech_deg(delta_deg: float, pole_pairs: int = 4) -> float:
    period = 360.0 / pole_pairs
    return (((ZERO_OFFSET_ELEC_DEG + delta_deg) / pole_pairs) + period / 2) % period - period / 2


def locked_rotor_request(current_a: float, delta_deg: float) -> dict:
    body = json.loads(REQUEST.read_text(encoding="utf-8"))
    body["rotor"]["magnet_angle_deg"] = rotor_offset_mech_deg(delta_deg)
    body["solve_params"].update(current_amplitude_A=float(current_a), current_angle_deg=180.0, rotor_sweep_range_deg=1.0, rotor_step_deg=1.0)
    body["solve_options"].update(back_emf=False, flux_density=False, torque_sweep=True)
    return body


def run_locked_rotor(out: Path, currents, deltas) -> None:
    from tools import experimental_solve

    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    done = {(r["current_A"], r["delta_deg"]) for r in results}
    for current in currents:
        for delta in deltas:
            if (current, delta) in done:
                continue
            start = time.perf_counter()
            record = experimental_solve.solve(locked_rotor_request(current, delta))
            results.append({
                "current_A": current,
                "delta_deg": delta,
                "torque_Nm": record["result"]["torque_waveform"]["torque_Nm"][0],
                "source_commit": record["source_commit"],
                "source_dirty": record["source_dirty"],
                "solve_s": round(time.perf_counter() - start, 1),
            })
            out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8", newline="\n")
            print(f"I={current} A delta={delta}: {results[-1]['torque_Nm']:+.2f} N m", flush=True)


def split_torque(rows: list[dict], current: int, pole_pairs: int = 4) -> dict:
    """Least-squares T = a sin(delta) + b sin(2 delta) for ORNL and coilEM at one current.

    a is the magnet torque, 1.5 p lambda_pm I; b is the reluctance torque,
    1.5 p (Ld - Lq) I^2 / 2. A diagnostic of which part differs; nothing is fitted
    back into the model.
    """

    import numpy as np

    delta = np.radians([r["delta_deg"] for r in rows])
    basis = np.c_[np.sin(delta), np.sin(2 * delta)]
    out = {"current_A": current}
    for source in ("ornl", "coilem"):
        a, b = np.linalg.lstsq(basis, np.array([r[f"{source}_Nm"][str(current)] for r in rows]), rcond=None)[0]
        out[source] = {
            "magnet_term_Nm": round(float(a), 2),
            "reluctance_term_Nm": round(float(b), 2),
            "lambda_pm_Wb": round(float(a) / (1.5 * pole_pairs * current), 4),
            "lq_minus_ld_mH": round(-float(b) / (0.75 * pole_pairs * current**2) * 1e3, 3),
        }
    out["magnet_term_error_pct"] = round((out["coilem"]["magnet_term_Nm"] / out["ornl"]["magnet_term_Nm"] - 1) * 100, 1)
    out["reluctance_term_error_pct"] = round((out["coilem"]["reluctance_term_Nm"] / out["ornl"]["reluctance_term_Nm"] - 1) * 100, 1)
    return out


def assemble(run: Path, locked: list[dict], out: Path) -> dict:
    summary = json.loads((run / "report/benchmark_summary.json").read_text(encoding="utf-8"))
    row = next(r for r in summary["rows"] if r["id"] == "ornl_prius_2004_ipm")
    identity = summary["run"]["identity"]
    targets = json.loads((FOLDER / "target-locked-rotor.json").read_text(encoding="utf-8"))["rows"]
    by_point = {(int(r["current_A"]), int(r["delta_deg"])): r["torque_Nm"] for r in locked}
    currents = sorted({int(r["current_A"]) for r in locked})
    rows = [
        {
            "delta_deg": t["electrical_position_deg_S3"],
            "ornl_Nm": {str(c): t[f"torque_Nm_{c}A"] for c in currents},
            "coilem_Nm": {str(c): by_point[c, t["electrical_position_deg_S3"]] for c in currents},
        }
        for t in targets
    ]
    peaks = []
    for c in currents:
        ornl, coilem = max(r["ornl_Nm"][str(c)] for r in rows), max(r["coilem_Nm"][str(c)] for r in rows)
        peaks.append({"current_A": c, "ornl_peak_Nm": ornl, "coilem_peak_Nm": coilem, "error_pct": (coilem / ornl - 1) * 100})
    commits = {(r.get("source_commit"), r.get("source_dirty")) for r in locked}
    split = [split_torque(rows, c) for c in currents]
    data = {
        "description": "coilEM's frozen 2004 Prius request against ORNL's hardware measurements. Exploratory; no pass/fail.",
        "request": REQUEST.relative_to(ROOT).as_posix(),
        "back_emf": {
            "source": row["hardware_comparison"]["reference"]["label"],
            "benchmark_run": {"commit": identity["commit"], "dirty": identity["dirty"], "harness": identity["harness_version"],
                              "protocol": identity["protocol_version"]},
            "conversion": row["hardware_comparison"]["conversion"],
            "rows": row["hardware_comparison"]["rows"],
            "rms_error_pct": row["hardware_comparison"]["rms_error_pct"],
            "peak_error_pct": row["hardware_comparison"]["peak_error_pct"],
        },
        "locked_rotor": {
            "source": "ORNL/TM-2006/423 Table 3.2 (S3 electrical positions); DC excitation Ia, -Ia/2, -Ia/2",
            "runs": [{"commit": c, "dirty": d} for c, d in sorted(commits)],
            "method": [
                "Static solves of the frozen request with only the excitation and rotor angle changed.",
                "Currents (Ia, -Ia/2, -Ia/2): current angle 180 deg at sweep position 0.",
                "delta = 0 is the no-torque position, as ORNL defines it, measured on coilEM's own 50 A cycle.",
                "Torque by weighted stress; motor-shaft torque, as ORNL's table reports it.",
            ],
            "currents_A": currents,
            "rows": rows,
            "peak_by_current": peaks,
            "magnet_reluctance_split": split,
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "comparison.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    locked = commands.add_parser("locked-rotor")
    locked.add_argument("--out", type=Path, required=True)
    locked.add_argument("--currents", type=float, nargs="+", default=CURRENTS_A)
    combine = commands.add_parser("assemble")
    combine.add_argument("--run", type=Path, required=True)
    combine.add_argument("--locked", type=Path, required=True)
    combine.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "locked-rotor":
        run_locked_rotor(args.out, args.currents, DELTAS_DEG)
    else:
        assemble(args.run, json.loads(args.locked.read_text(encoding="utf-8")), args.out)


if __name__ == "__main__":
    main()
