"""The exported application must be independent of inherited numerical flags."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

import backend.solver as solver
from backend import magneto2d_adapter as adapter
from backend import public_field_playback as playback
from backend import solver_environment as policy
from backend.gmsh_mesh_rotation import gmsh_mesh_reuse_enabled
from backend.models import MotorConfig

ROOT = Path(__file__).resolve().parents[1]
POOL_SWITCHES = (
    "COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL",
    "COILEM_MAGNETO2D_ALLOW_MESH_PROCESS_POOL",
    "COILEM_MAGNETO2D_ALLOW_PLAYBACK_PROCESS_POOL",
    "COILEM_MAGNETO2D_ALLOW_FIELD_FRAME_PROCESS_POOL",
)


@pytest.fixture(autouse=True)
def clean_process_pool_switches(monkeypatch):
    for name in POOL_SWITCHES:
        monkeypatch.delenv(name, raising=False)


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
    # Windows uppercases os.environ keys; Unix preserves their spelling.
    assert {key.upper(): value for key, value in child.items()}["SYSTEMROOT"] == "test-windows-root"
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
        for name in POOL_SWITCHES:
            monkeypatch.setenv(name, value)
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
    assert not set(POOL_SWITCHES) & observed[0][1].keys()


@pytest.mark.parametrize("value", ["0", " FALSE ", "No", "off"])
def test_installed_app_can_disable_all_python_pools(monkeypatch, value):
    assert policy.ISOLATED_RUNTIME is True
    monkeypatch.setenv(POOL_SWITCHES[0], value)
    assert not solver._magneto2d_python_process_pool_enabled()
    assert solver._field_preview_worker_count(48, 8) == 1
    assert solver._gmsh_pipeline_worker_count("COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS", 48, uses_process_pool=True) == 1
    with playback._playback_executor(48) as executor:
        assert isinstance(executor, ThreadPoolExecutor)


def test_installed_mesh_off_switch_keeps_playback_enabled(monkeypatch):
    monkeypatch.setenv(POOL_SWITCHES[1], "0")
    assert not solver._gmsh_mesh_process_pool_enabled()
    assert solver._playback_process_pool_enabled()
    assert solver._gmsh_pipeline_worker_count("COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS", 48, uses_process_pool=True) == 1


def test_installed_playback_off_switch_keeps_mesh_enabled(monkeypatch):
    monkeypatch.setenv(POOL_SWITCHES[2], "0")
    assert solver._gmsh_mesh_process_pool_enabled()
    assert not solver._playback_process_pool_enabled()
    with playback._playback_executor(48) as executor:
        assert isinstance(executor, ThreadPoolExecutor)


@pytest.mark.parametrize("value", ["1", "true", "invalid", ""])
def test_installed_enable_values_preserve_approved_worker_defaults(monkeypatch, value):
    for name in POOL_SWITCHES:
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(solver.os, "cpu_count", lambda: 16)
    monkeypatch.setenv("COILEM_MAGNETO2D_FIELD_PREVIEW_WORKERS", "1")
    assert solver._magneto2d_python_process_pool_enabled()
    assert solver._field_preview_worker_count(48, 8) == 8
    assert solver._gmsh_pipeline_worker_count("COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS", 48, uses_process_pool=True) == 8
    assert solver._playback_process_pool_enabled()
    assert policy.solver_setting(POOL_SWITCHES[0]) is None


def test_installed_shared_off_switch_overrides_specific_enable_values(monkeypatch):
    monkeypatch.setenv(POOL_SWITCHES[0], "0")
    monkeypatch.setenv(POOL_SWITCHES[1], "1")
    monkeypatch.setenv(POOL_SWITCHES[2], "1")
    assert not solver._gmsh_mesh_process_pool_enabled()
    assert not solver._playback_process_pool_enabled()


def test_fresh_isolated_backend_honors_off_switch_without_policy_patch():
    script = '''
import json
from concurrent.futures import ThreadPoolExecutor
import backend.solver as solver
from backend import solver_environment as policy
from backend.public_field_playback import _playback_executor
from backend.gmsh_mesh_rotation import gmsh_mesh_reuse_enabled
with _playback_executor(48) as executor:
    print(json.dumps({
        "isolated": policy.ISOLATED_RUNTIME,
        "mesh_workers": solver._gmsh_pipeline_worker_count("COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS", 48, uses_process_pool=True),
        "playback_threads": isinstance(executor, ThreadPoolExecutor),
        "field_workers": solver._field_preview_worker_count(48, 8),
        "mesh_reuse": gmsh_mesh_reuse_enabled(),
        "numerical_override": policy.solver_setting("MAGNETO2D_NONLINEAR_TOL"),
        "native_switch_forwarded": "COILEM_MAGNETO2D_ALLOW_PY_PROCESS_POOL" in policy.solver_process_environment(),
    }))
'''
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
        env={**os.environ, POOL_SWITCHES[0]: "0", POOL_SWITCHES[1]: "1", POOL_SWITCHES[2]: "1",
             "COILEM_MAGNETO2D_GMSH_MESH_REUSE": "0", "MAGNETO2D_NONLINEAR_TOL": "0.99"},
    )
    assert json.loads(completed.stdout) == {
        "isolated": True, "mesh_workers": 1, "playback_threads": True, "field_workers": 1,
        "mesh_reuse": True, "numerical_override": None, "native_switch_forwarded": False,
    }


def test_request_derived_armature_switch_still_works():
    motor = config()
    motor.solve_params.field_composition_source = "armature"
    overrides = adapter._magneto2d_env_overrides(motor)
    assert overrides["COILEM_MAGNET_BR_SCALE"] == "0"
    assert policy.solver_process_environment(overrides)["COILEM_MAGNET_BR_SCALE"] == "0"


def test_direct_model_takes_a_magnet_temperature_only_with_cited_coefficients():
    raw = config().model_dump(mode="json")
    raw["solve_params"]["magnet_temperature_C"] = 80
    assert MotorConfig.model_validate(raw).solve_params.magnet_temperature_C == 80
    raw["materials"]["magnet_grade"] = "Ferrite_Y30"
    with pytest.raises(ValidationError, match="No cited temperature coefficients"):
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
