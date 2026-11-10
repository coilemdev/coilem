"""Collect the preserved E/F reference matrix with batching and position resume."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.benchmark_suite import positions
from tools.femm_reference import runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phases", nargs="+", choices=("E", "F"), default=["E", "F"])
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--timeout-s", type=float, default=7200)
    parser.add_argument("--min-free-gib", type=float, default=20)
    parser.add_argument("--femm-bin", type=Path, help="Directory containing the separately installed FEMM 4.2 binaries")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="Validate every selected model without opening FEMM or solving fields")
    parser.add_argument("--verify-sources", action="store_true", help="Verify the source bundle without solver dependencies")
    parser.add_argument("--selection", type=Path, help="Explicit case-to-position selection; partial grids are non-gating pilots")
    parser.add_argument("--include-refinements", action="store_true", help="Include the three additional E refinement diagnostics")
    options = parser.parse_args(argv)
    if options.femm_bin:
        os.environ["COILEM_FEMM_BIN"] = str(options.femm_bin.resolve())
    try:
        manifest = runtime.verify_sources()
        if options.verify_sources:
            print(json.dumps({"status": "PASS", "verified_files": len(manifest["files"]), "field_solves_executed": 0}))
            return 0
        if options.out_dir is None:
            parser.error("--out-dir is required for collection or preparation")
        if options.selection and options.include_refinements:
            parser.error("Use --selection or --include-refinements")
        if not options.prepare_only:
            runtime.check_environment()
        with TemporaryDirectory(prefix="coilem-femm-selection-") as temporary:
            selection = options.selection
            if selection is None and not options.include_refinements:
                selected = json.loads((runtime.DATA / "standard-selection.json").read_text(encoding="utf-8"))
                selected = {alias: points for alias, points in selected.items() if alias[0].upper() in options.phases}
                # Only the content enters the immutable registration. A temporary
                # file leaves the output directory empty for the runner's lock.
                selection = Path(temporary) / "selection.json"
                selection.write_text(json.dumps(selected, indent=2) + "\n", encoding="utf-8")
            return positions.execute(
                argparse.Namespace(
                    producer=[runtime.PACKAGE / f"{phase.lower()}_producer.py" for phase in dict.fromkeys(options.phases)],
                    out_dir=options.out_dir,
                    selection=selection,
                    workers=options.workers,
                    batch_size=options.batch_size,
                    timeout_s=options.timeout_s,
                    min_free_gib=options.min_free_gib,
                    resume=options.resume,
                    prepare_only=options.prepare_only,
                    interrupt_after=None,
                )
            )
    except (ValueError, OSError) as exc:
        print(f"FEMM reference collection refused: {exc}")
        return 2
    except KeyboardInterrupt:
        print("Interrupted; position checkpoints retained. Repeat with --resume.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
