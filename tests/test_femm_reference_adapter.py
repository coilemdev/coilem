"""Check the consolidated reference bundle without an installed FEMM solver."""
from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.femm_reference import __main__ as command
from tools.femm_reference import e_producer, f_producer, runtime

ROOT = Path(__file__).resolve().parents[1]


def test_imported_sources_and_original_physics_definitions_are_intact():
    manifest = runtime.verify_sources()
    for name, entry in manifest["files"].items():
        definitions = entry.get("definition_ast_sha256", {})
        if not definitions:
            continue
        tree = ast.parse((runtime.PACKAGE / name).read_text(encoding="utf-8"))
        nodes = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        for definition, expected in definitions.items():
            actual = runtime.ast_fingerprint(nodes[definition])
            assert actual == expected, (name, definition)


def test_source_verification_rejects_tampering(tmp_path):
    source = tmp_path / "model.py"
    source.write_bytes(b"preserved model")
    manifest = {"files": {"model.py": {"sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}}
    (tmp_path / "source-manifest.json").write_text(json.dumps(manifest))
    runtime.verify_sources(tmp_path)
    source.write_bytes(b"changed mesh")
    with pytest.raises(ValueError, match="source changed"):
        runtime.verify_sources(tmp_path)


def test_definition_fingerprint_ignores_empty_optional_ast_fields():
    complete = ast.arguments(posonlyargs=[], args=[ast.arg(arg="point")], kwonlyargs=[], kw_defaults=[], defaults=[])
    sparse = ast.arguments(args=[ast.arg(arg="point")])
    assert runtime.ast_fingerprint(complete) == runtime.ast_fingerprint(sparse)


def test_standard_selection_preserves_all_grids_and_controls():
    selection = runtime.read(runtime.DATA / "standard-selection.json")
    catalog = {**e_producer.cases(), **f_producer.cases()}
    assert len(selection) == 26
    assert sum(len(points) for points in selection.values()) == 1502
    assert sum(len(points) for alias, points in selection.items() if alias.startswith("e")) == 350
    for alias, selected in selection.items():
        positions = catalog[alias]["positions"]
        assert selected == [p["id"] for p in positions]
        if alias.startswith("e"):
            assert len(positions) == 25
            assert positions[0]["electrical_angle_deg"] == 0
        else:
            assert len(positions) == 96
            for stage in ("loaded", "noload"):
                assert [p["electrical_angle_deg"] for p in positions if p["stage"] == stage] == [i * 7.5 for i in range(48)]
    assert catalog["f09"]["request"]["bulk_mesh_mm"] == 0.5
    assert catalog["f10"]["request"]["airgap_mesh_scale"] == 0.5
    assert catalog["f11"]["request"]["airgap_mesh_scale"] == 0.5
    assert catalog["e01"]["mesh_scale"] == catalog["e13"]["mesh_scale"] == 0.5


def test_cli_filters_phase_without_populating_new_run_directory(tmp_path, monkeypatch):
    output = tmp_path / "new-run"
    captured = {}

    def execute(args):
        captured.update(runtime.read(args.selection))
        assert not output.exists()
        assert [p.name for p in args.producer] == ["f_producer.py"]
        assert args.prepare_only
        return 0

    monkeypatch.setattr(command.positions, "execute", execute)
    assert command.main(["--phases", "F", "--prepare-only", "--out-dir", str(output)]) == 0
    assert len(captured) == 12 and all(alias.startswith("f") for alias in captured)


def test_namespace_guard_does_not_replace_application_backend():
    script = """
import backend
from tools.femm_reference import runtime
original = backend
try:
    runtime.activate('f')
except RuntimeError:
    import backend
    assert backend is original
else:
    raise AssertionError('Application backend was replaced')
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_f_models_match_measured_preflight_from_relocated_source(tmp_path):
    # This checkout deliberately contains no .git, product backend, old output,
    # tmp, or external adapter directories. -I also removes PYTHONPATH/user site.
    checkout = tmp_path / "relocated"
    shutil.copytree(runtime.PACKAGE, checkout / "tools/femm_reference", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "tools/benchmark_suite", checkout / "tools/benchmark_suite", ignore=shutil.ignore_patterns("__pycache__"))
    script = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tools.femm_reference import f_producer, runtime
expected = json.loads(sys.argv[2])
for alias in f_producer.cases():
    prepared = f_producer.prepare(alias)
    assert prepared['preflight']['status'] == 'PASS'
    assert prepared['field_solves_executed'] == 0
    # These exact floating-point hashes were measured on Windows. Other hosts
    # still exercise the relocated bundle without assuming identical libm bits.
    if sys.platform == 'win32':
        actual = runtime.canonical(prepared)
        assert actual == expected[alias], (alias, actual, expected[alias])
    for name, module in tuple(sys.modules.items()):
        if name == 'backend' or name.startswith('backend.'):
            assert Path(module.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve()), name
print('12 F cases/controls: exact prepared model data; no COM sessions')
"""
    expected = runtime.read(ROOT / "tests/fixtures/femm_reference_preflight.json")["prepared_sha256"]
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(checkout), json.dumps(expected)],
                            cwd=checkout, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
