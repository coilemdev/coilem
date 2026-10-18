"""``coilem benchmark``: run the registered A/B/C/D suite on this installation (#71).

It solves every selected case with the installed Magneto2D, grades it against
the frozen FEMM reference that ships with coilEM, matches the outcome against
the published record for this platform, and writes a shareable report. It
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
from backend.benchmark_suite.contract import DEFAULT_BUNDLE, SPEC, read, write
from backend.benchmark_suite.record import check_physics, compare_run, load_records, platform_key, select_record
from backend.benchmark_suite.references import load_suite
from backend.benchmark_suite.share import match_sentence, tolerance_text, write_share_report

# One short case per phase, about 5 minutes in all. Still graded against the
# reference and matched against the record, unlike the developer --smoke grid.
QUICK_CASES = (
    "spm_4p12s_simple__tight_airgap",
    "ipm_vshape_8p12s_thin_bridge_contract",
    "spm_8p24s_distributed_femm_validation",
    "spm_4p12s_small",
)
OPTIONS_FILE = "benchmark-options.json"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="coilem benchmark",
        description="Solve the published A/B/C/D benchmark on this computer, grade it against the frozen FEMM "
        "reference, and check it matches the published record for this platform.",
        epilog="A full run takes about 50 minutes and needs about 3 GB of free disk space; each case's solver files "
        "are deleted when it finishes.",
    )
    parser.add_argument("--phase", action="append", choices=list(PHASE_LABELS), help="run only this phase (A SPM, B IPM, "
                        "C distributed winding, D BLDC); repeat for several")
    parser.add_argument("--quick", action="store_true", help="run one short case per phase, about 5 minutes")
    parser.add_argument("--out", type=Path, help="output folder (default: a new coilem-benchmark-<date>-<time> folder here)")
    parser.add_argument("--resume", action="store_true", help="continue a stopped run in --out with its original options")
    parser.add_argument("--list", action="store_true", help="list the selected cases and expected times, then exit")
    parser.add_argument("--min-free-gb", type=float, default=DEFAULT_MIN_FREE_GB, metavar="GB",
                        help=f"stop before a case when the output drive has less free space (default {DEFAULT_MIN_FREE_GB:g})")
    parser.add_argument("--keep-runtime", action="store_true", help="keep each case's solver files instead of deleting them")
    return parser


def select_cases(spec, phases, quick):
    return [case for case in spec["cases"] if case["phase"] in phases and (not quick or case["id"] in QUICK_CASES)]


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
    if args.resume and args.out is None:
        parser.error("--resume needs --out, the folder of the run to continue")
    options_path = args.out / OPTIONS_FILE if args.out is not None else None
    if args.resume and options_path.is_file():
        options = read(options_path)
    else:
        options = {"phases": [p for p in PHASE_LABELS if p in (args.phase or PHASE_LABELS)], "quick": args.quick}
    phases, quick = options["phases"], options["quick"]
    spec = load_suite(SPEC)
    cases = select_cases(spec, phases, quick)
    record, cross_platform = select_record(load_records())
    expected = estimate(record, cases)

    if args.list:
        for case in cases:
            seconds = (record or {}).get("case_runtime_s", {}).get(case["id"])
            note = "not supported in this release" if recorded_status(record, case) == "UNSUPPORTED" else _minutes(seconds) if seconds else ""
            print(f"{case['phase']}  {PHASE_LABELS[case['phase']]:<20} {case['id']:<48} {note}")
        print(f"{len(cases)} cases" + (f", about {_minutes(expected)} on the computer that made the record" if expected else ""))
        return 0

    output = (args.out or Path.cwd() / f"coilem-benchmark-{datetime.now():%Y%m%d-%H%M%S}").resolve()
    print(f"coilEM {__version__} benchmark on {platform_key()}: {len(cases)} cases"
          + (" (quick subset)" if quick else "") + f", phases {' '.join(phases)}.", flush=True)
    if expected:
        print(f"Expect about {_minutes(expected)}; the record's computer took that long.", flush=True)
    physics = None
    if record is None:
        print(f"No published record for {platform_key()}: verdicts will be shown but not matched.", flush=True)
    else:
        physics = check_physics(record)
        origin = "closest " if cross_platform else ""
        print(f"Matching against the {origin}{record['platform']} record measured at {record['measured_commit'][:7]}; "
              f"physics sources {physics['status']}.", flush=True)
    print(f"Writing to {output}", flush=True)
    if not args.resume and not (output / "run_manifest.json").exists():
        write(output / OPTIONS_FILE, options)

    namespace = argparse.Namespace(
        phases=phases, case=[case["id"] for case in cases] if quick else None, suite=SPEC, reference_bundle=DEFAULT_BUNDLE,
        out_dir=output, list=False, resume=args.resume, report_only=False, no_reference=False, smoke=False,
        allow_dirty=True, pdf=False, min_free_gb=args.min_free_gb, keep_runtime=args.keep_runtime,
    )
    resume_hint = f"coilem benchmark --resume --out \"{output}\""
    try:
        code = execute(namespace)
    except DiskFloorError as exc:
        print(f"coilem benchmark stopped: {exc}\nContinue with: {resume_hint}")
        return 2
    except KeyboardInterrupt:
        print(f"\ncoilem benchmark stopped. Continue with: {resume_hint}")
        return 130
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"coilem benchmark refused: {exc}")
        return 2

    summary = read(output / "report" / "benchmark_summary.json")
    comparison = compare_run(summary["rows"], record, cross_platform=cross_platform, physics=physics)
    share = write_share_report(output, summary, comparison, selection={**options, "case_ids": [c["id"] for c in cases]})
    counts = ", ".join(f"{count} {status}" for status, count in sorted(summary["counts"].items()))
    print(f"\nOutcome: {summary['status']} ({counts}).")
    print(match_sentence(comparison))
    for case_id, case in comparison.get("cases", {}).items():
        if not case["match"]:
            print(f"  {case_id}: {'; '.join(case['differences'])}")
    if comparison["status"] != "NO_RECORD":
        print(f"Match policy: {tolerance_text()}.")
    print(f"Shareable report (no local paths): {share}")
    print(f"Full report: {output / 'report' / 'coilem_benchmark_report.html'}")
    if code:
        return code
    return 1 if comparison["status"] in ("DIFFERS", "NOT_COMPARABLE") else 0
