"""Compare coilEM's frozen 2005 Honda Accord request with ORNL's measurements (#92).

Runs on the frozen request docs/hardware-validation/honda-accord-2005/request.json, with the #91
tooth-coil winding emulated (see that folder's README):

    # 1. No-load back-EMF: one 360-degree electrical sweep at the request's 1000 rpm
    python tools/honda_accord_comparison.py no-load --out ../accord/no-load.json

    # 2. Locked rotor at ORNL's DC pattern (resumable; about 200 static solves)
    python tools/honda_accord_comparison.py locked-rotor --out ../accord/locked-rotor.json

    # 3. Assemble the comparison
    python tools/honda_accord_comparison.py assemble --no-load ../accord/no-load.json \\
        --locked ../accord/locked-rotor.json --out docs/hardware-validation/honda-accord-2005/first-comparison

Then tools/plot_honda_accord_comparison.py draws the charts. Nothing here is fitted.

The emulation: coilEM's concentrated map for 24s16p puts one phase in each slot, so the real tooth
coils are reached with i'A = (iA - iC)/2 going in and lA = (l'A - l'B)/2 coming out. ORNL's DC pattern
(Ia, -Ia/2, -Ia/2) is then coilEM current (0.75, -0.75, 0) Ia: amplitude (sqrt(3)/2) Ia at a 30-degree
current angle (source angle 90 - theta - gamma = 60 degrees at sweep position 0). The rotor is turned
with magnet_angle_deg.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "docs/hardware-validation/honda-accord-2005"
REQUEST = FOLDER / "request.json"
POLE_PAIRS = 8
CURRENTS_A = (25, 50, 75, 100, 125, 150, 175, 200, 225)
# delta = 0 is the no-torque position (ORNL's definition): coilEM's rotor offset of 240 degrees
# electrical, located on coilEM's own 100 A cycle (torque crosses zero rising there).
ZERO_OFFSET_ELEC_DEG = 240.0
PEAK_DELTAS_DEG = tuple(range(60, 151, 5))     # ORNL's 5-degree step, around the peak
LOBE_CURRENTS_A = (50, 125, 225)               # full 0-180 lobes for the magnet/reluctance split
LOBE_DELTAS_DEG = tuple(range(0, 181, 10))


def _git(*args: str) -> str | None:
    done = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)
    return done.stdout.strip() if done.returncode == 0 else None


def _identity() -> dict:
    return {"commit": _git("rev-parse", "HEAD"), "dirty": bool(_git("status", "--porcelain", "--untracked-files=no"))}


def _cache_root() -> Path:
    from backend.solve_workspace import user_data_root

    return Path(user_data_root()) / "solve_cache"


def tooth_coil(a: list[float], b: list[float]) -> list[float]:
    """Real tooth-coil quantity from two adjacent coilEM phases (#91): (A - B) / 2."""

    return [(x - y) / 2 for x, y in zip(a, b)]


def run_no_load(out: Path) -> None:
    from backend.public_policy import parse_public_motor_config
    from backend.solver import Magneto2DSolver

    body = json.loads(REQUEST.read_text(encoding="utf-8"))
    before = set(glob.glob(str(_cache_root() / "magneto2d-*")))
    Magneto2DSolver(launch_surface=True).solve(parse_public_motor_config(body))
    new = [d for d in glob.glob(str(_cache_root() / "magneto2d-*")) if d not in before]
    sweep = next(json.loads(Path(d, "sweep_report.json").read_text(encoding="utf-8"))["sweep"]
                 for d in new if Path(d, "sweep_report.json").exists())
    for d in new:
        shutil.rmtree(d, ignore_errors=True)
    ep = {k: sweep[f"no_load_back_emf_{k}_physical_v"] for k in "abc"}
    record = {
        "description": "coilEM no-load back-EMF of the frozen Accord request, re-paired to tooth coils (#91 emulated).",
        "run": _identity(), "solved_speed_rpm": body["solve_params"]["rated_speed_rpm"],
        "electrical_angle_deg": sweep["back_emf_rotor_positions_elec_deg"],
        "tooth_coil_back_emf_V": {"a": tooth_coil(ep["a"], ep["b"]), "b": tooth_coil(ep["b"], ep["c"]), "c": tooth_coil(ep["c"], ep["a"])},
        "coilem_slot_map_back_emf_V": ep,
        "cogging_torque_peak_Nm": sweep.get("cogging_torque_nm"),
    }
    out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")


def rotor_offset_mech_deg(delta_deg: float) -> float:
    period = 360.0 / POLE_PAIRS
    return (((ZERO_OFFSET_ELEC_DEG + delta_deg) / POLE_PAIRS) + period / 2) % period - period / 2


def locked_rotor_request(current_a: float, delta_deg: float) -> dict:
    body = json.loads(REQUEST.read_text(encoding="utf-8"))
    body["rotor"]["magnet_angle_deg"] = rotor_offset_mech_deg(delta_deg)
    body["solve_params"].update(current_amplitude_A=current_a * math.sqrt(3) / 2, current_angle_deg=30.0,
                                rotor_sweep_range_deg=1.0, rotor_step_deg=1.0)
    body["solve_options"].update(back_emf=False, flux_density=False, torque_sweep=True)
    return body


def locked_rotor_points() -> list[tuple[int, int]]:
    points = [(c, d) for c in CURRENTS_A for d in PEAK_DELTAS_DEG]
    points += [(c, d) for c in LOBE_CURRENTS_A for d in LOBE_DELTAS_DEG if (c, d) not in points]
    return points


def run_locked_rotor(out: Path) -> None:
    from backend.public_policy import parse_public_motor_config
    from backend.solver import Magneto2DSolver

    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    done = {(r["current_A"], r["delta_deg"]) for r in results}
    for current, delta in locked_rotor_points():
        if (current, delta) in done:
            continue
        before = set(glob.glob(str(_cache_root() / "magneto2d-*")))
        start = time.perf_counter()
        result = Magneto2DSolver(launch_surface=True).solve(parse_public_motor_config(locked_rotor_request(current, delta)))
        currents = None
        for d in (d for d in glob.glob(str(_cache_root() / "magneto2d-*")) if d not in before):
            report = Path(d, "sweep_pos000_loaded_report.json")
            if report.exists():
                currents = [round(x / current, 4) for x in json.loads(report.read_text(encoding="utf-8"))["results"]["phase_current_a"]]
            shutil.rmtree(d, ignore_errors=True)
        if currents is not None and [round(x, 3) for x in currents] != [0.75, -0.75, 0.0]:
            raise RuntimeError(f"coilEM currents {currents} x Ia are not the emulated ORNL pattern")
        results.append({"current_A": current, "delta_deg": delta, "torque_Nm": result.torque_waveform.torque_Nm[0],
                        "coilem_currents_per_Ia": currents, **{f"run_{k}": v for k, v in _identity().items()},
                        "solve_s": round(time.perf_counter() - start, 1)})
        out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"Ia={current} A delta={delta}: {results[-1]['torque_Nm']:+.2f} N m", flush=True)


