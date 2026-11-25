"""Collect Phase G rotor references in FEMM, several workers per history, then write the records.

    python -m tools.phase_g_femm run --out D:/coilem-phase-g-femm --workers 4
    python -m tools.phase_g_femm run --out D:/coilem-phase-g-femm --workers 4 --history inner_spm_loaded
    python -m tools.phase_g_femm status --out D:/coilem-phase-g-femm

`run` prepares each history and solves its first pose alone, then splits the other poses across
the workers, and writes the reference record when a history is complete. It continues where it
stopped: finished poses are kept. Add `--femm5` to run on FEMM 5 (macOS/Linux) instead; the
record then names FEMM 5 as its solver.
See tools/phase_g_femm/README.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from tools.phase_g_femm.contract import POSITIONS, history_ids


def done(out: Path, history_id: str) -> int:
    directory = out / history_id
    return sum(1 for index in range(POSITIONS + 1) if (directory / f"position-{index:04d}" / "position.json").exists())


def collector(history_id: str, out: Path, shard: str, femm5: float | None, extra: list[str]) -> list[str]:
    """One collector process; `femm5` is FEMM 5's minimum mesh angle, or None for Windows FEMM 4.2."""
    module = ["-m", "tools.phase_g_femm.collect", "--history", history_id, "--out", str(out), "--shard", shard, *extra]
    if femm5 is None:
        return [sys.executable, *module]
    return [sys.executable, "-m", "tools.phase_g_femm.femm5_run", "--min-angle", str(femm5), *module]


def run(args) -> int:
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    extra = ["--min-free-gb", str(args.min_free_gb)] + (["--keep-answers"] if args.keep_answers else [])
    for history_id in args.history or history_ids():
        started = time.time()
        if done(out, history_id) == 0:
            print(f"{history_id}: preparing and solving the first pose", flush=True)
            subprocess.run(collector(history_id, out, "0/1", args.femm5, [*extra, "--limit", "1"]), check=True)
        if done(out, history_id) < POSITIONS + 1:
            print(f"{history_id}: {POSITIONS + 1 - done(out, history_id)} poses on {args.workers} workers", flush=True)
            workers = [subprocess.Popen(collector(history_id, out, f"{shard}/{args.workers}", args.femm5, extra)) for shard in range(args.workers)]
            failed = [worker.args for worker in workers if worker.wait() != 0]
            if failed:
                print(f"{history_id}: {len(failed)} worker(s) stopped; run the same command again to continue", flush=True)
                return 1
        print(f"{history_id}: complete in {time.time() - started:.0f} s", flush=True)
        subprocess.run([sys.executable, "-m", "tools.phase_g_femm.report", "--out", str(out), "--history", history_id], check=True)
    return 0


def status(args) -> int:
    out = args.out.resolve()
    for history_id in history_ids():
        print(f"{history_id}: {done(out, history_id)}/{POSITIONS + 1} poses")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="Collect histories and write their reference records")
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--workers", type=int, default=4)
    run_parser.add_argument("--history", action="append", help="Only these histories (repeatable); default all eight")
    run_parser.add_argument("--femm5", nargs="?", type=float, const=33.0, default=None, metavar="MIN_ANGLE",
                            help="Run on FEMM 5 (macOS/Linux) instead of Windows FEMM 4.2, meshing at this minimum angle "
                                 "(default 33 degrees, which gives about FEMM 4.2's element counts)")
    run_parser.add_argument("--keep-answers", action="store_true")
    run_parser.add_argument("--min-free-gb", type=float, default=6.0)
    status_parser = commands.add_parser("status", help="Poses finished per history")
    status_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run" and args.workers < 1:
        parser.error("--workers must be at least 1")
    return run(args) if args.command == "run" else status(args)


if __name__ == "__main__":
    raise SystemExit(main())
