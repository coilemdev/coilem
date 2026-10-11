"""Runtime files in an installed package: layout, resolution order and build identity."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from backend import magneto2d_adapter as adapter
from backend import resources
from backend.material_contract import M350_50A_SPEC, load_electrical_steel_curve

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = {entry["path"]: entry for entry in json.loads((REPO_ROOT / "snapshot-manifest.json").read_text())["files"]}


def test_packaged_files_cover_every_runtime_schema_and_the_frozen_curve() -> None:
    schemas = {f"schemas/v1/{path.name}" for path in (REPO_ROOT / "schemas" / "v1").glob("*.json")}
    assert set(resources.PACKAGED_DATA_FILES) == schemas | {M350_50A_SPEC.relative_path}
    assert M350_50A_SPEC.sha256 == MANIFEST[M350_50A_SPEC.relative_path]["sha256"]
    assert M350_50A_SPEC.sha256 == "d6096df7cc7103e8b9fc77407b1750e8ddf9f5d0cd1fdf8ad748d9febf896c3d"
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    for relative in resources.PACKAGE_DATA_FILES:
        assert Path(relative).parent.relative_to("backend").as_posix() + "/*.json" in pyproject


def test_checkout_reads_repository_files() -> None:
    assert resources.source_checkout_root() == REPO_ROOT
    assert Path(str(resources.data_file(M350_50A_SPEC.relative_path))) == REPO_ROOT / M350_50A_SPEC.relative_path
    assert resources.stamped_build_info() is None


def _load_setup():
    spec = importlib.util.spec_from_file_location("coilem_setup", REPO_ROOT / "setup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def installed(tmp_path: Path, monkeypatch) -> Path:
    """Stage a package as a wheel build does, then resolve files as if installed there."""

    bundle = tmp_path / "ui-build"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<!doctype html>")
    (bundle / "assets" / "index-AbCd1234.js").write_text("export {};")
    binary = tmp_path / "magneto2d-build"
    binary.write_bytes(b"\x7fELF not really")
    monkeypatch.setenv("COILEM_BUILD_UI_DIST", str(bundle))
    monkeypatch.setenv("COILEM_BUILD_MAGNETO2D_BINARY", str(binary))
    monkeypatch.setenv("COILEM_BUILD_COMMIT", "1" * 40)
    package = tmp_path / "site-packages" / "backend"
    _load_setup().stage_runtime_files(package, "0.2.0")
    for name in ("COILEM_BUILD_UI_DIST", "COILEM_BUILD_MAGNETO2D_BINARY", "COILEM_BUILD_COMMIT", "COILEM_MAGNETO2D_BINARY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(resources.resources, "files", lambda name: package)
    monkeypatch.setattr(resources, "source_checkout_root", lambda: None)
    return package


def test_installed_package_resolves_every_runtime_file(installed: Path) -> None:
    for relative in resources.PACKAGED_DATA_FILES:
        assert (installed / "_data" / relative).read_bytes() == (REPO_ROOT / relative).read_bytes()
    curve = load_electrical_steel_curve("M350-50A")
    assert curve.sha256 == M350_50A_SPEC.sha256
    assert Path(str(curve.path)) == installed / "_data" / M350_50A_SPEC.relative_path
    assert resources.read_data_json("schemas/v1/magnetostatic_problem.schema.json")["type"] == "object"
    assert resources.ui_bundle_root() == installed / "_ui"
    executable = installed / "_bin" / adapter.MAGNETO2D_EXECUTABLE_NAME
    assert adapter.ensure_magneto2d_binary() == executable
    if os.name != "nt":
        assert os.access(executable, os.X_OK)


def test_build_identity_is_stamped_and_env_still_overrides(installed: Path, monkeypatch) -> None:
    info = json.loads((installed / "_build_info.json").read_text())
    assert info["application_version"] == "0.2.0"
    assert info["application_commit"] == "1" * 40
    assert len(info["magneto2d_sha256"]) == len(info["ui_bundle_sha256"]) == 64
    assert resources.application_commit() == "1" * 40
    monkeypatch.setenv("COILEM_BUILD_COMMIT", "2" * 40)
    assert resources.application_commit() == "2" * 40


def test_binary_override_comes_first(installed: Path, monkeypatch, tmp_path: Path) -> None:
    override = tmp_path / "custom-magneto2d"
    override.write_bytes(b"binary")
    monkeypatch.setenv("COILEM_MAGNETO2D_BINARY", str(override))
    assert adapter.ensure_magneto2d_binary() == override.resolve()
    monkeypatch.setenv("COILEM_MAGNETO2D_BINARY", str(tmp_path / "missing"))
    with pytest.raises(adapter.Magneto2DExecutionError, match="COILEM_MAGNETO2D_BINARY"):
        adapter.ensure_magneto2d_binary()


def test_installation_without_packaged_files_fails_clearly(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("COILEM_MAGNETO2D_BINARY", raising=False)
    monkeypatch.setattr(resources.resources, "files", lambda name: tmp_path)
    monkeypatch.setattr(resources, "source_checkout_root", lambda: None)
    monkeypatch.setattr(adapter, "MAGNETO2D_MANIFEST", tmp_path / "Cargo.toml")
    with pytest.raises(FileNotFoundError, match="missing from this installation"):
        resources.data_file(M350_50A_SPEC.relative_path)
    with pytest.raises(adapter.Magneto2DExecutionError, match="does not include the Magneto2D solver"):
        adapter.ensure_magneto2d_binary()
    assert resources.ui_bundle_root() is None


def test_build_rejects_data_that_differs_from_the_snapshot_manifest(monkeypatch, tmp_path: Path) -> None:
    setup_module = _load_setup()
    shutil.copy(REPO_ROOT / "snapshot-manifest.json", tmp_path / "snapshot-manifest.json")
    for relative in (*resources.PACKAGED_DATA_FILES, *resources.PACKAGE_DATA_FILES):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, tmp_path / relative)
    monkeypatch.setattr(setup_module, "ROOT", tmp_path)
    setup_module._check_packaged_sources()
    with (tmp_path / M350_50A_SPEC.relative_path).open("a") as curve:
        curve.write("# edited\n")
    with pytest.raises(SystemExit, match="M350-50A.csv differs from its snapshot-manifest.json entry"):
        setup_module._check_packaged_sources()