def split_torque(deltas: list[float], torques: list[float], current: float) -> dict:
    """Least-squares T = a sin(delta) + b sin(2 delta): magnet term a = 1.5 p lambda I, reluctance term b."""

    import numpy as np

    d = np.radians(deltas)
    a, b = np.linalg.lstsq(np.c_[np.sin(d), np.sin(2 * d)], np.asarray(torques), rcond=None)[0]
    return {"current_A": current, "magnet_term_Nm": round(float(a), 2), "reluctance_term_Nm": round(float(b), 2),
            "lambda_pm_Wb": round(float(a) / (1.5 * POLE_PAIRS * current), 5),
            "lq_minus_ld_uH": round(-float(b) / (0.75 * POLE_PAIRS * current**2) * 1e6, 1)}


def assemble(no_load: dict, locked: list[dict], out: Path, write: bool = True) -> dict:
    import numpy as np

    back = json.loads((FOLDER / "target-back-emf.json").read_text(encoding="utf-8"))["rows"]
    lr = json.loads((FOLDER / "target-locked-rotor.json").read_text(encoding="utf-8"))["rows"]
    waves = no_load["tooth_coil_back_emf_V"]
    rms = float(np.mean([math.sqrt(sum(v * v for v in waves[k]) / len(waves[k])) for k in "abc"]))
    slot_map_rms = float(np.mean([math.sqrt(sum(v * v for v in w) / len(w)) for w in no_load["coilem_slot_map_back_emf_V"].values()]))
    rpm0 = no_load["solved_speed_rpm"]
    emf_rows = [{"motor_shaft_rpm": r["motor_shaft_rpm"], "measured_ln_rms_V": r["average_ln_rms_V"],
                 "predicted_ln_rms_V": round(rms * r["motor_shaft_rpm"] / rpm0, 3),
                 "error_pct": round((rms * r["motor_shaft_rpm"] / rpm0 / r["average_ln_rms_V"] - 1) * 100, 2)} for r in back]
    by: dict[int, dict[int, float]] = {}
    for r in locked:
        by.setdefault(int(r["current_A"]), {})[int(r["delta_deg"])] = r["torque_Nm"]
    peaks = []
    for t in lr:
        c = int(t["current_A"])
        d, tq = max(by[c].items(), key=lambda kv: kv[1])
        peaks.append({"current_A": c, "ornl_peak_Nm": t["peak_torque_Nm"], "coilem_peak_Nm": round(tq, 3), "coilem_peak_delta_deg": d,
                      "error_pct": round((tq / t["peak_torque_Nm"] - 1) * 100, 2)})
    lobes = {c: sorted((d, by[c][d]) for d in by[c] if d in LOBE_DELTAS_DEG or d in PEAK_DELTAS_DEG) for c in LOBE_CURRENTS_A}
    runs = sorted({(r.get("run_commit"), r.get("run_dirty")) for r in locked})
    data = {
        "description": ("coilEM's frozen 2005 Honda Accord request against ORNL's hardware measurements (#92). "
                        "Exploratory; no pass/fail. #91 emulated."),
        "request": REQUEST.relative_to(ROOT).as_posix(),
        "back_emf": {"source": "ORNL/TM-2006/535 Table 3.1 (line-to-neutral rms, three-phase average)", "run": no_load["run"],
                     "method": ["One 360-degree electrical no-load sweep at the request's speed, 2-degree steps.",
                                "Tooth-coil phase = (A - B)/2 of coilEM's slot-map phases (#91 emulated).",
                                "True rms over the cycle, averaged over the three phases; scaled linearly with speed."],
                     "solved_speed_rpm": rpm0, "tooth_coil_rms_V": round(rms, 3), "coilem_slot_map_rms_V": round(slot_map_rms, 3),
                     "rows": emf_rows, "error_pct": {"mean": round(float(np.mean([r["error_pct"] for r in emf_rows])), 2),
                                                     "min": min(r["error_pct"] for r in emf_rows), "max": max(r["error_pct"] for r in emf_rows)},
                     "cogging_torque_peak_Nm": no_load.get("cogging_torque_peak_Nm")},
        "locked_rotor": {"source": "ORNL/TM-2006/535 Table 3.2 (peak over rotor position); DC pattern (Ia, -Ia/2, -Ia/2) assumed (A5)",
                         "runs": [{"commit": c, "dirty": d} for c, d in runs],
                         "method": ["Static solves of the frozen request; only the excitation and the rotor angle change.",
                                    "coilEM currents (0.75, -0.75, 0) Ia = ORNL's pattern on the tooth coils (#91 emulated); checked on every solve.",
                                    "delta = 0 is the no-torque position (ORNL's definition), coilEM rotor offset 240 deg electrical.",
                                    "Peak over delta = 60..150 deg in ORNL's 5-degree steps; full lobes at 50, 125 and 225 A in 10-degree steps."],
                         "peak_by_current": peaks,
                         "error_pct": {"mean": round(float(np.mean([p["error_pct"] for p in peaks])), 2),
                                       "min": min(p["error_pct"] for p in peaks), "max": max(p["error_pct"] for p in peaks)},
                         "curves": {str(c): [{"delta_deg": d, "torque_Nm": round(t, 3)} for d, t in lobes[c]] for c in LOBE_CURRENTS_A},
                         "magnet_reluctance_split": [split_torque([d for d, _ in lobes[c] if d % 10 == 0],
                                                                  [t for d, t in lobes[c] if d % 10 == 0], c) for c in LOBE_CURRENTS_A]},
    }
    if write:
        out.mkdir(parents=True, exist_ok=True)
        (out / "comparison.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("no-load").add_argument("--out", type=Path, required=True)
    commands.add_parser("locked-rotor").add_argument("--out", type=Path, required=True)
    combine = commands.add_parser("assemble")
    combine.add_argument("--no-load", type=Path, required=True)
    combine.add_argument("--locked", type=Path, required=True)
    combine.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "no-load":
        run_no_load(args.out)
    elif args.command == "locked-rotor":
        run_locked_rotor(args.out)
    else:
        assemble(json.loads(args.no_load.read_text(encoding="utf-8")), json.loads(args.locked.read_text(encoding="utf-8")), args.out)


if __name__ == "__main__":
    main()
