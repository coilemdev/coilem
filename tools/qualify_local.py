"""Collect one platform's qualification evidence on this machine, with no hosted runner.

Runs the same stages as ``release-benchmarks.yml`` for the platform it is run
on: build Magneto2D, record the binary, measure every shard in series, keep
the compact part of each, then join. The output folder has the layout of a
``benchmark-joined-<runner>`` artifact, so ``tools.qualification_carry``
accepts it as ``--macos`` or ``--windows``.

    python -m tools.qualify_local --candidate <full SHA> --directory ~/coilem-qualification

``--collection sentinel`` measures the covering subset of
``tools.qualification_sentinel`` instead: about a third of the work, for a change
that is expected to move no value. Use a separate directory for it.

The checkout must be clean at the candidate and the directory must be outside
it. A stopped run continues from the first unfinished shard. All shards of a
platform must come from one machine: the join rejects a mixed identity, so
this cannot fill in single shards beside hosted ones.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/release-benchmarks.yml"
# What the workflow keeps out of the compact shard artifact.
RAW_PATTERNS = ("native-runtime", "*.tar.gz", "*.tmp", "run.lock")


def rust_toolchain(root=ROOT):
    """The pinned toolchain the workflow builds with, so the two cannot drift."""
    match = re.search(r"cargo \+(\S+) build --release --locked", (root / WORKFLOW).read_text(encoding="utf-8"))
    if not match:
        raise ValueError("The benchmark workflow no longer names a pinned Rust toolchain")
    return match.group(1)


def free_gb(path):
    return shutil.disk_usage(path).free / 1e9


def command(*args, root=ROOT, env=None):
    subprocess.run([str(a) for a in args], cwd=root, env=env, check=True)


def check_candidate(candidate, directory, root=ROOT):
    if not re.fullmatch("[0-9a-f]{40}", candidate):
        raise ValueError("Need the full immutable candidate SHA")
    git = ["git", "-C", str(root)]
    head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    if head != candidate:
        raise ValueError(f"Checkout is at {head[:12]}, not the candidate {candidate[:12]}")
    if subprocess.check_output([*git, "status", "--porcelain"], text=True).strip():
        raise ValueError("Checkout has uncommitted changes; a measurement needs a clean candidate")
    if directory.resolve().is_relative_to(root.resolve()):
        raise ValueError("Keep the output directory outside the checkout")


def collect(candidate, directory, *, root=ROOT, min_free_gb=5.0, build=True, run=command, free=free_gb, shards=None,
            collection="registered"):
    """Build, measure every shard, compact and join. Returns the joined folder."""
    directory = directory.resolve()
    check_candidate(candidate, directory, root)
    directory.mkdir(parents=True, exist_ok=True)
    # Every stage reads the collection from the environment, as in the workflow.
    env = {**os.environ, "COILEM_BUILD_COMMIT": candidate, "COILEM_BENCHMARK_COLLECTION": collection}
    env.pop("COILEM_MAGNETO2D_BINARY", None)  # the standard solver path is part of the identity
    python = sys.executable
    binary, joined = directory / "binary", directory / "qualification"
    if (joined / "join-receipt.json").is_file():
        return joined
    if not (binary / "build-receipt.json").is_file():
        if build:
            run(python, "tools/verify_snapshot.py", "--publication", root=root, env=env)
            run("cargo", f"+{rust_toolchain(root)}", "build", "--release", "--locked",
                "--manifest-path", "solvers/magneto2d/Cargo.toml", root=root, env=env)
        run(python, "-m", "tools.benchmark_ci", "binary", "--directory", binary, root=root, env=env)
    if shards is None:
        shards = [s["id"] for s in json.loads((binary / "build-receipt.json").read_text(encoding="utf-8"))["plan"]["shards"]]
    timings = {}
    for shard in shards:
        compact = joined / "shards" / f"local-{shard}"
        if (compact / "workflow-receipt.json").is_file():
            print(f"{shard}: already collected", flush=True)
            continue
        available = free(directory)
        if available < min_free_gb:
            raise RuntimeError(f"Only {available:.1f} GB free before {shard}; free space and rerun to continue")
        work = directory / "collect" / shard
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        shutil.copyfile(binary / "build-receipt.json", work / "build-receipt.json")
        print(f"{shard}: collecting ({available:.1f} GB free)", flush=True)
        started = time.monotonic()
        run(python, "-m", "tools.benchmark_ci", "shard", "--shard", shard, "--directory", work, root=root, env=env)
        timings[shard] = round(time.monotonic() - started, 1)
        # Compact into a sibling first: an interrupted copy is never mistaken for a finished shard.
        staging = compact.with_name(compact.name + ".partial")
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(work / "out", staging, ignore=shutil.ignore_patterns(*RAW_PATTERNS))
        shutil.rmtree(compact, ignore_errors=True)
        staging.rename(compact)
        shutil.rmtree(work)
    shutil.rmtree(directory / "collect", ignore_errors=True)
    for name in ("joined-suite", "joined-prius", "prius-report"):  # left by an interrupted join
        shutil.rmtree(joined / name, ignore_errors=True)
    run(python, "-m", "tools.benchmark_ci", "join", "--directory", joined, root=root, env=env)
    (joined / "local-collection.json").write_text(json.dumps({
        "schema": "coilem.local_collection/v1", "candidate": candidate, "collector": "local", "collection": collection,
        "platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
        "shard_wall_time_s": timings, "raw_fields_retained": False,
        "note": "Collected in series on one machine with the release-benchmarks.yml commands; no hosted runner.",
    }, indent=2) + "\n", encoding="utf-8")
    return joined


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", required=True, help="Full SHA of the clean checkout being measured")
    parser.add_argument("--directory", required=True, type=Path, help="Output folder outside the checkout")
    parser.add_argument("--min-free-gb", type=float, default=5.0,
                        help="Stop before a shard when the output drive has less free space (default 5)")
    parser.add_argument("--skip-build", action="store_true",
                        help="Use the Magneto2D binary already built at the standard solver path")
    parser.add_argument("--collection", choices=["registered", "sentinel"], default="registered",
                        help="registered measures everything; sentinel measures the covering subset for a change "
                             "expected to move no value (default registered)")
    args = parser.parse_args(argv)
    try:
        joined = collect(args.candidate, args.directory.expanduser(), min_free_gb=args.min_free_gb, build=not args.skip_build,
                         collection=args.collection)
    except (ValueError, RuntimeError) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 2
    print(f"Joined collection: {joined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
