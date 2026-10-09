"""The exported application must be independent of inherited numerical flags."""

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend import magneto2d_adapter as adapter
from backend import solver_environment as policy
from backend.gmsh_mesh_rotation import gmsh_mesh_reuse_enabled
from backend.models import MotorConfig

ROOT = Path(__file__).resolve().parents[1]


def config():
    return MotorConfig.model_validate(json.loads((ROOT / "tests/fixtures/spm_4p12s_simple.json").read_text()))


def test_public_policy_is_fixed_and_filters_shell_settings(monkeypatch):
    assert policy.ISOLATED_RUNTIME is True
    monkeypatch.setenv("COILEM_MAGNET_BR_SCALE", "0")
    monkeypatch.setenv("MAGNETO2D_NONLINEAR_TOL", "0.99")
    monkeypatch.setenv("COILEM_MAGNETO2D_GMSH_MESH_REUSE", "0")
    monkeypatch.setenv("RAYON_NUM_THREADS", "1")
    monkeypatch.setenv("LD_PRELOAD", "/untrusted/library")
    monkeypatch.setenv("UNRELATED_CREDENTIAL", "do-not-export")
    monkeypatch.setenv("SystemRoot", "test-windows-root")
    child = policy.solver_process_environment({"COILEM_MAGNET_BR_SCALE": "1"})
    assert child["COILEM_MAGNET_BR_SCALE"] == "1"
    assert child["SystemRoot"] == "test-windows-root"
    assert not {"MAGNETO2D_NONLINEAR_TOL", "RAYON_NUM_THREADS", "LD_PRELOAD", "UNRELATED_CREDENTIAL"} & child.keys()
    assert gmsh_mesh_reuse_enabled()


@pytest.mark.parametrize("batch", [False, True])
def test_same_request_ignores_magnet_override_and_retains_policy(monkeypatch, tmp_path, batch):
    observed = []

    def runner(command, **kwargs):
        request = json.loads(Path(command[1]).read_text())
        observed.append((request, {k: v for k, v in kwargs["env"].items()
                                   if k != "MAGNETO2D_NONLINEAR_DIAGNOSTICS_PATH"}))
        output = Path(command[command.index("-o") + 1])
        output.write_text(json.dumps({"reports": [{}]} if batch else {}))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(adapter.subprocess, "run", runner)
    monkeypatch.setattr(adapter, "ensure_magneto2d_binary", lambda: Path("unused"))
    for index, value in enumerate(["1", "0"]):
        monkeypatch.setenv("COILEM_MAGNET_BR_SCALE", value)
        monkeypatch.setenv("MAGNETO2D_NONLINEAR_RELAX", value)
        directory = tmp_path / str(index)
        if batch:
            result = adapter.run_magneto2d_batch_reports(
                config(), [{"solve_mesh_artifact": {}, "rotor_angle_deg": 0}],
                runner=runner, persist_artifacts_dir=directory,
            )[0]
        else:
            result = adapter.run_magneto2d_report(
                config(), sweep=False, solve_mesh_artifact={}, runner=runner, persist_artifacts_dir=directory,
            )
        assert result["solver_environment"]["policy"] == "request-only-v1"
        retained = json.loads(next(directory.glob("*_report.json")).read_text())
        if batch:
            retained = retained["reports"][0]
        assert retained["solver_environment"] == result["solver_environment"]
    assert observed[0] == observed[1]
    assert "COILEM_MAGNET_BR_SCALE" not in observed[0][1]
    assert "MAGNETO2D_NONLINEAR_RELAX" not in observed[0][1]
    assert "solver_environment" in observed[0][0]["openem_provenance"]


def test_request_derived_armature_switch_still_works():
    motor = config()
    motor.solve_params.field_composition_source = "armature"
    overrides = adapter._magneto2d_env_overrides(motor)
    assert overrides["COILEM_MAGNET_BR_SCALE"] == "0"
    assert policy.solver_process_environment(overrides)["COILEM_MAGNET_BR_SCALE"] == "0"


def test_direct_model_rejects_excluded_thermal_without_import_error():
    raw = config().model_dump(mode="json")
    raw["solve_params"]["magnet_temperature_C"] = 80
    with pytest.raises(ValidationError, match="not supported"):
        MotorConfig.model_validate(raw)


def test_inherited_shaft_override_does_not_change_geometry(monkeypatch):
    from backend.geometry_ir import build_geometry_ir

    monkeypatch.delenv("COILEM_SHAFT_MATERIAL", raising=False)
    expected = build_geometry_ir(config())
    monkeypatch.setenv("COILEM_SHAFT_MATERIAL", "rotor_steel")
    actual = build_geometry_ir(config())
    assert actual == expected
    assert all(region.material_key == "air" for region in actual.regions if region.kind == "Shaft")


def test_user_gmsh_options_do_not_change_motor_mesh(tmp_path):
    import os
    import sys

    script = '''
import hashlib
import json
from pathlib import Path
from backend.gmsh_solver import run_gmsh_mesh_preview
from backend.models import MotorConfig
raw = json.loads(Path("tests/fixtures/spm_4p12s_simple.json").read_text())
raw["solve_params"]["mesh_density"] = "coarse"
mesh = run_gmsh_mesh_preview(MotorConfig.model_validate(raw))
physical = {key: mesh[key] for key in ("nodes_mm", "triangles", "element_region_ids")}
print(hashlib.sha256(json.dumps(physical, sort_keys=True).encode()).hexdigest())
'''
    fingerprints = []
    for name, options in [("clean", ""), ("custom", "Mesh.ElementOrder = 2;\nMesh.MeshSizeFactor = 1.7;\n")]:
        home = tmp_path / name
        home.mkdir()
        # Gmsh chooses the prefixed form on Unix and the plain form on Windows.
        for filename in ("gmshrc", ".gmshrc", "gmsh-options", ".gmsh-options"):
            (home / filename).write_text(options)
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT,
            env={**os.environ, "GMSH_HOME": str(home)},
            capture_output=True, text=True, check=False, timeout=60,
        )
        assert completed.returncode == 0, f"{name}: {completed.stderr}"
        fingerprints.append(completed.stdout.strip())
    assert fingerprints[0] == fingerprints[1]
