"""``coilem benchmark``: run A-F, retaining Phase E's experimental status.

It solves selected cases with the installed Magneto2D and each protocol's
frozen FEMM dataset. Recorded components are matched against platform records;
Phase E retains its experimental grades. It writes a shareable report and
needs no Git, Rust, Node.js or FEMM.
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path

from backend import __version__
from backend.benchmark_suite import PHASE_LABELS
from backend.benchmark_suite.cli import DEFAULT_MIN_FREE_GB, DiskFloorError, execute
from backend.benchmark_suite.collection import PUBLIC_PHASES, load_collection, run_collection
from backend.benchmark_suite.contract import read
from backend.benchmark_suite.record import check_physics, platform_key

# Preserve the historical A-D quick IDs; the collection adds one E and F case.
# Every quick case uses its full registered grid, unlike developer --smoke.
QUICK_CASES = (
    "spm_4p12s_simple__tight_airgap",
    "ipm_vshape_8p12s_thin_bridge_contract",
    "spm_8p24s_distributed_femm_validation",
    "spm_4p12s_small",
)
QUICK_PHASE_CASES = dict(zip("ABCD", QUICK_CASES, strict=True)) | {
    "E": "spm_4p12s_simple__baseline__cogging", "F": "spm_outer_14p12s_drone__baseline",
}
OPTIONS_FILE = "benchmark-options.json"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="coilem benchmark",
        description="Solve A-F using each protocol's own frozen FEMM dataset. Phase E cogging is experimental; "
        "its numerical grades remain visible and do not establish qualification.",
        epilog="Time varies with the selected cases and computer. Each case's solver files are deleted when it finishes.",
    )
    parser.add_argument("--phase", action="append", choices=list(PUBLIC_PHASES), help="run only this phase (A SPM, B IPM, "
                        "C distributed winding, D BLDC, E experimental cogging, F outrunner); repeat for several")
    parser.add_argument("--quick", action="store_true", help="run one registered case per selected phase")
    parser.add_argument("--out", type=Path, help="output folder (default: a new coilem-benchmark-<date>-<time> folder here)")
    parser.add_argument("--resume", action="store_true", help="continue a stopped run in --out with its original options")
    parser.add_argument("--report-only", action="store_true", help="rebuild reports from verified saved child runs in --out")
    parser.add_argument("--list", action="store_true", help="list the selected cases and expected times, then exit")
    parser.add_argument("--min-free-gb", type=float, default=None, metavar="GB",
                        help=f"stop below this free space (new-run default {DEFAULT_MIN_FREE_GB:g}); resumes keep the saved setting")
    parser.add_argument("--keep-runtime", action="store_true", default=None,
                        help="keep each case's solver files; this retention choice is preserved on resume")
    return parser


def select_cases(spec, phases, quick):
    return [case for case in spec["cases"] if case["phase"] in phases
            and (not quick or case["id"] == QUICK_PHASE_CASES.get(case["phase"]))]


def _minutes(seconds):
    return f"{max(1, round(seconds / 60))} min"


def recorded_status(record, case):
    return ((record or {}).get("cases", {}).get(case["id"]) or {}).get("status")


def estimate(record, cases):
    """Seconds the record's computer took for these cases; unsupported cases solve nothing."""

    if record is None:
        return None
    times = [record.get("case_runtime_s", {}).get(case["id"]) for case in cases if recorded_status(record, case) != "UNSUPPORTED"]
    return None if any(t is None for t in times) else sum(times)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.resume and args.report_only:
        parser.error("--resume and --report-only are mutually exclusive")
    if (args.resume or args.report_only) and args.out is None:
        mode = "--resume" if args.resume else "--report-only"
        parser.error(f"{mode} needs --out, the collection folder")
    output = (args.out or Path.cwd() / f"coilem-benchmark-{datetime.now():%Y%m%d-%H%M%S}").resolve()
    try:
        options_path = args.out / OPTIONS_FILE if args.out is not None else None
        if (args.resume or args.report_only) and options_path.is_file():
            options = read(options_path)
        else:
            options = {"phases": [phase for phase in PUBLIC_PHASES if phase in (args.phase or PUBLIC_PHASES)], "quick": args.quick}
        if (not isinstance(options, dict) or set(options) != {"phases", "quick"}
                or not isinstance(options["phases"], list) or type(options["quick"]) is not bool
                or options["phases"] != [phase for phase in PUBLIC_PHASES if phase in options["phases"]]):
            raise ValueError("Saved collection options are invalid")
        _, children, descriptor_sha256 = load_collection(options["phases"], quick=options["quick"])
        count = sum(len(child["cases"]) for child in children)
        estimates = [estimate(child["record"], child["cases"]) for child in children]
        expected = sum(estimates) if all(value is not None for value in estimates) else None
        if args.list:
            for child in children:
                for case in sorted(child["cases"], key=lambda case: PUBLIC_PHASES.index(case["phase"])):
                    seconds = (child["record"] or {}).get("case_runtime_s", {}).get(case["id"])
                    unsupported = recorded_status(child["record"], case) == "UNSUPPORTED"
                    note = "not supported in this release" if unsupported else _minutes(seconds) if seconds else ""
                    if child["component"]["experimental"]:
                        note = "; ".join(value for value in (note, "experimental") if value)
                    print(f"{case['phase']}  {PHASE_LABELS[case['phase']]:<20} {case['id']:<48} {note}")
            print(f"{count} cases" + (f", about {_minutes(expected)} on the record computers" if expected else ""))
            return 0
        print(f"coilEM {__version__} benchmark on {platform_key()}: {count} cases"
              + (" (quick subset)" if options["quick"] else "") + f", phases {' '.join(options['phases'])}.", flush=True)
        for child in children:
            label = " / ".join(child["component"]["phases"])
            if child["component"]["experimental"]:
                print(f"{label}: experimental; raw grades are reported without an accepted platform record.", flush=True)
            elif child["record"] is None:
                print(f"{label}: no comparable platform record is available.", flush=True)
            else:
                child["physics"] = check_physics(child["record"])
                origin = "closest " if child["cross_platform"] else ""
                print(f"{label}: matching the {origin}{child['record']['platform']} record at "
                      f"{child['record']['measured_commit'][:7]}; physics sources {child['physics']['status']}.", flush=True)
        print(f"Writing to {output}", flush=True)
        code, summary, comparison = run_collection(
            output, children, options, descriptor_sha256, execute_child=execute,
            resume=args.resume, report_only=args.report_only,
            min_free_gb=args.min_free_gb, keep_runtime=args.keep_runtime,
        )
    except DiskFloorError as exc:
        print(f"coilem benchmark stopped: {exc}\nContinue with: coilem benchmark --resume --out \"{output}\"")
        return 2
    except KeyboardInterrupt:
        print(f"\ncoilem benchmark stopped. Continue with: coilem benchmark --resume --out \"{output}\"")
        return 130
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"coilem benchmark refused: {exc}")
        return 2
    counts = ", ".join(f"{number} {status}" for status, number in sorted(summary["counts"].items()))
    print(f"\nRecorded outcomes: {summary['status']} ({counts}).")
    print(f"Record comparison: {comparison['status']}; Phase E remains experimental.")
    print(f"Shareable report: {output / 'share' / 'coilem-benchmark.md'}")
    print(f"Full report: {output / 'report' / 'coilem_benchmark_report.html'}")
    return code
