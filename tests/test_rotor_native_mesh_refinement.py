"""Validation controls cannot leak into production defaults or omit provenance."""

import argparse
import sys

import pytest

from backend import gmsh_solver
from tools import rotor_native_mesh_refinement as refinement


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf"])
def test_nonphysical_mesh_size_is_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        refinement.positive_size(value)


@pytest.mark.parametrize("fail", [False, True])
def test_owned_override_records_identity_and_restores_defaults_on_exit(monkeypatch, fail):
    original_size = gmsh_solver._base_lc_mm
    original_argv = sys.argv
    def identity_source(binary):
        return {"source_sha256": {"backend/unchanged.py": "source-proof"}}
    monkeypatch.setattr(refinement.native, "source_identity", identity_source)

    def collect():
        assert gmsh_solver._base_lc_mm(None, "normal") == 0.94
        identity = refinement.native.source_identity(None)
        assert identity["validation_mesh_controls"]["base_lc_mm"] == 0.94
        assert len(identity["source_sha256"]["tools/rotor_native_mesh_refinement.py"]) == 64
        assert identity["source_sha256"]["backend/unchanged.py"] == "source-proof"
        assert sys.argv[-2:] == ["--motion", "fixed-material"]
        assert "--base-lc-mm" not in sys.argv
        if fail:
            raise RuntimeError("collection failed")

    monkeypatch.setattr(refinement.native, "main", collect)
    args = ["--base-lc-mm", "0.94", "--out", "owned-output", "--binary", "owned-binary"]
    if fail:
        with pytest.raises(RuntimeError, match="collection failed"):
            refinement.main(args)
    else:
        refinement.main(args)
    assert gmsh_solver._base_lc_mm is original_size
    assert refinement.native.source_identity is identity_source
    assert sys.argv is original_argv
