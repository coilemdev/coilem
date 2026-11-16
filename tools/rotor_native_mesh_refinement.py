"""Explicit mesh-size control for the internal fixed-material validation collector.

The production mesher and its defaults are unchanged. An owned validation
process temporarily supplies a base target when generating its authoritative
template, records the override and this driver in source identity, and then
uses the ordinary imported-mesh native solve at every pose.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from unittest.mock import patch

from backend import gmsh_solver
from tools import rotor_native_pilot as native


def positive_size(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("base mesh size must be finite and positive")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     epilog="Remaining options are those of tools.rotor_native_pilot.")
    parser.add_argument("--base-lc-mm", type=positive_size, required=True)
    parser.add_argument("--motion", choices=("fixed-material",), default="fixed-material")
    args, remaining = parser.parse_known_args(argv)
    original_identity = native.source_identity

    def identity(binary):
        record = original_identity(binary)
        source = Path(__file__).resolve()
        record["source_sha256"][source.relative_to(native.ROOT).as_posix()] = native.sha(source)
        record["validation_mesh_controls"] = {
            "method": "explicit_gmsh_template_base_lc/v1",
            "base_lc_mm": args.base_lc_mm,
            "scope": "validation template generation only; unchanged production mesher and native solve",
        }
        return record

    with (patch.object(gmsh_solver, "_base_lc_mm", return_value=args.base_lc_mm),
          patch.object(native, "source_identity", side_effect=identity),
          patch.object(sys, "argv", [__file__, *remaining, "--motion", "fixed-material"])):
        native.main()


if __name__ == "__main__":
    main()
